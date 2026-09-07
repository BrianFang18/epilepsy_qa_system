# Epilepsy QA System｜AI / RAG 秋招面试准备

> 面向 AI / LLM 应用、RAG、Agent workflow 和 AI 工程岗位。先说清楚问题与选择，再根据追问补技术细节；不要逐字背成技术报告。

## 0. 面试前怎么使用这份文档

### A 档：先练到能脱口而出

- 第 1 节三档项目介绍；
- 第 2 节中的 Q1、Q2、Q3、Q4、Q5、Q8、Q9、Q13、Q15；
- 第 9 节“个人贡献”和“Bug 排查”两个真实故事；
- 第 10 节事实红线。

### B 档：技术面追问时再展开

第 3～7 节是追问增量，不需要主动一次讲完。主回答控制在 30～60 秒；面试官对某个词感兴趣，再补实现、trade-off 和边界。

### C 档：面试前核对事实

不要背会随版本变化或未经核验的数字。面试前基于固定 commit 准备 2～3 个自己真实验证过的事实，例如完整上传链路、某类测试范围或一次 Bug 修复；没有可靠测量就不报提升百分比。

> **个人贡献提醒：**本文描述的是仓库能力。只有确实由你完成的工作，才能改成“我设计、我实现、我主导”。标有 `【需要候选人根据真实经历补充】` 的内容必须自己填写。

---

## 1. 项目快速介绍

### 1.1 一句话版本｜15～20 秒

这是一个面向癫痫知识问答的 RAG 系统。它先从文档中找证据，证据不足就拒答，并把引用一起展示给用户。

### 1.2 30 秒版本

用户可以在后台上传癫痫相关资料，系统异步完成解析、分块和索引。提问时，它先判断问题是否需要检索，再查找 evidence、判断证据够不够，最后返回回答和 citation。默认环境不依赖模型 Key，也可以显式切换到 DeepSeek 等 OpenAI-compatible provider。

### 1.3 1 分钟版本

这个项目解决的是专业问答中“答案来源不透明、没有证据也可能强答”的问题。它有两条主链：文档上传后由 worker 异步完成解析、chunking、embedding 和索引，半成品索引不会直接开放查询；用户提问后，LangGraph 先处理紧急、问候和域外请求，再做 retrieval 和 evidence gate，证据不足就拒答，证据充分才进入生成。前端通过 SSE 展示回答、citation 和处理轨迹。仓库默认用 deterministic demo 保证任何人都能复现，真实模型是可选配置。它验证的是完整 RAG 工程链路，不代表临床效果。

【需要候选人根据真实经历补充】现场再补一句：`我主要负责/参与了 ______，针对 ______ 问题做了 ______，并通过 ______ 验证。`

### 1.4 项目最值得讲的 5 个亮点

1. **回答与证据绑定**：回答、citation 和 evidence panel 使用同一批检索结果。
2. **显式 graph workflow**：routing、retrieval、evidence gate 和 output policy 分开编排。
3. **可恢复的异步摄取**：worker 使用 lease、heartbeat、retry 和 reclaim 处理失败。
4. **半成品索引不可见**：Qdrant points 从 staging 切到 active 后才参与查询。
5. **运行模式不冒充**：deterministic demo、OpenAI-compatible generation 和 BGE 配置明确分开。

---

## 2. 高频必背 Q&A

### Q1：这个项目主要解决什么问题？

**推荐回答：**

核心不是让系统“能说话”，而是让专业问答有依据、能追溯，并且在没有证据时愿意停止。项目把文档摄取、retrieval、evidence gate、citation 和安全路由串成完整 Web 应用。用户既能看到回答，也能查看它参考了哪些内容。

**追问再补：**癫痫涉及急救和用药等高风险信息，很适合展示 evidence-aware RAG 的价值；但项目是工程与信息检索演示，不是医疗器械。

### Q2：为什么做 RAG，而不是直接调用 LLM？

**推荐回答：**

直接调用 LLM 时，本地资料不一定在模型参数里，回答依据也不透明。RAG 先从外部知识库找 evidence，再让生成过程基于 evidence 回答，所以知识可以更新，来源也能展示。不过 RAG 只是降低 hallucination，不会自动消除它，因为检索和生成都可能出错。

**追问再补：**因此 retrieval 和 generation 要分开评估，不能只看最终答案是否流畅。

### Q3：一次完整问答是怎么执行的？

**推荐回答：**

可以概括成四步：先判断这类问题要不要进入普通问答，再查找证据，然后判断证据够不够，最后生成并返回引用。问候、明显域外和紧急情况会提前处理；普通问题才进入 retrieval。证据不足时本地拒答，证据充分时才走 demo renderer 或真实模型，并通过 SSE 返回状态、sources 和回答片段。

**如果继续追问实现：**FastAPI 接收请求，LangGraph 编排节点，HybridRetriever 查询 Qdrant，ChatService 组织 SSE 事件。

### Q4：为什么使用 LangGraph？

**推荐回答：**

因为这不是一条固定直线，而是有紧急、问候、域外、证据不足和正常生成等分支。LangGraph 把 state、处理节点和条件路由显式化，比把所有逻辑堆在一个 FastAPI function 里更容易测试和扩展。代价是多了一层编排复杂度，所以简单流程不一定需要它。

### Q5：这个项目算 Agent 吗？

**推荐回答：**

更准确的说法是 **graph-based RAG workflow**，也可以有限度地叫 Agentic RAG。它有状态管理和条件路由，但路径主要由代码预先定义；没有让 LLM 自主规划、任意选择工具、循环执行，也没有服务端长期 memory。因此我不会把它包装成 fully autonomous Agent。

### Q6：文档上传后经历了什么？

**推荐回答：**

API 先校验文件，把原件放到 MinIO，并在 PostgreSQL 创建 document 和 queued job。worker 再完成 fetch、parse、chunk、embed、index 和 finalize。索引先写成 staging，确认完整后才切到 active，最后任务变成 succeeded。这样上传请求不会被重处理阻塞，失败任务也可以恢复。

### Q7：文档怎么 chunk？

**推荐回答：**

项目先按标题和段落做粗分，再对长内容做带 overlap 的滑动窗口。它采用 parent-child 思路：较小的 child 用于精确检索，较大的 parent text 用于生成上下文。真正建立向量索引的是 child，parent 不是另一套独立向量。

**追问再补：**chunk 太小会丢上下文，太大又会混入噪声；参数应该通过固定评估集调整。

### Q8：系统怎么找到相关 evidence？

**推荐回答：**

系统同时按 dense 和 sparse 两条路线找资料，再把结果融合、去重和重排。这样既能利用整体表示，也能保留关键词匹配。当前默认实现优先保证可复现，不等于真实语义模型；面试官追问时，再说明 Qdrant 使用 RRF、默认 dense 是 hash vector、sparse 是 term frequency，rerank 是 lexical overlap。

### Q9：怎么降低 hallucination？

**推荐回答：**

主要有四层：先做请求路由，减少不该生成的请求；再通过 retrieval 找 evidence；证据门控不通过就拒答；通过后，回答只能使用本轮允许的 citation。输出层还会处理部分高风险模式。它能降低明显风险，但 citation 和规则都不能证明答案一定正确，正式效果仍需要评估。

### Q10：知识库里没有足够证据怎么办？

**推荐回答：**

系统把“我不知道”当成正常产品能力。普通医学问题检索后，如果没有形成合格 citation，就进入 insufficient-evidence 分支，返回本地提示，不调用 LLM，也不伪造来源。这样比为了回答率强行生成更适合高风险场景。

### Q11：citation 和 evidence panel 怎么实现？

**推荐回答：**

同一批通过筛选的 evidence 既用于回答，也作为 sources 返回前端。后端按顺序给它们分配 C1、C2 等 ID，前端展示标题、excerpt、score 和来源。安全层会过滤精确匹配 `[C<number>]` 格式且不在本轮允许集合中的引用。

**边界：**这保证引用 ID 来自本轮检索集合，但不证明回答中的每句话都被该证据语义支持。

### Q12：为什么用 PostgreSQL、MinIO 和 Qdrant？

**推荐回答：**

三类数据的访问方式不同：PostgreSQL 管结构化业务状态和任务 lease，MinIO 保存上传原件，Qdrant 负责 vector 和 chunk 检索。这样职责清楚，但三套存储不能组成一个原子事务，所以项目依靠幂等、staging 和补偿做最终一致性，而不是声称强一致。

### Q13：项目最难的地方是什么？

**推荐回答：**

最难的不是调用模型，而是让 evidence 从上传到回答的生命周期可控。worker 可能中途失败，向量也可能只写了一部分。项目用 lease 和 heartbeat 支持任务重新接手，用 staging → active 避免半成品被检索，再配合幂等和重试处理崩溃窗口。这让我认识到，RAG 的难点通常也在数据与工程链路。

> 如果这部分不是你本人负责，请说“我重点学习和分析的难点”，不要说成个人实现。

### Q14：项目做了什么 trade-off？

**推荐回答：**

最有代表性的是“默认可复现”和“模型效果”之间的取舍。默认使用 deterministic embedding 和 evidence demo，不需要 Key 或模型权重，优点是稳定、便宜、容易测试，缺点是语义召回和生成能力有限。真实 generation 和 BGE 被设计成显式选项，避免 fallback 冒充真实模型。

### Q15：如果继续优化，下一步做什么？

**推荐回答：**

先建立评测基线，确认问题出在 retrieval 还是 generation，再决定是否换模型。第一优先是补齐 query 和 ingestion 使用同一真实 embedding 的配置，并建立带相关文档标注的 retrieval benchmark；第二优先是接通受控 evaluation runner，评估回答、citation 和 safety。基线稳定后，再考虑更强 reranker 或 Agent 能力。

---

## 3. RAG 与检索追问｜按需展开

### 3.1 当前 embedding 到底是什么？

默认是 `deterministic-md5-tf-v2`：token 被稳定映射成 dense hash vector，同时生成 TF sparse vector。它能验证 query 和 ingestion 的向量协议一致，但不是 BGE-M3，也不能代表跨语言语义召回。

**如果继续优化：**真实 embedding 必须保证 query 与 ingestion 的模型、维度、归一化方式和版本一致；升级模型后应重建索引。

### 3.2 dense、sparse、RRF 和 vector database 怎么串起来？

sparse 更接近关键词匹配，dense 用稠密表示找相似内容。Qdrant 分别召回两路结果，再通过 RRF 按排名融合，所以不要求两路原始分数同尺度。RRF score 是排序融合值，不是正确概率。Qdrant 还负责 chunk payload 和 `active` filter，这些是选择 vector database 的主要原因。

### 3.3 当前有没有 reranker？

有 rerank 阶段，但默认不是语义模型，而是把 retrieval score 和 lexical overlap 组合后重新排序。仓库保留真实模型路径；只有完成模型加载和效果验收后，才能说使用了 semantic reranker。

### 3.4 retrieval 效果不好怎么排查？

先确认解析结果、chunk 和 active 状态；再检查 query/index 的 embedding identity 与维度；然后分别看 dense、sparse、RRF、去重、rerank 和 evidence gate。最后用固定问题和 relevant chunk 标注比较指标。不要一上来就换大模型，因为错误可能发生在生成之前。

### 3.5 和 naive RAG 有什么区别？

naive RAG 通常是“问题 → top-k → prompt → answer”。当前项目增加了 routing、query 归一化、dense+sparse 融合、parent-child context、evidence gate、citation 约束和异步摄取。重点是把 RAG 做成可恢复、可解释的应用，而不只是 notebook demo。

---

## 4. LangGraph / Agent 追问｜按需展开

### 4.1 图里有哪些节点，State 传什么？

节点按功能可以记为：紧急检查、请求路由、归一化与指代消解、retrieval、证据充分性、generation preparation、output policy。State 保存原始问题、history、归一化 query、检索结果、citations、generation messages、trace 和最终 action。节点只更新自己负责的字段，条件边决定下一步。

### 4.2 为什么提前路由？为什么不用 if/else？

问候不需要检索，域外问题要说明边界，紧急情况要优先提示求助。提前路由能减少延迟和无意义模型调用。普通 if/else 可以实现，但分支多后会形成大函数；LangGraph 的优势是状态和路径显式，成本是额外学习与调试复杂度。

### 4.3 项目有长期记忆吗？

没有服务端长期 memory。前端把最近的 user/assistant history 随请求传回，图用它做规则式指代消解，生成时也可以带上历史。PostgreSQL 里的 session 主要用于管理员登录，不是聊天记忆；当前也没有启用 LangGraph checkpointer。

### 4.4 如果升级成更强 Agent，会怎么做？

只有需求明确时才加入受控工具，例如文献检索或结构化查询，并给每个工具设置 schema、权限、超时、最大调用次数和成本预算。医学场景应先保证可控和可评估，再考虑 planner、循环和更高自治度。

---

## 5. 文档摄取与数据架构追问｜按需展开

### 5.1 为什么异步处理？当前解析支持什么？

PDF 解析、chunking 和 embedding 可能很慢，放在上传请求里容易超时，也不方便重试，所以 API 只保存原件并建任务，worker 异步处理。管理上传支持 PDF、TXT 和 Markdown；TXT/Markdown 直接读取，PDF 走当前接线的解析路径并带 pypdf fallback。仓库里的 OCR/table 代码没有完整接入默认 worker，不能说默认链路已完整支持。

### 5.2 staging → active 解决什么？

向量写入不是瞬间完成的。worker 先写 staging，查询始终过滤 active；写完并核对数量后再激活，因此用户不会看到只写一半的索引。activation 与 PostgreSQL succeeded 仍不是跨系统原子操作，所以它解决的是可见性，不是分布式事务。

### 5.3 lease、heartbeat 和 reclaim 怎么工作？

worker claim 任务后记录 owner 和 lease，并用 heartbeat 续租。lease 过期的任务可以被其他 worker reclaim；一旦 reclaim 改写 owner，旧 worker 后续的数据库 stage/complete 更新会因 owner 不匹配被拒绝。需要准确说明：**仅仅过期但尚未被 reclaim，并不会形成硬 fencing**，Qdrant 写入本身也不携带数据库 fencing token，所以整体语义仍是 at-least-once。

### 5.4 worker 失败和取消怎么处理？

可重试异常进入 retry_wait，不可重试文件错误直接失败；reclaim 后可以重新执行。取消是在阶段边界检查，不是对所有底层调用的瞬时中断。特别是取消如果在 activation 已开始后到达，当前任务仍可能 finalize 为 succeeded，这是现有竞态，不能承诺“取消后绝不会完成”。

### 5.5 三存储如何保持一致？

项目使用补偿式最终一致性。上传时先写 MinIO，再在 PostgreSQL 建 document/job；数据库失败时尽力删除对象。摄取时先写 Qdrant staging，激活后再完成数据库状态。跨步骤崩溃时依赖幂等、reclaim 和后续清理；仍需要 orphan 对账，不能称 exactly-once 或强事务。

---

## 6. LLM、SSE 与后端工程追问｜按需展开

### 6.1 默认为什么不用真实 LLM？如何接 DeepSeek？

默认 demo 让任何人无需 Key、费用和模型权重也能跑通 UI、API、worker、retrieval 和 citation，并明确标注非模型生成。切换到 `openai_compatible` 后，后端 adapter 使用 endpoint、API key 和 model ID 发起流式请求。变量名保留 `DEEPSEEK_*`，协议本身是通用的。generation 与 embedding 是独立配置轴。

> 如果你确实验证过本地 DeepSeek，可以说“我的本地演示环境已接通 DeepSeek API”；仍要补充“仓库默认是 demo”。

### 6.2 每一轮都会调用模型吗？

不会。只有最终进入 generate 且存在合格 citations 时才调用 LLM adapter，一轮生成对应一次 provider streaming request。问候、明显域外、紧急情况和证据不足都本地返回，从而减少成本和不必要风险。

### 6.3 为什么使用 SSE，而不是 WebSocket？

场景主要是服务端持续向浏览器单向发送状态、sources 和回答片段，SSE 已经足够，而且基于普通 HTTP，和 FastAPI、Nginx、浏览器更容易集成。WebSocket 更适合高频双向通信，但连接和协议管理更复杂。

### 6.4 SSE contract 和取消怎么做？

事件 envelope 带 request、session、sequence、event 和 data。前端会校验顺序、request/session 一致性、sources-before-token 和终止事件；AbortController 用于停止请求，后端也检查断连并关闭 generator。底层 provider 是否立即停止仍取决于客户端取消能力。

### 6.5 处理轨迹和 token 是实时的吗？

当前 trace 更准确地说是 graph 完成后的公开轨迹回放，不是节点执行时的实时 distributed tracing。真实 provider 输出也经过安全 buffer，所以是分段流式，不保证每个 raw token 原样立即到前端。

---

## 7. Evaluation、测试与安全追问｜按需展开

### 7.1 怎么评估 RAG？

要把 retrieval 和 generation 分开。retrieval 看正确文档或 chunk 是否进入 top-k，例如 Recall@K、MRR、NDCG；generation 再看正确性、faithfulness、相关性和 citation 支持度；系统层还要看 safety、延迟、错误率和成本。这样才能判断问题发生在哪一层。

### 7.2 评估看板有什么用？为什么禁用？

它用于管理离线评估和比较模型、embedding、prompt 或索引版本，不是聊天访问统计。当前创建功能返回 409，因为还没有经过审核的评估集、参考答案与证据标签，也没有完整 runner、指标校准和人工复核。与其永久排队或展示虚假成功率，项目选择 fail closed。

### 7.3 当前 evaluation 能证明什么？

`public_eval` 是 synthetic smoke 工具：dry-run 只检查 manifest、hash、schema 和输出形状；live run 才调用公开 chat API 并汇总基础指标。它适合验证评估管线，不代表真实模型或临床效果。历史兼容 URL 虽含 `ragas`，实际只是 lexical context overlap，没有运行真正的 Ragas、faithfulness 或 LLM Judge。

### 7.4 正式 benchmark 怎么设计？

先准备版本化问题集，每条包含相关 document/chunk、参考答案要点和 safety label；固定文档、embedding、检索参数、prompt 和模型版本；先评 retrieval，再评 answer 和 citation。LLM-as-a-Judge 可以辅助，但医学场景需要人工或专家抽样校准，并记录分母、失败数、延迟和成本。

### 7.5 项目怎么测试？

unit test 验证 routing、SSE 顺序、安全过滤、worker retry 和 visibility；integration test 连接真实 PostgreSQL、MinIO、Qdrant 验证跨组件 contract；前端测试 stream parser、reducer 和页面状态；Compose CI 检查配置和镜像构建。主 CI 不等于完整真实模型 E2E，因此不要用测试通过数代替 RAG 质量。

### 7.6 医学安全和临床验证有什么区别？

项目做的是工程安全策略：紧急请求提前路由、证据不足拒答、输出后处理和免责声明。当前确定性输出过滤主要覆盖选定的中文诊断、停药和剂量模式，并不是完整的中英文安全分类器。临床验证需要明确人群、金标准、专家评审和统计设计；当前项目没有完成这部分。

---

## 8. 项目难点、Trade-off 与优化方向

### 8.1 为什么不是“接个 API 就结束”？

真正影响结果的是整条链路：文档能否正确解析、chunk 是否合理、query/index embedding 是否一致、evidence 是否足够、citation 是否可追溯、任务失败后能否恢复。模型 API 只是 generation 的一个环节。

### 8.2 为什么不做更简单的同步 Demo？

同步上传和直接写向量库实现更快，但大文件会阻塞请求，失败难重试，半成品也可能被查到。queue + worker + staging/active 用更多复杂度换来可恢复性和可观察进度，这是项目最重要的工程 trade-off 之一。

### 8.3 当前最大的不足是什么？

默认环境更侧重工程复现，不是模型效果。默认 embedding 和生成都是 deterministic 路径；真实 BGE query/ingestion 尚未成为一键默认方案，正式 evaluator 也没有接通。下一步应先用受控数据建立基线，再决定换模型、调 chunk 还是加 reranker。

### 8.4 如果再给两周，怎么安排？

第一周完成真实 embedding 的 query/ingestion 一致配置和 retrieval benchmark；第二周接通 evaluation runner，增加 answer、citation、safety 和延迟评估，并做人工抽样。目标是得到可比较基线，而不是继续堆没有指标支撑的模型。

### 8.5 当前有哪些技术债或设计纠偏？

新 ChatService、LangGraph 和 SSE 外壳仍通过 adapter 复用已有 HybridRetriever，旧接口也还存在。渐进迁移降低了风险，但配置和命名较复杂，后续应统一 retrieval port 并逐步收口 legacy 路径。

项目另一个值得学习的纠偏是：fallback 必须用真实 identity 标识，默认 worker 也必须真正启动。否则系统可能“名字像 BGE，实际是 hash”，或者上传任务一直 queued。

【需要候选人根据真实经历补充】如果你参与了上述问题，请讲清现象、定位、改动和验证；如果只是学习过，就说“项目采用了这个改进，我重点分析了它解决的问题”。

---

## 9. 行为型项目问题

### 9.1 为什么选择做这个项目？

**推荐回答：**

我不想只做一个“LLM API 加聊天页面”的 Demo，而是想把 RAG 应用从文档摄取、retrieval、workflow routing，一直做到 generation、citation、evaluation 和本地部署。选择癫痫作为垂直场景，是因为这里对证据可追溯、证据不足时拒答，以及 hallucination 控制都更有实际意义。我的目标不是做诊断系统，而是借这个场景把完整的 AI 应用工程链路真正跑通。

### 9.2 你个人主要负责什么？

**推荐回答：**

我的角色更接近 product owner 加 AI application engineer。我负责定义项目目标、拆解需求、选择整体 workflow，并给每个阶段设定约束和验收标准；具体代码有很大一部分由 coding agent 辅助完成。我不会把 Agent 输出直接当成正确答案，而是检查代码结构、配置和运行结果，确认摄取、retrieval、LangGraph、Qdrant、worker、SSE 和 evaluation 是否真的接通。发现实现和文档不一致时，我会重新提出问题，让 Agent 修改，再通过测试和端到端操作验收。README、架构、Demo 流程和能力边界也是我持续整理和纠偏的部分。

### 9.3 你学到最多的是什么？

**推荐回答：**

我学到最多的是，AI-assisted coding 并不会降低对系统理解的要求，反而提高了 review 的要求。Agent 生成的代码经常看起来合理，但一个类存在，不代表它接进了默认 runtime；名字叫 BGE 或 evaluation，也不代表后端真的用了真实模型或评估器。我需要对照配置、代码路径和端到端结果，检查 fallback 有没有被包装成真实能力。这个过程也让我认识到，AI 应用不只是 prompt engineering，数据摄取、检索质量、状态管理、可观测性、评估和故障恢复往往更决定系统是否可信。

### 9.4 遇到 Bug 时怎么排查？

**推荐回答：**

我一般先复现用户能看到的现象，再按层定位，而不是一开始就让 Agent 随机改代码。比如上传文档后任务一直 queued，我先确认前端确实创建了 job，再检查 Compose 服务、worker 状态和任务 attempts，最后发现“上传逻辑存在”和“默认 runtime 有 worker 消费”是两回事。随后我让 coding agent 沿着 API、PostgreSQL queue 和 worker 入口定位并修改接线；我再重建服务、重新上传合成文档，确认任务走到 succeeded、Qdrant 索引变成 active，聊天能够引用后才接受修改。我的原则是每次修复都要回到可观察结果验证。

### 9.5 有没有推翻过自己的设计？

**推荐回答：**

有。早期我更关注“功能有没有”和“页面能不能跑”，后来发现 RAG 项目里，能力名称和真实 runtime 同样重要：代码里定义了某个实现，不代表默认链路真的使用它；测试通过，也不代表模型质量；索引写入，也不代表应该立刻被查询。因此我把设计方向调整为更显式的 runtime mode、真实的 embedding identity、未配置能力 fail closed，以及 staging → active 的可见性边界。具体实现由 Agent 辅助迭代，我主要负责判断方案是否诚实、是否解决了原问题，以及最终验收。

### 9.6 如果重新做一次，会改什么？

**推荐回答：**

如果重新做一次，我会更早建立 evaluation baseline，而不是先做很多功能，最后再问怎么衡量。第一步先准备小而版本化的 retrieval benchmark，标注 query 和 relevant chunk；第二步统一 ingestion 与 query 的 embedding identity；第三步记录 baseline 指标，再迭代 chunking、embedding、rerank 和 generation。同时我会从一开始就给 coding agent 写清输入、输出、失败行为和验收条件，不只检查“代码看起来实现了”。也就是从 feature-driven development 更早转向 evaluation-driven AI engineering。

### 9.7 这个项目大量使用 AI Agent 开发，你怎么看？

**推荐回答：**

是的，coding agent 对这个项目的具体实现贡献很大，我也有意把它作为开发工具，因为 AI-assisted software development 本身就和我应聘的方向相关。但我的使用方式不是一句 prompt 让它一次生成整个项目，而是先拆任务、定义约束和 acceptance criteria，再让 Agent 实现。我会继续检查代码路径、配置、日志和运行结果，发现错误假设后让它迭代，并亲自完成最终验收。Agent 输出默认不可信；如果一个模块我解释不清，我就不会把它包装成自己的能力。我的体会是，Agent 提高了编码速度，但要把它用好，需要更强的系统理解和判断力，而不是更少。

---

## 10. 面试前一定别说错

1. **默认不是 DeepSeek。** 默认是 deterministic evidence demo；本地可显式接 OpenAI-compatible provider。
2. **默认 embedding 不是 BGE-M3。** 默认是 `deterministic-md5-tf-v2`；BGE profile 不等于完整端到端 BGE。
3. **不要把 graph workflow 说成 fully autonomous Agent。** 当前没有自主 planning、任意工具循环或长期 memory。
4. **citation 不等于答案必然正确。** 当前只约束特定格式引用的来源集合，不是 faithfulness 或临床证据等级证明。
5. **synthetic evaluation 不等于模型或临床效果。** 历史 `ragas` URL 也没有运行真正 Ragas。
6. **integration test 不等于 RAG quality benchmark。** 软件 contract 和模型效果是两件事。
7. **三存储不是强事务，worker 也不是 exactly-once。** 当前是 lease、幂等、staging 和补偿式最终一致性。
8. **不要声称临床验证或生产就绪。** 当前没有临床金标准、真实用户效果或完整生产安全与灾备结论。

---

## 11. 关键技术词速记

| Term | 面试时怎么理解 |
| --- | --- |
| RAG | 先检索外部知识，再让生成过程基于这些 evidence 回答。 |
| evidence | 本轮检索到、经过门控并允许进入回答上下文的文档片段。 |
| embedding | 把文本变成可比较的数值表示；query 和 index 必须保持模型与维度一致。 |
| dense retrieval | 用稠密表示找相似内容；默认 hash dense 不等于真实语义模型。 |
| sparse retrieval | 用稀疏词项表示做匹配，适合关键词和专业术语。 |
| RRF | 根据多路结果排名做融合，不要求原始分数在同一尺度。 |
| rerank | 对初步召回结果再次排序；当前默认是 lexical rerank。 |
| parent-child chunk | child 用于检索，parent text 用于提供更完整的生成上下文。 |
| Qdrant | 项目中的 vector database，保存 vector、chunk payload 和 visibility。 |
| LangGraph | 用 graph 和 state 编排 routing、retrieval、evidence gate 与 output policy。 |
| evidence gate | 证据不满足条件时停止生成并拒答。 |
| citation | 将回答里的 `[C1]` 等引用与本轮 sources 绑定。 |
| SSE | 服务端通过一个 HTTP 连接持续向浏览器单向发送事件。 |
| staging → active | 索引先不可见，确认完整后再开放检索。 |
| lease | worker 的临时任务所有权；过期任务可被重新领取，但不是强 fencing token。 |
| heartbeat | worker 定期续租，表示任务仍在处理。 |
| reclaim | lease 过期后由其他 worker重新领取并改写 owner。 |
| idempotency | 同一任务重复执行时尽量得到一致结果，不制造重复副作用。 |
| compensation | 跨存储失败后通过回滚或清理补偿，而不是依赖分布式事务。 |
| deterministic demo | 无需真实模型、结果可复现的默认工程演示模式。 |
| OpenAI-compatible API | 可连接 DeepSeek 或其他兼容服务的统一模型调用协议。 |

---

## 最后复习提醒

面试官真正想听的是：**为什么这样设计、解决了什么问题、有什么代价、你如何验证。**

如果一段回答听起来像 README、审计报告或源码注释，就先删掉一半术语。先把问题讲清楚，再根据追问补充 LangGraph、RRF、lease、staging/active 等细节。
