"""
V2 Module: 癫痫专科智能问诊系统 V2 升级模块

目录结构:
    app/v2/
    ├── __init__.py
    ├── conversation/          # 对话管理
    │   ├── __init__.py
    │   ├── state.py            # ConversationState 对话状态
    │   ├── policy.py           # DialoguePolicyEngine 策略引擎
    │   ├── memory.py           # ConversationMemory 记忆管理
    │   └── nodes.py            # 症状引导图节点定义
    ├── understanding/          # 语义理解
    │   ├── __init__.py
    │   ├── dialect_normalizer.py  # 方言与口语规范化
    │   └── coreference.py      # 指代消解
    ├── schemas_v2.py           # V2 数据模型
    └── config_v2.py            # V2 配置
"""

from __future__ import annotations

# 子模块
from .conversation import ConversationMemory, ConversationState, DialoguePolicyEngine
from .understanding import CoreferenceResolver, DialectNormalizer

__all__ = [
    "ConversationState",
    "DialoguePolicyEngine",
    "ConversationMemory",
    "DialectNormalizer",
    "CoreferenceResolver",
]
