from __future__ import annotations

import hashlib
import json
from pathlib import Path
from threading import Lock
from typing import Any, cast

import pytest

from app.retrieval.vector_store import (
    CONTENT_SHA256_FIELD,
    INDEX_VISIBILITY_ACTIVE,
    INDEX_VISIBILITY_FIELD,
    INDEX_VISIBILITY_STAGING,
    MANAGED_DOCUMENT_ID_FIELD,
    InMemoryHybridStore,
    ManagedDocumentPointCountMismatch,
)
from app.schemas import IndexedChunk, IngestTextRequest
from app.service import EpilepsyAgentService


def _chunk(
    chunk_id: str,
    *,
    document_id: str,
    content_hash: str,
    visibility: str | None,
) -> IndexedChunk:
    metadata: dict[str, Any] = {
        MANAGED_DOCUMENT_ID_FIELD: document_id,
        CONTENT_SHA256_FIELD: content_hash,
    }
    if visibility is not None:
        metadata[INDEX_VISIBILITY_FIELD] = visibility
    return IndexedChunk(
        chunk_id=chunk_id,
        parent_id=f"parent-{chunk_id}",
        doc_id=document_id,
        title=f"title-{chunk_id}",
        doc_type="literature",
        text=f"evidence-{chunk_id}",
        parent_text=f"parent evidence-{chunk_id}",
        metadata=metadata,
        dense_vector=[1.0, 0.0],
        sparse_vector={1: 1.0},
    )


def _store(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> InMemoryHybridStore:
    monkeypatch.setattr(InMemoryHybridStore, "_persist_path", tmp_path / "knowledge.json")
    return InMemoryHybridStore()


def _search(store: InMemoryHybridStore) -> list[IndexedChunk]:
    return store.hybrid_search(
        query_dense=[1.0, 0.0],
        query_sparse={1: 1.0},
        doc_type=None,
        top_k=20,
        dense_weight=0.5,
        sparse_weight=0.5,
    )


def test_staging_is_hidden_count_checked_and_active_is_visible(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    store = _store(monkeypatch, tmp_path)
    content_hash = "a" * 64
    store.upsert_chunks(
        [
            _chunk(
                "staging",
                document_id="managed-new",
                content_hash=content_hash,
                visibility=INDEX_VISIBILITY_STAGING,
            )
        ]
    )

    assert _search(store) == []
    with pytest.raises(ManagedDocumentPointCountMismatch):
        store.activate_managed_document(
            managed_document_id="managed-new",
            content_sha256=content_hash,
            expected_points=2,
        )
    assert _search(store) == []

    store.activate_managed_document(
        managed_document_id="managed-new",
        content_sha256=content_hash,
        expected_points=1,
    )

    visible = _search(store)
    assert [chunk.chunk_id for chunk in visible] == ["staging"]
    assert visible[0].metadata[INDEX_VISIBILITY_FIELD] == INDEX_VISIBILITY_ACTIVE


def test_missing_visibility_on_current_upsert_defaults_active_but_legacy_disk_data_is_hidden(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    store = _store(monkeypatch, tmp_path)
    store.upsert_chunks(
        [
            _chunk(
                "legacy-api",
                document_id="legacy-api-doc",
                content_hash="b" * 64,
                visibility=None,
            )
        ]
    )
    assert [chunk.chunk_id for chunk in _search(store)] == ["legacy-api"]

    legacy_path = tmp_path / "old-schema.json"
    legacy_path.write_text(
        json.dumps(
            [
                {
                    "chunk_id": "old-schema",
                    "parent_id": "parent-old",
                    "doc_id": "old-doc",
                    "title": "old",
                    "doc_type": "literature",
                    "text": "old evidence",
                    "parent_text": "old parent evidence",
                    "metadata": {},
                    "dense_vector": [1.0, 0.0],
                    "sparse_vector": {"1": 1.0},
                }
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(InMemoryHybridStore, "_persist_path", legacy_path)
    reloaded = InMemoryHybridStore()

    # Historical records without the managed field are not silently promoted.
    assert _search(reloaded) == []


def test_activation_supersedes_only_old_versions_with_the_same_content_hash(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    store = _store(monkeypatch, tmp_path)
    shared_hash = "c" * 64
    unrelated_hash = "d" * 64
    store.upsert_chunks(
        [
            _chunk(
                "old-version",
                document_id="managed-old",
                content_hash=shared_hash,
                visibility=INDEX_VISIBILITY_ACTIVE,
            ),
            _chunk(
                "unrelated",
                document_id="managed-unrelated",
                content_hash=unrelated_hash,
                visibility=INDEX_VISIBILITY_ACTIVE,
            ),
            _chunk(
                "new-version",
                document_id="managed-new",
                content_hash=shared_hash,
                visibility=INDEX_VISIBILITY_STAGING,
            ),
        ]
    )

    store.activate_managed_document(
        managed_document_id="managed-new",
        content_sha256=shared_hash,
        expected_points=1,
    )

    assert {chunk.chunk_id for chunk in _search(store)} == {
        "new-version",
        "unrelated",
    }
    persisted = json.loads((tmp_path / "knowledge.json").read_text(encoding="utf-8"))
    assert {item["chunk_id"] for item in persisted} == {"new-version", "unrelated"}
    for item in persisted:
        assert item[INDEX_VISIBILITY_FIELD] == INDEX_VISIBILITY_ACTIVE
        assert item[MANAGED_DOCUMENT_ID_FIELD]
        assert item[CONTENT_SHA256_FIELD]


def test_uncompensated_failed_or_canceled_staging_never_pollutes_search(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    store = _store(monkeypatch, tmp_path)
    store.upsert_chunks(
        [
            _chunk(
                "failed-staging",
                document_id="failed-document",
                content_hash="e" * 64,
                visibility=INDEX_VISIBILITY_STAGING,
            ),
            _chunk(
                "canceled-staging",
                document_id="canceled-document",
                content_hash="f" * 64,
                visibility=INDEX_VISIBILITY_STAGING,
            ),
        ]
    )

    assert _search(store) == []


class _RecordingLegacyRetriever:
    def __init__(self) -> None:
        self.chunks: list[Any] = []

    def index_child_chunks(self, chunks: list[Any]) -> int:
        self.chunks = chunks
        return len(chunks)


def test_legacy_synchronous_text_ingestion_explicitly_writes_active(
    settings_factory: Any,
) -> None:
    service = cast(Any, object.__new__(EpilepsyAgentService))
    service.settings = settings_factory()
    service.retriever = _RecordingLegacyRetriever()
    service._lock = Lock()
    text = "A sufficiently long legacy ingestion document about epilepsy care."

    response = service.ingest_text(
        IngestTextRequest(
            doc_id="legacy-document",
            title="Legacy document",
            text=text,
            metadata={INDEX_VISIBILITY_FIELD: INDEX_VISIBILITY_STAGING},
        )
    )

    assert response.inserted_children == len(service.retriever.chunks) > 0
    expected_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
    for chunk in service.retriever.chunks:
        assert chunk.metadata[INDEX_VISIBILITY_FIELD] == INDEX_VISIBILITY_ACTIVE
        assert chunk.metadata[MANAGED_DOCUMENT_ID_FIELD] == "legacy-document"
        assert chunk.metadata[CONTENT_SHA256_FIELD] == expected_hash
