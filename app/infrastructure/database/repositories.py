from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError

from .models import (
    AdminSession,
    AdminUser,
    Document,
    EvaluationJob,
    IngestionJob,
    WorkerHeartbeat,
)
from .session import SessionFactory


def utc_now() -> datetime:
    return datetime.now(UTC)


class AdminRepository:
    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    def get_user_by_username(self, username: str) -> AdminUser | None:
        with self._session_factory() as session:
            return session.scalar(select(AdminUser).where(AdminUser.username == username))

    def ensure_user(self, *, username: str, password_hash: str) -> AdminUser:
        existing = self.get_user_by_username(username)
        if existing is not None:
            return existing
        try:
            with self._session_factory() as session, session.begin():
                user = AdminUser(
                    id=str(uuid.uuid4()),
                    username=username,
                    password_hash=password_hash,
                )
                session.add(user)
            return user
        except IntegrityError:
            existing = self.get_user_by_username(username)
            if existing is None:
                raise
            return existing

    def update_password_hash(self, user_id: str, password_hash: str) -> None:
        with self._session_factory() as session, session.begin():
            user = session.get(AdminUser, user_id)
            if user is not None:
                user.password_hash = password_hash

    def record_login(self, user_id: str) -> None:
        with self._session_factory() as session, session.begin():
            user = session.get(AdminUser, user_id)
            if user is not None:
                user.last_login_at = utc_now()

    def create_session(
        self,
        *,
        user_id: str,
        token_digest: str,
        expires_at: datetime,
    ) -> AdminSession:
        with self._session_factory() as session, session.begin():
            admin_session = AdminSession(
                id=str(uuid.uuid4()),
                token_digest=token_digest,
                admin_user_id=user_id,
                expires_at=expires_at,
            )
            session.add(admin_session)
        return admin_session

    def resolve_session(self, token_digest: str) -> tuple[AdminUser, AdminSession] | None:
        now = utc_now()
        with self._session_factory() as session, session.begin():
            row = session.execute(
                select(AdminUser, AdminSession)
                .join(AdminSession, AdminSession.admin_user_id == AdminUser.id)
                .where(
                    AdminSession.token_digest == token_digest,
                    AdminSession.revoked_at.is_(None),
                    AdminSession.expires_at > now,
                    AdminUser.is_active.is_(True),
                )
            ).first()
            if row is None:
                return None
            user, admin_session = row._tuple()
            admin_session.last_seen_at = now
            return user, admin_session

    def revoke_session(self, token_digest: str) -> None:
        with self._session_factory() as session, session.begin():
            admin_session = session.scalar(
                select(AdminSession).where(AdminSession.token_digest == token_digest)
            )
            if admin_session is not None and admin_session.revoked_at is None:
                admin_session.revoked_at = utc_now()


class ManagementRepository:
    """Transactional repository for documents, jobs, and dashboard aggregates."""

    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    def find_document_upload(self, idempotency_key: str) -> tuple[Document, IngestionJob] | None:
        with self._session_factory() as session:
            document = session.scalar(
                select(Document).where(Document.idempotency_key == idempotency_key)
            )
            if document is None:
                return None
            job = session.scalar(
                select(IngestionJob)
                .where(IngestionJob.document_id == document.id)
                .order_by(IngestionJob.created_at.desc(), IngestionJob.id.desc())
                .limit(1)
            )
            if job is None:
                return None
            return document, job

    def create_document_with_job(
        self,
        *,
        document_values: Mapping[str, Any],
        max_attempts: int,
    ) -> tuple[Document, IngestionJob, bool]:
        document = Document(**dict(document_values))
        job = IngestionJob(
            id=str(uuid.uuid4()),
            document_id=document.id,
            status="queued",
            stage="fetch",
            progress=0,
            max_attempts=max_attempts,
        )
        try:
            with self._session_factory() as session, session.begin():
                session.add(document)
                session.add(job)
                document.status = "queued"
            return document, job, True
        except IntegrityError:
            existing = self.find_document_upload(document.idempotency_key)
            if existing is None:
                raise
            return existing[0], existing[1], False

    def list_documents(self, *, limit: int, offset: int) -> tuple[list[Document], int]:
        with self._session_factory() as session:
            total = int(session.scalar(select(func.count()).select_from(Document)) or 0)
            items = list(
                session.scalars(
                    select(Document)
                    .order_by(Document.created_at.desc(), Document.id.desc())
                    .offset(offset)
                    .limit(limit)
                )
            )
            return items, total

    def get_latest_ingestion_jobs(self, document_ids: Sequence[str]) -> dict[str, IngestionJob]:
        unique_document_ids = tuple(dict.fromkeys(document_ids))
        if not unique_document_ids:
            return {}

        latest_rank = (
            func.row_number()
            .over(
                partition_by=IngestionJob.document_id,
                order_by=(IngestionJob.created_at.desc(), IngestionJob.id.desc()),
            )
            .label("latest_rank")
        )
        ranked_jobs = (
            select(IngestionJob.id.label("job_id"), latest_rank)
            .where(IngestionJob.document_id.in_(unique_document_ids))
            .subquery()
        )
        with self._session_factory() as session:
            jobs = session.scalars(
                select(IngestionJob)
                .join(ranked_jobs, ranked_jobs.c.job_id == IngestionJob.id)
                .where(ranked_jobs.c.latest_rank == 1)
            )
            return {job.document_id: job for job in jobs}

    def get_document(self, document_id: str) -> Document | None:
        with self._session_factory() as session:
            return session.get(Document, document_id)

    def get_ingestion_job(self, job_id: str) -> IngestionJob | None:
        with self._session_factory() as session:
            return session.get(IngestionJob, job_id)

    def retry_ingestion_job(self, job_id: str) -> IngestionJob | None:
        with self._session_factory() as session, session.begin():
            job = session.get(IngestionJob, job_id)
            if job is None:
                return None
            if job.status not in {"failed", "canceled"}:
                raise ValueError("Only failed or canceled jobs can be retried")
            job.status = "queued"
            job.stage = "fetch"
            job.progress = 0
            job.lease_owner = None
            job.lease_expires_at = None
            job.heartbeat_at = None
            job.next_attempt_at = utc_now()
            job.cancel_requested_at = None
            job.error_code = None
            job.error_message = None
            job.finished_at = None
            document = session.get(Document, job.document_id)
            if document is not None:
                document.status = "queued"
            return job

    def request_ingestion_cancel(self, job_id: str) -> IngestionJob | None:
        now = utc_now()
        with self._session_factory() as session, session.begin():
            job = session.get(IngestionJob, job_id)
            if job is None:
                return None
            if job.status in {"succeeded", "failed", "canceled"}:
                return job
            job.cancel_requested_at = now
            if job.status in {"queued", "retry_wait"}:
                job.status = "canceled"
                job.finished_at = now
                job.progress = 0
                document = session.get(Document, job.document_id)
                if document is not None:
                    document.status = "canceled"
            return job

    def claim_ingestion_job(
        self,
        *,
        worker_id: str,
        lease_seconds: int,
    ) -> IngestionJob | None:
        now = utc_now()
        claimable = or_(
            IngestionJob.status.in_(("queued", "retry_wait")),
            (IngestionJob.status == "running") & (IngestionJob.lease_expires_at < now),
        )
        with self._session_factory() as session, session.begin():
            job = session.scalar(
                select(IngestionJob)
                .where(
                    claimable,
                    IngestionJob.next_attempt_at <= now,
                    IngestionJob.cancel_requested_at.is_(None),
                )
                .order_by(IngestionJob.next_attempt_at, IngestionJob.created_at)
                .with_for_update(skip_locked=True)
                .limit(1)
            )
            if job is None:
                return None
            job.status = "running"
            job.attempts += 1
            job.lease_owner = worker_id
            job.lease_expires_at = now + timedelta(seconds=lease_seconds)
            job.heartbeat_at = now
            job.started_at = job.started_at or now
            job.finished_at = None
            document = session.get(Document, job.document_id)
            if document is not None:
                document.status = "processing"
            return job

    def heartbeat_ingestion_job(
        self,
        *,
        job_id: str,
        worker_id: str,
        lease_seconds: int,
    ) -> bool:
        now = utc_now()
        with self._session_factory() as session, session.begin():
            job = session.get(IngestionJob, job_id)
            if job is None or job.status != "running" or job.lease_owner != worker_id:
                return False
            job.heartbeat_at = now
            job.lease_expires_at = now + timedelta(seconds=lease_seconds)
            return True

    def set_ingestion_stage(
        self,
        *,
        job_id: str,
        worker_id: str,
        stage: str,
        progress: int,
    ) -> bool:
        with self._session_factory() as session, session.begin():
            job = session.get(IngestionJob, job_id)
            if job is None or job.status != "running" or job.lease_owner != worker_id:
                return False
            job.stage = stage
            job.progress = progress
            return True

    def ingestion_cancel_requested(self, job_id: str, worker_id: str) -> bool:
        with self._session_factory() as session:
            job = session.get(IngestionJob, job_id)
            return bool(
                job is None
                or job.lease_owner != worker_id
                or job.cancel_requested_at is not None
                or job.status != "running"
            )

    def complete_ingestion_job(
        self,
        *,
        job_id: str,
        worker_id: str,
        inserted_parents: int,
        inserted_children: int,
    ) -> bool:
        now = utc_now()
        with self._session_factory() as session, session.begin():
            job = session.get(IngestionJob, job_id)
            if job is None or job.status != "running" or job.lease_owner != worker_id:
                return False
            # Cancellation is best-effort. Once the Qdrant upsert completed, finalize
            # the immutable version rather than exposing partially indexed points.
            job.cancel_requested_at = None
            job.status = "succeeded"
            job.stage = "finalize"
            job.progress = 100
            job.inserted_parents = inserted_parents
            job.inserted_children = inserted_children
            job.finished_at = now
            job.lease_owner = None
            job.lease_expires_at = None
            job.error_code = None
            job.error_message = None
            document = session.get(Document, job.document_id)
            if document is not None:
                document.status = "active"
                document.indexed_at = now
            return True

    def cancel_running_ingestion_job(self, *, job_id: str, worker_id: str) -> bool:
        now = utc_now()
        with self._session_factory() as session, session.begin():
            job = session.get(IngestionJob, job_id)
            if job is None or job.status != "running" or job.lease_owner != worker_id:
                return False
            job.status = "canceled"
            job.finished_at = now
            job.lease_owner = None
            job.lease_expires_at = None
            document = session.get(Document, job.document_id)
            if document is not None:
                document.status = "canceled"
            return True

    def fail_ingestion_job(
        self,
        *,
        job_id: str,
        worker_id: str,
        error_code: str,
        error_message: str,
        retryable: bool,
        retry_delay_seconds: int,
    ) -> bool:
        now = utc_now()
        with self._session_factory() as session, session.begin():
            job = session.get(IngestionJob, job_id)
            if job is None or job.status != "running" or job.lease_owner != worker_id:
                return False
            can_retry = retryable and job.attempts < job.max_attempts
            job.status = "retry_wait" if can_retry else "failed"
            job.next_attempt_at = now + timedelta(seconds=retry_delay_seconds)
            job.finished_at = None if can_retry else now
            job.lease_owner = None
            job.lease_expires_at = None
            job.error_code = error_code[:128]
            job.error_message = error_message[:500]
            document = session.get(Document, job.document_id)
            if document is not None:
                document.status = "queued" if can_retry else "failed"
            return True

    def create_evaluation_job(
        self,
        *,
        name: str,
        suite: str,
        requested_by_id: str,
        max_attempts: int,
    ) -> EvaluationJob:
        with self._session_factory() as session, session.begin():
            job = EvaluationJob(
                id=str(uuid.uuid4()),
                name=name,
                suite=suite,
                requested_by_id=requested_by_id,
                max_attempts=max_attempts,
            )
            session.add(job)
        return job

    def list_evaluation_jobs(self, *, limit: int, offset: int) -> tuple[list[EvaluationJob], int]:
        with self._session_factory() as session:
            total = int(session.scalar(select(func.count()).select_from(EvaluationJob)) or 0)
            items = list(
                session.scalars(
                    select(EvaluationJob)
                    .order_by(EvaluationJob.created_at.desc(), EvaluationJob.id.desc())
                    .offset(offset)
                    .limit(limit)
                )
            )
            return items, total

    def get_evaluation_job(self, job_id: str) -> EvaluationJob | None:
        with self._session_factory() as session:
            return session.get(EvaluationJob, job_id)

    def evaluation_summary(
        self,
    ) -> tuple[int, dict[str, int], dict[str, float], datetime | None]:
        with self._session_factory() as session:
            rows = session.execute(
                select(EvaluationJob.status, func.count()).group_by(EvaluationJob.status)
            ).all()
            counts = {str(status): int(count) for status, count in rows}
            total = sum(counts.values())
            latest = session.scalar(
                select(EvaluationJob)
                .where(EvaluationJob.status == "succeeded")
                .order_by(EvaluationJob.finished_at.desc())
                .limit(1)
            )
            if latest is None:
                return total, counts, {}, None
            metrics = {
                str(key): float(value)
                for key, value in latest.aggregate_metrics.items()
                if isinstance(value, int | float)
            }
            return total, counts, metrics, latest.finished_at

    def claim_evaluation_job(
        self,
        *,
        worker_id: str,
        lease_seconds: int,
    ) -> EvaluationJob | None:
        now = utc_now()
        claimable = or_(
            EvaluationJob.status.in_(("queued", "retry_wait")),
            (EvaluationJob.status == "running") & (EvaluationJob.lease_expires_at < now),
        )
        with self._session_factory() as session, session.begin():
            job = session.scalar(
                select(EvaluationJob)
                .where(
                    claimable,
                    EvaluationJob.next_attempt_at <= now,
                    EvaluationJob.cancel_requested_at.is_(None),
                )
                .order_by(EvaluationJob.next_attempt_at, EvaluationJob.created_at)
                .with_for_update(skip_locked=True)
                .limit(1)
            )
            if job is None:
                return None
            job.status = "running"
            job.attempts += 1
            job.lease_owner = worker_id
            job.lease_expires_at = now + timedelta(seconds=lease_seconds)
            job.heartbeat_at = now
            job.started_at = job.started_at or now
            return job

    def heartbeat_evaluation_job(
        self,
        *,
        job_id: str,
        worker_id: str,
        lease_seconds: int,
    ) -> bool:
        now = utc_now()
        with self._session_factory() as session, session.begin():
            job = session.get(EvaluationJob, job_id)
            if job is None or job.status != "running" or job.lease_owner != worker_id:
                return False
            job.heartbeat_at = now
            job.lease_expires_at = now + timedelta(seconds=lease_seconds)
            return True

    def fail_evaluation_job(
        self,
        *,
        job_id: str,
        worker_id: str,
        error_code: str,
        error_message: str,
        retryable: bool,
        retry_delay_seconds: int,
    ) -> bool:
        now = utc_now()
        with self._session_factory() as session, session.begin():
            job = session.get(EvaluationJob, job_id)
            if job is None or job.status != "running" or job.lease_owner != worker_id:
                return False
            can_retry = retryable and job.attempts < job.max_attempts
            job.status = "retry_wait" if can_retry else "failed"
            job.next_attempt_at = now + timedelta(seconds=retry_delay_seconds)
            job.finished_at = None if can_retry else now
            job.lease_owner = None
            job.lease_expires_at = None
            job.error_code = error_code[:128]
            job.error_message = error_message[:500]
            return True

    def complete_evaluation_job(
        self,
        *,
        job_id: str,
        worker_id: str,
        aggregate_metrics: Mapping[str, float],
        private_result_bucket: str | None = None,
        private_result_object_key: str | None = None,
    ) -> bool:
        now = utc_now()
        with self._session_factory() as session, session.begin():
            job = session.get(EvaluationJob, job_id)
            if job is None or job.status != "running" or job.lease_owner != worker_id:
                return False
            job.status = "succeeded"
            job.progress = 100
            job.aggregate_metrics = dict(aggregate_metrics)
            job.private_result_bucket = private_result_bucket
            job.private_result_object_key = private_result_object_key
            job.finished_at = now
            job.lease_owner = None
            job.lease_expires_at = None
            return True

    def heartbeat_worker(
        self,
        *,
        worker_id: str,
        status: str,
        metadata: Mapping[str, Any] | None = None,
    ) -> None:
        now = utc_now()
        with self._session_factory() as session, session.begin():
            heartbeat = session.get(WorkerHeartbeat, worker_id)
            if heartbeat is None:
                heartbeat = WorkerHeartbeat(
                    worker_id=worker_id,
                    status=status,
                    metadata_json=dict(metadata or {}),
                )
                session.add(heartbeat)
            else:
                heartbeat.heartbeat_at = now
                heartbeat.status = status
                heartbeat.metadata_json = dict(metadata or heartbeat.metadata_json)
