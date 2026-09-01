# 强化学习（RL）面试问答文档

## 关联说明

本文档是 [Epilepsy_RAG_Q&A.md](./Epilepsy_RAG_Q&A.md) 的**补充章节**，聚焦于强化学习（RL）八股与算法对比，专门为互联网公司大模型算法实习面试准备。

> **定位声明**：本项目中 **Epilepsy RAG 系统本身不涉及强化学习的直接应用**，以下所有 RL 问题均属于面试前需掌握的**通用技术储备**，旨在展示候选人对 RL 基础理论、核心算法、LLM+RL 融合技术（如 RLHF/GRPO/DPO 等）的系统理解深度。
>
> **评估与 reward 边界（重要）**：第 9 节涉及的 Ragas/LLM Judge/答案质量 reward 全部是 **hypothetical future integration**，不是本项目当前能力。`POST /v1/eval/ragas` 只是 legacy compatibility URL；当前未安装、也未运行 Ragas。当前 `backend=deterministic_lexical`、`metric_version=token_overlap_v1`、`aggregation=macro_average` 只比较 `ground_truth` 与 `retrieved_contexts`，以兼容字段 `context_precision` 返回 context-hit ratio、以 `context_recall` 返回 ground-truth token coverage 的样本宏平均，并忽略 `response`。这种 lexical overlap 不能作为答案质量、faithfulness、事实正确性、临床安全或临床效果 reward。

---

## 目录

1. [基础概念类](#1-基础概念类)
2. [value-based-vs-policy-based 类](#2-value-based-vs-policy-based-类)
3. [Policy Gradient 与 PPO 系列](#3-policy-gradient-与-ppo-系列)
4. [Actor-Critic 架构](#4-actor-critic-架构)
5. [On-policy vs Off-policy](#5-on-policy-vs-off-policy)
6. [RLHF / DPO / GRPO 等 LLM 对齐技术](#6-rlhf--dpo--grpo-等-llm-对齐技术)
7. [探索与利用](#7-探索与利用)
8. [多智能体与层次化 RL](#8-多智能体与层次化-rl)
9. [RL 在 RAG/LLM 场景的应用思考](#9-rl-在-ragllm-场景的应用思考)
10. [代码实现与算法对比](#10-代码实现与-算法对比)

---

## 1. 基础概念类

### Q1：什么是马尔可夫决策过程（MDP）？它由哪几部分组成？

MDP（Markov Decision Process）是序列决策问题的数学框架，是强化学习的理论基础。

**MDP 五元组：**<S, A, P, R, γ>

- **S（State）**：状态空间，所有可能状态的集合
- **A（Action）**：动作空间，智能体可以采取的所有动作的集合
- **P（Transition）**：状态转移概率函数，P(s'|s,a) 表示在状态 s 下执行动作 a 后转移到状态 s' 的概率
- **R（Reward）**：奖励函数，R(s,a) 或 R(s,a,s') 表示采取动作后获得的即时奖励
- **γ（Gamma）**：折扣因子，0≤γ≤1，衡量未来奖励的重要性

**核心假设——马尔可夫性**：未来状态只与当前状态有关，与历史状态无关，即：

\[ P(s_{t+1}|s_t, a_t, s_{t-1}, a_{t-1}, ...) = P(s_{t+1}|s_t, a_t) \]

**价值函数**：状态价值函数 V(s) 表示从状态 s 出发按照策略 π 行事的期望累计折扣奖励；动作价值函数 Q(s,a) 表示在状态 s 下执行动作 a 之后的期望累计折扣奖励。

**最优性方程（Bellman Optimality Equation）**：

\[ V^*(s) = \max_a \sum_{s'} P(s'|s,a) [R(s,a,s') + \gamma V^*(s')] \]

---

### Q2：什么是 Bellman 方程？它在 RL 中起什么作用？

**Bellman 方程**是连接当前价值与未来价值的递归方程，是几乎所有 RL 算法的基石。

**状态价值函数的 Bellman 方程**：

\[ V^\pi(s) = \sum_a \pi(a|s) \sum_{s'} P(s'|s,a) [R(s,a,s') + \gamma V^\pi(s')] \]

**动作价值函数的 Bellman 方程**：

\[ Q^\pi(s,a) = \sum_{s'} P(s'|s,a) [R(s,a,s') + \gamma \sum_{a'} \pi(a'|s') Q^\pi(s',a')] \]

**作用**：

1. **递归分解**：将无限期问题分解为"当前奖励 + 未来价值的折现"两部分
2. **动态规划基础**：Bellman 方程是 Value Iteration 和 Policy Iteration 的理论基础
3. **TD 学习基础**：TD(0) 的更新公式就是 Bellman 方程的随机近似版本
4. **收敛性保证**：在满足一定条件下（状态有限、折扣因子<1），Bellman 算子是压缩映射，解唯一存在

**Bellman 最优算子**（用于 Value Iteration）：

\[ TV(s) = \max_a \sum_{s'} P(s'|s,a) [R(s,a,s') + \gamma V(s')] \]

---

### Q3：什么是折扣因子 γ？为什么需要折扣因子？

**折扣因子 γ** 决定了未来奖励在当前决策中的重要性，取值范围 [0, 1)。

**引入折扣因子的原因**：

1. **数学上保证收敛**：无限期 MDP 中，无折扣的累计奖励可能发散，而 γ<1 能保证几何级数收敛
2. **反映偏好近未来**：实际场景中，当前的奖励比遥远的未来奖励更有价值
3. **建模不确定性**：未来状态存在不确定性（环境变化、任务终止），折扣因子隐式处理这种不确定性
4. **避免循环问题**：无折扣情况下，智能体可能陷入无限循环以获取更多奖励

**γ 的影响**：

- **γ → 0**：只关注即时奖励，类似"短视"策略
- **γ → 1**：更重视长期收益，但收敛更慢，训练不稳定
- **γ = 0.99**（常用）：平衡短期与长期，在很多任务中效果较好

---

### Q4：什么是值函数？V(s) 和 Q(s,a) 有什么区别？它们之间有什么关系？

**值函数**衡量的是在某个状态或状态下执行某个动作的"好坏"程度，用期望累计折扣奖励来度量。

| 函数 | 定义 | 含义 |
|------|------|------|
| V(s) | 从状态 s 出发，遵循策略 π 的期望累计折扣奖励 | "这个状态有多好" |
| Q(s,a) | 从状态 s 出发执行动作 a，之后遵循策略 π 的期望累计折扣奖励 | "在这个状态下做这个动作有多好" |
| V\*(s) | 最优策略下的状态价值函数 | "所有策略中，这个状态能获得的最好价值" |
| Q\*(s,a) | 最优策略下的动作价值函数 | "所有策略中，这个状态-动作对的最优价值" |

**关系**：

```
V(s)  = Σ_a π(a|s) · Q(s,a)                    （期望动作价值 = 状态价值）
Q(s,a) = Σ_{s'} P(s'|s,a) · [R(s,a,s') + γ·V(s')]   （动作价值 = 即时奖励 + 折扣未来价值）
V*(s) = max_a Q*(s,a)                          （最优状态下，选择最优动作）
Q*(s,a) = Σ_{s'} P(s'|s,a) · [R(s,a,s') + γ·V*(s')] （Bellman 最优方程）
```

**策略改进定理**：如果对于所有状态 s，有 Q(s, π'(s)) ≥ Vπ(s)，则新策略 π' 至少不比旧策略差。

---

## 2. Value-Based vs Policy-Based 类

### Q5：强化学习算法可以分为哪几类？请分别介绍。

RL 算法可以从多个角度分类，最常用的是按**学习范式**和**策略表示**分类：

**按学习范式分类**：

| 类别 | 代表算法 | 核心思想 | 优点 | 缺点 |
|------|---------|---------|------|------|
| **Value-Based** | DQN, DDQN, Dueling DQN | 学习状态-动作值函数 Q(s,a)，间接得到策略（选 Q 值最大的动作） | 采样效率高，稳定性好 | 只能处理离散动作，Q 值过估计问题 |
| **Policy-Based** | REINFORCE, Vanilla PG | 直接参数化策略函数 π(a\|s;θ)，通过梯度上升优化 | 能处理连续动作，收敛性更好 | 样本效率低，方差极高 |
| **Actor-Critic** | A2C, A3C, PPO, SAC | 结合两者：Actor（策略）+ Critic（价值函数） | 方差低，能处理连续动作 | 需要同时训练两个网络，调参复杂 |
| **Model-Based** | Dyna, MuZero, Dreamer | 学习环境模型 P(s'\|s,a)，结合规划 | 样本效率极高 | 模型误差会累积，训练复杂 |
| **Offline RL** | CQL, IQL, TD3+BC | 从固定数据集中学习，不与环境交互 | 安全性高，适合真实场景 | 分布偏移问题（OOD） |

**按策略更新方式分类**：

- **On-Policy**：只能用当前策略产生的数据更新（PPO、SARSA）
- **Off-Policy**：可以用任意数据更新（DQN、DDPG、SAC）

---

### Q6：Value-Based 方法（如 DQN）和 Policy-Based 方法（如 REINFORCE）各有什么优缺点？

**DQN（Deep Q-Network）**：

**优点**：
- 采样效率相对较高，off-policy 可以复用历史经验
- Q-learning 有理论收敛保证（当状态动作空间离散且有限时）
- 经验回放（Experience Replay）打破数据的时间相关性，稳定训练

**缺点**：
- 只能处理离散动作空间（连续动作需要用 DDPG/AAC 等）
- Q 值过估计（Overestimation）问题——由于使用 max Q 值，Q 估计倾向于高于真实值
- 对价值函数的微小波动可能导致策略剧烈变化

**DQN 的核心技巧**：
1. 目标网络（Target Network）：每隔 C 步复制 Q 网络参数，减少自举误差
2. 经验回放（Experience Replay）：从 Replay Buffer 随机采样，打破时序相关性
3. ε-greedy 探索：前期高探索、后期高利用

**REINFORCE（Policy Gradient）**：

**优点**：
- 能自然处理连续动作空间
- 收敛到局部最优，策略梯度天然是单调提升的
- 对隐含随机性建模好（如部分可观测环境）

**缺点**：
- 方差极高——回报是蒙特卡洛估计，噪声大
- 样本效率低——on-policy，每次更新后数据就过期
- 收敛慢，需要大量样本

**Policy Gradient 定理**：
\[ \nabla_\theta J(\theta) = \mathbb{E}_{\pi_\theta} [\nabla_\theta \log \pi_\theta(a|s) \cdot G_t] \]
其中 G_t 是从时间 t 开始的累计折扣奖励。

---

### Q7：DQN 的过估计（Overestimation）问题是什么？怎么解决？

**问题**：DQN 使用 max_a Q(s', a) 近似 Bellman 最优方程，但 max 操作会放大噪声——因为 Q(s', a) 是随机变量，估计误差会导致选中过高的 Q 值。

**具体分析**：
设真实 Q 值为 Q*(s', a)，DQN 估计为 Q(s', a) = Q*(s', a) + ε（误差），其中 E[ε] = 0 但 var(ε) > 0。
\[ \max_a Q(s', a) = Q*(s', a^*) + \varepsilon_{a^*} \geq Q*(s', a^*) \]
即使误差均值为零，max 操作使估计值系统性地偏高于真实值，且这种偏差会随时间步传播累积（TD 误差的链式传播）。

**解决方案**：

1. **Double DQN（DDQN）**：用两个 Q 网络解耦动作选择和价值评估
   - Online Q 网络选择最大 Q 值对应的动作：a_max = argmax_a Q_online(s', a)
   - Target Q 网络评估该动作的价值：Q_target = R + γ · Q_target(s', a_max)
   - 理论上证明可以消除 50% 以上的过估计

2. **Dueling DQN**：将 Q(s,a) 分解为 V(s) + A(a) 两部分
   - Q(s,a) = V(s) + A(s,a) - mean(A(s,a))
   - 优势函数 A(s,a) 衡量动作相对于平均水平的优势，减少对 max 的依赖

3. **Clipped Double Q**：SAC 等算法中用两个 Q 函数，Q1 和 Q2，取 min 避免过估计
   \[ y = r + \gamma \min_{i=1,2} Q_i(s', a') \]

---

## 3. Policy Gradient 与 PPO 系列

### Q8：Policy Gradient 的推导过程是什么？为什么要取对数梯度？

**Policy Gradient 推导（从似然比角度）**：

目标函数：J(θ) = E_{τ~π_θ}[R(τ)]，其中 τ = (s_0, a_0, s_1, a_1, ...) 是轨迹，R(τ) 是轨迹总奖励。

**第一步：轨迹概率分解**
\[ P_\theta(\tau) = P(s_0) \prod_{t=0}^{T-1} \pi_\theta(a_t|s_t) P(s_{t+1}|s_t, a_t) \]

**第二步：对数梯度**
\[ \nabla_\theta \log P_\theta(\tau) = \sum_{t=0}^{T-1} \nabla_\theta \log \pi_\theta(a_t|s_t) \]
注意：环境转移概率 P(s_{t+1}|s_t,a_t) 与 θ 无关，其梯度为 0。

**第三步：似然比技巧（Score Function）**
\[ \nabla_\theta J(\theta) = \mathbb{E}_{\tau \sim \pi_\theta}[R(\tau) \cdot \nabla_\theta \log P_\theta(\tau)] = \mathbb{E}_{\tau \sim \pi_\theta}\left[R(\tau) \cdot \sum_{t=0}^{T-1} \nabla_\theta \log \pi_\theta(a_t|s_t)\right] \]

**Policy Gradient 定理（用 G_t 替代 R(τ)）**：
\[ \nabla_\theta J(\theta) = \mathbb{E}_{\pi_\theta} \left[\sum_{t=0}^{T-1} \nabla_\theta \log \pi_\theta(a_t|s_t) \cdot G_t \right] \]

**为什么要取对数梯度（似然比/Score Function 技巧）**：

1. **避免对 P(s_{t+1}|...) 求梯度**：环境中转移概率通常未知，无法直接对 p 求梯度。通过 log 技巧，把 p 消掉了，只剩下 π。
2. **无偏估计**：E[∇ log π(a|s) · G_t] 是 ∇J 的无偏估计。
3. **可采样计算**：期望可以用蒙特卡洛采样估计，只需知道 π(a|s) 的值，不需要知道环境模型。

**一个直观的理解**：如果某个动作 a 在状态 s 下的 log 概率梯度为正（即增大该动作的概率），且该动作获得了高奖励 G_t，则策略会向增加该动作概率的方向更新。

---

### Q9：什么是基线（Baseline）？引入基线为什么能降低方差？

**基线 b(s)** 是状态 s 的任意函数，不依赖动作，满足 E_{a~π}[∇_θ log π(a|s) · b(s)] = 0。

**引入基线的梯度**：
\[ \nabla_\theta J(\theta) = \mathbb{E} \left[ \sum_t \nabla_\theta \log \pi(a_t|s_t) \cdot (G_t - b(s_t)) \right] \]

**证明 b(s) 不改变梯度的无偏性**：
\[ \mathbb{E}[\nabla \log \pi(a|s) \cdot b(s)] = b(s) \cdot \mathbb{E}[\nabla \log \pi(a|s)] = b(s) \cdot 0 = 0 \]
（因为概率分布积分为 1，其导数为 0：∫ π(a|s) da = 1 ⇒ ∫ ∇π da = 0 ⇒ E[∇log π] = 0）

**为什么降低方差**：
- 不减均值：E[G_t - b(s)] = E[G_t]（无偏）
- 降低方差：如果 b(s) ≈ E[G_t|s]，则 G_t - b(s) 的方差远小于 G_t 本身

**最常用的基线是状态价值函数 V(s)**：用 V(s) 估计 E[G_t|s]，则 G_t - V(s) = advantage（优势函数），衡量"这个动作比平均水平好多少"。

**Advantage Function（优势函数）**：
\[ A^\pi(s,a) = Q^\pi(s,a) - V^\pi(s) \]
如果 A(s,a) > 0，说明动作 a 比平均好，应该增加概率；如果 A(s,a) < 0，说明应该减少概率。

---

### Q10：REINFORCE 算法是怎么工作的？它的完整更新公式是什么？

**REINFORCE** 是最基础的 Policy Gradient 算法，直接用蒙特卡洛采样估计策略梯度。

**算法流程**：

```
1. 用策略 π_θ 采样一条完整轨迹 τ: (s_0,a_0,r_0), ..., (s_{T-1},a_{T-1},r_{T-1})
2. 计算每一步的回报：G_t = Σ_{k=t}^{T-1} γ^{k-t} r_k   （从 t 时刻开始的累计折扣奖励）
3. 对轨迹中每一步做策略梯度更新：
   θ ← θ + α · ∇_θ log π_θ(a_t|s_t) · G_t
```

**带基线的 REINFORCE**（更常用）：
```python
for each trajectory:
    for t in range(T):
        G_t = sum(gamma**(k-t) * r_k for k in range(t, T))
        advantage = G_t - V(s_t)  # V(s_t) 为价值网络估计
        θ_actor ← θ_actor + α_actor * advantage * ∇_θ log π_θ(a_t|s_t)
        θ_critic ← θ_critic + β * advantage * ∇ V(s_t)  # 更新价值网络
```

**关键特点**：
- On-policy：必须用当前策略采样的数据
- 无需环境模型（Model-free）
- 方差高，通常需要大量采样才能收敛
- 收敛速度慢，但理论保证单调改进

---

### Q11：PPO（Proximal Policy Optimization）的核心思想是什么？为什么它能同时保证稳定性与样本效率？

**PPO 的核心思想**：通过**裁剪（Clipping）**限制策略更新的幅度，既避免策略剧烈变化导致训练崩溃，又允许足够的探索来提升性能。

**PPO 损失函数（Clipped Surrogate Objective）**：

\[ L^{CLIP}(\theta) = \mathbb{E}_t \left[ \min\left( r_t(\theta) \cdot A_t,\; \text{clip}(r_t(\theta), 1-\epsilon, 1+\epsilon) \cdot A_t \right) \right] \]

其中**概率比** r_t(θ) = π_θ(a_t|s_t) / π_{θ_old}(a_t|s_t)，衡量新策略相对于旧策略的概率变化。

**裁剪机制的工作原理**：

当 A_t > 0（动作好，应该增加概率）：
- r_t(θ) > 1+ε：裁剪掉，不允许过度增加
- r_t(θ) ∈ [1-ε, 1+ε]：正常更新，但有上限约束

当 A_t < 0（动作差，应该减少概率）：
- r_t(θ) < 1-ε：裁剪掉，不允许过度减少
- r_t(θ) ∈ [1-ε, 1+ε]：正常更新，但有下限约束

**为什么比 TRPO 更实用**：
- TRPO 用了 KL 散度约束，需要在优化中额外求解约束优化问题（二阶方法，计算复杂）
- PPO 用一阶优化 + 裁剪，实现简单，效果相当

**PPO 的完整损失函数**：
\[ L^{PPO}(\theta) = L^{CLIP}(\theta) - c_1 \cdot L^{VF}(\theta) + c_2 \cdot S(\pi_\theta) \]

其中：
- L^{VF}(θ)：价值函数损失（均方误差），c_1 通常为 0.5
- S(π_θ)：熵正则项，鼓励探索，c_2 通常为 0.01

---

### Q12：PPO 中 ε（clip range）通常取多少？太大或太小有什么影响？

**ε（clip range）的常用取值**：

- **PPO2 / 线上实现默认值**：ε = 0.2（即 1±0.2）
- **Robust PPO（RPPO）**：ε 可以更小（如 0.1）或更大（如 0.3）

**ε 太大（> 0.3）的影响**：
- 策略更新幅度过大，可能导致训练不稳定、崩溃
- 相当于几乎没有约束，接近原始 Policy Gradient，退化为 On-Policy 高方差版本

**ε 太小（< 0.05）的影响**：
- 策略更新幅度过小，训练收敛极慢
- 探索不足，容易陷入局部最优
- 优势函数的估计误差可能掩盖策略改进

**工程调参经验**：通常在 [0.1, 0.3] 范围内调整，配合学习率一起调。在某些任务中，PPO 对 ε 的敏感性不高，可以固定为 0.2。

---

### Q13：PPO 和 TRPO 的区别是什么？为什么 PPO 逐渐成为主流？

| 维度 | TRPO | PPO |
|------|------|-----|
| 约束形式 | KL 散度硬约束：KL(π_old\|\|π_new) ≤ δ | Clipping 软约束（概率比裁剪） |
| 优化方法 | 约束优化（Conjugate Gradient + Line Search，二阶） | 一阶随机梯度下降（Adam） |
| 实现复杂度 | 高：需要计算 Fisher Information Matrix | 低：只需普通梯度下降 |
| 计算开销 | O(N²) ~ O(N³)（Hessian 矩阵相关） | O(N)（与普通 SGD 同阶） |
| 采样效率 | 略高于 PPO（KL 约束更紧） | 略低，但实现简单，可多 epoch 更新 |
| 实践效果 | 稳定但调参难 | 效果相当，易于工程实现 |

**为什么 PPO 成为主流**：
1. **实现简单**：只需几行代码修改梯度方向，不需要 TRPO 的共轭梯度求解器
2. **稳定性好**：Clipping 保证策略不会在单步更新中变化太大
3. **超参鲁棒**：默认 ε=0.2 在大多数任务中效果不错
4. **可以多 epoch 数据复用**：PPO 允许对同一批数据做多轮更新（mini-batch），比 TRPO 更样本高效
5. **工程友好**：OpenAI、Stable Baselines3 等主流库都优先实现 PPO

---

## 4. Actor-Critic 架构

### Q14：什么是 Actor-Critic 架构？Actor 和 Critic 分别负责什么？

**Actor-Critic（AC）** 是将 Value-Based 和 Policy-Based 方法结合的混合框架，同时维护两个网络：

**Actor（策略网络）**：
- 输出动作或动作分布 π(a|s; θ)
- 负责决策：给定状态，选择动作
- 通过策略梯度更新：θ ← θ + α_actor · ∇_θ log π(a|s) · A(s,a)

**Critic（价值网络）**：
- 估计状态价值 V(s; φ) 或状态-动作价值 Q(s,a)
- 负责评估："当前策略下，这个状态/动作有多好"
- 通过均方误差更新：φ ← φ - β · ∇_φ (r + γV(s') - V(s))²

**为什么需要 Critic**：
- REINFORCE 用蒙特卡洛 G_t 估计回报，方差极高
- Critic 提供了低方差的基线/优势函数估计
- Advantage: A(s,a) = Q(s,a) - V(s) 相比原始回报 G_t 方差显著降低

**AC 家族的主要变体**：

| 算法 | Actor | Critic | 特点 |
|------|-------|--------|------|
| A2C（Advantage AC） | 策略梯度 | Advantage A(s,a) | 同步更新，效率高 |
| A3C（Asynchronous AC） | 策略梯度 | Advantage A(s,a) | 异步多线程并行采集，稳定性好 |
| PPO | PPO 裁剪目标 | 均方误差 | 稳定性强，当前主流 |
| DDPG | 确定性策略 π(s) | Q(s,a) | 连续动作，Off-policy |
| SAC | 最大熵策略 | 双 Q 网络 | 最大熵 RL，探索充分 |

---

### Q15：GAE（Generalized Advantage Estimation）的原理是什么？λ 参数起什么作用？

**GAE** 是一种将 TD(λ) 思想引入优势函数估计的方法，用更少方差的同时保持低偏差。

**TD(λ) 在 Advantage 估计中的应用**：

传统的 n-step Return：
\[ G_t^{(n)} = r_t + \gamma r_{t+1} + ... + \gamma^{n-1} r_{t+n-1} + \gamma^n V(s_{t+n}) \]

优势函数的 n-step 估计：
\[ A_t^{(n)} = G_t^{(n)} - V(s_t) \]

**GAE 定义**：对不同 n 的优势估计做指数加权平均：
\[ A_t^{GAE(\lambda)} = (1-\lambda) \sum_{n=1}^{\infty} \lambda^{n-1} A_t^{(n)} \]

**等价递归形式（更常用）**：
\[ \delta_t = r_t + \gamma V(s_{t+1}) - V(s_t) \]
\[ A_t^{GAE(\lambda)} = \delta_t + \gamma\lambda A_{t+1}^{GAE(\lambda)} \]

这个递归形式可以高效计算，时间复杂度 O(T)，不需要遍历无穷多项。

**λ 参数的影响**：

| λ 取值 | 特性 | 偏差-方差权衡 |
|--------|------|--------------|
| λ = 0 | 只用 1-step TD error: A_t = δ_t | **方差最低，但偏差高**（一步之后就用 value 函数估计） |
| λ = 1 | 等价于蒙特卡洛: A_t = Σ γ^{k-t} r_k - V(s_t) | **偏差最低，但方差高**（完全用采样） |
| λ ∈ (0,1) | 平衡上述两者 | **偏差-方差最佳权衡**，通常效果最好 |
| 实际常用 | λ = 0.95 ~ 0.99 | 接近蒙特卡洛，但通过 bootstrap 降低方差 |

**λ 的直观理解**：λ 越大，越信任长期采样的回报；λ 越小，越信任价值网络 V(s) 的短期估计。

---

### Q16：DDPG（Deep Deterministic Policy Gradient）和 SAC（Soft Actor-Critic）的区别是什么？

| 维度 | DDPG | SAC |
|------|------|-----|
| 策略类型 | **确定性策略** π(a\|s)（输出具体动作） | **随机策略** π(a\|s)（输出动作分布） |
| Off/On Policy | Off-policy | Off-policy |
| 探索方式 | 人工添加噪声（Ornstein-Uhlenbeck） | 熵正则项自动调节探索 |
| Q 值估计 | 单 Q 网络（有过估计问题） | 双 Q 网络，取 min（减少过估计） |
| 目标 | 最大化累积奖励 | 最大化累积奖励 + 最大熵 |
| 适用场景 | 连续动作、低维动作空间 | 连续动作、需充分探索的任务 |
| 收敛稳定性 | 中等（需要目标网络+Twin Q 稳定） | 较高（双 Q + 熵正则天然稳定） |

**DDPG 的关键公式**：

确定性策略梯度（DPG）：
\[ \nabla_\theta J(\pi) = \mathbb{E}_{s \sim D} [\nabla_a Q^\mu(s,a)|_{a=\pi(s)} \cdot \nabla_\theta \pi(s|\theta)] \]

更新公式：
```python
# Critic 更新：TD 误差
y_i = r_i + γ Q_target(s', μ_target(s'))
Q_loss = MSE(Q_online(s,a), y_i)

# Actor 更新：沿着 Q 梯度上升方向更新策略
actor_loss = -Q_online(s, μ(s))  # 最大化 Q 等价于最小化负 Q
```

**SAC 的核心——最大熵 RL**：
\[ J(\pi) = \sum_t \mathbb{E}_{(s_t,a_t)\sim\pi}[r(s_t,a_t) + \alpha \cdot \mathcal{H}(\pi(\cdot|s_t))] \]

其中熵正则项 H(π) = -E_{a~π}[log π(a|s)]鼓励策略保持高熵（高随机性），避免过早收敛到确定性策略。温度参数 α 控制熵与奖励的相对权重。

**DDPG vs SAC 实际选择**：
- DDPG 适合相对简单的连续控制任务（如 MuJoCo）
- SAC 因为有熵正则，通常在稀疏奖励任务中表现更好

---

## 5. On-Policy vs Off-Policy

### Q17：什么是 On-Policy 和 Off-Policy？它们各有什么优缺点？

**On-Policy**：只能用当前策略 π_θ 采集的数据来更新 π_θ。
- 代表算法：REINFORCE、PPO（含 Clipping）、SARSA
- 核心矛盾：**"正在学习的策略" = "采集数据的策略"**

**Off-Policy**：可以用任意策略（包括历史策略）采集的数据来更新当前策略。
- 代表算法：DQN、DDQN、DDPG、SAC、TD3
- 核心思想：**"正在学习的策略" ≠ "采集数据的策略"**

**Off-Policy 的关键技术——重要性采样（Importance Sampling）**：

由于数据来自 π_old，期望需要修正：
\[ \mathbb{E}_{a \sim \pi_{new}} [f(a)] = \mathbb{E}_{a \sim \pi_{old}} \left[f(a) \cdot \frac{\pi_{new}(a|s)}{\pi_{old}(a|s)}\right] \]

这就解释了 PPO 的概率比 r_t(θ) = π_θ / π_{θ_old} 的来源。

**为什么 Off-Policy 更样本高效**：
- 可以从 Replay Buffer 复用历史数据
- 数据利用率高，每条数据可以被用于多次更新

**On-Policy 的优势**：
- 避免了重要性采样的高方差问题（当 π_new 和 π_old 差距大时，权重可能爆炸）
- 训练更稳定，PPO 通过 Clipping 进一步保证稳定性
- 理论上更容易保证单调改进

**Off-Policy 的问题**：

1. **分布偏移（Distribution Shift）**：用 π_old 采集的数据训练 π_new，但 π_new 可能已经远离 π_old，导致 Q 估计偏差
2. **Q 值过估计**（见 DQN 问题）
3. **梯度估计方差大**：重要性权重可能极端化

**PPO 的 Clipping 实际上是一种"受控的 Off-Policy"**：通过限制概率比变化，使数据分布偏移在可接受范围内，从而允许用稍旧的数据更新。

---

### Q18：Experience Replay（经验回放）的作用是什么？它为什么很重要？

**Experience Replay（经验回放）** 是 Off-Policy 算法中打破数据时序相关性的核心技术，由 DeepMind 在 DQN 论文中首次引入。

**工作原理**：将每条经验 (s_t, a_t, r_t, s_{t+1}) 存入 Replay Buffer，更新时随机采样。

**核心作用**：

1. **打破时序相关性**：连续采样得到的数据 (s_t, a_t, r_t, s_{t+1}) 和 (s_{t+1}, a_{t+1}, r_{t+1}, s_{t+2}) 有很强的相关性，直接用于梯度下降会导致网络收敛到局部最优。随机打散后，样本独立同分布（i.i.d.），梯度估计更稳定。

2. **数据复用**：一条经验可以被用于多次更新，提高样本效率。

3. **平滑数据分布**：从不同状态采集的经验混合后，训练分布更均匀，避免网络只记住最近的状态。

**问题与改进**：

- **均匀回放的缺陷**：所有经验同等重要，旧经验可能已经过时。

- **优先级经验回放（PER，Prioritized Experience Replay）**：按 TD 误差大小分配采样优先级——TD 误差大的样本（学习潜力大）被采样概率更高。需要用重要性采样权重修正偏移。

- **PER 的缺点**：计算优先级有额外开销，且需要额外机制平衡优先级与均匀采样。

---

## 6. RLHF / DPO / GRPO 等 LLM 对齐技术

### Q19：什么是 RLHF（Reinforcement Learning from Human Feedback）？它的完整流程是什么？

**RLHF** 是一种将人类偏好引入大模型对齐的技术，让模型生成的内容更符合人类意图和价值观。

**RLHF 三阶段流程**：

```
阶段1: SFT（有监督微调）
    预训练 LLM + 高质量人类标注数据 → SFT 模型
    数据：人类写的"标准答案"或"好的回复"
    目标：让模型学会"生成人类期望的内容格式和风格"

阶段2: 奖励模型训练（Reward Model, RM）
    SFT 模型 + 成对偏好数据（chosen/rejected）→ 奖励模型 r(x,y)
    数据：(prompt, chosen_response, rejected_response) 三元组
    目标：让奖励模型学会"给人类喜欢的回答更高的分数"
    损失函数（Bradley-Terry 模型）：
    L_RM = -E_{(x,y_c,y_r) ~ D}[log σ(r(x,y_c) - r(x,y_r))]

阶段3: RL 优化（PPO）
    奖励模型 r(x,y) 作为奖励函数 → PPO 优化策略模型 π_RL
    奖励函数：R(x,y) = r(x,y) - β · KL(π_RL || π_SFT)
    其中 KL 项防止策略 π_RL 偏离 SFT 模型太远（alignment tax）
    使用 PPO + Clipping 保证训练稳定
```

**KL 散度约束（KL penalty）的重要性**：
- 没有 KL 约束：RL 可能找到"欺骗奖励模型"的捷径（reward hacking）
- 有 KL 约束：策略只能有限度地偏离 SFT，生成的内容仍然保持在人类期望的分布内

**KL 系数的选择**：β 太大 → 策略几乎不更新（对齐税过高）；β 太小 → 可能出现 reward hacking 或语言退化（language drift）。

**经典 RLHF 论文**：Ouyang et al., "Training language models to follow instructions with human feedback" (InstructGPT, 2022)。

---

### Q20：什么是 Reward Model（奖励模型）？为什么不能直接用人工打分作为奖励？

**Reward Model（RM）** 是 RLHF 第二阶段训练的网络，用来预测"人类对一个回答的偏好程度"。

**为什么不能直接用人工打分作为奖励**：

1. **标注成本极高**：每次模型生成都需要人工打分，成本不可接受
2. **标注意味不一致**：不同标注者对同一回答可能有不同看法，直接打分方差大
3. **学习效率低**：绝对分数的尺度不一致，不同标注者基准不同

**更优方案：成对偏好学习（Pairwise Preference）**：
- 标注者只需判断"回答A vs 回答B，哪个更好"（或"一样好"）
- 偏好判断比绝对打分更一致、更容易标注
- RM 学习的是相对偏好，而不是绝对分数

**Reward Model 训练**：给定 prompt x，和一对回答 (y_c, y_r)，其中 y_c 是人类偏好的（chosen），y_r 是非偏好的（rejected）。

损失函数（基于 Bradley-Terry 模型）：
\[ L = -\mathbb{E}_{(x,y_c,y_r) \sim D} \left[ \log \sigma\left( r(x, y_c) - r(x, y_r) \right) \right] \]

其中 r(x,y) 是奖励模型输出的标量分数。这个损失函数的直觉：**让chosen回答的分数比 rejected 回答的分数高（通过 sigmoid 映射）**。

**训练细节**：
- RM 通常从 SFT 模型出发（去掉 LM head，换成 reward scalar head）
- 偏好数据来自人类标注，通常由多个标注者的投票决定哪个更好
- RM 的泛化能力很关键——需要能识别 SFT 模型可能产生的各类错误

---

### Q21：什么是 PPO 的 KL 散度约束？为什么 RLHF 中需要这个约束？

**PPO 中 KL 散度约束的两种实现方式**：

**方式一：KL 奖励（KL Reward Penalty）**（InstructGPT/PPO 的标准做法）

在 PPO 的奖励函数中直接加入 KL 散度惩罚项：
\[ R(x, y) = r(x, y) - \beta \cdot D_{KL}(\pi_{RL}(y|x) \| \pi_{SFT}(y|x)) \]

其中：
- r(x,y) 是 Reward Model 输出的奖励分数
- β 是 KL 系数（控制惩罚强度）
- D_KL(π_RL || π_SFT) 衡量策略 π_RL 相对于 SFT 策略的"偏离程度"
- KL 散度 = E_{y~π_RL}[log π_RL(y|x) - log π_SFT(y|x)]

**KL 约束的作用**：

1. **防止语言退化（Language Drift）**：没有 KL 约束时，PPO 最大化 r(x,y) 可能让模型生成人类评价高但语法怪异、内容空洞的文本，逐渐偏离人类期望的语言分布。
2. **防止 Reward Hacking**：RL 可能找到"骗过 RM"但不真正有用的模式——KL 约束让模型无法完全"跑偏"。
3. **保证可读性**：SFT 模型已经学会了正确的语言格式和风格，KL 约束防止 RL 破坏这些已经学到的能力。

**KL 系数的设置策略**：
- **固定 β**：简单但效果一般（Anthropic 的 PPO 实现常用固定 β=0.04）
- **自适应 KL 控制器**：根据实际 KL 动态调整 β，当 KL 超过目标值时增大 β，当 KL 过小时减小 β（OpenRLHF 的实现）

**KL 散度的计算方式**：
直接计算两序列的逐 token KL 散度：KL = Σ_t [log π_SFT(a_t|s_t) - log π_RL(a_t|s_t)]，但实际中通常用 sequence-level 近似。

---

### Q22：什么是 DPO（Direct Preference Optimization）？它相比 RLHF 有什么优势？

**DPO（Direct Preference Optimization）** 是斯坦福和 Berkeley 研究者提出的新型对齐算法，绕过了奖励模型和 RL 优化阶段，直接用偏好数据优化策略。

**RLHF 的问题**：
- 训练流程复杂（3个阶段：SFT → RM → PPO）
- PPO 训练不稳定，超参多（KL 系数、PPO clip ratio 等）
- 奖励模型可能存在映射偏差

**DPO 的核心思想**：将 RLHF 的 PPO 优化目标转化为一个**可直接优化的分类损失**，用两个回答的相对偏好替代显式奖励模型。

**DPO 损失函数**：
\[ L_{DPO} = -\mathbb{E}_{(x, y_c, y_r) \sim D} \left[ \log \sigma\left( \beta \cdot \left( \log \frac{\pi_\theta(y_c|x)}{\pi_{ref}(y_c|x)} - \log \frac{\pi_\theta(y_r|x)}{\pi_{ref}(y_r|x)} \right) \right) \right] \]

其中：
- π_θ：待优化的策略模型（SFT 模型初始化）
- π_ref：参考策略（通常冻结的 SFT 模型）
- β：温度参数，控制偏离参考策略的程度

**直觉理解**：DPO 让模型增加 chosen 回答的概率（相对于参考策略），同时减少 rejected 回答的概率。这等价于在隐式地优化"隐式奖励" r(x,y) = β · [log π_θ(y|x) - log π_ref(y|x)]。

**DPO 相比 RLHF 的优势**：

| 维度 | RLHF | DPO |
|------|------|-----|
| 训练阶段 | SFT → RM → PPO（3阶段） | SFT → DPO（2阶段） |
| 训练稳定性 | PPO 超参敏感，需 KL 约束调参 | 直接优化，稳定性好 |
| 计算开销 | 需要单独的 RM + PPO 训练 | 无需 RM，单次训练 |
| 内存占用 | RM + Actor + Critic + Ref（多个模型） | 只需 Policy + Ref（2个模型） |
| 超参数量 | KL系数、clip ratio、learning rate 等 | β（温度）+ learning rate |
| 对比效果 | 综合最优（在 Reward Hacking 方面更鲁棒） | 在简单对齐任务上效果相当，复杂任务略差 |

**DPO 的局限性**：
1. 对 reward hacking 的抵抗力不如 PPO（因为没有显式的 KL 约束）
2. 需要更大的 batch size 来稳定训练
3. 在需要严格约束输出的场景（如安全对齐）中，PPO 的 KL 惩罚更可控

---

### Q23：什么是 GRPO（Group Relative Policy Optimization）？它和 PPO 有什么关系？

**GRPO** 是 DeepSeek 团队在 DeepSeek-V2 / DeepSeek-Math 论文中提出的对齐算法，是对 PPO 的简化改进，在数学推理任务上表现优异。

**PPO 的三个阶段问题**：RLHF 需要训练 Reward Model（RM），但 RM 需要额外数据和训练资源，且 RM 的质量直接影响 PPO 效果。

**GRPO 的核心思想**：用**相对排名奖励（Group Relative Ranking）**替代显式 Reward Model，不需要单独训练 RM。

**GRPO 的奖励机制**：

给定一个 prompt x，采样 G 个回答 {y_1, y_2, ..., y_G}（G 通常取 8~64），计算每个回答的优势（Advantage）：

\[ A_i = \frac{r(x, y_i) - \mu}{\sigma} \]

其中 r(x, y) 是**可微分的奖励函数**（如数学任务的答案正确性、格式检查等），μ 和 σ 是该组内 G 个奖励的均值和标准差。

**GRPO 的优势函数设计**：
\[ L^{GRPO} = \mathbb{E} \left[ \frac{1}{G} \sum_{i=1}^{G} \min\left( \frac{\pi_\theta(y_i|x)}{\pi_{old}(y_i|x)} A_i,\; \text{clip}(\frac{\pi_\theta(y_i|x)}{\pi_{old}(y_i|x)}, 1-\epsilon, 1+\epsilon) A_i \right) \right] \]

**GRPO 相比 PPO 的优势**：

1. **不需要 Reward Model**：PPO 需要单独训练一个 RM，GRPO 直接用规则奖励（如"答案是否正确"）和组内相对排名，避免了 RM 的训练开销和偏差
2. **实现更简单**：不需要 Critic 网络，不需要额外的 RM 训练流程
3. **适合可定义奖励的任务**：如代码生成（单元测试）、数学推理（答案正确性）、格式检查等
4. **DeepSeekMath 验证**：DeepSeek-Math 在 MATH benchmark 上用 GRPO 达到 SOTA

**GRPO 的适用条件**：奖励必须能高效计算（如规则函数），且每个 prompt 需要采样足够多的回答来计算组内排名。对于奖励难以定义的任务（如开放式写作），GRPO 不如 RLHF。

---

### Q24：PPO 中 reward normalization 和 advantage normalization 分别是什么？为什么要做这些归一化？

**Reward Normalization（奖励归一化）**：
在 RLHF 中，来自 Reward Model 的奖励分数可能不在同一个尺度上，直接用会导致 PPO 更新不稳定。

处理方式：
```python
rewards = (rewards - rewards.mean()) / (rewards.std() + ε)
```

**Advantage Normalization（优势函数归一化）**：
GAE 计算得到的 Advantage A_t 量纲可能很大（因为是累计折扣奖励之和），直接用于策略梯度更新会导致梯度尺度不一致。

处理方式：
```python
advantages = (advantages - advantages.mean()) / (advantages.std() + ε)
```

**为什么需要归一化**：

1. **梯度尺度一致**：不同样本的 A_t 尺度差异大，大的 A_t 主导梯度更新，小的被忽略
2. **学习率适配**：若 A_t 分布不均，统一的学习率对不同样本要么过大（震荡）要么过小（收敛慢）
3. **PPO Clipping 效果**：当 |A_t| 很大时，几乎所有样本的概率比都会被 clip，策略几乎不更新

**ε 的作用**：防止除零错误，通常取 1e-8。

---

## 7. 探索与利用

### Q25：什么是探索-利用困境（Exploration-Exploitation Dilemma）？

**探索-利用困境**是 RL 最核心的权衡问题之一：

- **利用（Exploitation）**：在已知信息下选择当前最优动作（greedy），最大化即时奖励
- **探索（Exploration）**：尝试未知或不确定的动作，可能发现更好的长期策略

**核心矛盾**：如果只利用，智能体会错过潜在更优的长期策略；如果只探索，智能体会浪费大量资源在低奖励动作上。

**经典探索策略**：

1. **ε-greedy**：以概率 ε 随机探索，以概率 1-ε 利用（ε 通常随时间衰减）

2. **Softmax / Boltzmann 探索**：以 softmax 形式选择动作：
   \[ P(a|s) = \frac{e^{Q(s,a)/T}}{\sum_a e^{Q(s,a)/T}} \]
   温度 T 高 → 接近均匀随机（高探索）；T 低 → 接近贪婪（高利用）

3. **Upper Confidence Bound（UCB）**：平衡均值与不确定性：
   \[ A_t = \arg\max_a \left[ Q(s,a) + c \cdot \sqrt{\frac{\ln t}{N(s,a)}} \right] \]
   第二项是置信度上界，访问少的动作被鼓励探索

4. **Thompson Sampling（汤普森采样）**：对每个 (s,a) 的 Q 值维护一个分布（如 Gaussian / Beta），每次采样一个 Q 值作为估计，再选最大 Q 对应的动作

5. **DQN 中的探索**：ε-greedy（早期高 ε，末期低 ε）

**在 LLM 中的体现**：
- LLM 生成本质上是一种"动作空间巨大的离散动作选择"问题
- Temperature 采样控制探索程度
- RLHF/DPO 本质上是在用人类偏好信息引导探索方向

---

### Q26：熵正则（Entropy Regularization）在 RL 中起什么作用？为什么能缓解探索不足？

**熵（Entropy）** H(π) = -Σ_a π(a|s) log π(a|s)，衡量策略的随机性。

**熵正则的 RL 目标**：
\[ J(\pi) = \mathbb{E}_\pi [R] + \alpha \cdot \mathbb{E}_s [\mathcal{H}(\pi(\cdot|s))] \]
其中 α > 0 是熵系数，α 越大 → 越鼓励随机探索。

**为什么高熵（高探索）通常有帮助**：

1. **避免早熟收敛（Premature Convergence）**：没有熵正则时，策略在早期学到贪婪动作后，概率迅速集中在该动作上，失去了探索其他动作的机会。
2. **确保足够的探索**：熵正则自动调节——当策略熵高（探索多）时，正则项贡献正奖励；当策略熵低（探索少）时，正则项惩罚策略过于确定性。
3. **辅助梯度下降**：熵正则提供了一种"内在奖励"（Intrinsic Reward），鼓励策略维持随机性。

**SAC（Soft Actor-Critic）** 是最大熵 RL 的代表：
- 目标函数显式包含熵项：J(π) = Σ_t E[r_t + α·H(π)]
- α 通过自动温度调节机制（adaptive temperature）自动学习
- 最终策略不一定熵高（随着训练，策略本身变好，熵自然下降）

**不同算法的熵正则方式**：

| 算法 | 熵正则形式 | 说明 |
|------|-----------|------|
| PPO | 熵 bonus：L = L_clip + c_2·S(π) | 显式加到损失函数中 |
| SAC | 最大熵目标：J = Σ (r + α·H(π)) | 策略被鼓励同时最大化奖励和熵 |
| A2C | 熵 bonus（可选） | 类似 PPO，但效果通常不如 PPO |
| DQN | 无熵正则 | 纯确定性策略，无探索 |

---

## 8. 多智能体与层次化 RL

### Q27：什么是层次化强化学习（Hierarchical RL, HRL）？它解决什么问题？

**层次化强化学习**将复杂任务分解为多个层级的子任务，每个层级处理不同粒度的决策。

**解决的问题**：

1. **稀疏奖励问题**：原始任务奖励稀少，HRL 通过设计高层目标的密集子奖励来引导学习
2. **长时序任务**：原始 MDP 的时序跨度太长，直接学无法收敛；HRL 用多层 Temporal Abstraction 缩短每层的决策跨度
3. **迁移和泛化**：不同高层目标下的子策略可以复用

**经典 HRL 框架——Options 框架**（Sutton, Precup, Singh, 1999）：

一个 Option o = (I_o, π_o, β_o) 由三部分组成：
- **I_o**：初始条件（option 可以在哪些状态被调用）
- **π_o**：子策略（在 option 执行期间使用的低层策略）
- **β_o**：终止条件（option 在哪些状态下终止）

**两层 Options 框架示例**：
```
高层策略 π_H(s) → 选择 Option（子目标）
Option 1: "走向门"（内含低层策略 π_1: 步进电机控制）
Option 2: "打开门"（内含低层策略 π_2: 机械臂控制）
Option 3: "穿过门"（内含低层策略 π_3: 步进电机控制）
```

**经典 HRL 算法**：

| 算法 | 年份 | 核心思想 |
|------|------|---------|
| Options Framework | 1999 | 用"选项"封装子策略，实现时序抽象 |
| MAXQ | 2000 | 将任务递归分解为子任务的层次结构 |
| FeUdal Networks | 2017 | Manager 生成子目标（隐状态），Worker 执行 |
| HIRO | 2018 | 用 off-policy 方式学习高层和低层策略 |
| HAC | 2019 | 分层Actor-Critic，异步更新各层 |
| Option-Critic | 2017 | 端到端学习 Options 的内部策略和终止条件 |

---

### Q28：什么是多智能体强化学习（MARL）？它的主要挑战是什么？

**多智能体强化学习（MARL）** 研究多个智能体在共享环境中同时学习和决策的问题。

**核心分类**：

1. **合作型（Cooperative）**：所有智能体共享一个团队奖励，如星际争霸中的多单位协作
2. **竞争型（Competitive）**：零和博弈，如棋类、游戏 AI
3. **混合型（Mixed）**：同时存在合作和竞争，如足球比赛

**主要挑战**：

1. **非平稳性（Non-Stationarity）**：在多智能体环境中，每个智能体看到的环境由其他智能体的策略决定。当其他智能体的策略变化时，同一状态的 Q 值也在变化，导致"环境非平稳"——这是 MARL 最核心的困难。

2. **维度爆炸**：状态空间和动作空间随智能体数量指数增长，O((|S|·|A|)^n)

3. **信用分配（Credit Assignment）**：合作任务中，团队奖励如何分配到每个智能体？哪个智能体对团队成功贡献最大？

4. **通信（Communication）**：智能体之间是否需要通信？通信协议如何学习？

**经典 MARL 算法**：

| 算法 | 类型 | 核心思想 |
|------|------|---------|
| QMIX / VDN | 合作 | 中心化训练 + 分散执行（CTDE）；价值分解保证 IGM |
| MADDPG | 混合 | 中心化 Critic + 分散化 Actor |
| MAPPO | 合作 | 多智能体 PPO，利用共享观察降低方差 |
| COMA | 合作 | 中心化 Critic + 差异化的行动者信用分配 |
| QTRAN | 合作 | 精确价值分解，解决 QMIX 的表达能力限制 |

**CTDE（Centralized Training, Decentralized Execution）** 是当前 MARL 主流范式：训练时用全局信息辅助，部署时只依赖局部观察。

---

## 9. RL 在 RAG/LLM 场景的应用思考

### Q29：RL 在 RAG 系统中有哪些应用场景？能否设计一个基于 RL 的检索优化方法？

> [!IMPORTANT]
> **以下全部是 hypothetical future integration。** 本项目当前没有用 RL 优化 RAG，也没有可用的 Ragas/答案质量 reward。若未来实验，reward、训练数据和安全门禁必须独立设计、版本化和验证。

**RL 在 RAG 系统中的潜在应用场景**：

**场景 1：检索策略优化（Retrieval Policy Learning）**

可将 RAG 抽象为 Agent 环境：
- State：用户问题 + 当前检索到的上下文
- Action：是否继续检索、检索哪个索引、采用哪种查询改写
- Future reward：基于独立 qrels 的排序指标、预先定义的任务成功信号，或经独立验证的人类/模型反馈

优化目标可以是学习多跳检索次数、query 变体或索引选择，但不能把当前 lexical overlap 直接称为答案质量 reward。

**场景 2：Rewriter 优化**

未来可用 RL 优化 Query Rewriting 策略；reward 必须来自独立 held-out 任务与 response-level 协议。若未来单独安装、版本化并验证 Ragas，也只能将其作为一项有偏代理信号，不能仅凭该分数代表临床质量。

**场景 3：Reranker 策略学习**

未来可学习检索分数、语义相似度、chunk 长度等特征的组合，并对不同问题类型学习不同权重。优先使用带相关性标注的 qrels 和排序指标，避免让生成模型噪声主导检索 reward。

**场景 4：Self-RAG 风格的自我反思**

可研究让模型判断是否需要检索、证据是否相关以及回答是否被证据支持。该方向需要专门训练和验证，不是当前 endpoint 已提供的能力。

**Hypothetical pipeline**：

```text
Step 1: 在经过许可、去标识且版本冻结的数据上收集状态、动作与结果
Step 2: 用独立 qrels/任务成功信号构造 retrieval reward
Step 3: 将 response-level 人工或模型反馈作为单独 reward 通道，不与 lexical overlap 混称
Step 4: 在 held-out 集上检查泛化、reward hacking 与安全失败
Step 5: 通过门禁后才考虑 policy gradient / PPO 等优化方法
```

当前 `POST /v1/eval/ragas` 的 `context_precision` 只是 context-hit ratio，`context_recall` 只是 ground-truth token coverage，二者按样本宏平均且完全忽略 `response`。它们最多是有偏的检索词汇重叠诊断，**不能作为答案质量、faithfulness、事实正确性、临床安全或临床效果 reward**。

**挑战**：
- RAG 的 action space 离散且巨大；
- reward 容易受生成模型、标注偏差和词汇泄漏影响；
- 容易出现 reward hacking，尤其不能把高 lexical overlap 当成正确答案；
- 医疗场景还需要独立安全审查、停止条件和人工升级机制。

---

### Q30：In-Context Learning（ICL）和 RL 的关系是什么？能否用 RL 优化 ICL 的示例选择？

**In-Context Learning（ICL）** 是 LLM 在不更新参数的情况下，通过输入中的示例学会新任务的能力。给定 prompt = [task description] + [demonstration examples] + [test query]，LLM 能直接生成答案。

**ICL 的本质**：可以视为 LLM 在隐式地做 Bayesian Inference——通过示例推断任务分布参数，然后生成答案。

**RL 与 ICL 的关系**：

1. **RL 可以用于示例选择**：哪些示例最能帮助模型理解任务？
   - 用最终答案质量作为 reward，PPO 优化示例的选择策略
   - 这是 Meta-Learning 思想在 ICL 中的应用——学习"如何学习"（learn to learn）

2. **RLHF 本身就是 ICL 的增强**：RLHF 让模型学会遵循隐式的"人类意图模式"，这些模式以参数化的方式内化在模型中，ICL 则是在推理时激活这些模式

3. **Self-Play 与 ICL**：模型可以与自己生成的数据进行 self-play，类似于 RL 中的 self-play（SFT + RL 的迭代）

**RLHF 中 KL 约束与 ICL 的关系**：
- KL 约束（π_RL 与 π_SFT 的 KL）确保策略不会偏离 SFT 学到的 ICL 能力
- 如果 KL 约束过大，RL 优化退化为在 SFT 附近搜索，可能无法超越 SFT
- 如果 KL 约束过小，策略可能找到"RL hack"——在训练分布内生成高奖励但低质量的内容

---

## 10. 代码实现与算法对比

### Q31：实现一个简化的 PPO 算法（PyTorch pseudocode），并说明关键步骤。

```python
import torch
import torch.nn as nn
import torch.optim as optim
from torch.distributions import Categorical

# ========== 网络定义 ==========
class ActorCritic(nn.Module):
    def __init__(self, obs_dim, act_dim, hidden_dim=64):
        super().__init__()
        self.actor = nn.Sequential(
            nn.Linear(obs_dim, hidden_dim),
            nn.Tanh(),
            nn.Linear(hidden_dim, hidden_dim),
            nn.Tanh(),
            nn.Linear(hidden_dim, act_dim),  # 输出每个动作的 logit
        )
        self.critic = nn.Sequential(
            nn.Linear(obs_dim, hidden_dim),
            nn.Tanh(),
            nn.Linear(hidden_dim, hidden_dim),
            nn.Tanh(),
            nn.Linear(hidden_dim, 1),  # 输出 V(s)
        )

    def forward(self, obs):
        return self.actor(obs), self.critic(obs)

    def get_action(self, obs):
        """给定状态，返回动作（用于数据采集）"""
        logits, value = self.forward(obs)
        dist = Categorical(logits=logits)  # 离散动作分布
        action = dist.sample()            # 采样
        log_prob = dist.log_prob(action)  # log π(a|s)
        entropy = dist.entropy()          # 熵（用于正则）
        return action, log_prob, entropy, value


# ========== GAE 计算 ==========
def compute_gae(rewards, values, dones, gamma=0.99, lam=0.95):
    """
    rewards: list of floats
    values: list of V(s) from critic (包括最后一个状态的bootstrap)
    returns: advantages, returns (用于更新)
    """
    advantages = []
    gae = 0
    # 从后向前计算 GAE
    for t in reversed(range(len(rewards))):
        delta = rewards[t] + gamma * values[t + 1] * (1 - dones[t]) - values[t]
        gae = delta + gamma * lam * (1 - dones[t]) * gae
        advantages.insert(0, gae)

    returns = [adv + val for adv, val in zip(advantages, values[:-1])]
    return torch.tensor(advantages), torch.tensor(returns)


# ========== PPO 训练循环 ==========
def ppo_update(actor_critic, obs_buffer, act_buffer, log_prob_buffer,
               adv_buffer, ret_buffer, optimizer,
               ppo_epochs=10, clip_eps=0.2, entropy_coef=0.01,
               value_coef=0.5):
    """
    对采集到的数据进行多次 PPO 更新
    """
    actor_critic.train()
    obs = torch.stack(obs_buffer)        # [T, obs_dim]
    old_log_probs = torch.stack(log_prob_buffer).detach()  # 旧策略的 log π

    # 标准化 advantages
    advantages = (adv_buffer - adv_buffer.mean()) / (adv_buffer.std() + 1e-8)

    for _ in range(ppo_epochs):
        # 用当前策略计算新的 log π 和 V(s)
        _, new_log_probs, entropy, values = actor_critic.get_action(obs)

        # 概率比 r(θ) = π_θ(a|s) / π_θ_old(a|s)
        ratio = torch.exp(new_log_probs - old_log_probs)

        # Clipped surrogate objective
        surr1 = ratio * advantages
        surr2 = torch.clamp(ratio, 1 - clip_eps, 1 + clip_eps) * advantages
        policy_loss = -torch.min(surr1, surr2).mean()  # PPO 是梯度上升，取负号变损失

        # Value loss (clipping V 以避免过大更新)
        values_clipped = values + torch.clamp(
            values - ret_buffer, -clip_eps, clip_eps
        )
        value_loss1 = (values - ret_buffer) ** 2
        value_loss2 = (values_clipped - ret_buffer) ** 2
        value_loss = 0.5 * torch.max(value_loss1, value_loss2).mean()

        # 熵正则
        entropy_loss = -entropy.mean()

        # 总损失
        loss = policy_loss + value_coef * value_loss + entropy_coef * entropy_loss

        optimizer.zero_grad()
        loss.backward()
        nn.utils.clip_grad_norm_(actor_critic.parameters(), max_norm=0.5)
        optimizer.step()


# ========== 主训练循环（示意）==========
def train():
    actor_critic = ActorCritic(obs_dim=4, act_dim=2)
    optimizer = optim.Adam(actor_critic.parameters(), lr=3e-4)

    for epoch in range(num_epochs):
        # 1. 用当前策略采集数据
        obs_buffer, act_buffer, reward_buffer, done_buffer = [], [], [], []
        values_buffer = [0]  # 初始 V(s0)

        env = make_env()
        obs = env.reset()
        for step in range(steps_per_epoch):
            with torch.no_grad():
                action, log_prob, entropy, value = actor_critic.get_action(torch.tensor(obs).float())
            next_obs, reward, done, _ = env.step(action.item())

            obs_buffer.append(torch.tensor(obs).float())
            act_buffer.append(action)
            reward_buffer.append(reward)
            done_buffer.append(done)
            values_buffer.append(value.item())

            obs = next_obs
            if done:
                obs = env.reset()

        # 2. 计算 GAE
        advantages, returns = compute_gae(reward_buffer, values_buffer, done_buffer)
        advantages = advantages.to(device)
        returns = returns.to(device)

        # 3. PPO 更新
        ppo_update(actor_critic, obs_buffer, act_buffer,
                   log_prob_buffer, advantages, returns, optimizer)
```

**关键步骤说明**：

1. **数据采集**：用当前策略与环境交互，存储 (s, a, r, done, V(s)) 序列
2. **GAE 计算**：从后向前递归计算 advantage，λ 控制 bias-variance 权衡
3. **PPO Clipping**：限制策略变化幅度，保证训练稳定性
4. **多 epoch 更新**：同一批数据多次更新，提高样本效率（PPO 允许）
5. **梯度裁剪**：防止梯度爆炸，保持训练稳定

---

### Q32：TD3 和 SAC 的核心区别是什么？各自适合什么场景？

| 维度 | TD3（Twin Delayed DDPG） | SAC（Soft Actor-Critic） |
|------|-------------------------|-------------------------|
| 策略类型 | 确定性 + 目标策略平滑 | 随机策略（最大熵） |
| Q 值估计 | 双 Q + 延迟更新（避免过估计） | 双 Q + 取 min（减少过估计） |
| 探索方式 | 人工加噪声（clipped noise） | 熵正则（自动调节） |
| 目标网络 | 有（每隔 d 步更新） | 有（软更新 τ） |
| 适用场景 | 连续控制，中等复杂度 | 高维动作空间，稀疏奖励 |
| 调参难度 | 中等（需要手动调探索噪声） | 较高（温度 α 需要调） |
| 理论基础 | 确定性策略梯度（DPG） | 最大熵 RL |

**TD3 的三大技巧**：

1. **双 Q + 延迟更新**：维护两个 Q 网络 Q_θ1, Q_θ2，目标 Q = r + γ·min_i Q_i(s', π_target(s'))
2. **目标策略平滑（Target Policy Smoothing）**：在目标动作上加小噪声：π_target(s') + clip(noise, -c, c)，减少 Q 函数对特定动作的过估计
3. **延迟策略更新**：Actor 每更新 d=2 步才更新一次，减少 Q 估计的方差

**SAC 的关键机制**：

- **自动温度调节**：熵系数 α 不是固定的，而是作为优化变量同时学习
- **软更新**：目标网络参数 τ 软更新（τ=0.005），比 TD3 的硬更新（τ=1.0）更稳定
- **重参数化技巧**：用 reparameterization trick：a = tanh(μ + σ·ε)，使策略采样可导

**选择建议**：
- 动作空间高维、稀疏奖励 → SAC
- 动作空间低维、密集奖励、任务相对简单 → TD3

---

### Q33：请比较 DQN、Double DQN、Dueling DQN 的区别，画出改进路径。

```
DQN（2013, Nature）
│ 核心：端到端深度学习 + Experience Replay + Target Network
│ 问题：Q值过估计（Overestimation）
│
├─→ Double DQN（2015）
│   核心：用Online网络选动作，Target网络评估
│   效果：显著减少过估计，但仍然基于单Q网络
│
└─→ Dueling DQN（2016, ICML）
    核心：Q(s,a) = V(s) + A(s,a)
    效果：更准确的价值估计，特别适合价值变化不大的状态
    可与Double DQN叠加使用
```

**三者的对比**：

| 算法 | 改进点 | 解决的问题 | 改进效果 |
|------|--------|-----------|---------|
| DQN | 深度网络 + Replay + Target Network | 之前的 RL 不支持高维状态空间 | 能在 Atar games 上达到人类水平 |
| Double DQN | 解耦动作选择与价值评估 | Q值过估计导致次优策略 | 过估计减少 30-50%，策略质量提升 |
| Dueling DQN | 分解 V(s) 和 A(s,a) | 单 Q 难以区分"状态好"和"动作好" | 尤其在稀疏奖励的策略学习中提升明显 |

**注意**：Double DQN 和 Dueling DQN 可以**叠加**使用，既解决过估计，又利用价值分解的表示优势。Rainbow DQN 论文将其与其他 6 种技术（Prioritized Replay、Noisy Nets、Distributional RL 等）全部叠加，取得了远超单个技术的效果。

---

### Q34：什么是 Distributional RL？它和普通 RL 相比有什么优势？

**Distributional RL（分布式强化学习）** 是一种将价值函数扩展为**价值分布**的方法，而不是仅仅估计期望值。

**普通 RL**：V(s) 是一个标量，表示期望累计折扣奖励
**Distributional RL**：Z(s) 是一个分布（通常是离散的概率质量分布），V(s) = E[Z(s)] 是这个分布的均值

**C51 算法（Categorical DQN）**：

将价值分布 Z(s) 表示为在 [V_min, V_max] 范围内均匀分布的 51 个离散支撑点：
```
支撑点：z_i = V_min + i·Δz,  i = 0,1,...,50,  Δz = (V_max - V_min) / 50
概率：p_i(s) = Pr(Z(s) = z_i)
```
通过 DNN 输出每个支撑点的概率 p_i，然后通过 Bellman 更新：

\[ p_i(s') \leftarrow \sum_j p_j(s') \cdot \text{Proj}\left[r + \gamma z_j, \{z_i\}\right] \]

其中 Proj 是将目标分布投影到支撑点上（ distributional projection）。

**为什么 Distributional RL 有效**：

1. **表示更丰富**：期望值相同但方差不同的状态，普通 RL 看不到区别，但 Distributional RL 能区分"高风险高回报"和"低风险低回报"
2. **梯度信息更多**：普通 RL 只有 V(s) 的梯度，Distributional RL 有整个分布的梯度
3. **收敛更快**：分布的方差信息帮助策略更快识别高风险状态
4. **与人类决策更接近**：人类对风险的态度（risk-averse/risk-seeking）可以通过价值分布建模

**Rainbow DQN（2017, AAAI）**：将 Distributional RL 与其他 6 种 DQN 改进（Double DQN、Prioritized Replay、Dueling DQN、Noisy Nets、Multi-step Learning、A3C N-step）全部叠加，在 Atari 57 上取得当时 SOTA。

---

## 参考资料索引

| 主题 | 经典论文 |
|------|---------|
| DQN | Mnih et al., "Human-level control through deep reinforcement learning", *Nature* 2015 |
| Double DQN | Hasselt et al., "Deep Reinforcement Learning with Double Q-learning", *AAAI* 2016 |
| Dueling DQN | Wang et al., "Dueling Network Architectures for Deep RL", *ICML* 2016 |
| Policy Gradient | Sutton et al., "Policy Gradient Methods for Reinforcement Learning", 1999 |
| PPO | Schulman et al., "Proximal Policy Optimization Algorithms", *arXiv* 2017 |
| TRPO | Schulman et al., "Trust Region Policy Optimization", *ICML* 2015 |
| A3C | Mnih et al., "Asynchronous Methods for Deep Reinforcement Learning", *ICML* 2016 |
| DDPG | Lillicrap et al., "Continuous Control with Deep Reinforcement Learning", *ICLR* 2016 |
| SAC | Haarnoja et al., "Soft Actor-Critic: Off-Policy Maximum Entropy Deep RL", *ICML* 2018 |
| TD3 | Fujimoto et al., "Addressing Function Approximation Error in Actor-Critic Methods", *ICML* 2018 |
| GAE | Schulman et al., "High-Dimensional Continuous Control Using Generalized Advantage Estimation", *ICLR* 2016 |
| RLHF | Ouyang et al., "Training language models to follow instructions with human feedback", *NeurIPS* 2022 |
| DPO | Rafailov et al., "Direct Preference Optimization: Your Language Model is Secretly a Reward Model", *NeurIPS* 2023 |
| GRPO | DeepSeek Team, "DeepSeekMath: Pushing the Limit of Mathematical Reasoning in Open Language Models", *arXiv* 2024 |
| Options Framework | Sutton et al., "Between MDPs and Semi-MDPs: A Framework for Temporal Abstraction in RL", *AIJ* 1999 |
| QMIX | Rashid et al., "QMIX: Monotonic Value Function Factorisation for Deep Multi-Agent RL", *ICML* 2018 |
| Distributional RL | Bellemare et al., "A Distributional Perspective on RL", *ICML* 2017 |
| Rainbow DQN | Hessel et al., "Rainbow: Combining Improvements in Deep RL", *AAAI* 2018 |
| Self-RAG | Asai et al., "Self-RAG: Learning to Retrieve, Generate, and Critique through Self-Reflection", *ICLR* 2024 |

---

## 11. RAG 核心技术与工程实践
### Q35：针对长短期记忆，讲讲你是如何设计记忆的提取、压缩与冲突更新机制的？

**长短期记忆在 RAG 中的映射**：

在 Agentic RAG 系统中，"记忆"可类比为用户的查询历史与检索上下文的累积，设计机制如下：

**记忆提取（Retrieval / Extraction）**：

短期记忆对应当前对话轮次内的上下文（最近 N 轮对话），长期记忆对应历史会话的摘要。

提取策略：
- **滑动窗口**：维护最近 5 轮对话，每轮存储 (user_query, retrieved_chunks, generated_answer)
- **重要性筛选**：用 LLM 判断当前查询与历史记忆的相关性得分，只召回相关性 > 0.7 的历史片段
- **向量相似度召回**：将用户当前问题编码后，在历史记忆向量库中检索相关历史 Q&A 对

**记忆压缩（Summarization / Compression）**：

当短期记忆达到容量上限时，触发压缩：
- 用 LLM 对历史片段做摘要提取：`[summary] = LLM.summarize([session_history])`
- 压缩后保留：关键信息（药物名称、诊断结论、禁忌事项）和对话主题标签
- 压缩后的摘要存入长期记忆向量库，原始对话记录可丢弃或存档

**冲突更新（Conflict Resolution）**：

当新文档更新导致旧知识被覆盖时，采用以下策略：

1. **时间戳优先级**：新文档带版本号，检索时优先使用最新版本 chunk，通过 `chunk.metadata["version"]` 过滤
2. **语义冲突检测**：如果新旧两个 chunk 的向量相似度 > 0.9 但内容矛盾，触发冲突告警，人工审核
3. **置信度加权**：Reranker 分数 × 文档来源权重（如权威指南权重 1.0 vs 用户生成内容权重 0.5），综合排序
4. **增量写入而非覆盖**：使用 upsert（按 chunk_id 覆盖），同一 chunk_id 的新版本替换旧版本，保留版本历史用于回滚

---

### Q36：讲一下 dense 向量与 sparse 向量的区别，分别适合处理什么样的搜索需求？

**Dense Vector（稠密向量）**：

将文本映射为固定维度（通常 768/1024 维）的连续浮点向量，大部分维度均有非零值。

```python
# Dense 向量示例（1024维，截断显示）
[0.012, -0.034, 0.056, 0.089, -0.021, ...]  # 每个维度都是连续的浮点数
```

| 特性 | 说明 |
|------|------|
| 表达能力 | 强，能捕捉语义相似性（同义词、多义词） |
| 典型模型 | BGE-M3、DPR、BERT-based |
| 适用场景 | 语义匹配、语义等价查询、跨语言检索 |
| 优点 | 能理解"狗"和"犬"语义相近；能处理长文本的语义表示 |
| 缺点 | 存储成本高；冷启动需要大量语料训练；对精确关键词不敏感 |

**Sparse Vector（稀疏向量）**：

大部分维度为零，仅少数维度有值，本质是 BM25 风格的词项权重（字典格式）。

```python
# Sparse 向量示例（字典格式：token_id → weight）
{1234: 0.8, 5678: 0.5, 9012: 0.3}  # 仅少数维度有非零值
```

| 特性 | 说明 |
|------|------|
| 表达能力 | 弱，仅捕捉词项共现和 TF-IDF 权重 |
| 典型模型 | BM25、TF-IDF、BGE-M3 sparse 头 |
| 适用场景 | 精确关键词匹配，专业术语检索、搜索结果初筛 |
| 优点 | 精确匹配能力强；存储稀疏（仅存非零值）；无需训练 |
| 缺点 | 不能处理同义词；中文需要分词，分词质量影响大 |

**各自的搜索需求适配**：

| 场景 | Dense | Sparse |
|------|-------|--------|
| "左乙拉西坦适应症" vs "开浦兰适应症" | ✅ 强（语义等价） | ❌ 弱（词不同） |
| "抗癫痫药物副作用"（通用问法） | ✅ 强 | ⚠️ 中（关键词依赖） |
| "SE 持续状态的处理"（专业缩写） | ⚠️ 中（缩写需训练覆盖） | ✅ 强（词项精确匹配） |
| 跨语言：中英混合查询 | ✅ 强（BGE-M3 多语言） | ❌ 弱（分词语言边界） |

本系统使用 **BGE-M3 混合检索**：dense（权重 0.65）负责语义匹配，sparse（权重 0.35）负责词项精确匹配，两者互补。

---

### Q37：在向量化之前，为什么要对长文档进行 chunk？如果不 chunk 会有什么后果？

**为什么要 chunk（分块）**：

LLM 的上下文窗口有长度限制（如 8K/32K tokens），而且 token 计费按量收费，过长的上下文直接推送给 LLM 成本极高。

chunk 的核心目标：
- **控制上下文长度**：每个 chunk 编码后送入 LLM，保证上下文在 max_tokens 限制内
- **提高检索精度**：小块语义更集中，匹配更精准；大块噪声多，检索时容易引入不相关内容
- **提升向量质量**：语义集中的短文本比语义分散的长文本更容易编码出有区分性的向量

**如果不 chunk 的后果**：

1. **向量退化**：一篇 50 页的 PDF 编码为单一向量，信息高度混杂，向量空间被稀释，检索时与查询的相似度普遍偏低。

2. **Top-K 噪声淹没**：召回了整篇文档，上下文太长超过 LLM 窗口；如果取多个 Top-K，每个 chunk 包含大量无关内容，生成答案时 LLM 被噪声干扰。

3. **细粒度召回失效**：用户问"左乙拉西坦和德巴金哪个更易导致胎儿畸形"，召回了整本药品说明书，LLM 难以聚焦到具体对比段落。

4. **embedding 模型限制**：大多数 embedding 模型有 max_length（如 512 tokens），超过的部分被截断，重要信息可能丢失在不均匀的边界处。

---

### Q38：切片时设置重叠区域的作用是什么？这个比例通常怎么来确定？

**重叠区域（Overlap）的作用**：

chunk 边界切断了语义上下文，重叠让相邻块之间保留上下文连续性。

1. **防止主题在边界处被切断**：一段完整的"左乙拉西坦适应症"讨论可能被边界切成"左乙拉西坦"和"适应症"两个不完整的块
2. **保留跨块推理链**：某些医学推理需要跨段落的信息（如"第3段提到的药物→第7段提到的剂量"），重叠让这种跨块关联更容易被完整召回
3. **提升召回覆盖率**：用户问题可能恰好命中块边界附近的关键词，重叠增加了命中概率

**重叠比例的确定方法**：

| 方法 | 说明 | 适用场景 |
|------|------|---------|
| 固定重叠 token 数 | 如 chunk_size=500, overlap=50 tokens（10%） | 通用场景，简单有效 |
| 固定重叠比例 | overlap_ratio = 0.1 ~ 0.3 | 文档长度均匀时 |
| 自适应重叠 | 根据语义边界（段落/章节）动态决定 | 复杂文档结构 |
| 预注册调参 | 在独立 held-out、带相关性标注的检索集上 sweep，并按预先定义的 retrieval metric 选参 | 实际项目迭代 |

> **当前实现边界**：如果仅把 `deterministic_lexical/token_overlap_v1/macro_average` 用作辅助诊断，必须写明它只比较 ground truth 与 contexts、忽略 `response`，并防止在同一 ground truth 上调参和报告。该 lexical overlap 不是 Ragas、答案质量或临床 reward。

**本系统的做法**：

- 固定 chunk_size = 300-500 字符，覆盖一段完整的医学描述段落
- 重叠通过**父子分块（Parent-Child Chunking）**策略替代显式 overlap：
  - **子块（Child Chunk）**：300-500 字符，用于精确检索（高召回）
  - **父块（Parent Chunk）**：包含 2-4 个子块，上下文更完整，用于答案生成（高质量上下文）
- 这样做的好处是：检索用小块（精准），生成用大块（完整语义），避免 overlap 存储浪费

**overlap 过大的问题**：相邻块高度相似，检索结果冗余，存储成本上升；overlap 过小则语义割裂问题重现。

---

### Q39：余弦相似度和欧氏距离在衡量文本相似性时，各自的优缺点是什么？

**余弦相似度（Cosine Similarity）**：

衡量两个向量的**方向**是否接近，取值 [-1, 1]，通常用于归一化后的 embedding 向量。

| 优点 | 说明 |
|------|------|
| 对向量长度不敏感 | 只看方向不看大小，适合比较不同长度文本的语义方向是否一致 |
| 计算稳定 | 分母归一化后，向量尺度的变化不影响相似度 |
| embedding 场景天然适配 | BGE-M3 等 embedding 模型输出的向量通常已 L2 归一化，余弦等价于内积 |

| 缺点 | 说明 |
|------|------|
| 不能捕捉向量大小差异 | "积极"和"非常积极"，余弦相似度可能都很高，但语义强度不同 |
| 对稀疏向量的区分度有限 | Sparse 向量中，词项权重的绝对值差异被忽略 |

**欧氏距离（Euclidean Distance / L2 距离）**：

衡量两个向量在空间中的绝对距离，取值 [0, +∞)。

| 优点 | 说明 |
|------|------|
| 捕捉绝对差异 | 能区分"方向相似但幅度不同"的情况（如"价格 100 元"vs"价格 10000 元"） |
| 适合聚类任务 | K-Means 等聚类算法用欧氏距离，语义紧凑的簇内距离更小 |

| 缺点 | 说明 |
|------|------|
| 对向量长度敏感 | 长文本向量模长大，距离被放大，导致不公平比较 |
| 在高维空间中区分能力下降 | "维度灾难"——高维 embedding 空间中所有点之间距离趋同（Hubness 问题） |

**实际选择**：

- **向量检索（BGE-M3 等 embedding）**：推荐 **余弦相似度**。embedding 通常 L2 归一化后使用，余弦等价于内积，计算快且稳定。
- **稀疏向量（BM25）**：本质上用词项频率的内积，与余弦等价。
- **重排序（Reranker）**：输出的是归一化的相关性分数，直接比较即可。
- **聚类/分类任务**：欧氏距离可能更有意义。

---

### Q40：向量库检索出的 Top-K 结果，如果 K 值设置得过大，对后续的生成质量有哪些负面影响？

**K 值过大对生成质量的负面影响**：

**1. 上下文噪声稀释（Context Dilution）**

K 过大 → 召回了大量低相关性 chunk → LLM 的上下文被噪声淹没 → 生成答案时 LLM 无法区分哪些是证据哪些是干扰。LLM 对上下文中所有 token 做 Attention，低相关 chunk 稀释了关键证据的注意力权重。

**2. Token 成本爆炸**

K 过大 → 上下文 token 数激增 → LLM API 费用和延迟同步上升。本系统 `max_context_chars=5000` 限制了总 token 上限，K 过大意味着单块长度必须压缩，每个 chunk 只能截取很短的内容。

**3. 检索-生成不一致（Irrelevant Distraction）**

当 top-k 中混入语义相似但实际无关的 chunk（如"癫痫"和"头晕"），LLM 可能被这些 chunk 误导，给出错误的临床建议，在医疗场景下可能造成安全隐患。

**4. Reranker 性能下降**

Reranker 的交叉编码计算量与候选数 O(n) 成正比。K 过大（n > 100）时，Reranker 计算开销显著增加，且低质量 chunk 比例上升，精排效果被稀释。

**5. 答案冗余**

上下文过长，LLM 生成的答案可能变成多段信息的堆砌，而非针对问题的精准回答。

**本系统的 K 设定**：
- **初筛阶段**：`dense_top_k=12, sparse_top_k=12`，候选池最多 `top_k * 4 = 48`
- **精排阶段**：`reranker_top_k=5`，最终返回 5 个精排 chunk 给 LLM
- K 过大时，在 Reranker 之前增加**相关性阈值过滤**（如 score < 0.3 的 chunk 直接丢弃）

---

### Q41：为什么在初筛召回之后，还要加一个 Rerank 模型？能解决向量搜索哪些局限？

**双塔模型（Bi-Encoder）的根本局限**：

向量检索用双塔模型：query 和 doc 分别独立编码为向量，编码时彼此"看不到"对方的信息。

```
Query encoding:    Q = [q_1, q_2, ..., q_d]  (只看 query 自身)
Doc encoding:      D = [d_1, d_2, ..., d_d]  (只看 doc 自身)
Retrieval score:   sim(Q, D) = Q · D  (只看向量空间中的距离)
```

**双塔模型不能捕捉的信息**：
- Doc 中哪个词/短语最匹配 query 的哪个部分
- Query 和 Doc 之间精确的语义交互（如"副作用"在 doc 中的位置和上下文）
- 否定词匹配（query 说"不包括"，doc 中的"包括"应该被降权）

**Reranker（交叉编码器 / Cross-Encoder）的优势**：

Reranker 将 query 和 doc **拼接后一起输入编码器**，在每一层 Self-Attention 中 query 和 doc 的 token 全部交互，输出精确的相关性分数。

**Reranker 解决的问题**：

| 问题 | 双塔模型的局限 | Reranker 的解决 |
|------|-------------|----------------|
| **细粒度相关性** | 只能给出"大致相似"分数 | 能判断"这个 doc 片段是否真的回答了问题" |
| **精确匹配** | 语义相近但词项不符的情况 | 能捕捉关键词精确匹配（如药名、剂量数字） |
| **长 doc 稀释** | 长 doc 编码向量被稀释 | 交叉编码对 doc 中每个 token 都做 query 相关的注意力加权 |
| **多意图** | doc 中多主题混杂，只能给一个分数 | 能聚焦到 doc 中最相关的那个片段 |
| **否定词处理** | "不能开车"和"可以开车"向量可能相似 | 能识别"不/不能"等否定修饰词的语义影响 |

**本系统的 Reranker 流程**：

```
混合检索（快，粗筛）→ 候选池 top 48 → BGE Reranker（慢，精排）→ 最终 top 6
                                        ↓
                          混合评分: 0.4 × retrieval_score + 0.6 × reranker_score
```

---

### Q42：如何评估 Rerank 的有效性？有什么指标吗？

**Rerank 有效性评估指标**：

**1. 分层指标对比（最直观）**

| 指标 | 含义 | 预期变化 |
|------|------|---------|
| **NDCG@K**（Normalized Discounted Cumulative Gain） | 检索结果排序质量，0~1，越高越好 | Reranker 后 NDCG@3/5/10 提升 |
| **MAP**（Mean Average Precision） | 前 K 个结果中相关文档的平均精确率 | 提升 |
| **MRR**（Mean Reciprocal Rank） | 第一个相关文档的排名倒数均值 | 提升 |
| **Hit Rate@K** | 前 K 个结果中是否包含正确答案 | Reranker 后 hit rate 提升 |

**2. 与 ground truth 的对比**

```
Recall@K = |Retrieved_top_K ∩ Gold_Relevant| / |Gold_Relevant|
```

Reranker 后 recall@K 提升 → 说明更多相关 doc 被排到了前面。

**3. Reranker 分数与人工标注相关性**

计算 Reranker 输出的模型分数与人工分数的 **Spearman / Kendall-Tau 相关系数**。相关系数越高，说明 Reranker 的排序越符合人类判断。

**4. Response-level 评估（独立的未来协议）**

Reranker 对生成回答的影响只能通过独立、版本化的 response-level 协议评估，例如盲化人工 rubric、任务级事实核对或经单独验证的评估器。未来若独立安装和验证 Ragas，也只能按该版本的明确定义使用；不能因 legacy URL 名称就声称当前已有 Ragas 或 factuality 数据。

当前 `POST /v1/eval/ragas` 忽略 `response`。其 `context_precision` 是 context-hit ratio，`context_recall` 是 ground-truth token coverage，按样本宏平均；这些 lexical diagnostics 不能证明精排改善了生成质量。

**5. A/B 线上评估（未来且需安全门禁）**

可在适当授权和监控下比较 Reranker 开启/关闭的任务完成率或用户反馈，但满意度也不能直接代表事实正确性或临床安全。

**本系统可区分的三层评估**：

1. **排序层**：在带 qrels 的 held-out 检索集上报告 NDCG/MAP/MRR/Hit Rate；这是评估 Rerank 的首选。
2. **当前 lexical context diagnostic**：`deterministic_lexical/token_overlap_v1/macro_average` 只观察 ground truth 与 retrieved contexts 的词项命中和覆盖，不评估答案。
3. **未来 response/人工/安全评估**：必须独立设计、版本化和验收；不得用当前 lexical overlap 代替，也不得外推为临床表现。

人工抽检 top-k 相关性可以作为补充，但需记录抽样规则、标注 rubric 与分歧处理。

---

### Q43：Rerank 的 Top-k 数量怎么确定？

**Rerank Top-k 的确定需要平衡精度与效率**：

**关键约束**：

1. **计算成本**（交叉编码 O(n)）：候选数越多计算量越大，从 48 → 96 计算量翻倍，但收益不一定翻倍
2. **上下文容量限制**：最终送入 LLM 的 token 数有限（max_context_chars=5000），每个 chunk 平均 800 chars，6 个 chunk = 4800 chars

**工程经验法则**：

| 场景 | Reranker 候选数 | 最终 top_k | 理由 |
|------|----------------|-----------|------|
| 本系统配置 | 48 个候选 | **6 个输出** | 平衡上下文质量与 token 成本 |
| 高精度场景 | 64-100 候选 | 10-20 输出 | 可接受更高延迟，追求极致召回 |
| 实时性要求高 | 32 候选 | 4 输出 | 延迟优先，容忍少量召回损失 |

**自适应 Top-K 方法**：

- **基于 query 长度**：长 query（复杂问题）→ 更多 top_k（更多证据）；短 query → 较少 top_k
- **基于意图类型**：`both` 意图需要覆盖 literature + clinical 两个维度，top_k 可适当增大
- **基于分数 gap**：如果 top_1 和 top_2 的 Reranker 分数差距极大（如 0.9 vs 0.3），只取 top_1 即可

---

### Q44：对于 RAG，既然向量检索已经计算了相似度，为什么还要引入交叉编码器进行重排？

**核心回答**：

向量检索的相似度和 Reranker 的相关性分数**衡量的是不同的东西**，不可替代。

**向量检索的相似度衡量的是"编码空间中的距离"**：

当 query="左乙拉西坦的副作用有哪些"，向量检索找到与 query 向量距离近的 doc。这个距离度量的是 doc 的**整体语义主题**是否与 query 相似，但无法判断 doc 中的**哪一部分**与 query 相关。

**交叉编码器衡量的是"query 与 doc 之间细粒度的交互匹配"**：

Reranker 把 query 和 doc 拼接后一起编码，在注意力层中：
- query 中的"副作用"会与 doc 中所有出现"副作用"的位置交互
- 可以捕捉 doc 中哪一段是最直接回答"副作用"问题的
- doc 中其他不相关段落不会分散注意力

**类比理解**：
- 向量检索 = 用航拍图找最近的机场（只知道大致方向）
- Reranker = 用导航地图精确定位最近的停车场入口（考虑了具体路线和障碍物）

**为什么不直接用 Reranker 做检索**：

Reranker 无法预计算 doc 向量——每次都要把 query 和 doc 一起编码，无法用 FAISS/Qdrant 的快速向量索引。交叉编码的 O(n) 复杂度对百万级文档库不可接受，只能做精排。

**本系统的混合评分**：

```python
final_score = 0.4 × retrieval_score + 0.6 × reranker_score
```

0.6 的权重给 Reranker，说明 **精排的语义理解能力远强于双塔匹配**，混合评分比单独使用任一指标都更鲁棒。

---

### Q45：如果文档发生了局部更新，如何通过增量索引来避免全量重新向量化？

**增量索引（Incremental Indexing）的核心思想**：只对变更的文档做处理，不触碰未变化的文档。

**增量更新场景**：
1. **文档内容修改**（如药品说明书更新了某药物的剂量信息）
2. **新增文档**（如新增一篇 ILAE 指南 PDF）
3. **文档删除**（如某临床病历过期下架）

**增量索引的实现方案**：

每个 chunk 携带唯一标识 `chunk_id = hash(doc_id + chunk_index)`：

```python
# 新增文档
new_chunks = parse_and_chunk(new_pdf)
for chunk in new_chunks:
    chunk_id = generate_chunk_id(chunk)
    if chunk_id not in existing_ids:     # 仅处理新 chunk
        dense, sparse = embedder.encode(chunk.text)
        store.upsert(chunk_id, dense, sparse, metadata)

# 文档更新（局部修改）
updated_doc = reparse(updated_pdf)
old_chunk_ids = get_chunks_by_doc_id(doc_id)   # 找到该文档的所有旧 chunk
new_chunks = chunking(updated_doc)
for chunk in new_chunks:
    chunk_id = generate_chunk_id(chunk)
    if chunk_id in old_chunk_ids:
        # 已存在 → 重新向量化并更新
        dense, sparse = embedder.encode(chunk.text)
        store.upsert(chunk_id, dense, sparse, metadata)
    else:
        # 新增 → 插入
        store.insert(chunk_id, dense, sparse, metadata)
# 删除旧 chunk
store.delete(list(old_chunk_ids - new_chunk_ids))
```

**版本号 + 灰度切换**：

同一 doc_id 允许存在多个版本，检索时过滤 `version == latest`：

```python
# 检索时只查最新版本
results = store.hybrid_search(query, doc_type, top_k,
                               prefilter=lambda m: m.get("version") == latest_version)
```

**增量索引的注意事项**：
1. **父子块关系**：更新子块时需要同步更新父块
2. **Qdrant 等向量库的 upsert**：大多数向量库支持按 ID 的原子 upsert，无需手动判断存在性
3. **回滚机制**：保留最近 N 个版本，必要时可回滚到旧版本

---

### Q46：在 RAG 的生成阶段，如何在 Prompt 中设定边界条件来防止模型在没搜到内容时产生幻觉？

**核心策略：显式约束 + 强制区分 + 兜底机制**

**1. Prompt 中的显式指令（系统提示词）**

```python
ANSWER_SYSTEM_PROMPT = """你是癫痫专科智能问诊助手，仅基于给定证据回答。

你必须：
1. 直接输出最终结论，不得包含 <thinking> / <final_answer> 等 XML 标签
2. 区分"已有证据"与"经验性建议"，不得编造文献结论
3. 涉及急危重症必须明确标注【急危重症】并强烈建议立即线下就医/急救
4. 明确声明本回答不能替代医生面诊

【当检索证据无法直接回答问题时，必须严格按以下格式输出】：

依据本地知识库未找到直接答案，结合通用医学知识建议如下：
【结论】
【证据依据】(无可用证据写"无本地证据支持"或"[无]")
【风险与边界】(区分有证据支持和建议性内容)
【下一步建议】(区分紧急和常规)
"""
```

**关键设计**：
- "仅基于给定证据回答"：明确告诉模型不要超出上下文范围
- "不得编造文献结论"：直接禁止幻觉
- "区分已有证据与经验性建议"：强制模型对无证据部分做显式标注

**2. 无证据时的强制输出格式**

```
【证据依据】[无本地证据支持]
【风险与边界】以下内容基于通用医学知识，无法保证完全准确，建议咨询专科医生。
```

**3. CoT 过程中的幻觉过滤**

用 `<thinking>` 标签包裹内部推理，post_guard 节点统一过滤：

```python
answer = re.sub(r"<thinking>\s*.*?\s*</thinking>", "", answer, flags=re.DOTALL)
```

**4. post_guard 后处理节点**

```python
if "cannot replace" not in answer.lower():
    answer += "\n\nNotice: This system is for information retrieval assistance only..."
```

**5. Reranker 的隐式幻觉减少**

Reranker 精排后，top_k 中的 chunk 都是与 query 高度语义相关的，从源头减少了低质量 chunk 引发幻觉的概率。

**6. Self-RAG 风格的自我验证（进阶）**

Self-RAG 的思路是训练一个"反思 token"，让模型在生成时主动判断：
- ` Retrieve `：是否需要检索？
- ` ISREL `：检索到的内容是否相关？
- ` ISSUP `：当前生成的内容是否被证据支持？

这一机制可以在生成阶段主动拒绝不忠实于检索上下文的回答，从模型内部而非 Prompt 层面解决幻觉。

---

### Q47：调用大模型 API 时，为什么要使用 asyncio 异步编程？它在处理高并发请求时有何优势？

**同步 vs 异步的本质区别**：

**同步调用**：发起请求 → 等待 HTTP 响应 → 收到响应 → 继续执行。总耗时 = T1 + T2 + T3（三段等待时间相加）

**异步调用（asyncio）**：发起请求 → 切换执行权 → 等待期间处理其他任务。总耗时 ≈ max(T1, T2, T3)（最慢的请求时间）

**asyncio 在高并发中的核心优势**：

| 优势 | 说明 |
|------|------|
| **并发非并行** | 单线程内通过事件循环切换任务，在 I/O 等待时处理其他请求，无需多线程/多进程 |
| **资源高效** | 不需要为每个请求创建线程（线程栈开销 1-8MB），协程栈仅几 KB |
| **无阻塞** | async/await 语义清晰，I/O 操作让出控制权，CPU 在等待网络响应时处理其他请求 |
| **高吞吐** | 单机可支持上万并发连接，适合 RAG 系统中多用户同时请求 |

**asyncio 在 RAG 系统中的典型使用场景**：

```python
import asyncio
import httpx

async def batch_generate(questions: list[str]) -> list[str]:
    """并发调用 LLM API，同时处理多个问题"""
    async with httpx.AsyncClient(timeout=120.0) as client:
        tasks = [call_llm(client, q) for q in questions]
        results = await asyncio.gather(*tasks)  # 并发执行
    return results

async def call_llm(client: httpx.AsyncClient, question: str) -> str:
    """单个 LLM 调用（异步 HTTP POST）"""
    response = await client.post(
        "http://127.0.0.1:8000/v1/chat/completions",
        json={
            "model": "DeepSeek-R1-Distill-Qwen-32B-AWQ",
            "messages": [{"role": "user", "content": question}],
            "temperature": 0.2,
        }
    )
    return response.json()["choices"][0]["message"]["content"]
```

**在 RAG pipeline 中的具体应用**：

- **意图路由**：一个 LLM 调用，同时判断意图（可以并行）
- **Multi-Query 检索**：3 个查询变体的 embedding 和检索可以并行执行（`asyncio.gather`）
- **LLM-as-Judge**：多个候选答案的评分可以并行提交给 Judge 模型

**如果不用 asyncio 的代价**：
- 同步调用时，Multi-Query 3 个变体串行检索，总延迟 = t1 + t2 + t3
- 异步并行后，总延迟 = max(t1, t2, t3)，节省约 2/3 的等待时间
