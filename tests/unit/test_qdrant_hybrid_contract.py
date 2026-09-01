from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from uuid import UUID

import pytest
from qdrant_client import models

from app.retrieval.vector_store import (
    CONTENT_SHA256_FIELD,
    INDEX_VISIBILITY_ACTIVE,
    INDEX_VISIBILITY_FIELD,
    INDEX_VISIBILITY_STAGING,
    MANAGED_DOCUMENT_ID_FIELD,
    QdrantCollectionMigrationRequired,
    QdrantHybridStore,
)
from app.schemas import IndexedChunk


class FakeQdrantClient:
    def __init__(self, *, exists: bool = False, collection_info: Any = None) -> None:
        self.exists = exists
        self.collection_info = collection_info
        self.created: list[dict[str, Any]] = []
        self.upserts: list[dict[str, Any]] = []
        self.queries: list[dict[str, Any]] = []
        self.counts: list[dict[str, Any]] = []
        self.payload_updates: list[dict[str, Any]] = []
        self.point_deletes: list[dict[str, Any]] = []
        self.collection_deleted = False
        self.count_value = 0

    def collection_exists(self, _collection: str) -> bool:
        return self.exists

    def create_collection(self, **kwargs: Any) -> None:
        self.created.append(kwargs)
        self.exists = True

    def get_collection(self, **_kwargs: Any) -> Any:
        return self.collection_info

    def upsert(self, **kwargs: Any) -> None:
        self.upserts.append(kwargs)

    def query_points(self, **kwargs: Any) -> Any:
        self.queries.append(kwargs)
        return SimpleNamespace(points=[])

    def count(self, **kwargs: Any) -> Any:
        self.counts.append(kwargs)
        return SimpleNamespace(count=self.count_value)

    def set_payload(self, **kwargs: Any) -> None:
        self.payload_updates.append(kwargs)

    def delete(self, **kwargs: Any) -> None:
        self.point_deletes.append(kwargs)

    def delete_collection(self, **_kwargs: Any) -> None:
        self.collection_deleted = True
        self.exists = False


def _chunk(metadata: dict[str, Any] | None = None) -> IndexedChunk:
    return IndexedChunk(
        chunk_id="not-a-qdrant-id/c_123",
        parent_id="parent",
        doc_id="doc",
        title="title",
        doc_type="clinical",
        text="child evidence",
        parent_text="parent evidence",
        metadata=metadata or {"year": 2024},
        dense_vector=[0.1, 0.2, 0.3],
        sparse_vector={7: 0.4, 2: 0.9},
    )


def _field_matches(point_filter: models.Filter, branch: str = "must") -> dict[str, Any]:
    conditions = getattr(point_filter, branch) or []
    result: dict[str, Any] = {}
    for condition in conditions:
        if not isinstance(condition, models.FieldCondition):
            continue
        match = condition.match
        assert isinstance(match, models.MatchValue)
        result[condition.key] = match.value
    return result


def test_qdrant_sends_named_dense_and_sparse_prefetch_with_rrf(settings_factory) -> None:
    settings = settings_factory(
        use_qdrant=True,
        embed_dim=3,
        dense_top_k=11,
        sparse_top_k=13,
    )
    client = FakeQdrantClient()
    store = QdrantHybridStore(settings, client=client)

    created = client.created[0]
    assert set(created["vectors_config"]) == {"dense"}
    assert set(created["sparse_vectors_config"]) == {"sparse"}
    assert created["vectors_config"]["dense"].size == 3

    store.hybrid_search(
        query_dense=[0.3, 0.2, 0.1],
        query_sparse={2: 1.0, 9: 0.5},
        doc_type="clinical",
        top_k=5,
        dense_weight=0.65,
        sparse_weight=0.35,
    )

    query = client.queries[0]
    prefetch = query["prefetch"]
    assert len(prefetch) == 2
    assert {item.using for item in prefetch} == {"dense", "sparse"}
    dense = next(item for item in prefetch if item.using == "dense")
    sparse = next(item for item in prefetch if item.using == "sparse")
    assert dense.query == [0.3, 0.2, 0.1]
    assert dense.limit == 11
    assert isinstance(sparse.query, models.SparseVector)
    assert sparse.query.indices == [2, 9]
    assert sparse.query.values == [1.0, 0.5]
    assert sparse.limit == 13
    for item in prefetch:
        assert item.filter is not None
        assert _field_matches(item.filter) == {
            INDEX_VISIBILITY_FIELD: INDEX_VISIBILITY_ACTIVE,
            "doc_type": "clinical",
        }
    assert isinstance(query["query"], models.FusionQuery)
    assert query["query"].fusion == models.Fusion.RRF
    assert "query_vector" not in query


def test_qdrant_upsert_defaults_active_and_stores_filter_fields_at_top_level(
    settings_factory,
) -> None:
    settings = settings_factory(use_qdrant=True, embed_dim=3)
    client = FakeQdrantClient()
    store = QdrantHybridStore(settings, client=client)

    store.upsert_chunks([_chunk({"year": 2024, "object_key": "must-not-leak"})])
    upsert = client.upserts[0]
    point = upsert["points"][0]

    UUID(str(point.id))
    assert point.id == QdrantHybridStore._point_id("not-a-qdrant-id/c_123")
    assert point.payload["chunk_id"] == "not-a-qdrant-id/c_123"
    assert point.payload[INDEX_VISIBILITY_FIELD] == INDEX_VISIBILITY_ACTIVE
    assert point.payload[MANAGED_DOCUMENT_ID_FIELD] == "doc"
    assert len(point.payload[CONTENT_SHA256_FIELD]) == 64
    assert "object_key" not in point.payload["metadata"]
    assert set(point.vector) == {"dense", "sparse"}
    assert isinstance(point.vector["sparse"], models.SparseVector)
    assert upsert["wait"] is True


def test_qdrant_activation_counts_current_staging_then_targets_old_same_hash(
    settings_factory,
) -> None:
    settings = settings_factory(use_qdrant=True, embed_dim=3)
    client = FakeQdrantClient()
    client.count_value = 1
    store = QdrantHybridStore(settings, client=client)
    content_hash = "a" * 64

    store.upsert_chunks(
        [
            _chunk(
                {
                    INDEX_VISIBILITY_FIELD: INDEX_VISIBILITY_STAGING,
                    MANAGED_DOCUMENT_ID_FIELD: "new-document",
                    CONTENT_SHA256_FIELD: content_hash,
                }
            )
        ]
    )
    point = client.upserts[0]["points"][0]
    assert point.payload[INDEX_VISIBILITY_FIELD] == INDEX_VISIBILITY_STAGING

    store.activate_managed_document(
        managed_document_id="new-document",
        content_sha256=content_hash,
        expected_points=1,
    )

    count_filter = client.counts[0]["count_filter"]
    assert _field_matches(count_filter) == {
        MANAGED_DOCUMENT_ID_FIELD: "new-document",
        CONTENT_SHA256_FIELD: content_hash,
    }
    update = client.payload_updates[0]
    assert update["payload"] == {INDEX_VISIBILITY_FIELD: INDEX_VISIBILITY_ACTIVE}
    assert update["points"] == count_filter
    assert update["wait"] is True

    deletion = client.point_deletes[0]
    delete_filter = deletion["points_selector"].filter
    assert _field_matches(delete_filter) == {CONTENT_SHA256_FIELD: content_hash}
    assert _field_matches(delete_filter, "must_not") == {MANAGED_DOCUMENT_ID_FIELD: "new-document"}
    assert deletion["wait"] is True
    assert client.collection_deleted is False


def test_qdrant_document_cleanup_is_filtered_and_never_clears_collection(
    settings_factory,
) -> None:
    settings = settings_factory(use_qdrant=True, embed_dim=3)
    client = FakeQdrantClient()
    store = QdrantHybridStore(settings, client=client)

    store.delete_managed_document(managed_document_id="only-this-document")

    deletion = client.point_deletes[0]
    point_filter = deletion["points_selector"].filter
    assert _field_matches(point_filter) == {MANAGED_DOCUMENT_ID_FIELD: "only-this-document"}
    assert client.collection_deleted is False


def test_incompatible_existing_collection_requires_explicit_migration(
    settings_factory,
) -> None:
    settings = settings_factory(use_qdrant=True, embed_dim=3)
    old_params = SimpleNamespace(
        vectors=models.VectorParams(size=3, distance=models.Distance.COSINE),
        sparse_vectors=None,
    )
    client = FakeQdrantClient(
        exists=True,
        collection_info=SimpleNamespace(config=SimpleNamespace(params=old_params)),
    )

    with pytest.raises(QdrantCollectionMigrationRequired, match="migration required"):
        QdrantHybridStore(settings, client=client)

    assert client.created == []
    assert client.collection_deleted is False
