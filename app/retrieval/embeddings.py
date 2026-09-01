from __future__ import annotations

from collections.abc import Iterable

from ..config import Settings
from ..utils import hash_token_to_index, normalize_vector, simple_tokenize, tf_sparse_vector


class BgeM3Embedder:
    """
    BGE-M3 向量化抽象层：
    - 优先使用 FlagEmbedding 的 BGEM3 模型输出 dense + sparse。
    - 不可用时回退到确定性的哈希 dense + TF sparse。
    """

    def __init__(self, settings: Settings, model_name: str = "BAAI/bge-m3") -> None:
        self.settings = settings
        self.dim = settings.embed_dim
        self.model_name = model_name
        self.model_path = settings.embed_model_path
        self._model = None
        self._try_init_real_model()

    def _try_init_real_model(self) -> None:
        if self.settings.mock_mode:
            return
        try:
            from FlagEmbedding import BGEM3FlagModel

            self._model = BGEM3FlagModel(self.model_path, use_fp16=True)
        except Exception:
            self._model = None

    def encode_dense(self, texts: Iterable[str]) -> list[list[float]]:
        """
        长这样：[0.012, -0.034, 0.056, ..., 0.089]（1024维浮点数）每个维度都有非零值
        - 语义理解：能理解"狗"和"犬"意思相近。
        优点是能够捕捉更细粒度的语义信息，但需要更多的参数和计算资,且丢失精确关键词信息
        """
        texts = list(texts)
        if not texts:
            return []

        if self._model is not None:
            try:
                out = self._model.encode(
                    texts,
                    batch_size=8,
                    max_length=1024,
                    return_dense=True,
                    return_sparse=False,
                    return_colbert_vecs=False,
                )
                dense = out.get("dense_vecs", [])
                if hasattr(dense, "tolist"):
                    dense = dense.tolist()
                return [normalize_vector([float(x) for x in vec]) for vec in dense]
            except Exception:
                pass
        # # 回退方案：哈希向量，使用哈希函数将文本转换为固定长度的向量
        return [self._hash_dense(text) for text in texts]

    def encode_sparse(self, texts: Iterable[str]) -> list[dict[int, float]]:
        """
        其中大部分维度的值为零，仅少数维度有非零值
        长这样：{1234: 0.8, 5678: 0.5, 9012: 0.3}（字典格式）
        精确关键词匹配：统计词频权重
        但不理解语义, 优点是计算速度快，计算成本低，存储需求小,但召回率较低,可能无法捕捉到所有语义信息
        """
        texts = list(texts)
        if not texts:
            return []

        if self._model is not None:
            try:
                out = self._model.encode(
                    texts,
                    batch_size=8,
                    max_length=1024,
                    return_dense=False,
                    return_sparse=True,
                    return_colbert_vecs=False,
                )
                sparse = out.get("lexical_weights") or out.get("sparse_vecs") or []
                converted: list[dict[int, float]] = []
                for item in sparse:
                    if isinstance(item, dict):
                        converted.append({int(k): float(v) for k, v in item.items()})
                    else:
                        converted.append({})
                if len(converted) == len(texts):
                    return converted
            except Exception:
                pass

        return [tf_sparse_vector(text) for text in texts]

    def embed_query(self, query: str) -> tuple[list[float], dict[int, float]]:
        dense = self.encode_dense([query])[0]
        sparse = self.encode_sparse([query])[0]
        return dense, sparse

    def close(self) -> None:
        close = getattr(self._model, "close", None)
        if callable(close):
            close()
        self._model = None

    def _hash_dense(self, text: str) -> list[float]:
        """
        哈希向量：使用哈希函数将文本转换为固定长度的向量
        """
        vec = [0.0] * self.dim
        tokens = simple_tokenize(text)
        if not tokens:
            return vec
        for token in tokens:
            idx = hash_token_to_index(token, self.dim)
            vec[idx] += 1.0
        return normalize_vector(vec)
