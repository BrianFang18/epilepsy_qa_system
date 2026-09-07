from __future__ import annotations

from collections.abc import Iterable

from ..config import Settings
from ..utils import hash_token_to_index, normalize_vector, simple_tokenize, tf_sparse_vector


class DeterministicHashTfEmbedder:
    """Dependency-free local demo vectors; this is explicitly not BGE-M3."""

    backend_version = "deterministic-md5-tf-v2"

    def __init__(self, settings: Settings) -> None:
        self.dim = settings.embed_dim

    def encode_dense(self, texts: Iterable[str]) -> list[list[float]]:
        return [self._hash_dense(text) for text in texts]

    @staticmethod
    def encode_sparse(texts: Iterable[str]) -> list[dict[int, float]]:
        return [tf_sparse_vector(text) for text in texts]

    def embed_query(self, query: str) -> tuple[list[float], dict[int, float]]:
        return self.encode_dense([query])[0], self.encode_sparse([query])[0]

    def close(self) -> None:
        return None

    def _hash_dense(self, text: str) -> list[float]:
        vector = [0.0] * self.dim
        tokens = simple_tokenize(text)
        for token in tokens:
            vector[hash_token_to_index(token, self.dim)] += 1.0
        return normalize_vector(vector)


class BgeM3Embedder:
    """BGE-M3 adapter with an opt-out legacy deterministic fallback.

    Legacy API paths retain the fallback for compatibility. Managed BGE ingestion
    disables it after startup validation so a runtime model failure cannot be
    labelled and indexed as BGE output.
    """

    def __init__(self, settings: Settings, model_name: str | None = None) -> None:
        self.settings = settings
        self.dim = settings.embed_dim
        self.model_name = model_name or settings.embed_model_name
        self.model_path = settings.embed_model_path
        self._fallback = DeterministicHashTfEmbedder(settings)
        self._fallback_enabled = True
        self._model = None
        self._try_init_real_model()

    @property
    def using_real_model(self) -> bool:
        return self._model is not None

    @property
    def backend_version(self) -> str:
        if self.using_real_model:
            return f"bge-m3:{self.model_name}"
        return self._fallback.backend_version

    def disable_fallback(self) -> None:
        """Require every subsequent embedding operation to use BGE-M3."""

        self._fallback_enabled = False

    def _try_init_real_model(self) -> None:
        if self.settings.mock_mode:
            return
        try:
            from FlagEmbedding import BGEM3FlagModel

            self._model = BGEM3FlagModel(self.model_path, use_fp16=True)
        except Exception:
            self._model = None

    def _handle_runtime_failure(self, operation: str, exc: Exception) -> None:
        self._model = None
        if not self._fallback_enabled:
            raise RuntimeError(
                f"BGE-M3 {operation} failed; deterministic fallback is disabled"
            ) from exc

    def encode_dense(self, texts: Iterable[str]) -> list[list[float]]:
        values = list(texts)
        if not values:
            return []
        if self._model is not None:
            try:
                output = self._model.encode(
                    values,
                    batch_size=8,
                    max_length=1024,
                    return_dense=True,
                    return_sparse=False,
                    return_colbert_vecs=False,
                )
                dense = output.get("dense_vecs", [])
                if hasattr(dense, "tolist"):
                    dense = dense.tolist()
                converted = [normalize_vector([float(item) for item in vector]) for vector in dense]
            except Exception as exc:
                self._handle_runtime_failure("dense embedding", exc)
            else:
                if len(converted) == len(values):
                    return converted
                self._handle_runtime_failure(
                    "dense embedding",
                    ValueError("BGE-M3 dense output count mismatch"),
                )
        if not self._fallback_enabled:
            raise RuntimeError("BGE-M3 dense embedding is unavailable")
        return self._fallback.encode_dense(values)

    def encode_sparse(self, texts: Iterable[str]) -> list[dict[int, float]]:
        values = list(texts)
        if not values:
            return []
        if self._model is not None:
            try:
                output = self._model.encode(
                    values,
                    batch_size=8,
                    max_length=1024,
                    return_dense=False,
                    return_sparse=True,
                    return_colbert_vecs=False,
                )
                sparse = output.get("lexical_weights") or output.get("sparse_vecs") or []
                converted: list[dict[int, float]] = []
                for item in sparse:
                    converted.append(
                        {int(key): float(value) for key, value in item.items()}
                        if isinstance(item, dict)
                        else {}
                    )
            except Exception as exc:
                self._handle_runtime_failure("sparse embedding", exc)
            else:
                if len(converted) == len(values):
                    return converted
                self._handle_runtime_failure(
                    "sparse embedding",
                    ValueError("BGE-M3 sparse output count mismatch"),
                )
        if not self._fallback_enabled:
            raise RuntimeError("BGE-M3 sparse embedding is unavailable")
        return self._fallback.encode_sparse(values)

    def embed_query(self, query: str) -> tuple[list[float], dict[int, float]]:
        return self.encode_dense([query])[0], self.encode_sparse([query])[0]

    def close(self) -> None:
        close = getattr(self._model, "close", None)
        if callable(close):
            close()
        self._model = None
