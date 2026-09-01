from __future__ import annotations

import hashlib
import secrets
import uuid
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from app.infrastructure.database.models import (
    AdminSession,
    AdminUser,
    Document,
    EvaluationJob,
    IngestionJob,
)
from app.infrastructure.database.repositories import AdminRepository, ManagementRepository
from app.infrastructure.object_storage.ports import ObjectStorage

from .errors import AdminConflict, AdminNotFound, AuthenticationFailed, UploadRejected
from .schemas import (
    AdminSessionResponse,
    AdminUserResponse,
    DocumentListResponse,
    DocumentResponse,
    DocumentUploadResponse,
    EvaluationJobResponse,
    EvaluationListResponse,
    EvaluationSummaryResponse,
    IngestionJobResponse,
)

_ALLOWED_UPLOADS: dict[str, frozenset[str]] = {
    ".pdf": frozenset({"application/pdf", "application/octet-stream"}),
    ".txt": frozenset({"text/plain", "application/octet-stream"}),
    ".md": frozenset({"text/markdown", "text/plain", "application/octet-stream"}),
}


@dataclass(frozen=True, slots=True)
class LoginGrant:
    token: str
    session: AdminSessionResponse


class AdminService:
    def __init__(
        self,
        *,
        admin_repository: AdminRepository,
        management_repository: ManagementRepository,
        object_storage: ObjectStorage,
        object_bucket: str,
        session_ttl_seconds: int,
        cookie_name: str,
        cookie_secure: bool,
        max_upload_bytes: int,
        ingestion_max_attempts: int,
        evaluation_max_attempts: int,
        parser_version: str,
        chunker_version: str,
        embedder_version: str,
        index_version: str,
        password_hasher: PasswordHasher | None = None,
    ) -> None:
        self._admins = admin_repository
        self._management = management_repository
        self._objects = object_storage
        self._object_bucket = object_bucket
        self._session_ttl_seconds = session_ttl_seconds
        self.cookie_name = cookie_name
        self.cookie_secure = cookie_secure
        self.cookie_max_age = session_ttl_seconds
        self.max_upload_bytes = max_upload_bytes
        self._ingestion_max_attempts = ingestion_max_attempts
        self._evaluation_max_attempts = evaluation_max_attempts
        self._parser_version = parser_version
        self._chunker_version = chunker_version
        self._embedder_version = embedder_version
        self._index_version = index_version
        self._passwords = password_hasher or PasswordHasher()

    def ensure_bootstrap_user(self, username: str, password: str) -> AdminUser:
        normalized = self._normalize_username(username)
        existing = self._admins.get_user_by_username(normalized)
        if existing is not None:
            return existing
        return self._admins.ensure_user(
            username=normalized,
            password_hash=self._passwords.hash(password),
        )

    def login(self, username: str, password: str) -> LoginGrant:
        normalized = self._normalize_username(username)
        user = self._admins.get_user_by_username(normalized)
        if user is None or not user.is_active:
            raise AuthenticationFailed("Invalid credentials")
        try:
            self._passwords.verify(user.password_hash, password)
        except (InvalidHashError, VerificationError, VerifyMismatchError) as exc:
            raise AuthenticationFailed("Invalid credentials") from exc

        if self._passwords.check_needs_rehash(user.password_hash):
            self._admins.update_password_hash(user.id, self._passwords.hash(password))

        raw_token = secrets.token_urlsafe(32)
        expires_at = datetime.now(UTC) + timedelta(seconds=self._session_ttl_seconds)
        admin_session = self._admins.create_session(
            user_id=user.id,
            token_digest=self._digest_token(raw_token),
            expires_at=expires_at,
        )
        self._admins.record_login(user.id)
        return LoginGrant(
            token=raw_token,
            session=self._session_response(user, admin_session),
        )

    def current_session(self, token: str) -> AdminSessionResponse:
        resolved = self._admins.resolve_session(self._digest_token(token))
        if resolved is None:
            raise AuthenticationFailed("Authentication required")
        return self._session_response(*resolved)

    def logout(self, token: str) -> None:
        if token:
            self._admins.revoke_session(self._digest_token(token))

    def upload_document(
        self,
        *,
        filename: str,
        content_type: str | None,
        data: bytes,
        title: str | None,
        doc_type: str,
        created_by_id: str,
    ) -> DocumentUploadResponse:
        safe_filename, extension, media_type = self._validate_upload(
            filename=filename,
            content_type=content_type,
            data=data,
        )
        normalized_title = (title or Path(safe_filename).stem).strip()
        if not normalized_title or len(normalized_title) > 255:
            raise UploadRejected("Title must contain between 1 and 255 characters")
        if doc_type not in {"literature", "clinical"}:
            raise UploadRejected("Unsupported document type")

        content_sha256 = hashlib.sha256(data).hexdigest()
        pipeline_identity = ":".join(
            (
                content_sha256,
                self._parser_version,
                self._chunker_version,
                self._embedder_version,
                self._index_version,
            )
        )
        idempotency_key = hashlib.sha256(pipeline_identity.encode("utf-8")).hexdigest()
        existing = self._management.find_document_upload(idempotency_key)
        if existing is not None:
            return self._upload_response(*existing, deduplicated=True)

        document_id = str(uuid.uuid4())
        object_key = f"documents/{content_sha256}/{document_id}/source{extension}"
        self._objects.put_bytes(
            bucket=self._object_bucket,
            object_key=object_key,
            data=data,
            content_type=media_type,
            metadata={"document-id": document_id, "content-sha256": content_sha256},
        )
        try:
            document, job, created = self._management.create_document_with_job(
                document_values={
                    "id": document_id,
                    "filename": safe_filename,
                    "title": normalized_title,
                    "doc_type": doc_type,
                    "media_type": media_type,
                    "size_bytes": len(data),
                    "content_sha256": content_sha256,
                    "idempotency_key": idempotency_key,
                    "object_bucket": self._object_bucket,
                    "object_key": object_key,
                    "status": "uploaded",
                    "parser_version": self._parser_version,
                    "chunker_version": self._chunker_version,
                    "embedder_version": self._embedder_version,
                    "index_version": self._index_version,
                    "created_by_id": created_by_id,
                },
                max_attempts=self._ingestion_max_attempts,
            )
        except Exception:
            with suppress(Exception):
                self._objects.delete_object(bucket=self._object_bucket, object_key=object_key)
            raise

        if not created:
            with suppress(Exception):
                self._objects.delete_object(bucket=self._object_bucket, object_key=object_key)
        return self._upload_response(document, job, deduplicated=not created)

    def list_documents(self, *, limit: int, offset: int) -> DocumentListResponse:
        documents, total = self._management.list_documents(limit=limit, offset=offset)
        latest_jobs = self._management.get_latest_ingestion_jobs(
            [document.id for document in documents]
        )
        return DocumentListResponse(
            items=[
                self._document_response(document, latest_jobs.get(document.id))
                for document in documents
            ],
            total=total,
        )

    def get_document(self, document_id: str) -> DocumentResponse:
        document = self._management.get_document(document_id)
        if document is None:
            raise AdminNotFound("Document not found")
        latest_jobs = self._management.get_latest_ingestion_jobs([document.id])
        return self._document_response(document, latest_jobs.get(document.id))

    def get_ingestion_job(self, job_id: str) -> IngestionJobResponse:
        job = self._management.get_ingestion_job(job_id)
        if job is None:
            raise AdminNotFound("Ingestion job not found")
        return self._ingestion_response(job)

    def retry_ingestion_job(self, job_id: str) -> IngestionJobResponse:
        try:
            job = self._management.retry_ingestion_job(job_id)
        except ValueError as exc:
            raise AdminConflict(str(exc)) from exc
        if job is None:
            raise AdminNotFound("Ingestion job not found")
        return self._ingestion_response(job)

    def cancel_ingestion_job(self, job_id: str) -> IngestionJobResponse:
        job = self._management.request_ingestion_cancel(job_id)
        if job is None:
            raise AdminNotFound("Ingestion job not found")
        return self._ingestion_response(job)

    def create_evaluation(
        self,
        *,
        name: str,
        suite: str,
        requested_by_id: str,
    ) -> EvaluationJobResponse:
        normalized_name = name.strip()
        if not normalized_name:
            raise AdminConflict("Evaluation name cannot be empty")
        job = self._management.create_evaluation_job(
            name=normalized_name,
            suite=suite,
            requested_by_id=requested_by_id,
            max_attempts=self._evaluation_max_attempts,
        )
        return self._evaluation_response(job)

    def list_evaluations(self, *, limit: int, offset: int) -> EvaluationListResponse:
        jobs, total = self._management.list_evaluation_jobs(limit=limit, offset=offset)
        return EvaluationListResponse(
            items=[self._evaluation_response(job) for job in jobs], total=total
        )

    def get_evaluation(self, job_id: str) -> EvaluationJobResponse:
        job = self._management.get_evaluation_job(job_id)
        if job is None:
            raise AdminNotFound("Evaluation job not found")
        return self._evaluation_response(job)

    def evaluation_summary(self) -> EvaluationSummaryResponse:
        total, counts, metrics, completed_at = self._management.evaluation_summary()
        return EvaluationSummaryResponse(
            total=total,
            status_counts=counts,
            latest_metrics=metrics,
            latest_completed_at=completed_at,
        )

    def _validate_upload(
        self,
        *,
        filename: str,
        content_type: str | None,
        data: bytes,
    ) -> tuple[str, str, str]:
        safe_filename = filename.replace("\\", "/").rsplit("/", maxsplit=1)[-1].strip()
        if (
            not safe_filename
            or len(safe_filename) > 255
            or any(ord(char) < 32 for char in safe_filename)
        ):
            raise UploadRejected("Invalid filename")
        extension = Path(safe_filename).suffix.casefold()
        allowed_media_types = _ALLOWED_UPLOADS.get(extension)
        if allowed_media_types is None:
            raise UploadRejected("Only PDF, TXT, and Markdown files are supported", status_code=415)
        if not data:
            raise UploadRejected("Uploaded file is empty")
        if len(data) > self.max_upload_bytes:
            raise UploadRejected("Uploaded file exceeds the configured size limit", status_code=413)

        normalized_media_type = (
            (content_type or "application/octet-stream").split(";", 1)[0].strip().casefold()
        )
        if normalized_media_type not in allowed_media_types:
            raise UploadRejected("File extension and media type do not match", status_code=415)

        if extension == ".pdf":
            if not data.startswith(b"%PDF-"):
                raise UploadRejected("Invalid PDF signature", status_code=415)
            canonical_media_type = "application/pdf"
        else:
            if b"\x00" in data:
                raise UploadRejected("Text uploads cannot contain NUL bytes", status_code=415)
            try:
                data.decode("utf-8-sig")
            except UnicodeDecodeError as exc:
                raise UploadRejected("Text uploads must use UTF-8", status_code=415) from exc
            canonical_media_type = "text/markdown" if extension == ".md" else "text/plain"
        return safe_filename, extension, canonical_media_type

    @staticmethod
    def _normalize_username(username: str) -> str:
        return username.strip().casefold()

    @staticmethod
    def _digest_token(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    @staticmethod
    def _session_response(user: AdminUser, session: AdminSession) -> AdminSessionResponse:
        expires_at = session.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)
        return AdminSessionResponse(
            user=AdminUserResponse(id=user.id, username=user.username),
            expires_at=expires_at,
        )

    @classmethod
    def _upload_response(
        cls,
        document: Document,
        job: IngestionJob,
        *,
        deduplicated: bool,
    ) -> DocumentUploadResponse:
        return DocumentUploadResponse(
            document=cls._document_response(document, job),
            ingestion_job=cls._ingestion_response(job),
            deduplicated=deduplicated,
        )

    @classmethod
    def _document_response(
        cls,
        document: Document,
        latest_ingestion_job: IngestionJob | None = None,
    ) -> DocumentResponse:
        return DocumentResponse.model_validate(
            {
                "id": document.id,
                "filename": document.filename,
                "title": document.title,
                "doc_type": document.doc_type,
                "media_type": document.media_type,
                "size_bytes": document.size_bytes,
                "content_sha256": document.content_sha256,
                "status": document.status,
                "created_at": document.created_at,
                "updated_at": document.updated_at,
                "indexed_at": document.indexed_at,
                "latest_ingestion_job": (
                    cls._ingestion_response(latest_ingestion_job)
                    if latest_ingestion_job is not None
                    else None
                ),
            }
        )

    @staticmethod
    def _ingestion_response(job: IngestionJob) -> IngestionJobResponse:
        return IngestionJobResponse.model_validate(
            {
                "id": job.id,
                "document_id": job.document_id,
                "status": job.status,
                "stage": job.stage,
                "progress": job.progress,
                "attempts": job.attempts,
                "max_attempts": job.max_attempts,
                "inserted_parents": job.inserted_parents,
                "inserted_children": job.inserted_children,
                "error_code": job.error_code,
                "error_message": job.error_message,
                "created_at": job.created_at,
                "updated_at": job.updated_at,
                "started_at": job.started_at,
                "finished_at": job.finished_at,
            }
        )

    @staticmethod
    def _evaluation_response(job: EvaluationJob) -> EvaluationJobResponse:
        metrics = {
            str(key): float(value)
            for key, value in job.aggregate_metrics.items()
            if isinstance(value, int | float)
        }
        return EvaluationJobResponse.model_validate(
            {
                "id": job.id,
                "name": job.name,
                "suite": job.suite,
                "status": job.status,
                "progress": job.progress,
                "attempts": job.attempts,
                "max_attempts": job.max_attempts,
                "aggregate_metrics": metrics,
                "error_code": job.error_code,
                "error_message": job.error_message,
                "created_at": job.created_at,
                "updated_at": job.updated_at,
                "started_at": job.started_at,
                "finished_at": job.finished_at,
            }
        )
