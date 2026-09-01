"""
V2 对话策略引擎 (DialoguePolicyEngine)

基于规则的医生风格问诊策略，决定下一步问什么。
核心设计：急危重症优先 → 追问缺失信息 → 推进问诊阶段 → 生成总结

V2-001 迭代: 实现真正的医生风格多轮问诊
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..schemas_v2 import ActionType, ConversationState, DialoguePhase, UrgencyLevel


class DialoguePolicyEngine:
    """
    对话策略引擎：决定下一步问什么、做什么

    决策逻辑：
    1. 急危重症检测 → 触发紧急干预（最高优先）
    2. 缺失必填槽位 → 追问（按优先级）
    3. 当前阶段完成 → 推进到下一阶段
    4. 问诊完成 → 生成总结和建议
    5. 其他情况 → 选择性追问或继续当前流程
    """

    # 症状追问优先级（医学重要性排序）
    SLOT_PRIORITY = [
        "chief_complaint",  # 主诉
        "seizure_duration",  # 发作持续时间（>5分钟=急危重症）
        "loss_of_consciousness",  # 意识状态
        "seizure_type",  # 发作类型
        "affected_limb",  # 发作部位
        "post_ictal_confusion",  # 发作后状态
        "seizure_frequency",  # 发作频率
        "seizure_triggers",  # 诱因
        "current_medications",  # 当前用药
        "medication_adherence",  # 用药依从性
        "previous_diagnosis",  # 既往诊断
        "family_history",  # 家族史
    ]

    # 每个阶段默认最多追问轮次
    MAX_FOLLOW_UP_TURNS = {
        DialoguePhase.GREETING: 1,
        DialoguePhase.SYMPTOM_COLLECTION: 5,
        DialoguePhase.SEIZURE_CHARACTER: 4,
        DialoguePhase.MEDICAL_HISTORY: 3,
        DialoguePhase.MEDICATION_HISTORY: 3,
        DialoguePhase.TRIGGER_ANALYSIS: 2,
        DialoguePhase.FOLLOW_UP: 2,
    }

    def __init__(self, state: ConversationState):
        self.state = state

    def decide_action(self) -> DialogueAction:
        """
        决定下一步动作

        这是策略引擎的核心方法，根据当前状态决定：
        - 应该追问什么
        - 是否需要紧急干预
        - 是否可以推进问诊阶段
        """
        # Step 1: 急危重症检查（最高优先）
        if self._has_critical_urgency():
            return self._create_emergency_action()

        # Step 2: 检查缺失的必填槽位
        missing_required = self.state.get_missing_required_slots()
        if missing_required:
            next_slot = self._select_next_slot(missing_required)
            if next_slot:
                return self._create_follow_up_action(next_slot)

        # Step 3: 检查当前阶段的追问次数
        if self._exceeded_follow_up_limit():
            # 推进到下一阶段
            if self.state.advance_phase():
                return self._create_phase_intro_action()
            else:
                return self._create_consultation_complete_action()

        # Step 4: 检查是否可以进入诊断阶段
        if self._is_ready_for_diagnosis():
            self.state.current_phase = DialoguePhase.PRELIMINARY_DIAGNOSIS
            return self._create_diagnosis_action()

        # Step 5: 生成可选追问
        optional_slots = self.state.get_optional_slots()
        if optional_slots:
            next_slot = self._select_optional_slot(optional_slots)
            if next_slot:
                return self._create_follow_up_action(next_slot)

        # Step 6: 检查问诊完成条件
        if self._is_sufficient_for_summary():
            return self._create_consultation_complete_action()

        # Step 7: 默认：继续当前阶段的追问
        return self._create_default_action()

    def _has_critical_urgency(self) -> bool:
        """检查是否有急危重症迹象"""
        # 检查状态中的急危重症标志
        if self.state.is_critical():
            return True

        # 检查已收集的槽位中的急危重症信号
        slots = self.state.slots

        # 发作持续时间 > 5 分钟
        duration_slot = slots.get("seizure_duration")
        if duration_slot and duration_slot.value:
            duration_text = str(duration_slot.value).lower()
            # 检测分钟数
            import re

            minute_match = re.search(r"(\d+)\s*分", duration_text)
            if minute_match:
                minutes = int(minute_match.group(1))
                if minutes >= 5:
                    self.state.set_urgency(UrgencyLevel.CRITICAL, ["发作持续超过5分钟"])
                    return True

        # 检查系统消息中的急危重症信号
        for turn in self.state.turns[-3:]:
            if turn.emergency_signs:
                self.state.set_urgency(UrgencyLevel.CRITICAL, turn.emergency_signs)
                return True

        return False

    def _create_emergency_action(self) -> DialogueAction:
        """创建紧急干预动作"""
        urgency = self.state.urgency
        signs = self.state.emergency_signs

        # 生成紧急警告消息
        warning_messages = {
            UrgencyLevel.CRITICAL: (
                "【紧急提示】根据您的描述，情况可能比较紧急。"
                "如果抽搐持续超过5分钟、意识不能恢复或出现呼吸困难，"
                "请立即拨打急救电话或前往就近医院急诊！\n\n"
                "在等待急救时，请注意："
                "1. 保持患者侧卧位，防止窒息"
                "2. 不要强行按住患者或往嘴里塞东西"
                "3. 记录发作开始时间"
            ),
            UrgencyLevel.HIGH: (
                "【重要提示】根据您的描述，建议尽快到医院就诊。"
                "如果是第一次出现这种情况，或症状加重，请不要拖延。\n\n"
                "建议：\n"
                "1. 记录发作情况（时间、症状）\n"
                "2. 如有需要，尽快预约神经内科门诊\n"
                "3. 如症状频繁或加重，请就近急诊"
            ),
        }

        message = warning_messages.get(urgency, warning_messages[UrgencyLevel.HIGH])

        if signs:
            message += f"\n\n我们注意到了以下情况：{'、'.join(signs)}"

        return DialogueAction(
            action_type=ActionType.EMERGENCY_WARNING,
            message=message,
            urgency=urgency,
            next_phase=self.state.current_phase,
            suggested_action="立即就医或拨打急救电话",
            slots_to_collect=[],
        )

    def _select_next_slot(self, missing_slots: list[str]) -> str | None:
        """选择下一个要追问的槽位"""
        # 按优先级选择
        for priority_slot in self.SLOT_PRIORITY:
            if priority_slot in missing_slots:
                slot = self.state.slots.get(priority_slot)
                if slot and slot.asked_turns < slot.max_turns:
                    return priority_slot

        # 如果优先级列表中没有合适的，选择第一个
        for slot_name in missing_slots:
            slot = self.state.slots.get(slot_name)
            if slot and slot.asked_turns < slot.max_turns:
                return slot_name

        return None

    def _select_optional_slot(self, optional_slots: list[str]) -> str | None:
        """选择可选追问的槽位"""
        # 优先选择有医学价值的可选槽位
        valuable_optional = [
            "tongue_biting",
            "post_ictal_confusion",
            "seizure_triggers",
        ]
        for slot_name in valuable_optional:
            if slot_name in optional_slots:
                slot = self.state.slots.get(slot_name)
                if slot and slot.asked_turns < slot.max_turns:
                    return slot_name

        # 随机选择一个
        for slot_name in optional_slots:
            slot = self.state.slots.get(slot_name)
            if slot and slot.asked_turns < slot.max_turns:
                return slot_name

        return None

    def _create_follow_up_action(self, slot_name: str) -> DialogueAction:
        """创建追问动作"""
        slot = self.state.slots.get(slot_name)
        if not slot:
            return self._create_default_action()

        # 标记该槽位已被询问
        self.state.mark_slot_asked(slot_name)

        # 获取问题模板
        question = slot.question_template

        # 如果是重复询问，增加提示
        if slot.asked_turns > 0:
            question = f"刚才提到{slot.label}，能再具体说说吗？比如：{'、'.join(slot.examples[:2])}"

        return DialogueAction(
            action_type=ActionType.ASK_QUESTION,
            message=question,
            urgency=self.state.urgency,
            next_phase=self.state.current_phase,
            suggested_action=None,
            slots_to_collect=[slot_name],
        )

    def _exceeded_follow_up_limit(self) -> bool:
        """检查是否超过当前阶段的追问限制"""
        # 检查是否有槽位还在追问中
        for slot in self.state.slots.values():
            if not slot.is_collected and slot.asked_turns >= slot.max_turns:
                return True
        return False

    def _is_ready_for_diagnosis(self) -> bool:
        """检查是否可以进入诊断阶段"""
        # 至少需要收集到主诉和关键信息
        required_for_diagnosis = [
            "chief_complaint",
            "seizure_duration",
            "loss_of_consciousness",
        ]

        collected = sum(
            1
            for name in required_for_diagnosis
            if self.state.slots.get(name) and self.state.slots[name].is_collected
        )

        return collected >= 2

    def _is_sufficient_for_summary(self) -> bool:
        """检查是否足以生成问诊总结"""
        # 收集了足够的必填槽位
        total_required = sum(1 for s in self.state.slots.values() if s.is_required)
        total_collected = sum(
            1 for s in self.state.slots.values() if s.is_required and s.is_collected
        )

        if total_required == 0:
            return False

        return (total_collected / total_required) >= 0.7  # 收集了70%以上即可

    def _create_phase_intro_action(self) -> DialogueAction:
        """创建阶段介绍动作"""
        phase_intros = {
            DialoguePhase.SYMPTOM_COLLECTION: "好的，接下来让我们详细了解一下您的症状。",
            DialoguePhase.SEIZURE_CHARACTER: "现在让我们更详细地了解发作的具体表现。",
            DialoguePhase.MEDICAL_HISTORY: "了解了您的症状后，我再了解一下您的既往病史。",
            DialoguePhase.MEDICATION_HISTORY: "您的用药情况对诊断和治疗很重要，请告诉我。",
            DialoguePhase.FAMILY_HISTORY: "家族史对癫痫的诊断也有参考价值。",
            DialoguePhase.TRIGGER_ANALYSIS: "了解可能的诱因有助于预防发作。",
            DialoguePhase.PRELIMINARY_DIAGNOSIS: "根据您提供的信息，我可以给您一些初步的分析。",
            DialoguePhase.TREATMENT_SUGGESTION: "针对您的情况，我有一些建议。",
            DialoguePhase.FOLLOW_UP: "最后，让我告诉您后续需要注意的事项。",
        }

        message = phase_intros.get(self.state.current_phase, "接下来让我们继续问诊。")

        return DialogueAction(
            action_type=ActionType.PROVIDE_INFO,
            message=message,
            urgency=self.state.urgency,
            next_phase=self.state.current_phase,
            suggested_action=None,
            slots_to_collect=[],
        )

    def _create_diagnosis_action(self) -> DialogueAction:
        """创建诊断阶段动作"""
        return DialogueAction(
            action_type=ActionType.PROVIDE_INFO,
            message="根据您提供的信息，我可以给您一些初步的分析和建议。",
            urgency=self.state.urgency,
            next_phase=DialoguePhase.PRELIMINARY_DIAGNOSIS,
            suggested_action=None,
            slots_to_collect=[],
        )

    def _create_consultation_complete_action(self) -> DialogueAction:
        """创建问诊完成动作"""
        # 更新状态
        self.state.current_phase = DialoguePhase.COMPLETED
        self.state.completion_percentage = 1.0

        collected_count = sum(1 for s in self.state.slots.values() if s.is_collected)

        return DialogueAction(
            action_type=ActionType.SUMMARIZE,
            message=self._generate_summary_prompt(),
            urgency=self.state.urgency,
            next_phase=DialoguePhase.COMPLETED,
            suggested_action="建议：整理好症状记录，按时就医复查",
            slots_to_collect=[],
            metadata={
                "collected_slots_count": collected_count,
                "completion": f"{collected_count}/{len(self.state.slots)}",
            },
        )

    def _generate_summary_prompt(self) -> str:
        """生成总结提示"""
        parts = ["根据您提供的信息，我为您整理以下问诊摘要："]
        parts.append("")

        # 收集到的信息
        parts.append("【已收集信息】")
        for slot in self.state.slots.values():
            if slot.is_collected:
                parts.append(f"- {slot.label}: {slot.value}")

        parts.append("")
        parts.append("【建议】")
        parts.append("1. 如有急危重症迹象，请立即就医")
        parts.append("2. 整理好发作记录（时间、症状、持续时间）")
        parts.append("3. 如需进一步诊断，请预约神经内科门诊")

        return "\n".join(parts)

    def _create_default_action(self) -> DialogueAction:
        """创建默认动作"""
        return DialogueAction(
            action_type=ActionType.ASK_QUESTION,
            message="请问还有什么需要补充的吗？或者您有什么想问的吗？",
            urgency=self.state.urgency,
            next_phase=self.state.current_phase,
            suggested_action=None,
            slots_to_collect=[],
        )

    def process_user_input(
        self,
        user_input: str,
        normalized_input: str,
        extracted_slots: dict[str, Any],
        medical_entities: list[dict],
    ) -> tuple[dict[str, Any], ActionType]:
        """
        处理用户输入，提取槽位信息

        Returns:
            tuple of (extracted_slots, action_type)
        """
        extracted = {}

        # 从规范化后的输入中提取槽位信息
        input_text = normalized_input.lower()

        # 主诉
        if "chief_complaint" not in self.state.confirmed_slots:
            if medical_entities:
                extracted["chief_complaint"] = ";".join(
                    e["normalized"] for e in medical_entities if e.get("category") == "symptom"
                )

        # 发作持续时间
        duration_patterns = [
            (r"(\d+)\s*[秒秒钟]", lambda m: f"{m.group(1)}秒"),
            (r"(\d+)\s*[分分钟]", lambda m: f"{m.group(1)}分钟"),
            (r"(\d+)\s*[小时]", lambda m: f"{m.group(1)}小时"),
            (r"几分钟", lambda _: "几分钟"),
            (r"十多分钟", lambda _: "10多分钟"),
            (r"半小时", lambda _: "30分钟"),
        ]
        if "seizure_duration" not in self.state.confirmed_slots:
            import re

            for pattern, converter in duration_patterns:
                match = re.search(pattern, input_text)
                if match:
                    extracted["seizure_duration"] = converter(match)
                    break

        # 意识状态
        if "loss_of_consciousness" not in self.state.confirmed_slots:
            if any(
                kw in input_text for kw in ["昏过去", "没意识", "不省人事", "意识丧失", "不知道"]
            ):
                extracted["loss_of_consciousness"] = "是"
            elif any(kw in input_text for kw in ["意识清楚", "清醒", "知道"]):
                extracted["loss_of_consciousness"] = "否"

        # 发作部位
        if "affected_limb" not in self.state.confirmed_slots:
            limb_keywords = {
                "四肢": "四肢",
                "全身": "全身",
                "手": "手部",
                "脚": "足部",
                "手臂": "上肢",
                "腿": "下肢",
                "嘴角": "面部",
                "脸": "面部",
                "头": "头部",
            }
            for keyword, value in limb_keywords.items():
                if keyword in input_text:
                    extracted["affected_limb"] = value
                    break

        # 用药情况
        if "current_medications" not in self.state.confirmed_slots:
            drug_keywords = [
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
            for drug in drug_keywords:
                if drug in user_input:
                    if "current_medications" not in extracted:
                        extracted["current_medications"] = drug
                    else:
                        extracted["current_medications"] += f"、{drug}"

        # 用药依从性
        if "medication_adherence" not in self.state.confirmed_slots:
            if "漏服" in input_text or "忘记" in input_text:
                extracted["medication_adherence"] = "偶尔漏服"
            elif "没有吃" in input_text or "停了" in input_text or "没吃" in input_text:
                extracted["medication_adherence"] = "自行停药"

        return extracted, ActionType.ASK_QUESTION


@dataclass
class DialogueAction:
    """对话动作"""

    action_type: ActionType
    message: str
    urgency: UrgencyLevel = UrgencyLevel.LOW
    next_phase: DialoguePhase = DialoguePhase.GREETING
    suggested_action: str | None = None
    slots_to_collect: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
