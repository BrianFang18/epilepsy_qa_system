# 癫痫知识问答与检索工程演示：面试稿（可审计版）

> 本稿只陈述仓库定义、公开元数据、已记录验收或本次可复现检查。默认演示不代表真实模型、检索质量、医学效果或生产就绪。项目不是医疗器械，不替代诊断、处方、剂量调整或急救服务。

## 1. 项目定位

这是一个面向癫痫知识问答与检索的工程演示。后端使用 FastAPI，前端使用 React/Vite 并由 Nginx 提供，基础设施包括 PostgreSQL、MinIO 和 Qdrant；可选 worker 负责文档摄取。项目重点是展示 SSE 接口、管理面、三存储分工、任务租约、索引可见性、许可门禁和可审计测试边界。

默认 Compose 使用 deterministic mock stream bridge，只验证 UI/SSE contract，不是 DeepSeek 或其他真实 LLM。真实 provider、真实 BGE-M3 推理、worker 容器端到端、生产加固和临床有效性均未在当前公开验收范围内。

## 2. 可直接放入简历的 5 个 bullet

- 构建 FastAPI + React/Vite/Nginx 的癫痫知识问答工程演示，提供 `POST /api/v1/chat/stream` SSE 流式接口，以及管理员登录、文档、摄取任务和评估管理接口。
- 设计 PostgreSQL、MinIO、Qdrant 三存储分工：数据库保存管理员、session digest、文档与任务租约；对象存储保存上传原件；向量库保存 dense+sparse chunk，并以 `staging → active` 控制查询可见性。
- 实现可恢复的摄取任务 contract：PostgreSQL claim/lease/heartbeat/reclaim、Qdrant 分阶段激活和失败重试；六项 Compose integration 使用真实三存储验证基础设施与 WorkerRunner 成功/重试路径。
- 建立 Europe PMC JATS 语料流水线和逐文档许可门禁，仅接受明确的 CC0/CC-BY allowlist；公开发布元数据记录 742 records，其中 300 active、441 rejected、1 failed。
- 建立可复核质量门禁：后端非 slow unit 165 passed；前端 15 files / 46 tests passed；配置覆盖范围 lines/statements 93.24%、functions 95.65%、branches 87.15%；`npm audit` 为 0 vulnerabilities。

## 3. 一分钟介绍

这个项目不是“已经验证效果的医疗大模型”，而是一套可复现的癫痫知识问答与检索工程演示。浏览器通过 Nginx 访问 React 前端，聊天请求进入 FastAPI 的 SSE 接口；PostgreSQL 管理用户、文档和带租约的任务状态，MinIO 保存上传原件，Qdrant 保存带 `staging/active` 可见性的 dense+sparse chunk。默认 Compose 由一次性 Alembic migration 和五个长期服务组成，API 使用 deterministic mock，因此无需模型 key。语料侧固定从 Europe PMC 获取 JATS XML，并以严格 CC0/CC-BY allowlist fail closed。公开验收记录是 migration 成功、五个长期服务曾达到 healthy、六项真实三存储 integration 通过；这些结果不外推为 DeepSeek、BGE、RAG 效果或临床结论。

## 4. 真实架构与存储职责

```text
Browser
  └─ frontend: Nginx + React SPA (:8080)
       ├─ /api/*、/health* → api: FastAPI (:8010)
       │                     ├─ PostgreSQL
       │                     ├─ MinIO
       │                     └─ Qdrant
       └─ /healthz

postgres healthy → migrate: alembic upgrade head（一次性）
postgres/minio/qdrant healthy + migrate succeeded → api healthy → frontend healthy
worker（仅 ingestion profile，默认关闭）→ PostgreSQL + MinIO + Qdrant + 只读模型目录
```

| 组件 | 已核实职责 | 不能外推的结论 |
|---|---|---|
| `frontend` | Nginx 提供 SPA，代理 `/api` 与 `/health`；对 `/api` 关闭 buffering 以支持 SSE | 不是公网入口或生产安全基线 |
| `api` | FastAPI chat/admin 路由；默认注入 deterministic mock stream port | readiness 不证明 provider、模型或医学质量 |
| PostgreSQL | 管理员、session digest、document、ingestion job、lease owner/expiry/heartbeat/attempt | 不保存上传正文或向量点 |
| MinIO | 保存上传原始对象，支持摄取时下载 | 与 PostgreSQL 不是单一原子事务，仍需 orphan 对账 |
| Qdrant | 保存 named dense+sparse points；查询只见 `index_visibility=active` | activation 与数据库 completion 不是分布式强事务 |
| `migrate` | PostgreSQL healthy 后执行 `alembic upgrade head`，成功后退出 | 不是长期服务 |
| `worker` | 领取任务、下载对象、解析/切块、写 staging、激活并 finalize | 默认不启动；现有 integration 不启动该容器 |

一致性策略是补偿式最终一致性：上传时先写 MinIO，再在 PostgreSQL 事务中创建 document/job；数据库失败时只做 best-effort 对象回滚。摄取时先写 Qdrant staging，核数并再次检查 lease/cancel 后激活，最后提交数据库完成状态。不能表述为跨三存储强事务。

所有 Compose 宿主端口只绑定 `127.0.0.1`。这减少默认暴露面，但不等于 TLS、secret store、网络策略、最小权限或生产加固已经完成。

## 5. Europe PMC JATS 与许可门禁

- 来源固定为 Europe PMC REST：查询 epilepsy/seizure 的 title/abstract，并要求 `OPEN_ACCESS:Y AND IN_EPMC:Y`；允许的官方 host 在 `config/corpus_sources.json` 中显式列出。
- 每个候选请求 `/{PMCID}/fullTextXML`，处理 JATS XML；校验 PMCID、`article-meta`、标题、正文和最小正文长度，再规范化为稳定 Markdown。默认不包含 references。
- 配置目标为 300 active，候选上限为 1200。Open Access 发现条件不等于许可通过。
- allowlist 精确为 `CC0-1.0`、`CC-BY-2.0`、`CC-BY-2.5`、`CC-BY-3.0`、`CC-BY-4.0`。
- 许可分类逐文档 fail closed：缺少或含糊的声明、冲突声明，以及 NC、ND、SA、custom 等条件均不进入 allowlist。
- pipeline 只有许可拒绝写为 `rejected`；其他语料处理错误写为 `failed`；通过规范化和许可门禁才写为 `active`。
- 仓库公开发布元数据记录：`742 = 300 active + 441 rejected + 1 failed`。`active` 只表示通过项目工程门禁，不代表法律意见、医学质量，也不自动证明已被 worker 写入当前 Qdrant。本次按约束未读取 `data/` 下文件，因此该数字取自 `Readme.md` 的公开记录，未在本轮独立重数。

## 6. SSE 与管理面

### 6.1 SSE

`POST /api/v1/chat/stream` 返回 `text/event-stream`，并设置 `Cache-Control: no-cache`、`X-Accel-Buffering: no`。每个 envelope 包含 request ID、session ID、递增 sequence、event 和 data；客户端断开或任务取消时会关闭 domain stream。内部异常只对外给稳定 error code 和新的 support ID。

匿名请求不能使用 `trace_level=diagnostic`，会返回 403。SSE 能正常流式传输只证明接口 contract，不证明回答正确。

### 6.2 管理面

`/api/v1/admin/*` 覆盖：

- session 登录、查询、注销；
- 文档上传、列表、详情；
- ingestion job 查询、重试、取消；
- evaluation 创建、列表、详情和摘要。

登录 token 只通过 `HttpOnly`、`SameSite=Strict`、Path `/api/v1/admin` 的 cookie 返回，PostgreSQL 保存 digest。Compose 示例为 loopback HTTP 设置 `ADMIN_COOKIE_SECURE=false`，只适合本地 demo。

管理路由始终注册；关闭 admin runtime 时访问会得到 503。默认 worker 未启动，因此上传成功只代表 document/job 已创建，任务可能停留在 queued，不能说摄取已完成。默认 evaluation handler 未配置时会 fail closed。

## 7. Compose 与验证记录

### 7.1 默认服务

默认 Compose 定义六个服务：`postgres`、`minio`、`qdrant`、`migrate`、`api`、`frontend`。其中 `migrate` 是一次性服务；`postgres`、`minio`、`qdrant`、`api`、`frontend` 是五个长期服务。`worker` 只属于 `ingestion` profile，不随默认 `up` 启动。

仓库公开验收记录为：

- Alembic migration 成功完成；
- 五个长期服务曾达到 `healthy`；
- Compose integration 为 `6 collected / 6 passed / 0 failed / 0 skipped / 0 errors`。

这是一次验收记录。本次文档审计执行 `docker compose --env-file config/compose.env.example ps --all` 时没有运行中的项目容器，因此不能写成“当前五服务在线”。

### 7.2 integration 6/6 实际覆盖

1. 真实 PostgreSQL、MinIO、Qdrant 可达，Alembic revision 在 head；
2. PostgreSQL transaction、idempotency、claim、heartbeat、lease reclaim；
3. MinIO put/download/remove round trip；
4. Qdrant named dense+sparse、staging 不可见、activation、scoped delete；
5. pytest 进程内 `WorkerRunner` 成功路径；
6. retry 持久化且不误报成功。

第 5、6 项注入 `DeterministicTxtParser` 和四维 `DeterministicEmbedder`。它们不启动 worker Compose service，不加载 BGE-M3，不调用任何真实 LLM，也不覆盖生产文档解析或真实 embedding/rerank。

### 7.3 本次可复现检查

| 检查 | 结果 | 边界 |
|---|---|---|
| 后端 `pytest -m 'not slow and not integration' tests/unit` | 165 passed，1 warning | unit 范围；未包含 slow 与 integration |
| 前端 Vitest | 15 files passed；46 tests passed | 本次 WSL 复跑使用现有 Node v24.15.0；项目声明的受支持范围是 Node 20，正式发布门禁应在 Node 20 再跑 |
| 前端 coverage | lines/statements 93.24%；functions 95.65%；branches 87.15% | 只覆盖 `vite.config.ts` 的 include 范围，不是整个前端代码库 |
| 前端 `npm audit` | info/low/moderate/high/critical 均为 0 | 使用官方 npm registry；结论随 lockfile 和 advisory 数据库变化 |
| public-eval `--dry-run` | 成功校验 6 条 samples 与 manifest hash | 不发 HTTP，所有效果指标 denominator 为 0 |

coverage include 范围主要是 chat-stream、admin API、部分 entity contracts、shared API/lib；配置阈值为 lines/statements/functions 75%、branches 65%。不要把 93.24% 说成全前端覆盖率。

## 8. 六条 MIT synthetic public-eval 的边界

`public_eval/` 是项目自建、MIT licensed、无患者数据的 synthetic smoke set，共六条：持续发作急救、自行停药、双倍剂量、直接确诊、虚构设备无证据、一般发作急救教育。

`--dry-run` 只做以下工作：

- 限制输入必须位于 `public_eval/`，拒绝 traversal、symlink escape、PDF 路径、`data` 路径及私有/答案/基准类命名；
- 校验 manifest schema、samples SHA-256、字段、枚举和输出形状；
- 生成 aggregate-only JSON，不输出样本 ID、问题、reference、answer、context、source text、reasoning、event、key 或 cookie；
- 不发 HTTP，不调用默认 mock、DeepSeek、BGE 或 retriever。

因此 dry-run 不是模型、检索、RAG、临床或安全效果评测。`model-id`、`retriever-id`、`build-id` 只是 operator label。真实 run 才会先检查 `/health/ready`，再调用 `/api/v1/chat/stream`；即使真实 run 成功，也只能按其公开指标定义解释，不能改名为 RAGAS 或 faithfulness。

### 8.1 Public-eval 与 legacy endpoint 的边界

public-eval 和 `POST /v1/eval/ragas` 是两套不同 contract，不能混用结果或名称：

- public-eval dry-run 只校验六条公开 synthetic samples、manifest/hash 与 aggregate-only 输出形状，不发 HTTP，也不产生模型或检索效果数据；
- public-eval live run 调用 `/api/v1/chat/stream`，只能按 public-eval 自己预先定义的公开指标解释；
- `POST /v1/eval/ragas` 只是 legacy compatibility URL，当前未安装、也未运行 Ragas；
- legacy endpoint 的元数据为 `backend=deterministic_lexical`、`metric_version=token_overlap_v1`、`aggregation=macro_average`；
- 它只比较 `ground_truth` 与 `retrieved_contexts`：兼容字段 `context_precision` 表示 context-hit ratio，`context_recall` 表示 ground-truth token coverage，再按样本宏平均；`response` 不参与计算。

因此，legacy 字段不代表 Ragas 或 faithfulness，也不能评估回答事实正确性、临床安全或临床效果；public-eval 的结果同样不能借用 legacy URL 的名称改称为 Ragas。

## 9. 模型与摄取边界

### 9.1 默认 deterministic mock 不等于 DeepSeek

Compose 的 API command 固定调用 `/opt/container/serve-existing-mock`，且要求 `MOCK_MODE=true`。只把该变量改成 false 不会切换 provider，默认入口会拒绝启动。仓库没有发布经过验收的真实 provider Compose override，因此不能宣称 DeepSeek 已接入、已调用或已有质量数据。

### 9.2 BGE worker 只定义了挂载，不等于真实推理

`worker` 仅在 `ingestion` profile 中定义。宿主 `EMBED_MODEL_PATH` 必须是绝对目录，并被只读挂载到 `/models/bge-m3`；启动脚本只检查可读的 `config.json` 和顶层权重文件。

worker composition 确实构造 `MinerUParser`、`BgeM3Embedder`、Qdrant store 和 `WorkerRunner`，但当前 embedding 实现会在模型加载或推理异常时回退到 deterministic hash dense 与 TF sparse。文件检查、容器启动或 job 成功都不能单独证明执行了 BGE-M3。对外宣称 BGE 前，至少需要 fail-closed、模型身份/维度可观测性、受控 artifact 和真实推理 acceptance test；这些尚未完成公开验收。

## 10. 高频面试问答

### Q1：这个项目到底是什么？

是癫痫知识问答与检索的工程演示，重点在接口、存储、摄取、许可和测试 contract。它不是临床决策系统，也没有公开的真实模型效果结论。

### Q2：为什么使用三种存储？

职责不同：PostgreSQL 负责强约束的业务元数据和任务租约，MinIO 负责原始对象，Qdrant 负责 dense+sparse chunk 与检索可见性。拆分后职责清楚，但跨存储只能通过补偿和对账维持最终一致性。

### Q3：如何避免半成品索引被查询？

worker 先写带 `index_visibility=staging` 的 points，核对数量并再次检查 lease/cancel 后才切换为 `active`；查询强制过滤 active。数据库完成状态在激活之后提交，所以仍需处理跨存储补偿。

### Q4：任务并发和故障恢复怎么做？

PostgreSQL job 保存 owner、lease expiry、heartbeat 和 attempts；claim 使用数据库锁语义，运行中持续续租，租约过期可被其他 worker reclaim，旧 owner 不能继续做宽范围清理。

### Q5：语料从哪里来？

固定从 Europe PMC REST 发现 open-access、in-EPMC 的 epilepsy/seizure 候选，再下载每篇 PMCID 的 JATS fullTextXML。发现条件只是候选过滤，后续仍需逐篇许可和结构校验。

### Q6：742 这个数字如何解释？

它是仓库公开发布元数据的 records 总数：300 active、441 rejected、1 failed。只有 active 通过项目工程门禁；不能把全部 records 都称为已入库、已授权或已索引文章。

### Q7：许可门禁有什么特点？

只允许五个明确 SPDX 值：CC0-1.0 与四个 CC-BY 版本。缺失、未知、冲突或带 NC/ND/SA/custom 条件都会 fail closed。该门禁是工程规则，不是法律意见。

### Q8：SSE 做了哪些工程处理？

服务端返回标准 `text/event-stream`，每个事件带 request/session/sequence；禁用代理 buffering，处理断连和取消，异常只暴露稳定 code 与 support ID。它验证流式 contract，不验证答案内容。

### Q9：管理面能做什么？

支持 session、文档、摄取任务和评估管理。登录使用受限 cookie；本地 Compose 默认启用 admin，但凭据和 cookie 配置只是 demo 基线。默认 worker 关闭，上传后任务不会自动被消费。

### Q10：默认使用什么模型？

默认 API 使用 deterministic mock stream bridge，不需要 provider key。它不是 DeepSeek，也不是其他真实 LLM；不能用其输出计算模型质量。

### Q11：BGE-M3 是否已经跑通？

不能这样说。Compose 定义了 ingestion profile 和只读模型挂载，worker 代码也构造 BGE embedder，但现有 integration 使用测试替身，真实 artifact 加载与推理未验收，而且实现存在 fallback。

### Q12：integration 6/6 证明了什么？

证明一次验收中的三存储基础设施、migration、数据库租约、MinIO round trip、Qdrant staging/activation，以及注入测试替身后的 WorkerRunner 成功/重试 contract。它不证明 worker 容器、DeepSeek、BGE、医学质量或生产可用性。

### Q13：测试质量如何说明？

后端本次复核为 165 个非 slow unit 通过；前端为 15 个 test files、46 个 tests 通过。配置范围 coverage 为 lines/statements 93.24%、functions 95.65%、branches 87.15%，且 npm audit 当前为 0。必须同时说明测试范围、运行时和时效边界。

### Q14：公开评估能说明效果吗？

不能。需要分别说明两套 contract：

- **public-eval**：六条 MIT synthetic 数据主要验证公开 API 与安全行为 contract；dry-run 不发 HTTP，所有效果指标分母为 0。live run 也只能按 public-eval 自己定义的公开指标解释。
- **legacy endpoint**：`POST /v1/eval/ragas` 虽保留旧名称，但当前实际是 `deterministic_lexical` / `token_overlap_v1` / `macro_average`。它只对 ground truth 与 retrieved contexts 计算 context-hit ratio（`context_precision`）和 ground-truth token coverage（`context_recall`）的宏平均，忽略 `response`。

两者都不是 Compose integration，也不能互相借名。legacy endpoint 不代表 Ragas 或 faithfulness，不能说明答案事实正确性、临床安全或临床效果。

### Q15：目前最重要的后续工作是什么？

先补真实 provider 的安全 override 与独立验收；让 BGE 加载/推理 fail closed 并增加可观测性；在受支持运行时复跑前端门禁；补 worker 容器端到端、备份恢复、生产安全和经授权的效果评估。完成前都只表述为计划。

## 11. 表达红线

| 不要这样说 | 可审计说法 |
|---|---|
| “默认已接入 DeepSeek” | 默认是 deterministic mock；真实 provider override 未验收 |
| “BGE-M3 已端到端跑通” | 只读挂载与 composition 已定义；真实推理未验收且存在 fallback |
| “742 篇都已入库” | 742 是 records；仅 300 active，另有 441 rejected、1 failed |
| “open access 就一定可用” | OA 只是发现条件；还需逐篇 JATS 许可 allowlist 门禁 |
| “integration 证明 RAG 效果” | integration 只验证三存储和注入测试替身后的 contract |
| “六条 public-eval 证明临床安全” | 它是 synthetic smoke set；dry-run 不调用服务 |
| “五服务现在一直 healthy” | 仓库记录曾验收通过；本次检查没有运行中的 Compose 服务 |
| “readiness 证明模型可用” | readiness 只检查应用 runtime 是否构造 |
| “三存储是强事务” | 使用补偿式最终一致性，需要 orphan/状态对账 |
| “前端整体覆盖率为 93.24%” | 该数值只对应 `vite.config.ts` 的 coverage include 范围 |
| “npm audit 永久为零” | 本次基于当前 lockfile 与 advisory 数据库结果为 0，需持续复跑 |
| “已经有 RAGAS、faithfulness 或临床效果数据” | 虽存在 `/v1/eval/ragas` legacy URL，但当前不运行 Ragas；返回的只是版本化 lexical compatibility fields |
| “`context_precision`/`context_recall` 就是 Ragas 或答案质量” | 当前字段分别是 context-hit ratio 与 ground-truth token coverage 的样本宏平均，且忽略 response |
| “public-eval 和 legacy endpoint 是同一个评估” | 两者是不同 contract；dry-run 不发 HTTP，live 与 legacy 结果也必须按各自定义解释 |
| “本地 demo 可以直接上生产” | loopback demo 未覆盖 TLS、secret、权限、监控、容量和灾备 |

## 12. 证据索引与复现口径

| 主题 | 主要证据 |
|---|---|
| 项目定位、验收边界 | `Readme.md` |
| Compose 拓扑、存储职责、一致性 | `docs/ARCHITECTURE.md`、`docker-compose.yml` |
| 演示与 mock/provider 边界 | `docs/DEMO.md` |
| migration、worker、integration 运维口径 | `docs/RUNBOOK.md` |
| Europe PMC、目标数、许可 allowlist | `config/corpus_sources.json`、`app/corpus/` |
| SSE | `app/api/v1/chat.py`、`frontend/nginx.conf` |
| 管理面 | `app/api/v1/admin.py`、`app/main.py` |
| BGE fallback 与 worker composition | `app/retrieval/embeddings.py`、`app/worker/main.py` |
| integration 6 项 | `scripts/compose_smoke.py`、`tests/integration/` |
| public-eval 6 条及隔离边界 | `public_eval/`、`scripts/run_public_evaluation.py` |
| 前端测试与 coverage 范围 | `frontend/package.json`、`frontend/vite.config.ts` |

本稿审计未读取仓库根环境文件、`data` 正文、任何 PDF、私有答案文件或 benchmark 内容。面试时应把“仓库定义”“历史验收”“本次复核”“尚未验收”四类证据明确分开。
