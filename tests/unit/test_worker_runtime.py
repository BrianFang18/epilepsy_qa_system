"""Worker assembly, evaluation policy, and ingestion indexing regressions."""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any, NoReturn, cast

import pytest

import app.worker.main as worker_main
from app.infrastructure.database.models import EvaluationJob
from app.retrieval.chunking import ChildChunk
from app.retrieval.indexer import IngestionIndexer
from app.retrieval.retriever import HybridRetriever
from app.schemas import IndexedChunk
from app.worker.runner import (
    EVALUATION_NOT_CONFIGURED,
    EvaluationResult,
    WorkerRunner,
    evaluation_not_configured_handler,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class _RecordingEmbedder:
    def __init__(
        self,
        *,
        dense: list[list[float]],
        sparse: list[dict[int, float]],
    ) -> None:
        self.dense = dense
        self.sparse = sparse
        self.dense_inputs: list[str] = []
        self.sparse_inputs: list[str] = []

    def encode_dense(self, texts: Iterable[str]) -> list[list[float]]:
        self.dense_inputs = list(texts)
        return self.dense

    def encode_sparse(self, texts: Iterable[str]) -> list[dict[int, float]]:
        self.sparse_inputs = list(texts)
        return self.sparse


class _RecordingStore:
    def __init__(self) -> None:
        self.upsert_calls: list[list[IndexedChunk]] = []

    def upsert_chunks(self, chunks: list[IndexedChunk]) -> None:
        self.upsert_calls.append(chunks)

    def activate_managed_document(
        self,
        *,
        managed_document_id: str,
        content_sha256: str,
        expected_points: int,
    ) -> None:
        del managed_document_id, content_sha256, expected_points

    def delete_managed_document(self, *, managed_document_id: str) -> None:
        del managed_document_id


class _ClosableResource:
    def __init__(self, name: str) -> None:
        self.name = name
        self.close_calls = 0

    def close(self) -> None:
        self.close_calls += 1


class _FakeEngine:
    def __init__(self) -> None:
        self.dispose_calls = 0

    def dispose(self) -> None:
        self.dispose_calls += 1


class _FactoryHarness:
    def __init__(self, settings: Any, *, fail_runner: bool = False) -> None:
        self.settings = settings
        self.fail_runner = fail_runner
        self.engine = _FakeEngine()
        self.repository = object()
        self.storage = _ClosableResource("storage")
        self.parser = _ClosableResource("parser")
        self.embedder = _ClosableResource("embedder")
        self.store = _ClosableResource("store")
        self.indexer = _ClosableResource("indexer")
        self.runner = cast(Any, object())
        self.runner_kwargs: dict[str, Any] = {}
        self.indexer_kwargs: dict[str, Any] = {}

    @property
    def resources(self) -> tuple[_ClosableResource, ...]:
        return self.storage, self.parser, self.embedder, self.store, self.indexer

    def install(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def create_runtime(*_args: Any, **_kwargs: Any) -> tuple[Any, object]:
            return self.engine, object()

        def build_repository(_session_factory: object) -> object:
            return self.repository

        def build_storage(**_kwargs: Any) -> _ClosableResource:
            return self.storage

        def build_parser() -> _ClosableResource:
            return self.parser

        def build_embedder(_settings: Any) -> _ClosableResource:
            return self.embedder

        def build_store(_settings: Any) -> _ClosableResource:
            return self.store

        def build_indexer(**kwargs: Any) -> _ClosableResource:
            self.indexer_kwargs = kwargs
            return self.indexer

        def build_runner(**kwargs: Any) -> Any:
            self.runner_kwargs = kwargs
            if self.fail_runner:
                raise RuntimeError("runner construction failed")
            return self.runner

        monkeypatch.setattr(worker_main, "get_settings", lambda: self.settings)
        monkeypatch.setattr(worker_main, "create_database_runtime", create_runtime)
        monkeypatch.setattr(worker_main, "ManagementRepository", build_repository)
        monkeypatch.setattr(worker_main, "MinioObjectStorage", build_storage)
        monkeypatch.setattr(worker_main, "MinerUParser", build_parser)
        monkeypatch.setattr(worker_main, "BgeM3Embedder", build_embedder)
        monkeypatch.setattr(worker_main, "build_vector_store", build_store)
        monkeypatch.setattr(worker_main, "IngestionIndexer", build_indexer)
        monkeypatch.setattr(worker_main, "WorkerRunner", build_runner)


class _EvaluationRepository:
    def __init__(self, job: EvaluationJob) -> None:
        self.jobs = [job]
        self.complete_calls: list[dict[str, Any]] = []
        self.fail_calls: list[dict[str, Any]] = []

    def heartbeat_worker(self, **_kwargs: Any) -> None:
        return None

    def claim_ingestion_job(self, **_kwargs: Any) -> None:
        return None

    def claim_evaluation_job(self, **_kwargs: Any) -> EvaluationJob | None:
        return self.jobs.pop(0) if self.jobs else None

    def heartbeat_evaluation_job(self, **_kwargs: Any) -> bool:
        return True

    def complete_evaluation_job(self, **kwargs: Any) -> bool:
        self.complete_calls.append(kwargs)
        return True

    def fail_evaluation_job(self, **kwargs: Any) -> None:
        self.fail_calls.append(kwargs)


def _child_chunks() -> list[ChildChunk]:
    return [
        ChildChunk(
            chunk_id=f"chunk-{index}",
            parent_id="parent-1",
            doc_id="document-1",
            title="Test document",
            doc_type="literature",
            text=f"child text {index}",
            parent_text="parent text",
            metadata={"position": index},
        )
        for index in range(2)
    ]


def _evaluation_job(suite: str = "smoke", *, attempts: int = 1) -> EvaluationJob:
    return EvaluationJob(
        id=f"evaluation-{suite}",
        name=f"{suite} evaluation",
        suite=suite,
        status="running",
        attempts=attempts,
        max_attempts=2,
        requested_by_id="admin-1",
    )


def _evaluation_runner(
    repository: _EvaluationRepository,
    handler: Any,
) -> WorkerRunner:
    return WorkerRunner(
        worker_id="worker-test",
        repository=cast(Any, repository),
        object_storage=cast(Any, object()),
        parser=cast(Any, object()),
        indexer=cast(Any, object()),
        lease_seconds=30,
        heartbeat_seconds=5,
        retry_base_seconds=7,
        poll_seconds=0.1,
        evaluation_handler=handler,
    )


def test_worker_main_cold_import_does_not_load_full_application_dependencies() -> None:
    script = """
import importlib
import sys

importlib.import_module("app.worker.main")
forbidden = ("app.service", "app.llm", "app.retrieval.reranker", "app.workflow")
loaded = sorted(
    name
    for name in sys.modules
    if any(name == prefix or name.startswith(f"{prefix}.") for prefix in forbidden)
)
if loaded:
    raise SystemExit(f"forbidden worker imports: {loaded}")
"""
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr or completed.stdout


def test_factory_injects_default_callable_evaluation_handler_and_closes_resources(
    settings_factory: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = _FactoryHarness(settings_factory(embed_dim=3))
    harness.install(monkeypatch)

    runtime = worker_main.build_worker_runtime("explicit-worker")

    assert harness.runner_kwargs["evaluation_handler"] is evaluation_not_configured_handler
    assert callable(harness.runner_kwargs["evaluation_handler"])
    assert harness.runner_kwargs["parser"] is harness.parser
    assert harness.runner_kwargs["indexer"] is harness.indexer
    assert harness.indexer_kwargs == {
        "embedder": harness.embedder,
        "store": harness.store,
        "dense_dimension": 3,
    }

    runtime.close()
    runtime.close()

    assert harness.engine.dispose_calls == 1
    assert all(resource.close_calls == 1 for resource in harness.resources)


def test_factory_allows_replacing_evaluation_handler(
    settings_factory: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = _FactoryHarness(settings_factory(embed_dim=3))
    harness.install(monkeypatch)

    def custom_handler(_job: EvaluationJob) -> EvaluationResult:
        return EvaluationResult(aggregate_metrics={"score": 1.0})

    runtime = worker_main.build_worker_runtime(evaluation_handler=custom_handler)

    assert harness.runner_kwargs["evaluation_handler"] is custom_handler
    runtime.close()


def test_factory_reclaims_constructed_resources_when_runner_construction_fails(
    settings_factory: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = _FactoryHarness(settings_factory(embed_dim=3), fail_runner=True)
    harness.install(monkeypatch)

    with pytest.raises(RuntimeError, match="runner construction failed"):
        worker_main.build_worker_runtime()

    assert harness.engine.dispose_calls == 1
    assert all(resource.close_calls == 1 for resource in harness.resources)


@pytest.mark.parametrize("suite", ["smoke", "retrieval", "generation", "safety", "full"])
def test_unconfigured_evaluation_is_permanent_for_every_suite(suite: str) -> None:
    repository = _EvaluationRepository(_evaluation_job(suite))
    runner = _evaluation_runner(repository, evaluation_not_configured_handler)

    assert runner.run_once() is True
    assert runner.run_once() is False

    assert repository.complete_calls == []
    assert len(repository.fail_calls) == 1
    failure = repository.fail_calls[0]
    assert failure["error_code"] == EVALUATION_NOT_CONFIGURED
    assert failure["error_message"] == "Evaluation processing failed"
    assert failure["retryable"] is False


def test_ordinary_evaluation_exception_keeps_retry_policy() -> None:
    repository = _EvaluationRepository(_evaluation_job(attempts=2))

    def failing_handler(_job: EvaluationJob) -> NoReturn:
        raise RuntimeError("handler failed")

    runner = _evaluation_runner(repository, failing_handler)

    assert runner.run_once() is True

    assert repository.complete_calls == []
    assert len(repository.fail_calls) == 1
    failure = repository.fail_calls[0]
    assert failure["error_code"] == "runtime_error"
    assert failure["retryable"] is True
    assert failure["retry_delay_seconds"] == 14


@pytest.mark.parametrize(
    "metrics",
    [
        pytest.param({}, id="empty"),
        pytest.param({"": 1.0}, id="empty-key"),
        pytest.param({"   ": 1.0}, id="blank-key"),
        pytest.param({"score": float("nan")}, id="nan"),
        pytest.param({"score": float("inf")}, id="positive-infinity"),
        pytest.param({"score": float("-inf")}, id="negative-infinity"),
    ],
)
def test_invalid_evaluation_metrics_never_succeed(metrics: Mapping[str, float]) -> None:
    repository = _EvaluationRepository(_evaluation_job())

    def invalid_result(_job: EvaluationJob) -> EvaluationResult:
        return EvaluationResult(aggregate_metrics=metrics)

    runner = _evaluation_runner(repository, invalid_result)

    assert runner.run_once() is True

    assert repository.complete_calls == []
    assert len(repository.fail_calls) == 1
    assert repository.fail_calls[0]["retryable"] is True
    assert repository.fail_calls[0]["error_code"] == "value_error"


def test_finite_nonempty_evaluation_metrics_can_succeed() -> None:
    repository = _EvaluationRepository(_evaluation_job())
    metrics = {"faithfulness": 0.75}
    runner = _evaluation_runner(
        repository,
        lambda _job: EvaluationResult(aggregate_metrics=metrics),
    )

    assert runner.run_once() is True

    assert repository.fail_calls == []
    assert len(repository.complete_calls) == 1
    assert repository.complete_calls[0]["aggregate_metrics"] == metrics


@pytest.mark.parametrize(
    ("dense", "sparse", "message"),
    [
        pytest.param(
            [[1.0, 0.0, 0.0]],
            [{1: 1.0}, {2: 1.0}],
            "output count mismatch",
            id="dense-count",
        ),
        pytest.param(
            [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]],
            [{1: 1.0}],
            "output count mismatch",
            id="sparse-count",
        ),
        pytest.param(
            [[1.0, 0.0, 0.0], [0.0, 1.0]],
            [{1: 1.0}, {2: 1.0}],
            "dimension mismatch",
            id="dense-dimension",
        ),
    ],
)
def test_indexer_validates_all_embeddings_before_upsert(
    dense: list[list[float]],
    sparse: list[dict[int, float]],
    message: str,
) -> None:
    embedder = _RecordingEmbedder(dense=dense, sparse=sparse)
    store = _RecordingStore()
    indexer = IngestionIndexer(
        embedder=embedder,
        store=store,
        dense_dimension=3,
    )

    with pytest.raises(ValueError, match=message):
        indexer.index_child_chunks(_child_chunks())

    assert store.upsert_calls == []


def test_indexer_upserts_complete_valid_batch() -> None:
    embedder = _RecordingEmbedder(
        dense=[[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]],
        sparse=[{1: 1.0}, {2: 1.0}],
    )
    store = _RecordingStore()
    indexer = IngestionIndexer(
        embedder=embedder,
        store=store,
        dense_dimension=3,
    )

    inserted = indexer.index_child_chunks(_child_chunks())

    assert inserted == 2
    assert len(store.upsert_calls) == 1
    assert [chunk.chunk_id for chunk in store.upsert_calls[0]] == ["chunk-0", "chunk-1"]
    assert embedder.dense_inputs == ["child text 0", "child text 1"]
    assert embedder.sparse_inputs == embedder.dense_inputs


def test_hybrid_retriever_keeps_index_child_chunks_compatibility_delegate(
    settings_factory: Any,
) -> None:
    chunks = _child_chunks()
    delegated: list[list[ChildChunk]] = []

    class SpyIndexer:
        def index_child_chunks(self, received: list[ChildChunk]) -> int:
            delegated.append(received)
            return 23

    retriever = HybridRetriever(
        settings=settings_factory(embed_dim=3),
        embedder=cast(Any, object()),
        store=cast(Any, object()),
        reranker=cast(Any, object()),
    )
    cast(Any, retriever)._ingestion_indexer = SpyIndexer()

    assert retriever.index_child_chunks(chunks) == 23
    assert delegated == [chunks]
