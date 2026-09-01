# Project Deliverables (Five Stages)
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

## Stage 1: 系统架构与模块划分
1. 数据流转：

   - 用户请求进入 `/v1/ask` 接口
   - 意图路由器（Intent router）决定走向 `literature`（文献）、`clinical`（临床）或 `both`（两者兼有）分支
   - 分支检索执行混合召回
   - 重排器（Reranker）对候选内容进行精排
   - 大语言模型（LLM）生成结构化答案
   - 护栏（Guardrail）附加安全边界

2. LangGraph 路由逻辑：

   - 节点设置：`route_intent -> retrieve_* -> generate_answer -> post_guard`
   - 条件边根据意图进行路由跳转
      用户 POST /v1/ask
               ↓
         main.py: ask()
               ↓
         service.py: service.ask()
               ↓
         workflow.py: workflow.run()
               ↓
   ┌─────────────────────────────────────────────┐
   │ LangGraph 工作流执行：                       │
   │  1. route_intent → 判断意图 (literature/    │
   │     clinical/both)                          │
   │  2. retrieve_xxx → 检索知识库               │
   │  3. generate_answer → LLM 生成答案           │
   │  4. post_guard → 安全检查 + 免责声明        │
   └─────────────────────────────────────────────┘
               ↓
            service.py: 组装 AskResponse
               ↓
            返回给用户

## Stage 2: Core Pipeline Logic

               用户问题: "癫痫夜间发作频繁怎么办？"
                        │
                        ▼
┌──────────────────────────────────────────────────────────┐
│              第1步：查询改写 (Query Rewrite)              │
│  "癫痫夜间发作频繁怎么办？"                                │
│       ↓ LLM改写                                          │
│  ["癫痫夜间发作频繁怎么办？",                              │
│   "seizure disorder nocturnal management",               │
│   "癫痫夜间急性处理方案"]                                  │
└──────────────────────────────────────────────────────────┘
                        │
                        ▼
┌──────────────────────────────────────────────────────────┐
│              第2步：向量化 (Embedding)                    │
│  每个查询变 → Dense向量 + Sparse向量                      │
└──────────────────────────────────────────────────────────┘
                        │
                        ▼
┌──────────────────────────────────────────────────────────┐
│           第3步：混合检索 (Hybrid Search)                 │
│  Dense检索 (0.65权重) + Sparse检索 (0.35权重)            │
│  召回 top_k × 4 = 24 个候选文档                         │
└──────────────────────────────────────────────────────────┘
                        │
                        ▼
┌──────────────────────────────────────────────────────────┐
│              第4步：多查询结果合并                         │
│  3个查询各召回24个 → 合并去重 → 保留最高分               │
└──────────────────────────────────────────────────────────┘
                        │
                        ▼
┌──────────────────────────────────────────────────────────┐
│            第5步：重排序 (Re-Ranking)                     │
│  用 BGE Reranker 对候选文档精排                          │
│  混合分数 = 0.4 × 检索分数 + 0.6 × 重排分数              │
└──────────────────────────────────────────────────────────┘
           │
           ▼
┌──────────────────────────────────────────────────────────┐
│              第6步：返回最终结果                          │
│  返回 top_k = 6 个最相关的文档片段                       │
└──────────────────────────────────────────────────────────┘

关于多查询合并 HybridRetriever.retrieve：
      查询1: "癫痫夜间发作频繁怎么办？" → 召回24条 → [A, B, C, D, ...]
      查询2: "seizure disorder nocturnal..." → 召回24条 → [A, E, F, G, ...]
      查询3: "癫痫夜间急性处理方案"    → 召回24条 → [H, I, J, A, ...]

      合并去重（相同chunk保留最高分）:
      {A: 0.85, B: 0.72, C: 0.68, E: 0.65, F: 0.63, ...}

      精排 top_k=6:
      返回: [A, B, C, E, F, G]
1. 数据处理：

   - `app/retrieval/mineru_pipeline.py`
   - `app/retrieval/chunking.py`（父子文档分块策略）

   2.混合检索：

   - `app/retrieval/embeddings.py`
   - `app/retrieval/vector_store.py`
   - `app/retrieval/retriever.py`

   3.工作流调度：

   - `app/workflow.py`，包含状态图（StateGraph）与条件分支逻辑

## Stage 3: Model Deployment and Performance
1. vLLM 启动命令：

   - `scripts/vllm_start_commands.ps1`（包含 AWQ/GPTQ INT4 量化示例）

   2.显存优化关键参数：

   - `--quantization`（量化配置）
   - `--max-model-len`（最大模型上下文长度）
   - `--gpu-memory-utilization`（GPU 显存利用率）
   - `--tensor-parallel-size`（张量并行规模）

   3. 提示词策略：

   - `app/prompts.py` 中的结构化输出模板与内部推理策略

## Stage 4: Testing and Evaluation
1. Deterministic lexical 兼容诊断：

   - `POST /v1/eval/ragas` 仅是 legacy compatibility URL；当前未安装、也未运行 Ragas。
   - 当前元数据固定为 `backend=deterministic_lexical`、`metric_version=token_overlap_v1`、`aggregation=macro_average`。
   - 每个样本只比较 `ground_truth` 与 `retrieved_contexts`：兼容字段 `context_precision` 表示 context-hit ratio（命中的 retrieved context 比例），`context_recall` 表示 ground-truth token coverage（检索上下文覆盖的 ground-truth token 比例），最终按样本做宏平均。
   - `response` 不参与计算；这两个字段不代表 Ragas、faithfulness、答案事实正确性、临床安全或临床效果。

2. LLM-as-a-Judge（大模型作为裁判，独立路径）：

   - `app/prompts.py` 中的 JSON 格式打分模板
   - `app/llm/llm_judge.py` 中的执行封装逻辑
   - 不得把该独立接口与 deterministic lexical 兼容字段合并称为“RAGAS 双轨质量评估”，接口存在本身也不能证明专业性、安全性或临床有效性。

项目的回退机制：

用户请求
    │
    ├─────────────────────────────────────────┐
    ▼                                         ▼
LangGraph 可用？                        LLM 可用？
├─ 是 → LangGraph 工作流               ├─ 是 → LLM 改写查询
└─ 否 → 手动顺序执行                    └─ 否 → 规则改写
                                            │
                                            ▼
                                    Dense 向量可用？
                                    ├─ 是 → BGE-M3
                                    └─ 否 → 哈希向量
                                            │
                                            ▼
                                    Sparse 向量可用？
                                    ├─ 是 → BGE-M3
                                    └─ 否 → TF-IDF
                                            │
                                            ▼
                                    Reranker 可用？
                                    ├─ 是 → BGE Reranker
                                    └─ 否 → 词项重叠
                                            │
                                            ▼
                                    向量数据库可用？
                                    ├─ 是 → Qdrant
                                    └─ 否 → 内存存储
                                            │
                                            ▼
                                        返回结果