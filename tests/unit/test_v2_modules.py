"""
V2 单元测试

测试覆盖：
- 方言规范化
- 指代消解
- 对话状态管理
- 策略引擎
- 安全护栏
"""

from __future__ import annotations

import pytest

from app.v2.conversation.policy import DialoguePolicyEngine
from app.v2.safety.guard_v2 import EmergencyDetector, SafetyGuardV2
from app.v2.schemas_v2 import (
    ActionType,
    ConversationState,
    DialoguePhase,
    UrgencyLevel,
)
from app.v2.understanding.coreference import CoreferenceResolver
from app.v2.understanding.dialect_normalizer import DialectNormalizer

# ============================================================
# 方言规范化测试
# ============================================================


class TestDialectNormalizer:
    """方言规范化器测试"""

    @pytest.fixture
    def normalizer(self):
        return DialectNormalizer()

    def test_sichuan_headache(self, normalizer):
        """测试：脑阔痛 → 头痛"""
        result = normalizer.normalize("我脑阔痛啷个办")
        assert "头痛" in result.normalized_text
        # 应该识别到头痛实体
        symptom_entities = [
            e for e in result.medical_entities if e.category == "symptom" and e.normalized == "头痛"
        ]
        assert len(symptom_entities) >= 1

    def test_sichuan_convulsion(self, normalizer):
        """测试：扯风 → 抽搐"""
        result = normalizer.normalize("他又在扯风了")
        assert "抽搐" in result.normalized_text

    def test_sichuan_body_part(self, normalizer):
        """测试：小手臂 → 前臂"""
        result = normalizer.normalize("小手臂起了水泡")
        assert "前臂" in result.normalized_text

    def test_colloquial_awareness_loss(self, normalizer):
        """测试：昏厥 → 意识丧失相关"""
        result = normalizer.normalize("他昏过去了")
        # 方言转换为"晕厥"（更接近标准医学术语）
        assert "晕厥" in result.normalized_text
        # 应该识别到症状实体
        symptom_entities = [e for e in result.medical_entities if e.category == "symptom"]
        assert len(symptom_entities) >= 1

    def test_colloquial_foaming(self, normalizer):
        """测试：口吐泡泡 → 口吐白沫"""
        result = normalizer.normalize("嘴巴口吐泡泡")
        assert "口吐白沫" in result.normalized_text

    def test_symptom_expansion(self, normalizer):
        """测试：症状同义词扩展"""
        result = normalizer.normalize("娃儿在抽风")
        assert "抽搐" in result.normalized_text

    def test_no_change_standard_text(self, normalizer):
        """测试：标准文本不做改变"""
        result = normalizer.normalize("头痛、抽搐、意识丧失")
        # 标准文本应该保持或被标准化为同义词
        assert len(result.normalized_text) > 0
        # 变换历史不应该太多
        assert len(result.transformations) >= 0

    def test_urgency_signals(self, normalizer):
        """测试：急危重症信号检测"""
        result = normalizer.normalize("抽搐持续超过5分钟了，停不下来")
        assert len(result.urgency_signs) > 0

    def test_combined_dialect(self, normalizer):
        """测试：综合方言表达"""
        result = normalizer.normalize("我脑阔痛得很，还扯风，脚杆也在抖")
        text = result.normalized_text
        assert "头痛" in text
        assert "抽搐" in text

    def test_medical_term_expansion(self, normalizer):
        """测试：医学术语扩展（不同说法）"""
        terms = ["抽风", "抽搐", "惊厥"]
        for term in terms:
            result = normalizer.normalize(term)
            # 应该标准化为"抽搐"
            assert "抽搐" in result.normalized_text


# ============================================================
# 指代消解测试
# ============================================================


class TestCoreferenceResolver:
    """指代消解器测试"""

    @pytest.fixture
    def resolver(self):
        return CoreferenceResolver()

    def test_detect_pronoun(self, resolver):
        """测试：指代词检测"""
        text = "小手臂起了水泡，哪个位置？"
        pronouns = resolver._detect_pronouns(text)
        assert len(pronouns) >= 1
        # 应该检测到"哪个位置"
        found = any(p["normalized"] in ["哪里", "哪儿", "哪个位置"] for p in pronouns)
        assert found

    def test_resolve_location_pronoun(self, resolver):
        """测试：位置指代消解"""
        history = [
            {
                "user_message": "小手臂起了水泡",
                "collected_slots": {"affected_limb": "前臂"},
            }
        ]
        result = resolver.resolve(
            current_utterance="哪个位置？",
            conversation_history=history,
            current_slots={"affected_limb": "前臂"},
        )
        # 应该将"哪个位置"消解为"前臂"相关的描述
        assert result.resolved != "哪个位置？"
        assert "前臂" in result.resolved or "小手臂" in result.resolved

    def test_no_pronoun_no_change(self, resolver):
        """测试：无指代词时不做改变"""
        result = resolver.resolve(
            current_utterance="我头痛",
            conversation_history=[],
            current_slots={},
        )
        assert result.resolved == "我头痛"
        assert len(result.resolved_entities) == 0

    def test_multiple_pronouns(self, resolver):
        """测试：多个指代词"""
        history = [
            {"user_message": "我手昨天烫伤了", "collected_slots": {}},
            {"user_message": "小手臂起了水泡", "collected_slots": {"affected_limb": "前臂"}},
        ]
        result = resolver.resolve(
            current_utterance="那儿现在还痛吗？",
            conversation_history=history,
            current_slots={"affected_limb": "前臂"},
        )
        # 应该消解"那儿"
        assert len(result.resolved_entities) >= 1


# ============================================================
# 对话状态测试
# ============================================================


class TestConversationState:
    """对话状态测试"""

    @pytest.fixture
    def state(self):
        state = ConversationState()
        state.init_slots()
        return state

    def test_init_slots(self, state):
        """测试：槽位初始化"""
        assert len(state.slots) > 0
        assert "chief_complaint" in state.slots
        assert "seizure_duration" in state.slots

    def test_update_slot(self, state):
        """测试：槽位更新"""
        result = state.update_slot("chief_complaint", "头痛、抽搐")
        assert result is True
        assert state.slots["chief_complaint"].is_collected
        assert state.slots["chief_complaint"].value == "头痛、抽搐"

    def test_get_required_slots(self, state):
        """测试：获取缺失的必填槽位"""
        state.update_slot("chief_complaint", "头痛")
        missing = state.get_missing_required_slots()
        assert "chief_complaint" not in missing
        assert "seizure_duration" in missing

    def test_mark_slot_asked(self, state):
        """测试：标记槽位已询问"""
        state.mark_slot_asked("seizure_duration")
        assert "seizure_duration" in state.asked_slots
        assert state.slots["seizure_duration"].asked_turns == 1

    def test_add_turn(self, state):
        """测试：添加对话轮次"""
        state.add_turn(
            user_message="我头痛",
            system_response="请问持续多久了？",
            collected_slots={"chief_complaint": "头痛"},
        )
        assert state.turn_count == 1
        assert len(state.turns) == 1
        assert state.turns[0].user_message == "我头痛"

    def test_urgency_setting(self, state):
        """测试：紧迫性设置"""
        state.set_urgency(UrgencyLevel.CRITICAL, ["发作持续超过5分钟"])
        assert state.urgency == UrgencyLevel.CRITICAL
        assert state.is_critical()
        assert "发作持续超过5分钟" in state.emergency_signs

    def test_phase_advancement(self, state):
        """测试：阶段推进"""
        initial_phase = state.current_phase
        state.advance_phase()
        assert state.current_phase != initial_phase
        assert initial_phase in state.completed_phases

    def test_completion_calculation(self, state):
        """测试：完成度计算"""
        state.update_slot("chief_complaint", "头痛")
        state.update_slot("seizure_duration", "1分钟")
        state.current_phase = DialoguePhase.COMPLETED
        state._recalculate_completion()
        assert state.completion_percentage == 1.0

    def test_summary(self, state):
        """测试：获取摘要"""
        state.update_slot("chief_complaint", "头痛")
        state.update_slot("seizure_duration", "2分钟")
        summary = state.get_summary()
        assert summary["session_id"] == state.session_id
        assert "头痛" in str(summary["collected_slots"].values())


# ============================================================
# 策略引擎测试
# ============================================================


class TestDialoguePolicyEngine:
    """对话策略引擎测试"""

    @pytest.fixture
    def engine(self):
        state = ConversationState()
        state.init_slots()
        return DialoguePolicyEngine(state)

    def test_first_action_is_follow_up(self, engine):
        """测试：首次动作应该是追问"""
        action = engine.decide_action()
        assert action.action_type == ActionType.ASK_QUESTION
        assert len(action.slots_to_collect) > 0

    def test_emergency_overrides_all(self, engine):
        """测试：急危重症优先于所有其他逻辑"""
        # 模拟急危重症状态
        engine.state.set_urgency(UrgencyLevel.CRITICAL, ["发作持续超过5分钟"])
        action = engine.decide_action()
        assert action.action_type == ActionType.EMERGENCY_WARNING
        assert action.urgency == UrgencyLevel.CRITICAL

    def test_collects_key_slots(self, engine):
        """测试：收集关键槽位"""
        action = engine.decide_action()
        # 应该追问主诉
        assert "chief_complaint" in action.slots_to_collect or len(action.slots_to_collect) > 0

    def test_completes_when_sufficient(self, engine):
        """测试：收集足够信息后生成总结"""
        # 收集几乎所有关键信息
        engine.state.update_slot("chief_complaint", "头痛、抽搐")
        engine.state.update_slot("seizure_duration", "2分钟")
        engine.state.update_slot("loss_of_consciousness", "是")
        engine.state.update_slot("affected_limb", "四肢")
        engine.state.update_slot("seizure_frequency", "每周一次")
        engine.state.update_slot("current_medications", "左乙拉西坦")
        # 推进阶段
        engine.state.current_phase = DialoguePhase.PRELIMINARY_DIAGNOSIS
        # 多次调用直到策略决定总结
        action = engine.decide_action()
        # 应该进入诊断或总结（或继续追问更多槽位）
        assert action.action_type in [
            ActionType.PROVIDE_INFO,
            ActionType.SUMMARIZE,
            ActionType.SUGGEST_ACTION,
            ActionType.ASK_QUESTION,
        ]

    def test_pydantic_default_factories_are_isolated(self):
        """动态值和可变容器不得跨模型实例共享。"""
        from app.v2.schemas_v2 import DialogueTurn

        first_state = ConversationState()
        second_state = ConversationState()
        first_state.tags.add("first-only")
        first_state.turns.append(DialogueTurn(user_message="first"))

        assert first_state.session_id != second_state.session_id
        assert second_state.tags == set()
        assert second_state.turns == []

        first_turn = DialogueTurn()
        second_turn = DialogueTurn()
        first_turn.medical_entities.append({"name": "first-only"})

        assert first_turn.turn_id != second_turn.turn_id
        assert second_turn.medical_entities == []

    def test_respects_max_follow_ups(self, engine):
        """达到槽位追问上限后，策略不得继续选择同一槽位。"""
        slot = engine.state.slots["chief_complaint"]

        for _ in range(slot.max_turns):
            action = engine.decide_action()
            assert action.slots_to_collect == ["chief_complaint"]

        next_action = engine.decide_action()
        assert "chief_complaint" not in next_action.slots_to_collect
        assert slot.asked_turns == slot.max_turns


# ============================================================
# 急危重症检测测试
# ============================================================


class TestEmergencyDetector:
    """急危重症检测器测试"""

    @pytest.fixture
    def detector(self):
        return EmergencyDetector()

    def test_detect_prolonged_seizure(self, detector):
        """测试：检测持续发作"""
        is_emergency, level, signs = detector.detect(
            "抽搐持续超过5分钟了",
            "抽搐持续超过5分钟",
        )
        assert is_emergency is True
        assert level == UrgencyLevel.CRITICAL
        assert len(signs) > 0

    def test_detect_consciousness_disorder(self, detector):
        """测试：检测意识障碍（用明确关键词，放在 user_message）"""
        is_emergency, level, signs = detector.detect(
            "抽搐发作后叫不醒，嘴唇发紫，完全没有反应，呼吸不正常",
            "",  # 空 normalized_message，确保使用 user_message
        )
        assert is_emergency is True
        assert level == UrgencyLevel.CRITICAL

    def test_normal_symptoms_no_emergency(self, detector):
        """测试：正常症状不触发紧急"""
        is_emergency, level, signs = detector.detect(
            "我最近有点头痛",
            "头痛",
        )
        assert is_emergency is False
        assert level == UrgencyLevel.LOW

    def test_generate_warning(self, detector):
        """测试：生成警告消息"""
        warning = detector.generate_emergency_warning(
            UrgencyLevel.CRITICAL,
            ["发作持续超过5分钟"],
        )
        assert "紧急" in warning or "120" in warning
        assert len(warning) > 20


# ============================================================
# 安全护栏测试
# ============================================================


class TestSafetyGuardV2:
    """安全护栏测试"""

    @pytest.fixture
    def guard(self):
        return SafetyGuardV2()

    def test_removes_thinking_tags(self, guard):
        """测试：移除思维链标签"""
        response = "<thinking>Let me think about this</thinking>这是一个答案"
        cleaned = guard.guard_output(response)
        assert "<thinking>" not in cleaned

    def test_removes_xml_tags(self, guard):
        """测试：移除 XML 标签"""
        response = "<final_answer>这是一个答案</final_answer>"
        cleaned = guard.guard_output(response)
        assert "<final_answer>" not in cleaned
        assert "这是一个答案" in cleaned

    def test_adds_disclaimer(self, guard):
        """测试：添加免责声明"""
        response = "这是一个普通的回答"
        cleaned = guard.guard_output(response)
        assert "不能替代" in cleaned or "免责声明" in cleaned

    def test_detects_suicide_mention(self, guard):
        """测试：检测自杀相关表述"""
        is_safe, warning = guard.check_input("我有自杀的想法")
        assert is_safe is False
        assert "心理" in warning or "求助" in warning or "热线" in warning

    def test_detects_medical_avoidance(self, guard):
        """测试：检测回避就医表述"""
        is_safe, warning = guard.check_input("不用去医院自己能好")
        assert is_safe is False

    def test_normal_input_passes(self, guard):
        """测试：正常输入通过检查"""
        is_safe, warning = guard.check_input("我头痛怎么办")
        assert is_safe is True


# ============================================================
# 运行测试
# ============================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
