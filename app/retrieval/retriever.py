from __future__ import annotations

from typing import Protocol

from ..config import Settings
from ..prompts import MULTI_QUERY_PROMPT
from ..schemas import IndexedChunk, IntentType
from ..utils import safe_json_loads
from .chunking import ChildChunk
from .embeddings import BgeM3Embedder
from .indexer import IngestionIndexer
from .reranker import BGEReranker
from .vector_store import BaseHybridStore


class ChatLike(Protocol):
    def chat(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        json_mode: bool = False,
    ) -> str: ...


class HybridRetriever:
    """混合检索主流程：查询改写 -> 混合召回 -> 精排。"""

    def __init__(
        self,
        settings: Settings,
        embedder: BgeM3Embedder,
        store: BaseHybridStore,
        reranker: BGEReranker,
        llm: ChatLike | None = None,
    ) -> None:
        self.settings = settings
        self.embedder = embedder
        self.store = store
        self.reranker = reranker
        self.llm = llm
        self._ingestion_indexer = IngestionIndexer(
            embedder=embedder,
            store=store,
            dense_dimension=settings.embed_dim,
        )

    def index_child_chunks(self, chunks: list[ChildChunk]) -> int:
        """Delegate ingestion writes to the dependency-light indexer."""
        return self._ingestion_indexer.index_child_chunks(chunks)

    def retrieve(
        self,
        query: str,
        intent: IntentType | str,
        top_k: int | None = None,
    ) -> list[IndexedChunk]:
        top_k = top_k or self.settings.final_top_k
        doc_type = self._intent_to_doc_type(intent)

        # 1. 查询改写（生成3个变体）
        # 长问题或表达模糊时，改写成多个查询能提升召回覆盖。
        query_variants = self._rewrite_queries(query, n=3)

        # 2.多查询结果合并：同一个 chunk 仅保留最高分。
        merged: dict[str, IndexedChunk] = {}
        retrieve_k = max(self.settings.dense_top_k, top_k * 4)
        for variant in query_variants:
            # 每个变体做混合检索
            q_dense, q_sparse = self.embedder.embed_query(variant)
            hits = self.store.hybrid_search(
                query_dense=q_dense,
                query_sparse=q_sparse,
                doc_type=doc_type,
                top_k=retrieve_k,
                dense_weight=self.settings.hybrid_dense_weight,
                sparse_weight=self.settings.hybrid_sparse_weight,
            )
            # 合并去重：同一个chunk保留最高分
            for item in hits:
                old = merged.get(item.chunk_id)
                if old is None or item.score > old.score:
                    merged[item.chunk_id] = item

        if not merged:
            return []

        pool = sorted(merged.values(), key=lambda x: x.score, reverse=True)

        # 3. 重排序: BGE Reranker 精排
        # 只对候选池做精排，平衡质量与延迟。
        rerank_k = max(top_k, self.settings.reranker_top_k)
        reranked = self.reranker.rerank(query, pool[: max(rerank_k * 4, top_k)], top_k=top_k)
        return reranked

    def count(self) -> int:
        return self.store.count()

    @staticmethod
    def _intent_to_doc_type(intent: IntentType | str) -> str | None:
        intent_value = intent.value if isinstance(intent, IntentType) else str(intent)
        if intent_value == IntentType.literature.value:
            return "literature"
        if intent_value == IntentType.clinical.value:
            return "clinical"
        return None

    def _rewrite_queries(self, question: str, n: int = 3) -> list[str]:
        """
        改写查询：
        为什么需要改写？
        - 用户的问题可能表达模糊或过于专业。
        - 使用 LLM 改写查询,一个问题改写成多个版本，可以提高召回率。
        - 返回改写后的查询。
        - return eg: ["癫痫夜间发作怎么办？", "seizure disorder nocturnal management", "癫痫夜间急性处理方案"]
        """
        rewritten = self._llm_rewrite(question, n=n)
        if rewritten:
            return rewritten[:n]

        # 无 LLM 改写服务时，使用规则改写保证可用性。
        variants = [question]
        q_lower = question.lower()
        if "epilepsy" in q_lower:
            variants.append(question.replace("epilepsy", "seizure disorder"))
        if "seizure" in q_lower:
            variants.append(f"{question} acute management")
        if "drug" in q_lower or "medication" in q_lower:
            variants.append(f"{question} anti-seizure medication guideline")

        unique: list[str] = []
        seen = set()
        for q in variants:
            q = q.strip()
            if q and q not in seen:
                unique.append(q)
                seen.add(q)
        return unique[:n]

    def _llm_rewrite(self, question: str, n: int) -> list[str]:
        """
        使用 LLM 改写查询。
        - 如果 LLM 不可用，返回空列表。
        - 返回改写后的查询。
        - return eg: ["癫痫夜间发作频繁怎么办？","seizure disorder nocturnal management","癫痫夜间急性处理方案"]
        """
        if self.llm is None:
            return []
        try:
            prompt = MULTI_QUERY_PROMPT.format(question=question, n=n)
            raw = self.llm.chat(
                [{"role": "user", "content": prompt}],
                temperature=0.0,
                json_mode=True,
                max_tokens=256,
            )
            data = safe_json_loads(raw)
            queries = data.get("queries", [])
            if not isinstance(queries, list):
                return []
            return [str(x).strip() for x in queries if str(x).strip()]
        except Exception:
            return []
