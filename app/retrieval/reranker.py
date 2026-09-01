from __future__ import annotations

from ..config import Settings
from ..schemas import IndexedChunk
from ..utils import simple_tokenize


class BGEReranker:
    """
    BGE 重排器封装。
    当模型不可用时，回退为词项重叠重排。
    """

    def __init__(self, settings: Settings, model_name: str = "BAAI/bge-reranker-v2-m3") -> None:
        self.settings = settings
        self.model_name = model_name
        self.model_path = settings.reranker_model_path
        self._model = None
        self._try_init_real_model()

    def _try_init_real_model(self) -> None:
        if self.settings.mock_mode:
            return
        try:
            from FlagEmbedding import FlagReranker

            self._model = FlagReranker(self.model_path, use_fp16=True)
        except Exception:
            self._model = None

    def rerank(self, query: str, candidates: list[IndexedChunk], top_k: int) -> list[IndexedChunk]:
        if not candidates:
            return []
        if self._model is not None:
            # 用 BGE Reranker 对每个 (查询, 文档) 对打分
            try:
                pairs = [[query, c.text] for c in candidates]
                scores = self._model.compute_score(pairs, batch_size=16)
                if not isinstance(scores, list):
                    scores = [scores]
                rescored = []
                # 混合分数：0.4×检索分 + 0.6×重排分
                for chunk, rr_score in zip(candidates, scores, strict=False):
                    final_score = 0.4 * chunk.score + 0.6 * float(rr_score)
                    rescored.append(chunk.model_copy(update={"score": float(final_score)}))
                rescored.sort(key=lambda x: x.score, reverse=True)
                return rescored[:top_k]
            except Exception:
                pass

        return self._lexical_rerank(query, candidates, top_k=top_k)

    def _lexical_rerank(
        self, query: str, candidates: list[IndexedChunk], top_k: int
    ) -> list[IndexedChunk]:
        q_tokens = set(simple_tokenize(query))
        rescored: list[IndexedChunk] = []
        for chunk in candidates:
            c_tokens = set(simple_tokenize(chunk.text))
            overlap = len(q_tokens & c_tokens)
            overlap_ratio = overlap / max(len(q_tokens), 1)
            final_score = 0.7 * chunk.score + 0.3 * overlap_ratio
            rescored.append(chunk.model_copy(update={"score": float(final_score)}))
        rescored.sort(key=lambda x: x.score, reverse=True)
        return rescored[:top_k]
