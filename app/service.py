from __future__ import annotations

import hashlib
import time
import uuid
from pathlib import Path
from threading import Lock

from .config import Settings, get_settings
from .evaluation.evaluation import evaluate_context_metrics
from .llm.llm_client import LLMClient
from .llm.llm_judge import LLMJudge
from .retrieval.chunking import build_parent_child_chunks
from .retrieval.embeddings import BgeM3Embedder
from .retrieval.mineru_pipeline import MinerUParser
from .retrieval.reranker import BGEReranker
from .retrieval.retriever import HybridRetriever
from .retrieval.vector_store import build_vector_store
from .schemas import (
    AskRequest,
    AskResponse,
    IngestFileRequest,
    IngestResponse,
    IngestTextRequest,
    IntentType,
    JudgeRequest,
    JudgeResponse,
    RagasEvalRequest,
    RagasEvalResponse,
    SourceItem,
)
from .workflow import AgenticRAGWorkflow


class GroundTruthIngestionForbidden(PermissionError):
    """Raised when evaluation-only truth data targets production storage."""


def _is_production(settings: Settings) -> bool:
    return settings.environment.strip().casefold() in {"prod", "production"}


def _is_truthy(value: object) -> bool:
    if isinstance(value, str):
        return value.strip().casefold() in {"1", "true", "yes", "on"}
    return bool(value)


def _validate_ingestion_source(
    settings: Settings,
    source: str,
    metadata: dict[str, object],
) -> None:
    if not _is_production(settings):
        return

    sources = (source, metadata.get("source", ""))
    has_ground_truth_source = any(
        str(candidate).strip().casefold() == "ground_truth" for candidate in sources
    )
    if has_ground_truth_source or _is_truthy(metadata.get("is_ground_truth", False)):
        raise GroundTruthIngestionForbidden(
            "Evaluation ground-truth data cannot be ingested into production knowledge bases"
        )


def _legacy_ingestion_metadata(
    metadata: dict[str, object],
    *,
    source: str,
    document_id: str,
    content_sha256: str,
) -> dict[str, object]:
    # Reserved lifecycle values are written last so callers cannot accidentally
    # stage points through the legacy synchronous /v1 contract.
    return {
        **metadata,
        "source": source,
        "index_visibility": "active",
        "managed_document_id": document_id,
        "content_sha256": content_sha256,
    }


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for block in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


class EpilepsyAgentService:
    """系统核心编排器：负责入库、问答与评估三条主链路。"""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

        # 启动阶段一次性构建可复用组件。
        self.parser = MinerUParser()
        self.llm = LLMClient(self.settings)
        self.embedder = BgeM3Embedder(self.settings)
        self.store = build_vector_store(self.settings)
        self.reranker = BGEReranker(self.settings)

        self.retriever = HybridRetriever(
            settings=self.settings,
            embedder=self.embedder,
            store=self.store,
            reranker=self.reranker,
            llm=self.llm,
        )
        self.workflow = AgenticRAGWorkflow(
            settings=self.settings,
            llm=self.llm,
            retriever=self.retriever,
        )
        self.judge = LLMJudge(self.llm)

        # 入库时可能有并发请求，使用锁保护索引写入。
        self._lock = Lock()

    def seed_demo_data(self) -> None:
        # 保证幂等：知识库已有数据时不重复写入演示样本。
        if self.retriever.count() > 0:
            return

        docs = [
            IngestTextRequest(
                doc_id="lit_guideline_001",
                title="ILAE Epilepsy Management Guideline (Summary)",
                doc_type="literature",
                text=(
                    "Adult epilepsy management should be stratified by seizure type, EEG pattern, and imaging findings."
                    "First-line medication should be selected by syndrome profile and adverse-effect risk."
                    "Status epilepticus or recurrent uncontrolled seizure requires emergency pathway activation."
                ),
                metadata={"year": 2023, "source": "guideline"},
            ),
            IngestTextRequest(
                doc_id="cli_case_001",
                title="Outpatient Follow-up Notes",
                doc_type="clinical",
                text=(
                    "Patient reported one to two nocturnal episodes per week in the last two months with inconsistent adherence."
                    "The patient self-reduced levetiracetam dose without specialist confirmation."
                    "Recommendation: reinforce adherence education, track seizure diary, and review dose at follow-up."
                    "Emergency care is required if convulsion lasts more than 5 minutes."
                ),
                metadata={"department": "neurology"},
            ),
        ]
        for doc in docs:
            self.ingest_text(doc)

    def ingest_text(self, request: IngestTextRequest) -> IngestResponse:
        _validate_ingestion_source(self.settings, request.source, request.metadata)
        content_sha256 = hashlib.sha256(request.text.encode("utf-8")).hexdigest()

        # 父子分块：父块保上下文，子块保检索粒度。
        parents, children = build_parent_child_chunks(
            doc_id=request.doc_id,
            title=request.title,
            text=request.text,
            doc_type=request.doc_type,
            metadata=_legacy_ingestion_metadata(
                request.metadata,
                source=request.source,
                document_id=request.doc_id,
                content_sha256=content_sha256,
            ),
        )

        with self._lock:
            inserted = self.retriever.index_child_chunks(children)

        return IngestResponse(
            inserted_parents=len(parents),
            inserted_children=inserted,
            doc_id=request.doc_id,
        )

    def ingest_file(self, request: IngestFileRequest) -> IngestResponse:
        _validate_ingestion_source(self.settings, request.source, request.metadata)

        path = Path(request.file_path)
        doc_id = request.doc_id or self._default_doc_id(path)
        title = request.title or path.stem

        parents, children = self.parser.parse_to_chunks(
            file_path=str(path),
            doc_id=doc_id,
            title=title,
            doc_type=request.doc_type,
            metadata=_legacy_ingestion_metadata(
                request.metadata,
                source=request.source,
                document_id=doc_id,
                content_sha256=_file_sha256(path),
            ),
        )

        with self._lock:
            inserted = self.retriever.index_child_chunks(children)

        return IngestResponse(
            inserted_parents=len(parents),
            inserted_children=inserted,
            doc_id=doc_id,
        )

    def ask(self, request: AskRequest) -> AskResponse:
        start = time.perf_counter()

        # 工作流内部执行：意图路由 -> 检索 -> 生成 -> 安全后处理。
        # 这是RAG的核心逻辑，将问题转换为意图，然后检索相关文档，生成答案，并进行安全后处理。
        # 即问题交给 workflow（工作流）去处理
        state = self.workflow.run(question=request.question, top_k=request.top_k)
        latency_ms = (time.perf_counter() - start) * 1000

        # 防御式兜底，避免异常路由值导致响应失败。
        intent_str = str(state.get("intent", IntentType.clinical.value))
        if intent_str not in {i.value for i in IntentType}:
            intent_str = IntentType.clinical.value

        retrieved = state.get("retrieved", [])
        sources = [
            SourceItem(
                chunk_id=item.chunk_id,
                parent_id=item.parent_id,
                doc_id=item.doc_id,
                title=item.title,
                doc_type=item.doc_type,
                score=item.score,
                text=item.text,
                metadata=item.metadata,
            )
            for item in retrieved
        ]

        trace = state.get("trace", []) if request.with_trace else []
        return AskResponse(
            answer=state.get("answer", ""),
            intent=IntentType(intent_str),
            sources=sources,
            trace=trace,
            latency_ms=latency_ms,
        )

    def evaluate_ragas(self, request: RagasEvalRequest) -> RagasEvalResponse:
        result = evaluate_context_metrics(request.samples)
        return RagasEvalResponse(
            metrics=result.get("metrics", {}), details=result.get("details", {})
        )

    def run_judge(self, request: JudgeRequest) -> JudgeResponse:
        return self.judge.judge(request.question, request.answer, request.references)

    def kb_count(self) -> int:
        return self.retriever.count()

    def kb_clear(self) -> None:
        """清空知识库（用于重新入库）。"""
        self.retriever.store.clear()

    @staticmethod
    def _default_doc_id(path: Path) -> str:
        # 生成便于本地调试识别的默认文档 ID。
        return f"{path.stem}_{uuid.uuid4().hex[:8]}"


_service_instance: EpilepsyAgentService | None = None


def get_service() -> EpilepsyAgentService:
    global _service_instance
    if _service_instance is None:
        _service_instance = EpilepsyAgentService()
    return _service_instance
