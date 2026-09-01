"""
V2 数据模型: 扩展 Pydantic schemas 用于多轮对话和医疗问诊场景

扩展内容:
- ConversationState: 会话状态模型
- DialogueTurn: 对话轮次模型
- SymptomSlot: 症状槽位模型
- DialogueNode: 问诊节点模型
- IntentTypeV2: 扩展意图类型
- UrgencyLevel: 紧迫性等级
- MedicalEntity: 医学实体模型
- NormalizationResult: 规范化结果模型
- CoreferenceChain: 指代链模型
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

# ============================================================
# 枚举类型
# ============================================================


class UrgencyLevel(str, Enum):
    """紧迫性等级"""

    CRITICAL = "critical"  # 急危重症 — 立即干预
    HIGH = "high"  # 紧急 — 24h内就医
    MEDIUM = "medium"  # 一般 — 常规随访
    LOW = "low"  # 低 — 健康咨询

    def is_emergency(self) -> bool:
        return self == UrgencyLevel.CRITICAL


class DialoguePhase(str, Enum):
    """问诊阶段"""

    GREETING = "greeting"  # 问候
    SYMPTOM_COLLECTION = "symptom_collection"  # 症状收集
    SEIZURE_CHARACTER = "seizure_character"  # 发作特征
    MEDICAL_HISTORY = "medical_history"  # 既往史
    MEDICATION_HISTORY = "medication_history"  # 用药史
    FAMILY_HISTORY = "family_history"  # 家族史
    TRIGGER_ANALYSIS = "trigger_analysis"  # 诱因分析
    PHYSICAL_EXAM = "physical_exam"  # 体格检查建议
    PRELIMINARY_DIAGNOSIS = "preliminary_diagnosis"  # 初步诊断
    TREATMENT_SUGGESTION = "treatment_suggestion"  # 处置建议
    FOLLOW_UP = "follow_up"  # 随访安排
    COMPLETED = "completed"  # 问诊完成

    @property
    def order(self) -> int:
        """阶段的顺序编号"""
        order_map = {
            self.GREETING: 0,
            self.SYMPTOM_COLLECTION: 1,
            self.SEIZURE_CHARACTER: 2,
            self.MEDICAL_HISTORY: 3,
            self.MEDICATION_HISTORY: 4,
            self.FAMILY_HISTORY: 5,
            self.TRIGGER_ANALYSIS: 6,
            self.PHYSICAL_EXAM: 7,
            self.PRELIMINARY_DIAGNOSIS: 8,
            self.TREATMENT_SUGGESTION: 9,
            self.FOLLOW_UP: 10,
            self.COMPLETED: 11,
        }
        return order_map[self]

    def next(self) -> DialoguePhase:
        """获取下一阶段"""
        all_phases = list(DialoguePhase)
        try:
            idx = all_phases.index(self)
            if idx < len(all_phases) - 1:
                return all_phases[idx + 1]
        except ValueError:
            pass
        return DialoguePhase.COMPLETED


class ActionType(str, Enum):
    """对话动作类型"""

    ASK_QUESTION = "ask_question"  # 追问问题
    CONFIRM_UNDERSTANDING = "confirm"  # 确认理解
    PROVIDE_INFO = "provide_info"  # 提供信息
    EMERGENCY_WARNING = "emergency_warning"  # 紧急警告
    SUMMARIZE = "summarize"  # 总结
    SUGGEST_ACTION = "suggest_action"  # 建议行动
    END_CONVERSATION = "end"  # 结束对话


class IntentTypeV2(str, Enum):
    """V2 扩展意图类型（七分类）"""

    # 基础三类（保留兼容）
    LITERATURE = "literature"  # 文献检索
    CLINICAL = "clinical"  # 临床咨询
    BOTH = "both"  # 两者都要

    # 扩展分类
    SEIZURE_TYPE = "seizure_type"  # 发作类型咨询
    MEDICATION = "medication"  # 用药相关
    EMERGENCY = "emergency"  # 紧急情况
    GENERAL = "general"  # 一般性咨询
    FOLLOW_UP_QUESTION = "follow_up_question"  # 追问


# ============================================================
# 槽位定义
# ============================================================


class SymptomSlot(BaseModel):
    """症状槽位定义"""

    name: str  # 槽位名称
    label: str  # 显示标签
    value: Any = None  # 当前值
    is_required: bool = True  # 是否必填
    is_collected: bool = False  # 是否已收集
    max_turns: int = 3  # 最大追问轮次
    asked_turns: int = 0  # 已追问轮次
    question_template: str = ""  # 追问模板
    examples: list[str] = Field(default_factory=list)  # 填写示例
    dialect_aliases: dict[str, str] = Field(default_factory=dict)  # 方言别名

    def mark_collected(self, value: Any) -> None:
        self.value = value
        self.is_collected = True

    def mark_asked(self) -> None:
        self.asked_turns += 1

    @property
    def is_answered(self) -> bool:
        """是否有有效回答"""
        return self.value is not None and str(self.value).strip() != ""


# 预定义症状槽位
SYMPTOM_SLOTS: dict[str, SymptomSlot] = {
    "chief_complaint": SymptomSlot(
        name="chief_complaint",
        label="主要症状",
        question_template="请问您今天主要是因为什么不舒服来就诊？",
        examples=["抽搐", "头痛", "意识丧失"],
        dialect_aliases={"脑阔痛": "头痛", "扯风": "抽搐"},
    ),
    "seizure_duration": SymptomSlot(
        name="seizure_duration",
        label="发作持续时间",
        question_template="发作大概持续了多长时间？",
        examples=["几秒", "1-2分钟", "10多分钟"],
        dialect_aliases={"有好久": "持续时间"},
    ),
    "seizure_frequency": SymptomSlot(
        name="seizure_frequency",
        label="发作频率",
        question_template="这种发作一般多长时间发作一次？",
        examples=["每天几次", "每周一次", "一个月两三次"],
    ),
    "loss_of_consciousness": SymptomSlot(
        name="loss_of_consciousness",
        label="意识丧失",
        question_template="发作的时候意识清楚吗？",
        examples=["完全不知道发生了什么", "有点印象但模糊", "意识清楚"],
        dialect_aliases={"昏过去了": "是", "晕过去了": "是"},
    ),
    "affected_limb": SymptomSlot(
        name="affected_limb",
        label="发作部位",
        question_template="抽搐主要发生在哪些部位？",
        examples=["四肢", "右侧手脚", "只有嘴角"],
        dialect_aliases={"小手臂": "前臂", "脚杆": "小腿"},
    ),
    "tongue_biting": SymptomSlot(
        name="tongue_biting",
        label="舌咬伤",
        question_template="发作时有没有咬到舌头？",
        examples=["有", "没有", "不确定"],
    ),
    "post_ictal_confusion": SymptomSlot(
        name="post_ictal_confusion",
        label="发作后状态",
        question_template="发作之后多久能清醒？能回忆发作过程吗？",
        examples=["几分钟就清醒了", "迷糊了很久", "完全不记得"],
    ),
    "current_medications": SymptomSlot(
        name="current_medications",
        label="当前用药",
        question_template="您目前正在服用哪些抗癫痫药物？剂量是多少？",
        examples=["左乙拉西坦早晚各500mg", "丙戊酸钠500mg每日两次"],
    ),
    "medication_adherence": SymptomSlot(
        name="medication_adherence",
        label="用药依从性",
        question_template="平时吃药规律吗？有没有漏服过？",
        examples=["规律服药", "偶尔漏服", "经常漏服", "自行停过药"],
    ),
    "seizure_triggers": SymptomSlot(
        name="seizure_triggers",
        label="可能的诱因",
        question_template="发作前有没有什么特殊情况？比如熬夜、情绪激动、闪光等？",
        examples=["熬夜后容易发", "情绪紧张时发", "闪光刺激诱发", "饮酒后"],
        dialect_aliases={"闷倒": "突然发作"},
    ),
    "previous_diagnosis": SymptomSlot(
        name="previous_diagnosis",
        label="既往诊断",
        question_template="之前在医院做过什么检查或诊断吗？",
        examples=["做过脑电图", "CT显示正常", "诊断为癫痫"],
    ),
    "family_history": SymptomSlot(
        name="family_history",
        label="家族史",
        question_template="家里有没有其他人也有癫痫或抽搐的情况？",
        examples=["父亲有", "无家族史", "不太清楚"],
    ),
}


# ============================================================
# 对话轮次
# ============================================================


class DialogueTurn(BaseModel):
    """单轮对话"""

    model_config = ConfigDict(ser_json_timedelta="iso8601")

    turn_id: str = Field(default_factory=lambda: str(uuid.uuid4().hex[:8]))
    turn_index: int = 0
    timestamp: datetime = Field(default_factory=datetime.now)

    # 用户输入
    user_message: str = ""
    normalized_message: str = ""
    medical_entities: list[dict] = Field(default_factory=list)

    # 系统输出
    system_response: str = ""
    action_type: ActionType = ActionType.ASK_QUESTION

    # 本轮收集的槽位
    collected_slots: dict[str, Any] = Field(default_factory=dict)

    # 指代消解信息
    resolved_entities: list[dict] = Field(default_factory=list)

    # 本轮检测到的急危重症迹象
    emergency_signs: list[str] = Field(default_factory=list)


# ============================================================
# 对话状态
# ============================================================


class ConversationState(BaseModel):
    """
    会话状态：跟踪整个问诊会话的完整上下文

    这是 V2 相比 V1 的核心区别：
    - V1: 每次请求独立，AgentState 不持久化
    - V2: 每个 session_id 对应一个持久化的 ConversationState
    """

    model_config = ConfigDict(ser_json_timedelta="iso8601")

    session_id: str = Field(default_factory=lambda: str(uuid.uuid4().hex[:12]))
    patient_id: str | None = None

    # 问诊进度
    current_phase: DialoguePhase = DialoguePhase.GREETING
    completed_phases: list[DialoguePhase] = Field(default_factory=list)
    completion_percentage: float = 0.0  # 0.0 ~ 1.0

    # 槽位管理
    slots: dict[str, SymptomSlot] = Field(default_factory=dict)
    asked_slots: set[str] = Field(default_factory=set)  # 已询问过的槽位
    confirmed_slots: set[str] = Field(default_factory=set)  # 已确认的槽位

    # 对话历史
    turns: list[DialogueTurn] = Field(default_factory=list)
    turn_count: int = 0

    # 紧迫性
    urgency: UrgencyLevel = UrgencyLevel.LOW
    emergency_detected: bool = False
    emergency_signs: list[str] = Field(default_factory=list)

    # 诊断相关
    draft_diagnoses: list[str] = Field(default_factory=list)
    suggested_actions: list[str] = Field(default_factory=list)

    # 检索与上下文
    retrieved_evidence: list[dict] = Field(default_factory=list)
    current_intent: IntentTypeV2 = IntentTypeV2.GENERAL

    # 元数据
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
    last_activity: datetime = Field(default_factory=datetime.now)

    # 会话标签
    tags: set[str] = Field(default_factory=set)

    # ─────────────────────────────────────────────────────────
    # 槽位管理方法
    # ─────────────────────────────────────────────────────────

    def init_slots(self) -> None:
        """初始化所有预定义槽位"""
        if not self.slots:
            self.slots = {k: SymptomSlot(**v.model_dump()) for k, v in SYMPTOM_SLOTS.items()}

    def update_slot(self, slot_name: str, value: Any) -> bool:
        """更新槽位值"""
        if slot_name not in self.slots:
            return False
        self.slots[slot_name].mark_collected(value)
        self.confirmed_slots.add(slot_name)
        self.updated_at = datetime.now()
        self.last_activity = datetime.now()
        return True

    def mark_slot_asked(self, slot_name: str) -> bool:
        """标记槽位已被询问"""
        if slot_name not in self.slots:
            return False
        self.slots[slot_name].mark_asked()
        self.asked_slots.add(slot_name)
        return True

    def get_required_slots(self) -> list[str]:
        """获取未收集的必填槽位"""
        return [
            name for name, slot in self.slots.items() if slot.is_required and not slot.is_collected
        ]

    def get_missing_required_slots(self) -> list[str]:
        """获取缺失的必填槽位（优先级排序）"""
        priority_order = [
            "chief_complaint",
            "seizure_duration",
            "loss_of_consciousness",
            "affected_limb",
            "seizure_frequency",
            "current_medications",
            "medication_adherence",
            "post_ictal_confusion",
            "seizure_triggers",
            "previous_diagnosis",
            "family_history",
        ]
        missing = self.get_required_slots()
        return [s for s in priority_order if s in missing]

    def get_optional_slots(self) -> list[str]:
        """获取未收集的可选槽位"""
        return [
            name
            for name, slot in self.slots.items()
            if not slot.is_required and not slot.is_collected
        ]

    # ─────────────────────────────────────────────────────────
    # 对话历史管理
    # ─────────────────────────────────────────────────────────

    def add_turn(
        self,
        user_message: str,
        system_response: str,
        action_type: ActionType = ActionType.ASK_QUESTION,
        collected_slots: dict[str, Any] | None = None,
        normalized_message: str = "",
        medical_entities: list[dict] | None = None,
        resolved_entities: list[dict] | None = None,
        emergency_signs: list[str] | None = None,
    ) -> DialogueTurn:
        """添加一轮对话"""
        self.turn_count += 1
        turn = DialogueTurn(
            turn_index=self.turn_count,
            user_message=user_message,
            normalized_message=normalized_message or user_message,
            medical_entities=medical_entities or [],
            system_response=system_response,
            action_type=action_type,
            collected_slots=collected_slots or {},
            resolved_entities=resolved_entities or [],
            emergency_signs=emergency_signs or [],
        )
        self.turns.append(turn)

        # 更新实体到检索上下文
        for entity in medical_entities or []:
            self.tags.add(entity.get("medical_term", ""))

        self.updated_at = datetime.now()
        self.last_activity = datetime.now()
        return turn

    def get_recent_turns(self, n: int = 5) -> list[DialogueTurn]:
        """获取最近n轮对话"""
        return self.turns[-n:] if self.turns else []

    # ─────────────────────────────────────────────────────────
    # 紧迫性管理
    # ─────────────────────────────────────────────────────────

    def set_urgency(self, level: UrgencyLevel, signs: list[str] | None = None) -> None:
        """设置紧迫性"""
        self.urgency = level
        self.emergency_detected = level == UrgencyLevel.CRITICAL
        if signs:
            self.emergency_signs.extend(signs)

    def is_critical(self) -> bool:
        """是否急危重症"""
        return self.emergency_detected or self.urgency == UrgencyLevel.CRITICAL

    # ─────────────────────────────────────────────────────────
    # 阶段管理
    # ─────────────────────────────────────────────────────────

    def advance_phase(self) -> bool:
        """推进到下一阶段"""
        if self.current_phase == DialoguePhase.COMPLETED:
            return False
        if self.current_phase not in self.completed_phases:
            self.completed_phases.append(self.current_phase)
        self.current_phase = self.current_phase.next()
        self._recalculate_completion()
        return True

    def _recalculate_completion(self) -> None:
        """重新计算完成度"""
        total_phases = len(list(DialoguePhase))
        completed = len(self.completed_phases)
        if self.current_phase == DialoguePhase.COMPLETED:
            self.completion_percentage = 1.0
        else:
            self.completion_percentage = completed / total_phases

    # ─────────────────────────────────────────────────────────
    # 序列化
    # ─────────────────────────────────────────────────────────

    def to_dict(self) -> dict:
        """转换为字典（用于 Redis 存储）"""
        return self.model_dump()

    @classmethod
    def from_dict(cls, data: dict) -> ConversationState:
        """从字典恢复（用于 Redis 读取）"""
        # 恢复 slots
        if "slots" in data and isinstance(data["slots"], dict):
            restored_slots = {}
            for name, slot_data in data["slots"].items():
                if isinstance(slot_data, SymptomSlot):
                    restored_slots[name] = slot_data
                elif isinstance(slot_data, dict):
                    restored_slots[name] = SymptomSlot(**slot_data)
            data["slots"] = restored_slots
        return cls(**data)

    # ─────────────────────────────────────────────────────────
    # 摘要信息
    # ─────────────────────────────────────────────────────────

    def get_summary(self) -> dict:
        """获取问诊摘要"""
        collected = {name: slot.value for name, slot in self.slots.items() if slot.is_collected}
        return {
            "session_id": self.session_id,
            "phase": self.current_phase.value,
            "completion": f"{self.completion_percentage:.0%}",
            "urgency": self.urgency.value,
            "turn_count": self.turn_count,
            "collected_slots": collected,
            "pending_required": self.get_missing_required_slots(),
            "draft_diagnoses": self.draft_diagnoses,
        }


# ============================================================
# 规范化结果
# ============================================================


class MedicalEntity(BaseModel):
    """医学实体"""

    text: str  # 原始文本
    normalized: str  # 标准化文本
    medical_term: str  # 医学术语
    category: str  # 类别: symptom, body_part, drug, exam, ...
    confidence: float = 1.0  # 置信度 0-1
    position: tuple[int, int] | None = None  # 在原文中的位置


class NormalizationResult(BaseModel):
    """方言与口语规范化结果"""

    original_text: str
    normalized_text: str
    medical_entities: list[MedicalEntity] = Field(default_factory=list)
    transformations: list[Transformation] = Field(default_factory=list)  # 变换历史
    urgency_signs: list[str] = Field(default_factory=list)  # 紧迫性信号


class Transformation(BaseModel):
    """规范化变换记录"""

    stage: str  # 阶段: dialect, symptom, body_part, medical_term
    original: str  # 原始词
    replacement: str  # 替换后
    confidence: float


# ============================================================
# 指代消解
# ============================================================


class ResolvedEntity(BaseModel):
    """消解后的实体"""

    pronoun: str  # 代词原文
    resolved_to: str  # 消解到的实体
    entity_type: str  # 实体类型
    source_turn: int = -1  # 来源轮次（-1表示来自槽位）


class CoreferenceChain(BaseModel):
    """指代链"""

    pronoun: str  # 代词
    antecedent: str  # 指代对象
    entity_type: str  # 实体类型


class ResolvedUtterance(BaseModel):
    """指代消解结果"""

    original: str  # 原始输入
    resolved: str  # 消解后的文本
    resolved_entities: list[ResolvedEntity] = Field(default_factory=list)
    coreference_chains: list[CoreferenceChain] = Field(default_factory=list)


# ============================================================
# V2 API 请求/响应模型
# ============================================================


class ConversationStartRequest(BaseModel):
    """开始新问诊"""

    patient_id: str | None = None
    initial_complaint: str | None = None


class ConversationStartResponse(BaseModel):
    """开始问诊响应"""

    session_id: str
    greeting: str
    first_question: str
    estimated_turns: int = 5


class ConversationTurnRequest(BaseModel):
    """对话轮次请求"""

    session_id: str
    message: str  # 用户消息
    with_trace: bool = False  # 是否返回详细链路


class ConversationTurnResponse(BaseModel):
    """对话轮次响应"""

    session_id: str
    response: str  # 医生回复
    action_type: ActionType
    phase: DialoguePhase
    completion: float  # 完成度 0.0-1.0
    urgency: UrgencyLevel
    emergency_detected: bool
    emergency_signs: list[str] = Field(default_factory=list)
    collected_slots: dict[str, Any] = Field(default_factory=dict)
    suggested_action: str | None = None
    trace: list[str] = Field(default_factory=list)


class ConsultationSummaryRequest(BaseModel):
    """请求问诊总结"""

    session_id: str


class ConsultationSummaryResponse(BaseModel):
    """问诊总结响应"""

    session_id: str
    summary: str  # 问诊总结
    collected_info: dict[str, Any]  # 收集到的信息
    draft_diagnoses: list[str]  # 初步诊断
    suggested_actions: list[str]  # 建议处置
    referral_urgency: UrgencyLevel  # 转诊紧迫性
    draft_note: str = ""  # 电子病历草稿（可选）
