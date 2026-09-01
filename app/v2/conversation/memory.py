"""
V2 对话记忆管理模块

采用 Last-Recent-Important (LRI) 压缩策略：
- 保留最近 N 轮完整历史
- 对更早历史进行摘要压缩
- 医学关键信息永久保留

V2-001 迭代: 解决上下文压缩和记忆管理问题
"""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable
from typing import Any

from ..schemas_v2 import ConversationState, DialogueTurn


class ConversationMemory:
    """
    对话记忆管理器：压缩历史对话，保留关键医学信息

    压缩策略：
    1. 保留最近 max_turns 轮完整对话
    2. 对早期对话做摘要压缩
    3. 医学关键信息（症状、药物、诊断）永不丢失
    4. 超过 max_age_seconds 的旧会话自动归档
    """

    def __init__(
        self,
        max_turns: int = 20,
        max_tokens: int = 4096,
        max_age_seconds: int = 1800,  # 30分钟无活动则归档
        importance_weight_fn: Callable[[DialogueTurn, dict], float] | None = None,
    ):
        self.max_turns = max_turns
        self.max_tokens = max_tokens
        self.max_age_seconds = max_age_seconds
        self.importance_weight_fn = importance_weight_fn or self._default_importance

        # 内存中的会话状态缓存
        self._state_cache: dict[str, ConversationState] = {}

        # Redis 客户端（可选）
        self._redis = None

    def _default_importance(self, turn: DialogueTurn, current_slots: dict) -> float:
        """
        默认重要性评分函数
        医学信息 > 闲聊，症状 > 一般信息
        """
        score = 1.0
        msg = turn.user_message.lower()

        # 医学关键词加权
        medical_keywords = {
            "症状",
            "发作",
            "抽搐",
            "癫痫",
            "药物",
            "剂量",
            "脑电图",
            "意识",
            "倒地",
            "口吐",
            "舌咬",
            "头痛",
            "头晕",
            "麻木",
            "左乙",
            "丙戊",
            "symptom",
            "seizure",
            "epilepsy",
            "medication",
        }
        if any(kw in msg for kw in medical_keywords):
            score += 3.0

        # 当前槽位相关
        for slot_name in turn.collected_slots:
            if slot_name in current_slots:
                score += 2.0

        # 急危重症迹象
        if turn.emergency_signs:
            score += 5.0

        return score

    # ─────────────────────────────────────────────────────────
    # 会话状态管理
    # ─────────────────────────────────────────────────────────

    def get_state(self, session_id: str) -> ConversationState | None:
        """获取会话状态（从缓存或存储）"""
        # 先查缓存
        if session_id in self._state_cache:
            state = self._state_cache[session_id]
            # 检查是否过期
            if self._is_state_expired(state):
                self._archive_state(state)
                del self._state_cache[session_id]
                return None
            return state

        # 从 Redis 加载
        if self._redis:
            return self._load_from_redis(session_id)

        return None

    def save_state(self, state: ConversationState) -> None:
        """保存会话状态"""
        state.updated_at = state.last_activity

        # 更新缓存
        self._state_cache[state.session_id] = state

        # 持久化到 Redis
        if self._redis:
            self._save_to_redis(state)

    def delete_state(self, session_id: str) -> None:
        """删除会话状态"""
        if session_id in self._state_cache:
            state = self._state_cache[session_id]
            self._archive_state(state)
            del self._state_cache[session_id]

        if self._redis:
            key = f"conv_state:{session_id}"
            self._redis.delete(key)

    def _is_state_expired(self, state: ConversationState) -> bool:
        """检查会话是否过期"""
        import datetime

        now = datetime.datetime.now()
        age = (now - state.last_activity).total_seconds()
        return age > self.max_age_seconds

    def _archive_state(self, state: ConversationState) -> None:
        """归档旧会话"""
        # 可以将历史对话写入知识库或归档存储
        pass

    # ─────────────────────────────────────────────────────────
    # 历史压缩
    # ─────────────────────────────────────────────────────────

    def compress_history(
        self,
        history: list[DialogueTurn],
        current_slots: dict[str, Any],
    ) -> list[DialogueTurn]:
        """
        对话历史压缩算法

        策略：
        1. 计算每轮的重要性分数
        2. 保留最近的 max_turns 轮完整对话
        3. 对早期对话做摘要压缩
        4. 急危重症信息永久保留
        """
        if not history:
            return []

        # Step 1: 分离最近轮次和早期轮次
        recent_turns = history[-self.max_turns :] if len(history) > self.max_turns else history
        early_turns = history[: -self.max_turns] if len(history) > self.max_turns else []

        # Step 2: 检查最近的轮次是否有急危重症
        has_emergency = any(t.emergency_signs for t in history)

        # Step 3: 对早期轮次做摘要
        if early_turns:
            summary_turn = self._summarize_early_turns(
                early_turns, current_slots, preserve_emergency=has_emergency
            )
            return [summary_turn] + recent_turns

        return recent_turns

    def _summarize_early_turns(
        self,
        early_turns: list[DialogueTurn],
        current_slots: dict[str, Any],
        preserve_emergency: bool = False,
    ) -> DialogueTurn:
        """
        将早期对话压缩为一个摘要轮次

        保留：
        - 所有已收集的槽位信息
        - 急危重症信息（如果有）
        - 关键医学实体的首次出现
        """
        # 收集所有已确认的槽位
        all_collected_slots: dict[str, Any] = {}
        all_medical_entities: list[dict] = []
        emergency_signs: list[str] = []

        for turn in early_turns:
            all_collected_slots.update(turn.collected_slots)
            all_medical_entities.extend(turn.medical_entities)
            emergency_signs.extend(turn.emergency_signs)

        # 构建摘要文本
        summary_parts = []
        if all_collected_slots:
            slot_summary = "；".join(f"{k}: {v}" for k, v in all_collected_slots.items() if v)
            summary_parts.append(f"已收集信息：{slot_summary}")

        if emergency_signs:
            summary_parts.append(f"急危重症迹象：{'、'.join(set(emergency_signs))}")

        summary_text = " | ".join(summary_parts) if summary_parts else "[早期对话摘要]"

        return DialogueTurn(
            turn_id="summary",
            turn_index=0,
            user_message="[早期对话摘要]",
            system_response=summary_text,
            collected_slots=all_collected_slots,
            medical_entities=all_medical_entities,
            emergency_signs=list(set(emergency_signs)) if emergency_signs else [],
        )

    def build_context_for_retrieval(
        self,
        history: list[DialogueTurn],
        current_slots: dict[str, Any],
        max_turns: int = 5,
    ) -> str:
        """
        构建用于检索的上下文文本

        将对话历史转换为适合作为检索上下文的文本格式
        """
        if not history:
            return ""

        # 压缩历史
        compressed = self.compress_history(history, current_slots)

        # 取最近 max_turns 轮
        recent = compressed[-max_turns:] if len(compressed) > max_turns else compressed

        # 构建上下文文本
        context_parts = []

        # 先添加已收集的关键槽位
        collected = {k: v for k, v in current_slots.items() if v is not None and str(v).strip()}
        if collected:
            context_parts.append("【已收集症状信息】")
            for slot_name, slot_value in collected.items():
                context_parts.append(f"- {slot_name}: {slot_value}")

        # 添加最近的对话历史
        context_parts.append("\n【最近对话历史】")
        for turn in recent:
            if turn.user_message and turn.user_message != "[早期对话摘要]":
                context_parts.append(f"患者: {turn.user_message}")
            if turn.system_response:
                # 截断系统回复，只保留关键信息
                resp = (
                    turn.system_response[:200] + "..."
                    if len(turn.system_response) > 200
                    else turn.system_response
                )
                context_parts.append(f"医生: {resp}")

        return "\n".join(context_parts)

    def build_context_for_generation(
        self,
        history: list[DialogueTurn],
        current_slots: dict[str, Any],
        max_turns: int = 3,
    ) -> str:
        """
        构建用于生成的上下文文本

        比检索上下文更简洁，专注于当前对话流
        """
        if not history:
            return ""

        recent = history[-max_turns:] if len(history) > max_turns else history

        context_parts = []
        for turn in recent:
            if turn.user_message and turn.user_message != "[早期对话摘要]":
                context_parts.append(f"患者：{turn.user_message}")
            if turn.system_response and turn.system_response != "[早期对话摘要]":
                context_parts.append(f"医生：{turn.system_response}")

        return "\n".join(context_parts)

    # ─────────────────────────────────────────────────────────
    # Redis 集成（可选）
    # ─────────────────────────────────────────────────────────

    def connect_redis(self, redis_client) -> None:
        """连接 Redis 用于分布式会话状态存储"""
        self._redis = redis_client

    def _load_from_redis(self, session_id: str) -> ConversationState | None:
        """从 Redis 加载会话状态"""
        if not self._redis:
            return None

        try:
            key = f"conv_state:{session_id}"
            data = self._redis.hgetall(key)
            if not data:
                return None

            # 反序列化
            state_dict = {}
            for field, value in data.items():
                if field == "data":
                    state_dict = json.loads(value)
                    break

            if state_dict:
                return ConversationState.from_dict(state_dict)
        except Exception:
            pass

        return None

    def _save_to_redis(self, state: ConversationState) -> None:
        """保存会话状态到 Redis"""
        if not self._redis:
            return

        try:
            key = f"conv_state:{state.session_id}"
            self._redis.hset(
                key,
                mapping={
                    "data": json.dumps(state.to_dict(), default=str),
                    "updated_at": str(int(time.time())),
                },
            )
            # 设置过期时间
            self._redis.expire(key, self.max_age_seconds + 300)
        except Exception:
            pass

    # ─────────────────────────────────────────────────────────
    # 工具方法
    # ─────────────────────────────────────────────────────────

    def get_turn_hash(self, turn: DialogueTurn) -> str:
        """获取对话轮次的哈希值（用于去重）"""
        content = f"{turn.turn_index}:{turn.user_message}:{turn.system_response}"
        return hashlib.md5(content.encode()).hexdigest()[:8]

    def deduplicate_turns(self, turns: list[DialogueTurn]) -> list[DialogueTurn]:
        """去除重复的对话轮次"""
        seen_hashes = set()
        result = []
        for turn in turns:
            h = self.get_turn_hash(turn)
            if h not in seen_hashes:
                seen_hashes.add(h)
                result.append(turn)
        return result
