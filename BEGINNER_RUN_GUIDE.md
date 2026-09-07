# 中文新手使用指南

这份文档面向第一次使用本项目的人。你不需要先理解 FastAPI、Qdrant 或 LangGraph；按顺序完成一次“启动 -> 上传文档 -> 等待摄取 -> 提问 -> 查看证据”即可。

> 先说明最重要的事实：以前上传后一直“排队中”，不是你不会使用，而是默认 Compose 没有启动 worker。现在默认 worker 会自动启动并处理上传任务。默认聊天也不再伪装成真实模型：它只展示相关证据摘录，并明确标注“确定性 Demo · 非模型生成”。

本项目是技术演示和健康信息检索工具，不是医疗器械，不提供诊断、处方、剂量调整或急救服务。不要上传真实患者身份信息、真实病历、生产密钥、私有答案或未获授权的文档。

## 1. 先用一分钟理解系统

系统有两个主要入口：

| 页面 | 地址 | 用途 |
| --- | --- | --- |
| 聊天页面 | <http://127.0.0.1:8080/> | 对已经成功摄取的本地证据提问 |
| 管理后台 | <http://127.0.0.1:8080/admin/login> | 上传文档、查看摄取进度、查看评估页 |

默认运行模式包含真实的 PostgreSQL、MinIO、Qdrant、FastAPI、worker 和 React 前端，但模型能力有明确边界：

- 文档会真实上传到 MinIO，并由 worker 自动处理；
- 文档会真实分块、生成确定性向量并写入 Qdrant；
- 默认向量后端是 `deterministic-md5-tf-v2`，不是 BGE-M3；
- 默认聊天不是 LLM 生成，只会摘取与问题有词法关联的证据；
- 问候和明显域外问题不会误进知识库检索；
- 中文问题返回中文系统说明，英文问题返回英文系统说明；
- 当前没有真实评估执行器，评估创建入口被禁用。

## 2. 第一次启动

### 2.1 准备环境

在 Windows 上启动 Docker Desktop，并确认已为 Ubuntu-20.04 开启 WSL Integration。然后打开 Ubuntu-20.04 终端，进入你 clone 的仓库目录：

```bash
cd "$HOME/work_project/epilepsy_qa_system"
pwd
docker version
docker compose version
```

为了避免 Compose 隐式读取仓库根 `.env`，每次新开终端先执行：

```bash
export COMPOSE_DISABLE_ENV_FILE=1
```

后续每条 Compose 命令都要显式带：

```text
--env-file config/compose.env.example
```

### 2.2 校验配置

```bash
docker compose --env-file config/compose.env.example config --quiet
docker compose --env-file config/compose.env.example config --services
```

默认服务应包含：

```text
postgres
minio
qdrant
migrate
api
worker
frontend
```

`worker-bge` 不应出现在默认列表中；它是高级 opt-in profile，不是新手流程。

### 2.3 构建并启动

第一次运行：

```bash
docker compose --env-file config/compose.env.example up --build -d
```

后端镜像包含较大的可选模型运行依赖，首次构建可能很慢。以后如果依赖没有变化，普通源码层会使用缓存。官方软件源较慢时，可以先单独构建：

```bash
docker compose --env-file config/compose.env.example build \
  --build-arg DEBIAN_MIRROR=https://mirrors.tuna.tsinghua.edu.cn \
  --build-arg PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple

docker compose --env-file config/compose.env.example up -d
```

这两个镜像参数只影响构建，不会切换聊天或 embedding 模式。

### 2.4 检查服务状态

```bash
docker compose --env-file config/compose.env.example ps --all
```

正常状态：

| 服务 | 正常表现 |
| --- | --- |
| `postgres` | Up / healthy |
| `minio` | Up / healthy |
| `qdrant` | Up / healthy |
| `api` | Up / healthy |
| `worker` | Up；当前没有单独 healthcheck |
| `frontend` | Up / healthy |
| `migrate` | `Exited (0)`，表示迁移成功，不是故障 |

再检查 HTTP：

```bash
curl -fsS http://127.0.0.1:8080/healthz
curl -fsS http://127.0.0.1:8010/health
curl -fsS http://127.0.0.1:8010/health/ready
```

默认 readiness 中应看到：

```json
{
  "status": "ready",
  "chat_mode": "demo",
  "model_generation_enabled": false,
  "admin_enabled": true,
  "admin_ready": true
}
```

`model_generation_enabled=false` 不是启动失败，它诚实表示当前没有真实 LLM 在生成回答。

## 3. 登录管理后台

打开：

<http://127.0.0.1:8080/admin/login>

`config/compose.env.example` 中的本地公开占位账号为：

```text
用户名：CHANGE_ME_admin
密码：CHANGE_ME_admin_password
```

它只适合当前 `127.0.0.1` 本地 Demo。不要把该账号用于共享环境或生产环境。

登录后主要看到两个页面：

1. **文档摄取**：把 PDF/TXT/Markdown 变成聊天可检索的证据；
2. **评估看板**：未来展示受控 evaluator 的聚合指标；当前没有执行器，因此只读且不能创建任务。

## 4. 文档摄取页面到底做什么

### 4.1 一条上传任务的真实流程

```text
浏览器选择文件
  -> API 校验扩展名、类型和大小
  -> 原始文件写入 MinIO
  -> PostgreSQL 创建 document 和 queued ingestion job
  -> worker 自动领取任务
  -> fetch：从 MinIO 获取原件
  -> parse：解析文字
  -> chunk：生成父子分块
  -> embed：生成 deterministic-md5-tf-v2 向量
  -> index：以 staging 状态写入 Qdrant
  -> finalize：核对并切换为 active，任务成功
```

上传文档不等于“把文件直接交给大模型”，也不等于“训练模型”。它只是建立本地可检索索引。

### 4.2 支持什么文件

- PDF、TXT、Markdown；
- 单文件最大 25 MB；
- 可选显示标题；
- 类型可选“文献资料”或“临床资料”。

为了演示，请只使用项目自建的合成文本。例如在 WSL 创建：

```bash
printf '%s\n' \
  '本项目自建合成证据，不含患者或隐私数据。' \
  '癫痫发作时，家属应记录发作开始时间，清理周围危险物品并保持环境安全。' \
  > /tmp/epilepsy-demo.txt
```

Windows 文件选择器可以输入：

```text
\\wsl.localhost\Ubuntu-20.04\tmp\epilepsy-demo.txt
```

### 4.3 如何判断上传真的成功

1. 选择文件并点击“上传并排队”；
2. 短暂显示“排队中”是正常的；
3. worker 领取后，“尝试”通常从 `0/3` 变成 `1/3`；
4. 进度依次经过获取、解析、分块、向量、索引、完成；
5. 最终显示 `succeeded`、`finalize`、`100%`；
6. 页面提示“文档已完成索引并生效”。

只有第 5 步完成后，聊天才应该检索到这份资料。`queued` 只表示任务已创建，不能当成已入库。

相同内容和相同处理流水线再次上传时，系统可能复用已有任务，这是幂等行为，不是上传失败。

### 4.4 各状态怎么理解

| 状态 | 含义 | 你应该做什么 |
| --- | --- | --- |
| `queued` | 等待 worker 领取 | 通常等几秒；长时间 0/3 则查 worker |
| `running` | 正在处理 | 查看阶段和进度，不要重复上传 |
| `retry_wait` | 一次尝试失败，等待自动重试 | 查看 worker 日志和错误信息 |
| `succeeded` | 索引已激活 | 可以回聊天页面提问 |
| `failed` | 达到失败条件 | 修复原因后点“重试” |
| `canceled` | 已取消 | 需要时点“重试” |

## 5. 聊天页面应该怎么用

打开：

<http://127.0.0.1:8080/>

对刚才的合成文档提问：

```text
癫痫发作时，家属应记录什么并如何保持环境安全？
```

默认正确表现：

- 页面显示“确定性 Demo · 非模型生成”；
- 回答使用中文；
- 正文直接摘取刚才上传的相关片段；
- 文中出现 `[C1]` 等引用；
- “查看证据”中可看到标题、摘录和分数；
- 回答末尾有医疗免责声明。

### 5.1 为什么默认回答不像大模型

因为默认 `CHAT_LLM_MODE=demo`。它故意不做“智能归纳”，而是：

1. 检索本地证据；
2. 过滤与问题缺少词法重叠的结果；
3. 直接展示最多三段相关摘录；
4. 明确告诉你这不是 LLM 生成。

这样做是为了不再用固定模板伪装成模型能力。要获得自然语言综合回答，必须另行选择并配置真实 OpenAI-compatible 模型。

### 5.2 语言、问候和域外问题

- 输入 `你好`：本地返回中文问候，不检索；
- 输入 `hello`：本地返回英文问候，不检索；
- 输入“请帮我写 Python 代码”：返回域外提示，不检索，也不调用模型；
- 中文医学问题：中文系统回答；
- 英文医学问题：英文系统回答；
- 回答语言以最新一条原始用户消息为准，不受内部 query rewrite 影响。

### 5.3 为什么会显示“证据不足”

常见原因：

- 知识库为空；
- 上传任务尚未 `succeeded`；
- 问题与文档内容不相关；
- 默认确定性检索依赖词法重叠；
- 用中文问题查只有英文措辞的材料，或反过来。

默认模式不是 BGE 语义模型。先使用与文档相同的语言和关键词验证完整链路，不要把它描述成跨语言语义检索。

## 6. 评估看板到底是什么

评估看板不是：

- 文档处理进度；
- 用户聊天次数统计；
- 自动生成的“准确率”；
- 已经接好的 RAGAS 或 LLM Judge。

它的设计用途是：未来在有受控测试集和真实 evaluator 时，展示检索、生成、安全等任务的状态和**聚合指标**。敏感样本明细不应直接展示在页面上。

当前项目没有配置真实 evaluation runner，因此：

- 页面会显示黄色说明；
- “创建评估任务”按钮被禁用；
- API 创建请求返回 HTTP 409；
- 不会创建永远排队的任务；
- 不会伪造准确率、成功率或其他指标；
- 页面仍可显示历史任务或历史聚合结果（如果 volume 中存在）。

`public_eval` 的 `--dry-run` 是另一套合成结构校验，只校验 schema、hash 和输出形状，不是模型质量评估。

## 7. 上传一直排队时怎么排查

如果短暂排队，不需要操作。如果超过约 30 秒仍是 `queued` 且 `attempts 0/3`：

```bash
docker compose --env-file config/compose.env.example ps --all worker
docker compose --env-file config/compose.env.example logs --since=10m worker
```

### 情况 A：列表中没有 worker

重新启动默认服务：

```bash
docker compose --env-file config/compose.env.example up -d
```

或只启动 worker：

```bash
docker compose --env-file config/compose.env.example up -d worker
```

默认 worker 不需要 profile，也不需要模型文件。

### 情况 B：worker 已退出或反复重启

查看最后日志：

```bash
docker compose --env-file config/compose.env.example logs --tail=200 worker
```

同时检查基础设施：

```bash
docker compose --env-file config/compose.env.example ps --all postgres minio qdrant migrate
```

### 情况 C：attempts 已增加并显示错误

这说明 worker 已经领取任务，问题发生在解析、分块、索引或存储阶段。不要重复上传；先看页面错误和 worker 日志，修复后对 `failed/canceled` 任务点击“重试”。

## 8. 其他常见问题

### 8.1 管理员登录失败

bootstrap 管理员只在数据库中不存在时创建。若复用了旧 PostgreSQL volume，修改示例密码不会覆盖旧用户。

如果本地所有数据都可丢弃，才可以执行：

```bash
docker compose --env-file config/compose.env.example down -v
```

这会永久删除 PostgreSQL、MinIO 和 Qdrant 三个 named volume；不要把它当普通重启命令。

### 8.2 API healthy，但页面说不是模型生成

这是默认正确行为。检查：

```bash
curl -fsS http://127.0.0.1:8010/health/ready
```

`chat_mode=demo`、`model_generation_enabled=false` 表示诚实的确定性 Demo。

### 8.3 `migrate` 显示 Exited

`Exited (0)` 是成功；它是一次性数据库迁移服务。只有非 0 才需要查看：

```bash
docker compose --env-file config/compose.env.example logs migrate
```

### 8.4 前端等待 API

```bash
docker compose --env-file config/compose.env.example logs --since=10m api frontend
```

前端依赖 API healthy，先解决 API readiness。

## 9. 真实模型模式怎么选择

默认模式不下载模型、不索要 Key，也不产生 API 费用。切换真实模型涉及资源、网络和费用，需要你先选择：

1. **本地 Ollama/vLLM 7B 或 14B**：RTX 3090 24 GB 通常适合这一级别，但要决定模型和部署位置；
2. **其他自托管 OpenAI-compatible 服务**；
3. **DeepSeek/OpenAI-compatible API**：需要 backend-only Key，并可能产生费用。

代码使用：

```text
CHAT_LLM_MODE=openai_compatible
DEEPSEEK_BASE_URL=<OpenAI-compatible /v1 endpoint>
DEEPSEEK_API_KEY=<非空且不是 EMPTY 的后端 Key>
DEEPSEEK_MODEL=<服务端模型 ID>
```

变量名称保留了 DeepSeek 前缀，但协议是通用 OpenAI-compatible。不要把 Key 写进 `config/compose.env.example` 后提交。可复制为 Git 忽略的本地文件：

```bash
cp config/compose.env.example .env.local
```

修改 `.env.local` 后显式使用：

```bash
export COMPOSE_DISABLE_ENV_FILE=1
docker compose --env-file .env.local up -d --force-recreate api frontend
```

注意：

- 缺 endpoint、model 或非占位 Key 时，真实模式会 fail closed；
- readiness 的 `model_generation_enabled=true` 表示模式已启用，不等于模型质量已验证；
- Windows Ollama 默认只监听 `127.0.0.1:11434`，原生 WSL Docker 通常不能直接访问；不要未经安全决定就改成对所有网卡开放；
- 切换真实 LLM 只改变回答生成，不会自动把默认 embedding 变成 BGE-M3。

如果你希望继续配置真实模型，请先明确选择“本地 7B/14B”还是“API”。

## 10. BGE-M3 的边界

默认 worker 使用 `deterministic-md5-tf-v2`。仓库还定义了 `worker-bge` 和 `bge-ingestion` profile，但它不是新手的一键模式：

- 需要本地真实 BGE-M3 `config.json` 和权重；
- 缺文件会直接启动失败，不会把 fallback 冒充 BGE；
- 不能与默认 worker 同时消费同一队列；
- 只启动 BGE worker 还不等于 API query embedding 已完成兼容配置；
- 必须单独做维度、模型身份、query/ingestion 一致性和端到端验收。

因此，在没有完成整套真实模型配置前，保持默认 worker 即可。

## 11. 日常启动、停止和查看日志

日常启动：

```bash
export COMPOSE_DISABLE_ENV_FILE=1
cd "$HOME/work_project/epilepsy_qa_system"
docker compose --env-file config/compose.env.example up -d
```

查看状态：

```bash
docker compose --env-file config/compose.env.example ps --all
```

查看主要日志：

```bash
docker compose --env-file config/compose.env.example logs --since=10m api worker frontend
```

停止并保留数据：

```bash
docker compose --env-file config/compose.env.example down
```

下次 `up -d` 会继续使用保留的管理员、上传记录、对象和向量索引。

## 12. 你已经会使用系统的判定标准

完成以下清单就足够：

- [ ] 能启动默认 Compose，并知道 `migrate Exited (0)` 是成功；
- [ ] 能登录 `/admin/login`；
- [ ] 能在“文档摄取”上传一个非敏感 TXT；
- [ ] 能看到任务从 queued 进入 running，最后 succeeded / 100%；
- [ ] 能回聊天页用相同语言和关键词提问；
- [ ] 能打开证据抽屉，确认回答来自已上传资料；
- [ ] 知道默认回答是证据摘录，不是真实 LLM；
- [ ] 知道评估看板当前禁用，不是聊天统计；
- [ ] 知道真实模型和 BGE 都需要额外选择及验收。

更多操作细节见 [Demo 手册](docs/DEMO.md)，架构原理见 [架构说明](docs/ARCHITECTURE.md)，运维排障见 [Runbook](docs/RUNBOOK.md)。
