from __future__ import annotations

import hashlib
import json
import logging
import uuid
from abc import ABC, abstractmethod
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from ..config import Settings
from ..schemas import IndexedChunk
from ..utils import cosine_similarity, sparse_dot

logger = logging.getLogger(__name__)

INDEX_VISIBILITY_FIELD = "index_visibility"
MANAGED_DOCUMENT_ID_FIELD = "managed_document_id"
CONTENT_SHA256_FIELD = "content_sha256"
INDEX_VISIBILITY_ACTIVE = "active"
INDEX_VISIBILITY_STAGING = "staging"
_MANAGED_PAYLOAD_FIELDS = (
    INDEX_VISIBILITY_FIELD,
    MANAGED_DOCUMENT_ID_FIELD,
    CONTENT_SHA256_FIELD,
)
_PRIVATE_METADATA_FIELDS = frozenset({"object_bucket", "object_key"})


class ManagedDocumentPointCountMismatch(RuntimeError):
    """Raised before activation when a managed document is not fully present."""


def _fallback_content_sha256(chunk: IndexedChunk) -> str:
    content = f"{chunk.doc_id}\0{chunk.title}\0{chunk.parent_text}".encode()
    return hashlib.sha256(content).hexdigest()


def _normalize_chunk_for_upsert(chunk: IndexedChunk) -> IndexedChunk:
    metadata = {
        key: value for key, value in chunk.metadata.items() if key not in _PRIVATE_METADATA_FIELDS
    }
    visibility = str(metadata.get(INDEX_VISIBILITY_FIELD) or INDEX_VISIBILITY_ACTIVE)
    if visibility not in {INDEX_VISIBILITY_ACTIVE, INDEX_VISIBILITY_STAGING}:
        raise ValueError("index_visibility must be active or staging")

    managed_document_id = str(
        metadata.get(MANAGED_DOCUMENT_ID_FIELD) or chunk.doc_id or chunk.chunk_id
    )
    content_sha256 = str(metadata.get(CONTENT_SHA256_FIELD) or _fallback_content_sha256(chunk))
    metadata.update(
        {
            INDEX_VISIBILITY_FIELD: visibility,
            MANAGED_DOCUMENT_ID_FIELD: managed_document_id,
            CONTENT_SHA256_FIELD: content_sha256,
        }
    )
    return chunk.model_copy(update={"metadata": metadata})


def _metadata_value(chunk: IndexedChunk, key: str) -> str:
    value = chunk.metadata.get(key)
    return str(value) if value is not None else ""


class BaseHybridStore(ABC):
    @abstractmethod
    def upsert_chunks(self, chunks: list[IndexedChunk]) -> None:
        raise NotImplementedError

    @abstractmethod
    def activate_managed_document(
        self,
        *,
        managed_document_id: str,
        content_sha256: str,
        expected_points: int,
    ) -> None:
        """Activate one complete version and remove other versions of the same content."""

    @abstractmethod
    def delete_managed_document(self, *, managed_document_id: str) -> None:
        """Idempotently delete only points owned by one managed document."""

    @abstractmethod
    def hybrid_search(
        self,
        query_dense: list[float],
        query_sparse: dict[int, float],
        doc_type: str | None,
        top_k: int,
        dense_weight: float,
        sparse_weight: float,
    ) -> list[IndexedChunk]:
        raise NotImplementedError

    @abstractmethod
    def count(self) -> int:
        raise NotImplementedError

    @abstractmethod
    def clear(self) -> None:
        """清空所有数据（用于重新入库）"""


class InMemoryHybridStore(BaseHybridStore):
    """内存版向量存储，支持 JSON 文件持久化（重启不丢数据）。

    数据保存在 data/knowledge_base.json，重启后自动加载。历史缺少
    index_visibility 的记录不会被查询命中，需通过受控重摄取迁移。
    """

    _persist_path = Path(__file__).resolve().parents[2] / "data" / "knowledge_base.json"

    def __init__(self) -> None:
        self._chunks: dict[str, IndexedChunk] = {}
        self._load_from_disk()

    def _load_from_disk(self) -> None:
        """启动时从 JSON 文件加载已有数据，实现持久化。"""
        path = self._persist_path
        if not path.exists():
            return
        try:
            with path.open(encoding="utf-8") as file:
                raw = json.load(file)
            for item in raw:
                chunk = self._dict_to_chunk(item)
                self._chunks[chunk.chunk_id] = chunk
            logger.info("Loaded %d chunks from disk", len(self._chunks))
        except Exception as exc:
            logger.warning("Failed to load KB from disk: %s", exc)

    def _save_to_disk(self) -> None:
        """Persist the current snapshot atomically or report failure to the caller."""
        path = self._persist_path
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        try:
            with temporary_path.open("w", encoding="utf-8") as file:
                json.dump(
                    [self._chunk_to_dict(chunk) for chunk in self._chunks.values()],
                    file,
                    ensure_ascii=False,
                )
            temporary_path.replace(path)
        except Exception as exc:
            temporary_path.unlink(missing_ok=True)
            raise RuntimeError("Vector store persistence failed") from exc

    @staticmethod
    def _chunk_to_dict(chunk: IndexedChunk) -> dict[str, Any]:
        return {
            "chunk_id": chunk.chunk_id,
            "parent_id": chunk.parent_id,
            "doc_id": chunk.doc_id,
            "title": chunk.title,
            "doc_type": chunk.doc_type,
            "text": chunk.text,
            "parent_text": chunk.parent_text,
            "metadata": chunk.metadata,
            INDEX_VISIBILITY_FIELD: chunk.metadata.get(INDEX_VISIBILITY_FIELD),
            MANAGED_DOCUMENT_ID_FIELD: chunk.metadata.get(MANAGED_DOCUMENT_ID_FIELD),
            CONTENT_SHA256_FIELD: chunk.metadata.get(CONTENT_SHA256_FIELD),
            "dense_vector": chunk.dense_vector,
            "sparse_vector": chunk.sparse_vector,
        }

    @staticmethod
    def _dict_to_chunk(data: dict[str, Any]) -> IndexedChunk:
        raw_metadata = data.get("metadata", {})
        metadata = dict(raw_metadata) if isinstance(raw_metadata, Mapping) else {}
        for field in _MANAGED_PAYLOAD_FIELDS:
            if data.get(field) is not None:
                metadata[field] = data[field]
        for field in _PRIVATE_METADATA_FIELDS:
            metadata.pop(field, None)
        return IndexedChunk(
            chunk_id=data["chunk_id"],
            parent_id=data.get("parent_id", ""),
            doc_id=data.get("doc_id", ""),
            title=data.get("title", ""),
            doc_type=data.get("doc_type", "clinical"),
            text=data.get("text", ""),
            parent_text=data.get("parent_text", ""),
            metadata=metadata,
            dense_vector=data.get("dense_vector", []),
            sparse_vector={
                int(key): float(value) for key, value in data.get("sparse_vector", {}).items()
            },
        )

    def upsert_chunks(self, chunks: list[IndexedChunk]) -> None:
        if not chunks:
            return
        for chunk in chunks:
            normalized = _normalize_chunk_for_upsert(chunk)
            self._chunks[normalized.chunk_id] = normalized
        self._save_to_disk()

    def activate_managed_document(
        self,
        *,
        managed_document_id: str,
        content_sha256: str,
        expected_points: int,
    ) -> None:
        if expected_points <= 0:
            raise ValueError("expected_points must be positive")

        current_ids = [
            chunk_id
            for chunk_id, chunk in self._chunks.items()
            if _metadata_value(chunk, MANAGED_DOCUMENT_ID_FIELD) == managed_document_id
            and _metadata_value(chunk, CONTENT_SHA256_FIELD) == content_sha256
        ]
        if len(current_ids) != expected_points:
            raise ManagedDocumentPointCountMismatch(
                "Managed document point count did not match the completed ingestion batch"
            )

        for chunk_id in current_ids:
            chunk = self._chunks[chunk_id]
            metadata = {**chunk.metadata, INDEX_VISIBILITY_FIELD: INDEX_VISIBILITY_ACTIVE}
            self._chunks[chunk_id] = chunk.model_copy(update={"metadata": metadata})

        stale_ids = [
            chunk_id
            for chunk_id, chunk in self._chunks.items()
            if _metadata_value(chunk, CONTENT_SHA256_FIELD) == content_sha256
            and _metadata_value(chunk, MANAGED_DOCUMENT_ID_FIELD) != managed_document_id
        ]
        for chunk_id in stale_ids:
            del self._chunks[chunk_id]
        self._save_to_disk()

    def delete_managed_document(self, *, managed_document_id: str) -> None:
        owned_ids = [
            chunk_id
            for chunk_id, chunk in self._chunks.items()
            if _metadata_value(chunk, MANAGED_DOCUMENT_ID_FIELD) == managed_document_id
        ]
        if not owned_ids:
            return
        for chunk_id in owned_ids:
            del self._chunks[chunk_id]
        self._save_to_disk()

    def hybrid_search(
        self,
        query_dense: list[float],
        query_sparse: dict[int, float],
        doc_type: str | None,
        top_k: int,
        dense_weight: float,
        sparse_weight: float,
    ) -> list[IndexedChunk]:
        scored: list[IndexedChunk] = []
        for chunk in self._chunks.values():
            if _metadata_value(chunk, INDEX_VISIBILITY_FIELD) != INDEX_VISIBILITY_ACTIVE:
                continue
            if doc_type and chunk.doc_type != doc_type:
                continue

            dense_score = cosine_similarity(query_dense, chunk.dense_vector)
            sparse_score = sparse_dot(query_sparse, chunk.sparse_vector)
            final_score = dense_weight * dense_score + sparse_weight * sparse_score

            if final_score <= 0:
                continue
            scored.append(chunk.model_copy(update={"score": float(final_score)}))

        scored.sort(key=lambda chunk: chunk.score, reverse=True)
        return scored[:top_k]

    def count(self) -> int:
        return len(self._chunks)

    def clear(self) -> None:
        self._chunks.clear()
        if self._persist_path.exists():
            self._persist_path.unlink()
        logger.info("Knowledge base cleared.")


class QdrantCollectionMigrationRequired(RuntimeError):
    """Raised when an existing collection predates the named hybrid schema."""


class QdrantHybridStore(BaseHybridStore):
    DENSE_VECTOR_NAME = "dense"
    SPARSE_VECTOR_NAME = "sparse"

    def __init__(self, settings: Settings, client: Any | None = None) -> None:
        try:
            from qdrant_client import QdrantClient, models
        except Exception as exc:
            raise RuntimeError("qdrant-client is not installed.") from exc

        self.settings = settings
        self.collection = settings.qdrant_collection
        self._models = models
        self.client = client or QdrantClient(
            url=settings.qdrant_url,
            api_key=settings.qdrant_api_key or None,
        )
        self._ensure_collection()

    def _collection_exists(self) -> bool:
        collection_exists = getattr(self.client, "collection_exists", None)
        if callable(collection_exists):
            return bool(collection_exists(self.collection))

        collections = self.client.get_collections().collections
        return any(collection.name == self.collection for collection in collections)

    def _ensure_collection(self) -> None:
        if self._collection_exists():
            self._validate_collection_schema()
            return

        self.client.create_collection(
            collection_name=self.collection,
            vectors_config={
                self.DENSE_VECTOR_NAME: self._models.VectorParams(
                    size=self.settings.embed_dim,
                    distance=self._models.Distance.COSINE,
                )
            },
            sparse_vectors_config={self.SPARSE_VECTOR_NAME: self._models.SparseVectorParams()},
        )

    def _validate_collection_schema(self) -> None:
        info = self.client.get_collection(collection_name=self.collection)
        params = getattr(getattr(info, "config", None), "params", None)
        vectors = getattr(params, "vectors", None)
        sparse_vectors = getattr(params, "sparse_vectors", None)

        compatible = isinstance(vectors, Mapping) and isinstance(sparse_vectors, Mapping)
        dense_config = vectors.get(self.DENSE_VECTOR_NAME) if isinstance(vectors, Mapping) else None
        sparse_config = (
            sparse_vectors.get(self.SPARSE_VECTOR_NAME)
            if isinstance(sparse_vectors, Mapping)
            else None
        )
        compatible = compatible and dense_config is not None and sparse_config is not None

        if dense_config is not None:
            actual_size = getattr(dense_config, "size", None)
            actual_distance = getattr(dense_config, "distance", None)
            expected_distance = self._models.Distance.COSINE
            actual_distance_value = str(
                getattr(actual_distance, "value", actual_distance)
            ).casefold()
            expected_distance_value = str(
                getattr(expected_distance, "value", expected_distance)
            ).casefold()
            compatible = (
                compatible
                and actual_size == self.settings.embed_dim
                and actual_distance_value == expected_distance_value
            )

        if not compatible:
            raise QdrantCollectionMigrationRequired(
                "Qdrant collection migration required: expected named dense and sparse "
                "vectors with the configured dense dimension; the existing collection "
                "was not modified"
            )

    @staticmethod
    def _point_id(chunk_id: str) -> str:
        """Map arbitrary business IDs to stable Qdrant-compatible UUIDs."""
        return str(uuid.uuid5(uuid.NAMESPACE_URL, f"epilepsy-qa:chunk:{chunk_id}"))

    def _field_condition(self, key: str, value: str) -> Any:
        return self._models.FieldCondition(
            key=key,
            match=self._models.MatchValue(value=value),
        )

    def _managed_document_filter(
        self,
        *,
        managed_document_id: str,
        content_sha256: str | None = None,
    ) -> Any:
        conditions = [self._field_condition(MANAGED_DOCUMENT_ID_FIELD, managed_document_id)]
        if content_sha256 is not None:
            conditions.append(self._field_condition(CONTENT_SHA256_FIELD, content_sha256))
        return self._models.Filter(must=conditions)

    def upsert_chunks(self, chunks: list[IndexedChunk]) -> None:
        points: list[Any] = []
        for raw_chunk in chunks:
            chunk = _normalize_chunk_for_upsert(raw_chunk)
            if len(chunk.dense_vector) != self.settings.embed_dim:
                raise ValueError(
                    f"dense vector dimension must be {self.settings.embed_dim}, "
                    f"got {len(chunk.dense_vector)}"
                )

            sparse_items = sorted(chunk.sparse_vector.items())
            payload = {
                "chunk_id": chunk.chunk_id,
                "parent_id": chunk.parent_id,
                "doc_id": chunk.doc_id,
                "title": chunk.title,
                "doc_type": chunk.doc_type,
                "text": chunk.text,
                "parent_text": chunk.parent_text,
                "metadata": chunk.metadata,
                INDEX_VISIBILITY_FIELD: chunk.metadata[INDEX_VISIBILITY_FIELD],
                MANAGED_DOCUMENT_ID_FIELD: chunk.metadata[MANAGED_DOCUMENT_ID_FIELD],
                CONTENT_SHA256_FIELD: chunk.metadata[CONTENT_SHA256_FIELD],
            }
            points.append(
                self._models.PointStruct(
                    id=self._point_id(chunk.chunk_id),
                    vector={
                        self.DENSE_VECTOR_NAME: chunk.dense_vector,
                        self.SPARSE_VECTOR_NAME: self._models.SparseVector(
                            indices=[index for index, _ in sparse_items],
                            values=[float(value) for _, value in sparse_items],
                        ),
                    },
                    payload=payload,
                )
            )

        if points:
            self.client.upsert(
                collection_name=self.collection,
                points=points,
                wait=True,
            )

    def activate_managed_document(
        self,
        *,
        managed_document_id: str,
        content_sha256: str,
        expected_points: int,
    ) -> None:
        if expected_points <= 0:
            raise ValueError("expected_points must be positive")

        current_filter = self._managed_document_filter(
            managed_document_id=managed_document_id,
            content_sha256=content_sha256,
        )
        current_count = self.client.count(
            collection_name=self.collection,
            count_filter=current_filter,
            exact=True,
        )
        if int(current_count.count) != expected_points:
            raise ManagedDocumentPointCountMismatch(
                "Managed document point count did not match the completed ingestion batch"
            )

        self.client.set_payload(
            collection_name=self.collection,
            payload={INDEX_VISIBILITY_FIELD: INDEX_VISIBILITY_ACTIVE},
            points=current_filter,
            wait=True,
        )
        old_versions_filter = self._models.Filter(
            must=[self._field_condition(CONTENT_SHA256_FIELD, content_sha256)],
            must_not=[self._field_condition(MANAGED_DOCUMENT_ID_FIELD, managed_document_id)],
        )
        self.client.delete(
            collection_name=self.collection,
            points_selector=self._models.FilterSelector(filter=old_versions_filter),
            wait=True,
        )

    def delete_managed_document(self, *, managed_document_id: str) -> None:
        point_filter = self._managed_document_filter(managed_document_id=managed_document_id)
        self.client.delete(
            collection_name=self.collection,
            points_selector=self._models.FilterSelector(filter=point_filter),
            wait=True,
        )

    def hybrid_search(
        self,
        query_dense: list[float],
        query_sparse: dict[int, float],
        doc_type: str | None,
        top_k: int,
        dense_weight: float,
        sparse_weight: float,
    ) -> list[IndexedChunk]:
        if len(query_dense) != self.settings.embed_dim:
            raise ValueError(
                f"dense query dimension must be {self.settings.embed_dim}, "
                f"got {len(query_dense)}"
            )

        filter_conditions = [self._field_condition(INDEX_VISIBILITY_FIELD, INDEX_VISIBILITY_ACTIVE)]
        if doc_type:
            filter_conditions.append(self._field_condition("doc_type", doc_type))
        query_filter = self._models.Filter(must=filter_conditions)

        sparse_items = sorted(query_sparse.items())
        dense_prefetch = self._models.Prefetch(
            query=query_dense,
            using=self.DENSE_VECTOR_NAME,
            filter=query_filter,
            limit=max(self.settings.dense_top_k, top_k),
        )
        sparse_prefetch = self._models.Prefetch(
            query=self._models.SparseVector(
                indices=[index for index, _ in sparse_items],
                values=[float(value) for _, value in sparse_items],
            ),
            using=self.SPARSE_VECTOR_NAME,
            filter=query_filter,
            limit=max(self.settings.sparse_top_k, top_k),
        )

        # RRF combines independently retrieved dense and sparse candidates. The
        # legacy weights stay in the interface for the in-memory adapter but are
        # intentionally not applied to Qdrant's rank-based fusion.
        result = self.client.query_points(
            collection_name=self.collection,
            prefetch=[dense_prefetch, sparse_prefetch],
            query=self._models.FusionQuery(fusion=self._models.Fusion.RRF),
            limit=top_k,
            with_payload=True,
            with_vectors=False,
        )

        fused: list[IndexedChunk] = []
        for hit in result.points:
            payload = dict(hit.payload or {})
            raw_metadata = payload.get("metadata", {})
            metadata = dict(raw_metadata) if isinstance(raw_metadata, Mapping) else {}
            for field in _MANAGED_PAYLOAD_FIELDS:
                if payload.get(field) is not None:
                    metadata[field] = payload[field]
            for field in _PRIVATE_METADATA_FIELDS:
                metadata.pop(field, None)
            fused.append(
                IndexedChunk(
                    chunk_id=str(payload.get("chunk_id", hit.id)),
                    parent_id=str(payload.get("parent_id", "")),
                    doc_id=str(payload.get("doc_id", "")),
                    title=str(payload.get("title", "")),
                    doc_type=str(payload.get("doc_type", "")),
                    text=str(payload.get("text", "")),
                    parent_text=str(payload.get("parent_text", "")),
                    metadata=metadata,
                    dense_vector=[],
                    sparse_vector={},
                    score=float(hit.score or 0.0),
                )
            )

        return fused

    def close(self) -> None:
        close = getattr(self.client, "close", None)
        if callable(close):
            close()

    def count(self) -> int:
        result = self.client.count(collection_name=self.collection, exact=True)
        return int(result.count)

    def clear(self) -> None:
        if self._collection_exists():
            self.client.delete_collection(collection_name=self.collection)
        self._ensure_collection()


def build_vector_store(settings: Settings) -> BaseHybridStore:
    """Build the explicitly selected store without cross-backend fallback."""
    if settings.use_qdrant:
        # Authentication, connectivity, and collection errors are fatal. In
        # particular, production must never continue against a local JSON file.
        return QdrantHybridStore(settings)

    environment = settings.environment.strip().casefold()
    if environment not in {"dev", "development", "test", "testing"}:
        raise RuntimeError(
            "The JSON vector store is restricted to explicit dev/test environments; "
            "enable Qdrant for this environment"
        )
    return InMemoryHybridStore()
