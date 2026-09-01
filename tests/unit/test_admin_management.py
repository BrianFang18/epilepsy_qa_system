from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from argon2 import PasswordHasher
from fastapi.testclient import TestClient
from sqlalchemy import delete, event, select

from app.infrastructure.database.models import AdminSession, Base, IngestionJob
from app.infrastructure.database.repositories import AdminRepository, ManagementRepository
from app.infrastructure.database.session import create_database_runtime
from app.main import create_app
from app.modules.admin.errors import AuthenticationFailed, UploadRejected
from app.modules.admin.service import AdminService
from app.worker.runner import WorkerRunner


class MemoryObjectStorage:
    def __init__(self) -> None:
        self.objects: dict[tuple[str, str], bytes] = {}
        self.put_calls = 0

    def put_bytes(
        self,
        *,
        bucket: str,
        object_key: str,
        data: bytes,
        content_type: str,
        metadata: Mapping[str, str] | None = None,
    ) -> None:
        del content_type, metadata
        self.put_calls += 1
        self.objects[(bucket, object_key)] = data

    def download_file(self, *, bucket: str, object_key: str, destination: str) -> None:
        Path(destination).write_bytes(self.objects[(bucket, object_key)])

    def delete_object(self, *, bucket: str, object_key: str) -> None:
        self.objects.pop((bucket, object_key), None)

    def healthcheck(self, bucket: str) -> bool:
        return any(stored_bucket == bucket for stored_bucket, _ in self.objects)


class FakeParser:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def parse_to_chunks(
        self,
        file_path: str,
        doc_id: str,
        title: str | None = None,
        doc_type: str = "literature",
        metadata: dict[str, Any] | None = None,
    ) -> tuple[list[object], list[object]]:
        self.calls.append(
            {
                "file_path": file_path,
                "doc_id": doc_id,
                "title": title,
                "doc_type": doc_type,
                "metadata": metadata,
            }
        )
        assert Path(file_path).read_text(encoding="utf-8")
        return [object()], [object(), object()]


class FakeIndexer:
    def __init__(
        self,
        *,
        activation_failures: int = 0,
        index_failures: int = 0,
        cleanup_fail_on_calls: set[int] | None = None,
    ) -> None:
        self.indexed: list[object] = []
        self.activation_failures = activation_failures
        self.index_failures = index_failures
        self.cleanup_fail_on_calls = cleanup_fail_on_calls or set()
        self.activation_calls: list[dict[str, Any]] = []
        self.cleanup_calls: list[str] = []
        self.on_index: Any = None

    def index_child_chunks(self, chunks: list[Any]) -> int:
        self.indexed.extend(chunks)
        if self.on_index is not None:
            self.on_index()
        if self.index_failures > 0:
            self.index_failures -= 1
            raise RuntimeError("synthetic index failure")
        return len(chunks)

    def activate_managed_document(
        self,
        *,
        managed_document_id: str,
        content_sha256: str,
        expected_points: int,
    ) -> None:
        self.activation_calls.append(
            {
                "managed_document_id": managed_document_id,
                "content_sha256": content_sha256,
                "expected_points": expected_points,
            }
        )
        if self.activation_failures > 0:
            self.activation_failures -= 1
            raise RuntimeError("synthetic activation failure")

    def delete_managed_document(self, *, managed_document_id: str) -> None:
        self.cleanup_calls.append(managed_document_id)
        if len(self.cleanup_calls) in self.cleanup_fail_on_calls:
            raise RuntimeError("synthetic cleanup failure")


@pytest.fixture
def admin_stack(tmp_path: Path):
    engine, session_factory = create_database_runtime(f"sqlite:///{tmp_path / 'admin.db'}")
    Base.metadata.create_all(engine)
    admins = AdminRepository(session_factory)
    management = ManagementRepository(session_factory)
    objects = MemoryObjectStorage()
    service = AdminService(
        admin_repository=admins,
        management_repository=management,
        object_storage=objects,
        object_bucket="documents",
        session_ttl_seconds=1800,
        cookie_name="test_admin_session",
        cookie_secure=False,
        max_upload_bytes=1024,
        ingestion_max_attempts=3,
        evaluation_max_attempts=2,
        parser_version="parser-v1",
        chunker_version="chunker-v1",
        embedder_version="embedder-v1",
        index_version="index-v1",
        password_hasher=PasswordHasher(time_cost=1, memory_cost=1024, parallelism=1),
    )
    user = service.ensure_bootstrap_user("admin", "test-password-123")
    stack = SimpleNamespace(
        engine=engine,
        session_factory=session_factory,
        admins=admins,
        management=management,
        objects=objects,
        service=service,
        user=user,
    )
    try:
        yield stack
    finally:
        engine.dispose()


def _upload(stack: SimpleNamespace, content: bytes, *, filename: str = "guide.txt"):
    return stack.service.upload_document(
        filename=filename,
        content_type="text/plain",
        data=content,
        title="Epilepsy guide",
        doc_type="literature",
        created_by_id=stack.user.id,
    )


def test_admin_session_stores_only_token_digest(admin_stack: SimpleNamespace) -> None:
    with pytest.raises(AuthenticationFailed, match="Invalid credentials"):
        admin_stack.service.login("admin", "wrong-password")

    grant = admin_stack.service.login("ADMIN", "test-password-123")
    assert grant.session.user.username == "admin"
    assert admin_stack.service.current_session(grant.token).user.id == admin_stack.user.id

    with admin_stack.session_factory() as database_session:
        stored = database_session.scalar(select(AdminSession))
        assert stored is not None
        assert stored.token_digest != grant.token
        assert len(stored.token_digest) == 64

    admin_stack.service.logout(grant.token)
    with pytest.raises(AuthenticationFailed, match="Authentication required"):
        admin_stack.service.current_session(grant.token)


def test_upload_validation_and_pipeline_idempotency(admin_stack: SimpleNamespace) -> None:
    content = "癫痫诊疗资料，供本地检索演示。".encode()
    first = _upload(admin_stack, content)
    duplicate = _upload(admin_stack, content, filename="renamed.txt")

    assert first.deduplicated is False
    assert duplicate.deduplicated is True
    assert duplicate.document.id == first.document.id
    assert duplicate.ingestion_job.id == first.ingestion_job.id
    assert admin_stack.objects.put_calls == 1
    assert first.document.content_sha256 not in first.document.filename
    assert first.ingestion_job.status == "queued"

    with pytest.raises(UploadRejected) as invalid_pdf:
        admin_stack.service.upload_document(
            filename="fake.pdf",
            content_type="application/pdf",
            data=b"not-a-pdf",
            title=None,
            doc_type="literature",
            created_by_id=admin_stack.user.id,
        )
    assert invalid_pdf.value.status_code == 415

    with pytest.raises(UploadRejected) as too_large:
        _upload(admin_stack, b"x" * 1025)
    assert too_large.value.status_code == 413

    with pytest.raises(UploadRejected) as binary_text:
        _upload(admin_stack, b"text\x00binary")
    assert binary_text.value.status_code == 415


def test_document_list_and_detail_return_latest_safe_job_without_duplicates(
    admin_stack: SimpleNamespace,
    settings_factory: Any,
    fake_service_factory: Any,
) -> None:
    tied_upload = _upload(admin_stack, b"document with tied ingestion jobs")
    no_job_upload = _upload(admin_stack, b"legacy document without an ingestion job")
    other_upload = _upload(admin_stack, b"third document for pagination")
    tied_at = datetime(2026, 8, 26, 10, 0, tzinfo=UTC)
    lower_job_id = "00000000-0000-0000-0000-000000000001"
    higher_job_id = "00000000-0000-0000-0000-000000000002"

    with admin_stack.session_factory() as database_session, database_session.begin():
        original_job = database_session.get(IngestionJob, tied_upload.ingestion_job.id)
        assert original_job is not None
        original_job.id = lower_job_id
        original_job.created_at = tied_at
        original_job.updated_at = tied_at
        original_job.lease_owner = "private-worker-one"
        database_session.add(
            IngestionJob(
                id=higher_job_id,
                document_id=tied_upload.document.id,
                status="failed",
                stage="parse",
                progress=40,
                attempts=2,
                max_attempts=3,
                lease_owner="private-worker-two",
                lease_expires_at=tied_at,
                heartbeat_at=tied_at,
                next_attempt_at=tied_at,
                cancel_requested_at=tied_at,
                inserted_parents=1,
                inserted_children=2,
                error_code="parse_failed",
                error_message="Document processing failed",
                created_at=tied_at,
                updated_at=tied_at,
                finished_at=tied_at,
            )
        )
        database_session.execute(
            delete(IngestionJob).where(IngestionJob.document_id == no_job_upload.document.id)
        )

    statements: list[str] = []

    def record_statement(*args: Any) -> None:
        statements.append(str(args[2]))

    event.listen(admin_stack.engine, "before_cursor_execute", record_statement)
    try:
        latest_jobs = admin_stack.management.get_latest_ingestion_jobs(
            [
                tied_upload.document.id,
                no_job_upload.document.id,
                other_upload.document.id,
            ]
        )
    finally:
        event.remove(admin_stack.engine, "before_cursor_execute", record_statement)

    assert len(statements) == 1
    assert latest_jobs[tied_upload.document.id].id == higher_job_id
    assert no_job_upload.document.id not in latest_jobs

    settings = settings_factory(enable_admin_api=False)
    legacy_service = fake_service_factory(settings)
    application = create_app(
        settings=settings,
        service=legacy_service,
        admin_runtime=admin_stack.service,
    )
    with TestClient(application) as client:
        login = client.post(
            "/api/v1/admin/session",
            json={"username": "admin", "password": "test-password-123"},
        )
        assert login.status_code == 200

        first_page = client.get("/api/v1/admin/documents?limit=2&offset=0")
        second_page = client.get("/api/v1/admin/documents?limit=2&offset=2")
        assert first_page.status_code == second_page.status_code == 200
        assert first_page.json()["total"] == second_page.json()["total"] == 3
        paged_ids = [
            item["id"]
            for response in (first_page, second_page)
            for item in response.json()["items"]
        ]
        assert len(paged_ids) == len(set(paged_ids)) == 3

        listed = client.get("/api/v1/admin/documents?limit=100&offset=0")
        detail = client.get(f"/api/v1/admin/documents/{tied_upload.document.id}")
        no_job_detail = client.get(f"/api/v1/admin/documents/{no_job_upload.document.id}")
        assert listed.status_code == detail.status_code == no_job_detail.status_code == 200

    listed_by_id = {item["id"]: item for item in listed.json()["items"]}
    listed_tied_job = listed_by_id[tied_upload.document.id]["latest_ingestion_job"]
    detail_job = detail.json()["latest_ingestion_job"]
    assert listed_tied_job["id"] == detail_job["id"] == higher_job_id
    assert listed_by_id[no_job_upload.document.id]["latest_ingestion_job"] is None
    assert no_job_detail.json()["latest_ingestion_job"] is None

    public_document_fields = {
        "id",
        "filename",
        "title",
        "doc_type",
        "media_type",
        "size_bytes",
        "content_sha256",
        "status",
        "created_at",
        "updated_at",
        "indexed_at",
        "latest_ingestion_job",
    }
    public_job_fields = {
        "id",
        "document_id",
        "status",
        "stage",
        "progress",
        "attempts",
        "max_attempts",
        "inserted_parents",
        "inserted_children",
        "error_code",
        "error_message",
        "created_at",
        "updated_at",
        "started_at",
        "finished_at",
    }
    assert set(listed_by_id[tied_upload.document.id]) == public_document_fields
    assert set(listed_tied_job) == public_job_fields
    serialized_responses = f"{listed.json()!r}{detail.json()!r}{no_job_detail.json()!r}"
    for private_field in (
        "object_bucket",
        "object_key",
        "lease_owner",
        "lease_expires_at",
        "heartbeat_at",
        "next_attempt_at",
        "cancel_requested_at",
    ):
        assert private_field not in serialized_responses

    assert legacy_service.closed is True


def test_ingestion_job_lease_retry_cancel_and_worker_success(admin_stack: SimpleNamespace) -> None:
    canceled_upload = _upload(admin_stack, b"cancel this ingestion")
    canceled = admin_stack.management.request_ingestion_cancel(canceled_upload.ingestion_job.id)
    assert canceled is not None and canceled.status == "canceled"
    retried = admin_stack.management.retry_ingestion_job(canceled.id)
    assert retried is not None and retried.status == "queued"

    first_claim = admin_stack.management.claim_ingestion_job(worker_id="worker-a", lease_seconds=60)
    assert first_claim is not None
    assert first_claim.id == retried.id
    assert first_claim.attempts == 1
    assert admin_stack.management.fail_ingestion_job(
        job_id=first_claim.id,
        worker_id="worker-a",
        error_code="temporary_error",
        error_message="Document processing failed",
        retryable=True,
        retry_delay_seconds=0,
    )
    second_claim = admin_stack.management.claim_ingestion_job(
        worker_id="worker-b", lease_seconds=60
    )
    assert second_claim is not None
    assert second_claim.id == first_claim.id
    assert second_claim.attempts == 2
    assert admin_stack.management.cancel_running_ingestion_job(
        job_id=second_claim.id,
        worker_id="worker-b",
    )

    successful_upload = _upload(admin_stack, b"worker should index this document")
    parser = FakeParser()
    indexer = FakeIndexer()
    worker = WorkerRunner(
        worker_id="worker-success",
        repository=admin_stack.management,
        object_storage=admin_stack.objects,
        parser=parser,
        indexer=indexer,
        lease_seconds=60,
        heartbeat_seconds=5,
        retry_base_seconds=1,
        poll_seconds=0.1,
    )
    assert worker.run_once() is True

    completed = admin_stack.management.get_ingestion_job(successful_upload.ingestion_job.id)
    document = admin_stack.management.get_document(successful_upload.document.id)
    assert completed is not None
    assert completed.status == "succeeded"
    assert completed.stage == "finalize"
    assert completed.progress == 100
    assert completed.inserted_parents == 1
    assert completed.inserted_children == 2
    assert document is not None and document.status == "active"
    assert len(indexer.indexed) == 2
    assert parser.calls[0]["metadata"]["content_sha256"] == document.content_sha256
    assert parser.calls[0]["metadata"]["managed_document_id"] == document.id
    assert parser.calls[0]["metadata"]["index_visibility"] == "staging"
    assert indexer.activation_calls == [
        {
            "managed_document_id": document.id,
            "content_sha256": document.content_sha256,
            "expected_points": 2,
        }
    ]
    assert indexer.cleanup_calls == [document.id]


def test_admin_http_api_cookie_permissions_upload_and_evaluation(
    admin_stack: SimpleNamespace,
    settings_factory: Any,
    fake_service_factory: Any,
) -> None:
    settings = settings_factory(enable_admin_api=False)
    legacy_service = fake_service_factory(settings)
    application = create_app(
        settings=settings,
        service=legacy_service,
        admin_runtime=admin_stack.service,
    )

    with TestClient(application) as client:
        assert client.get("/api/v1/admin/documents").status_code == 401
        bad_login = client.post(
            "/api/v1/admin/session",
            json={"username": "admin", "password": "wrong-password"},
        )
        assert bad_login.status_code == 401
        assert bad_login.json() == {"detail": "Invalid credentials"}

        login = client.post(
            "/api/v1/admin/session",
            json={"username": "admin", "password": "test-password-123"},
        )
        assert login.status_code == 200
        set_cookie = login.headers["set-cookie"].casefold()
        assert "httponly" in set_cookie
        assert "samesite=strict" in set_cookie
        assert "path=/api/v1/admin" in set_cookie
        assert login.headers["cache-control"] == "no-store"

        upload = client.post(
            "/api/v1/admin/documents",
            files={"file": ("clinical.md", b"# safe epilepsy note", "text/markdown")},
            data={"title": "Clinical note", "doc_type": "clinical"},
        )
        assert upload.status_code == 201
        upload_body = upload.json()
        assert upload_body["document"]["status"] == "queued"
        assert upload_body["ingestion_job"]["status"] == "queued"

        listed = client.get("/api/v1/admin/documents")
        assert listed.status_code == 200
        assert listed.json()["total"] == 1
        assert "object_key" not in listed.text

        evaluation = client.post(
            "/api/v1/admin/evaluations",
            json={"name": "Public aggregate smoke run", "suite": "smoke"},
        )
        assert evaluation.status_code == 202
        assert evaluation.json()["aggregate_metrics"] == {}
        summary = client.get("/api/v1/admin/evaluations/summary")
        assert summary.status_code == 200
        assert summary.json()["status_counts"] == {"queued": 1}
        assert "private_result" not in summary.text

        assert client.delete("/api/v1/admin/session").status_code == 204
        assert client.get("/api/v1/admin/session").status_code == 401

    assert legacy_service.closed is True


def _ingestion_worker(
    stack: SimpleNamespace,
    *,
    worker_id: str,
    parser: FakeParser,
    indexer: FakeIndexer,
) -> WorkerRunner:
    return WorkerRunner(
        worker_id=worker_id,
        repository=stack.management,
        object_storage=stack.objects,
        parser=parser,
        indexer=indexer,
        lease_seconds=60,
        heartbeat_seconds=5,
        retry_base_seconds=0,
        poll_seconds=0.1,
    )


def test_activation_failure_retries_and_repeated_activation_is_idempotent(
    admin_stack: SimpleNamespace,
) -> None:
    upload = _upload(admin_stack, b"activation should retry safely")
    indexer = FakeIndexer(activation_failures=1)
    worker = _ingestion_worker(
        admin_stack,
        worker_id="worker-activation-retry",
        parser=FakeParser(),
        indexer=indexer,
    )

    assert worker.run_once() is True
    retrying = admin_stack.management.get_ingestion_job(upload.ingestion_job.id)
    assert retrying is not None and retrying.status == "retry_wait"
    assert retrying.error_code == "runtime_error"
    assert len(indexer.activation_calls) == 1
    # One pre-attempt cleanup plus compensation after failed activation.
    assert indexer.cleanup_calls == [upload.document.id, upload.document.id]

    assert worker.run_once() is True
    completed = admin_stack.management.get_ingestion_job(upload.ingestion_job.id)
    assert completed is not None and completed.status == "succeeded"
    assert len(indexer.activation_calls) == 2
    assert all(
        call["managed_document_id"] == upload.document.id
        and call["content_sha256"] == upload.document.content_sha256
        and call["expected_points"] == 2
        for call in indexer.activation_calls
    )
    assert indexer.cleanup_calls == [
        upload.document.id,
        upload.document.id,
        upload.document.id,
    ]


def test_cleanup_failure_enters_retry_and_next_attempt_recovers(
    admin_stack: SimpleNamespace,
) -> None:
    upload = _upload(admin_stack, b"partial index needs cleanup retry")
    indexer = FakeIndexer(index_failures=1, cleanup_fail_on_calls={2})
    worker = _ingestion_worker(
        admin_stack,
        worker_id="worker-cleanup-retry",
        parser=FakeParser(),
        indexer=indexer,
    )

    assert worker.run_once() is True
    retrying = admin_stack.management.get_ingestion_job(upload.ingestion_job.id)
    assert retrying is not None and retrying.status == "retry_wait"
    assert retrying.error_code == "managed_document_cleanup_error"
    assert indexer.cleanup_calls == [upload.document.id, upload.document.id]

    assert worker.run_once() is True
    completed = admin_stack.management.get_ingestion_job(upload.ingestion_job.id)
    assert completed is not None and completed.status == "succeeded"
    assert len(indexer.activation_calls) == 1
    assert indexer.cleanup_calls == [
        upload.document.id,
        upload.document.id,
        upload.document.id,
    ]


def test_cancel_arriving_after_upsert_cleans_staging_without_activation(
    admin_stack: SimpleNamespace,
) -> None:
    upload = _upload(admin_stack, b"cancel immediately after vector upsert")
    indexer = FakeIndexer()

    def cancel_after_upsert() -> None:
        indexer.on_index = None
        canceled = admin_stack.management.request_ingestion_cancel(upload.ingestion_job.id)
        assert canceled is not None

    indexer.on_index = cancel_after_upsert
    worker = _ingestion_worker(
        admin_stack,
        worker_id="worker-cancel-after-upsert",
        parser=FakeParser(),
        indexer=indexer,
    )

    assert worker.run_once() is True
    canceled = admin_stack.management.get_ingestion_job(upload.ingestion_job.id)
    document = admin_stack.management.get_document(upload.document.id)
    assert canceled is not None and canceled.status == "canceled"
    assert document is not None and document.status == "canceled"
    assert indexer.activation_calls == []
    assert indexer.cleanup_calls == [upload.document.id, upload.document.id]


def test_final_index_failure_still_attempts_document_scoped_cleanup(
    admin_stack: SimpleNamespace,
) -> None:
    upload = _upload(admin_stack, b"all index attempts fail")
    indexer = FakeIndexer(index_failures=3)
    worker = _ingestion_worker(
        admin_stack,
        worker_id="worker-final-failure",
        parser=FakeParser(),
        indexer=indexer,
    )

    assert worker.run_once() is True
    assert worker.run_once() is True
    assert worker.run_once() is True

    failed = admin_stack.management.get_ingestion_job(upload.ingestion_job.id)
    document = admin_stack.management.get_document(upload.document.id)
    assert failed is not None and failed.status == "failed"
    assert document is not None and document.status == "failed"
    assert indexer.activation_calls == []
    assert indexer.cleanup_calls == [upload.document.id] * 6
