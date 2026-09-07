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

LanguageCode = Literal["zh", "en"]
LocalRoute = Literal["greeting", "out_of_scope"]
ChatAction = Literal["emergency", "greeting", "out_of_scope", "refuse", "generate"]


class ChatGraphState(TypedDict, total=False):
    message: str
    history: list[dict[str, str]]
    language: LanguageCode
    local_route: LocalRoute
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
        re.compile(r"(?:昏迷|叫不醒|持续意识不清)|(?:unconscious|unresponsive)", re.I),
    ),
    (
        "serious_injury",
        re.compile(r"(?:发作|抽搐).{0,12}(?:严重受伤|大量出血)|seizure.{0,20}serious injury", re.I),
    ),
)

_HAN = re.compile(r"[\u3400-\u9fff]")
_CLEARLY_OUT_OF_SCOPE = re.compile(
    r"(?:天气|气温|股票|基金|汇率|编程|代码|写程序|旅游|菜谱|做饭|足球比分|篮球比分|球赛比分|电影推荐|推荐.{0,4}电影|游戏攻略)|"
    r"\b(?:weather|temperature|stock|forex|programming|write code|travel|recipe|"
    r"football score|basketball score|movie recommendation|video game walkthrough)\b",
    re.IGNORECASE,
)
_EPILEPSY_CONTEXT = re.compile(
    r"(?:癫痫|癫癎|发作|抽搐|脑电图|抗癫痫|光敏)|"
    r"\b(?:epilepsy|epileptic|seizure|convulsion|EEG|photosensitive)\b",
    re.IGNORECASE,
)
_GREETING_ZH = {"你好", "您好", "嗨", "哈喽", "早上好", "下午好", "晚上好", "在吗"}
_GREETING_EN = {
    "hi",
    "hello",
    "hey",
    "hello there",
    "good morning",
    "good afternoon",
    "good evening",
}

_EMERGENCY_GUIDANCE: dict[LanguageCode, str] = {
    "zh": (
        "【紧急情况——请立即呼叫急救】\n"
        "1. 立即拨打当地急救电话（中国大陆请拨 120），并记录发作开始时间。\n"
        "2. 移开周围硬物，保护头部；条件允许时让患者侧卧并保持呼吸道通畅。\n"
        "3. 不要按压肢体，不要往口中塞任何物品，不要喂水、食物或药物。\n"
        "4. 若停止呼吸，在急救调度指导下由受过训练者实施心肺复苏，并等待急救人员。\n\n"
        "本指引用于现场紧急处置，不能替代急救人员；请现在就寻求紧急医疗帮助。"
    ),
    "en": (
        "[Emergency — call emergency services now]\n"
        "1. Call your local emergency number and note when the seizure began.\n"
        "2. Move hard objects away, protect the head, and place the person on their side when safe.\n"
        "3. Do not restrain them, put anything in their mouth, or give food, water, or medicine.\n"
        "4. If breathing stops, follow the dispatcher's instructions and have a trained person begin CPR.\n\n"
        "This immediate guidance does not replace emergency professionals. Seek urgent medical help now."
    ),
}

_NO_EVIDENCE_ANSWER: dict[LanguageCode, str] = {
    "zh": (
        "当前检索结果没有足够证据支持可靠回答，因此我不能据此给出医学结论。"
        "请在管理后台摄取相关资料，或咨询神经科医生。\n\n"
        "免责声明：本系统仅提供信息检索辅助，不能替代医生面诊、诊断或处方。"
    ),
    "en": (
        "The current retrieval results do not contain enough evidence for a reliable answer, "
        "so I cannot provide a medical conclusion from them. Ingest relevant material or consult "
        "a neurology professional.\n\n"
        "Disclaimer: This system supports information retrieval only and cannot replace an "
        "in-person assessment, diagnosis, or prescription."
    ),
}

_GREETING_ANSWER: dict[LanguageCode, str] = {
    "zh": (
        "你好！我可以帮助检索并回答癫痫相关的循证问题。你可以询问癫痫发作、脑电图、"
        "检查、用药原则、日常照护或急救常识。回答是否由真实模型生成会在运行模式中明确标注。"
    ),
    "en": (
        "Hello! I can help with evidence-grounded questions about epilepsy, including seizures, "
        "EEG, investigations, medication principles, daily care, and first aid. The runtime mode "
        "will clearly indicate whether a real model is generating the response."
    ),
}

_OUT_OF_SCOPE_ANSWER: dict[LanguageCode, str] = {
    "zh": "这个问题不属于本系统的癫痫循证问答范围，因此没有调用知识库或模型。请改问癫痫相关问题。",
    "en": (
        "That request is outside this epilepsy evidence assistant's scope, so the knowledge base "
        "and model were not called. Please ask an epilepsy-related question."
    ),
}


def _detect_language(text: str) -> LanguageCode:
    return "zh" if _HAN.search(text) else "en"


def _is_greeting(text: str) -> bool:
    stripped = text.strip().casefold()
    compact_zh = re.sub(r"[\s，。！？、,.!?]+", "", stripped)
    if compact_zh in _GREETING_ZH:
        return True
    normalized_en = re.sub(r"[^a-z]+", " ", stripped).strip()
    return normalized_en in _GREETING_EN


class ChatGraph:
    """Streaming chat graph with local safety, scope, retrieval, and generation routes."""

    def __init__(self, settings: Settings, retriever: RetrieverPort) -> None:
        self._settings = settings
        self._retriever = retriever
        self._normalizer = DialectNormalizer()
        self._coreference = CoreferenceResolver(use_llm_fallback=False)
        self._compiled = self._build()

    def _build(self):
        graph = StateGraph(ChatGraphState)
        graph.add_node("input_emergency_guard", self._input_emergency_guard)
        graph.add_node("request_route", self._request_route)
        graph.add_node("normalize_coreference", self._normalize_coreference)
        graph.add_node("retrieve", self._retrieve)
        graph.add_node("evidence_sufficiency", self._evidence_sufficiency)
        graph.add_node("generation_preparation", self._generation_preparation)
        graph.add_node("output_policy", self._output_policy)
        graph.set_entry_point("input_emergency_guard")
        graph.add_conditional_edges(
            "input_emergency_guard",
            self._after_input_guard,
            {"emergency": "output_policy", "continue": "request_route"},
        )
        graph.add_conditional_edges(
            "request_route",
            self._after_request_route,
            {"local": "output_policy", "continue": "normalize_coreference"},
        )
        graph.add_edge("normalize_coreference", "retrieve")
        graph.add_edge("retrieve", "evidence_sufficiency")
        graph.add_edge("evidence_sufficiency", "generation_preparation")
        graph.add_edge("generation_preparation", "output_policy")
        graph.add_edge("output_policy", END)
        return graph.compile()

    async def run(self, *, message: str, history: list[dict[str, str]]) -> ChatGraphState:
        initial: ChatGraphState = {
            "message": message,
            "history": history,
            "language": _detect_language(message),
            "trace": [],
        }
        return cast(ChatGraphState, await self._compiled.ainvoke(initial))

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
        categories = [
            name for name, pattern in _EMERGENCY_PATTERNS if pattern.search(state["message"])
        ]
        return {
            "emergency": bool(categories),
            "emergency_categories": categories,
            "trace": self._trace(
                state, node="input_emergency_guard", started=started, count=len(categories)
            ),
        }

    @staticmethod
    def _after_input_guard(state: ChatGraphState) -> str:
        return "emergency" if state.get("emergency", False) else "continue"

    def _request_route(self, state: ChatGraphState) -> ChatGraphState:
        started = time.perf_counter()
        message = state["message"]
        user_scope_context = " ".join(
            [
                message,
                *(
                    item.get("content", "")
                    for item in state.get("history", [])
                    if item.get("role") == "user"
                ),
            ]
        )
        route: LocalRoute | None = None
        if _is_greeting(message):
            route = "greeting"
        elif _CLEARLY_OUT_OF_SCOPE.search(message) and not _EPILEPSY_CONTEXT.search(
            user_scope_context
        ):
            route = "out_of_scope"
        result: ChatGraphState = {
            "trace": self._trace(
                state, node="request_route", started=started, count=1 if route else 0
            )
        }
        if route is not None:
            result["local_route"] = route
        return result

    @staticmethod
    def _after_request_route(state: ChatGraphState) -> str:
        return "local" if state.get("local_route") else "continue"

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
                    state, node="retrieve", started=started, status="skipped", count=0
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
            "trace": self._trace(state, node="retrieve", started=started, count=len(retrieved)),
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

        # RRF scores are rank values rather than calibrated relevance probabilities.
        # In the dependency-free backend, require explicit lexical overlap so a
        # generic epilepsy mention cannot pass the evidence gate for an unrelated
        # question. Real BGE deployments retain semantic retrieval without this rule.
        if self._settings.ingestion_embedding_backend == "deterministic":
            from ...utils import simple_tokenize

            stopwords = {
                "a",
                "an",
                "and",
                "can",
                "do",
                "during",
                "how",
                "i",
                "is",
                "my",
                "or",
                "should",
                "the",
                "what",
            }
            query_tokens = {
                token for token in simple_tokenize(state["message"]) if token not in stopwords
            }
            required_overlap = 1 if len(query_tokens) <= 2 else 2
            if query_tokens:
                usable = [
                    chunk
                    for chunk in usable
                    if len(
                        query_tokens
                        & set(simple_tokenize(f"{chunk.title} {chunk.text} {chunk.parent_text}"))
                    )
                    >= required_overlap
                ]

        return {
            "retrieved": usable,
            "evidence_sufficient": bool(usable),
            "trace": self._trace(
                state, node="evidence_sufficiency", started=started, count=len(usable)
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
        language = state.get("language", "zh")
        language_instruction = (
            "Answer in Chinese because the latest user message is Chinese."
            if language == "zh"
            else "Answer in English because the latest user message is English."
        )
        system_prompt = (
            "You are an evidence-grounded epilepsy information assistant. "
            f"{language_instruction} "
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
        sufficient = bool(state.get("evidence_sufficient", False) and citations)
        messages = [
            {"role": "system", "content": system_prompt},
            *history_messages,
            {"role": "user", "content": state["message"]},
        ]
        return {
            "retrieved": used,
            "citations": citations,
            "evidence_context": evidence_context,
            "evidence_sufficient": sufficient,
            "generation_messages": messages if sufficient else [],
            "trace": self._trace(
                state, node="generation_preparation", started=started, count=len(citations)
            ),
        }

    def _output_policy(self, state: ChatGraphState) -> ChatGraphState:
        started = time.perf_counter()
        language = state.get("language", "zh")
        local_route = state.get("local_route")
        if state.get("emergency", False):
            action: ChatAction = "emergency"
            local_answer = _EMERGENCY_GUIDANCE[language]
        elif local_route == "greeting":
            action = "greeting"
            local_answer = _GREETING_ANSWER[language]
        elif local_route == "out_of_scope":
            action = "out_of_scope"
            local_answer = _OUT_OF_SCOPE_ANSWER[language]
        elif not state.get("evidence_sufficient", False):
            action = "refuse"
            local_answer = _NO_EVIDENCE_ANSWER[language]
        else:
            action = "generate"
            local_answer = ""
        return {
            "action": action,
            "local_answer": local_answer,
            "trace": self._trace(
                state, node="output_policy", started=started, count=len(state.get("citations", []))
            ),
        }
