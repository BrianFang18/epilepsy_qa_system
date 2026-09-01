"""Opt-in fixtures for real compose infrastructure smoke tests."""

from __future__ import annotations

import os
import uuid
from collections.abc import Generator
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, NoReturn, cast
from unittest.mock import patch

import alembic.command as command
import pytest
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, delete, func, select, text
from sqlalchemy.orm import Session, sessionmaker

from app.infrastructure.database.models import (
    AdminUser,
    Document,
    IngestionJob,
    WorkerHeartbeat,
)
from app.infrastructure.database.repositories import AdminRepository, ManagementRepository
from app.infrastructure.database.session import create_database_runtime
from app.infrastructure.object_storage.minio import MinioObjectStorage
from app.retrieval.vector_store import QdrantHybridStore

PROJECT_ROOT = Path(__file__).resolve().parents[2]
_DENSE_DIMENSION = 4
_ADVISORY_LOCK_KEY = 7_230_684_976_114_991_103
_ACTIVE_JOB_STATUSES = ("queued", "retry_wait", "running")


def _required_environment(name: str) -> str:
    value = os.environ.get(name)
    if value is None or not value.strip():
        pytest.fail(f"required integration environment variable is missing: {name}", pytrace=False)
    return value.strip()


def _optional_environment(name: str) -> str | None:
    value = os.environ.get(name)
    if value is None or not value.strip():
        return None
    return value.strip()


def _environment_boolean(name: str) -> bool:
    raw = _required_environment(name).casefold()
    if raw in {"1", "true"}:
        return True
    if raw in {"0", "false"}:
        return False
    pytest.fail(f"{name} must be one of: 0, 1, false, true", pytrace=False)


def _forbid_application_settings() -> NoReturn:
    raise AssertionError("compose integration must not instantiate application Settings")


@dataclass(frozen=True, slots=True)
class ComposeTestConfig:
    postgres_dsn: str = field(repr=False)
    minio_endpoint: str
    minio_access_key: str = field(repr=False)
    minio_secret_key: str = field(repr=False)
    minio_secure: bool
    minio_region: str | None
    qdrant_url: str = field(repr=False)
    qdrant_api_key: str | None = field(repr=False)


@pytest.fixture(scope="session")
def compose_test_config() -> ComposeTestConfig:
    """Read only the explicit integration namespace; never load dotenv or Settings."""
    return ComposeTestConfig(
        postgres_dsn=_required_environment("COMPOSE_TEST_POSTGRES_DSN"),
        minio_endpoint=_required_environment("COMPOSE_TEST_MINIO_ENDPOINT"),
        minio_access_key=_required_environment("COMPOSE_TEST_MINIO_ACCESS_KEY"),
        minio_secret_key=_required_environment("COMPOSE_TEST_MINIO_SECRET_KEY"),
        minio_secure=_environment_boolean("COMPOSE_TEST_MINIO_SECURE"),
        minio_region=_optional_environment("COMPOSE_TEST_MINIO_REGION"),
        qdrant_url=_required_environment("COMPOSE_TEST_QDRANT_URL"),
        qdrant_api_key=_optional_environment("COMPOSE_TEST_QDRANT_API_KEY"),
    )


@dataclass(frozen=True, slots=True)
class DatabaseRuntime:
    engine: Engine = field(repr=False)
    session_factory: sessionmaker[Session] = field(repr=False)
    current_heads: frozenset[str]
    expected_heads: frozenset[str]


@pytest.fixture(scope="session")
def database_runtime(
    compose_test_config: ComposeTestConfig,
) -> Generator[DatabaseRuntime, None, None]:
    """Connect to PostgreSQL, apply real migrations, and hold a smoke-run lock."""
    engine, session_factory = create_database_runtime(
        compose_test_config.postgres_dsn,
        pool_size=5,
    )
    if engine.dialect.name != "postgresql":
        engine.dispose()
        pytest.fail("COMPOSE_TEST_POSTGRES_DSN must select PostgreSQL", pytrace=False)

    try:
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT 1")) == 1
    except Exception:
        engine.dispose()
        pytest.fail("PostgreSQL is unavailable through COMPOSE_TEST_POSTGRES_DSN", pytrace=False)

    alembic_config = Config()
    alembic_config.set_main_option("script_location", str(PROJECT_ROOT / "alembic"))
    # ConfigParser reserves percent signs; get_main_option restores the original URL.
    alembic_config.set_main_option(
        "sqlalchemy.url",
        compose_test_config.postgres_dsn.replace("%", "%%"),
    )
    try:
        with patch("app.config.get_settings", side_effect=_forbid_application_settings):
            command.upgrade(alembic_config, "head")
        expected_heads = frozenset(ScriptDirectory.from_config(alembic_config).get_heads())
        with engine.connect() as connection:
            current_heads = frozenset(MigrationContext.configure(connection).get_current_heads())
    except Exception:
        engine.dispose()
        pytest.fail("Alembic upgrade or head verification failed", pytrace=False)

    if not expected_heads or current_heads != expected_heads:
        engine.dispose()
        pytest.fail("PostgreSQL is not at the repository Alembic head", pytrace=False)

    lock_connection = engine.connect()
    try:
        acquired = lock_connection.scalar(
            text("SELECT pg_try_advisory_lock(:key)"),
            {"key": _ADVISORY_LOCK_KEY},
        )
        if acquired is not True:
            pytest.fail("another compose integration smoke run is active", pytrace=False)
        yield DatabaseRuntime(
            engine=engine,
            session_factory=session_factory,
            current_heads=current_heads,
            expected_heads=expected_heads,
        )
    finally:
        with suppress(Exception):
            lock_connection.execute(
                text("SELECT pg_advisory_unlock(:key)"),
                {"key": _ADVISORY_LOCK_KEY},
            )
        lock_connection.close()
        engine.dispose()


@dataclass(slots=True)
class DatabaseRows:
    session_factory: sessionmaker[Session] = field(repr=False)
    admin_repository: AdminRepository = field(repr=False)
    management: ManagementRepository = field(repr=False)
    admin_id: str = ""
    admin_ids: set[str] = field(default_factory=set)
    document_ids: set[str] = field(default_factory=set)
    job_ids: set[str] = field(default_factory=set)
    worker_ids: set[str] = field(default_factory=set)

    def track_document(self, document: Document, job: IngestionJob) -> None:
        self.document_ids.add(document.id)
        self.job_ids.add(job.id)

    def track_worker(self, worker_id: str) -> None:
        self.worker_ids.add(worker_id)

    def cleanup(self) -> None:
        """Delete only rows created by this test, in foreign-key-safe order."""
        with self.session_factory() as session, session.begin():
            if self.job_ids:
                session.execute(delete(IngestionJob).where(IngestionJob.id.in_(self.job_ids)))
            if self.document_ids:
                session.execute(delete(Document).where(Document.id.in_(self.document_ids)))
            if self.worker_ids:
                session.execute(
                    delete(WorkerHeartbeat).where(WorkerHeartbeat.worker_id.in_(self.worker_ids))
                )
            if self.admin_ids:
                session.execute(delete(AdminUser).where(AdminUser.id.in_(self.admin_ids)))

        with self.session_factory() as session:
            remaining = 0
            if self.job_ids:
                remaining += int(
                    session.scalar(
                        select(func.count())
                        .select_from(IngestionJob)
                        .where(IngestionJob.id.in_(self.job_ids))
                    )
                    or 0
                )
            if self.document_ids:
                remaining += int(
                    session.scalar(
                        select(func.count())
                        .select_from(Document)
                        .where(Document.id.in_(self.document_ids))
                    )
                    or 0
                )
            if self.worker_ids:
                remaining += int(
                    session.scalar(
                        select(func.count())
                        .select_from(WorkerHeartbeat)
                        .where(WorkerHeartbeat.worker_id.in_(self.worker_ids))
                    )
                    or 0
                )
            if self.admin_ids:
                remaining += int(
                    session.scalar(
                        select(func.count())
                        .select_from(AdminUser)
                        .where(AdminUser.id.in_(self.admin_ids))
                    )
                    or 0
                )
        if remaining:
            raise AssertionError("compose integration database row cleanup was incomplete")


@pytest.fixture
def database_rows(database_runtime: DatabaseRuntime) -> Generator[DatabaseRows, None, None]:
    """Provide repositories plus exact-ID cleanup, refusing an active shared queue."""
    with database_runtime.session_factory() as session:
        active_jobs = int(
            session.scalar(
                select(func.count())
                .select_from(IngestionJob)
                .where(IngestionJob.status.in_(_ACTIVE_JOB_STATUSES))
            )
            or 0
        )
    if active_jobs:
        pytest.fail(
            "integration PostgreSQL contains pre-existing active ingestion jobs; "
            "use a dedicated compose test database",
            pytrace=False,
        )

    rows = DatabaseRows(
        session_factory=database_runtime.session_factory,
        admin_repository=AdminRepository(database_runtime.session_factory),
        management=ManagementRepository(database_runtime.session_factory),
    )
    try:
        admin = rows.admin_repository.ensure_user(
            username=f"compose-smoke-{uuid.uuid4().hex}",
            password_hash="compose-smoke-not-a-login-secret",
        )
        rows.admin_id = admin.id
        rows.admin_ids.add(admin.id)
        yield rows
    finally:
        rows.cleanup()


@dataclass(slots=True)
class MinioSandbox:
    storage: MinioObjectStorage = field(repr=False)
    client: Any = field(repr=False)
    bucket: str
    object_keys: set[str] = field(default_factory=set)

    def put_bytes(self, object_key: str, data: bytes) -> None:
        self.storage.put_bytes(
            bucket=self.bucket,
            object_key=object_key,
            data=data,
            content_type="text/plain; charset=utf-8",
            metadata={"smoke": "true"},
        )
        self.object_keys.add(object_key)

    def delete_object(self, object_key: str) -> None:
        self.storage.delete_object(bucket=self.bucket, object_key=object_key)
        self.object_keys.discard(object_key)

    def cleanup(self) -> None:
        """Remove this unique bucket only; never enumerate or mutate another bucket."""
        first_error: Exception | None = None
        for object_key in tuple(self.object_keys):
            try:
                self.storage.delete_object(bucket=self.bucket, object_key=object_key)
            except Exception as exc:  # pragma: no cover - exercised only on cleanup failure
                first_error = first_error or exc
        self.object_keys.clear()
        try:
            if self.client.bucket_exists(self.bucket):
                for item in self.client.list_objects(self.bucket, recursive=True):
                    self.client.remove_object(self.bucket, item.object_name)
                self.client.remove_bucket(self.bucket)
            if self.client.bucket_exists(self.bucket):
                raise AssertionError("temporary MinIO bucket still exists after cleanup")
        except Exception as exc:  # pragma: no cover - exercised only on cleanup failure
            first_error = first_error or exc
        if first_error is not None:
            raise RuntimeError("temporary MinIO bucket cleanup failed") from first_error


@pytest.fixture
def minio_sandbox(
    compose_test_config: ComposeTestConfig,
) -> Generator[MinioSandbox, None, None]:
    from minio import Minio

    storage = MinioObjectStorage(
        endpoint=compose_test_config.minio_endpoint,
        access_key=compose_test_config.minio_access_key,
        secret_key=compose_test_config.minio_secret_key,
        secure=compose_test_config.minio_secure,
        region=compose_test_config.minio_region,
    )
    client = Minio(
        compose_test_config.minio_endpoint,
        access_key=compose_test_config.minio_access_key,
        secret_key=compose_test_config.minio_secret_key,
        secure=compose_test_config.minio_secure,
        region=compose_test_config.minio_region,
    )
    sandbox = MinioSandbox(
        storage=storage,
        client=client,
        bucket=f"epilepsy-smoke-{uuid.uuid4().hex}",
    )
    probe_key = f"probe/{uuid.uuid4().hex}.txt"
    try:
        sandbox.put_bytes(probe_key, b"compose-smoke-probe")
        if storage.healthcheck(sandbox.bucket) is not True:
            raise AssertionError("temporary MinIO bucket is not visible")
        sandbox.delete_object(probe_key)
    except Exception:
        with suppress(Exception):
            sandbox.cleanup()
        pytest.fail("MinIO is unavailable through COMPOSE_TEST_MINIO_*", pytrace=False)

    try:
        yield sandbox
    finally:
        sandbox.cleanup()


@dataclass(frozen=True, slots=True)
class QdrantTestSettings:
    qdrant_url: str = field(repr=False)
    qdrant_api_key: str | None = field(repr=False)
    qdrant_collection: str
    embed_dim: int = _DENSE_DIMENSION
    dense_top_k: int = 8
    sparse_top_k: int = 8


@dataclass(slots=True)
class QdrantSandbox:
    store: QdrantHybridStore = field(repr=False)
    client: Any = field(repr=False)
    collection: str
    dense_dimension: int = _DENSE_DIMENSION

    def cleanup(self) -> None:
        """Delete exactly this generated collection; never call store.clear()."""
        first_error: Exception | None = None
        try:
            if self.client.collection_exists(self.collection):
                self.client.delete_collection(collection_name=self.collection)
            if self.client.collection_exists(self.collection):
                raise AssertionError("temporary Qdrant collection still exists after cleanup")
        except Exception as exc:  # pragma: no cover - exercised only on cleanup failure
            first_error = exc
        finally:
            with suppress(Exception):
                self.client.close()
        if first_error is not None:
            raise RuntimeError("temporary Qdrant collection cleanup failed") from first_error


@pytest.fixture
def qdrant_sandbox(
    compose_test_config: ComposeTestConfig,
) -> Generator[QdrantSandbox, None, None]:
    try:
        from qdrant_client import QdrantClient
    except ImportError:
        pytest.fail("qdrant-client is unavailable for compose integration", pytrace=False)

    collection = f"epilepsy-compose-smoke-{uuid.uuid4().hex}"
    client = QdrantClient(
        url=compose_test_config.qdrant_url,
        api_key=compose_test_config.qdrant_api_key,
    )
    settings = QdrantTestSettings(
        qdrant_url=compose_test_config.qdrant_url,
        qdrant_api_key=compose_test_config.qdrant_api_key,
        qdrant_collection=collection,
    )
    try:
        store = QdrantHybridStore(cast(Any, settings), client=client)
        if client.collection_exists(collection) is not True:
            raise AssertionError("temporary Qdrant collection is not visible")
    except Exception:
        with suppress(Exception):
            if client.collection_exists(collection):
                client.delete_collection(collection_name=collection)
        with suppress(Exception):
            client.close()
        pytest.fail("Qdrant is unavailable through COMPOSE_TEST_QDRANT_*", pytrace=False)

    sandbox = QdrantSandbox(store=store, client=client, collection=collection)
    try:
        yield sandbox
    finally:
        sandbox.cleanup()
