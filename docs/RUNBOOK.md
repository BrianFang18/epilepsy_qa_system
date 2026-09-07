# 运维 Runbook

本文面向 Linux/WSL operator，描述仓库当前 loopback Docker Compose 运行方式、管理摄取、日志排障和能力边界。它不是生产部署模板。

## 1. 不可省略的配置约束

从仓库根目录执行：

```bash
cd "$HOME/work_project/epilepsy_qa_system"
export COMPOSE_DISABLE_ENV_FILE=1
```

每条 Compose 命令必须显式指定环境文件：

```text
--env-file config/compose.env.example
```

不要让 Compose 隐式读取仓库根 `.env`。示例文件中的 `CHANGE_ME_*` 是公开的本地占位值，只能用于隔离的 loopback Demo，不能用于共享或生产环境。

真实 provider 配置应复制到 Git 忽略的 `.env.local`，显式 `--env-file .env.local` 使用，不得提交密钥。

## 2. 默认拓扑和端口

默认 Compose 服务：

- `postgres`、`minio`、`qdrant`：长期存储；
- `migrate`：一次性 Alembic migration；
- `api`：FastAPI；
- `worker`：默认自动启动的 deterministic ingestion worker；
- `frontend`：Nginx + React SPA；
- `worker-bge`：仅 `bge-ingestion` profile，可选且默认不启动。

| Service | 宿主映射 | 正常状态 |
| --- | --- | --- |
| `frontend` | `127.0.0.1:8080` | healthy |
| `api` | `127.0.0.1:8010` | healthy |
| `postgres` | `127.0.0.1:5432` | healthy |
| `minio` | API `127.0.0.1:9000`；Console `127.0.0.1:9001` | healthy |
| `qdrant` | `127.0.0.1:6333` | healthy |
| `worker` | 无宿主端口 | Up |
| `migrate` | 无宿主端口 | Exited (0) |

所有默认映射只监听 loopback。Loopback 不是 TLS、secret store、网络策略或生产鉴权的替代品。

## 3. 构建、启动和停止

配置预检：

```bash
docker compose --env-file config/compose.env.example config --quiet
docker compose --env-file config/compose.env.example config --services
```

首次构建和启动：

```bash
docker compose --env-file config/compose.env.example up --build -d
docker compose --env-file config/compose.env.example ps --all
```

受限网络可使用构建参数：

```bash
docker compose --env-file config/compose.env.example build \
  --build-arg DEBIAN_MIRROR=https://mirrors.tuna.tsinghua.edu.cn \
  --build-arg PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple

docker compose --env-file config/compose.env.example up -d
```

后端依赖层较大；Dockerfile 只在依赖安装前复制 package metadata 和 `app/__init__.py`，普通业务源码修改应命中昂贵依赖层缓存。

日常启动：

```bash
docker compose --env-file config/compose.env.example up -d
```

停止并保留 named volumes：

```bash
docker compose --env-file config/compose.env.example down
```

`down -v` 会删除 PostgreSQL、MinIO 和 Qdrant 的全部 Compose volume，必须单独确认数据可丢弃。

## 4. 健康和日志

```bash
curl -fsS http://127.0.0.1:8080/healthz
curl -fsS http://127.0.0.1:8010/health
curl -fsS http://127.0.0.1:8010/health/ready
```

默认 readiness 应返回：

- `status=ready`；
- `legacy_ready=true`；
- `chat_ready=true`；
- `chat_mode=demo`；
- `model_generation_enabled=false`；
- `admin_enabled=true`；
- `admin_ready=true`。

`model_generation_enabled` 表示选择的生成模式，不是 provider 质量或可用性探针。

查看状态与日志：

```bash
docker compose --env-file config/compose.env.example ps --all
docker compose --env-file config/compose.env.example logs --since=30m migrate
docker compose --env-file config/compose.env.example logs --since=30m api worker frontend
docker compose --env-file config/compose.env.example logs --since=30m postgres minio qdrant
```

日志不得包含 session cookie、对象正文、数据库 URL、provider key、管理员密码或完整私有 prompt/context。

## 5. Migration

默认 `up` 等待 PostgreSQL healthy，然后执行：

```text
/opt/container/with-database-url alembic -c alembic.ini upgrade head
```

`migrate Exited (0)` 是成功。查看 revision：

```bash
docker compose --env-file config/compose.env.example run --rm migrate \
  /opt/container/with-database-url alembic -c alembic.ini current
```

若 migration 非 0，停止后续写操作，检查脱敏日志；不要手工修改 `alembic_version`。

## 6. 默认聊天运行模式

API 使用标准入口：

```text
/opt/container/with-database-url python -m uvicorn app.main:app --host 0.0.0.0 --port 8010
```

`app.main` 根据 `CHAT_LLM_MODE` 选择 streaming adapter。

默认：

```text
CHAT_LLM_MODE=demo
MOCK_MODE=true
```

`demo` adapter 不调用 LLM。它只显示与最新问题有词法重叠的已检索 evidence blocks，并在正文标注 Deterministic Demo / not LLM-generated。

聊天图先处理：

1. 紧急语言；
2. 问候；
3. 明显域外问题；
4. normalization/coreference；
5. retrieval 和 evidence gate；
6. generation preparation；
7. output policy。

问候和明显域外问题跳过 retrieval/LLM。输出语言由最新原始用户消息决定。deterministic backend 额外要求词法重叠，避免 RRF 高排名但无关的内容进入回答；BGE 模式不应用该词法 gate。

## 7. 真实 OpenAI-compatible 生成

支持：

```text
CHAT_LLM_MODE=openai_compatible
DEEPSEEK_BASE_URL=<endpoint ending in /v1 when required by provider>
DEEPSEEK_API_KEY=<backend-only, non-empty, not EMPTY>
DEEPSEEK_MODEL=<served model ID>
```

变量名保留 DeepSeek 前缀，但 adapter 使用 OpenAI-compatible protocol。缺非占位 key 时应用启动 fail closed。

推荐从示例复制本地私有配置：

```bash
cp config/compose.env.example .env.local
```

修改后：

```bash
export COMPOSE_DISABLE_ENV_FILE=1
docker compose --env-file .env.local config --quiet
docker compose --env-file .env.local up -d --force-recreate api frontend
```

操作前必须由用户选择本地 Ollama/vLLM 或外部 API。不要自动下载模型、索要 Key、产生费用，或把 Windows Ollama 从 `127.0.0.1` 未经评审地暴露到所有网卡。

真实 LLM 只改变答案综合方式；它不会自动把 query/ingestion embedding 切为 BGE。

## 8. 管理端摄取

管理上传接受 PDF/TXT/Markdown，默认最大 25 MB。成功请求：

1. 校验文件；
2. 计算内容 SHA-256 与 pipeline identity；
3. 写 MinIO object；
4. PostgreSQL 事务创建 document 和 ingestion job；
5. default worker 领取 queued/retry/expired-lease job；
6. fetch/parse/chunk/embed/index/finalize；
7. Qdrant staging points 核数后切换 active；
8. PostgreSQL 提交 succeeded。

默认 worker：

```text
MOCK_MODE=true
INGESTION_EMBEDDING_BACKEND=deterministic
embedding backend identity=deterministic-md5-tf-v2
```

它不需要模型权重。pipeline identity 包含 parser、chunker、embedding 和 index 版本；embedding 算法升级会创建新不可变版本，避免复用旧向量。

### 8.1 queued 排障

短暂 queued 正常。长期 `attempts=0`：

```bash
docker compose --env-file config/compose.env.example ps --all worker
docker compose --env-file config/compose.env.example logs --tail=200 worker
```

若 worker 缺失：

```bash
docker compose --env-file config/compose.env.example up -d worker
```

若 attempts 已增加，说明 worker 已领取；按页面 error 和 worker 日志定位 parse/storage/index 失败。不要通过重复上传制造重复任务。

### 8.2 一致性边界

MinIO、PostgreSQL、Qdrant 不是一个分布式事务。实现使用幂等键、lease owner 校验、staging/active、point count、精确 scoped delete 和 best-effort compensation。仍需 orphan 与状态对账，不能表述为强事务。

## 9. BGE ingestion profile

`worker-bge` 位于 `bge-ingestion` profile，并在启动时要求：

- `/models/bge-m3/config.json` 可读；
- 顶层存在 `.safetensors` 或 `pytorch_model*.bin`。

缺少模型会 exit 64，不会把 deterministic fallback 标为 BGE。启动前必须停止默认 worker：

```bash
docker compose --env-file .env.local stop worker
docker compose --env-file .env.local --profile bge-ingestion up -d worker-bge
```

但是，该命令只说明 worker 侧 artifact 通过最低预检。API query embedding 也必须使用维度和模型身份一致的真实 BGE 配置；当前默认 API 没有模型 bind mount，因此 profile 本身不是完整的一键 BGE 方案。启用前需独立设计并验收，不得与默认 worker 并行消费队列。

## 10. 评估看板

默认：

```text
EVALUATION_RUNNER_ENABLED=false
```

前端禁用创建入口，API `POST /api/v1/admin/evaluations` 返回 409：

```text
Evaluation runner is not configured; no metrics were generated
```

默认 worker 不领取 evaluation job。这样避免永久 queued 或伪造指标。列表和 summary 只用于已有历史聚合数据。

该看板不是聊天统计。`public_eval --dry-run` 和 legacy `/v1/eval/ragas` 也是独立 contract；不能把它们的结构/词法结果称为真实模型质量、RAGAS、faithfulness 或临床效果。

## 11. 管理会话

示例 Compose 启用 admin，bootstrap 账号是公开占位值。登录 token 只通过 `HttpOnly` cookie 返回，PostgreSQL 保存 digest。

- `ADMIN_COOKIE_SECURE=false` 只适合 loopback HTTP；
- bootstrap 用户只在不存在时创建；修改 env 不会轮换现有密码；
- 当前没有管理员改密 API；
- 共享环境必须重新设计 secret、HTTPS、cookie、CORS 和访问控制。

## 12. 常见故障表

| 现象 | 原因/处理 |
| --- | --- |
| `migrate` 非 0 | 检查 PostgreSQL health 和 migration 日志 |
| API degraded | 检查 app startup、Qdrant schema、admin runtime 和 provider 配置 |
| API 因 real mode 启动失败 | 检查 endpoint、model 和非占位 backend key |
| frontend 等待 | 它依赖 API healthy；先查 readiness |
| 文档 queued / 0 attempts | worker 未运行或无法连接 PostgreSQL |
| 文档 failed | 查 worker stage/error、MinIO/Qdrant health |
| succeeded 后证据不足 | 问题与文档语言/关键词不匹配；默认不是语义模型 |
| 管理员登录失败 | 旧 volume 中已有不同 bootstrap 用户/密码 |
| 评估按钮禁用 | 预期行为；没有真实 evaluator |
| worker-bge exit 64 | 模型 config/权重缺失或不可读 |

## 13. 备份、恢复和生产边界

仓库未提供经过验收的跨 PostgreSQL、MinIO、Qdrant 一致备份恢复方案。生产前至少需要：

1. 定义跨存储一致性点和 backup ID；
2. 暂停写入或实现一致 snapshot 协议；
3. 在隔离环境恢复到新资源；
4. 对账 document/object/active points；
5. 记录并演练 RPO、RTO 和回滚；
6. 完成 TLS、secret store、最小权限、监控、容量和事件响应。

本地 healthcheck、Demo 回答或 synthetic smoke 不能外推为生产或临床就绪。
