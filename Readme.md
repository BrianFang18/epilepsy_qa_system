# Epilepsy QA System

面向癫痫知识问答与检索的工程演示：后端使用 FastAPI，前端使用 React/Vite，基础设施使用 PostgreSQL、MinIO 与 Qdrant，并提供可选的摄取 worker。项目用于软件工程、检索和安全边界演示，**不是医疗器械，也不提供诊断、处方、剂量调整或紧急处置的替代意见**。

## 当前能力与事实边界

- 根目录 `app/` 是唯一后端实现；浏览器应用位于 `frontend/`。
- `docker-compose.yml` 已提供本地演示编排。默认启动 `postgres`、`minio`、`qdrant`、一次性 `migrate`、`api` 和 `frontend`；`worker` 只属于 `ingestion` profile，默认不启动。
- 默认 Compose API 使用 Dockerfile 内的专用 deterministic mock stream bridge，无需 provider key 即可演示 SSE 聊天。**mock 响应不等于 DeepSeek 响应，也不代表任何真实模型效果。**
- `POST /api/v1/chat/stream` 提供 SSE 聊天接口；`/api/v1/admin/*` 提供管理接口。示例 Compose 为本地演示启用管理接口，不能把该设置直接视为生产安全基线。
- worker 从 PostgreSQL 领取带租约的任务，读取 MinIO 对象并写入 Qdrant；它需要 operator 提供真实 BGE-M3 文件，且不在默认栈的已验证范围内。
- corpus 发布元数据统计为 **742 records = 300 active + 441 rejected + 1 failed**。`active` 只表示通过项目工程门禁，不表示医学、法律或版权结论。
- `public_eval/` 是项目自建的 6 条 synthetic smoke samples。它与下文 Compose integration 的“6/6 passed”不是同一测试集，也不能作为临床或真实模型效果证据。

## 仓库结构

```text
app/                    # 唯一 Python/FastAPI 后端
  api/v1/               # chat 与 admin HTTP 路由
  modules/              # chat/admin 应用服务
  infrastructure/       # PostgreSQL、MinIO、模型适配器
  retrieval/            # 解析、分块、embedding、Qdrant、rerank
  worker/               # 带 lease/heartbeat 的后台任务执行器
frontend/               # React 19 + Vite，容器内由 Nginx 提供
alembic/                 # PostgreSQL schema migration
config/compose.env.example
config/corpus_sources.json
public_eval/             # 公开 synthetic smoke set 与 manifest
scripts/                 # Compose/public-eval/corpus CLI
tests/integration/       # opt-in Compose infrastructure contracts
docs/                    # 架构、运行与演示文档
docker-compose.yml
```

更详细的边界见 [架构文档](docs/ARCHITECTURE.md)，操作步骤见 [Runbook](docs/RUNBOOK.md)，演示流程见 [Demo](docs/DEMO.md)。

## 运行要求

- Docker Engine 与 Docker Compose plugin；以下命令从仓库根目录执行。
- 源码开发使用 **Python 3.11.x**；前端构建使用 Node.js `>=20 <21`。
- 默认 Compose 演示不需要 DeepSeek 或其他 provider key。
- 启用 `ingestion` profile 前，宿主机必须已有可读取的 BGE-M3 模型目录。

## 本地 Compose 演示

所有仓库支持的 Compose 命令都必须显式指定示例环境文件：

```bash
docker compose --env-file config/compose.env.example config --quiet
docker compose --env-file config/compose.env.example up --build -d
docker compose --env-file config/compose.env.example ps --all
```

**不要省略 `--env-file config/compose.env.example`，不要让 Compose 隐式读取仓库根 `.env`。** `config/compose.env.example` 中的 `CHANGE_ME_*` 只是本地、隔离 demo 的占位凭据；不要把这些值用于共享、测试、预发布或生产环境，也不要在该文件中写入真实生产 secret。生产部署与 secret 注入不在本次 Compose 验收范围内。

默认拓扑如下：

| Service | 生命周期 | 宿主访问 | 说明 |
|---|---|---|---|
| `postgres` | 长期 | `127.0.0.1:5432` | PostgreSQL 16.6 |
| `minio` | 长期 | API `127.0.0.1:9000`；Console `127.0.0.1:9001` | Console 映射已在 Compose 中确认 |
| `qdrant` | 长期 | `127.0.0.1:6333` | Qdrant 1.12.6 |
| `migrate` | 一次性 | 无宿主端口 | PostgreSQL healthy 后执行 `alembic upgrade head` |
| `api` | 长期 | `127.0.0.1:8010` | 默认 deterministic mock stream bridge |
| `frontend` | 长期 | `127.0.0.1:8080` | Nginx 静态站点并代理 `/api`、`/health` |
| `worker` | 可选 | 无宿主端口 | 仅 `ingestion` profile；默认不启动 |

所有已发布端口都只绑定 `127.0.0.1`，不是局域网或公网暴露配置。浏览器入口为 <http://127.0.0.1:8080>，API 可直接访问 <http://127.0.0.1:8010>。

```bash
curl -fsS http://127.0.0.1:8080/healthz
curl -fsS http://127.0.0.1:8010/health
curl -fsS http://127.0.0.1:8010/health/ready
```

`/health/ready` 是应用级 readiness，不替代深度 provider、模型或数据质量验证。

## 已执行的 Compose 验收

仓库当前的 Compose 验收记录为：

- 一次性 `migrate` 已成功执行 Alembic upgrade；
- 五个长期服务 `postgres`、`minio`、`qdrant`、`api`、`frontend` 均已实测达到 `healthy`；
- opt-in integration suite 已取得 **6 collected / 6 passed / 0 failed / 0 skipped / 0 errors**。

这组 6 项测试使用真实 PostgreSQL、MinIO 与 Qdrant，并验证数据库事务/lease、MinIO round trip、Qdrant staging→active、以及向 `WorkerRunner` 注入 deterministic parser/embedder 后的成功与重试 contracts。它**不启动或证明 `worker` 容器，不加载 BGE-M3，不调用 DeepSeek/其他 provider，也不证明真实 embedding、rerank、LLM 或医学效果**。该结果是一次验收记录，不是服务当前持续在线的承诺。

## 默认 mock 与真实 provider

Compose 的 `api.command` 固定调用 `/opt/container/serve-existing-mock`。该 Dockerfile 专用桥接器把现有 deterministic mock 客户端接到 streaming port，并要求 `MOCK_MODE=true`，所以默认演示无需 provider endpoint、provider key 或虚构 model ID。

只把 `MOCK_MODE=false` 改掉**不会**切换到真实 provider；默认 command 会拒绝启动。接入真实 OpenAI-compatible/DeepSeek-compatible provider 需要经过安全与行为评审的 Compose command/service override、明确的 endpoint/key 注入、失败语义和单独验收。本仓库没有发布该 override 的已验证配置，也没有真实 DeepSeek 或其他模型效果证据。

## 可选 ingestion worker

`worker` 默认不启动。启用前必须把 `config/compose.env.example` 中的 `EMBED_MODEL_PATH` 改为宿主机上已存在的**绝对目录**；Compose 会将它只读挂载到 `/models/bge-m3`。worker 启动脚本还会检查 `config.json` 与模型权重文件：

```bash
docker compose --env-file config/compose.env.example --profile ingestion up --build -d worker
docker compose --env-file config/compose.env.example --profile ingestion ps --all worker
```

只有确认真实 artifact 已加载并执行真实推理后，才能把结果称为 BGE-M3。任何 deterministic/hash/lexical fallback 都不是 BGE；上面的 6/6 integration 也只使用注入的 deterministic 测试替身。worker 容器与真实 BGE 推理仍需单独验收。

## 镜像固定方式

Compose 与两个 Dockerfile 使用明确版本 tag，例如 PostgreSQL `16.6-bookworm`、MinIO `RELEASE.2024-11-07T00-52-20Z`、Qdrant `v1.12.6`、Python `3.11.11-slim-bookworm`、Node `20.11.0-alpine3.19` 和 Nginx `1.27.3-alpine3.20`。这些是版本 tag，**不是 image digest 固定**；不能据此声称供应链产物不可变。

## 管理面与 cookie

示例 Compose 设置 `ENABLE_ADMIN_API=true`，仅用于本地 demo。登录成功后，后端设置名为 `epilepsy_admin_session` 的 `HttpOnly`、`SameSite=Strict` cookie，Path 为 `/api/v1/admin`，默认 TTL 1800 秒。示例 Compose 的 `ADMIN_COOKIE_SECURE=false` 也只适合 loopback HTTP 演示；任何受信部署都必须重新评审 HTTPS、cookie、CORS、网络入口和凭据。

Bootstrap 用户只在不存在时创建。修改 `ADMIN_BOOTSTRAP_PASSWORD` 不会轮换已有用户密码；当前代码没有管理员改密 API，详见 [Runbook](docs/RUNBOOK.md)。

## 公开评测

完全离线的 dry-run：

```bash
python scripts/run_public_evaluation.py \
  --base-url http://127.0.0.1:8010 \
  --model-id dry-run-not-a-model-result \
  --retriever-id dry-run-not-a-retriever-result \
  --build-id local-dry-run \
  --dry-run
```

它只校验 6 条 synthetic 样本、manifest hash、字段约束和 aggregate-only 输出，不发出 HTTP 请求。不要把 dry-run、默认 Compose mock 或 integration 6/6 表述为真实模型、RAG、临床安全或效果研究结果。

## 验证范围与免责声明

本次验收没有验证备份恢复、真实 DeepSeek、真实 BGE-M3 推理、worker 容器或生产加固。项目自有代码按根目录 [LICENSE](LICENSE) 的 MIT License 提供；第三方软件、模型、文章和服务保留各自权利与条款。

本系统只用于技术演示和信息检索辅助，不替代医生诊断、个体化治疗、药物调整或急救服务。若正在发生持续发作、反复发作、呼吸困难、受伤或意识未恢复等紧急情况，应立即联系当地急救服务。
