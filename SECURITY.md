# Security Policy / 安全策略

## 负责任披露

请不要在公开 Issue、讨论区、截图、日志或演示中发布可利用细节、secret、cookie、患者信息、私有文档或未修复漏洞。

优先使用代码托管平台的 Private vulnerability reporting / Security Advisory（若仓库已启用），或维护者公开列出的其他私密安全渠道。当前文档未列专用安全邮箱；若私密渠道不可用，请只创建不含技术细节的公开 Issue，请求维护者提供私密联系方式。

报告建议包含：

- 受影响 commit、Compose image tag，以及部署者独立记录的 image digest；
- 最小复现步骤、前置权限和影响；
- 已脱敏的请求/响应；
- 建议缓解方式；
- 报告者希望如何署名。

仓库镜像使用明确版本 tag，但没有固定 image digest。不要把 tag 当作不可变供应链标识。不要发送真实患者数据或生产 secret；只使用 synthetic 示例和占位符。

## 安全范围

优先报告：

- 管理认证绕过、session 劫持、cookie scope 或 CORS 缺陷；
- 任意文件读取/写入、路径穿越、上传类型绕过或对象 key 泄露；
- PostgreSQL、MinIO、Qdrant 或模型 API 凭据泄露；
- worker lease 绕过、跨任务接管或重复执行导致的数据破坏；
- staging 数据被检索、active 切换错误或跨存储补偿失效；
- SSE 中泄露内部 context、secret、hidden reasoning 或私有标识；
- public eval 隔离绕过，尤其访问 `data`、PDF、private/benchmark/with-answers 输入；
- 依赖供应链、构建产物或容器配置导致的可利用风险。

一般功能 bug、文档错别字和不含安全影响的模型质量问题可走普通 Issue。第三方服务自身漏洞应遵循其上游披露政策。

## 医疗与数据安全边界

本项目不是医疗器械，不替代医生、药师或急救服务。模型或 Demo 输出不得用于确诊、个体化处方、剂量调整或自行停药。持续发作、反复发作、呼吸困难、受伤或意识未恢复等情况应立即联系当地急救服务。

- 不要把真实患者身份信息、病历、处方或联系方式放入 prompt、上传、测试、Issue、日志或公开评测；
- `public_eval/` 的 synthetic smoke data 只能验证有限 contract；
- corpus `active` 表示通过工程门禁，不代表医学正确、最新、适合个体患者或法律许可意见；
- 第三方文章、上传文档、模型输出和确定性 Demo 输出均是不可信输入；
- 任何面向真实用户的部署都需要独立的临床、安全、隐私、红队和合规评审。

## Compose 与 secret 管理

默认服务为 `postgres`、`minio`、`qdrant`、一次性 `migrate`、`api`、`worker` 和 `frontend`；`worker-bge` 只在 `bge-ingestion` profile 中启用。所有发布端口绑定 loopback：frontend `127.0.0.1:8080`、API `127.0.0.1:8010`、PostgreSQL `127.0.0.1:5432`、MinIO API/Console `127.0.0.1:9000/9001`、Qdrant `127.0.0.1:6333`。Loopback 降低默认暴露面，但不等于生产网络加固。

每条 Compose 命令必须显式指定环境文件：

```bash
export COMPOSE_DISABLE_ENV_FILE=1
docker compose --env-file config/compose.env.example config --quiet
docker compose --env-file config/compose.env.example up --build -d
```

- 不得让 Compose 隐式读取仓库根 `.env`；
- `config/compose.env.example` 的 `CHANGE_ME_*` 只适用于隔离本地 Demo；
- 真实 provider 配置应存放在 Git 忽略的本地环境文件，backend key 不得进入前端、仓库或日志；
- 不要在 shell history、CI 日志、浏览器截图或评测结果中输出 secret；
- PostgreSQL、MinIO、Qdrant 与 provider 应使用不同、最小权限凭据并有独立轮换流程；
- bootstrap 管理员只在不存在时创建；修改环境变量不会轮换已有密码；
- 紧急情况下应撤销管理 sessions、轮换相关凭据并审查访问日志。

## 默认 Demo 与真实 provider 边界

默认 API 使用标准 Uvicorn 入口，`app.main` 根据 `CHAT_LLM_MODE` 选择 adapter。默认 `CHAT_LLM_MODE=demo` 使用 `DeterministicEvidenceLLMStreamAdapter`：它不调用大语言模型，只展示与问题词法相关的本地 evidence excerpts，并明确标注“非模型生成”。该行为不是 DeepSeek、OpenAI-compatible provider 或任何模型效果证据。

真实生成必须显式设置：

```text
CHAT_LLM_MODE=openai_compatible
DEEPSEEK_BASE_URL=...
DEEPSEEK_API_KEY=<backend-only, non-empty, not EMPTY>
DEEPSEEK_MODEL=...
```

缺少非占位 backend key 时应用 fail closed。不要自动下载模型、索要用户 Key、产生 API 费用，或未经安全评审把本地模型服务监听到所有网卡。`MOCK_MODE` 仍控制 legacy query rewrite/embedding fallback，不能用于推断聊天是否为真实模型。

## Web 与管理面基线

- 示例 Compose 为本地 Demo 设置 `ENABLE_ADMIN_API=true`、`ADMIN_COOKIE_SECURE=false`；不得沿用到受信或公网部署；
- 生产应只通过 HTTPS 暴露管理面，并设置 secure cookie；
- 当前 cookie 为 `HttpOnly`、`SameSite=Strict`、Path `/api/v1/admin`，默认 TTL 1800 秒；
- `CORS_ORIGINS` 只列明确可信 origin，不使用通配符；
- 限制管理 API 网络入口、上传大小、对象 bucket 权限和数据库角色；
- SSE/代理应禁用缓冲并设置超时，但不得返回内部异常、hidden reasoning 或 key。

## 存储与 worker 基线

- PostgreSQL 是 job、lease 和 document 状态的权威来源，限制直接写权限；
- MinIO bucket 不应公开；示例 Console 只适合本地管理；
- Qdrant 只允许受信网络访问；检索必须过滤 `index_visibility=active`；
- default worker 自动启动，使用唯一 ID、lease 和 heartbeat；时钟偏差会影响 lease；
- default worker 显式使用 `deterministic-md5-tf-v2`，不得称为 BGE；
- `worker-bge` 需要只读模型目录、`config.json` 和顶层权重，缺失时 exit 64；
- default worker 和 worker-bge 不得同时消费同一队列；
- BGE 文件预检、容器启动或 job 成功都不单独证明端到端 BGE query/ingestion 兼容；
- 不要手工把 staging points 改为 active；跨存储故障应按 document/job ID 精确对账。

## 评估边界

默认 `EVALUATION_RUNNER_ENABLED=false`：

- UI 禁用创建入口；
- API 创建 evaluation job 返回 HTTP 409；
- default worker 不 claim evaluation job；
- 不生成硬编码或伪造指标；
- 历史列表和 summary 只展示已有 aggregate metadata。

评估看板不是聊天流量统计。`public_eval --dry-run`、legacy lexical endpoint 和未来 controlled evaluator 是不同 contract，不能混用名称或结果。

## 已验证内容与明确缺口

当前本地验收包括：

- migration 成功，默认基础设施/API/frontend healthy，worker Up；
- 管理端 synthetic TXT 经过 default worker 在一次尝试后完成；
- Qdrant active point 标记 `embedding_backend=deterministic-md5-tf-v2`；
- 中英文问候、域外路由和证据回答通过真实 SSE 验证；
- evaluation 创建被 HTTP 409 拒绝；
- 后端 165 项 unit tests、前端 15 个 test files / 46 项 tests 通过，typecheck/lint 通过。

这些结果不证明：

- BGE-M3 artifact 已完成 API + worker 端到端推理；
- DeepSeek/Ollama/vLLM 或其他 provider 的质量；
- 真实 PDF、私有语料或临床内容质量；
- 备份恢复、TLS、secret store、网络策略、最小权限、监控或生产加固；
- 任何 RAG、模型或临床准确率。

其他限制：

- `/health/ready` 是 runtime readiness，不是 provider/BGE/医学质量验收；
- PostgreSQL、MinIO 与 Qdrant 使用补偿式最终一致性，不是分布式事务；
- Qdrant schema 不兼容时需要受控迁移，不应自动破坏旧 collection；
- 当前没有受支持的管理员改密 API。

## 备份、恢复与安全更新

跨 PostgreSQL、MinIO、Qdrant 的一致备份恢复流程尚未完成生产验收。部署者必须在隔离环境定义一致性点、执行恢复和跨存储对账、记录 RPO/RTO；完成前不得宣称可恢复。

仓库没有正式版本支持矩阵。部署者应记录实际镜像 digest、关注上游公告，并在隔离环境验证更新。第三方依赖的许可证与安全信息见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
