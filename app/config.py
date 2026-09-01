from __future__ import annotations

from functools import lru_cache

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # 应用基础运行参数。
    app_name: str = "Epilepsy Agentic RAG System"
    environment: str = "dev"
    host: str = "0.0.0.0"
    port: int = 8010
    cors_origins: list[str] = Field(
        default_factory=lambda: ["http://localhost:5173", "http://127.0.0.1:5173"]
    )

    # 可选功能必须显式开启；demo 数据默认永不自动写入。
    enable_v2_workflow: bool = False
    enable_admin_api: bool = False
    seed_demo_data: bool = False

    # 为 true 时，LLM 与检索走本地可预测的 mock 逻辑。
    mock_mode: bool = False

    # OpenAI 兼容接口配置（vLLM 默认提供该协议）。
    llm_api_base: str = "http://127.0.0.1:8000/v1"
    llm_api_key: str = "EMPTY"
    llm_model: str = "DeepSeek-R1-Distill-Qwen-32B-AWQ"
    llm_temperature: float = 0.2
    llm_max_tokens: int = 1024

    # 新流式 chat 使用独立的 OpenAI 兼容配置；未设置时兼容旧 LLM 配置。
    deepseek_base_url: str | None = None
    deepseek_api_key: str | None = None
    deepseek_model: str | None = None
    deepseek_timeout_seconds: float = Field(default=30.0, gt=0, le=300)

    # 新 chat 图的证据边界。所有历史仅在单次请求内使用，不持久化。
    chat_top_k: int = Field(default=5, ge=1, le=20)
    chat_min_evidence_score: float = Field(default=0.0, ge=0.0)
    chat_max_context_chars: int = Field(default=6000, ge=500, le=20000)
    chat_max_excerpt_chars: int = Field(default=800, ge=100, le=2000)

    # 检索与排序相关参数。
    embed_dim: int = 1024
    dense_top_k: int = 12
    sparse_top_k: int = 12
    final_top_k: int = 6
    hybrid_dense_weight: float = 0.65
    hybrid_sparse_weight: float = 0.35
    reranker_top_k: int = 5
    max_context_chars: int = 5000

    # 向量数据库配置（Qdrant 可选）。
    use_qdrant: bool = False
    qdrant_url: str = "http://127.0.0.1:6333"
    qdrant_api_key: str | None = None
    qdrant_collection: str = "epilepsy_hybrid_docs"

    # 管理面 PostgreSQL 与 MinIO。两者只在管理功能开启后使用。
    database_url: str = "postgresql+psycopg://epilepsy:epilepsy@127.0.0.1:5432/epilepsy"
    database_echo: bool = False
    database_pool_size: int = Field(default=5, ge=1, le=20)
    minio_endpoint: str = "127.0.0.1:9000"
    minio_access_key: SecretStr = SecretStr("minioadmin")
    minio_secret_key: SecretStr = SecretStr("minioadmin")
    minio_secure: bool = False
    minio_region: str | None = None
    minio_documents_bucket: str = "epilepsy-documents"
    minio_evaluations_bucket: str = "epilepsy-evaluations"

    # 管理员凭据仅用于首次引导；会话原始 token 永不写入数据库。
    admin_bootstrap_username: str | None = None
    admin_bootstrap_password: SecretStr | None = None
    admin_session_cookie_name: str = "epilepsy_admin_session"
    admin_session_ttl_seconds: int = Field(default=1800, ge=300, le=86400)
    admin_cookie_secure: bool = False
    admin_max_upload_bytes: int = Field(default=25 * 1024 * 1024, ge=1024, le=100 * 1024 * 1024)

    # 摄取流水线版本组成幂等键，升级任一版本都会生成新的不可变文档版本。
    ingestion_parser_version: str = "mineru-parser-v1"
    ingestion_chunker_version: str = "parent-child-v1"
    ingestion_index_version: str = "qdrant-hybrid-rrf-v1"

    # PostgreSQL job 队列与 worker lease。
    worker_poll_seconds: float = Field(default=2.0, ge=0.1, le=60)
    worker_lease_seconds: int = Field(default=300, ge=30, le=3600)
    worker_heartbeat_seconds: int = Field(default=30, ge=5, le=300)
    worker_max_attempts: int = Field(default=3, ge=1, le=10)
    worker_retry_base_seconds: int = Field(default=30, ge=1, le=3600)
    evaluation_max_attempts: int = Field(default=2, ge=1, le=10)

    # 向量模型本地路径。
    embed_model_name: str = "BAAI/bge-m3"
    embed_model_path: str = "/home/brian/llm/BAAI/bge-m3"
    reranker_model_path: str = "/home/brian/llm/BAAI/bge-reranker-large"

    # 回答安全边界控制。
    allow_unverified_medical_advice: bool = False
    cot_mode: str = "structured"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    # 仅初始化一次，避免每次请求重复读取环境变量。
    return Settings()
