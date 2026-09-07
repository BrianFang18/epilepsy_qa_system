# 本地完整 Demo 运行手册

本文用于逐项演示和验收 Epilepsy QA System。命令默认在 Ubuntu-20.04 WSL 终端、仓库根目录执行。

> 默认 Demo 使用真实 PostgreSQL、MinIO、Qdrant、FastAPI、worker 和 React 前端。文档上传会自动完成摄取；聊天默认只展示相关证据摘录，并明确标注“非模型生成”。它不代表真实 LLM、BGE-M3、临床效果或生产部署。

不要输入患者身份信息、真实病历、处方、生产凭据、私有文档、私有评测答案或其他敏感数据。

## 1. 演示前检查清单

- [ ] Docker Desktop 已启动并启用 Ubuntu-20.04 WSL Integration
- [ ] 已设置 `COMPOSE_DISABLE_ENV_FILE=1`
- [ ] Compose 配置校验通过
- [ ] 六个长期服务已启动，`migrate` 为 `Exited (0)`
- [ ] frontend、API health 和 readiness 正常
- [ ] 使用项目自建合成 TXT 验证管理上传
- [ ] 摄取任务达到 `succeeded / finalize / 100%`
- [ ] 中英文问题按提问语言回答
- [ ] `hello/你好` 不产生引用
- [ ] 明显域外问题返回 out-of-scope
- [ ] 已向观众解释默认 Demo 不是 LLM/BGE
- [ ] 已解释评估看板当前只读且没有 evaluator

## 2. 默认 Demo 能证明什么

能够证明：

- Compose 服务编排、migration 和健康检查；
- 管理员登录和会话；
- MinIO 原件、PostgreSQL 队列、worker、Qdrant 激活索引的完整上传链路；
- deterministic hash/TF 查询与摄取向量一致；
- LangGraph 问候、域外、紧急、检索、证据门控和拒答路由；
- SSE、处理轨迹、引用抽屉和运行模式标识；
- 中英文系统回答跟随最新用户消息；
- 未配置 evaluator 时 fail closed。

不能证明：

- 大语言模型回答质量；
- BGE-M3 embedding、reranker 或跨语言语义检索质量；
- 医学正确性、临床安全有效性或任何临床指标；
- 评估准确率、RAGAS、faithfulness 或 LLM Judge；
- TLS、备份恢复、生产鉴权、监控和容量能力。

## 3. 启动默认服务

```bash
cd "$HOME/work_project/epilepsy_qa_system"
export COMPOSE_DISABLE_ENV_FILE=1

docker compose --env-file config/compose.env.example config --quiet
docker compose --env-file config/compose.env.example config --services
docker compose --env-file config/compose.env.example up --build -d
docker compose --env-file config/compose.env.example ps --all
```

默认 services 应包含：

```text
postgres
minio
qdrant
migrate
api
worker
frontend
```

稳定后的预期状态：

| 服务 | 预期 |
| --- | --- |
| `postgres` | healthy |
| `minio` | healthy |
| `qdrant` | healthy |
| `api` | healthy |
| `worker` | Up |
| `frontend` | healthy |
| `migrate` | Exited (0) |

首次后端构建较慢时可使用：

```bash
docker compose --env-file config/compose.env.example build \
  --build-arg DEBIAN_MIRROR=https://mirrors.tuna.tsinghua.edu.cn \
  --build-arg PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple

docker compose --env-file config/compose.env.example up -d
```

以后日常启动只需 `up -d`。

## 4. 健康检查

```bash
curl -fsS http://127.0.0.1:8080/healthz
curl -fsS http://127.0.0.1:8010/health
curl -fsS http://127.0.0.1:8010/health/ready
```

默认 readiness 应满足：

- `status=ready`；
- `legacy_ready=true`；
- `chat_ready=true`；
- `chat_mode=demo`；
- `model_generation_enabled=false`；
- `admin_enabled=true`；
- `admin_ready=true`。

`model_generation_enabled=false` 是诚实的默认边界，不是故障。

入口：

| 功能 | 地址 |
| --- | --- |
| 聊天页面 | <http://127.0.0.1:8080/> |
| 管理后台 | <http://127.0.0.1:8080/admin/login> |
| Swagger | <http://127.0.0.1:8010/docs> |
| MinIO Console | <http://127.0.0.1:9001> |

## 5. 创建合成演示文档

在 WSL 中创建一份不含隐私的项目自建样例：

```bash
printf '%s\n' \
  'Project-authored synthetic demo evidence; no patient or private data.' \
  'During a seizure, a caregiver should record the seizure start time and keep the surrounding area clear.' \
  '' \
  '本项目自建合成演示证据，不含患者或私有数据。' \
  '癫痫发作时，家属应记录发作开始时间，清理周围危险物品并保持环境安全。' \
  > /tmp/epilepsy-demo.txt
```

不要使用真实病历或患者信息替代该文件。

## 6. 验证管理端自动摄取

打开 <http://127.0.0.1:8080/admin/login>，使用本地公开占位账号：

```text
用户名：CHANGE_ME_admin
密码：CHANGE_ME_admin_password
```

进入“文档摄取”：

1. 选择 `/tmp/epilepsy-demo.txt`；Windows 文件选择器可使用 `\\wsl.localhost\Ubuntu-20.04\tmp\epilepsy-demo.txt`；
2. 标题填写“项目自建双语合成演示证据”；
3. 类型选择“文献资料”；
4. 点击“上传并排队”；
5. 观察任务状态和进度。

正常流程：

```text
queued (0/3)
  -> running (通常 1/3)
  -> fetch
  -> parse
  -> chunk
  -> embed
  -> index
  -> finalize
  -> succeeded / 100%
```

默认 embed 阶段使用 `deterministic-md5-tf-v2`，不是 BGE-M3。最终成功表示 Qdrant points 已从 staging 切换为 active，可以被聊天检索。

若超过约 30 秒仍是 queued / attempts 0：

```bash
docker compose --env-file config/compose.env.example ps --all worker
docker compose --env-file config/compose.env.example logs --since=10m worker
```

默认 worker 应随 `up` 自动启动，不需要 profile 或模型文件。

## 7. 验证聊天路由

### 7.1 问候

依次输入：

```text
hello
你好
```

预期：

- 分别返回英文和中文问候；
- 完成原因是 greeting；
- 没有证据引用；
- 不进入检索或模型。

### 7.2 明显域外问题

输入：

```text
请帮我写一段 Python 代码
```

预期：

- 提示不属于癫痫循证问答范围；
- 出现 `OUT_OF_SCOPE`；
- 没有引用；
- 不调用知识库或模型。

### 7.3 英文证据问题

输入：

```text
During a seizure, what should a caregiver record and keep clear?
```

预期：

- 回答以 `[Deterministic demo mode]` 开始；
- 明确说明不是 LLM-generated；
- 摘录包含 `record the seizure start time`；
- 出现引用和证据抽屉；
- 英文免责声明只出现一次。

### 7.4 中文证据问题

输入：

```text
癫痫发作时，家属应记录什么并如何保持环境安全？
```

预期：

- 回答以 `【确定性 Demo 模式】` 开始；
- 明确说明“不是大语言模型生成”；
- 摘录包含“记录发作开始时间”；
- 系统说明和免责声明为中文；
- 证据抽屉包含刚上传的合成文档。

### 7.5 证据不足

询问与已上传内容无关、但仍属于癫痫领域的问题。若当前知识库没有其他资料，预期返回 `INSUFFICIENT_EVIDENCE`，而不是猜测结论。

默认检索是词法型确定性 Demo。英文资料与中文问题之间不保证跨语言语义召回。

## 8. 验证前端交互

- **查看证据**：检查标题、摘录、tier、score 和引用 ID；
- **查看处理轨迹**：检查 request route、retrieval、evidence gate、output policy；
- **停止生成**：可取消尚未完成的请求；
- **重新生成/重试**：重试最后一个公开错误或已取消请求；
- **清空会话**：只清当前标签页消息，不删除 Qdrant 证据；
- **运行模式**：默认必须显示“确定性 Demo · 非模型生成”。

## 9. 验证评估看板

进入“评估看板”。预期：

- 页面说明当前没有真实评估执行器；
- 创建表单和按钮禁用；
- 没有指标时显示“尚无真实评估器产生的聚合指标”；
- 历史任务存在时可以查看，但不能把旧值冒充本次运行结果。

评估看板不是聊天统计，也不是摄取页面。当前 API 会以 HTTP 409 拒绝创建新 evaluation job，避免永久 queued 或伪造指标。

可选的 public evaluation dry-run：

```bash
python scripts/run_public_evaluation.py \
  --base-url http://127.0.0.1:8010 \
  --model-id dry-run-not-a-model-result \
  --retriever-id dry-run-not-a-retriever-result \
  --build-id local-dry-run \
  --dry-run
```

该命令不发聊天请求，不验证 LLM、retriever 或临床质量。

## 10. 日志与排障

```bash
docker compose --env-file config/compose.env.example ps --all
docker compose --env-file config/compose.env.example logs --since=30m migrate
docker compose --env-file config/compose.env.example logs --since=30m api worker frontend
docker compose --env-file config/compose.env.example logs --since=30m postgres minio qdrant
```

常见现象：

| 现象 | 检查 |
| --- | --- |
| 上传长期 queued / 0 attempts | worker 是否 Up；查看 worker 日志 |
| job failed | 页面 error、worker 日志、MinIO/Qdrant 状态 |
| 聊天证据不足 | job 是否 succeeded；问题是否与文档同语言且有关键词重叠 |
| 管理员登录失败 | 可能复用了旧 PostgreSQL volume 和旧密码 |
| frontend 等待 | 先检查 API readiness 和 api 日志 |
| `migrate Exited (0)` | 正常成功，不需要重启 |

## 11. 真实模型和 BGE 边界

默认 Demo 不需要做本节。

真实回答生成需要用户先选择本地 7B/14B 或付费 API，再配置：

```text
CHAT_LLM_MODE=openai_compatible
DEEPSEEK_BASE_URL=...
DEEPSEEK_API_KEY=...
DEEPSEEK_MODEL=...
```

缺少非占位 Key、endpoint 或 model 时应启动失败。不要把真实 Key 提交到仓库，也不要未经安全评审把 Windows Ollama 暴露到所有网卡。

`worker-bge` 位于 `bge-ingestion` profile。它要求真实本地权重并在缺失时 fail closed，但只启动该 worker 不代表 API 查询 embedding 已完成兼容配置。默认 worker 和 worker-bge 不应同时消费队列；BGE 需要单独的端到端方案和验收。

## 12. 结束演示

保留数据库、对象和向量数据：

```bash
docker compose --env-file config/compose.env.example down
```

完全删除三个 named volume 的命令是：

```bash
docker compose --env-file config/compose.env.example down -v
```

后者具有破坏性，只能在确认全部本地数据可丢弃时执行。

## 13. 演示完成判定

- [ ] `migrate` 为 Exited (0)
- [ ] postgres/minio/qdrant/api/frontend healthy
- [ ] worker Up
- [ ] readiness 为 ready，chat mode 为 demo
- [ ] 管理上传从 queued 自动到 succeeded
- [ ] 中英文证据问题分别返回对应语言
- [ ] hello/你好无引用
- [ ] 域外问题无引用并返回 out-of-scope
- [ ] 默认回答明确“非模型生成”
- [ ] 评估创建入口禁用
- [ ] 已向观众说明真实 LLM、BGE 和临床效果均未由默认 Demo 证明

更面向新手的解释见 [中文新手使用指南](../BEGINNER_RUN_GUIDE.md)。
