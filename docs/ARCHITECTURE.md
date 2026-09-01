# 架构说明

本文描述 `docker-compose.yml`、容器镜像和 opt-in integration tests 中可核对的运行边界。默认 Compose 是 loopback 本地演示，不是生产部署模板，也不代表真实 DeepSeek/BGE 或灾难恢复已经验收。

## 1. Compose 拓扑

```text
Host browser
  │ http://127.0.0.1:8080
  ▼
frontend (Nginx :8080)
  ├── /api/* ───────────────► api:8010
  ├── /health* ─────────────► api:8010
  └── static SPA
                               │
                               ├── PostgreSQL postgres:5432
                               ├── MinIO minio:9000
                               └── Qdrant qdrant:6333

postgres healthy ──► migrate (alembic upgrade head, one-shot)
postgres/minio/qdrant healthy + migrate succeeded ──► api healthy ──► frontend

worker [profile: ingestion, default off]
  ├── PostgreSQL: claim / lease / heartbeat / finalize
  ├── MinIO: download source object
  ├── Qdrant: staging points → active points
  └── /models/bge-m3: read-only BGE-M3 bind mount
```

默认服务为 `postgres`、`minio`、`qdrant`、`migrate`、`api`、`frontend`。其中 `migrate` 是成功后退出的一次性服务，其余五个是长期服务。`worker` 只属于 `ingestion` profile，不会随默认 `up` 启动。

所有 Compose 命令必须显式指定环境文件，例如：

```bash
docker compose --env-file config/compose.env.example config --quiet
docker compose --env-file config/compose.env.example up --build -d
```

`--env-file config/compose.env.example` 不得省略；Compose 不应隐式读取仓库根 `.env`。示例文件中的占位凭据只适用于隔离本地 demo。

## 2. 网络与服务边界

| Service | 容器职责 | 宿主映射 |
|---|---|---|
| `frontend` | Nginx 提供 SPA，并代理 `/api` 与 `/health` | `127.0.0.1:8080` |
| `api` | FastAPI 与默认 mock stream bridge | `127.0.0.1:8010` |
| `postgres` | 管理用户、session digest、文档、job 与 lease | `127.0.0.1:5432` |
| `minio` | 原始对象；Console 由 `--console-address :9001` 启用 | API `127.0.0.1:9000`；Console `127.0.0.1:9001` |
| `qdrant` | dense+sparse chunks 与 active visibility | `127.0.0.1:6333` |
| `migrate` | Alembic schema migration | 无 |
| `worker` | 可选摄取进程 | 无 |

端口全部绑定 `127.0.0.1`，因此默认不会监听宿主所有网卡。容器通过 Compose `app` bridge network 使用 service DNS 互联。Loopback 绑定不是 TLS、认证、网络策略或生产隔离的替代品。

前端 Nginx 在 `/api` 上禁用 proxy buffering 并使用较长 read timeout，以支持 SSE；`/healthz` 是前端自身健康端点，`/health` 则代理给 API。

## 3. 启动依赖与健康

- `postgres` 使用 `pg_isready`。
- `minio` 使用 `mc ready local`。
- `qdrant` 检查容器内 `127.0.0.1:6333` TCP 可连接。
- `migrate` 等待 PostgreSQL healthy，再执行 `alembic upgrade head`。
- `api` 等待三种存储 healthy 且 migration 成功；其 healthcheck 要求 `/health/ready` JSON 的 `status` 为 `ready`。
- `frontend` 等待 API healthy，并检查自身 `/healthz`。
- `worker` 在启用 profile 后等待三种存储 healthy 且 migration 成功。

已执行的本地验收中，`migrate` 成功完成，`postgres`、`minio`、`qdrant`、`api`、`frontend` 五个长期服务均达到 `healthy`。这是一次验收记录，不是持续在线或生产可用性保证。

## 4. 默认 API：deterministic mock stream bridge

Compose 的 `api.command` 是：

```text
/opt/container/with-database-url /opt/container/serve-existing-mock
```

`with-database-url` 从 PostgreSQL bootstrap 变量构造转义后的 SQLAlchemy URL。`serve-existing-mock` 是 Dockerfile 专用入口：

1. 加载现有 `LLMClient` deterministic mock；
2. 用 `ExistingMockStreamPort` 将它适配到异步 streaming port；
3. 把该 port 注入 `create_app`；
4. 仅在 `MOCK_MODE=true` 时启动 Uvicorn。

因此默认 API 无需 provider endpoint 或 provider key，即可演示 `/api/v1/chat/stream` 的 SSE contract。该路径的输出是 mock，不是 DeepSeek、OpenAI-compatible provider 或任何真实模型推理结果。

只修改 `MOCK_MODE=false` 不会选择真实 provider；默认入口会主动拒绝启动。真实 provider 需要受审查的 Compose command/service override，改用真实 streaming adapter，并独立评审 endpoint/key 注入、错误处理、日志脱敏和模型验收。仓库没有提供经过验收的真实 provider override。

## 5. API、管理会话与 readiness

- `POST /api/v1/chat/stream` 返回 `text/event-stream`，默认 Compose 由上述 mock bridge 提供 token stream。
- `/api/v1/admin/*` 是管理接口。源码配置可以关闭它，但 `config/compose.env.example` 为本地 demo 设置 `ENABLE_ADMIN_API=true`。
- 管理登录成功后，原 session token 只通过 `HttpOnly` cookie 返回；PostgreSQL 保存 SHA-256 digest。
- cookie Path 为 `/api/v1/admin`，`SameSite=Strict`，默认 TTL 1800 秒。示例 Compose 的 `ADMIN_COOKIE_SECURE=false` 只适合 loopback HTTP demo。
- `/health/ready` 验证应用 runtime 是否准备好，并被 API container healthcheck 使用；它不证明 DeepSeek、BGE、医学质量、备份或生产外部控制有效。

Bootstrap 用户只在不存在时创建。改变 `ADMIN_BOOTSTRAP_PASSWORD` 不会更新已有用户，当前也没有受支持的管理员改密 API。

## 6. 文档摄取与一致性

### 6.1 上传与 MinIO

管理 API 校验 PDF/TXT/Markdown 后：

1. 计算内容 SHA-256 与幂等键；
2. 将原始对象写入 MinIO；
3. 在一个 PostgreSQL 事务中创建 document 与 ingestion job；
4. 数据库失败或并发幂等竞争时，best-effort 删除本次重复对象。

MinIO 保存原始对象，不承担 staging/active 状态。对象存储与数据库不是单一事务，因此仍需要 orphan 对账。

### 6.2 PostgreSQL lease

worker 领取 `queued`、到期的 `retry_wait` 或 lease 过期的 `running` job，使用 `FOR UPDATE SKIP LOCKED` 并记录 owner、expiry、heartbeat 与 attempts。续租、stage 更新和 finalize 都校验当前 owner；旧 owner 失去 lease 后不能执行宽范围 Qdrant 删除。

### 6.3 Qdrant staging → active

摄取主路径为：下载对象、解析 parent/child chunks、写入带 `index_visibility=staging` 的 points、核对数量、再次检查取消/lease、切换为 `active`、清理同内容旧版本，最后提交 PostgreSQL job/document 状态。查询强制过滤 `index_visibility=active`。

Qdrant activation 与 PostgreSQL completion 不是原子事务。这是补偿式最终一致性设计，不是分布式事务，也不是已验证的灾难恢复方案。

## 7. 可选 worker 与 BGE 边界

`worker` 仅在 `ingestion` profile 中定义。宿主 `EMBED_MODEL_PATH` 必须是绝对路径，Compose 将其只读挂载为 `/models/bge-m3`，并在容器启动时检查：

- `/models/bge-m3/config.json` 可读；
- 顶层存在 `.safetensors` 或 `pytorch_model*.bin` 权重。

这些启动检查只能证明文件形状符合最低要求，不证明 artifact 正确、维度匹配或真实 BGE-M3 推理成功。任何 hash、TF、lexical 或其他 fallback 结果都不是 BGE，必须清楚标注。默认栈不会启动 worker。

## 8. Integration suite 的实际覆盖

`scripts/compose_smoke.py` 以 opt-in 方式运行 `tests/integration/` 并只输出 aggregate counts。已记录结果为 **6 collected / 6 passed / 0 failed / 0 skipped / 0 errors**。

六项 contract 覆盖：

1. 真实 PostgreSQL/MinIO/Qdrant 可达，Alembic revision 在 head；
2. PostgreSQL document/job 事务、幂等与 lease reclaim；
3. MinIO put/download/remove round trip；
4. Qdrant named dense+sparse schema、staging 不可见、activation 与 scoped delete；
5. 使用注入 `DeterministicTxtParser` 与 `DeterministicEmbedder` 的进程内 `WorkerRunner` 成功路径；
6. 使用注入失败 parser 的 retry 持久化与“不误报成功”路径。

这组测试使用真实三种存储，但 **WorkerRunner 是由 pytest 进程构造，parser/embedder 是测试替身**。它不启动 `worker` Compose service，不加载 BGE-M3，不调用 DeepSeek/其他 provider，也不测真实 PDF 解析、真实 embedding/rerank 或 LLM。

## 9. 镜像与供应链边界

当前明确版本 tag 包括：

- backend build/runtime：`python:3.11.11-slim-bookworm`；
- PostgreSQL：`postgres:16.6-bookworm`；
- MinIO：`minio/minio:RELEASE.2024-11-07T00-52-20Z`；
- Qdrant：`qdrant/qdrant:v1.12.6`；
- frontend build：`node:20.11.0-alpine3.19`；
- frontend runtime：`nginx:1.27.3-alpine3.20`。

backend/frontend 本地镜像也使用描述性版本 tag。所有这些均未在仓库中以 image digest 固定，因此不能把构建声明为不可变或可重现供应链证明。

## 10. 验证边界

本次 Compose 与 integration 验收没有证明：

- 真实 DeepSeek 或其他 provider 可用或有效；
- 真实 BGE-M3 embedding/rerank 已执行；
- `worker` 容器通过端到端验收；
- 备份恢复流程可用；
- TLS、secret store、网络策略、权限、监控、容量或生产加固已完成；
- 系统具有临床有效性或医疗安全性。

这些项目需要各自独立、可审计的验证，不能从默认 mock、healthcheck 或 integration 6/6 外推。
