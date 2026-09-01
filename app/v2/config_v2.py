"""
V2 配置模块

扩展配置项用于支持：
- Redis 缓存
- Milvus 向量数据库
- 多级缓存策略
- V2 工作流参数
"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class SettingsV2(BaseSettings):
    """V2 配置"""

    # ── V2 开关 ──────────────────────────────────────────────
    enable_v2_workflow: bool = False  # 启用 V2 工作流
    enable_redis: bool = False  # 启用 Redis
    enable_graphrag: bool = False  # 启用 GraphRAG

    # ── Redis 配置 ────────────────────────────────────────────
    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_db: int = 0
    redis_password: str | None = None
    redis_session_ttl: int = 1800  # 30分钟
    redis_cache_ttl: int = 86400  # 24小时

    # ── Milvus 配置 ───────────────────────────────────────────
    milvus_host: str = "localhost"
    milvus_port: int = 19530
    milvus_user: str = ""
    milvus_password: str = ""
    milvus_collection: str = "epilepsy_medical"

    # ── Neo4j 配置 ────────────────────────────────────────────
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = ""

    # ── 多级缓存配置 ──────────────────────────────────────────
    cache_semantic_enabled: bool = True
    cache_semantic_threshold: float = 0.92  # 语义相似度阈值
    cache_semantic_ttl: int = 86400  # 24小时

    # ── 方言配置 ──────────────────────────────────────────────
    dialect_enabled: bool = True
    dialect_default_type: str = "sichuan"  # 默认方言类型
    dialect_confidence_threshold: float = 0.7  # 最小置信度

    # ── 急危重症检测配置 ──────────────────────────────────────
    emergency_critical_threshold: float = 0.9  # 急危重症阈值
    emergency_high_threshold: float = 0.7  # 高紧迫性阈值

    # ── 对话配置 ──────────────────────────────────────────────
    conversation_max_turns: int = 20  # 最大对话轮次
    conversation_max_age_seconds: int = 1800  # 30分钟无活动则过期
    conversation_max_tokens: int = 4096  # 对话历史最大 token 数

    # ── 检索配置 ──────────────────────────────────────────────
    retrieval_local_search_depth: int = 2  # GraphRAG local search 深度
    retrieval_community_top_k: int = 5  # GraphRAG global search 社区数
    retrieval_enable_rerank: bool = True  # 是否启用重排

    # ── 生成配置 ──────────────────────────────────────────────
    generation_temperature: float = 0.3  # 生成温度
    generation_max_tokens: int = 1024  # 最大 token 数
    generation_doctor_persona: str = "癫痫专科资深医生"  # 医生人设

    # ── 安全配置 ──────────────────────────────────────────────
    safety_require_disclaimer: bool = True  # 强制添加免责声明
    safety_allow_unverified: bool = False  # 允许非验证医学建议

    # ── API 配置 ──────────────────────────────────────────────
    api_auth_enabled: bool = False  # 启用 API 认证
    api_rate_limit: int = 60  # 每分钟请求数限制

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


@lru_cache(maxsize=1)
def get_settings_v2() -> SettingsV2:
    """获取 V2 配置（单例）"""
    return SettingsV2()
