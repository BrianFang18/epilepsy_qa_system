# 角色设定

> [!IMPORTANT]
> **状态说明：以下正文是项目最初的需求 Prompt，用于保留历史规划背景，不是当前实现清单或验收结果。** 后文关于 Ragas、LLM-as-a-Judge、CoT、模型部署和量化指标的内容均是原始要求或未来方向；只有经过独立实现核对和留存证据的事项才能称为当前能力。
>
> **当前评估基线**：`POST /v1/eval/ragas` 仅为 legacy compatibility URL；当前未安装、也未运行 Ragas。实际实现为 `backend=deterministic_lexical`、`metric_version=token_overlap_v1`、`aggregation=macro_average`，只对 `ground_truth` 与 `retrieved_contexts` 计算 context-hit ratio（兼容字段 `context_precision`）和 ground-truth token coverage（兼容字段 `context_recall`）后做样本宏平均；`response` 不参与计算。因此它不代表 Ragas、faithfulness、答案事实正确性、临床安全或临床效果。未来若接入 Ragas 或 response-level/临床评估，必须作为独立、显式版本化并重新验收的集成。

你是一名资深的 AI 算法架构师，拥有丰富的大模型落地实战经验，精通 Agentic RAG 系统架构与企业级部署。

# 任务目标
我需要你帮我完整设计一个名为“基于 Agentic RAG 的癫痫专科智能问诊与检索系统”的个人实战项目。该项目将写在我的简历上，用于申请大模型/算法岗位的暑期实习。请提供从架构设计、核心代码思路到面试准备的完整技术方案。

# 技术栈限定
- 核心语言与框架：Python, FastAPI
- 工作流引擎：LangGraph
- 大模型部署：vLLM (DeepSeek-R1-Distill-Qwen-32B 或类似尺寸，INT4量化)
- 向量与检索：Qdrant 或 Milvus, BGE-M3 (混合检索), BGE-Reranker-v2 (精排)
- 文档解析与处理：MinerU (父子文档分块策略)
- 评估框架：RAGAS, LLM-as-a-Judge

# 输出要求（请严格按以下五个阶段拆解输出）

## 第一阶段：系统架构与模块划分
1. 描述系统整体架构的数据流转过程（从用户输入到系统最终输出的具体步骤）。
2. 说明 LangGraph 工作流中 Agent 的意图路由逻辑（如何区分并处理“医学文献检索”与“临床问诊匹配”两个分支）。

## 第二阶段：核心链路代码思路
请提供以下核心链路的具体实现思路或伪代码：
1. **数据处理**：如何结合 MinerU 解析复杂医学文献并实现父子文档分块（Parent-Child Chunking）。
2. **混合检索**：BGE-M3 结合向量数据库进行 Dense（稠密向量）+ Sparse（稀疏向量）混合召回的逻辑。
3. **工作流调度**：LangGraph 的状态图（StateGraph）定义和条件边的路由逻辑。

## 第三阶段：模型部署与性能优化
1. 提供使用 vLLM 部署 32B 模型并开启 AWQ/GPTQ INT4 量化的具体启动命令。
2. 说明在 24G/32G 显存限制下，有哪些核心参数可以优化推理速度。
3. 说明如何设计提示词，以利用大模型的思维链（CoT）能力提升医疗问答的严谨性。

## 第四阶段：系统测试与评估
1. 简述如何使用 RAGAS 框架自动评估系统的上下文精确度（Context Precision）和召回率（Context Recall）。
2. 提供一个用于 LLM-as-a-Judge 的评估提示词模板，让大模型评估最终答案的专业性和安全性。

## 第五阶段：简历撰写与面试防坑
1. 针对本项目，提供 3-4 条符合 STAR 法则的高质量简历项目经历描述（需包含量化指标和解决的技术痛点）。
2. 站在面试官的角度，列出 3 个关于该项目的高频技术深挖问题，并提供简要的解答思路。