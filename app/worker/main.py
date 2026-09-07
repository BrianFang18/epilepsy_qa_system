from __future__ import annotations

import argparse
import logging
import os
import signal
import socket
import uuid
from collections.abc import Iterable
from dataclasses import dataclass, field
from threading import Event
from typing import Any

from sqlalchemy import Engine

from app.config import Settings, get_settings
from app.infrastructure.database.repositories import ManagementRepository
from app.infrastructure.database.session import create_database_runtime
from app.infrastructure.object_storage.minio import MinioObjectStorage
from app.retrieval.embeddings import BgeM3Embedder, DeterministicHashTfEmbedder
from app.retrieval.indexer import IngestionIndexer
from app.retrieval.mineru_pipeline import MinerUParser
from app.retrieval.vector_store import build_vector_store

from .runner import EvaluationHandler, WorkerRunner, evaluation_not_configured_handler

logger = logging.getLogger(__name__)


def _close_resources(resources: Iterable[object]) -> Exception | None:
    first_error: Exception | None = None
    seen: set[int] = set()
    for resource in reversed(tuple(resources)):
        if id(resource) in seen:
            continue
        seen.add(id(resource))
        close = getattr(resource, "close", None)
        if not callable(close):
            continue
        try:
            close()
        except Exception as exc:
            if first_error is None:
                first_error = exc
            logger.exception("Failed to close worker resource %s", type(resource).__name__)
    return first_error


def _dispose_engine(engine: Engine) -> Exception | None:
    try:
        engine.dispose()
    except Exception as exc:
        logger.exception("Failed to dispose worker database engine")
        return exc
    return None


def _build_ingestion_embedder(settings: Settings) -> object:
    if settings.ingestion_embedding_backend == "deterministic":
        return DeterministicHashTfEmbedder(settings)

    embedder = BgeM3Embedder(settings)
    # A missing/corrupt model is a startup error for the explicit BGE worker.
    if not bool(getattr(embedder, "using_real_model", True)):
        embedder.close()
        raise RuntimeError(
            "INGESTION_EMBEDDING_BACKEND=bge_m3 requires a loadable local BGE-M3 model"
        )
    # Test doubles and legacy adapters may not expose this capability. The real
    # BGE adapter does, and disables runtime fallback before any job is claimed.
    disable_fallback = getattr(embedder, "disable_fallback", None)
    if callable(disable_fallback):
        disable_fallback()
    return embedder


@dataclass(slots=True)
class WorkerRuntime:
    runner: WorkerRunner
    engine: Engine
    closeable_resources: tuple[object, ...] = ()
    _closed: bool = field(default=False, init=False, repr=False)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        resource_error = _close_resources(self.closeable_resources)
        engine_error = _dispose_engine(self.engine)
        if resource_error is not None:
            raise resource_error
        if engine_error is not None:
            raise engine_error


def build_worker_runtime(
    worker_id: str | None = None,
    *,
    evaluation_handler: EvaluationHandler | None = evaluation_not_configured_handler,
) -> WorkerRuntime:
    if evaluation_handler is not None and not callable(evaluation_handler):
        raise TypeError("evaluation_handler must be callable or None")

    settings = get_settings()
    engine: Engine | None = None
    resources: list[object] = []
    try:
        engine, session_factory = create_database_runtime(
            settings.database_url,
            echo=settings.database_echo,
            pool_size=settings.database_pool_size,
        )
        repository = ManagementRepository(session_factory)
        storage = MinioObjectStorage(
            endpoint=settings.minio_endpoint,
            access_key=settings.minio_access_key.get_secret_value(),
            secret_key=settings.minio_secret_key.get_secret_value(),
            secure=settings.minio_secure,
            region=settings.minio_region,
        )
        resources.append(storage)

        parser = MinerUParser()
        resources.append(parser)
        embedder = _build_ingestion_embedder(settings)
        resources.append(embedder)
        store = build_vector_store(settings)
        resources.append(store)
        indexer = IngestionIndexer(
            embedder=embedder,  # type: ignore[arg-type]
            store=store,
            dense_dimension=settings.embed_dim,
        )
        resources.append(indexer)

        identity = worker_id or f"{socket.gethostname()}-{os.getpid()}-{uuid.uuid4().hex[:8]}"
        runner = WorkerRunner(
            worker_id=identity,
            repository=repository,
            object_storage=storage,
            parser=parser,
            indexer=indexer,
            lease_seconds=settings.worker_lease_seconds,
            heartbeat_seconds=settings.worker_heartbeat_seconds,
            retry_base_seconds=settings.worker_retry_base_seconds,
            poll_seconds=settings.worker_poll_seconds,
            evaluation_handler=evaluation_handler,
        )
        closeable_resources = tuple(
            resource for resource in resources if callable(getattr(resource, "close", None))
        )
        return WorkerRuntime(
            runner=runner,
            engine=engine,
            closeable_resources=closeable_resources,
        )
    except Exception:
        _close_resources(resources)
        if engine is not None:
            _dispose_engine(engine)
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Epilepsy document ingestion worker")
    parser.add_argument("--once", action="store_true", help="Process at most one job and exit")
    parser.add_argument("--worker-id", default=None)
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO)
    # The bundled process is ingestion-only. It must not claim evaluation jobs
    # until a controlled evaluator is explicitly wired by another deployment.
    runtime = build_worker_runtime(args.worker_id, evaluation_handler=None)
    stop_event = Event()

    def request_stop(_signum: int, _frame: Any) -> None:
        stop_event.set()

    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)
    try:
        if args.once:
            runtime.runner.run_once()
        else:
            runtime.runner.run_forever(stop_event)
        return 0
    finally:
        try:
            runtime.runner.stop()
        finally:
            runtime.close()


if __name__ == "__main__":
    raise SystemExit(main())
