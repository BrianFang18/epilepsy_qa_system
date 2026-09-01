from __future__ import annotations

import asyncio
import math
import re
import time
from typing import Literal, TypedDict, cast

from langgraph.graph import END, StateGraph

from ...config import Settings
from ...schemas import IndexedChunk
from ...v2.understanding.coreference import CoreferenceResolver
from ...v2.understanding.dialect_normalizer import DialectNormalizer
from .citations import build_evidence_bundle
from .errors import RetrievalUnavailableError
from .ports import RetrieverPort
from .schemas import Citation, PublicTraceEntry

ChatAction = Literal["emergency", "refuse", "generate"]


class ChatGraphState(TypedDict, total=False):
    message: str
    history: list[dict[str, str]]
    normalized_query: str
    resolved_query: str
    emergency: bool
    emergency_categories: list[str]
    retrieved: list[IndexedChunk]
    citations: list[Citation]
    evidence_context: str
    evidence_sufficient: bool
    generation_messages: list[dict[str, str]]
    action: ChatAction
    local_answer: str
    trace: list[PublicTraceEntry]


_EMERGENCY_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "prolonged_seizure",
        re.compile(
            r"(?:(?:发作|抽搐).{0,16}(?:超过|持续).{0,6}(?:5|五)\s*分)|"
            r"(?:seizure|convulsion).{0,24}(?:over|more than|longer than)\s*5\s*min",
            re.IGNORECASE,
        ),
    ),
    (
        "repeated_seizures",
        re.compile(
            r"连续(?:抽搐|发作)|反复发作.{0,12}(?:没有|未)清醒|"
            r"repeated seizures?.{0,24}(?:without|no)\s+(?:waking|recovery)",
            re.IGNORECASE,
        ),
    ),
    (
        "breathing_problem",
        re.compile(
            r"(?:呼吸停止|没有呼吸|呼吸困难|嘴唇.{0,4}(?:发紫|青紫))|"
            r"(?:not breathing|stopped breathing|blue lips)",
            re.IGNORECASE,
        ),
    ),
    (
        "unresponsive",
        re.compile(r"(?:昏迷|叫不醒|持续意识不清)|(?:unconscious|unresponsive)", re.IGNORECASE),
    ),
    (
        "serious_injury",
        re.compile(r"(?:发作|抽搐).{0,12}(?:严重受伤|大量出血)|seizure.{0,20}serious injury", re.I),
    ),
)

_EMERGENCY_GUIDANCE = (
    "【紧急情况——请立即呼叫急救】\n"
    "1. 立即拨打当地急救电话（中国大陆请拨 120），并记录发作开始时间。\n"
    "2. 移开周围硬物，保护头部；条件允许时让患者侧卧并保持呼吸道通畅。\n"
    "3. 不要按压肢体，不要往口中塞任何物品，不要喂水、食物或药物。\n"
    "4. 若停止呼吸，在急救调度指导下由受过训练者实施心肺复苏，并等待急救人员。\n\n"
    "本指引用于现场紧急处置，不能替代急救人员；请现在就寻求紧急医疗帮助。"
)

_NO_EVIDENCE_ANSWER = (
    "当前检索结果没有足够证据支持可靠回答，因此我不能据此给出医学结论。"
    "请咨询神经科医生，或补充经专业人员核实的检查和病史资料。\n\n"
    "免责声明：本系统仅提供信息检索辅助，不能替代医生面诊、诊断或处方。"
)


class ChatGraph:
    """The only graph for the new streaming chat path."""

    def __init__(self, settings: Settings, retriever: RetrieverPort) -> None:
        self._settings = settings
        self._retriever = retriever
        self._normalizer = DialectNormalizer()
        self._coreference = CoreferenceResolver(use_llm_fallback=False)
        self._compiled = self._build()

    def _build(self):
        graph = StateGraph(ChatGraphState)
        graph.add_node("input_emergency_guard", self._input_emergency_guard)
        graph.add_node("normalize_coreference", self._normalize_coreference)
        graph.add_node("retrieve", self._retrieve)
        graph.add_node("evidence_sufficiency", self._evidence_sufficiency)
        graph.add_node("generation_preparation", self._generation_preparation)
        graph.add_node("output_policy", self._output_policy)
        graph.set_entry_point("input_emergency_guard")
        graph.add_conditional_edges(
            "input_emergency_guard",
            self._after_input_guard,
            {
                "emergency": "output_policy",
                "continue": "normalize_coreference",
            },
        )
        graph.add_edge("normalize_coreference", "retrieve")
        graph.add_edge("retrieve", "evidence_sufficiency")
        graph.add_edge("evidence_sufficiency", "generation_preparation")
        graph.add_edge("generation_preparation", "output_policy")
        graph.add_edge("output_policy", END)
        return graph.compile()

    async def run(
        self,
        *,
        message: str,
        history: list[dict[str, str]],
    ) -> ChatGraphState:
        initial: ChatGraphState = {
            "message": message,
            "history": history,
            "trace": [],
        }
        result = await self._compiled.ainvoke(initial)
        return cast(ChatGraphState, result)

    @staticmethod
    def _trace(
        state: ChatGraphState,
        *,
        node: str,
        started: float,
        status: Literal["completed", "skipped"] = "completed",
        count: int | None = None,
    ) -> list[PublicTraceEntry]:
        trace = list(state.get("trace", []))
        trace.append(
            PublicTraceEntry(
                node=node,
                status=status,
                count=count,
                duration_ms=round((time.perf_counter() - started) * 1000, 3),
            )
        )
        return trace

    def _input_emergency_guard(self, state: ChatGraphState) -> ChatGraphState:
        started = time.perf_counter()
        message = state["message"]
        categories = [name for name, pattern in _EMERGENCY_PATTERNS if pattern.search(message)]
        return {
            "emergency": bool(categories),
            "emergency_categories": categories,
            "trace": self._trace(
                state,
                node="input_emergency_guard",
                started=started,
                count=len(categories),
            ),
        }

    @staticmethod
    def _after_input_guard(state: ChatGraphState) -> str:
        return "emergency" if state.get("emergency", False) else "continue"

    def _normalize_coreference(self, state: ChatGraphState) -> ChatGraphState:
        started = time.perf_counter()
        normalized = self._normalizer.normalize(state["message"])
        normalized_query = normalized.normalized_text or state["message"]

        turns: list[dict[str, str]] = []
        for item in state.get("history", []):
            if item.get("role") == "user":
                turns.append({"user_message": item.get("content", "")})
            elif item.get("role") == "assistant" and turns:
                turns[-1]["system_response"] = item.get("content", "")

        resolved = self._coreference.resolve(
            current_utterance=normalized_query,
            conversation_history=turns,
            current_slots={},
            llm_client=None,
        )
        emergency_categories = list(state.get("emergency_categories", []))
        if normalized.urgency_signs and "urgent_language" not in emergency_categories:
            emergency_categories.append("urgent_language")

        return {
            "normalized_query": normalized_query,
            "resolved_query": resolved.resolved or normalized_query,
            "emergency": bool(emergency_categories),
            "emergency_categories": emergency_categories,
            "trace": self._trace(
                state,
                node="normalize_coreference",
                started=started,
                count=len(normalized.transformations) + len(resolved.resolved_entities),
            ),
        }

    async def _retrieve(self, state: ChatGraphState) -> ChatGraphState:
        started = time.perf_counter()
        if state.get("emergency", False):
            return {
                "retrieved": [],
                "trace": self._trace(
                    state,
                    node="retrieve",
                    started=started,
                    status="skipped",
                    count=0,
                ),
            }

        try:
            retrieved = await self._retriever.retrieve(
                state.get("resolved_query", state["message"]),
                top_k=self._settings.chat_top_k,
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            raise RetrievalUnavailableError() from None

        return {
            "retrieved": retrieved,
            "trace": self._trace(
                state,
                node="retrieve",
                started=started,
                count=len(retrieved),
            ),
        }

    def _evidence_sufficiency(self, state: ChatGraphState) -> ChatGraphState:
        started = time.perf_counter()
        minimum = self._settings.chat_min_evidence_score
        usable = [
            chunk
            for chunk in state.get("retrieved", [])
            if (chunk.text.strip() or chunk.parent_text.strip())
            and math.isfinite(float(chunk.score))
            and float(chunk.score) >= minimum
        ]
        return {
            "retrieved": usable,
            "evidence_sufficient": bool(usable),
            "trace": self._trace(
                state,
                node="evidence_sufficiency",
                started=started,
                count=len(usable),
            ),
        }

    def _generation_preparation(self, state: ChatGraphState) -> ChatGraphState:
        started = time.perf_counter()
        used, citations, evidence_context = build_evidence_bundle(
            state.get("retrieved", []),
            max_context_chars=self._settings.chat_max_context_chars,
            max_excerpt_chars=self._settings.chat_max_excerpt_chars,
        )
        citation_ids = ", ".join(citation.id for citation in citations) or "none"
        system_prompt = (
            "You are an evidence-grounded epilepsy information assistant. "
            "Use only the supplied evidence. Do not reveal hidden reasoning or chain-of-thought. "
            "Do not make a definite diagnosis, prescribe medication, or tell a person to change a dose. "
            f"The only valid citations are: {citation_ids}. Cite them exactly as [C1], [C2], etc. "
            "If the evidence is insufficient, say so.\n\n"
            f"Evidence:\n{evidence_context}"
        )
        history_messages = [
            {"role": item["role"], "content": item["content"]}
            for item in state.get("history", [])
            if item.get("role") in {"user", "assistant"} and item.get("content")
        ]
        messages = [
            {"role": "system", "content": system_prompt},
            *history_messages,
            {
                "role": "user",
                "content": state.get("resolved_query", state["message"]),
            },
        ]
        sufficient = bool(state.get("evidence_sufficient", False) and citations)
        return {
            "retrieved": used,
            "citations": citations,
            "evidence_context": evidence_context,
            "evidence_sufficient": sufficient,
            "generation_messages": messages if sufficient else [],
            "trace": self._trace(
                state,
                node="generation_preparation",
                started=started,
                count=len(citations),
            ),
        }

    def _output_policy(self, state: ChatGraphState) -> ChatGraphState:
        started = time.perf_counter()
        if state.get("emergency", False):
            action: ChatAction = "emergency"
            local_answer = _EMERGENCY_GUIDANCE
        elif not state.get("evidence_sufficient", False):
            action = "refuse"
            local_answer = _NO_EVIDENCE_ANSWER
        else:
            action = "generate"
            local_answer = ""

        return {
            "action": action,
            "local_answer": local_answer,
            "trace": self._trace(
                state,
                node="output_policy",
                started=started,
                count=len(state.get("citations", [])),
            ),
        }
