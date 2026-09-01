"""
V2 安全护栏模块 (Safety Guard V2)

相比 V1 的增强：
1. 独立的急危重症检测（EmergencyDetector）
2. 输入层安全检查（危险表述过滤）
3. 输出层安全清洗（幻觉检测、免责声明强制添加）
4. 医学事实一致性检查
"""

from __future__ import annotations

import re
from typing import Any

from ..schemas_v2 import UrgencyLevel


class EmergencyDetector:
    """
    急危重症检测器

    基于规则 + 关键词的急危重症检测
    检测到急危重症时立即触发紧急干预流程
    """

    # 急危重症关键词及其严重程度
    CRITICAL_KEYWORDS = {
        # 癫痫持续状态
        "持续抽搐": 1.0,
        "一直抽": 1.0,
        "抽个不停": 1.0,
        "停不下来": 0.95,
        "5分钟": 1.0,
        "超过5分钟": 1.0,
        "10分钟以上": 1.0,
        "status epilepticus": 1.0,
        # 意识障碍
        "叫不醒": 1.0,
        "不省人事": 0.95,
        "完全没有反应": 1.0,
        "呼吸不正常": 1.0,
        "喘不上气": 0.9,
        "嘴唇发紫": 0.95,
        "嘴唇发乌": 0.95,
        # 发作后状态
        "一直不清醒": 0.9,
        "一直迷糊": 0.85,
        "发作后偏瘫": 1.0,
        # 外伤
        "咬舌头": 0.85,
        "摔伤了": 0.8,
        "头部受伤": 0.9,
        "流血了": 0.75,
        # 妊娠
        "怀孕": 0.7,
        "孕妇": 0.7,
        "妊娠": 0.7,
        # 药物不良反应
        "皮疹": 0.6,
        "过敏": 0.6,
        "肝功能异常": 0.75,
    }

    HIGH_URGENCY_KEYWORDS = {
        "第一次发作": 0.8,
        "新出现": 0.75,
        "加重": 0.8,
        "频繁": 0.75,
        "发作多了": 0.8,
        "控制不住": 0.85,
        "没效果": 0.75,
        "耐药": 0.8,
    }

    def detect(
        self,
        user_message: str,
        normalized_message: str = "",
        collected_slots: dict[str, Any] | None = None,
    ) -> tuple[bool, UrgencyLevel, list[str]]:
        """
        检测急危重症信号

        Returns:
            tuple of (is_emergency, urgency_level, detected_signs)
        """
        text = (normalized_message or user_message).lower()
        detected_signs: list[str] = []

        # 检查急危重症关键词
        for keyword in self.CRITICAL_KEYWORDS:
            if keyword.lower() in text:
                detected_signs.append(keyword)

        # 检查高紧迫性关键词
        for keyword in self.HIGH_URGENCY_KEYWORDS:
            if keyword.lower() in text:
                detected_signs.append(f"[需关注] {keyword}")

        # 检查槽位中的急危重症信号
        slots = collected_slots or {}
        if "seizure_duration" in slots:
            duration = str(slots["seizure_duration"]).lower()
            # 检测分钟数
            minute_match = re.search(r"(\d+)\s*[分分钟]", duration)
            if minute_match:
                minutes = int(minute_match.group(1))
                if minutes >= 5:
                    detected_signs.append(f"发作持续{minutes}分钟（>5分钟）")
                elif minutes >= 3:
                    detected_signs.append(f"发作持续{minutes}分钟")

        # 确定紧迫性等级
        if detected_signs:
            has_critical = any(kw in text for kw in self.CRITICAL_KEYWORDS.keys())
            if has_critical:
                return True, UrgencyLevel.CRITICAL, detected_signs
            return True, UrgencyLevel.HIGH, detected_signs

        return False, UrgencyLevel.LOW, []

    def generate_emergency_warning(
        self,
        urgency: UrgencyLevel,
        signs: list[str],
    ) -> str:
        """生成紧急警告消息"""
        if urgency == UrgencyLevel.CRITICAL:
            return (
                "【紧急提示】\n\n"
                "根据您描述的情况，可能涉及急危重症，请立即采取以下措施：\n\n"
                "1. 如果抽搐持续超过5分钟，立即拨打120急救电话\n"
                "2. 保持患者侧卧位，防止窒息\n"
                "3. 不要强行按住患者或往嘴里塞东西\n"
                "4. 记录发作开始时间\n\n"
                f"我们检测到的紧急信号：{', '.join(signs)}\n\n"
                "在等待急救时，请保持冷静，遵医嘱处理。"
            )
        elif urgency == UrgencyLevel.HIGH:
            return (
                "【重要提示】\n\n"
                "根据您的描述，建议尽快就医：\n\n"
                "1. 建议尽快预约神经内科门诊\n"
                "2. 如症状加重或频繁发作，请就近急诊\n"
                "3. 记录发作情况（时间、症状、持续时间）\n\n"
                f"我们关注到以下情况：{', '.join(signs)}\n\n"
                "如有任何紧急情况，请立即就医或拨打急救电话。"
            )
        return ""


class SafetyGuardV2:
    """
    V2 安全护栏

    多层安全检查：
    1. 输入层：危险表述过滤
    2. 处理层：幻觉检测
    3. 输出层：免责声明强制添加、内容清洗
    """

    # 危险表述（需要过滤或警告的）
    DANGEROUS_PATTERNS = [
        (r"自杀|自残|轻生", "suicide"),
        (r"不用看医生|不用去医院", "avoid_medical"),
        (r"自行停药|自己减药", "self_adjust_medication"),
    ]

    # 幻觉检测关键词（用于检测模型是否在编造信息）
    HALLUCINATION_KEYWORDS = [
        "著名研究表明",
        "据权威数据显示",
        "临床试验证明",
        "100%有效",
        "保证治愈",
        "绝对安全",
    ]

    def __init__(
        self,
        require_disclaimer: bool = True,
        allow_unverified_advice: bool = False,
    ):
        self.require_disclaimer = require_disclaimer
        self.allow_unverified_advice = allow_unverified_advice
        self.emergency_detector = EmergencyDetector()

    def check_input(self, user_message: str) -> tuple[bool, str | None]:
        """
        检查用户输入是否包含危险表述

        Returns:
            tuple of (is_safe, warning_message)
        """
        text = user_message.lower()

        for pattern, category in self.DANGEROUS_PATTERNS:
            if re.search(pattern, text):
                if category == "suicide":
                    return False, (
                        "如果您有自杀想法，请立即寻求帮助。\n"
                        "全国心理援助热线：400-821-1215\n"
                        "紧急情况请拨打110或120。"
                    )
                elif category == "avoid_medical":
                    return False, (
                        "请务必重视您的情况，及时就医。\n" "本系统不能替代专业医生的诊断和治疗。"
                    )
                elif category == "self_adjust_medication":
                    return False, (
                        "调整药物剂量需在医生指导下进行，"
                        "请勿自行停药或改变剂量。\n"
                        "如有用药问题，请咨询您的主治医生。"
                    )

        return True, None

    def guard_output(
        self,
        response: str,
        user_message: str = "",
        collected_slots: dict[str, Any] | None = None,
    ) -> str:
        """
        输出安全护栏

        1. 剔除 <thinking> 等思维链标签
        2. 剔除 <final_answer> 等 XML 标签
        3. 清理多余空行
        4. 强制添加免责声明
        5. 检测幻觉表述
        """
        result = response.strip()

        # Step 1: 剔除思维链标签
        result = re.sub(r"<thinking>\s*.*?\s*</thinking>", "", result, flags=re.DOTALL)
        result = re.sub(r"<\/?analysis>", "", result, flags=re.DOTALL)

        # Step 2: 剔除 XML 标签
        result = re.sub(r"<final_answer>\s*", "", result, flags=re.DOTALL)
        result = re.sub(r"\s*</final_answer>", "", result, flags=re.DOTALL)
        result = re.sub(r"<answer>\s*", "", result, flags=re.DOTALL)
        result = re.sub(r"\s*</answer>", "", result, flags=re.DOTALL)

        # Step 3: 清理多余空行
        result = re.sub(r"\n{3,}", "\n\n", result)
        result = result.strip()

        # Step 4: 检测幻觉表述并添加警告
        for keyword in self.HALLUCINATION_KEYWORDS:
            if keyword in result:
                result = result.replace(
                    keyword,
                    f"[注意：以下信息需要进一步核实] {keyword}",
                )

        # Step 5: 强制添加免责声明
        if self.require_disclaimer and "不能替代" not in result.lower():
            disclaimer = (
                "\n\n---\n"
                "⚠️ 免责声明：本回答仅供参考，不能替代医生的诊断和治疗。"
                "如有健康问题，请及时就医。"
            )
            result += disclaimer

        return result

    def detect_emergency(
        self,
        user_message: str,
        normalized_message: str = "",
        collected_slots: dict[str, Any] | None = None,
    ) -> tuple[bool, UrgencyLevel, list[str]]:
        """检测急危重症"""
        return self.emergency_detector.detect(user_message, normalized_message, collected_slots)


# 全局单例
_default_guard: SafetyGuardV2 | None = None


def get_safety_guard() -> SafetyGuardV2:
    """获取全局安全护栏实例"""
    global _default_guard
    if _default_guard is None:
        _default_guard = SafetyGuardV2()
    return _default_guard
