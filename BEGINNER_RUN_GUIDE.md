# 小白运行文档（Beginner Run Guide）

本文档面向第一次接触本项目的同学，目标是让你在最短时间内：
- 看懂目录和文件职责
- 跑起服务并完成一次问答
- 知道“改参数/改地址/改模型”要改哪个文件

---

## 1. 项目是什么

这是一个基于 Agentic RAG 的癫痫专科问答与检索后端，核心能力：
- 用户提问后先做意图路由（文献检索 / 临床匹配 / 混合）
- 走混合检索（Dense + Sparse）并重排
- 调用大模型生成结构化答案
- 提供 deterministic lexical 检索上下文诊断兼容接口，以及独立的 LLM-as-a-Judge 接口

> **当前评估实现（重要）**：`POST /v1/eval/ragas` 仅保留为 legacy compatibility URL；当前未安装、也未运行 Ragas。响应元数据为 `backend=deterministic_lexical`、`metric_version=token_overlap_v1`、`aggregation=macro_average`。每个样本只比较 `ground_truth` 与 `retrieved_contexts`：兼容字段 `context_precision` 表示 context-hit ratio（命中的 retrieved context 比例），`context_recall` 表示 ground-truth token coverage（检索上下文覆盖的 ground-truth token 比例），最终按样本做宏平均。`response` 不参与计算。这些字段不代表 Ragas 或 faithfulness，也不能证明答案事实正确性、临床安全或临床效果。LLM Judge 是另一条独立路径，不应与该 lexical 结果合并解读。

┌─────────────────────────────────────────────────────┐
│                   癫痫智能问诊系统                    │
├─────────────────────────────────────────────────────┤
│  用户提问 "癫痫夜间发作怎么办？"                     │
│         ↓                                           │
│  FastAPI 接收请求                                    │
│         ↓                                           │
│  LangGraph 调度工作流                                 │
│         ↓                                           │
│  意图判断：临床问诊 → 检索临床文档                    │
│         ↓                                           │
│  混合检索 (Dense + Sparse)                          │
│         ↓                                           │
│  BGE 重排序                                         │
│         ↓                                           │
│  LLM 生成答案 + 安全检查                             │
│         ↓                                           │
│  返回答案给用户                                      │
└─────────────────────────────────────────────────────┘
---

## 2. 目录结构总览

```text
epilepsy_qa_system/
├─ app/                           # 主应用代码
│  ├─ main.py                     # FastAPI 路由入口
│  ├─ service.py                  # 业务编排（问答、入库、评估）
│  ├─ workflow.py                 # LangGraph 工作流
│  ├─ config.py                   # 配置读取（.env）
│  ├─ schemas.py                  # 请求/响应数据模型
│  ├─ prompts.py                  # 路由/回答/评估提示词
│  ├─ utils.py                    # 通用工具函数
│  ├─ llm/
│  │  ├─ llm_client.py            # 大模型调用封装
│  │  └─ llm_judge.py             # LLM-as-a-Judge 评估器
│  ├─ retrieval/
│  │  ├─ mineru_pipeline.py       # 文档解析（MinerU + PDF fallback）
│  │  ├─ chunking.py              # 父子分块（Parent-Child）
│  │  ├─ embeddings.py            # 向量编码（BGE-M3风格）
│  │  ├─ vector_store.py          # 向量库封装（InMemory/Qdrant）
│  │  ├─ retriever.py             # 混合召回 + 查询改写
│  │  └─ reranker.py              # 精排器
│  └─ evaluation/
│     └─ evaluation.py            # deterministic lexical 兼容评估（非 Ragas）
├─ scripts/
│  ├─ ingest_demo.py              # 演示入库脚本
│  ├─ run_eval_demo.py            # 演示评估脚本
│  └─ vllm_start_commands.ps1     # vLLM 启动命令模板
├─ docs/
│  └─ PROJECT_DELIVERABLES.md     # 五阶段项目交付说明
├─ .env.example                   # 环境变量模板
├─ requirements.txt               # 依赖列表
├─ run_server.py                  # 本地启动入口
├─ Readme.md                      # 项目简版说明
└─ BEGINNER_RUN_GUIDE.md          # 当前文档
```

---

## 3. 一分钟理解运行模式

你有两种运行方式：

1. `MOCK_MODE=true`（推荐新手先用）
- 不依赖真实 vLLM / Qdrant
- 启动快，方便确认链路和接口是通的

2. `MOCK_MODE=false`
- 使用真实模型与检索组件
- 需要先启动 vLLM（可选 Qdrant）

---

## 4. 从零运行（新手最稳步骤）

## 4.1 环境准备
- Python 3.10+（建议 3.10/3.11）
- Windows PowerShell（当前项目已按 PowerShell 示例）

## 4.2 安装依赖

```powershell
pip install -r requirements.txt
```

## 4.3 创建配置文件

```powershell
Copy-Item .env.example .env
```

> 首次建议保持 `.env` 里 `MOCK_MODE=true`，先跑通再切真实模型。

## 4.4 启动服务

```powershell
python run_server.py
```

启动成功后默认地址：
- API: `http://127.0.0.1:8010`
- Swagger 文档: `http://127.0.0.1:8010/docs`

## 4.5 快速验证

浏览器访问：
- `http://127.0.0.1:8010/health`

或命令行测试问答：

```powershell
curl -X POST "http://127.0.0.1:8010/v1/ask" `
  -H "Content-Type: application/json" `
  -d "{\"question\":\"How to manage increasing nocturnal seizures?\",\"with_trace\":true}"
```

---

## 5. 常用接口怎么用

1. 问答接口
- `POST /v1/ask`
- 入参文件定义：`app/schemas.py` -> `AskRequest`

2. 文本入库
- `POST /v1/ingest/text`
- 入参文件定义：`app/schemas.py` -> `IngestTextRequest`

3. 文件入库（PDF/TXT/MD）
- `POST /v1/ingest/file`
- 解析链路：`app/retrieval/mineru_pipeline.py`

4. Legacy lexical 兼容评估
- `POST /v1/eval/ragas`（仅为 legacy compatibility URL，不运行 Ragas）
- 实际逻辑：`app/evaluation/evaluation.py` 中的 `deterministic_lexical` / `token_overlap_v1`
- 只比较 `ground_truth` 与 `retrieved_contexts` 并做样本宏平均；`response` 不计分

5. LLM Judge 评估
- `POST /v1/eval/judge`
- 评估器：`app/llm/llm_judge.py`

---

## 6. 参数和地址该改哪里（最常用）

核心原则：
- 绝大部分参数都改 `.env`
- 代码默认值在 `app/config.py`

### 6.1 服务地址和端口
- 改文件：`.env`
- 关键参数：
  - `HOST=0.0.0.0`
  - `PORT=8010`
- 读取位置：`app/config.py`
- 启动入口：`run_server.py`

### 6.2 模型地址和模型名（vLLM）
- 改文件：`.env`
- 关键参数：
  - `LLM_API_BASE=http://127.0.0.1:8000/v1`
  - `LLM_API_KEY=EMPTY`
  - `LLM_MODEL=DeepSeek-R1-Distill-Qwen-32B-AWQ`
- vLLM 启动命令模板：`scripts/vllm_start_commands.ps1`

### 6.3 是否启用真实组件
- 改文件：`.env`
- 关键参数：
  - `MOCK_MODE=true/false`
  - `USE_QDRANT=true/false`

### 6.4 Qdrant 地址
- 改文件：`.env`
- 关键参数：
  - `QDRANT_URL=http://127.0.0.1:6333`
  - `QDRANT_API_KEY=`
  - `QDRANT_COLLECTION=epilepsy_hybrid_docs`

### 6.5 检索效果相关参数
- 改文件：`.env`
- 常改项：
  - `DENSE_TOP_K`
  - `SPARSE_TOP_K`
  - `FINAL_TOP_K`
  - `HYBRID_DENSE_WEIGHT`
  - `HYBRID_SPARSE_WEIGHT`
  - `RERANKER_TOP_K`

### 6.6 生成效果相关参数
- 改文件：`.env`
- 常改项：
  - `LLM_TEMPERATURE`
  - `LLM_MAX_TOKENS`
  - `MAX_CONTEXT_CHARS`

### 6.7 安全边界开关
- 改文件：`.env`
- 关键参数：
  - `ALLOW_UNVERIFIED_MEDICAL_ADVICE=false`

### 6.8 提示词内容（路由、回答、评估）
- 改文件：`app/prompts.py`
- 说明：如果你要改回答风格、引用格式、评估标准，优先改这个文件

---

## 7. 改功能时该看哪些文件

1. 改 API 路由或新增接口
- `app/main.py`

2. 改业务逻辑（问答主流程）
- `app/service.py`
- `app/workflow.py`

3. 改检索策略
- `app/retrieval/retriever.py`
- `app/retrieval/vector_store.py`
- `app/retrieval/reranker.py`

4. 改分块策略
- `app/retrieval/chunking.py`

5. 改文档解析方式
- `app/retrieval/mineru_pipeline.py`

6. 改评估逻辑
- `app/evaluation/evaluation.py`
- `app/llm/llm_judge.py`

---

## 8. 切换到真实模型（标准流程）

1. 启动 vLLM（参考 `scripts/vllm_start_commands.ps1`）
2. 修改 `.env`：
- `MOCK_MODE=false`
- `LLM_API_BASE` 指向你的 vLLM 地址
- `LLM_MODEL` 与 vLLM `served-model-name` 保持一致
3. （可选）启动 Qdrant 并设置：
- `USE_QDRANT=true`
- `QDRANT_URL` 改成你的地址
4. 重启服务：

```powershell
python run_server.py
```

---

## 9. 常见问题排查

1. 报错 `ModuleNotFoundError`
- 先执行：`pip install -r requirements.txt`

2. 端口被占用
- 把 `.env` 里的 `PORT` 改成其他端口（比如 `8011`），重启

3. 请求很快但回答像模板
- 检查 `.env` 是否仍是 `MOCK_MODE=true`

4. 连接不上模型
- 检查 `LLM_API_BASE` 是否可访问
- 检查 vLLM 是否已启动且模型名一致

5. 检索结果太少
- 提高 `DENSE_TOP_K` / `SPARSE_TOP_K` / `FINAL_TOP_K`
- 检查是否已经完成入库（`/health` 的 `kb_count`）

---

## 附：完整中文 curl 示例
- docs/API_CURL_EXAMPLES_CN.md

## 10. 推荐你的调试顺序

1. 先 `MOCK_MODE=true` 跑通全部接口
2. 再接入真实 vLLM
3. 最后接入 Qdrant 和真实文档入库
4. 分开做接口检查：用 legacy `/v1/eval/ragas` 观察 ground truth 与 contexts 的 lexical overlap，用 `/v1/eval/judge` 走独立 Judge 路径

不要把第 4 步称为“效果验证”：legacy endpoint 忽略 `response`，不能验证生成答案、事实正确性、临床安全或临床效果。

这样最不容易卡住。
