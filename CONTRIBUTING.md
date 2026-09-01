# 贡献指南

感谢参与。本项目涉及医疗主题、第三方文章、模型服务和多存储一致性；贡献必须优先保证事实可追溯、默认安全和可复现，不能用演示结果冒充临床或模型验收。

## 1. 开发环境

### 后端

`pyproject.toml` 严格要求 **Python 3.11.x**：

```bash
python3.11 --version
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e '.[dev]'
```

需要真实解析、embedding、Qdrant 或模型 adapter 时再安装：

```bash
python -m pip install -e '.[runtime,dev]'
```

`/v1/eval/ragas` 是为旧客户端保留的兼容 URL；它执行项目内置、离线且确定性的 lexical context-overlap 聚合，不加载 Ragas 或其他 evaluation extra。

不要为了修文档或普通单测安装不需要的重型依赖。所有声明依赖均为 exact pin；新增依赖也必须固定版本、解释必要性，并更新 `THIRD_PARTY_NOTICES.md`。

### 前端

前端要求 Node `>=20 <21`，仓库 `.nvmrc` 为 `20.11.0`，package manager 为 npm `10.2.4`：

```bash
cd frontend
nvm use
npm ci
```

`npm ci` 必须使用现有 lockfile；不要用会静默重写依赖范围的命令。

## 2. 仓库边界

- `app/` 是唯一后端；不要创建第二套 `backend/` 或复制业务实现。
- `frontend/` 通过相对 `/api`、`/health` 调用后端。
- PostgreSQL 是文档/job/lease 状态权威源，MinIO 保存原始对象，Qdrant 只暴露 active points。
- 管理与 worker 变更必须保持幂等、lease owner 校验、staging/active 隔离和补偿路径。
- schema 变化必须新增 Alembic revision；不得依赖应用启动时隐式建表。
- 不要在生产环境增加本地 store 或 mock 的静默 fallback。

## 3. 数据、评测与医疗表述

禁止在贡献中提交：

- 真实患者数据、可识别病历或未获授权文档；
- 根 `.env`、secret、cookie、私有对象 key；
- 私有答案、`eval_with_answers`、benchmark 私有数据或从 corpus 生成的答案；
- 无法证明再分发权利的第三方正文、PDF、模型权重或评测输出。

`public_eval/` 只能包含项目自建、允许公开的 synthetic 数据。dry-run 只能描述为 schema/hash/output-shape 校验；任何真实指标必须附运行配置、数据版本、分母、失败数和 operator attestation，且不得外推为临床效果。

corpus 的 allowlist 是工程门禁，不是法律判断。新增来源需记录 provenance、条目级许可、获取条款与删除流程，并由有权限的人独立复核。

文档和 UI 不得给出确诊、个体处方、剂量调整或自行停药指令。紧急情况应引导联系当地急救服务。

## 4. 质量命令

从仓库根执行后端检查：

```bash
python -m ruff check app tests scripts
python -m mypy app tests
python -m pytest
python -m pytest --cov=app --cov-report=term-missing
```

`pyproject.toml` 的 pytest 使用 strict config/markers；mypy 目标为 `app`、`tests`；Ruff 目标 Python 为 3.11。若某个 runtime 集成需要外部服务，请用 marker 或显式环境开关，默认测试必须离线、确定且 fail closed。

公开评测契约的离线检查：

```bash
python scripts/run_public_evaluation.py \
  --base-url http://127.0.0.1:8010 \
  --model-id dry-run-not-a-model-result \
  --retriever-id dry-run-not-a-retriever-result \
  --build-id contributor-dry-run \
  --dry-run
```

前端检查：

```bash
cd frontend
npm ci
npm run typecheck
npm run lint
npm run format:check
npm test
npm run build
```

涉及单个模块时可先跑定向测试，但合并前应跑相关完整检查。不能运行的检查要在变更说明中写明原因和替代验证，不要写“应当通过”。

## 5. 测试要求

- bug fix 先添加能复现问题的测试，再修复；
- API 变更覆盖成功、认证失败、边界值、错误码和敏感信息不泄露；
- admin 变更覆盖 cookie Path/Secure/SameSite、session revoke 和 CORS；
- worker 变更覆盖 claim 竞争、lease 续租/失租、取消、重试上限、崩溃窗口与补偿失败；
- Qdrant 变更覆盖 schema guard、staging 不可见、point count mismatch 和 active 切换；
- 上传变更覆盖大小、扩展名/MIME/signature、UTF-8、幂等竞争和 MinIO 回滚；
- public eval 测试不得访问应用 settings、dotenv、私有路径或输出样本内容；
- 前端变更覆盖 loading/error/auth redirect、SSE 断流和可访问性。

测试日志使用 synthetic 占位符，严禁打印 key、cookie、完整 prompt/context 或上传正文。

## 6. 代码与文档风格

- Python 遵循 Ruff、mypy 和现有分层；公开接口加类型。
- TypeScript 保持 strict 类型，不用 `any` 绕过契约。
- 错误面向客户端返回稳定 code 和 support ID；内部异常只进入受控日志。
- 中文文档为主，命令优先适配 Linux/WSL。
- 新命令必须说明 cwd、依赖、是否联网、是否会写数据以及回滚方式。
- 架构或运维行为变化时同步更新 `Readme.md`、`docs/ARCHITECTURE.md`、`docs/RUNBOOK.md`、`docs/DEMO.md`。
- 不添加未经复现的性能、准确率、安全率、RAGAS、临床或模型验收数字。

## 7. 数据库与跨存储变更

数据库变更流程：

1. 更新 SQLAlchemy model；
2. 新增可升级/可回退的 Alembic revision；
3. 测试空库 upgrade 和已有数据 upgrade；
4. 说明锁表、停机和回滚条件；
5. 更新备份恢复步骤。

跨存储流程必须明确 PostgreSQL、MinIO、Qdrant 各自的提交点。不得把多个系统描述为一个事务；为每个失败窗口设计幂等重放、精确清理和 orphan 对账。删除操作必须限定 document/job/collection/bucket，不得默认全量 clear。

## 8. 变更提交检查表

提交评审前确认：

- [ ] 变更范围最小，没有复制第二套后端；
- [ ] 没有 secret、患者数据、私有答案、未授权正文或大模型权重；
- [ ] 依赖仍为 exact pin，第三方 notice 已更新；
- [ ] 相关后端/前端检查已通过并记录；
- [ ] migration、备份、回滚和兼容性影响已说明；
- [ ] admin/worker/storage 安全不变量有测试；
- [ ] 指标有数据版本、分母和限制，没有虚假模型或临床结论；
- [ ] 文档命令适用于 Linux/WSL，不隐式读取根 `.env`；
- [ ] Compose 命令显式 `--env-file`，且 service 名和端口来自实际 Compose 文件；
- [ ] 对用户可见的医疗免责声明和紧急边界仍然清晰。

安全漏洞不要走公开评审，按 [SECURITY.md](SECURITY.md) 私下披露。