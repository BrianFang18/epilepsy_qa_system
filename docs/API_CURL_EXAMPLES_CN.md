# 完全中文 API 调用示例（可直接复制）

> 适用环境：Windows PowerShell
> 建议使用 `curl.exe`（不要只写 `curl`），避免命令被 PowerShell 别名拦截。
> 默认服务地址：`http://127.0.0.1:8010`

---

## 0. 先确认服务已启动

```powershell
python run_server.py
```

---

## 1. 根接口（查看服务信息）

```powershell
curl.exe -X GET "http://127.0.0.1:8010/"
```

---

## 2. 健康检查接口

```powershell
curl.exe -X GET "http://127.0.0.1:8010/health"
```

---

## 3. 问答接口 `/v1/ask`

```powershell
curl.exe -X POST "http://127.0.0.1:8010/v1/ask" -H "Content-Type: application/json" -d '{"question":"我最近夜间癫痫发作增多，下一步怎么处理？","user_id":"demo_user_001","conversation_id":"conv_001","top_k":6,"with_trace":true}'
```

---

## 4. 文本入库接口 `/v1/ingest/text`

```powershell
curl.exe -X POST "http://127.0.0.1:8010/v1/ingest/text" -H "Content-Type: application/json" -d '{"doc_id":"zh_guideline_001","title":"癫痫门诊管理建议（示例）","text":"成人癫痫管理应结合发作类型、脑电图与影像学结果进行分层。一线药物选择需根据综合征类型和不良反应谱个体化调整。若出现持续抽搐超过5分钟，应立即急诊处理。","doc_type":"literature","source":"manual","metadata":{"year":2024,"lang":"zh","department":"neurology"}}'
```

---

## 5. 文件入库接口 `/v1/ingest/file`

> 说明：请把 `file_path` 改成你本机真实存在的文件路径。
> Windows 路径要写成双反斜杠（`\\`）。

```powershell
curl.exe -X POST "http://127.0.0.1:8010/v1/ingest/file" -H "Content-Type: application/json" -d '{"file_path":"F:\\\\fz\\\\找工作\\\\project\\\\epilepsy_qa_system\\\\sample_docs\\\\癫痫指南.pdf","doc_id":"pdf_guideline_001","title":"癫痫诊疗指南PDF","doc_type":"literature","source":"local_pdf","metadata":{"uploader":"demo_user","year":2025}}'
```

---

## 6. Legacy lexical 兼容接口 `/v1/eval/ragas`（不是 Ragas）

> `POST /v1/eval/ragas` 只是为旧调用方保留的 legacy compatibility URL。当前项目未安装、也不运行 Ragas；实际评估元数据为 `backend=deterministic_lexical`、`metric_version=token_overlap_v1`、`aggregation=macro_average`。
>
> 每个样本只比较 `ground_truth` 与 `retrieved_contexts`：兼容字段 `context_precision` 是 context-hit ratio，`context_recall` 是 ground-truth token coverage；服务再对样本做宏平均。请求中的 `response` 即使保留也不参与计算。字段名仅为兼容用途，不代表 Ragas、faithfulness、答案事实正确性、临床安全或临床效果。

```powershell
curl.exe -X POST "http://127.0.0.1:8010/v1/eval/ragas" -H "Content-Type: application/json" -d '{"samples":[{"question":"癫痫患者夜间发作增多是否需要调整用药？","ground_truth":"应结合发作频率、依从性和专科评估决定是否调药，持续抽搐需急诊。","retrieved_contexts":["患者近两月每周夜间发作1-2次，建议记录发作日记。","持续抽搐超过5分钟应立即急诊。"],"response":"该兼容字段会被忽略，不参与 lexical 计算。"}]}'
```

解读返回值时必须同时记录上述 backend、metric version 和 aggregation；不要把两个兼容字段改称为“RAGAS 指标”或回答质量分。

---

## 7. LLM 裁判评估接口 `/v1/eval/judge`

```powershell
curl.exe -X POST "http://127.0.0.1:8010/v1/eval/judge" -H "Content-Type: application/json" -d '{"question":"癫痫患者夜间发作增多，是否应加药？","answer":"建议先核对服药依从性、睡眠与诱因，再由神经内科专科医生评估是否调整剂量。如出现持续抽搐超过5分钟，应立即急诊。","references":["门诊随访记录提示发作频率增加与依从性下降相关。","持续抽搐超过5分钟属于急诊指征。"]}'
```

---

## 8. 常见补充：把返回结果保存到文件

```powershell
curl.exe -X POST "http://127.0.0.1:8010/v1/ask" -H "Content-Type: application/json" -d '{"question":"癫痫患者如何进行日常随访？","with_trace":true}' -o ask_result.json
```

---

## 9. 快速排错

1. 如果提示连接失败：先确认 `python run_server.py` 正在运行。
2. 如果返回 422：通常是 JSON 字段名或格式不对，按本示例字段检查。
3. 如果 `/v1/ingest/file` 失败：优先检查 `file_path` 是否真实存在。
4. 如果回答像模板：检查 `.env` 的 `MOCK_MODE` 是否仍为 `true`。
