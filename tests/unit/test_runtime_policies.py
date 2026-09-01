"""Regression tests for storage selection and production ingestion policy."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

import app.retrieval.vector_store as vector_store
import app.service as service_module
from app.schemas import IngestTextRequest
from app.service import EpilepsyAgentService, GroundTruthIngestionForbidden


def test_qdrant_failure_never_falls_back_to_json_in_production(
    settings_factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = settings_factory(environment="production", use_qdrant=True)

    class FailingQdrantStore:
        def __init__(self, _settings: Any) -> None:
            raise ConnectionError("qdrant unavailable")

    class ForbiddenJsonStore:
        def __init__(self) -> None:
            pytest.fail("production silently fell back to the JSON store")

    monkeypatch.setattr(vector_store, "QdrantHybridStore", FailingQdrantStore)
    monkeypatch.setattr(vector_store, "InMemoryHybridStore", ForbiddenJsonStore)

    with pytest.raises(ConnectionError, match="qdrant unavailable"):
        vector_store.build_vector_store(settings)


def test_json_store_is_rejected_outside_explicit_dev_or_test(
    settings_factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = settings_factory(environment="production", use_qdrant=False)

    class ForbiddenJsonStore:
        def __init__(self) -> None:
            pytest.fail("production constructed the JSON store")

    monkeypatch.setattr(vector_store, "InMemoryHybridStore", ForbiddenJsonStore)

    with pytest.raises(RuntimeError, match="restricted to explicit dev/test"):
        vector_store.build_vector_store(settings)


def test_json_store_uses_only_a_temporary_path_in_tests(
    settings_factory,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    persist_path = tmp_path / "isolated-data" / "knowledge_base.json"
    monkeypatch.setattr(vector_store.InMemoryHybridStore, "_persist_path", persist_path)

    store = vector_store.build_vector_store(settings_factory(environment="test"))

    assert isinstance(store, vector_store.InMemoryHybridStore)
    assert store._persist_path == persist_path
    assert store.count() == 0
    assert not persist_path.exists()


@pytest.mark.parametrize(
    ("source", "metadata"),
    [
        pytest.param("ground_truth", {}, id="request-source"),
        pytest.param("manual", {"source": "ground_truth"}, id="metadata-source"),
        pytest.param("manual", {"is_ground_truth": True}, id="metadata-flag"),
        pytest.param("manual", {"is_ground_truth": "yes"}, id="metadata-string-flag"),
    ],
)
def test_production_ingestion_rejects_ground_truth_before_indexing(
    source: str,
    metadata: dict[str, Any],
    settings_factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = settings_factory(environment="production", use_qdrant=True)
    service = object.__new__(EpilepsyAgentService)
    service.settings = settings

    def indexing_must_not_start(*_args: Any, **_kwargs: Any) -> None:
        pytest.fail("ground-truth validation ran after indexing started")

    monkeypatch.setattr(service_module, "build_parent_child_chunks", indexing_must_not_start)
    request = IngestTextRequest(
        doc_id="evaluation-only",
        title="Evaluation truth",
        text="This text is long enough for schema validation.",
        source=source,
        metadata=metadata,
    )

    with pytest.raises(GroundTruthIngestionForbidden, match="cannot be ingested"):
        service.ingest_text(request)
