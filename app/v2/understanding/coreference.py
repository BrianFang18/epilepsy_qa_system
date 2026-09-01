"""
V2 指代消解模块 (Coreference Resolution)

解决代词、指示词、指别词指向哪个实体的问题。
V2-003 迭代：解决"小手臂起了水泡，模型再次问哪个位置"的重复询问问题
"""

from __future__ import annotations

import re
from typing import Any

from ..schemas_v2 import (
    CoreferenceChain,
    ResolvedEntity,
    ResolvedUtterance,
)


class CoreferenceResolver:
    """
    指代消解器：解决代词、指示词、指别词指向哪个实体

    医疗场景专用的指代消解规则：
    - "这/那/它" → 前文提到的症状/部位
    - "哪个位置/哪儿" → 前文提到的身体部位
    - "上次/那会儿" → 既往病史中的时间
    - "那种情况/这个" → 前文提到的发作场景
    """

    # 医疗场景高频指代词及其消解策略
    MEDICAL_PRONOUNS: dict[str, dict] = {
        "这": {
            "type": "current_entity",
            "description": "当前提到的症状/部位",
            "priority": 1,
        },
        "那": {
            "type": "previous_entity",
            "description": "之前提到的症状/部位",
            "priority": 2,
        },
        "它": {
            "type": "antecedent",
            "description": "前一句的主语",
            "priority": 1,
        },
        "这个": {
            "type": "current_entity",
            "description": "刚提到的实体",
            "priority": 1,
        },
        "那个": {
            "type": "previous_entity",
            "description": "之前提到的实体",
            "priority": 2,
        },
        "这里": {
            "type": "body_part",
            "description": "身体部位",
            "priority": 1,
        },
        "那里": {
            "type": "body_part",
            "description": "身体部位",
            "priority": 1,
        },
        "这儿": {
            "type": "body_part",
            "description": "身体部位",
            "priority": 1,
        },
        "那儿": {
            "type": "body_part",
            "description": "身体部位",
            "priority": 1,
        },
        "哪儿": {
            "type": "location_query",
            "description": "需要追问或引用位置",
            "priority": 3,
        },
        "哪里": {
            "type": "location_query",
            "description": "需要追问或引用位置",
            "priority": 3,
        },
        "哪个位置": {
            "type": "location_query",
            "description": "需要引用之前提到的位置",
            "priority": 3,
        },
        "哪种": {
            "type": "symptom_query",
            "description": "需要引用之前的症状类型",
            "priority": 3,
        },
        "什么情况": {
            "type": "situation_query",
            "description": "需要引用之前描述的情况",
            "priority": 3,
        },
        "上次": {
            "type": "past_reference",
            "description": "既往病史中的时间",
            "priority": 2,
        },
        "那会儿": {
            "type": "past_reference",
            "description": "既往病史中的时间",
            "priority": 2,
        },
        "那时候": {
            "type": "past_reference",
            "description": "既往病史中的时间",
            "priority": 2,
        },
        "那个情况": {
            "type": "previous_situation",
            "description": "之前提到的发作情况",
            "priority": 2,
        },
        "这个症状": {
            "type": "current_symptom",
            "description": "当前正在讨论的症状",
            "priority": 1,
        },
        "那种症状": {
            "type": "previous_symptom",
            "description": "之前提到的症状",
            "priority": 2,
        },
        "这个情况": {
            "type": "current_situation",
            "description": "当前正在描述的情况",
            "priority": 1,
        },
    }

    # 需要消解的指代词正则
    PRONOUN_PATTERN = re.compile(
        r"(?:"
        r"这(?:个|儿|里|种)?|"
        r"那(?:个|儿|里|种|种情(?:况|况))?|"
        r"它(?:个)?|"
        r"哪(?:儿|里|个位置)|"
        r"上(?:次)|"
        r"那(?:会儿|时候)|"
        r"什么情况|"
        r"哪种|"
        r"这儿|那儿"
        r")",
        re.IGNORECASE,
    )

    def __init__(self, use_llm_fallback: bool = True):
        """
        Args:
            use_llm_fallback: 当规则无法消解时，是否使用 LLM 兜底
        """
        self.use_llm_fallback = use_llm_fallback

    def resolve(
        self,
        current_utterance: str,
        conversation_history: list[dict] | None = None,
        current_slots: dict[str, Any] | None = None,
        llm_client: Any = None,
    ) -> ResolvedUtterance:
        """
        指代消解主流程

        Args:
            current_utterance: 当前用户输入
            conversation_history: 对话历史（每项包含 user_message, collected_slots 等）
            current_slots: 当前已收集的槽位
            llm_client: LLM 客户端（用于 LLM 兜底）

        Returns:
            ResolvedUtterance: 包含消解后的文本和指代链
        """
        resolved = current_utterance
        resolved_entities: list[ResolvedEntity] = []
        coreference_chains: list[CoreferenceChain] = []

        # Step 1: 检测指代词
        pronouns = self._detect_pronouns(current_utterance)

        if not pronouns:
            return ResolvedUtterance(
                original=current_utterance,
                resolved=current_utterance,
                resolved_entities=[],
                coreference_chains=[],
            )

        history = conversation_history or []
        slots = current_slots or {}

        # Step 2: 对每个指代词寻找候选实体
        for pronoun_info in pronouns:
            pronoun = pronoun_info["text"]
            position = pronoun_info["position"]

            # 寻找候选实体
            candidate = self._find_candidate_entity(
                pronoun=pronoun,
                history=history,
                slots=slots,
            )

            if candidate:
                # Step 3: 替换指代词
                resolved = self._replace_pronoun_at(
                    text=resolved,
                    pronoun=pronoun,
                    position=position,
                    replacement=candidate["text"],
                )

                resolved_entities.append(
                    ResolvedEntity(
                        pronoun=pronoun,
                        resolved_to=candidate["text"],
                        entity_type=candidate["type"],
                        source_turn=candidate.get("turn_index", -1),
                    )
                )

                coreference_chains.append(
                    CoreferenceChain(
                        pronoun=pronoun,
                        antecedent=candidate["text"],
                        entity_type=candidate["type"],
                    )
                )

        # Step 4: LLM 兜底（如果规则无法完全消解）
        if self.use_llm_fallback and llm_client and resolved == current_utterance:
            resolved = self._llm_fallback_resolve(current_utterance, history, llm_client)

        return ResolvedUtterance(
            original=current_utterance,
            resolved=resolved,
            resolved_entities=resolved_entities,
            coreference_chains=coreference_chains,
        )

    def _detect_pronouns(self, text: str) -> list[dict]:
        """
        检测文本中的指代词

        Returns:
            list of {text, position}: 检测到的指代词及其在文本中的位置
        """
        pronouns: list[dict] = []

        for m in self.PRONOUN_PATTERN.finditer(text):
            pronoun = m.group()
            # 规范化
            normalized = self._normalize_pronoun(pronoun)
            if normalized in self.MEDICAL_PRONOUNS:
                pronouns.append(
                    {
                        "text": pronoun,
                        "normalized": normalized,
                        "position": (m.start(), m.end()),
                    }
                )

        # 去重（保留最长的）
        if pronouns:
            pronouns.sort(key=lambda x: len(x["text"]), reverse=True)
            seen = set()
            filtered = []
            for p in pronouns:
                # 避免"这"和"这个"同时匹配
                key = p["position"][0]
                if key not in seen:
                    filtered.append(p)
                    seen.add(key)
            return filtered

        return []

    def _normalize_pronoun(self, pronoun: str) -> str:
        """规范化指代词到标准形式"""
        # 四川话常见变体
        variants = {
            "这儿": "这里",
            "那儿": "那里",
            "哪个位置": "哪里",
        }
        return variants.get(pronoun, pronoun)

    def _find_candidate_entity(
        self,
        pronoun: str,
        history: list[dict],
        slots: dict[str, Any],
    ) -> dict | None:
        """
        寻找指代词指向的实体

        优先级策略：
        1. 当前槽位中的相关实体（最近添加的）
        2. 对话历史中最近提到的相关实体
        3. 按时间回溯查找
        """
        # 时间相关的指代 → 查找历史中的时间描述
        if pronoun in ["上次", "那会儿", "那时候"]:
            return self._find_time_reference(history)

        # 位置相关的指代 → 查找最近提到的身体部位
        if pronoun in ["哪儿", "哪里", "哪个位置", "这里", "那里", "这儿", "那儿"]:
            # 优先使用槽位中的部位信息
            body_part = self._get_body_part_from_slots(slots)
            if body_part:
                return body_part

            # 在历史中查找
            for item in reversed(history):
                body_part = self._get_body_part_from_turn(item)
                if body_part:
                    return body_part

        # 症状/情况相关 → 查找历史中的症状
        if pronoun in ["那个", "那个情况", "那种情况", "那种", "那"]:
            for item in reversed(history):
                symptom = self._get_symptom_from_turn(item)
                if symptom:
                    return symptom

        # 当前症状/情况
        if pronoun in ["这个", "这个情况", "这个症状", "这"]:
            # 从最近的轮次获取
            if history:
                symptom = self._get_symptom_from_turn(history[-1])
                if symptom:
                    return symptom

            # 从槽位获取
            symptom = self._get_symptom_from_slots(slots)
            if symptom:
                return symptom

        # 泛指的"它"
        if pronoun in ["它", "它个"]:
            if history:
                return self._get_last_mentioned_entity(history[-1])

        return None

    def _get_body_part_from_slots(self, slots: dict[str, Any]) -> dict | None:
        """从槽位中提取身体部位"""
        body_part_slots = [
            "affected_limb",
            "chief_complaint",
            "symptom_location",
            "pain_location",
        ]
        for slot_name in body_part_slots:
            if slot_name in slots and slots[slot_name]:
                value = slots[slot_name]
                if isinstance(value, str) and value.strip():
                    return {
                        "text": value,
                        "type": "body_part",
                        "source": "slot",
                    }
        return None

    def _get_body_part_from_turn(self, turn: dict) -> dict | None:
        """从对话轮次中提取身体部位"""
        # 检查 collected_slots
        if "collected_slots" in turn:
            result = self._get_body_part_from_slots(turn["collected_slots"])
            if result:
                return result

        # 从 user_message 中提取身体部位关键词
        body_keywords = [
            "手臂",
            "腿",
            "脚",
            "手",
            "头",
            "脸",
            "口",
            "眼",
            "背",
            "胸",
            "腹",
            "颈",
            "前臂",
            "小腿",
            "小手臂",
            "脑壳",
            "脑阔",
            "脚杆",
            "颈子",
            "手杆",
        ]
        msg = turn.get("user_message", "")

        # 查找最近提到的部位
        for keyword in body_keywords:
            idx = msg.rfind(keyword)
            if idx != -1:
                # 提取上下文
                start = max(0, idx - 3)
                end = min(len(msg), idx + len(keyword) + 5)
                return {
                    "text": msg[start:end].strip(),
                    "type": "body_part",
                    "source": "history",
                }

        return None

    def _get_symptom_from_slots(self, slots: dict[str, Any]) -> dict | None:
        """从槽位中提取症状"""
        symptom_slots = [
            "chief_complaint",
            "symptom_description",
            "main_symptom",
            "seizure_type",
        ]
        for slot_name in symptom_slots:
            if slot_name in slots and slots[slot_name]:
                value = slots[slot_name]
                if isinstance(value, str) and value.strip():
                    return {
                        "text": value,
                        "type": "symptom",
                        "source": "slot",
                    }
        return None

    def _get_symptom_from_turn(self, turn: dict) -> dict | None:
        """从对话轮次中提取症状"""
        # 从 collected_slots
        if "collected_slots" in turn:
            result = self._get_symptom_from_slots(turn["collected_slots"])
            if result:
                return result

        # 从 user_message 提取
        msg = turn.get("user_message", "")
        symptom_keywords = [
            "抽搐",
            "头痛",
            "晕",
            "痛",
            "麻",
            "吐",
            "抽",
            "扯风",
            "发作了",
            "翻",
            "僵",
            "软",
        ]
        for keyword in symptom_keywords:
            idx = msg.rfind(keyword)
            if idx != -1:
                start = max(0, idx - 5)
                end = min(len(msg), idx + len(keyword) + 5)
                return {
                    "text": msg[start:end].strip(),
                    "type": "symptom",
                    "source": "history",
                }

        return None

    def _get_last_mentioned_entity(self, turn: dict) -> dict | None:
        """获取上一个轮次中提到的最后一个实体"""
        # 优先使用主诉
        if "collected_slots" in turn:
            cs = turn["collected_slots"]
            if "chief_complaint" in cs:
                return {"text": str(cs["chief_complaint"]), "type": "entity", "source": "slot"}
            if "main_symptom" in cs:
                return {"text": str(cs["main_symptom"]), "type": "entity", "source": "slot"}

        # 从 user_message 提取
        msg = turn.get("user_message", "")
        if msg:
            # 取最后50个字符作为上下文
            context = msg[-50:] if len(msg) > 50 else msg
            return {"text": context.strip(), "type": "context", "source": "message"}

        return None

    def _find_time_reference(self, history: list[dict]) -> dict | None:
        """查找时间相关引用"""
        time_keywords = ["昨天", "今天", "前几天", "上周", "去年", "小时候", "之前", "最近"]

        for item in reversed(history):
            msg = item.get("user_message", "")
            for keyword in time_keywords:
                if keyword in msg:
                    idx = msg.find(keyword)
                    start = max(0, idx - 5)
                    end = min(len(msg), idx + 20)
                    return {
                        "text": msg[start:end].strip(),
                        "type": "time_reference",
                        "source": "history",
                    }

        return None

    def _replace_pronoun_at(
        self,
        text: str,
        pronoun: str,
        position: tuple[int, int],
        replacement: str,
    ) -> str:
        """
        在指定位置替换指代词
        智能判断替换策略：
        - 如果是"哪个位置"→直接替换为具体位置
        - 如果是"这/那"→可能需要扩展替换
        """
        start, end = position

        # 特殊处理"哪个位置"
        if pronoun in ["哪个位置", "哪里", "哪儿"]:
            # 直接插入具体位置
            return text[:start] + replacement + text[end:]

        # 对于指示代词，可能需要更完整的替换
        return text[:start] + replacement + text[end:]

    def _llm_fallback_resolve(
        self,
        utterance: str,
        history: list[dict],
        llm_client: Any,
    ) -> str:
        """
        LLM 兜底：当规则无法消解时，使用 LLM 进行指代消解
        """
        history_text = ""
        for i, turn in enumerate(history[-3:]):
            history_text += f"[轮次{i+1}] 用户: {turn.get('user_message', '')}\n"
            history_text += f"[轮次{i+1}] 系统: {turn.get('system_response', '')}\n"

        prompt = f"""你是一个医学问诊系统的指代消解专家。

请根据对话历史，消解当前用户输入中的指代词。

对话历史：
{history_text}

当前用户输入：{utterance}

请只返回消解后的文本（不需要解释）。如果当前输入中没有需要消解的指代词，直接返回原输入。"""

        try:
            result = llm_client.chat(
                [{"role": "user", "content": prompt}],
                temperature=0.0,
                max_tokens=256,
            )
            return result.strip() if result.strip() else utterance
        except Exception:
            return utterance
