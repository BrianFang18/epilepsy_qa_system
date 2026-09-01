# 实验验证指南

> [!WARNING]
> **状态：历史实验草案已归档，当前不支持直接照此运行。** 旧版文档中的 `quantization_benchmark.py`、`run_full_evaluation.py`、`COT_MODE`、固定样本规模、`--alpha`、`final_avg`、Jaccard composite 等名称或流程未在本指南中复核，不得视为当前可执行验收步骤，也不得据此填写简历结果。

本文档只给出可审计的实验边界和记录方法。任何性能、检索、回答或临床结论都必须来自独立、可复现的实测记录，不能使用“预期值”代替结果。

---

## 1. 当前评估实现

`POST /v1/eval/ragas` **仅是 legacy compatibility URL**；当前未安装、也未运行 Ragas。

当前返回口径为：

- `backend=deterministic_lexical`
- `metric_version=token_overlap_v1`
- `aggregation=macro_average`
- `context_precision`：每个样本中 ground truth 与 retrieved contexts 的 context-hit ratio（兼容字段名）
- `context_recall`：每个样本中 retrieved contexts 对 ground-truth token 的 coverage（兼容字段名）
- 聚合方式：先计算每个样本，再对样本做宏平均
- `response`：不参与计算

因此，这两个字段只用于检查 ground truth 与检索上下文的确定性词项重叠。它们不代表 Ragas 或 faithfulness，也不能证明回答事实正确性、CoT 有效性、临床安全或临床效果。

---

## 2. 实验结论的分层

实验开始前先声明要验证哪一层，不能跨层外推：

| 层级 | 可以验证的内容 | 不能自动推出的内容 |
|---|---|---|
| 接口/运行 | 请求能否完成、schema 与元数据是否符合约定 | 模型或检索质量 |
| 性能 | 指定环境下的显存、延迟、吞吐量 | 回答正确性或临床效果 |
| Lexical context diagnostic | ground truth 与 retrieved contexts 的词项命中及覆盖 | response 质量、faithfulness、事实正确性 |
| Response-level evaluation | 按独立协议评估生成回答 | 临床安全或临床效果 |
| 临床研究 | 预注册协议下的临床终点 | 超出研究设计和样本范围的结论 |

当前 legacy endpoint 只覆盖第三行，而且只是 lexical diagnostic。

---

## 3. 量化与性能实验

量化对比必须在相同硬件、模型 artifact、服务参数、请求集、预热策略和采样次数下进行。不要预填显存节省、延迟加速或吞吐提升。

至少记录：

- 日期、代码版本和模型 artifact 标识
- GPU 型号、数量、显存和驱动/runtime 版本
- 量化方式、上下文长度、batch/concurrency 与服务参数
- 请求集定义、预热次数、正式采样次数
- 显存峰值、P50/P95 延迟、吞吐量及失败率
- 原始结果位置和统计方法

结果表：

| 配置 | 显存峰值 | P50 延迟 | P95 延迟 | 吞吐量 | 失败率 | 证据位置 |
|---|---:|---:|---:|---:|---:|---|
| 基线 | 待实测 | 待实测 | 待实测 | 待实测 | 待实测 | 待填写 |
| 候选 | 待实测 | 待实测 | 待实测 | 待实测 | 待实测 | 待填写 |

只有在以上条件一致并保存原始结果后，才能描述观察到的性能差异。

---

## 4. CoT 或生成策略 A/B

当前 deterministic lexical endpoint 忽略 `response`，所以不能用于比较 standard/structured CoT、回答逻辑、事实正确性或安全性。旧版“比较综合得分即可确认 CoT 提升”的实验方法已停止支持。

未来若开展 response-level A/B，至少需要：

1. 预先固定互斥实验变量和生成参数；
2. 使用独立、版本化且不由同一待测系统生成的参考或评分协议；
3. 对样本随机化并尽可能盲化；
4. 分别报告事实性、证据支持、任务完成度和安全错误，不合成为“临床质量分”；
5. 保存失败样本、置信区间和人工分歧；
6. 不把自动指标直接外推为临床效果。

在这套协议实际实施并留存证据前，只能把 CoT 对比写为未来实验计划。

---

## 5. 数据集与 ground truth

- ground truth 必须记录来源、许可、版本、创建方式和适用范围。
- 不应使用同一待测 retriever 的 contexts 和同一待测生成器制作 ground truth 后，再用词项重叠评价该系统；这会造成循环验证和词汇泄漏。
- LLM 辅助标注只能作为待审核草稿，不能因少量抽检而自动代表整个数据集正确。
- 开发集、调参集和最终评估集应分离；不得在最终评估集上反复调参。
- 涉及医学主张时，应定义具有相应资质的审核角色、分歧处理和版本冻结流程。
- 样本数量必须按实际数据记录，不使用未经核验的固定规模或语料数量。

---

## 6. Legacy lexical diagnostic 的报告方式

调用 legacy URL 时，每份结果至少同时记录：

```text
endpoint: POST /v1/eval/ragas (legacy compatibility URL)
backend: deterministic_lexical
metric_version: token_overlap_v1
aggregation: macro_average
context_precision: <实测宏平均；语义为 context-hit ratio>
context_recall: <实测宏平均；语义为 ground-truth token coverage>
response_evaluated: false
```

报告中禁止：

- 将该端点简称为“RAGAS 评估”或声称项目正在运行 Ragas；
- 将兼容字段解释为标准 Ragas 指标或 faithfulness；
- 将二者加权成 composite、`final_avg`、答案质量分或临床分；
- 根据字段升降断言回答更正确、更安全或临床效果更好；
- 隐去 backend、metric version、aggregation 或 response 未计分这一限制。

---

## 7. 实验记录模板

```text
实验名称：
实验目的：
状态：计划 / 已执行 / 失败 / 已作废
代码版本：
运行环境：
数据集名称与版本：
数据来源与许可：
样本选择规则：
唯一实验变量：
指标定义与版本：
聚合方式：
原始结果位置：
实测结果：
失败与缺失样本：
已知限制：
复核人和日期：
```

不要在执行前填写预期数字；不要删除失败样本以美化汇总。

---

## 8. 简历与报告表述

可以陈述有证据的工程事实，例如：

- 实现或暴露了 deterministic lexical context diagnostic；
- 明确版本化为 `token_overlap_v1` 并按样本宏平均；
- 建立了性能实验记录模板和 response-level 评估边界。

如需报告数值，必须带数据集版本、样本数、环境、指标完整名称和限制。不要使用“专家共识吻合度”“覆盖生成安全性”“CoT 提升严谨性”或其他未经独立验证的结论。

---

## 9. 常见问题

### Q1：两个 lexical 字段变高能否说明回答更好？

不能。`response` 未参与计算，字段只描述 ground truth 与 retrieved contexts 的词项重叠。

### Q2：为什么 URL 里仍然有 `ragas`？

这是为旧调用方保留的 legacy compatibility URL，不表示安装或运行了 Ragas。

### Q3：能否把 precision 和 recall 加权成一个综合分？

可以为特定研究另行定义探索性统计量，但当前实现没有将其定义为质量分；不得把自定义 composite 称为答案质量或临床分，也不得用于临床效果结论。

### Q4：如何验证生成回答？

需要独立的 response-level 协议，例如版本化人工 rubric 或经单独验证的评估器，并明确其偏差与适用范围；不能复用当前 lexical endpoint 代替。
