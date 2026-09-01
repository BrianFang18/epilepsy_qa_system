# 运维 Runbook

本文面向 Linux/WSL operator，提供仓库当前 **loopback 本地 Compose demo** 的可执行步骤。默认栈已完成 migration、五个长期服务健康和基础设施 integration 验收，但备份恢复、真实模型、worker 容器与生产加固没有通过本次验收。

## 0. 不可省略的命令约束

从仓库根目录执行命令。每一条 Compose 命令都必须显式使用：

```text
--env-file config/compose.env.example
```

例如：

```bash
docker compose --env-file config/compose.env.example config --quiet
```

不要省略该参数，也不要让 Compose 隐式读取仓库根 `.env`。`config/compose.env.example` 中的 `CHANGE_ME_*` 是隔离本地 demo 的占位凭据，不得用于共享环境、预发布或生产，也不得替换成真实生产 secret 后提交。

## 1. 已确认的服务与端口

默认服务：

- `postgres`、`minio`、`qdrant`：长期基础设施；
- `migrate`：一次性执行 `alembic upgrade head`；
- `api`、`frontend`：长期应用服务；
- `worker`：只属于 `ingestion` profile，默认不启动。

| Service | 宿主映射 | 默认状态 |
|---|---|---|
| `frontend` | `127.0.0.1:8080` | 长期 |
| `api` | `127.0.0.1:8010` | 长期 |
| `postgres` | `127.0.0.1:5432` | 长期 |
| `minio` | API `127.0.0.1:9000`；Console `127.0.0.1:9001` | 长期 |
| `qdrant` | `127.0.0.1:6333` | 长期 |
| `migrate` | 无 | 成功后退出 |
| `worker` | 无 | profile opt-in |

这些映射只监听 loopback。不要用额外端口发布或反向代理把它们暴露到受信边界之外，除非完成独立安全评审。

## 2. 默认栈启动

### 2.1 配置预检

```bash
docker compose --env-file config/compose.env.example config --quiet
docker compose --env-file config/compose.env.example config --services
```

默认 services 输出应包含 `postgres`、`minio`、`qdrant`、`migrate`、`api`、`frontend`，不包含 `worker`。顺序不重要。

示例文件可直接用于隔离本地 demo，但其中的占位管理员、PostgreSQL 与 MinIO 凭据必须被视为公开值。不要在该配置下放入敏感数据。

### 2.2 构建并启动

```bash
docker compose --env-file config/compose.env.example up --build -d
docker compose --env-file config/compose.env.example ps --all
```

依赖顺序为：三种基础设施 healthcheck 通过；`migrate` 成功；`api` healthy；最后 `frontend` healthy。正常稳定状态为：

- `migrate` 显示成功退出（exit code 0）；
- `postgres`、`minio`、`qdrant`、`api`、`frontend` 五个长期服务显示 `healthy`；
- `worker` 不出现，因为 profile 没有启用。

仓库的已执行验收已观察到上述状态。每次新启动仍应重新检查，而不能把历史记录当成当前在线状态。

## 3. 健康与日志

### 3.1 HTTP 检查

```bash
curl -fsS http://127.0.0.1:8080/healthz
curl -fsS http://127.0.0.1:8010/health
curl -fsS http://127.0.0.1:8010/health/ready
```

- frontend `/healthz` 只检查 Nginx 自身响应；
- API `/health/ready` 也是 container healthcheck 的依据；
- healthcheck 不证明 DeepSeek/BGE、医学质量、备份或生产控制有效。

浏览器入口：<http://127.0.0.1:8080>
MinIO Console：<http://127.0.0.1:9001>

Console 使用 `config/compose.env.example` 中的本地 MinIO 占位凭据。不要截图、复用或传播真实凭据。

### 3.2 查看状态与日志

```bash
docker compose --env-file config/compose.env.example ps --all
docker compose --env-file config/compose.env.example logs --since=30m migrate
docker compose --env-file config/compose.env.example logs --since=30m postgres minio qdrant api frontend
```

日志中不得记录 session cookie、对象正文、数据库 URL、provider key 或管理员密码。

## 4. Migration 操作

默认 `up` 会等待 PostgreSQL healthy，然后由专用 `migrate` service 执行：

```text
/opt/container/with-database-url alembic -c alembic.ini upgrade head
```

查看当前 revision：

```bash
docker compose --env-file config/compose.env.example run --rm migrate \
  /opt/container/with-database-url alembic -c alembic.ini current
```

按 service 默认 command 重新执行幂等 upgrade：

```bash
docker compose --env-file config/compose.env.example run --rm migrate
```

当前 Compose 验收中 migration 已成功完成，integration 也检查 current heads 与 expected heads 一致。若 migration 失败，停止后续 API/worker 操作并保留 revision 与脱敏错误；不要手工修改 `alembic_version`。

## 5. 默认 API 与 provider 切换

默认 `api` command 是 Dockerfile 专用的 deterministic mock stream bridge：

```text
/opt/container/with-database-url /opt/container/serve-existing-mock
```

它要求 `MOCK_MODE=true`，无需 provider key，可用于演示 SSE 与 UI contract。mock 输出不是 DeepSeek、不是任何真实 LLM 结果，也不能用于模型质量结论。

**不要只把 `MOCK_MODE=false` 后重启。** 默认 command 会拒绝这种组合，并不会自动切换 provider。接入真实 provider 需要受审查的 command/service override，至少覆盖：

1. 真实 streaming app entrypoint；
2. endpoint、key 与 model ID 的受控注入；
3. provider 不可用时的 fail-closed 语义；
4. 日志与 SSE 脱敏；
5. 独立集成、安全和效果验收。

本 Runbook 不提供未经验证的真实 provider override 命令。完成评审前保持默认 mock 配置。

## 6. 可选 ingestion worker

### 6.1 模型目录要求

编辑本地 `config/compose.env.example` 的非 secret 路径配置，使 `EMBED_MODEL_PATH` 指向宿主机上已存在、可读取的**绝对 BGE-M3 目录**。相对路径不受支持。Compose 将它只读挂载到 `/models/bge-m3`，不会复制或下载模型。

worker 启动前会检查：

- `/models/bge-m3/config.json` 可读；
- 顶层至少有一个 `.safetensors` 或 `pytorch_model*.bin` 权重文件。

### 6.2 启动与停止

```bash
docker compose --env-file config/compose.env.example --profile ingestion config --services
docker compose --env-file config/compose.env.example --profile ingestion up --build -d worker
docker compose --env-file config/compose.env.example --profile ingestion ps --all worker
docker compose --env-file config/compose.env.example --profile ingestion logs --since=30m worker
```

停止 worker：

```bash
docker compose --env-file config/compose.env.example --profile ingestion stop worker
```

文件检查通过只证明挂载形状，不证明模型正确加载或真实推理成功。任何 fallback 结果都不是 BGE。默认 Compose 验收和 6/6 integration 均未启动 worker 容器，因此启用后必须做独立验收。

## 7. Opt-in integration 结果与边界

入口脚本为 `scripts/compose_smoke.py`，测试文件为 `tests/integration/test_compose_smoke.py`。它只有在 operator 显式设置 `RUN_COMPOSE_INTEGRATION=1` 时运行，并输出 aggregate-only JSON。复跑时应显式注入测试环境，不依赖仓库根 `.env`，且只能使用 synthetic 数据。

已记录结果：

```text
collected=6 passed=6 failed=0 skipped=0 errors=0
```

实际覆盖：

- 真实 PostgreSQL、MinIO、Qdrant 可达与 Alembic head；
- PostgreSQL transaction/idempotency/claim/heartbeat/lease reclaim；
- MinIO put/download/remove；
- Qdrant named dense+sparse、staging→active 与 scoped delete；
- pytest 进程内构造的 `WorkerRunner`，配合注入 deterministic parser/embedder，验证成功与 retry contracts。

没有覆盖：

- `worker` Compose container；
- BGE-M3 或 reranker 真实推理；
- DeepSeek/其他 provider；
- 真实 PDF、私有数据或临床内容；
- 备份恢复或生产加固。

不要把“6/6 passed”改写成“DeepSeek/BGE/worker 已通过”。

## 8. 管理面注意事项

示例 Compose 为本地 demo 设置 `ENABLE_ADMIN_API=true`，bootstrap username/password 也是公开占位值。它适合展示登录和管理 contract，不适合敏感数据或共享环境。

- 示例中 `ADMIN_COOKIE_SECURE=false` 只因为入口是 loopback HTTP；受信部署必须使用 HTTPS 并重新评审 cookie/CORS。
- bootstrap 用户只在不存在时创建；修改环境变量不会轮换已有密码。
- 当前没有受支持的管理员改密 API。
- 默认 worker 关闭，因此上传后 ingestion job 不会被容器消费；不要把 queued job 表述为摄取成功。
- evaluation handler 默认以 `EVALUATION_NOT_CONFIGURED` fail closed。

## 9. 常见故障

| 现象 | 原因/处置 |
|---|---|
| `migrate` 非 0 退出 | 检查 PostgreSQL health 与脱敏 migration 日志；修复后重新运行 `migrate`，不要跳 revision |
| `api` 未启动且 `MOCK_MODE=false` | 默认 bridge 故意要求 `true`；本地 demo 恢复 `true`。真实 provider 必须走受审查 override |
| `frontend` 等待 | 它依赖 `api` healthy；先检查 API readiness 与日志 |
| `/health/ready` 失败 | 检查 runtime 初始化和依赖日志；不要据此推断模型效果 |
| MinIO Console 无法访问 | 核对 `minio` health 与 `127.0.0.1:9001`，不要改成公网绑定 |
| 默认栈没有 worker | 这是设计行为；只有显式启用 `ingestion` profile 才创建 worker |
| worker bind mount 失败 | `EMBED_MODEL_PATH` 不是存在的绝对目录，或宿主权限不足 |
| worker 以 64 退出 | `/models/bge-m3` 缺少可读 `config.json` 或顶层权重 |
| worker 运行但不能证明 BGE | 文件检查与 fallback 不是推理证据；增加受控 instrumentation 与真实 artifact test |
| 文档 job 一直 queued | 默认 worker 未启动，或 worker 没有成功 claim；检查 profile、日志与 lease |
| evaluation 失败 | `EVALUATION_NOT_CONFIGURED` 是默认 fail-closed 行为 |

## 10. 停止与本地清理

停止但保留容器和卷：

```bash
docker compose --env-file config/compose.env.example stop
```

删除容器与网络、保留 named volumes：

```bash
docker compose --env-file config/compose.env.example down
```

不要在含有需要保留的数据时使用 `down -v`；它会删除 PostgreSQL、MinIO、Qdrant named volumes。任何卷删除都应单独确认。

## 11. 备份、恢复与生产部署状态

仓库当前没有经过本次验收证明可用的备份/恢复流程。不要把 named volumes、手工 copy、数据库 dump 或 Qdrant snapshot 单独称为完整恢复方案。生产前至少需要：

1. 定义跨 PostgreSQL、MinIO、Qdrant 与配置元数据的一致性边界；
2. 暂停写入并记录同一 backup ID；
3. 在隔离环境恢复到新资源并做跨存储对账；
4. 记录 RPO/RTO、软件版本、artifact hash 和失败回滚；
5. 定期重复演练。

同样，本地 healthcheck、loopback 端口与 6/6 integration 不证明 TLS、secret store、最小权限、网络策略、监控、容量、升级或事件响应已经生产加固。

## 12. 镜像版本

Compose/Dockerfile 使用明确版本 tag：PostgreSQL `16.6-bookworm`、MinIO `RELEASE.2024-11-07T00-52-20Z`、Qdrant `v1.12.6`、Python `3.11.11-slim-bookworm`、Node `20.11.0-alpine3.19`、Nginx `1.27.3-alpine3.20`。这些 tag 没有以 digest 固定。受信部署必须自行记录并审核实际 digest，不能仅凭 tag 宣称构建不可变。
