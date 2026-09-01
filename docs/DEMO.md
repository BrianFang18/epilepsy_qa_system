# 演示指南

本文给出仓库当前可复现的本地 Compose 演示。默认路径无需 DeepSeek 或其他 provider key，因为 API 使用 Dockerfile 专用 deterministic mock stream bridge。**mock 只演示 UI/SSE contract，不代表 DeepSeek、BGE、RAG 或医学效果。**

任何流程都不是医疗验证。不要输入真实患者身份信息、病历、处方、生产 secret 或未获授权文档。

## 0. 演示范围

执行 `docker compose --env-file config/compose.env.example up --build -d` 时，默认启动：

- `postgres`、`minio`、`qdrant`；
- 一次性 `migrate`；
- `api`、`frontend`。

`worker` 仅属于 `ingestion` profile，默认不启动。因此默认演示可以展示前端、mock SSE、健康状态和本地管理接口，但不能把 queued ingestion job 说成已由 worker 处理。

所有宿主映射均为 loopback：frontend `127.0.0.1:8080`、API `127.0.0.1:8010`、PostgreSQL `127.0.0.1:5432`、MinIO API/Console `127.0.0.1:9000/9001`、Qdrant `127.0.0.1:6333`。

## 1. 安全准备

从仓库根目录执行。所有 Compose 命令必须显式带：

```text
--env-file config/compose.env.example
```

不得省略该参数，也不要让 Compose 隐式读取仓库根 `.env`。`config/compose.env.example` 的 `CHANGE_ME_*` 是公开的本地 demo 占位凭据，只能用于隔离环境；不要在该文件中保存真实生产 secret，也不要用该演示处理敏感数据。

## 2. 启动默认演示

```bash
docker compose --env-file config/compose.env.example config --quiet
docker compose --env-file config/compose.env.example up --build -d
docker compose --env-file config/compose.env.example ps --all
```

等待稳定后，应看到：

- `migrate` 成功退出（exit code 0）；
- `postgres`、`minio`、`qdrant`、`api`、`frontend` 五个长期服务为 `healthy`；
- 没有 `worker`，因为没有启用 `ingestion` profile。

上述 migration 与五服务 healthy 状态已经在 Compose 验收中实测通过；新演示仍须当场检查。

健康检查：

```bash
curl -fsS http://127.0.0.1:8080/healthz
curl -fsS http://127.0.0.1:8010/health
curl -fsS http://127.0.0.1:8010/health/ready
```

浏览器打开 <http://127.0.0.1:8080>。MinIO Console 已明确映射在 <http://127.0.0.1:9001>，只使用示例文件中的本地占位凭据。

## 3. 展示默认聊天

默认 `api` service 执行：

```text
/opt/container/with-database-url /opt/container/serve-existing-mock
```

该 bridge 把已有 deterministic mock 客户端注入 streaming chat port，因此无需 provider endpoint 或 key。可以演示：

1. 前端通过相对 `/api` 访问同一 Nginx origin；
2. `/api/v1/chat/stream` 返回 SSE；
3. Nginx 对 `/api` 禁用 buffering；
4. UI 能处理流式事件与完成状态。

演示时必须明确说：

- 当前回答来自 deterministic mock；
- 它不是 DeepSeek 或其他真实 LLM；
- 流式 contract 正常不等于答案正确；
- healthcheck 不等于模型、检索或医学验证。

不要用 mock 输出计算或宣传模型准确率、安全率、faithfulness 或临床指标。

## 4. 管理面演示

示例 Compose 设置 `ENABLE_ADMIN_API=true`，可打开 `/admin/login`。bootstrap 管理员与 MinIO/PostgreSQL 凭据都来自公开占位配置，因此只适合本地 contract 演示。

可以展示：

- 登录与 `HttpOnly` session cookie；
- cookie Path `/api/v1/admin` 与 `SameSite=Strict`；
- 文档管理 UI；
- 未配置 evaluation 时明确返回 `EVALUATION_NOT_CONFIGURED`。

必须说明：

- 示例 `ADMIN_COOKIE_SECURE=false` 只适用于 loopback HTTP；
- 修改 bootstrap password 不会更新已存在的管理员；
- 默认 worker 未启动，上传任务会停留在队列，不能演示为完成摄取；
- 不要上传真实患者资料或私有文档。

## 5. 可选 worker 演示

只有准备好本地 BGE-M3 artifact 并愿意单独验收时才启用。将 `config/compose.env.example` 中的 `EMBED_MODEL_PATH` 设为宿主机上已存在的**绝对目录**；Compose 会只读挂载到 `/models/bge-m3`。相对路径无效。

```bash
docker compose --env-file config/compose.env.example --profile ingestion up --build -d worker
docker compose --env-file config/compose.env.example --profile ingestion ps --all worker
docker compose --env-file config/compose.env.example --profile ingestion logs --since=30m worker
```

worker 启动会检查 `/models/bge-m3/config.json` 和顶层权重，但文件存在不证明真实 BGE-M3 推理成功。任何 deterministic/hash/TF/lexical fallback 都不是 BGE，不得使用 BGE 标签展示。默认 Compose 验收没有启动 worker 容器。

## 6. 已通过的 opt-in integration

Compose integration 已记录 **6 collected / 6 passed / 0 failed / 0 skipped / 0 errors**。它覆盖真实 PostgreSQL、MinIO、Qdrant，以及 pytest 进程内注入 deterministic parser/embedder 的 `WorkerRunner` 成功与 retry contracts。

演示中可以诚实陈述：

- Alembic migration 成功；
- 五个默认长期服务曾达到 healthy；
- 真实三种存储的六项基础设施/contract integration 通过。

不可陈述：

- “worker 容器通过 6 项测试”；
- “BGE-M3 推理通过”；
- “DeepSeek 通过”；
- “备份恢复或生产加固通过”；
- “系统通过医学或临床验证”。

## 7. 真实 provider 不是开关

只把 `MOCK_MODE=false` 改掉不会切到真实 provider；Dockerfile 的默认 bridge 会拒绝启动。不要在演示现场把它当成 provider selector。

接入真实 OpenAI-compatible/DeepSeek-compatible provider 需要受审查的 Compose command/service override，并明确：

1. 使用哪个真实 app entrypoint 与 streaming adapter；
2. endpoint、key、model ID 如何安全注入；
3. provider 失败时是否 fail closed；
4. 日志、SSE 与截图如何脱敏；
5. 如何独立验证真实调用与结果。

仓库没有经过验收的真实 provider override，因此本文不提供一个看似可用但未经验证的命令。真实 provider 输出也不能自动成为医学结论。

## 8. Public eval dry-run（与 integration 6/6 不同）

完全离线的 public-eval dry-run 仍可用于展示公开数据契约：

```bash
python scripts/run_public_evaluation.py \
  --base-url http://127.0.0.1:8010 \
  --model-id dry-run-not-a-model-result \
  --retriever-id dry-run-not-a-retriever-result \
  --build-id local-dry-run \
  --dry-run
```

它校验 6 条项目自建 synthetic samples 和 aggregate-only 输出，不发 HTTP，不调用默认 mock、DeepSeek、BGE 或真实 retriever。不要把这 6 条与 Compose integration 6/6 混为一谈。

## 9. 查看日志与结束演示

```bash
docker compose --env-file config/compose.env.example logs --since=30m migrate api frontend
docker compose --env-file config/compose.env.example down
```

`down` 保留 named volumes。不要随意使用 `down -v`，它会删除 PostgreSQL、MinIO 与 Qdrant 的本地卷。结束前注销管理 session，并确认日志、截图和演示输出不含凭据、cookie、患者信息或私有正文。

## 10. 最终口径

本次演示与验收只证明默认本地 Compose 的 migration、五服务健康、deterministic mock UI/SSE，以及规定范围内的真实存储 contracts。镜像使用明确版本 tag，但未固定 digest；备份恢复、真实 DeepSeek、真实 BGE、worker 容器和生产加固都需要独立验证。
