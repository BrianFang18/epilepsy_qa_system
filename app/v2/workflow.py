"""
V2 问诊工作流引擎

整合方言规范化、指代消解、对话状态管理、策略引擎，
实现真正的医生风格多轮问诊。

V2 核心架构：
  用户输入
     │
     ▼
  ┌──────────────────┐
  │ 方言规范化层      │  DialectNormalizer
  │ (口语 → 标准医学) │
  └────────┬─────────┘
           │
           ▼
  ┌──────────────────┐
  │ 指代消解层        │  CoreferenceResolver
  │ (代词 → 实体)   │
  └────────┬─────────┘
           │
           ▼
  ┌──────────────────┐
  │ 急危重症检测      │  EmergencyDetector (集成在策略引擎)
  │ (紧急 → 干预)   │
  └────────┬─────────┘
           │
           ▼
  ┌──────────────────┐
  │ 对话状态更新      │  ConversationState.update_slot()
  │ (提取 → 槽位)   │
  └────────┬─────────┘
           │
           ▼
  ┌──────────────────┐
  │ 策略决策          │  DialoguePolicyEngine.decide_action()
  │ (状态 → 动作)   │
  └────────┬─────────┘
           │
     ┌─────┴─────┐
     │            │
     ▼            ▼
  追问         生成回复
     │
     ▼
  ┌──────────────────┐
  │ 医生风格生成      │  DoctorStyleGenerator
  │ (上下文 → 回复) │
  └────────┬─────────┘
           │
           ▼
  ┌──────────────────┐
  │ 安全护栏          │  SafetyGuard
  │ (输出 → 清洗)   │
  └──────────────────┘
"""

from __future__ import annotations

import logging
from typing import Any

from .conversation import ConversationMemory, DialoguePolicyEngine
from .generation.prompts_v2 import build_doctor_consultation_prompt
from .schemas_v2 import (
    ActionType,
    ConversationState,
    ConversationTurnRequest,
    ConversationTurnResponse,
    NormalizationResult,
    UrgencyLevel,
)
from .understanding import CoreferenceResolver, DialectNormalizer

logger = logging.getLogger(__name__)


class MedicalConsultationWorkflow:
    """
    V2 核心工作流：医生风格智能问诊

    相比 V1 的改进：
    1. 多轮对话状态管理（每个 session_id 对应一个持久化状态）
    2. 方言规范化（四川话等方言 → 标准医学术语）
    3. 指代消解（"小手臂" → 前臂，避免重复询问）
    4. 急危重症优先检测
    5. 策略驱动的追问（基于症状引导图）
    6. 医生风格的同理心回复
    """

    def __init__(
        self,
        llm_client,
        retriever,
        embedder=None,
        memory: ConversationMemory | None = None,
    ) -> None:
        self.llm = llm_client
        self.retriever = retriever
        self.embedder = embedder

        # 初始化各组件
        self.dialect_normalizer = DialectNormalizer()
        self.coreference_resolver = CoreferenceResolver()
        self.memory = memory or ConversationMemory()

        # 对话状态缓存（session_id -> ConversationState）
        self._states: dict[str, ConversationState] = {}

    def start_consultation(
        self,
        patient_id: str | None = None,
        initial_complaint: str | None = None,
    ) -> tuple[str, str, str]:
        """
        开始一个新的问诊会话

        Returns:
            tuple of (session_id, greeting, first_question)
        """
        # 创建新的会话状态
        state = ConversationState(patient_id=patient_id)
        state.init_slots()

        # 如果有初始主诉，先处理
        if initial_complaint:
            self._process_initial_complaint(state, initial_complaint)

        # 保存状态
        self._states[state.session_id] = state
        self.memory.save_state(state)

        # 生成开场白
        greeting = self._generate_greeting(initial_complaint)

        # 生成第一个追问
        policy = DialoguePolicyEngine(state)
        action = policy.decide_action()

        return state.session_id, greeting, action.message

    def process_turn(
        self,
        request: ConversationTurnRequest,
    ) -> ConversationTurnResponse:
        """
        处理一轮对话

        V2 核心流程：
        1. 获取会话状态
        2. 方言规范化用户输入
        3. 指代消解
        4. 提取症状信息
        5. 更新对话状态
        6. 策略决策（追问/诊断/总结）
        7. 生成回复
        8. 安全护栏
        """
        session_id = request.session_id
        trace: list[str] = []

        # Step 1: 获取会话状态
        state = self._get_or_create_state(session_id)
        if state is None:
            raise ValueError(f"Session not found: {session_id}")

        trace.append("state_loaded")

        # Step 2: 方言规范化
        norm_result = self.dialect_normalizer.normalize(request.message)
        normalized_text = norm_result.normalized_text
        trace.append(f"normalized: '{request.message}' -> '{normalized_text}'")

        # Step 3: 指代消解
        history_dicts = self._turns_to_dicts(state.turns)
        resolved = self.coreference_resolver.resolve(
            current_utterance=request.message,
            conversation_history=history_dicts,
            current_slots=self._slots_to_dict(state),
            llm_client=self.llm,
        )
        resolved_text = resolved.resolved
        trace.append(f"resolved: '{resolved_text}'")

        # Step 4: 提取症状信息
        extracted_slots, action_type = self._extract_slots(
            state, normalized_text, resolved_text, norm_result
        )
        trace.append(f"extracted_slots: {list(extracted_slots.keys())}")

        # Step 5: 检查急危重症
        urgency_signs = norm_result.urgency_signs or []
        if urgency_signs:
            state.set_urgency(UrgencyLevel.HIGH, urgency_signs)
            trace.append(f"urgency_detected: {urgency_signs}")

        # Step 6: 更新对话状态
        for slot_name, value in extracted_slots.items():
            state.update_slot(slot_name, value)

        # Step 7: 策略决策
        policy = DialoguePolicyEngine(state)
        action = policy.decide_action()
        trace.append(
            f"policy_decision: {action.action_type.value} -> phase={action.next_phase.value}"
        )

        # Step 8: 生成回复
        if action.action_type == ActionType.EMERGENCY_WARNING:
            response_text = action.message
        else:
            response_text = self._generate_response(
                state=state,
                user_message=request.message,
                normalized_message=normalized_text,
                resolved_message=resolved_text,
                action=action,
            )

        # Step 9: 添加到对话历史
        state.add_turn(
            user_message=request.message,
            system_response=response_text,
            action_type=action.action_type,
            collected_slots=extracted_slots,
            normalized_message=normalized_text,
            medical_entities=[e.model_dump() for e in norm_result.medical_entities],
            resolved_entities=[r.model_dump() for r in resolved.resolved_entities],
            emergency_signs=urgency_signs,
        )

        # Step 10: 保存状态
        self._states[session_id] = state
        self.memory.save_state(state)

        return ConversationTurnResponse(
            session_id=session_id,
            response=response_text,
            action_type=action.action_type,
            phase=state.current_phase,
            completion=state.completion_percentage,
            urgency=state.urgency,
            emergency_detected=state.is_critical(),
            emergency_signs=urgency_signs,
            collected_slots={k: v for k, v in self._slots_to_dict(state).items() if v is not None},
            suggested_action=action.suggested_action,
            trace=trace if request.with_trace else [],
        )

    def get_consultation_summary(self, session_id: str) -> dict:
        """获取问诊总结"""
        state = self._get_or_create_state(session_id)
        if state is None:
            raise ValueError(f"Session not found: {session_id}")

        return {
            "session_id": session_id,
            "phase": state.current_phase.value,
            "completion": f"{state.completion_percentage:.0%}",
            "urgency": state.urgency.value,
            "turn_count": state.turn_count,
            "collected_slots": {k: v for k, v in self._slots_to_dict(state).items() if v},
            "pending_slots": state.get_missing_required_slots(),
            "draft_diagnoses": state.draft_diagnoses,
            "suggested_actions": state.suggested_actions,
        }

    # ─────────────────────────────────────────────────────────
    # 内部辅助方法
    # ─────────────────────────────────────────────────────────

    def _get_or_create_state(self, session_id: str) -> ConversationState | None:
        """获取或创建会话状态"""
        # 先从内存缓存获取
        if session_id in self._states:
            return self._states[session_id]

        # 从记忆层获取
        state = self.memory.get_state(session_id)
        if state:
            self._states[session_id] = state
            return state

        return None

    def _process_initial_complaint(
        self,
        state: ConversationState,
        complaint: str,
    ) -> None:
        """处理初始主诉"""
        norm_result = self.dialect_normalizer.normalize(complaint)
        extracted, _ = self._extract_slots(
            state, norm_result.normalized_text, complaint, norm_result
        )
        for slot_name, value in extracted.items():
            state.update_slot(slot_name, value)

    def _extract_slots(
        self,
        state: ConversationState,
        normalized_text: str,
        resolved_text: str,
        norm_result: NormalizationResult,
    ) -> tuple[dict[str, Any], ActionType]:
        """从文本中提取症状槽位"""
        extracted: dict[str, Any] = {}

        # 从规范化结果中提取
        for entity in norm_result.medical_entities:
            if entity.category == "symptom":
                if "chief_complaint" not in state.confirmed_slots:
                    if "chief_complaint" not in extracted:
                        extracted["chief_complaint"] = entity.normalized
                    else:
                        extracted["chief_complaint"] += f"、{entity.normalized}"

        # 从文本模式匹配中提取
        import re

        # 发作持续时间
        if "seizure_duration" not in state.confirmed_slots:
            patterns = [
                (r"(\d+)\s*[秒秒钟]", lambda m: f"{m.group(1)}秒"),
                (r"(\d+)\s*[分分钟]", lambda m: f"{m.group(1)}分钟"),
                (r"(\d+)\s*[小时h]", lambda m: f"{m.group(1)}小时"),
                (r"几分钟", lambda _: "几分钟"),
                (r"十多分钟", lambda _: "10多分钟"),
                (r"半小时", lambda _: "30分钟"),
                (r"一直", lambda _: "持续"),
            ]
            for pattern, converter in patterns:
                match = re.search(pattern, normalized_text)
                if match:
                    extracted["seizure_duration"] = converter(match)
                    break

        # 意识状态
        if "loss_of_consciousness" not in state.confirmed_slots:
            consciousness_positive = ["昏", "不省人事", "不知道", "没意识", "意识丧"]
            consciousness_negative = ["意识清楚", "清醒", "知道", "有意识"]
            text_lower = normalized_text.lower()
            if any(kw in text_lower for kw in consciousness_positive):
                extracted["loss_of_consciousness"] = "是"
            elif any(kw in text_lower for kw in consciousness_negative):
                extracted["loss_of_consciousness"] = "否"

        # 发作部位
        if "affected_limb" not in state.confirmed_slots:
            body_parts = {
                "四肢": "四肢",
                "全身": "全身",
                "手": "手部",
                "脚": "足部",
                "手臂": "上肢",
                "腿": "下肢",
                "脸": "面部",
                "嘴角": "面部",
            }
            for keyword, value in body_parts.items():
                if keyword in normalized_text:
                    extracted["affected_limb"] = value
                    break

        # 当前用药
        if "current_medications" not in state.confirmed_slots:
            drugs = [
                "左乙拉西坦",
                "丙戊酸钠",
                "卡马西平",
                "奥卡西平",
                "拉莫三嗪",
                "加巴喷丁",
                "托吡酯",
                "苯巴比妥",
                "德巴金",
                "开浦兰",
                "曲莱",
                "利必通",
            ]
            found_drugs = [d for d in drugs if d in normalized_text]
            if found_drugs:
                extracted["current_medications"] = "、".join(found_drugs)

        return extracted, ActionType.ASK_QUESTION

    def _generate_greeting(self, initial_complaint: str | None) -> str:
        """生成开场白"""
        if initial_complaint:
            return (
                f"您好，我已收到您的描述：'{initial_complaint}'。"
                "为了更好地帮助您，我需要进一步了解一些情况。"
                "请问您方便回答几个问题吗？"
            )
        return (
            "您好，我是癫痫专科的问诊助手。"
            "为了更好地了解您的情况，我会问您几个问题。"
            "请问您今天主要是因为什么不舒服来咨询呢？"
        )

    def _generate_response(
        self,
        state: ConversationState,
        user_message: str,
        normalized_message: str,
        resolved_message: str,
        action,
    ) -> str:
        """生成医生风格的回复"""
        # 构建已收集信息的摘要
        collected_parts = []
        for slot in state.slots.values():
            if slot.is_collected and slot.value:
                collected_parts.append(f"{slot.label}: {slot.value}")
        collected_summary = "；".join(collected_parts) if collected_parts else "暂无"

        # 构建缺失槽位信息
        missing = state.get_missing_required_slots()
        pending_parts = []
        for slot_name in missing[:3]:
            pending_slot = state.slots.get(slot_name)
            if pending_slot:
                pending_parts.append(f"{pending_slot.label}（{pending_slot.question_template}）")
        pending_summary = "；".join(pending_parts) if pending_parts else "关键信息已收集完整"

        # 构建提示词
        prompt = build_doctor_consultation_prompt(
            current_phase=state.current_phase.value,
            completion_percentage=state.completion_percentage,
            collected_info_summary=collected_summary,
            collected_symptoms=collected_summary,
            pending_slots=pending_summary,
            user_message=user_message,
            normalized_message=normalized_message,
            evidence="",  # TODO: 接入 GraphRAG 检索
        )

        # 调用 LLM 生成回复
        try:
            response = self.llm.chat(
                [
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": f"患者说：{resolved_message}"},
                ],
                temperature=0.3,
                max_tokens=512,
            )
            return response.strip() if response.strip() else action.message
        except Exception as e:
            logger.warning(f"LLM generation failed: {e}")
            return action.message

    def _turns_to_dicts(self, turns: list) -> list[dict]:
        """将 DialogueTurn 列表转换为字典列表"""
        return [
            {
                "user_message": t.user_message,
                "system_response": t.system_response,
                "collected_slots": t.collected_slots,
                "medical_entities": t.medical_entities,
            }
            for t in turns
        ]

    def _slots_to_dict(self, state: ConversationState) -> dict:
        """将槽位转换为字典"""
        return {name: slot.value for name, slot in state.slots.items()}
