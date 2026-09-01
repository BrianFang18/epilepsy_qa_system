from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol

from app.schemas import IndexedChunk

from .chunking import ChildChunk


class IngestionEmbedder(Protocol):
    def encode_dense(self, texts: Iterable[str]) -> list[list[float]]: ...

    def encode_sparse(self, texts: Iterable[str]) -> list[dict[int, float]]: ...


class IngestionStore(Protocol):
    def upsert_chunks(self, chunks: list[IndexedChunk]) -> None: ...

    def activate_managed_document(
        self,
        *,
        managed_document_id: str,
        content_sha256: str,
        expected_points: int,
    ) -> None: ...

    def delete_managed_document(self, *, managed_document_id: str) -> None: ...


class IngestionIndexer:
    """Build and persist ingestion vectors without retrieval-time dependencies."""

    def __init__(
        self,
        *,
        embedder: IngestionEmbedder,
        store: IngestionStore,
        dense_dimension: int,
    ) -> None:
        if dense_dimension <= 0:
            raise ValueError("dense_dimension must be positive")
        self.embedder = embedder
        self.store = store
        self.dense_dimension = dense_dimension

    def index_child_chunks(self, chunks: list[ChildChunk]) -> int:
        if not chunks:
            return 0

        texts = [chunk.text for chunk in chunks]
        dense_vectors = self.embedder.encode_dense(texts)
        sparse_vectors = self.embedder.encode_sparse(texts)
        self._validate_embeddings(
            chunk_count=len(chunks),
            dense_vectors=dense_vectors,
            sparse_vectors=sparse_vectors,
        )

        indexed = [
            IndexedChunk(
                chunk_id=chunk.chunk_id,
                parent_id=chunk.parent_id,
                doc_id=chunk.doc_id,
                title=chunk.title,
                doc_type=chunk.doc_type,
                text=chunk.text,
                parent_text=chunk.parent_text,
                metadata=chunk.metadata,
                dense_vector=dense,
                sparse_vector=sparse,
            )
            for chunk, dense, sparse in zip(chunks, dense_vectors, sparse_vectors, strict=True)
        ]
        self.store.upsert_chunks(indexed)
        return len(indexed)

    def activate_managed_document(
        self,
        *,
        managed_document_id: str,
        content_sha256: str,
        expected_points: int,
    ) -> None:
        self.store.activate_managed_document(
            managed_document_id=managed_document_id,
            content_sha256=content_sha256,
            expected_points=expected_points,
        )

    def delete_managed_document(self, *, managed_document_id: str) -> None:
        self.store.delete_managed_document(managed_document_id=managed_document_id)

    def _validate_embeddings(
        self,
        *,
        chunk_count: int,
        dense_vectors: list[list[float]],
        sparse_vectors: list[dict[int, float]],
    ) -> None:
        if len(dense_vectors) != chunk_count or len(sparse_vectors) != chunk_count:
            raise ValueError(
                "Embedding output count mismatch: "
                f"chunks={chunk_count}, dense={len(dense_vectors)}, "
                f"sparse={len(sparse_vectors)}"
            )

        invalid_dimensions = sorted(
            {len(vector) for vector in dense_vectors if len(vector) != self.dense_dimension}
        )
        if invalid_dimensions:
            actual = ", ".join(str(dimension) for dimension in invalid_dimensions)
            raise ValueError(
                "Dense embedding dimension mismatch: "
                f"expected={self.dense_dimension}, actual={actual}"
            )
