# Security Policy / 安全策略

## 负责任披露

请不要在公开 Issue、讨论区、截图、日志或演示中发布可利用细节、secret、cookie、患者信息、私有文档或未修复漏洞。

优先使用代码托管平台的 **Private vulnerability reporting / Security Advisory**（若仓库已启用），或维护者公开列出的其他私密安全渠道。当前文档未列专用安全邮箱；若私密渠道不可用，请只创建不含技术细节的公开 Issue，请求维护者提供私密联系方式。

报告建议包含：

- 受影响 commit、Compose image tag，以及部署者独立记录的 image digest（如有）；
- 最小复现步骤、前置权限和影响；
- 已脱敏的请求/响应；
- 建议缓解方式；
- 报告者希望如何署名。

仓库镜像目前固定明确版本 tag，但没有固定 image digest。不要把 tag 当作不可变供应链标识。

不要发送真实患者数据或生产 secret。请使用 synthetic 示例和占位符。项目不承诺固定响应 SLA；维护者应限制传播范围，先复现与分级，再协商修复和披露时间。

## 安全范围

优先报告以下问题：

- 管理认证绕过、session 劫持、cookie scope 或 CORS 缺陷；
- 任意文件读取/写入、路径穿越、上传类型绕过或对象 key 泄露；
- PostgreSQL、MinIO、Qdrant 或模型 API 凭据泄露；
- worker lease 绕过、跨任务接管或重复执行导致的数据破坏；
- staging 数据被检索、active 切换错误或跨存储补偿失效；
- SSE 中泄露内部 context、secret、隐藏 reasoning 或私有标识；
- public eval 隔离绕过，尤其访问 `data`、PDF、private/benchmark/with-answers 输入；
- 依赖供应链、构建产物或容器配置导致的可利用风险。

一般功能 bug、文档错别字和不含安全影响的模型质量问题可走普通 Issue。第三方服务自身漏洞也应遵循其上游披露政策。

## 医疗与数据安全边界

本项目不是医疗器械，不替代医生、药师或急救服务。模型或 mock 输出不得用于确诊、个体化处方、剂量调整或自行停药。持续发作、反复发作、呼吸困难、受伤或意识未恢复等情况应立即联系当地急救服务。

- 不要把真实患者身份信息、病历、处方或联系方式放入 prompt、测试、Issue、日志或公开评测。
- `public_eval/` 的 6 条样本是项目自建 synthetic smoke data，只能验证有限契约。
- corpus `active` 表示通过工程门禁，不代表内容医学正确、最新、适合个体患者，也不是法律许可意见。
- 第三方文章、上传文档、模型输出和 mock 输出均是不可信输入。
- 任何面向真实用户的部署都需要独立的临床、安全、隐私、红队和合规评审。

## Compose 与 secret 管理

仓库已有 `docker-compose.yml`。默认服务为 `postgres`、`minio`、`qdrant`、一次性 `migrate`、`api` 和 `frontend`；`worker` 只在 `ingestion` profile 中启用。所有发布端口均绑定 loopback：frontend `127.0.0.1:8080`、API `127.0.0.1:8010`、PostgreSQL `127.0.0.1:5432`、MinIO API/Console `127.0.0.1:9000/9001`、Qdrant `127.0.0.1:6333`。Loopback 降低了默认暴露面，但不等于生产网络加固。

每条 Compose 命令都必须保留显式环境文件，例如：

```bash
docker compose --env-file config/compose.env.example config --quiet
docker compose --env-file config/compose.env.example up --build -d
```

- 不得省略 `--env-file config/compose.env.example`，也不得让 Compose 隐式读取仓库根 `.env`。
- `config/compose.env.example` 的 `CHANGE_ME_*` 仅适用于隔离的本地 demo；不得用于共享环境或生产，也不得在该文件写入真实生产 secret。
- 不要在 shell history、CI 日志、浏览器截图或评测结果中输出 secret。
- PostgreSQL、MinIO、Qdrant 与 provider 应使用不同、最小权限凭据并有独立轮换流程。
- `ADMIN_BOOTSTRAP_USERNAME` 与 `ADMIN_BOOTSTRAP_PASSWORD` 只用于首次建用户；改变 bootstrap password 不会更新已有管理员。
- 紧急情况下应撤销管理 sessions、轮换相关凭据并审查访问日志。

## 默认 mock 与 provider 边界

默认 `api` 服务执行 Dockerfile 的 `/opt/container/serve-existing-mock`，把现有 deterministic mock 接到 streaming chat port。它要求 `MOCK_MODE=true`，所以本地演示不需要 provider key；这只是 mock contract，**不是 DeepSeek、OpenAI-compatible provider 或任何模型效果证据**。

只设置 `MOCK_MODE=false` 不会切换真实 provider，反而会让默认 container command 拒绝启动。真实 provider 接入必须通过受审查的 command/service override，明确 endpoint/key、失败语义、日志脱敏和验收测试。本仓库没有发布经过验证的真实 provider override。

## Web 与管理面基线

- 示例 Compose 为本地 demo 设置 `ENABLE_ADMIN_API=true`、`ADMIN_COOKIE_SECURE=false`；不得把这两个值沿用到受信或公网部署。
- 生产应只通过 HTTPS 暴露管理面，并设置 `ADMIN_COOKIE_SECURE=true`。
- 当前 cookie 为 `HttpOnly`、`SameSite=Strict`、Path `/api/v1/admin`，默认 TTL 1800 秒；反向代理不得扩大 Path 或记录 cookie。
- `CORS_ORIGINS` 只列明确可信 origin，不使用通配符。
- 限制管理 API 的网络入口、上传大小、对象 bucket 权限和数据库角色。
- SSE/代理应禁用缓冲并设置超时，但不得把内部异常、隐藏 reasoning 或 key 返回客户端。

## 存储与 worker 基线

- PostgreSQL 是 job、lease 和 document 状态的权威来源；限制直接写权限。
- MinIO bucket 不应公开；示例 Console 位于 `127.0.0.1:9001`，只适合本地管理。
- Qdrant 只允许受信网络访问；检索必须过滤 `index_visibility=active`。
- worker 使用唯一 ID、短期 lease 和 heartbeat；时钟偏差会影响 lease 判定。
- `worker` 默认不启动。启用 `ingestion` profile 时，`EMBED_MODEL_PATH` 必须是宿主机绝对目录，并只读挂载到 `/models/bge-m3`。
- 模型目录、权重和 `config.json` 通过启动检查仍不等于真实推理验收；fallback 结果不得标注为 BGE。
- 不要手工把 staging points 改为 active；跨存储故障应按 document/job ID 精确对账。

## 已验证内容与明确缺口

已记录的本地 Compose 验收包括：`migrate` 成功完成 Alembic upgrade，`postgres`、`minio`、`qdrant`、`api`、`frontend` 五个长期服务达到 `healthy`，opt-in integration 为 **6/6 passed**。

该 integration suite 覆盖真实 PostgreSQL、MinIO、Qdrant，以及使用注入 deterministic parser/embedder 的进程内 `WorkerRunner` contracts。它不证明：

- `worker` 容器可运行；
- BGE-M3 artifact 已加载或执行真实 embedding/rerank；
- DeepSeek 或其他 provider 已调用；
- 备份与恢复可用；
- TLS、secret store、网络策略、最小权限、监控或其他生产加固已完成。

其他已知限制：

- `/health/ready` 是应用级 readiness，不是 DeepSeek/BGE 或完整外部依赖验收。
- evaluation worker 默认 fail closed 为 `EVALUATION_NOT_CONFIGURED`。
- PostgreSQL、MinIO 与 Qdrant 之间采用补偿式最终一致性，不是分布式事务。
- Qdrant schema 不兼容时需要受控迁移，不应自动破坏旧 collection。
- 当前没有受支持的管理员改密 API。

## 备份、恢复与安全更新

备份/恢复流程和生产灾难恢复**未在本次 Compose 验收中实测**。部署者必须在隔离环境建立覆盖 PostgreSQL、MinIO、Qdrant 与配置元数据的一致性方案，执行恢复演练并记录 RPO/RTO；在此之前不得宣称可恢复。

仓库没有正式版本支持矩阵。安全修复以维护者明确发布的 commit 或版本为准；部署者应记录实际镜像 digest、关注上游公告，并在隔离环境验证更新。第三方依赖的许可证与安全信息见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
