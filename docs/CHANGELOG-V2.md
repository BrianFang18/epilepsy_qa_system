# 癫痫专科智能问诊系统 V2 迭代日志

> 项目名称：癫痫专科智能问诊系统
> 起始版本：V1.0（基础 RAG 系统）
> 当前版本：V2.0（开发中）
> 维护者：Epilepsy-QA Team

> [!IMPORTANT]
> **状态边界：本文混合记录历史问题、原始声明、目标阈值和未来规划，不等同于完成清单或验收证据。** `2026-MM-DD`、计划工期、拟新增文件和“验证方法”均表示 `FUTURE/PLANNED`；只有同时给出真实完成日期与可复核证据的条目才能标为 `COMPLETED/VERIFIED`。文中的准确率、召回率、延迟、覆盖率等数值都是目标阈值，不是实测结果。
>
> **当前评估状态**：`POST /v1/eval/ragas` 仅为 legacy compatibility URL；当前未安装、也未运行 Ragas。实际实现是 `backend=deterministic_lexical`、`metric_version=token_overlap_v1`、`aggregation=macro_average`，只比较 `ground_truth` 与 `retrieved_contexts`，输出 context-hit ratio（兼容字段 `context_precision`）与 ground-truth token coverage（兼容字段 `context_recall`）的样本宏平均；`response` 不参与计算。这些字段不代表 Ragas、faithfulness、答案事实正确性、临床安全或临床效果。未来的 Ragas 或医疗专项评估属于 hypothetical integration，必须独立版本化和验收。

---

## 迭代记录规范

本文记录历史问题与未来规划，不以“写入日志”代表问题已经解决。每个条目至少记录：
- **迭代编号**：V2-XXX
- **状态**：HISTORICAL / PLANNED / IN PROGRESS / COMPLETED / VERIFIED
- **问题类型**：口语理解 / 幻觉 / 重复询问 / 性能 / 可观测性 / 安全 等
- **问题描述**：具体问题表现
- **根因分析**：问题的根本原因
- **解决方案**：具体实现方案或规划方案
- **改造文件**：涉及或计划修改的代码文件
- **验证方法**：计划如何验证；不等同于已通过
- **证据/验收记录**：命令、环境、结果或可复核链接；没有证据时留空
- **完成日期**：真实完成后填写 YYYY-MM-DD；`YYYY-MM-DD` 占位符不是完成日期

---

## V2.0 迭代记录

### [V2-001] 🔴 高优先级 — 对话状态管理缺失（问卷型对话问题）

**问题类型**：架构设计
**问题描述**：
系统为单轮问答设计，每次 `POST /v1/ask` 都是独立事件，无会话状态。无多轮上下文追踪能力。

**具体表现**：
- 用户第一轮说"我脑阔痛"，系统回复"请描述症状"
- 用户第二轮说"就是扯风那种"，系统完全不知道用户在说什么
- 无法识别用户已提供了哪些信息、还缺少哪些信息

**根因分析**：
V1 的 `AgenticRAGWorkflow` 只有单次 `run()` 调用，`AgentState` 不持久化，每次请求独立，无法累积上下文。

**解决方案**：
引入 `ConversationState` 数据模型和 `DialoguePolicyEngine`，为每个会话（`session_id`）维护一个持久化状态机，跟踪已收集的症状槽位和待追问队列。

**改造文件**：
- 新增 `app/v2/conversation/state.py`
- 新增 `app/v2/conversation/policy.py`
- 新增 `app/v2/conversation/memory.py`
- 修改 `app/schemas.py` — 新增对话相关数据模型
- 修改 `app/service.py` — 引入会话管理

**验证方法**：
模拟 5 轮连续对话，验证：
1. 第 2 轮能引用第 1 轮信息
2. 不重复询问已提供的信息
3. 问诊完成度（completion_percentage）正确递增

**完成日期**：2026-MM-DD（计划 2 周）

---

### [V2-002] 🔴 高优先级 — 口语/方言理解能力不足

**问题类型**：口语理解
**问题描述**：
jieba 分词器无法识别四川话等方言词汇，导致模型无法理解患者描述。

**具体表现**：
- "我脑阔痛啷个办" → 模型无法识别"脑阔痛"="头痛"
- "扯风" → 模型无法识别="抽搐"
- "小手臂起了水泡" → "小手臂"无法标准化为"前臂"

**根因分析**：
V1 的 `simple_tokenize()` 仅用标准 jieba 词典，缺少方言词表和口语-医学术语映射层。

**解决方案**：
构建多层级的方言规范化管道：
1. **Layer 1**：医学术语标准化（症状词典 + 同义词扩展）
2. **Layer 2**：方言词汇转换（四川话词典 v1.0，200+词条）
3. **Layer 3**：口语症状解析（口语表达 → 标准医学描述）
4. **Layer 4**：身体部位标准化
5. **Layer 5**：向量相似度兜底（处理未知方言）

**改造文件**：
- 新增 `app/v2/understanding/dialect_normalizer.py`
- 新增 `app/v2/understanding/dialect_dict.py` — 方言词典
- 新增 `data/dialect_dictionary_v1.json`
- 修改 `app/utils.py` — 集成方言规范化

**验证方法**：
测试集 100 条方言表达，验证标准化准确率 > 85%

**完成日期**：2026-MM-DD（计划 1.5 周）

---

### [V2-003] 🔴 高优先级 — 指代消解缺失

**问题类型**：上下文连贯性
**问题描述**：
无法消解代词和指示词的指代对象，导致重复询问或答非所问。

**具体表现**：
- 用户："小手臂起了水泡"
- 系统问："水泡在哪个位置？"
- 用户答："小手臂啊"
- 系统再次问："小手臂具体哪个位置？"

**根因分析**：
V1 完全没有指代消解（Coreference Resolution）模块，所有历史信息仅作为检索上下文使用，无法识别"小手臂"已在上一轮被回答。

**解决方案**：
实现 `CoreferenceResolver`，采用规则 + 检索混合策略：
1. 医疗场景高频指代词表（"这/那/它/哪个位置"等）
2. 基于对话历史的候选实体检索
3. 时序优先原则（越近的指代越可能指向前文）

**改造文件**：
- 新增 `app/v2/understanding/coreference.py`
- 修改 `app/v2/conversation/state.py` — 集成指代消解

**验证方法**：
30 条含指代消解的测试用例，准确率 > 80%

**完成日期**：2026-MM-DD（计划 1 周）

---

### [V2-004] 🔴 高优先级 — GraphRAG 检索能力不足

**问题类型**：检索增强
**问题描述**：
传统向量 RAG 无法理解医学实体间的语义关系，组合症状检索效果差。

**具体表现**：
- 用户问"抽搐伴意识丧失是什么病"，只检索到包含单个词的结果
- 检索"左乙拉西坦不管用怎么办"，无法推理出替代药物
- 相似症状不同疾病无法区分

**根因分析**：
V1 的 `HybridRetriever` 仅基于向量相似度，缺少结构化的医学知识推理能力。

**解决方案**：
引入 GraphRAG 架构：
1. **医疗知识图谱 Schema**：定义 Disease/Symptom/Drug/Exam 等节点类型
2. **图谱构建器**：从医学文献和临床病历中自动抽取三元组
3. **GraphRAG Retriever**：支持 Local Search / Global Search / Hybrid Search 三种模式
4. **自学习机制**：从医患对话和病历中持续更新图谱

**改造文件**：
- 新增 `app/v2/graphrag/schema.py`
- 新增 `app/v2/graphrag/builder.py`
- 新增 `app/v2/graphrag/retriever.py`
- 新增 `app/v2/graphrag/updater.py`
- 修改 `app/retrieval/retriever.py` — 集成 GraphRAG

**验证方法**：
对比评估：GraphRAG vs 纯向量 RAG，召回率提升 > 20%

**完成日期**：2026-MM-DD（计划 3 周）

---

### [V2-005] 🟡 中优先级 — 重复性问题输出

**问题类型**：对话体验
**问题描述**：
模型在同一轮回复中或跨轮对话中重复询问同一信息。

**具体表现**：
- 模型回复开头说"请问发作持续多长时间"，结尾又说"请告诉我发作持续时间"
- 连续两轮问同一个问题
- 用户已明确回答后，继续追问相同问题

**根因分析**：
1. 无对话状态跟踪，用户已回答的信息不在系统记忆中
2. `_build_context()` 每次重新构建，无法感知已问/已答
3. Prompt 中缺少"不要重复询问"的显式约束

**解决方案**：
1. `ConversationState` 中维护 `asked_slots` 集合
2. 生成答案前检查该槽位是否已被询问且用户已回答
3. 在 `DOCTOR_SYMPTOM_PROMPT` 中增加"避免重复已问问题"的约束
4. 后处理增加重复检测

**改造文件**：
- 修改 `app/v2/conversation/state.py` — 增加 `asked_slots` 追踪
- 修改 `app/v2/generation/doctor_generator.py` — 重复检测
- 修改 `app/v2/understanding/prompts_v2.py` — 更新 Prompt

**验证方法**：
自动化检测：同一会话中重复询问同一槽位 > 1 次的比率 < 5%

**完成日期**：2026-MM-DD（计划 1 周）

---

### [V2-006] 🟡 中优先级 — 急危重症检测能力不足

**问题类型**：医疗安全
**问题描述**：
系统缺少独立的急危重症检测和紧急干预机制。

**具体表现**：
- 用户描述"抽搐超过 10 分钟"，系统仍然生成普通回复，无紧急提示
- 缺少对癫痫持续状态、意识障碍、呼吸窘迫等急危重症的实时检测

**根因分析**：
V1 的 `ANSWER_SYSTEM_PROMPT` 仅在 prompt 层面约束紧急情况，没有独立的急危重症检测节点。

**解决方案**：
1. 实现独立的 `EmergencyDetector` 模块，基于规则 + LLM 双重检测
2. 在 `DialoguePolicyEngine` 中增加紧急干预分支
3. 急危重症检测优先于任何其他逻辑
4. 配置紧急干预消息模板

**改造文件**：
- 新增 `app/v2/safety/emergency_detector.py`
- 修改 `app/v2/conversation/policy.py` — 集成紧急检测
- 修改 `app/prompts.py` — 新增紧急干预提示词

**验证方法**：
测试集 50 条含急危重症迹象的输入，召回率 100%，误报率 < 10%

**完成日期**：2026-MM-DD（计划 1 周）

---

### [V2-007] 🟡 中优先级 — 响应延迟过高

**问题类型**：性能
**问题描述**：
小程序高并发场景下，纯推理架构无法满足 < 5s 响应要求。

**具体表现**：
- 单次请求延迟 P95 > 7s（目标 P95 < 3s）
- 并发量 100+ 时响应崩溃
- vLLM QPS 上限成为瓶颈

**根因分析**：
1. 每次请求都走完整的 LLM 推理（意图路由 + 查询改写 + 生成）
2. 无缓存层，相同/相似问题重复推理
3. 缺少快速预判机制

**解决方案**：
1. **L1 缓存（Redis）**：对话状态缓存（TTL=30min）
2. **L2 缓存（语义缓存）**：基于向量相似度的请求缓存（TTL=24h）
3. **L3 缓存（KB Snapshot）**：向量索引快照缓存（TTL=1h）
4. **快速预判模型**：Qwen3-8B 独立服务做意图分类（<500ms）
5. **批量检索**：多查询变体并行执行

**改造文件**：
- 新增 `app/v2/cache/semantic_cache.py`
- 新增 `app/v2/cache/dialogue_cache.py`
- 新增 `app/v2/performance/quick_triage.py`
- 修改 `app/config.py` — 新增 Redis 配置
- 修改 `app/retrieval/retriever.py` — 集成缓存

**验证方法**：
1. 缓存命中率 > 40%（相同/相似问题）
2. P95 延迟 < 3s（P50 < 1.5s）
3. 500 并发下系统稳定

**完成日期**：2026-MM-DD（计划 2 周）

---

### [V2-008] 🟡 中优先级 — 意图路由分类粒度不够

**问题类型**：路由准确性
**问题描述**：
三分类路由（literature/clinical/both）粒度太粗，医学场景下经常跑偏。

**具体表现**：
- "我最近发作变多了" 被路由为 literature（应为 clinical）
- "左乙拉西坦说明书上写了什么" 被路由为 clinical（应为 literature）

**根因分析**：
`ROUTER_PROMPT` 分类规则过于简单，关键词覆盖不足，医学术语区分度低。

**解决方案**：
1. 增强 `ROUTER_PROMPT`，增加更多医学场景分类示例
2. 增加七分类甚至更细粒度的意图标签
3. 引入症状类型路由（seizure_type/medication/diagnosis/treatment/emergency）
4. LLM 路由 + 规则路由双保险

**改造文件**：
- 修改 `app/prompts.py` — 重构 `ROUTER_PROMPT`
- 修改 `app/schemas.py` — 扩展 `IntentType` 枚举
- 修改 `app/workflow.py` — 支持多分支路由

**验证方法**：
测试集 200 条意图分类，准确率 > 90%

**完成日期**：2026-MM-DD（计划 1 周）

---

### [V2-009] 🟢 低优先级 — 测试体系缺失

**问题类型**：工程化
**问题描述**：
整个项目没有单元测试、集成测试、回归测试，代码质量无保障。

**具体表现**：
- 修改一个函数无法快速验证是否破坏其他功能
- 无法量化 V2 改进效果
- 无法做 A/B 测试

**解决方案**：
建立完整测试体系：
1. **单元测试**（pytest）：方言规范化、指代消解、检索逻辑
2. **集成测试**：API 端点、完整对话流
3. **端到端测试**：医生问诊场景、急危重症检测
4. **性能测试**：延迟、吞吐量、缓存命中率
5. **自动化评测（hypothetical future integration）**：未来可独立接入并版本化验证 Ragas 与医疗专项评估；当前 legacy `/v1/eval/ragas` 仅是 `deterministic_lexical/token_overlap_v1/macro_average` 的兼容 URL，忽略 `response`，不能验证医学准确性、安全或生成质量

**改造文件**：
- 新增 `tests/unit/`
- 新增 `tests/integration/`
- 新增 `tests/e2e/`
- 新增 `tests/performance/`
- 修改 `requirements.txt` — 新增 pytest、pytest-asyncio

**验证方法**：
测试覆盖率 > 60%（核心模块 > 80%）

**完成日期**：2026-MM-DD（持续迭代）

---

### [V2-010] 🟢 低优先级 — 可观测性不足

**问题类型**：运维
**问题描述**：
无结构化日志、无链路追踪、无 metrics，生产环境问题定位困难。

**具体表现**：
- 线上问题只能靠 print 大法排查
- 无法看到一次请求的完整调用链路
- 无法监控缓存命中率、检索质量等关键指标

**解决方案**：
1. **结构化日志**：JSON 格式日志，含 session_id、trace_id、latency 等字段
2. **链路追踪**：OpenTelemetry 集成，每次请求分配 trace_id
3. **Metrics**：Prometheus 指标（延迟分布、QPS、缓存命中率）
4. **健康检查增强**：Redis 连接、vLLM 可用性、向量库状态

**改造文件**：
- 新增 `app/logging_config.py`
- 修改 `app/service.py` — 集成 tracing
- 修改 `app/main.py` — 增强健康检查
- 修改 `app/retrieval/` — 添加关键日志点

**验证方法**：
上线后可从 Grafana 看到完整监控面板

**完成日期**：2026-MM-DD（计划 1 周）

---

### [V2-011] 🟢 低优先级 — API 安全机制缺失

**问题类型**：安全
**问题描述**：
CORS 全开、无认证、无限流，存在滥用风险。

**具体表现**：
- `allow_origins=["*"]` — 任意域可访问
- 无 API Key 认证
- 无请求速率限制
- 无输入长度校验

**解决方案**：
1. **API 认证**：JWT Token / API Key
2. **限流**：基于 Redis 的滑动窗口限流（每用户 60 req/min）
3. **CORS 收紧**：只允许指定域名
4. **输入校验**：请求体大小限制、敏感词过滤
5. **审计日志**：记录所有请求的 session_id、user_id、timestamp

**改造文件**：
- 修改 `app/main.py` — 新增认证中间件、限流中间件
- 新增 `app/middleware/auth.py`
- 新增 `app/middleware/rate_limiter.py`
- 修改 `app/config.py` — 新增安全配置项

**验证方法**：
1. 无 Token 请求返回 401
2. 超过限流返回 429
3. 超大请求被拒绝

**完成日期**：2026-MM-DD（计划 1 周）

---

### [V2-012] 🟢 低优先级 — 知识库可扩展性不足

**问题类型**：架构
**问题描述**：
仅支持父子分块，无法适应多样化医疗文档格式。

**具体表现**：
- 临床病历（模板化）与医学文献（自由文本）用同一分块策略
- 表格类文档（脑电图报告）分块效果差
- 无统一的文档类型识别和分块策略选择

**解决方案**：
1. 实现 `ChunkingFactory`：根据文档类型自动选择最优分块策略
2. 支持多种分块策略：父子分块 / 模板感知分块 / 表格分块 / 句子级分块
3. 文档类型自动识别（基于文件名/内容特征）
4. 完善 MinerU 集成，支持更多 PDF 类型

**改造文件**：
- 新增 `app/v2/ingestion/chunking_factory.py`
- 修改 `app/retrieval/chunking.py` — 增加策略选项
- 修改 `app/retrieval/mineru_pipeline.py` — 完善集成
- 修改 `app/retrieval/vector_store.py` — 新增 Milvus 实现

**验证方法**：
1. 临床病历分块准确率 > 90%
2. 表格文档保留结构信息
3. 不同文档类型分块效果可量化评估

**完成日期**：2026-MM-DD（计划 1.5 周）

---

## 迭代进度总览

| 迭代编号 | 问题 | 优先级 | 状态 | 计划工期 | 开始日期 | 完成日期 |
|---------|------|--------|------|---------|---------|---------|
| V2-001 | 对话状态管理缺失 | 🔴 高 | 进行中 | 2 周 | 2026-MM-DD | - |
| V2-002 | 口语/方言理解不足 | 🔴 高 | 待开始 | 1.5 周 | - | - |
| V2-003 | 指代消解缺失 | 🔴 高 | 待开始 | 1 周 | - | - |
| V2-004 | GraphRAG 检索不足 | 🔴 高 | 待开始 | 3 周 | - | - |
| V2-005 | 重复性问题输出 | 🟡 中 | 待开始 | 1 周 | - | - |
| V2-006 | 急危重症检测不足 | 🟡 中 | 待开始 | 1 周 | - | - |
| V2-007 | 响应延迟过高 | 🟡 中 | 待开始 | 2 周 | - | - |
| V2-008 | 意图路由粒度不够 | 🟡 中 | 待开始 | 1 周 | - | - |
| V2-009 | 测试体系缺失 | 🟢 低 | 待开始 | 持续 | - | - |
| V2-010 | 可观测性不足 | 🟢 低 | 待开始 | 1 周 | - | - |
| V2-011 | API 安全机制缺失 | 🟢 低 | 待开始 | 1 周 | - | - |
| V2-012 | 知识库可扩展性不足 | 🟢 低 | 待开始 | 1.5 周 | - | - |

**图例**：
- 🔴 高 = 必须解决，影响核心功能
- 🟡 中 = 重要，影响用户体验
- 🟢 低 = 优化项，影响工程化质量

---

## 版本历史

### V1.0 — 基础 RAG 系统（历史状态标签：已完成；下列声明仍需独立证据）
- 单轮问答 RAG 架构
- 意图路由（literature/clinical/both）
- 混合检索（BGE-M3 dense + sparse）
- BGE Reranker 精排
- LangGraph 状态机编排
- MinerU/PyMuPDF 文档解析
- 父子分块策略
- 原始历史声明：RAGAS + LLM-as-a-Judge 评估（未按当前标准验收）
- 当前状态：`/v1/eval/ragas` 仅保留 legacy URL，实际为 `deterministic_lexical/token_overlap_v1/macro_average`，不安装或运行 Ragas，且不评估 `response`
- 完成日期：2025-XX-XX

### V2.0 — 智能问诊系统（规划/进行中，未整体验收）
- 多轮对话状态机
- 方言规范化层
- GraphRAG 检索增强
- 医生风格生成器
- 多级缓存架构
- 生产化改造（测试/可观测性/安全）
- HIS 联动支持
- 目标完成：2026-XX-XX

---

*文档版本：V2.0*
*最后更新：2026-05-14*
*维护者：Epilepsy-QA Team*
