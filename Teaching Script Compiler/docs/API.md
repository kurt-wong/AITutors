# Teaching Script Compiler — API（pilot）

服务只绑定 `127.0.0.1:8820`，为讲题链路与 DeepTutor 学生端提供只读派生数据。

## GET /health

返回 QCore 快照信息（构建时间、数据库名、只读事务证明、已发布题数、脚本缓存数）。

## GET /api/catalog?subject=数学

已发布题目目录（不含题干正文；用于调试与人工检查）。

## POST /api/search/photo

`multipart/form-data`，字段 `file`（JPG/PNG/WebP/PDF，≤12MB）。

处理顺序：

1. 图片包成单页 PDF → PaddleOCR-VL 识别；
2. OCR 文本 → 候选检索（词法 + 字符 n-gram + 结构 + 可选 LLM 判定）；
3. 输出候选与决策，不返回答案/解析。

响应（节选）：

```json
{
  "search_id": "…",
  "decision": "high_confidence|ambiguous|low_confidence|no_match|ocr_failed",
  "requires_confirmation": false,
  "may_teach": true,
  "message": "已找到高置信题目，可直接进入讲题。",
  "decision_reason": "top score 0.785, margin 0.436, evidence 6",
  "candidates": [
    {
      "question_id": "…", "revision_id": "…",
      "score": 0.785,
      "score_parts": {"lexical":0.73,"semantic":0.72,"structure":0.67,"llm":1.0},
      "match_evidence": [{"type":"number","value":"1"}],
      "source_document_id": "…", "printed_number": "1", "question_type": "single_choice",
      "title": "…", "needs_confirmation": false,
      "llm": {"match": 1.0, "verdict": "match"}
    }
  ],
  "ocr": {"status":"ok","engine":"PaddleOCR-VL-1.6","pages":1,"duration_s":4.4,"text":"…"},
  "llm": {"enabled": true, "status": "ok", "error": null}
}
```

OCR 失败 → `503` + `decision="ocr_failed"`，**不进入匹配**。

## POST /api/search/text

JSON `{"text": "...", "use_llm": false}`；同一匹配/决策逻辑，用于离线回归与审计。

## GET /api/teaching-bundles/{question_id}?revision_id=&language=zh-CN&init_step=s1

返回 Teaching Bundle：`{question_id, revision_id, revision_number, language, init_step, question, script, assets}`。

- `revision_id` 必须等于当前 published revision，否则 `409`（旧 revision 的脚本仍在缓存中可追溯，但不作为当前讲题播放）。
- 脚本未通过校验 → `422 {code, message}`。
- 题目未发布/不存在 → `404`。

## 决策阈值（fail-closed）

| 决策 | 条件 | 可否自动进入讲题 |
| --- | --- | --- |
| `high_confidence` | top ≥ 0.68、margin ≥ 0.08、证据 ≥ 3 项、LLM verdict=`match`（启用时） | 是 |
| `ambiguous` | top ≥ 0.30 但未达高置信 | 否，必须用户确认 |
| `low_confidence` | 0.12 ≤ top < 0.30 | 否（学生端禁用“进入讲题”） |
| `no_match` | 无候选 ≥ 0.12 | 否 |

LLM 关闭时高置信需要更强的文本分数与 margin；LLM 调用失败时上限为 `ambiguous`。

## 版本与缓存

缓存键：`question_id|revision_id|language|script_schema_version|prompt_version|model|renderer_version`，
磁盘路径逐段重复该键。新 revision 产生新目录，旧脚本绝不覆盖。

## 安全边界

- 只读：快照与守卫均以 `default_transaction_read_only=on` 连接。
- 检索响应不含答案/解析；Teaching Bundle 含答案，因为讲题本身要讲答案，且服务只在 loopback。
- 不写 QCore，不触发发布/审核状态变更。
