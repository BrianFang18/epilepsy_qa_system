# 癫痫专科智能问诊系统 V2 技术架构报告

> 文档版本：V2.0
> 更新日期：2026-05-14
> 文档状态：初稿待评审
> 适用版本：V2.0 及后续迭代

> [!IMPORTANT]
> **状态边界：本文是历史 V2 设计提案与未来路线图，不是当前仓库的实现清单或验收报告。** 下文架构图、类定义、文件路径、性能百分比、医学指标和技术选型均保留其规划意义；除非有单独实现与验收证据，否则应读作 `FUTURE/HYPOTHETICAL` 或 `UNVERIFIED`，不得表述为已实现效果。
>
> **CURRENT IMPLEMENTED（评估基线）**：`POST /v1/eval/ragas` 仅是 legacy compatibility URL；当前未安装、也未运行 Ragas。实际评估为 `backend=deterministic_lexical`、`metric_version=token_overlap_v1`、`aggregation=macro_average`。每个样本只比较 `ground_truth` 与 `retrieved_contexts`：兼容字段 `context_precision` 是 context-hit ratio，`context_recall` 是 ground-truth token coverage，之后按样本宏平均；`response` 不参与计算。该结果不代表 Ragas、faithfulness、答案事实正确性、临床安全或临床效果。未来 Ragas、response-level 或医疗专项评估必须作为独立、显式版本化并重新验收的集成。

> **阅读标签**：`CURRENT IMPLEMENTED` = 当前明确实现；`HISTORICAL REQUIREMENT` = 历史要求；`FUTURE/HYPOTHETICAL` = 未来设想；`UNVERIFIED` = 尚无当前验收证据。

---

## 一、项目背景与愿景

### 1.1 产品定位

**产品名称**：癫痫专科智能问诊系统（Epilepsy Agentic Consultation System）

**产品愿景**：打造一款能够真正模拟医生问诊体验的医疗AI产品，让患者感受到"在跟一个真实的医生对话"，而非填写一份冰冷的问卷表单。

**核心场景**：
1. **智能导诊**：通过多轮对话理解患者主诉，精准分诊
2. **预问诊**：在患者到达诊室前，AI完成症状、既往史、用药史的结构化采集
3. **电子病历辅助**：基于问诊对话自动生成规范化的门诊病历
4. **HIS联动**：与医院信息系统无缝对接，实现数据互通

### 1.2 当前痛点（V1 版本问题诊断）

通过对 V1 代码的深度分析，我们识别出以下核心问题：

| 问题类别 | 具体表现 | 根因分析 |
|---------|---------|---------|
| **对话感缺失** | 每次问答都是独立事件，无多轮上下文 | 系统架构为单轮问答设计，无会话状态管理 |
| **口语理解偏差** | "脑阔痛"无法识别为"头痛"，方言词汇普遍漏识别 | 分词器仅用 jieba 标准词典，缺少方言词汇表和口语规范化层 |
| **指代消解失败** | "小手臂起了水泡"后问"哪个位置"，模型重复询问 | 无指代消解（Coreference Resolution）机制 |
| **幻觉严重** | 常见病症回答出现错误，检索结果与问题不匹配 | 检索与生成解耦不足，查询改写质量低，上下文压缩丢失关键信息 |
| **重复性问题** | 模型反复询问同一信息 | 无对话状态跟踪，用户已提供信息被重复索取 |
| **响应延迟高** | 并发量上来后响应变慢 | 每次请求都走完整的 LLM 推理，无缓存层 |
| **意图路由失效** | 三分类路由经常跑偏 | 路由 Prompt 粒度过粗，医学术语覆盖不足 |
| **评测体系薄弱** | 无单元测试、无回归测试 | 测试覆盖率接近 0，无法量化改进效果 |

---

## 二、V2 系统架构总览

### 2.1 整体架构图

```
┌─────────────────────────────────────────────────────────────────────────────────────┐
│                              癫痫专科智能问诊系统 V2                                   │
│                                                                                      │
│  ┌──────────────────────────────────────────────────────────────────────────────┐   │
│  │                           用户交互层 (User Interaction Layer)                  │   │
│  │    小程序 / Web / App → 实时对话 → 流式响应 → 问诊进度可视化                    │   │
│  └──────────────────────────────────────────────────────────────────────────────┘   │
│                                        │                                           │
│                                        ▼                                           │
│  ┌──────────────────────────────────────────────────────────────────────────────┐   │
│  │                          API 网关层 (API Gateway Layer)                         │   │
│  │    认证鉴权 │ 限流熔断 │ 请求路由 │ 协议转换 (REST ↔ SSE) │ 调用链路追踪         │   │
│  └──────────────────────────────────────────────────────────────────────────────┘   │
│                                        │                                           │
│                                        ▼                                           │
│  ┌──────────────────────────────────────────────────────────────────────────────┐   │
│  │                    多级缓存层 (Multi-tier Caching Layer)                       │   │
│  │         L1: Redis (对话状态) │ L2: Embedding Cache │ L3: KB Snapshot Cache    │   │
│  └──────────────────────────────────────────────────────────────────────────────┘   │
│                                        │                                           │
│  ┌──────────────────────────────────────────────────────────────────────────────┐   │
│  │                    智能问诊引擎 (Medical Consultation Engine)                  │   │
│  │                                                                              │   │
│  │   ┌─────────────────────────────────────────────────────────────────────┐    │   │
│  │   │              核心状态机 (Doctor-Style State Machine)                 │    │   │
│  │   │  ┌─────────┐  ┌──────────┐  ┌──────────┐  ┌───────────┐          │    │   │
│  │   │  │ 症状收集 │→│ 既往史采集│→│ 用药史采集│→│ 诱因分析  │→...       │    │   │
│  │   │  └─────────┘  └──────────┘  └──────────┘  └───────────┘            │    │   │
│  │   └─────────────────────────────────────────────────────────────────────┘    │   │
│  │                                                                              │   │
│  │   ┌──────────┐  ┌────────────┐  ┌──────────────┐  ┌─────────────────┐       │   │
│  │   │ 方言规范化│  │ 指代消解    │  │ 对话状态跟踪  │  │ 意图理解增强     │       │   │
│  │   │ (口语层) │  │ (Coref)    │  │ (Context)    │  │ (Intent+)       │       │   │
│  │   └──────────┘  └────────────┘  └──────────────┘  └─────────────────┘       │   │
│  │                                                                              │   │
│  │   ┌──────────────────────────────────────────────────────────────────────┐   │   │
│  │   │               GraphRAG 引擎 (医疗知识图谱增强检索)                      │   │   │
│  │   │  ┌──────────┐  ┌────────────┐  ┌──────────────┐  ┌──────────────┐  │   │   │
│  │   │  │ 症状节点 │  │ 药物节点    │  │ 检查节点     │  │ 疾病节点     │  │   │   │
│  │   │  │ (Symptom)│  │ (Drug)     │  │ (LabExam)   │  │ (Disease)    │  │   │   │
│  │   │  └────┬─────┘  └─────┬──────┘  └──────┬──────┘  └──────┬──────┘  │   │   │
│  │   │       └───────────────┼─────────────────┼───────────────┘           │   │   │
│  │   │               ┌───────▼────────┬────────▼────────┐                │   │   │
│  │   │               │  医患对话知识库 │  │ 医学文献知识库 │               │   │   │
│  │   │               │ (Milvus/ES)   │  │ (Milvus/ES)  │               │   │   │
│  │   │               └───────────────┴────────────────┘                │   │   │
│  │   └──────────────────────────────────────────────────────────────────┘   │   │
│  │                                                                              │   │
│  └──────────────────────────────────────────────────────────────────────────────┘   │
│                                        │                                           │
│  ┌──────────────────────────────────────────────────────────────────────────────┐   │
│  │                          模型服务层 (Model Serving Layer)                     │   │
│  │   ┌────────────────┐  ┌──────────────────┐  ┌────────────────────┐          │   │
│  │   │ Qwen3-8B       │  │ BGE-M3 Embedding │  │ BGE Reranker v2   │          │   │
│  │   │ (对话理解+生成)│  │ (Dense+Sparse)  │  │ (精排)            │          │   │
│  │   │ vLLM / SGLang │  │ ONNX 加速        │  │ ONNX 加速         │          │   │
│  │   └────────────────┘  └──────────────────┘  └────────────────────┘          │   │
│  └──────────────────────────────────────────────────────────────────────────────┘   │
│                                        │                                           │
│  ┌──────────────────────────────────────────────────────────────────────────────┐   │
│  │                          数据存储层 (Data Storage Layer)                       │   │
│  │  ┌─────────┐  ┌──────────┐  ┌──────────┐  ┌────────────┐  ┌───────────┐    │   │
│  │  │ Redis   │  │ Milvus    │  │ PostgreSQL│  │ MongoDB    │  │ MinIO/S3  │    │   │
│  │  │ 会话状态 │  │ 向量检索  │  │ 关系数据  │  │ 病历文档  │  │ 文件存储  │    │   │
│  │  └─────────┘  └──────────┘  └──────────┘  └────────────┘  └───────────┘    │   │
│  └──────────────────────────────────────────────────────────────────────────────┘   │
│                                                                                      │
└─────────────────────────────────────────────────────────────────────────────────────┘
```

### 2.2 V2 核心升级矩阵

> **FUTURE/HYPOTHETICAL + UNVERIFIED**：本表保存 V2 立项时的目标假设。百分比、延迟降幅和效率提升均不是当前实测结果；“模拟医生问诊”“推理深度”等描述也是产品目标，不能作为临床能力或效果结论。

| 升级维度 | V1 方案 | V2 方案 | 历史目标/待验证假设 |
|---------|---------|---------|---------|
| **对话架构** | 单轮 RAG | 多轮状态机 + 对话记忆 | 真正模拟医生问诊 |
| **口语处理** | 基础 jieba 分词 | 方言规范化 + 医学口语词表 | 方言识别率 +60% |
| **指代消解** | 无 | Coreference Resolution | 上下文连贯性 +80% |
| **检索增强** | 向量检索 | GraphRAG + 向量混合 | 召回率 +25% |
| **知识管理** | 平坦 chunk 存储 | 医疗知识图谱 | 推理深度大幅提升 |
| **响应速度** | 纯推理 | 小模型+多级缓存 | P95 延迟降低 70% |
| **评测体系** | 手工测试 | 自动化测试+回归测试 | 开发效率 +50% |
| **可观测性** | 无 | 结构化日志+Metrics+Tracing | 问题定位时间 -80% |

### 2.3 模块依赖关系

```
口语规范化层 (dialect_normalizer)
        ↓
指代消解层 (coreference_resolution)
        ↓
对话状态管理器 (conversation_state)
        ↓
意图增强路由器 (intent_router+)
        ↓
┌───────────────────┬──────────────────┐
│  GraphRAG 引擎     │  检索增强模块      │
│  (知识图谱检索)    │  (原有混合检索)    │
└─────────┬─────────┴────────┬─────────┘
          │                   │
          └─────────┬─────────┘
                    ↓
            上下文融合器 (context_fusion)
                    ↓
            医疗对话生成器 (doctor_style_generator)
                    ↓
            安全护栏 (safety_guard)
                    ↓
            响应格式化器 (response_formatter)
```

---

## 三、详细技术设计

### 3.1 Phase 1: 多轮对话状态机（Doctor-Style State Machine）

#### 3.1.1 设计动机

传统问卷型导诊的本质问题是：**系统不知道用户说了什么、没说什么**。当用户说"我手昨天烫伤了，小手臂起了水泡"，系统应该记住这个信息，而不是在下一轮再次询问水泡位置。

真实的医生问诊遵循一个隐式的状态机：

```
初诊 → 症状确认 → 发作特征 → 既往史 → 用药史 → 家族史 → 体格检查建议 → 初步诊断 → 处置建议
```

每一步的推进依赖于前一步的完成状态。V2 将这一逻辑显式化，构建一个 **症状引导图（Symptom Guidance Graph）**。

#### 3.1.2 症状引导图设计

```python
# 症状引导图节点定义
class DialogueNode:
    node_id: str                      # 节点唯一标识
    node_type: DialogueNodeType       # 节点类型
    question_template: str            # 问诊问题模板
    required_slots: list[str]         # 必须收集的槽位
    optional_slots: list[str]         # 可选槽位
    follow_up_conditions: list[Condition]  # 触发条件
    medical_urgency: UrgencyLevel     # 紧迫性等级
    evidence_required: list[str]     # 需要检索的证据类型

# 节点类型枚举
class DialogueNodeType(Enum):
    SYMPTOM_COLLECTION    # 症状收集
    SEIZURE_CHARACTER     # 发作特征
    MEDICAL_HISTORY       # 既往史
    MEDICATION_HISTORY    # 用药史
    FAMILY_HISTORY        # 家族史
    TRIGGER_ANALYSIS      # 诱因分析
    PHYSICAL_EXAM         # 体格检查
    PRELIMINARY_DIAGNOSIS # 初步诊断
    TREATMENT_SUGGESTION  # 处置建议
    FOLLOW_UP             # 随访安排
```

#### 3.1.3 对话状态追踪

```python
# 对话状态模型
class ConversationState:
    session_id: str                       # 会话 ID
    patient_id: str | None                # 患者 ID（未登录为 None）
    current_node: str                     # 当前所在节点
    collected_slots: dict[str, Any]       # 已收集的槽位信息
    pending_questions: list[str]          # 待回答的问题队列
    retrieved_evidence: list[Evidence]    # 已检索到的证据
    conversation_history: list[Turn]      # 对话历史
    medical_urgency: UrgencyLevel        # 当前紧迫性
    completion_percentage: float          # 问诊完成度
    draft_diagnosis: list[str]            # 初步诊断（可能列表）
    suggested_actions: list[str]          # 建议处置
    created_at: datetime
    updated_at: datetime

# 槽位示例
SYMPTOM_SLOTS = {
    "chief_complaint": {      # 主诉
        "type": "text",
        "required": True,
        "max_turns": 2,       # 最多问 2 轮
        "medical_terms": ["抽搐", "意识丧失", "口吐白沫", ...],
        "dialect_mapping": {"脑阔痛": "头痛", "扯风": "抽搐", ...},
    },
    "seizure_duration": {     # 发作持续时间
        "type": "duration",
        "required": True,
        "unit_hint": "秒/分钟",
    },
    "seizure_frequency": {    # 发作频率
        "type": "frequency",
        "required": True,
    },
    "affected_limb": {        # 发作部位
        "type": "body_part",
        "required": False,
        "coreference_pronouns": ["这", "该", "那", "它", "此处", "这里"],
    },
    "loss_of_consciousness": {  # 意识丧失
        "type": "boolean",
        "required": True,
    },
    "tongue_biting": {         # 舌咬伤
        "type": "boolean",
        "required": False,
    },
    "post_ictal_confusion": {  # 发作后意识模糊
        "type": "boolean",
        "required": False,
    },
    "current_medications": {   # 当前用药
        "type": "medication_list",
        "required": True,
    },
    "medication_adherence": {  # 用药依从性
        "type": "enum",
        "values": ["规律", "偶尔漏服", "经常漏服", "自行停药"],
    },
}
```

#### 3.1.4 对话策略引擎

```python
class DialoguePolicyEngine:
    """
    对话策略引擎：决定下一步问什么
    基于强化学习的医生风格对话策略
    """

    def __init__(self, state: ConversationState, llm: LLMClient):
        self.state = state
        self.llm = llm

    def decide_next_action(self) -> DialogueAction:
        """
        决定下一步动作：
        1. 如果有急危重症迹象 → 触发紧急干预
        2. 如果必填槽位缺失 → 追问该槽位
        3. 如果可选槽位有价值 → 选择性追问
        4. 如果关键信息完整 → 进入下一节点
        5. 如果完成度足够 → 生成总结和建议
        """
        # 急危重症检测
        if self._detect_emergency(self.state):
            return DialogueAction(
                action_type=ActionType.EMERGENCY_INTERVENTION,
                message=self._generate_emergency_warning(),
                urgency=UrgencyLevel.CRITICAL,
            )

        # 缺失必填槽位 → 追问
        missing_required = self._get_missing_required_slots()
        if missing_required:
            slot = self._prioritize_missing_slots(missing_required)
            return self._generate_follow_up_question(slot)

        # 检查是否可以推进节点
        if self._can_advance_node():
            next_node = self._get_next_node()
            return self._generate_node_intro_question(next_node)

        # 生成问诊总结
        if self._is_sufficient_for_diagnosis():
            return self._generate_consultation_summary()

        # 继续当前节点的可选追问
        return self._generate_optional_follow_up()

    def _detect_emergency(self, state: ConversationState) -> bool:
        """急危重症检测规则"""
        critical_signs = {
            "seizure_duration": lambda v: v > 300,  # >5分钟
            "status_epilepticus": lambda v: v,      # 癫痫持续状态
            "respiratory_distress": lambda v: v,    # 呼吸窘迫
            "consciousness_abnormal": lambda v: v,  # 意识异常
            "post_ictal_paralysis": lambda v: v,    # 发作后偏瘫（Todd's麻痹）
        }
        for sign, check in critical_signs.items():
            if sign in state.collected_slots and check(state.collected_slots[sign]):
                return True
        return False
```

#### 3.1.5 上下文压缩与记忆管理

```python
class ConversationMemory:
    """
    对话记忆管理器：压缩历史对话，保留关键医学信息
    采用 Last-Recent-Important (LRI) 压缩策略
    """

    def __init__(
        self,
        max_turns: int = 20,
        max_tokens: int = 4096,
        importance_weight_fn: Callable[[Turn, Slot], float] = None,
    ):
        self.max_turns = max_turns
        self.max_tokens = max_tokens
        self.importance_weight = importance_weight_fn or self._default_importance

    def compress(self, history: list[Turn], current_slots: dict) -> list[Turn]:
        """
        对话历史压缩算法：
        1. 标记所有包含医学关键信息的轮次（权重高）
        2. 保留最近 N 轮完整历史
        3. 对更早历史进行摘要压缩
        """
        # Step 1: 计算每轮的重要性分数
        scored_turns = []
        for turn in history:
            score = self.importance_weight(turn, current_slots)
            scored_turns.append((turn, score))

        # Step 2: 保留最近的完整轮次
        recent_turns = scored_turns[-self.max_turns:]

        # Step 3: 对早期轮次做摘要
        early_turns = scored_turns[:-self.max_turns]
        if early_turns:
            summary = self._summarize_early_turns(early_turns, current_slots)
            return summary + [t for t, _ in recent_turns]

        return [t for t, _ in recent_turns]

    def _default_importance(self, turn: Turn, current_slots: dict) -> float:
        """默认重要性评分：医学信息 > 闲聊，症状 > 一般信息"""
        score = 1.0
        medical_keywords = {"症状", "发作", "药物", "剂量", "抽搐", "意识", "脑电图", "癫痫"}
        if any(kw in turn.user_message for kw in medical_keywords):
            score += 3.0
        if any(k in current_slots for k in turn.collected_slots):
            score += 2.0
        return score
```

---

### 3.2 Phase 2: 口语理解与方言规范化

#### 3.2.1 问题分析

V1 的口语理解问题有三重：

1. **方言词汇**：患者使用四川话、粤语等方言描述症状
   - "脑阔痛" → "头痛"
   - "扯风" → "抽搐/癫痫发作"
   - "甩不到符" → "控制不住（不能自主）"
   - "闷倒" → "突然发作"
   - "抠脚" → "（四川部分地区）抽搐"

2. **症状口语化表达**：
   - "昏过去了" → 意识丧失
   - "嘴巴流口水" → 口角流涎
   - "手脚不听使唤" → 四肢不自主运动
   - "遭不住" → 不能耐受

3. **身体部位方言**：
   - "小手臂" → 前臂
   - "脚杆" → 小腿
   - "颈子" → 颈部
   - "肚子" → 腹部

#### 3.2.2 方言规范化架构

```
┌──────────────────────────────────────────────────────────────────┐
│                      用户输入（口语/方言）                          │
│                   "我脑阔痛得很，还扯风"                              │
└──────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌──────────────────────────────────────────────────────────────────┐
│              Layer 1: 医学术语标准化 (Medical Terminology)         │
│  ┌────────────────────────────────────────────────────────────┐  │
│  │ 症状词典匹配 + 词向量相似度扩展                              │  │
│  │ "扯风" → ["抽搐", "癫痫发作", "惊厥"]                        │  │
│  │ 阈值: cosine > 0.75 → 标准化映射                           │  │
│  └────────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌──────────────────────────────────────────────────────────────────┐
│            Layer 2: 方言词汇转换 (Dialect Normalization)           │
│  ┌────────────────────────────────────────────────────────────┐  │
│  │ 四川话词典 │ 粤语词典 │ 其他方言词典                          │  │
│  │ "脑阔"→"头" │ "扯风"→"抽搐" │ "闷倒"→"发作"               │  │
│  └────────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌──────────────────────────────────────────────────────────────────┐
│            Layer 3: 口语症状解析 (Colloquial Symptom Parsing)      │
│  ┌────────────────────────────────────────────────────────────┐  │
│  │ 口语表达 → 标准医学描述                                     │  │
│  │ "嘴巴流口水" → "口角流涎"                                  │  │
│  │ "手脚不听使唤" → "四肢不自主运动"                           │  │
│  └────────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌──────────────────────────────────────────────────────────────────┐
│              Layer 4: 身体部位标准化 (Body Part Normalization)      │
│  ┌────────────────────────────────────────────────────────────┐  │
│  │ "小手臂" → "左/右前臂" (需要结合上下文判断左右)             │  │
│  │ 部位关系图谱辅助消歧                                        │  │
│  └────────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌──────────────────────────────────────────────────────────────────┐
│                    标准医学文本输出                                │
│     "头痛（剧烈），伴四肢抽搐"                                      │
└──────────────────────────────────────────────────────────────────┘
```

#### 3.2.3 方言词典设计

```python
# 方言词典数据结构
class DialectEntry:
    dialect: str              # 方言类型: "sichuan", "cantonese", "hakka", ...
    source: str              # 原始词汇
    normalized: str          # 标准普通话
    medical_term: str        # 标准化医学术语
    category: str            # 类别: "symptom", "body_part", "verb", "expression"
    confidence: float        # 置信度 0-1
    examples: list[str]      # 用法示例

# 核心方言词典（四川话为主）
SICHUAN_DIALECT_DICT: list[DialectEntry] = [
    # 症状类
    DialectEntry("sichuan", "扯风", "抽搐", "convulsion", 0.95, ["他又在扯风了"]),
    DialectEntry("sichuan", "闷倒", "突然发作", "sudden_onset", 0.85, ["他闷倒就倒了"]),
    DialectEntry("sichuan", "抠脚", "抽搐（部分地区）", "convulsion", 0.6, ["脚一直在抠"]),
    DialectEntry("sichuan", "甩不到符", "不能控制", "uncontrollable", 0.9, ["手甩不到符"]),
    DialectEntry("sichuan", "神志不清", "意识障碍", "consciousness_disorder", 0.95, []),
    DialectEntry("sichuan", "口吐泡泡", "口吐白沫", "foaming_at_mouth", 0.9, ["嘴巴吐泡泡"]),
    DialectEntry("sichuan", "脑壳痛", "头痛", "headache", 0.98, ["脑壳痛得很"]),
    DialectEntry("sichuan", "脑阔痛", "头痛", "headache", 0.95, ["脑阔痛啷个办"]),
    DialectEntry("sichuan", "惊爪爪", "惊慌、惊厥", "panic/seizure", 0.7, ["吓得惊爪爪的"]),
    # 身体部位类
    DialectEntry("sichuan", "小手臂", "前臂", "forearm", 0.95, ["小手臂起了水泡"]),
    DialectEntry("sichuan", "脚杆", "小腿", "lower_leg", 0.9, ["脚杆疼"]),
    DialectEntry("sichuan", "颈子", "颈部", "neck", 0.98, ["颈子硬"]),
    DialectEntry("sichuan", "kuǎi子", "大腿", "thigh", 0.85, ["kuǎi子疼"]),
    # 时间频率类
    DialectEntry("sichuan", "有好久", "多久", "duration", 0.9, ["有好久了"]),
    DialectEntry("sichuan", "啷个", "怎么", "how", 0.98, ["啷个办", "啷个回事"]),
    DialectEntry("sichuan", "囊个", "怎么", "how", 0.9, ["囊个整"]),
    # 程度副词
    DialectEntry("sichuan", "黑死人了", "非常吓人", "very_frightening", 0.9, []),
    DialectEntry("sichuan", "好黑人", "很吓人", "frightening", 0.85, []),
]

# 口语症状表达映射
COLLOQUIAL_SYMPTOM_MAP: dict[str, str] = {
    "昏过去了": "意识丧失",
    "晕过去了": "意识丧失",
    "倒下去了": "跌倒/晕厥",
    "嘴巴流口水": "口角流涎",
    "口水淌": "流涎",
    "眼睛翻": "眼球上翻",
    "牙关紧咬": "牙关紧闭",
    "手脚僵起": "四肢僵硬",
    "手脚不听使唤": "四肢不自主运动",
    "人不舒服": "不适",
    "遭不住": "不能耐受",
    "造孽得很": "症状严重",
    "没得力气": "乏力",
    "心子把把痛": "心前区疼痛",
    "肚子痛": "腹痛",
    "脑壳晕": "头晕",
    "眼睛发黑": "黑矇",
}
```

#### 3.2.4 医学术语扩展

```python
# 症状同义词扩展词表（用于检索增强）
SYMPTOM_SYMPTOM_EXPANSION: dict[str, list[str]] = {
    "头痛": ["头疼", "头部疼痛", "头痛", "headache", "cephalalgia", "cranialgia"],
    "抽搐": ["抽风", "抽搐", "惊厥", "convulsion", "seizure", "twitching", "痉挛"],
    "意识丧失": ["昏迷", "昏厥", "不省人事", "unconscious", "LOC", "loss_of_consciousness"],
    "口角流涎": ["流口水", "流涎", "口涎外溢", "drooling", "hypersalivation", "sialorrhea"],
    "四肢麻木": ["手脚麻木", "四肢发麻", "limb numbness", "paresthesia"],
    "癫痫发作": ["癫痫", "发作", "seizure", "epileptic_seizure", "fit"],
    "肌阵挛": ["肌肉抽动", "myoclonus", "muscle_jerk"],
    "失神": ["愣神", "发呆", "意识短暂丧失", "absence_seizure", "staring_spells"],
}

# 身体部位标准化
BODY_PART_NORMALIZATION: dict[str, dict[str, str]] = {
    "头部": {"标准": "头部", "细分": ["前额", "颞部", "顶部", "枕部", "面部"]},
    "上肢": {"标准": "上肢", "细分": ["肩部", "上臂", "肘部", "前臂", "手腕", "手部", "手指"]},
    "下肢": {"标准": "下肢", "细分": ["髋部", "大腿", "膝部", "小腿", "踝部", "足部", "脚趾"]},
    "腹部": {"标准": "腹部", "细分": ["上腹部", "中腹部", "下腹部", "脐周"]},
}
```

#### 3.2.5 口语规范化处理器

```python
class DialectNormalizer:
    """
    方言与口语规范化处理器
    采用多级管道（Pipeline）架构，每级专注一个转换任务
    """

    def __init__(
        self,
        dialect_dict: list[DialectEntry] = None,
        symptom_map: dict[str, str] = None,
        embedder: BgeM3Embedder = None,
    ):
        self.dialect_dict = dialect_dict or SICHUAN_DIALECT_DICT
        self.symptom_map = symptom_map or COLLOQUIAL_SYMPTOM_MAP
        self.embedder = embedder
        self._build_dialect_index()

    def _build_dialect_index(self):
        """构建方言词典索引，加速匹配"""
        self._exact_match_index: dict[str, DialectEntry] = {}
        self._category_index: dict[str, list[DialectEntry]] = {}

        for entry in self.dialect_dict:
            # 精确匹配索引
            self._exact_match_index[entry.source] = entry

            # 分类索引
            if entry.category not in self._category_index:
                self._category_index[entry.category] = []
            self._category_index[entry.category].append(entry)

    def normalize(self, text: str) -> NormalizationResult:
        """
        完整规范化流程
        返回：规范化文本 + 提取的医学实体 + 变换历史
        """
        current_text = text
        medical_entities = []
        transformations = []

        # Stage 1: 医学术语标准化
        current_text, entities1, trans1 = self._normalize_medical_terms(current_text)
        medical_entities.extend(entities1)
        transformations.extend(trans1)

        # Stage 2: 方言词汇转换
        current_text, entities2, trans2 = self._normalize_dialect_words(current_text)
        medical_entities.extend(entities2)
        transformations.extend(trans2)

        # Stage 3: 口语症状解析
        current_text, entities3, trans3 = self._normalize_colloquial(current_text)
        medical_entities.extend(entities3)
        transformations.extend(trans3)

        # Stage 4: 身体部位标准化
        current_text, entities4, trans4 = self._normalize_body_parts(current_text)
        medical_entities.extend(entities4)
        transformations.extend(trans4)

        # Stage 5: 向量相似度兜底（处理未知方言）
        current_text, entities5, trans5 = self._normalize_fuzzy(current_text)
        medical_entities.extend(entities5)
        transformations.extend(trans5)

        return NormalizationResult(
            original_text=text,
            normalized_text=current_text,
            medical_entities=medical_entities,
            transformations=transformations,
        )

    def _normalize_dialect_words(self, text: str) -> tuple[str, list[MedicalEntity], list[Transformation]]:
        """方言词汇转换（基于词典的贪婪匹配）"""
        result = text
        entities = []
        transformations = []

        # 从最长匹配到最短，避免"小手臂"被"手臂"截断
        sorted_entries = sorted(
            self._exact_match_index.items(),
            key=lambda x: len(x[0]),
            reverse=True,
        )

        for dialect_word, entry in sorted_entries:
            if dialect_word in result:
                result = result.replace(dialect_word, entry.normalized)
                entities.append(MedicalEntity(
                    text=dialect_word,
                    normalized=entry.normalized,
                    medical_term=entry.medical_term,
                    category=entry.category,
                    confidence=entry.confidence,
                ))
                transformations.append(Transformation(
                    stage="dialect_normalization",
                    original=dialect_word,
                    replacement=entry.normalized,
                    confidence=entry.confidence,
                ))

        return result, entities, transformations
```

---

### 3.3 Phase 3: 指代消解（Coreference Resolution）

#### 3.3.1 问题分析

V1 中"小手臂起了水泡，模型回复中又问哪个位置"的问题，本质是**指代消解（Coreference Resolution）**缺失。

具体场景：
- 用户："我手昨天烫伤了，小手臂起了水泡"
- 系统应记住：水泡位置 = 小手臂（前臂）
- 用户追问："哪个位置？"→ 系统应知道用户在问之前提到的"小手臂"
- 如果系统不知道"小手臂"已经被回答，就会重复询问

#### 3.3.2 指代消解策略

```python
class CoreferenceResolver:
    """
    指代消解器：解决代词、指示词、指别词指向哪个实体
    医疗场景专用的指代消解规则
    """

    # 医疗场景高频指代词
    MEDICAL_PRONOUNS = {
        "这": "当前提到的症状/部位",
        "那": "之前提到的症状/部位",
        "它": "前一句的主语",
        "这个": "刚提到的实体",
        "那个": "之前提到的实体",
        "这里": "身体部位",
        "那里": "身体部位",
        "这儿": "身体部位",
        "那儿": "身体部位",
        "哪儿": "需要追问",
        "哪个位置": "需要追问或引用",
        "上次": "既往病史中的时间",
        "那会儿": "既往病史中的时间",
    }

    def resolve(
        self,
        current_utterance: str,
        conversation_history: list[Turn],
        current_slots: dict[str, Any],
    ) -> ResolvedUtterance:
        """
        指代消解主流程：
        1. 检测指代词
        2. 查找候选实体（前文提到的身体部位、症状等）
        3. 选择最可能的实体
        4. 替换指代词
        """
        resolved = current_utterance
        resolved_entities = []
        coreference_chains = []

        # Step 1: 检测指代词
        pronouns = self._detect_pronouns(current_utterance)

        for pronoun in pronouns:
            # Step 2: 在上下文中寻找候选实体
            candidate = self._find_candidate_entity(
                pronoun=pronoun,
                history=conversation_history,
                current_slots=current_slots,
            )

            if candidate:
                # Step 3: 替换指代词
                resolved = self._replace_pronoun(resolved, pronoun, candidate)

                resolved_entities.append(ResolvedEntity(
                    pronoun=pronoun,
                    resolved_to=candidate["text"],
                    entity_type=candidate["type"],
                    source_turn=candidate["turn_index"],
                ))

                coreference_chains.append(CoreferenceChain(
                    pronoun=pronoun,
                    antecedent=candidate["text"],
                    entity_type=candidate["type"],
                ))

        return ResolvedUtterance(
            original=current_utterance,
            resolved=resolved,
            resolved_entities=resolved_entities,
            coreference_chains=coreference_chains,
        )

    def _find_candidate_entity(
        self,
        pronoun: str,
        history: list[Turn],
        current_slots: dict[str, Any],
    ) -> dict | None:
        """
        寻找指代词指向的实体
        优先级：当前槽位 > 最近轮次 > 较早轮次
        """
        # 检查当前已收集的槽位
        body_parts_in_slots = self._extract_body_parts(current_slots)
        symptoms_in_slots = self._extract_symptoms(current_slots)

        # 时间相关的指代
        if pronoun in ["上次", "那会儿", "那时候"]:
            return self._find_time_reference(history)

        # 位置相关的指代
        if pronoun in ["哪儿", "哪里", "哪个位置", "哪儿的位置"]:
            # 优先使用最近提到的身体部位
            for turn in reversed(history):
                body_parts = self._extract_body_parts_from_text(turn.user_message)
                if body_parts:
                    return {
                        "text": body_parts[0],
                        "type": "body_part",
                        "turn_index": history.index(turn),
                    }
            # 其次使用槽位
            if body_parts_in_slots:
                return {
                    "text": body_parts_in_slots[-1],
                    "type": "body_part",
                    "turn_index": -1,
                }

        # 症状相关的指代
        if pronoun in ["这个症状", "那种情况", "它"]:
            for turn in reversed(history):
                symptoms = self._extract_symptoms_from_text(turn.user_message)
                if symptoms:
                    return {
                        "text": symptoms[0],
                        "type": "symptom",
                        "turn_index": history.index(turn),
                    }

        # 默认：使用最近提到的身体部位
        for turn in reversed(history):
            body_parts = self._extract_body_parts_from_text(turn.user_message)
            if body_parts:
                return {
                    "text": body_parts[0],
                    "type": "body_part",
                    "turn_index": history.index(turn),
                }

        return None
```

---

### 3.4 Phase 4: GraphRAG 医疗知识图谱

#### 3.4.1 为什么需要 GraphRAG

传统向量 RAG 的核心局限：**缺乏结构化推理能力**。

以问题"抽搐伴意识丧失可能是什么病？"为例：

| 检索方式 | 召回内容 | 局限性 |
|---------|---------|--------|
| 向量检索 | 分散的段落，可能没有直接关联 | 不知道"抽搐"和"意识丧失"的关系 |
| GraphRAG | 从知识图谱中检索"抽搐-是症状→癫痫"等路径 | 能推理出组合症状的含义 |

#### 3.4.2 医疗知识图谱设计

```python
# ============================================================
# 医疗知识图谱 Schema
# ============================================================

class MedicalNodeType(Enum):
    DISEASE          # 疾病（癫痫、全面性发作等）
    SYMPTOM          # 症状（抽搐、意识丧失等）
    DRUG             # 药物（左乙拉西坦、丙戊酸钠等）
    LAB_EXAM         # 检查（脑电图、CT、MRI等）
    BODY_PART        # 身体部位（脑部、四肢等）
    PATIENT          # 患者（实体，关联病历）
    CLINICAL_CASE    # 临床病例
    GUIDELINE        # 临床指南
    TREATMENT        # 治疗方案
    TRIGGER          # 诱因/触发因素

class MedicalEdgeType(Enum):
    HAS_SYMPTOM      # 疾病-症状关系：癫痫→抽搐
    CAUSES           # 诱因关系：睡眠不足→癫痫发作
    TREATS           # 治疗关系：左乙拉西坦→癫痫
    REQUIRES_EXAM    # 检查关系：疑似癫痫→脑电图
    COMPLICATES      # 并发关系：癫痫持续状态→脑损伤
    INTERACTS        # 药物相互作用
    DIFFERENTIATES   # 鉴别诊断
    FOLLOWED_BY      # 发作后状态
    IS_A             # 上下位关系：全身性发作→癫痫

# 节点定义
@dataclass
class MedicalNode:
    node_id: str
    node_type: MedicalNodeType
    name: str                       # 标准名称
    aliases: list[str]               # 别名/缩写（扩展检索）
    description: str                 # 简短描述
    properties: dict[str, Any]       # 额外属性
    evidence_refs: list[str]          # 证据来源

# 边定义
@dataclass
class MedicalEdge:
    edge_id: str
    source_id: str
    target_id: str
    edge_type: MedicalEdgeType
    weight: float                    # 关系强度（0-1）
    description: str
    evidence_refs: list[str]

# ============================================================
# 医疗知识图谱构建
# ============================================================
class MedicalKnowledgeGraphBuilder:
    """
    从医学文献和临床病历中自动构建知识图谱
    采用 LLM + 规则混合抽取策略
    """

    def __init__(self, llm: LLMClient, ner_model=None):
        self.llm = llm
        self.ner_model = ner_model

    def extract_from_text(self, text: str, source_type: str) -> tuple[list[MedicalNode], list[MedicalEdge]]:
        """
        从文本中抽取医学实体和关系
        使用 LLM 进行三元组抽取
        """
        extraction_prompt = f"""你是一个医学知识抽取专家。请从以下医学文本中抽取实体和关系。

        实体类型：疾病(DISEASE)、症状(SYMPTOM)、药物(DRUG)、检查(LAB_EXAM)、身体部位(BODY_PART)、诱因(TRIGGER)

        关系类型：
        - HAS_SYMPTOM：疾病具有某症状（如：癫痫 HAS_SYMPTOM 抽搐）
        - CAUSES：诱因导致疾病或发作（如：睡眠不足 CAUSES 癫痫发作）
        - TREATS：药物治疗疾病（如：左乙拉西坦 TREATS 癫痫）
        - REQUIRES_EXAM：诊断需要检查（如：疑似癫痫 REQUIRES_EXAM 脑电图）
        - DIFFERENTIATES：需要鉴别诊断（如：癫痫 DIFFERENTIATES 癔症）

        输出JSON格式：
        {{
            "nodes": [
                {{"id": "e1", "type": "SYMPTOM", "name": "抽搐", "aliases": ["抽风", "惊厥"]}},
                ...
            ],
            "edges": [
                {{"source": "e1", "target": "d1", "type": "HAS_SYMPTOM", "weight": 0.95}},
                ...
            ]
        }}

        文本：
        {text}
        """

        raw = self.llm.chat(
            [{"role": "user", "content": extraction_prompt}],
            temperature=0.0,
            json_mode=True,
            max_tokens=2048,
        )
        data = safe_json_loads(raw)
        return self._parse_extraction(data, source_type)
```

#### 3.4.3 GraphRAG 检索策略

```python
class GraphRAGRetriever:
    """
    GraphRAG 检索器：结合知识图谱和向量检索
    支持三种检索模式：
    1. Local Search：围绕特定实体展开
    2. Global Search：基于社区的全局推理
    3. Hybrid Search：图谱 + 向量混合
    """

    def __init__(
        self,
        graph_db,        # Neo4j / NebulaGraph
        vector_store,
        llm: LLMClient,
    ):
        self.graph_db = graph_db
        self.vector_store = vector_store
        self.llm = llm

    def retrieve(
        self,
        query: str,
        mode: str = "hybrid",  # "local" | "global" | "hybrid"
        top_k: int = 6,
    ) -> list[RetrievalResult]:
        if mode == "local":
            return self._local_search(query, top_k)
        elif mode == "global":
            return self._global_search(query, top_k)
        else:
            return self._hybrid_search(query, top_k)

    def _local_search(self, query: str, top_k: int) -> list[RetrievalResult]:
        """
        Local Search：围绕查询中识别的实体展开
        步骤：
        1. 实体识别：从查询中识别医学实体
        2. 图谱扩展：从实体节点向外扩展N跳
        3. 上下文收集：收集关联节点和边的信息
        4. 向量补充：用原始查询在扩展子图上做向量检索
        """
        # Step 1: 实体识别
        entities = self._recognize_medical_entities(query)

        if not entities:
            # 无实体，回退到纯向量检索
            return self.vector_store.retrieve(query, top_k)

        # Step 2: 图谱扩展
        expanded_nodes = set()
        expanded_edges = set()

        for entity in entities:
            # 扩展 2 跳
            neighbors = self.graph_db.expand(
                start_node=entity["id"],
                depth=2,
                edge_types=[
                    MedicalEdgeType.HAS_SYMPTOM,
                    MedicalEdgeType.CAUSES,
                    MedicalEdgeType.TREATS,
                    MedicalEdgeType.DIFFERENTIATES,
                ],
            )
            expanded_nodes.update(neighbors["nodes"])
            expanded_edges.update(neighbors["edges"])

        # Step 3: 构建子图上下文
        subgraph_context = self._build_subgraph_context(
            nodes=expanded_nodes,
            edges=expanded_edges,
        )

        # Step 4: 用子图上下文 + 原始查询做向量检索
        combined_query = f"{query}\n\n相关医学知识：\n{subgraph_context}"
        return self.vector_store.retrieve(combined_query, top_k)

    def _global_search(self, query: str, top_k: int) -> list[RetrievalResult]:
        """
        Global Search：基于社区检测的全局推理
        用于回答需要综合多种医学知识的复杂问题
        例如："癫痫的诊断和治疗原则是什么？"
        """
        # Step 1: 识别查询涉及的主题社区
        communities = self.graph_db.get_communities_by_theme(query)

        # Step 2: 每个社区生成摘要
        community_summaries = []
        for comm in communities:
            summary = self._generate_community_summary(comm)
            community_summaries.append(summary)

        # Step 3: 从每个社区检索最相关的段落
        results = []
        for summary in community_summaries:
            # 在该社区的上下文中检索
            community_query = f"{query}\n\n社区摘要：{summary}"
            hits = self.vector_store.retrieve(community_query, top_k // len(communities))
            results.extend(hits)

        return results

    def _hybrid_search(self, query: str, top_k: int) -> list[RetrievalResult]:
        """
        Hybrid Search：图谱 + 向量的混合检索
        策略：并行执行 local search 和向量检索，结果融合
        """
        # Step 1: 提取当前对话中的实体（如果有上下文）
        current_entities = getattr(self, "current_entities", [])

        # Step 2: 从查询和上下文中识别实体
        all_entities = current_entities + self._recognize_medical_entities(query)

        # Step 3: 如果有实体，走 local search
        if all_entities:
            local_results = self._local_search_with_entities(query, all_entities, top_k)
        else:
            local_results = []

        # Step 4: 纯向量检索作为补充
        vector_results = self.vector_store.retrieve(query, top_k)

        # Step 5: RRFF 融合
        fused = self._rrff_fusion(local_results, vector_results, k=60)
        return fused[:top_k]
```

#### 3.4.4 自学习知识图谱

```python
class SelfLearningGraphUpdater:
    """
    自学习机制：通过医患对话和真实病历持续更新知识图谱
    """

    def __init__(self, graph_db, llm: LLMClient):
        self.graph_db = graph_db
        self.llm = llm
        self.update_queue = []

    def process_conversation(
        self,
        conversation: list[Turn],
        final_diagnosis: str,
        treatment_plan: str,
    ):
        """
        从一次问诊对话中学习：
        1. 从对话中抽取新的症状-疾病关联
        2. 更新患者的症状图谱
        3. 记录罕见案例
        """
        # Step 1: 提取对话中的症状组合
        symptoms = self._extract_symptom_cluster(conversation)

        # Step 2: 验证症状-疾病关联是否存在
        for symptom in symptoms:
            exists = self.graph_db.check_edge(
                source_type=MedicalNodeType.SYMPTOM,
                source_name=symptom,
                edge_type=MedicalEdgeType.HAS_SYMPTOM,
                target_name=final_diagnosis,
            )
            if not exists:
                # 记录为候选关系，需要专家审核
                self.update_queue.append(KnowledgeCandidate(
                    source_type="conversation",
                    source_node=symptom,
                    target_node=final_diagnosis,
                    edge_type=MedicalEdgeType.HAS_SYMPTOM,
                    confidence=self._calculate_confidence(conversation),
                    evidence=conversation,
                ))

        # Step 3: 更新患者个人图谱
        self._update_patient_graph(conversation, final_diagnosis)

    def process_clinical_note(self, clinical_note: dict):
        """
        从电子病历中学习：
        1. 抽取结构化病历中的实体和关系
        2. 更新疾病-症状图谱
        3. 发现新的诱因关系
        """
        # 使用 NER + 关系抽取
        ...
```

---

### 3.5 Phase 5: 医疗对话生成器（Doctor-Style）

#### 3.5.1 设计原则

真实的医生问诊风格有以下特点，V2 的生成器需要体现：

| 医生风格特点 | V1 问题 | V2 改进 |
|------------|---------|---------|
| 温和、鼓励性语气 | 冷漠机械 | 添加同理心表达 |
| 主动告知已收集信息 | 重复询问 | 显示理解摘要 |
| 追问关键缺失信息 | 随意跳转 | 基于症状引导图追问 |
| 不确定性时坦诚告知 | 过度自信导致幻觉 | 明确区分已知/未知 |
| 急危重症立即干预 | 无急危重症检测 | 独立的紧急干预流程 |
| 专业但易懂 | 术语堆砌 | 术语+通俗解释 |

#### 3.5.2 医生风格生成器

```python
class DoctorStyleGenerator:
    """
    医生风格回复生成器
    核心改进：多轮追问、主动确认、急危重症优先
    """

    def __init__(
        self,
        llm: LLMClient,
        dialogue_state: ConversationState,
        graph_retriever: GraphRAGRetriever,
    ):
        self.llm = llm
        self.state = dialogue_state
        self.graph_retriever = graph_retriever

    def generate_response(
        self,
        user_input: str,
        resolved_input: str,  # 指代消解后的输入
        context: list[Evidence],
    ) -> GenerationResult:
        """
        生成医生风格的回复
        """
        # Step 1: 判断是否需要紧急干预
        if self._is_emergency(user_input, resolved_input):
            return self._generate_emergency_response()

        # Step 2: 判断当前处于问诊的哪个阶段
        current_phase = self._get_current_phase()

        # Step 3: 根据阶段生成对应风格的回复
        if current_phase == Phase.SYMPTOM_COLLECTION:
            return self._generate_symptom_collection_response(
                user_input, resolved_input, context
            )
        elif current_phase == Phase.MEDICAL_HISTORY:
            return self._generate_history_response(user_input, context)
        elif current_phase == Phase.PRELIMINARY_DIAGNOSIS:
            return self._generate_diagnosis_response(context)
        elif current_phase == Phase.FOLLOW_UP:
            return self._generate_follow_up_response()
        else:
            return self._generate_general_response(user_input, context)

    def _generate_symptom_collection_response(
        self,
        user_input: str,
        resolved_input: str,
        context: list[Evidence],
    ) -> GenerationResult:
        """
        症状收集阶段的回复策略：
        1. 先确认理解到的信息（主动反馈）
        2. 再追问下一个关键问题
        3. 避免重复已收集的信息
        """
        # 构建理解确认
        confirmation = self._build_symptom_confirmation()

        # 确定下一个追问
        next_question = self._decide_next_symptom_question()

        # 生成回复
        prompt = DOCTOR_SYMPTOM_PROMPT.format(
            confirmed_symptoms=confirmation,
            next_question=next_question,
            user_input=resolved_input,
            evidence=context,
            doctor_persona=self._get_doctor_persona(),
        )

        response = self.llm.chat(
            [{"role": "system", "content": prompt}],
            temperature=0.3,
            max_tokens=512,
        )

        return GenerationResult(
            response=response,
            intent=Intent.SYMPTOM_FOLLOW_UP,
            collected_info=self._extract_new_slots(resolved_input),
            next_node=self._get_next_node(),
        )

    def _build_symptom_confirmation(self) -> str:
        """
        构建对已收集症状的理解确认
        风格："我理解到您说的是……"
        """
        if not self.state.collected_slots:
            return ""

        confirmation_parts = []
        for slot_name, value in self.state.collected_slots.items():
            slot_info = SYMPTOM_SLOTS.get(slot_name, {})
            slot_label = slot_info.get("label", slot_name)
            confirmation_parts.append(f"{slot_label}：{value}")

        return "，".join(confirmation_parts)

    def _decide_next_symptom_question(self) -> str:
        """
        决定下一个追问
        遵循"最重要信息优先"原则
        """
        # 获取缺失的必填槽位
        missing = self._get_missing_required_slots()

        # 按医学重要性排序
        priority_order = [
            "chief_complaint",      # 主诉
            "seizure_duration",      # 发作持续时间
            "loss_of_consciousness", # 意识
            "seizure_type",          # 发作类型
            "post_ictal_state",      # 发作后状态
            "frequency",             # 发作频率
            "triggers",              # 诱因
        ]

        for slot in priority_order:
            if slot in missing:
                return self._get_question_for_slot(slot)

        return "请问还有没有其他不舒服的地方？"
```

#### 3.5.3 医生风格 Prompt

```python
DOCTOR_SYMPTOM_PROMPT = """你是一位有丰富临床经验的癫痫专科医生，正在对患者进行问诊。

【问诊原则】
1. 主动确认你理解到的信息，让患者知道你在认真倾听
2. 追问要具体、有医学依据，避免跳跃性提问
3. 语气温和、专业、有同理心
4. 避免重复询问患者已经回答过的问题
5. 如果患者描述的症状可能是急危重症（如发作超过5分钟），立即给出紧急建议
6. 医学术语后附带通俗解释，确保患者理解

【当前问诊进度】
{progress_bar}

【已收集到的信息】
{confirmed_symptoms}

【你正要追问】
{next_question}

【患者刚才说的话】
{user_input}

【参考医学知识】
{evidence}

【输出要求】
请生成一句医生的回复，要求：
1. 先确认你理解到的信息（如有）
2. 然后提出下一个具体问题
3. 语气温和专业，如同面对面问诊
4. 如果判断可能是急危重症，在回复中包含紧急提示

【医生角色设定】
- 温和但不失专业
- 耐心倾听，不打断
- 追问精准，不问无关问题
- 关注患者情绪，适时安慰
"""

DOCTOR_DIAGNOSIS_PROMPT = """你是一位癫痫专科医生，根据收集到的症状信息给出初步分析。

【已收集的完整信息】
{collected_info}

【问诊对话历史】
{conversation_history}

【相关医学证据】
{evidence}

【输出要求】
请按以下格式输出：
1. 【初步分析】：基于症状组合的可能诊断
2. 【诊断依据】：支持该诊断的证据
3. 【需要进一步确认】：还需要哪些信息来完善诊断
4. 【建议】：下一步应该做什么（检查、用药调整、线下就医等）

注意：
- 区分"很可能"、"可能"、"不能排除"等确定性程度
- 涉及急危重症立即建议线下就医
- 不要过度诊断或过度建议
"""
```

---

### 3.6 Phase 6: 性能与缓存优化

#### 3.6.1 多级缓存架构

```
┌──────────────────────────────────────────────────────────────────────┐
│                         多级缓存架构                                   │
│                                                                      │
│  请求 → L1 Redis (对话状态, TTL=30min)                                │
│         │ miss                                                       │
│         ▼                                                            │
│     L2 Embedding Cache (语义缓存, TTL=24h)                          │
│         │ miss                                                       │
│         ▼                                                            │
│     L3 KB Snapshot Cache (向量索引快照, TTL=1h)                       │
│         │ miss                                                       │
│         ▼                                                            │
│     全量检索流程                                                      │
│                                                                      │
└──────────────────────────────────────────────────────────────────────┘
```

```python
class SemanticCache:
    """
    语义缓存：基于向量相似度的请求缓存
    避免相同/相似问题重复推理
    """

    def __init__(
        self,
        redis_client,
        embedder: BgeM3Embedder,
        similarity_threshold: float = 0.92,
        ttl_seconds: int = 86400,
    ):
        self.redis = redis_client
        self.embedder = embedder
        self.similarity_threshold = similarity_threshold
        self.ttl = ttl_seconds

    def get_or_compute(
        self,
        query: str,
        compute_fn: Callable[[str], Any],
    ) -> CacheResult:
        """
        语义缓存查找：
        1. 对查询向量化
        2. 在缓存中找相似度 > 阈值的记录
        3. 命中则返回缓存结果，否则计算并缓存
        """
        # Step 1: 向量化
        query_vec = self.embedder.encode_dense([query])[0]

        # Step 2: 扫描缓存中所有 key，计算相似度
        cache_keys = self.redis.keys("semantic_cache:*")
        best_match = None
        best_score = 0.0

        for key in cache_keys:
            cached_vec = self.redis.hget(key, "vector")
            if cached_vec:
                similarity = cosine_similarity(query_vec, json.loads(cached_vec))
                if similarity > best_score:
                    best_score = similarity
                    best_match = (key, similarity)

        # Step 3: 命中检查
        if best_match and best_score >= self.similarity_threshold:
            cached_result = self.redis.hgetall(best_match[0])
            return CacheResult(
                hit=True,
                result=json.loads(cached_result["result"]),
                similarity_score=best_score,
            )

        # Step 4: 未命中，计算并缓存
        result = compute_fn(query)
        result_vec = self.embedder.encode_dense([query])[0]

        cache_key = f"semantic_cache:{hashlib.md5(query.encode()).hexdigest()}"
        self.redis.hset(cache_key, mapping={
            "query": query,
            "vector": json.dumps(result_vec),
            "result": json.dumps(result),
            "created_at": time.time(),
        })
        self.redis.expire(cache_key, self.ttl)

        return CacheResult(hit=False, result=result, similarity_score=0.0)
```

#### 3.6.2 小模型快速预判

```python
class QuickTriageModel:
    """
    轻量级预判模型：使用 Qwen3-8B 做快速分类
    避免每次都调用大模型做完整推理
    """

    def __init__(
        self,
        model_path: str = "Qwen/Qwen3-8B",
        vllm_server: str = "http://127.0.0.1:8001/v1",  # 独立的小模型服务
    ):
        self.client = OpenAI(api_key="EMPTY", base_url=vllm_server)

    def quick_classify(
        self,
        query: str,
        intent_types: list[str] = None,
    ) -> ClassificationResult:
        """
        快速分类（<500ms）：
        1. 意图分类（症状咨询 / 用药咨询 / 紧急情况 / 闲聊）
        2. 紧迫性评估
        3. 是否需要多轮对话
        """
        prompt = f"""快速分类以下患者问题（只回答JSON，不需要解释）：
{{
    "intent": "symptom|medication|emergency|general",  // 主要意图
    "urgency": "critical|high|medium|low",             // 紧迫性
    "needs_multi_turn": true|false,                      // 是否需要多轮对话
    "key_symptoms": [],                                  // 识别到的关键症状
    "emergency_signs": []                                 // 急危重症迹象
}}

问题：{query}
"""
        resp = self.client.chat.completions.create(
            model="Qwen3-8B",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0,
            max_tokens=256,
        )
        return safe_json_loads(resp.choices[0].message.content)
```

---

### 3.7 Phase 7: 生产化与评测体系

#### 3.7.1 测试体系设计

```
tests/
├── unit/                           # 单元测试
│   ├── test_dialect_normalizer.py   # 方言规范化测试
│   ├── test_coreference.py          # 指代消解测试
│   ├── test_conversation_state.py   # 对话状态测试
│   ├── test_graph_extraction.py     # 知识图谱抽取测试
│   ├── test_chunking.py             # 分块策略测试
│   ├── test_retriever.py            # 检索器测试
│   └── test_safety_guard.py         # 安全护栏测试
├── integration/                    # 集成测试
│   ├── test_api_endpoints.py        # API 端点测试
│   ├── test_conversation_flow.py    # 完整对话流测试
│   └── test_ingestion_pipeline.py   # 入库流程测试
├── e2e/                           # 端到端测试
│   ├── test_doctor_consultation.py  # 医生问诊场景测试
│   └── test_emergency_detection.py  # 急危重症检测测试
├── performance/                   # 性能测试
│   ├── test_latency.py             # 延迟测试
│   ├── test_throughput.py          # 吞吐量测试
│   └── test_cache_hit_rate.py      # 缓存命中率测试
└── fixtures/                      # 测试数据
    ├── dialect_test_cases.json
    ├── conversation_test_cases.json
    └── medical_corpus_sample.json
```

#### 3.7.2 自动化评估指标

> **FUTURE/HYPOTHETICAL — NOT IMPLEMENTED BY THE CURRENT ENDPOINT**：以下字典是未来评估 taxonomy，包含对话、医学准确性、安全和用户体验等拟议指标；它不表示当前已采集、已验证或达到任何指标。当前 legacy `/v1/eval/ragas` 只运行 `deterministic_lexical/token_overlap_v1`，对 ground truth 与 retrieved contexts 的 context-hit ratio 和 ground-truth token coverage 做样本宏平均，且不评估 `response`。因此当前结果不能替代下列 response-level、人工或临床评估。

```python
# V2 未来评估指标体系（规划，不是当前输出）
V2_EVALUATION_METRICS = {
    # 对话质量
    "conversation_metrics": {
        "turn_completion_rate": "每个问诊节点完成的比率",
        "redundancy_rate": "重复询问同一信息的比率",
        "context_continuity_score": "上下文连贯性评分（人工/自动）",
        "avg_turns_to_diagnosis": "从开始到给出初步诊断的平均轮次",
    },
    # 医学准确性
    "medical_accuracy": {
        "symptom_extraction_accuracy": "症状提取准确率",
        "dialect_recognition_rate": "方言识别率",
        "coreference_resolution_accuracy": "指代消解准确率",
        "diagnosis_relevance_score": "诊断相关性评分",
        "evidence_recall": "证据召回率",
    },
    # 安全与合规
    "safety_metrics": {
        "emergency_detection_recall": "急危重症召回率（最重要！）",
        "false_negative_emergency": "漏检急危重症次数",
        "disclaimer_presence_rate": "免责声明出现率",
        "hallucination_rate": "幻觉率（编造信息的比率）",
    },
    # 用户体验
    "ux_metrics": {
        "user_satisfaction_score": "用户满意度评分",
        "p50_latency_ms": "P50 响应延迟",
        "p95_latency_ms": "P95 响应延迟",
        "cache_hit_rate": "缓存命中率",
    },
}
```

---

### 3.8 Phase 8: 多源文档处理流水线

#### 3.8.1 文档类型与分块策略矩阵

| 文档来源 | 格式 | 特点 | 推荐分块策略 |
|---------|------|------|------------|
| 医学文献（指南/共识） | PDF | 结构化、章节清晰 | 父子分块 + 语义标题分段 |
| 临床病历 | 结构化/半结构化 | 高重复性、模板化 | 模板感知分块 |
| 检查报告（脑电图/MRI） | PDF/图片 | 包含图像、模板化 | 表格分块 + OCR |
| 药品说明书 | PDF/网页 | 固定结构 | 固定字段提取 |
| 患者自述 | 自由文本 | 口语化、碎片化 | 句子级分块 |
| 医学教材 | PDF | 长段落、深度内容 | 语义段落分块 |

#### 3.8.2 统一分块工厂

```python
class ChunkingFactory:
    """
    文档分块工厂：根据文档类型选择最优分块策略
    """

    STRATEGIES = {
        "guideline": ParentChildChunking(
            parent_size=1600,
            child_size=360,
            semantic_split=True,  # 按章节分割
        ),
        "clinical_note": TemplateAwareChunking(
            template_fields=["主诉", "现病史", "既往史", "诊断"],
        ),
        "lab_report": TableChunking(
            include_headers=True,
            merge_adjacent_rows=True,
        ),
        "drug_label": FieldExtractionChunking(
            fields=["适应症", "用法用量", "禁忌", "不良反应"],
        ),
        "patient_narrative": SentenceLevelChunking(
            window=5,  # 5句为一个chunk
            overlap=2,
        ),
        "textbook": SemanticParagraphChunking(
            merge_short=True,
            min_paragraph_len=200,
        ),
    }

    @classmethod
    def chunk_document(
        cls,
        doc: ParsedDocument,
        strategy_name: str = "auto",
    ) -> list[Chunk]:
        if strategy_name == "auto":
            strategy_name = cls._infer_strategy(doc)

        strategy = cls.STRATEGIES.get(strategy_name)
        if not strategy:
            strategy = cls.STRATEGIES["guideline"]  # 默认策略

        return strategy.chunk(doc)
```

---

## 四、技术路线图

### 4.1 迭代阶段规划

```
Phase 1: 对话状态机 ⭐⭐⭐⭐⭐（最高优先）
├── 实现 ConversationState 数据模型
├── 实现 DialoguePolicyEngine
├── 实现 ConversationMemory 压缩
└── 时间：2 周

Phase 2: 口语理解层 ⭐⭐⭐⭐⭐
├── 实现 DialectNormalizer
├── 构建四川话词典 v1.0（200+词条）
├── 实现 COLLOQUIAL_SYMPTOM_MAP
└── 时间：1.5 周

Phase 3: 指代消解 ⭐⭐⭐⭐
├── 实现 CoreferenceResolver
├── 医疗场景指代规则库
└── 时间：1 周

Phase 4: GraphRAG ⭐⭐⭐⭐⭐
├── 设计医疗知识图谱 Schema
├── 实现 MedicalKnowledgeGraphBuilder
├── 实现 GraphRAGRetriever（local/global/hybrid）
└── 时间：3 周

Phase 5: 医生风格生成 ⭐⭐⭐⭐⭐
├── 实现 DoctorStyleGenerator
├── 重构 ANSWER_SYSTEM_PROMPT
├── 实现安全护栏增强版
└── 时间：2 周

Phase 6: 性能优化 ⭐⭐⭐
├── 实现 SemanticCache
├── 部署 Qwen3-8B 推理服务
├── 性能压测与调优
└── 时间：2 周

Phase 7: 生产化 ⭐⭐⭐
├── 单元测试 + 集成测试
├── 结构化日志 + Tracing
├── API 认证 + 限流
└── 时间：2 周

Phase 8: 文档流水线 ⭐⭐
├── ChunkingFactory 实现
├── Milvus 部署
├── 完善 MinerU 集成
└── 时间：1.5 周

总计：~15 周
```

### 4.2 技术选型更新

| 组件 | V1 | V2 | 原因 |
|------|----|----|------|
| 主模型 | DeepSeek-R1-Distill-Qwen-32B | Qwen3-8B（快速）+ Qwen3-32B（复杂） | 速度与质量平衡 |
| 向量数据库 | InMemory / Qdrant | **Milvus** | 更好的混合检索支持 |
| 图数据库 | 无 | **Neo4j / NebulaGraph** | GraphRAG 必需 |
| 缓存 | 无 | **Redis** | 对话状态 + 语义缓存 |
| 关系数据库 | 无 | **PostgreSQL** | 病历 + 元数据 |
| 评测框架（历史规划） | Ragas 基础（原始设想，未按当前标准验收） | **未来独立接入：Ragas + 医疗专项评估** | hypothetical integration；当前基线是 deterministic lexical |
| 部署 | 单机 | **K8s + Docker** | 小程序高并发需求 |

---

## 五、现有代码改造计划

### 5.1 需要新增的文件

```
app/
├── v2/                           # V2 新增模块（与 v1 并行开发）
│   ├── __init__.py
│   ├── conversation/             # 对话管理
│   │   ├── __init__.py
│   │   ├── state.py              # ConversationState
│   │   ├── policy.py             # DialoguePolicyEngine
│   │   ├── memory.py             # ConversationMemory
│   │   └── nodes.py              # 症状引导图节点定义
│   ├── understanding/            # 语义理解
│   │   ├── __init__.py
│   │   ├── dialect_normalizer.py # 方言规范化
│   │   ├── coreference.py        # 指代消解
│   │   ├── symptom_extractor.py  # 症状提取
│   │   └── intent_enhanced.py    # 增强意图识别
│   ├── graphrag/                # GraphRAG
│   │   ├── __init__.py
│   │   ├── schema.py             # 医疗知识图谱 Schema
│   │   ├── builder.py            # 图谱构建器
│   │   ├── retriever.py          # GraphRAG 检索器
│   │   └── updater.py            # 自学习更新器
│   ├── generation/               # 生成模块
│   │   ├── __init__.py
│   │   ├── doctor_generator.py   # 医生风格生成器
│   │   └── prompts_v2.py         # V2 Prompt 模板
│   ├── cache/                   # 缓存层
│   │   ├── __init__.py
│   │   ├── semantic_cache.py     # 语义缓存
│   │   └── dialogue_cache.py     # 对话状态缓存
│   ├── safety/                  # 安全增强
│   │   ├── __init__.py
│   │   ├── emergency_detector.py # 急危重症检测
│   │   └── guard_v2.py           # V2 安全护栏
│   └── api_v2.py                # V2 API 路由
├── tests/                       # 测试（新增）
│   ├── unit/
│   ├── integration/
│   └── e2e/
└── config_v2.py                # V2 配置
```

### 5.2 需要改造的现有文件

| 文件 | 改造内容 |
|------|---------|
| `app/schemas.py` | 新增 ConversationState, Turn, Slot, DialogueAction 等数据模型 |
| `app/service.py` | 改造为 V2 服务编排器，支持对话模式切换 |
| `app/workflow.py` | 新增 V2 状态机工作流，保留 V1 回退 |
| `app/prompts.py` | 新增 V2 Prompt 模板（医生风格、急危重症等）|
| `app/config.py` | 新增 V2 配置项（Redis、Milvus、Neo4j 等）|
| `app/main.py` | 新增 V2 API 路由（对话、预问诊、电子病历等）|
| `app/retrieval/vector_store.py` | 新增 Milvus 实现，保留 Qdrant 和 InMemory |
| `requirements.txt` | 新增 redis, milvus-client, neo4j, pytest 等 |

### 5.3 改造优先级

**第一批次（立即开始）：**
1. `app/schemas.py` — 新增对话数据模型
2. `app/config.py` — 新增 Redis/缓存配置
3. 新建 `app/v2/conversation/state.py` — 对话状态
4. 新建 `app/v2/understanding/dialect_normalizer.py` — 方言规范化
5. `app/prompts.py` — 新增 V2 提示词

**第二批次（1-2周后）：**
6. 新建 `app/v2/graphrag/` — GraphRAG 模块
7. 新建 `app/v2/generation/doctor_generator.py` — 医生风格生成
8. `app/workflow.py` — 集成 V2 状态机
9. `app/service.py` — 改造服务编排

**第三批次（持续迭代）：**
10. 性能优化、测试完善、部署配置

---

## 六、HIS 联动设计

### 6.1 联动场景

```
┌─────────────────────────────────────────────────────────────────┐
│                         HIS 联动架构                              │
│                                                                  │
│   ┌──────────┐      ┌──────────┐      ┌──────────┐              │
│   │ 门诊系统 │      │ 住院系统  │      │ 检验系统  │              │
│   └────┬─────┘      └────┬─────┘      └────┬─────┘              │
│        │                 │                 │                    │
│        └────────────────┬┴─────────────────┘                    │
│                         │                                       │
│                         ▼                                       │
│               ┌──────────────────┐                              │
│               │   HIS 中间件     │                              │
│               │ (FHIR / WebService)│                              │
│               └────────┬─────────┘                              │
│                        │                                         │
│                        ▼                                         │
│    ┌───────────────────────────────────────────────┐             │
│    │        癫痫智能问诊系统 V2                      │             │
│    │                                               │             │
│    │  ← 获取历史病历 →  ← 获取检验结果 →              │             │
│    │                                               │             │
│    │  → 推送预问诊结果 →  → 推送诊断建议 →            │             │
│    └───────────────────────────────────────────────┘             │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### 6.2 数据接口

| 方向 | 接口 | 数据内容 |
|------|------|---------|
| HIS → 问诊系统 | `GET /patient/{id}/history` | 历史诊断、用药、手术史 |
| HIS → 问诊系统 | `GET /patient/{id}/labs` | 脑电图、影像学报告 |
| HIS → 问诊系统 | `POST /consultation/start` | 开启新问诊会话 |
| 问诊系统 → HIS | `POST /consultation/{id}/complete` | 预问诊结果（JSON） |
| 问诊系统 → HIS | `POST /consultation/{id}/note` | 门诊病历草稿 |
| 问诊系统 → HIS | `POST /alert/emergency` | 急危重症预警 |

---

## 七、风险与缓解策略

| 风险 | 影响 | 缓解策略 |
|------|------|---------|
| 方言词典覆盖不足 | 方言识别率低 | 分批构建，持续扩充；建立用户反馈机制 |
| GraphRAG 构建成本高 | 初期投入大 | 先用规则抽取 + LLM 补全，后续引入 NER 模型 |
| 小程序并发瓶颈 | 响应延迟 | 多级缓存 + Qwen3-8B 快速路由 + 异步处理 |
| 医学幻觉风险 | 患者安全 | 三层安全护栏（输入/过程/输出）+ 急危重症优先检测 |
| 患者隐私合规 | 法律风险 | 数据脱敏 + 传输加密 + 最小化数据收集 |
| 模型微调效果不达预期 | 投入浪费 | 先做 prompt engineering，验证后再微调 |

---

## 八、总结

本报告详细阐述了癫痫专科智能问诊系统 V2 的完整技术架构。V2 的核心目标是将当前的单轮 RAG 系统，升级为能够真正模拟医生问诊体验的智能对话系统。

**关键技术升级：**
1. **多轮对话状态机**：解决问卷型对话问题，实现真正的医生风格问诊
2. **口语理解层**：解决方言和口语化表达问题，提升医学实体识别率
3. **GraphRAG**：引入医疗知识图谱，增强检索的推理能力和召回质量
4. **性能优化**：多级缓存 + 小模型快速路由，满足高并发场景
5. **生产化**：测试体系 + 可观测性 + 安全护栏，保障系统可靠性

**迭代原则：**
- 每解决一个问题写入迭代文档
- 渐进式改造，保留 V1 作为回退
- 医学安全永远是第一优先级
- 性能优化与用户体验并重

---

*文档版本：V2.0*
*最后更新：2026-05-14*
*维护者：Epilepsy-QA Team*
