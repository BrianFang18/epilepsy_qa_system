from __future__ import annotations

from typing import TypedDict

from .config import Settings
from .llm.llm_client import LLMClient
from .prompts import (
    ANSWER_SYSTEM_PROMPT,
    ANSWER_SYSTEM_PROMPT_STANDARD,
    ANSWER_USER_TEMPLATE,
    ROUTER_PROMPT,
)
from .retrieval.retriever import HybridRetriever
from .schemas import IndexedChunk, IntentType
from .utils import safe_json_loads


class AgentState(TypedDict, total=False):
    question: str
    top_k: int
    intent: str
    retrieved: list[IndexedChunk]
    answer: str
    trace: list[str]


class AgenticRAGWorkflow:
    """兼容 LangGraph 的状态工作流；缺少依赖时自动回退到手工流程。"""

    def __init__(self, settings: Settings, llm: LLMClient, retriever: HybridRetriever) -> None:
        self.settings = settings
        self.llm = llm
        self.retriever = retriever
        self._graph = self._try_build_langgraph()

    def run(self, question: str, top_k: int | None = None) -> AgentState:
        state: AgentState = {
            "question": question,
            "top_k": top_k or self.settings.final_top_k,
            "trace": [],
        }
        if self._graph is not None:
            return self._graph.invoke(state)
        return self._run_manual(state)

    def _try_build_langgraph(self):
        try:
            from langgraph.graph import END, StateGraph
        except Exception:
            return None

        graph = StateGraph(AgentState)

        # 每个节点只做一件事，便于调试与定位问题。
        graph.add_node("route_intent", self._node_route_intent)
        graph.add_node("retrieve_literature", self._node_retrieve_literature)
        graph.add_node("retrieve_clinical", self._node_retrieve_clinical)
        graph.add_node("retrieve_both", self._node_retrieve_both)
        graph.add_node("generate_answer", self._node_generate_answer)
        graph.add_node("post_guard", self._node_post_guard)

        # 设置流程
        graph.set_entry_point("route_intent")
        graph.add_conditional_edges(
            "route_intent",
            self._route_selector,
            {
                IntentType.literature.value: "retrieve_literature",
                IntentType.clinical.value: "retrieve_clinical",
                IntentType.both.value: "retrieve_both",
            },
        )
        graph.add_edge("retrieve_literature", "generate_answer")
        graph.add_edge("retrieve_clinical", "generate_answer")
        graph.add_edge("retrieve_both", "generate_answer")
        graph.add_edge("generate_answer", "post_guard")
        graph.add_edge("post_guard", END)
        return graph.compile()

    def _run_manual(self, state: AgentState) -> AgentState:
        # 当 LangGraph 未安装时，使用等价顺序逻辑保障可用性。
        state.update(self._node_route_intent(state))
        intent = state.get("intent", IntentType.clinical.value)
        if intent == IntentType.literature.value:
            state.update(self._node_retrieve_literature(state))
        elif intent == IntentType.clinical.value:
            state.update(self._node_retrieve_clinical(state))
        else:
            state.update(self._node_retrieve_both(state))
        state.update(self._node_generate_answer(state))
        state.update(self._node_post_guard(state))
        return state

    def _route_selector(self, state: AgentState) -> str:
        intent = state.get("intent", IntentType.clinical.value)
        if intent not in {i.value for i in IntentType}:
            return IntentType.clinical.value
        return intent

    def _node_route_intent(self, state: AgentState) -> AgentState:
        """
        意图路由节点：
        - 把用户问题包装成提示词模板，交给 LLM 模型确定意图。
        - 返回意图和推理原因,解析 LLM 返回的 JSON。
        - 返回意图类型(意图是用户问题所属的领域，如文献、临床、两者都有)。
        - return eg: {"intent": "clinical", "reason": "用户询问临床处理建议"}
        """
        question = state["question"]
        prompt = ROUTER_PROMPT.format(question=question)
        raw = self.llm.chat(
            [{"role": "user", "content": prompt}], temperature=0.0, json_mode=True, max_tokens=120
        )
        data = safe_json_loads(raw)

        # 对模型输出做规范化，避免返回异常值导致路由错误。
        intent = str(data.get("intent", IntentType.clinical.value)).strip().lower()
        if intent not in {i.value for i in IntentType}:
            intent = IntentType.clinical.value

        reason = str(data.get("reason", ""))
        trace = list(state.get("trace", []))
        trace.append(f"intent={intent}; reason={reason}")
        print(f"[ROUTER DEBUG] question={question[:30]}...  raw={raw[:100]}  intent={intent}")
        return {"intent": intent, "trace": trace}

    # 工作流根据意图选择不同的检索方式
    # # 如果是 literature
    def _node_retrieve_literature(self, state: AgentState) -> AgentState:
        top_k = state.get("top_k", self.settings.final_top_k)
        retrieved = self.retriever.retrieve(
            query=state["question"],
            intent=IntentType.literature,
            top_k=top_k,
        )
        trace = list(state.get("trace", []))
        trace.append(f"literature_hits={len(retrieved)}")
        return {"retrieved": retrieved, "trace": trace}

    # 如果是 clinical
    def _node_retrieve_clinical(self, state: AgentState) -> AgentState:
        top_k = state.get("top_k", self.settings.final_top_k)
        retrieved = self.retriever.retrieve(
            query=state["question"],
            intent=IntentType.clinical,
            top_k=top_k,
        )
        trace = list(state.get("trace", []))
        trace.append(f"clinical_hits={len(retrieved)}")
        return {"retrieved": retrieved, "trace": trace}

    # 如果是 both
    def _node_retrieve_both(self, state: AgentState) -> AgentState:
        top_k = state.get("top_k", self.settings.final_top_k)
        lit = self.retriever.retrieve(
            query=state["question"], intent=IntentType.literature, top_k=top_k
        )
        cli = self.retriever.retrieve(
            query=state["question"], intent=IntentType.clinical, top_k=top_k
        )
        # 合并、去重、排序，返回 top_k 个片段。
        # 按 chunk_id 去重，同一片段保留更高分。
        merged: dict[str, IndexedChunk] = {}
        for item in lit + cli:
            old = merged.get(item.chunk_id)
            if old is None or item.score > old.score:
                merged[item.chunk_id] = item

        retrieved = sorted(merged.values(), key=lambda x: x.score, reverse=True)[:top_k]
        trace = list(state.get("trace", []))
        trace.append(f"both_hits={len(retrieved)}")
        return {"retrieved": retrieved, "trace": trace}

    def _node_generate_answer(self, state: AgentState) -> AgentState:
        """
        - 把检索到的内容打包成上下文，发送给 LLM。
        - LLM 根据系统提示词和用户问题、上下文生成结构化答案。
        - CoT 模式可切换：structured（显式推理链）或 standard（标准回答）。
        - 返回答案和推理过程。
        """
        retrieved = state.get("retrieved", [])
        context = self._build_context(retrieved, limit_chars=self.settings.max_context_chars)
        user_prompt = ANSWER_USER_TEMPLATE.format(
            question=state["question"],
            intent=state.get("intent", IntentType.clinical.value),
            context=context,
        )

        # 根据配置选择 CoT 模式
        if self.settings.cot_mode == "structured":
            system_prompt = ANSWER_SYSTEM_PROMPT
        else:
            system_prompt = ANSWER_SYSTEM_PROMPT_STANDARD

        answer = self.llm.chat(
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=self.settings.llm_temperature,
            max_tokens=self.settings.llm_max_tokens,
        )

        trace = list(state.get("trace", []))
        trace.append("answer_generated")
        return {"answer": answer, "trace": trace}

    def _node_post_guard(self, state: AgentState) -> AgentState:
        """
        作用：后处理节点
        1. 剔除 <thinking>...</thinking> 思维链（防止CoT污染Jaccard评估）
        2. 剔除 <final_answer>...</final_answer> XML 标签
        3. 剔除多余空白
        4. 添加免责声明
        """
        answer = state.get("answer", "").strip()

        # ── 1. 剔除 <thinking>...</thinking> ──────────────────────────────────────
        import re

        answer = re.sub(r"<thinking>\s*.*?\s*</thinking>", "", answer, flags=re.DOTALL)

        # ── 2. 剔除 <final_answer>...</final_answer> ────────────────────────────
        answer = re.sub(r"<final_answer>\s*", "", answer, flags=re.DOTALL)
        answer = re.sub(r"\s*</final_answer>", "", answer, flags=re.DOTALL)

        # ── 3. 清理多余空行 ──────────────────────────────────────────────────────
        answer = re.sub(r"\n{3,}", "\n\n", answer)
        answer = answer.strip()

        # ── 4. 添加免责声明 ─────────────────────────────────────────────────────
        if not self.settings.allow_unverified_medical_advice:
            boundary = "\n\nNotice: This system is for information retrieval assistance only and cannot replace a physician visit."
            if "cannot replace" not in answer.lower():
                answer += boundary

        trace = list(state.get("trace", []))
        trace.append("post_guard_applied")
        return {"answer": answer, "trace": trace}

    @staticmethod
    def _build_context(chunks: list[IndexedChunk], limit_chars: int) -> str:
        # 将检索证据压缩为提示词上下文，控制长度避免超 token。
        lines: list[str] = []
        total = 0
        for idx, chunk in enumerate(chunks, start=1):
            snippet = chunk.text.strip().replace("\n", " ")
            if chunk.parent_text:
                # 使用父块文本作为上下文（包含更多背景信息）
                snippet = chunk.parent_text.strip().replace("\n", " ")
            row = f"[{idx}] ({chunk.doc_type}) {chunk.title} | score={chunk.score:.4f}\n{snippet}\n"
            total += len(row)
            if total > limit_chars:
                break
            lines.append(row)
        return "\n".join(lines) if lines else "[No retrieved evidence]"
