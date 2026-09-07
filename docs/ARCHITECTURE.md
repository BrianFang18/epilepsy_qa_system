# 架构说明

本文描述当前 `docker-compose.yml` 和应用代码可核对的运行架构。默认 Compose 是 loopback 本地工程 Demo，不是生产部署模板，也不代表真实 LLM、BGE-M3 或临床效果已经验收。

## 1. 默认 Compose 拓扑

```text
Browser
  │ http://127.0.0.1:8080
  ▼
frontend (Nginx + React :8080)
  ├── /api/* ───────────────► api (FastAPI :8010)
  ├── /health* ─────────────► api
  └── /healthz ─────────────► Nginx self-check

api
  ├── PostgreSQL: admin/session/document/job metadata
  ├── MinIO: uploaded original objects
  └── Qdrant: active dense+sparse evidence chunks

postgres healthy ──► migrate (Alembic, one-shot)
postgres/minio/qdrant healthy + migrate succeeded
  ├──► api
  └──► worker (default deterministic ingestion)
api healthy ──► frontend

worker-bge [profile: bge-ingestion, default off]
  └── read-only /models/bge-m3 + PostgreSQL + MinIO + Qdrant
```

默认长期服务是 `postgres`、`minio`、`qdrant`、`api`、`worker` 和 `frontend`。`migrate` 成功后退出。`worker-bge` 不属于默认服务。

所有 Compose 命令必须显式指定环境文件，并建议禁用根 `.env` 隐式读取：

```bash
export COMPOSE_DISABLE_ENV_FILE=1
docker compose --env-file config/compose.env.example config --quiet
docker compose --env-file config/compose.env.example up --build -d
```

## 2. 组件职责

| 组件 | 职责 | 边界 |
| --- | --- | --- |
| `frontend` | 提供 SPA，代理 `/api` 和 `/health`，渲染 SSE、引用、轨迹和管理页面 | 不是公网安全入口 |
| `api` | FastAPI chat/admin/legacy routes；构造 chat 和 admin runtime | readiness 不证明模型质量 |
| `worker` | 默认领取 ingestion job，解析、分块、确定性 embedding、索引和 finalize | 不执行 evaluation job |
| `worker-bge` | opt-in BGE ingestion worker | 需要真实 artifact；profile 本身不是端到端 query 配置 |
| PostgreSQL | admin、session digest、document、job、lease、aggregate evaluation metadata | 不保存上传正文或向量 |
| MinIO | 上传原始对象和预留的私有 evaluation object storage | 与数据库不是单一事务 |
| Qdrant | named dense+sparse vectors、chunk payload、staging/active visibility | activation 与数据库完成不是原子事务 |
| `migrate` | `alembic upgrade head` | 一次性服务 |

宿主端口均绑定 `127.0.0.1`。这减少默认暴露面，但不等于 TLS、认证、网络策略或最小权限已经完成。

## 3. API 启动与模式选择

共享后端镜像的 API command 是标准 Uvicorn：

```text
/opt/container/with-database-url python -m uvicorn app.main:app --host 0.0.0.0 --port 8010
```

`with-database-url` 从 Compose PostgreSQL 变量构造经过 URL 转义的 SQLAlchemy URL。`app.main` 在 lifespan 中构造：

- admin runtime；
- legacy retrieval/service；
- chat service；
- 根据 `CHAT_LLM_MODE` 选择 streaming adapter。

### 3.1 `CHAT_LLM_MODE=demo`

默认使用 `DeterministicEvidenceLLMStreamAdapter`。它不是 LLM：

1. 从 generation prompt 中解析已允许的 evidence blocks；
2. 计算问题与 evidence 的简单 token overlap；
3. 最多展示三段相关摘录；
4. 按用户语言标注“确定性 Demo / 非模型生成”；
5. 不展示无词法重叠的摘录。

### 3.2 `CHAT_LLM_MODE=openai_compatible`

使用 `DeepSeekLLMStreamAdapter`，通过 OpenAI-compatible streaming protocol 调用 endpoint。`DEEPSEEK_*` 名称是兼容保留；adapter 可连接兼容服务。

构造时要求 backend-only key 非空且不是 `EMPTY`。provider 异常转换为稳定的 LLM unavailable 错误；reasoning content 不对外发送。仓库不会自动选择 provider、下载模型、开放网络端口或索要 Key。

真实生成模式与 embedding backend 是两个独立轴。

## 4. 聊天图

```text
input_emergency_guard
  ├── emergency ─────────────────────────► output_policy
  └── continue
        ▼
request_route
  ├── greeting / obvious out-of-scope ──► output_policy
  └── continue
        ▼
normalize_coreference
        ▼
retrieve
        ▼
evidence_sufficiency
        ▼
generation_preparation
        ▼
output_policy
```

关键规则：

- 语言直接依据最新原始 `message`，而不是 rewritten query；
- `hello/你好` 等问候不进入 retrieval；
- 明显天气、股票、编程、旅游等请求不进入 retrieval/LLM；
- 紧急语言优先返回本地紧急指引；
- 没有可用引用时拒绝医学结论；
- deterministic embedding 模式额外要求 query/document 词法重叠；
- 真实 BGE 模式不使用该词法 overlap gate，以保留语义召回；
- generation prompt 只允许 `[C1]` 等已构造引用；
- hidden reasoning 被过滤，输出 segment 经过引用和医疗安全清理；
- 最终附加与用户语言一致的免责声明。

SSE envelope 包含 request ID、session ID、sequence、event、timestamp 和 data。事件类型包括 `meta`、`status`、`sources`、`token`、`safety`、`done`、`error`。

`meta` 暴露 `chat_mode` 和 `model_generation_enabled`，让前端不能把 Demo 冒充真实模型。

## 5. 默认 deterministic embedding

默认 API/worker 通过 Compose 使用：

```text
MOCK_MODE=true
INGESTION_EMBEDDING_BACKEND=deterministic
```

`DeterministicHashTfEmbedder` 的身份为：

```text
deterministic-md5-tf-v2
```

实现：

- 英文/数字 token 统一小写；
- 有 jieba 时中文使用分词；
- 无 jieba 时中文使用重叠 CJK 双字 token；
- dense vector 将 token 的 MD5 稳定映射到固定维度后归一化；
- sparse vector 使用 token-frequency；
- query 和 managed ingestion 使用同一算法版本。

它的用途是无需权重或 Key 即可完成可复现本地链路。它不是 BGE-M3，不具有可靠跨语言语义能力。版本进入 pipeline identity 和 Qdrant metadata，算法变化后不会错误复用旧 ingestion 结果。

## 6. 管理上传和文档生命周期

### 6.1 API 上传

管理 API 校验 PDF/TXT/Markdown 和大小后：

1. 计算内容 SHA-256；
2. 结合 parser/chunker/embedder/indexer 版本形成 pipeline identity；
3. 原始对象写入 MinIO；
4. PostgreSQL 事务创建 immutable document version 和 ingestion job；
5. 幂等冲突时复用相同任务，best-effort 删除重复对象。

### 6.2 PostgreSQL queue/lease

worker 可领取：

- `queued`；
- 到期 `retry_wait`；
- lease 过期的 `running`。

claim 使用 `FOR UPDATE SKIP LOCKED`，记录 owner、expiry、heartbeat 和 attempts。续租、stage 更新和 finalize 校验 owner；失去 lease 的旧 worker 不能继续执行宽范围清理。

### 6.3 Worker pipeline

```text
fetch -> parse -> chunk -> embed -> index -> finalize
```

默认 worker 显式构造 `DeterministicHashTfEmbedder`。`worker-bge` 显式构造 BGE adapter，并要求 `using_real_model=true`；缺模型或加载失败时启动失败，而不是静默把 hash vectors 标为 BGE。

### 6.4 Qdrant staging -> active

worker 先写带以下 payload 的 points：

- `index_visibility=staging`；
- `managed_document_id`；
- `content_sha256`；
- `metadata.embedding_backend`。

激活前核对当前 document/content 的 point count，再设置 `active`，删除相同内容的旧版本，最后提交 PostgreSQL succeeded。查询始终过滤 `index_visibility=active`。

## 7. 跨存储一致性

PostgreSQL、MinIO、Qdrant 无法组成单一原子事务。系统采用补偿式最终一致性：

- 上传数据库失败时 best-effort 删除新 MinIO object；
- job 和 object 通过稳定 identity 关联；
- lease 和 heartbeat 支持 crash reclaim；
- Qdrant staging 防止半成品被查询；
- point-count mismatch 阻止不完整激活；
- delete 以 managed document scope 限定；
- finalize 在 activation 之后提交。

仍需运维 orphan、staging 和数据库状态对账；不能把该设计描述为分布式强事务。

## 8. BGE profile 边界

`worker-bge` 的启动预检：

- `/models/bge-m3/config.json` 可读；
- 顶层存在 `.safetensors` 或 `pytorch_model*.bin`。

通过预检只证明最低文件形状。真实部署还必须验证 artifact hash、模型身份、embedding 维度、query/ingestion 一致性和受控 acceptance set。

默认 API 没有 BGE model bind mount；因此只启用 `worker-bge` 会造成 query/ingestion 配置风险，不是完整的一键 BGE 路径。默认 worker 与 worker-bge 不应同时消费队列。

## 9. 评估架构

管理 API 保留 evaluation job/list/detail/summary contract，但默认：

```text
EVALUATION_RUNNER_ENABLED=false
```

行为：

- UI 创建入口禁用；
- API 创建返回 HTTP 409；
- default worker 的 `evaluation_handler=None`，不 claim evaluation job；
- 不生成硬编码或 synthetic-but-unlabelled 指标；
- 页面可展示已有历史 aggregate metrics。

评估看板不是聊天流量统计。`public_eval` 和 legacy lexical endpoint 是另外的 contract，不能混成同一个 evaluator。

## 10. Readiness

`/health/ready` 检查 runtime 是否构造：

- legacy service；
- chat service；
- admin service（启用时）。

同时返回：

- `chat_mode`；
- `model_generation_enabled`；
- `admin_enabled`；
- `admin_ready`。

Readiness 不调用真实 provider，也不证明检索质量、医学质量、备份或生产控制。

## 11. 安全和隐私边界

- 默认端口只绑定 loopback；
- admin cookie 使用 HttpOnly、SameSite=Strict 和受限 Path；
- root `.env` 不应由 Compose 隐式读取；
- provider key 仅后端使用，不进入前端；
- Qdrant payload 删除 MinIO bucket/key 等私有 metadata；
- 日志和 SSE 不应暴露 hidden reasoning、key、cookie 或完整私有内容；
- Demo 不应摄取患者数据、真实病历、私有答案或无授权正文。

这些控制仍不等于生产安全。生产前需要 HTTPS、secret store、身份与权限、网络策略、审计、备份恢复、监控和容量设计。

## 12. 已验证和未验证边界

当前本地最终验收覆盖：

- Compose config；
- 最终 backend/frontend image；
- migration 和默认服务启动；
- default worker 管理上传自动成功；
- Qdrant point 的 `deterministic-md5-tf-v2` metadata；
- 中英文问候、域外、证据回答和 SSE；
- evaluation create 409；
- 相关后端 unit tests 和前端 typecheck/lint/tests。

没有证明：

- 真实 DeepSeek/OpenAI-compatible provider 的质量；
- 本地 Ollama/vLLM 网络部署；
- BGE-M3 端到端 query/ingestion；
- 真实 PDF 或私有语料质量；
- RAG/临床准确率；
- 灾难恢复和生产加固。
