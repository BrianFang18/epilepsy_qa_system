"""Real PostgreSQL, MinIO, Qdrant, and WorkerRunner compose smoke tests."""

from __future__ import annotations

import hashlib
import os
import uuid
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, NoReturn

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.infrastructure.database.models import Document, IngestionJob
from app.retrieval.chunking import ChildChunk, ParentChunk
from app.retrieval.indexer import IngestionIndexer
from app.retrieval.vector_store import (
    CONTENT_SHA256_FIELD,
    INDEX_VISIBILITY_ACTIVE,
    INDEX_VISIBILITY_FIELD,
    INDEX_VISIBILITY_STAGING,
    MANAGED_DOCUMENT_ID_FIELD,
)
from app.schemas import IndexedChunk
from app.worker.runner import WorkerRunner
from tests.integration.conftest import (
    DatabaseRows,
    DatabaseRuntime,
    MinioSandbox,
    QdrantSandbox,
)

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.environ.get("RUN_COMPOSE_INTEGRATION") != "1",
        reason="set RUN_COMPOSE_INTEGRATION=1 to run real compose integration",
    ),
]

_DENSE_VECTOR = [1.0, 0.5, 0.25, 0.125]
_SPARSE_VECTOR = {3: 1.0, 11: 0.5}
_SYNTHETIC_TEXT = b"Synthetic TXT payload for deterministic compose infrastructure validation."


class DeterministicTxtParser:
    """Small injectable parser that reads only the downloaded synthetic TXT object."""

    def parse_to_chunks(
        self,
        file_path: str,
        doc_id: str,
        title: str | None = None,
        doc_type: str = "literature",
        metadata: dict[str, Any] | None = None,
    ) -> tuple[list[ParentChunk], list[ChildChunk]]:
        text = Path(file_path).read_text(encoding="utf-8").strip()
        if not text:
            raise ValueError("synthetic TXT is empty")
        inherited = dict(metadata or {})
        resolved_title = title or "Synthetic compose document"
        parent_id = f"p_{uuid.uuid5(uuid.NAMESPACE_URL, f'{doc_id}:parent')}"
        chunk_id = f"c_{uuid.uuid5(uuid.NAMESPACE_URL, f'{doc_id}:child')}"
        parent = ParentChunk(
            parent_id=parent_id,
            doc_id=doc_id,
            title=resolved_title,
            doc_type=doc_type,
            text=text,
            metadata={**inherited, "level": "parent"},
        )
        child = ChildChunk(
            chunk_id=chunk_id,
            parent_id=parent_id,
            doc_id=doc_id,
            title=resolved_title,
            doc_type=doc_type,
            text=text,
            parent_text=text,
            metadata={**inherited, "level": "child", "source_parent": parent_id},
        )
        return [parent], [child]


class DeterministicEmbedder:
    def encode_dense(self, texts: Iterable[str]) -> list[list[float]]:
        return [list(_DENSE_VECTOR) for _ in texts]

    def encode_sparse(self, texts: Iterable[str]) -> list[dict[int, float]]:
        return [dict(_SPARSE_VECTOR) for _ in texts]


class RetryableFailingParser:
    def parse_to_chunks(
        self,
        file_path: str,
        doc_id: str,
        title: str | None = None,
        doc_type: str = "literature",
        metadata: dict[str, Any] | None = None,
    ) -> NoReturn:
        del file_path, doc_id, title, doc_type, metadata
        raise RuntimeError("synthetic retryable parser failure")


def _document_values(
    rows: DatabaseRows,
    *,
    bucket: str,
    object_key: str,
    content: bytes,
) -> dict[str, Any]:
    content_sha256 = hashlib.sha256(content).hexdigest()
    document_id = str(uuid.uuid4())
    return {
        "id": document_id,
        "filename": "synthetic.txt",
        "title": "Synthetic compose document",
        "doc_type": "literature",
        "media_type": "text/plain",
        "size_bytes": len(content),
        "content_sha256": content_sha256,
        "idempotency_key": hashlib.sha256(
            f"compose-smoke:{document_id}:{content_sha256}".encode()
        ).hexdigest(),
        "object_bucket": bucket,
        "object_key": object_key,
        "status": "uploaded",
        "parser_version": "compose-deterministic-txt-v1",
        "chunker_version": "compose-single-chunk-v1",
        "embedder_version": "compose-deterministic-vector-v1",
        "index_version": "compose-qdrant-hybrid-v1",
        "created_by_id": rows.admin_id,
    }


def _upload_and_create_job(
    rows: DatabaseRows,
    minio: MinioSandbox,
    *,
    content: bytes = _SYNTHETIC_TEXT,
    max_attempts: int = 3,
) -> tuple[Document, IngestionJob]:
    object_key = f"documents/{uuid.uuid4().hex}/synthetic.txt"
    minio.put_bytes(object_key, content)
    values = _document_values(
        rows,
        bucket=minio.bucket,
        object_key=object_key,
        content=content,
    )
    document, job, created = rows.management.create_document_with_job(
        document_values=values,
        max_attempts=max_attempts,
    )
    rows.track_document(document, job)
    assert created is True
    assert document.status == "queued"
    assert job.status == "queued"
    return document, job


def _runner(
    rows: DatabaseRows,
    minio: MinioSandbox,
    qdrant: QdrantSandbox,
    *,
    worker_id: str,
    parser: Any,
    retry_base_seconds: int = 5,
) -> WorkerRunner:
    rows.track_worker(worker_id)
    indexer = IngestionIndexer(
        embedder=DeterministicEmbedder(),
        store=qdrant.store,
        dense_dimension=qdrant.dense_dimension,
    )
    return WorkerRunner(
        worker_id=worker_id,
        repository=rows.management,
        object_storage=minio.storage,
        parser=parser,
        indexer=indexer,
        lease_seconds=30,
        heartbeat_seconds=5,
        retry_base_seconds=retry_base_seconds,
        poll_seconds=0.01,
    )


def _hybrid_search(qdrant: QdrantSandbox) -> list[IndexedChunk]:
    return qdrant.store.hybrid_search(
        query_dense=list(_DENSE_VECTOR),
        query_sparse=dict(_SPARSE_VECTOR),
        doc_type="literature",
        top_k=8,
        dense_weight=0.5,
        sparse_weight=0.5,
    )


def test_real_services_are_available_and_alembic_is_at_head(
    database_runtime: DatabaseRuntime,
    minio_sandbox: MinioSandbox,
    qdrant_sandbox: QdrantSandbox,
) -> None:
    assert database_runtime.engine.dialect.name == "postgresql"
    assert database_runtime.current_heads == database_runtime.expected_heads
    assert minio_sandbox.storage.healthcheck(minio_sandbox.bucket) is True
    assert qdrant_sandbox.client.collection_exists(qdrant_sandbox.collection) is True


def test_postgresql_transaction_claim_and_lease_reclaim(
    database_runtime: DatabaseRuntime,
    database_rows: DatabaseRows,
) -> None:
    values = _document_values(
        database_rows,
        bucket=f"unused-smoke-{uuid.uuid4().hex[:24]}",
        object_key=f"unused/{uuid.uuid4().hex}/synthetic.txt",
        content=_SYNTHETIC_TEXT,
    )
    invalid_values = {**values, "created_by_id": str(uuid.uuid4())}

    with pytest.raises(IntegrityError):
        database_rows.management.create_document_with_job(
            document_values=invalid_values,
            max_attempts=3,
        )
    with database_runtime.session_factory() as session:
        rolled_back_documents = int(
            session.scalar(
                select(func.count()).select_from(Document).where(Document.id == values["id"])
            )
            or 0
        )
        rolled_back_jobs = int(
            session.scalar(
                select(func.count())
                .select_from(IngestionJob)
                .where(IngestionJob.document_id == values["id"])
            )
            or 0
        )
    assert (rolled_back_documents, rolled_back_jobs) == (0, 0)

    document, job, created = database_rows.management.create_document_with_job(
        document_values=values,
        max_attempts=3,
    )
    database_rows.track_document(document, job)
    assert created is True

    duplicate_document, duplicate_job, duplicate_created = (
        database_rows.management.create_document_with_job(
            document_values=values,
            max_attempts=3,
        )
    )
    assert duplicate_created is False
    assert duplicate_document.id == document.id
    assert duplicate_job.id == job.id

    first_worker = f"compose-lease-a-{uuid.uuid4().hex}"
    second_worker = f"compose-lease-b-{uuid.uuid4().hex}"
    database_rows.track_worker(first_worker)
    database_rows.track_worker(second_worker)
    first_claim = database_rows.management.claim_ingestion_job(
        worker_id=first_worker,
        lease_seconds=30,
    )
    assert first_claim is not None
    assert first_claim.id == job.id
    assert first_claim.status == "running"
    assert first_claim.attempts == 1
    assert first_claim.lease_owner == first_worker
    assert first_claim.lease_expires_at is not None

    assert (
        database_rows.management.claim_ingestion_job(
            worker_id=second_worker,
            lease_seconds=30,
        )
        is None
    )
    assert (
        database_rows.management.heartbeat_ingestion_job(
            job_id=job.id,
            worker_id=second_worker,
            lease_seconds=30,
        )
        is False
    )
    assert database_rows.management.heartbeat_ingestion_job(
        job_id=job.id,
        worker_id=first_worker,
        lease_seconds=30,
    )

    with database_runtime.session_factory() as session, session.begin():
        stored = session.get(IngestionJob, job.id)
        assert stored is not None
        stored.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)

    reclaimed = database_rows.management.claim_ingestion_job(
        worker_id=second_worker,
        lease_seconds=30,
    )
    assert reclaimed is not None
    assert reclaimed.id == job.id
    assert reclaimed.attempts == 2
    assert reclaimed.lease_owner == second_worker
    assert database_rows.management.fail_ingestion_job(
        job_id=job.id,
        worker_id=second_worker,
        error_code="compose_smoke_terminal",
        error_message="Synthetic smoke termination",
        retryable=False,
        retry_delay_seconds=0,
    )


def test_minio_adapter_put_fget_and_remove(
    minio_sandbox: MinioSandbox,
    tmp_path: Path,
) -> None:
    object_key = f"round-trip/{uuid.uuid4().hex}.txt"
    payload = b"Synthetic MinIO adapter round trip."
    destination = tmp_path / "downloaded.txt"

    minio_sandbox.put_bytes(object_key, payload)
    minio_sandbox.storage.download_file(
        bucket=minio_sandbox.bucket,
        object_key=object_key,
        destination=str(destination),
    )
    assert destination.read_bytes() == payload

    minio_sandbox.delete_object(object_key)
    remaining_names = {
        item.object_name
        for item in minio_sandbox.client.list_objects(minio_sandbox.bucket, recursive=True)
    }
    assert object_key not in remaining_names


def test_qdrant_named_dense_sparse_staging_activation_and_scoped_delete(
    qdrant_sandbox: QdrantSandbox,
) -> None:
    info = qdrant_sandbox.client.get_collection(collection_name=qdrant_sandbox.collection)
    vectors = info.config.params.vectors
    sparse_vectors = info.config.params.sparse_vectors
    assert set(vectors) == {qdrant_sandbox.store.DENSE_VECTOR_NAME}
    assert set(sparse_vectors) == {qdrant_sandbox.store.SPARSE_VECTOR_NAME}
    assert vectors[qdrant_sandbox.store.DENSE_VECTOR_NAME].size == qdrant_sandbox.dense_dimension

    managed_document_id = str(uuid.uuid4())
    content_sha256 = hashlib.sha256(_SYNTHETIC_TEXT).hexdigest()
    chunk = IndexedChunk(
        chunk_id=f"compose-direct-{uuid.uuid4().hex}",
        parent_id="compose-direct-parent",
        doc_id=managed_document_id,
        title="Synthetic direct Qdrant document",
        doc_type="literature",
        text="Synthetic direct Qdrant child text.",
        parent_text="Synthetic direct Qdrant parent text.",
        metadata={
            INDEX_VISIBILITY_FIELD: INDEX_VISIBILITY_STAGING,
            MANAGED_DOCUMENT_ID_FIELD: managed_document_id,
            CONTENT_SHA256_FIELD: content_sha256,
        },
        dense_vector=list(_DENSE_VECTOR),
        sparse_vector=dict(_SPARSE_VECTOR),
    )
    qdrant_sandbox.store.upsert_chunks([chunk])
    assert qdrant_sandbox.store.count() == 1
    assert _hybrid_search(qdrant_sandbox) == []

    qdrant_sandbox.store.activate_managed_document(
        managed_document_id=managed_document_id,
        content_sha256=content_sha256,
        expected_points=1,
    )
    visible = _hybrid_search(qdrant_sandbox)
    assert [item.chunk_id for item in visible] == [chunk.chunk_id]
    assert visible[0].metadata[INDEX_VISIBILITY_FIELD] == INDEX_VISIBILITY_ACTIVE

    qdrant_sandbox.store.delete_managed_document(managed_document_id=managed_document_id)
    assert qdrant_sandbox.store.count() == 0
    assert qdrant_sandbox.client.collection_exists(qdrant_sandbox.collection) is True


def test_synthetic_txt_worker_runner_succeeds_across_all_real_stores(
    database_rows: DatabaseRows,
    minio_sandbox: MinioSandbox,
    qdrant_sandbox: QdrantSandbox,
) -> None:
    document, job = _upload_and_create_job(database_rows, minio_sandbox)
    worker_id = f"compose-success-{uuid.uuid4().hex}"
    runner = _runner(
        database_rows,
        minio_sandbox,
        qdrant_sandbox,
        worker_id=worker_id,
        parser=DeterministicTxtParser(),
    )

    assert runner.run_once() is True

    completed = database_rows.management.get_ingestion_job(job.id)
    activated_document = database_rows.management.get_document(document.id)
    assert completed is not None
    assert completed.status == "succeeded"
    assert completed.stage == "finalize"
    assert completed.progress == 100
    assert completed.attempts == 1
    assert completed.inserted_parents == 1
    assert completed.inserted_children == 1
    assert completed.lease_owner is None
    assert completed.finished_at is not None
    assert activated_document is not None
    assert activated_document.status == "active"
    assert activated_document.indexed_at is not None

    visible = _hybrid_search(qdrant_sandbox)
    assert len(visible) == 1
    assert visible[0].doc_id == document.id
    assert visible[0].metadata[MANAGED_DOCUMENT_ID_FIELD] == document.id
    assert visible[0].metadata[CONTENT_SHA256_FIELD] == document.content_sha256
    assert visible[0].metadata[INDEX_VISIBILITY_FIELD] == INDEX_VISIBILITY_ACTIVE


def test_worker_runner_retry_is_persisted_and_never_reports_false_success(
    database_rows: DatabaseRows,
    minio_sandbox: MinioSandbox,
    qdrant_sandbox: QdrantSandbox,
) -> None:
    document, job = _upload_and_create_job(
        database_rows,
        minio_sandbox,
        max_attempts=2,
    )
    worker_id = f"compose-retry-{uuid.uuid4().hex}"
    runner = _runner(
        database_rows,
        minio_sandbox,
        qdrant_sandbox,
        worker_id=worker_id,
        parser=RetryableFailingParser(),
        retry_base_seconds=30,
    )

    assert runner.run_once() is True

    retrying = database_rows.management.get_ingestion_job(job.id)
    queued_document = database_rows.management.get_document(document.id)
    assert retrying is not None
    assert retrying.status == "retry_wait"
    assert retrying.attempts == 1
    assert retrying.error_code == "runtime_error"
    assert retrying.error_message == "Document processing failed"
    assert retrying.lease_owner is None
    assert retrying.finished_at is None
    assert retrying.next_attempt_at > datetime.now(UTC)
    assert queued_document is not None and queued_document.status == "queued"
    assert qdrant_sandbox.store.count() == 0
    assert _hybrid_search(qdrant_sandbox) == []
    assert runner.run_once() is False
