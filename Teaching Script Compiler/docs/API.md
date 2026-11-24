# Teaching Script Compiler — API（pre-prod）

服务只绑定 `127.0.0.1:8820`，为讲题链路与 DeepTutor 学生端提供只读派生数据。

## 认证（pre-prod 起强制）

| 调用方 | 凭证 | 说明 |
| --- | --- | --- |
| DeepTutor Next 代理（服务端） | `X-TSC-Token: $TSC_SERVICE_TOKEN` | 浏览器永远看不到该令牌 |
| Interactive Lesson iframe | `?access_token=<短期签名令牌>` | 只对单个 `question_id + revision_id` 有效，默认 15 分钟 |
| 任何人 | 无 | `/health` 公开；其余 `/api/*` 401/503 |

`TSC_SERVICE_TOKEN` / `TSC_SIGNING_SECRET` 只存在于 `.env.local`（gitignored）或部署环境变量。
服务端缺少 token 时 **503 fail-closed**，不会退化为匿名可读。

## GET /health

公开。返回快照信息与 `auth_required / service_token_configured / signing_configured`。

## GET /api/catalog?subject=数学

已发布题目目录（不含题干正文；服务端调试用）。

## POST /api/search/photo/jobs

`multipart/form-data`，字段 `file`（JPG/PNG/WebP/PDF，≤12MB）。需要 service token。

立即返回 `202 {job_id, status:"queued"}`，后台串行执行 OCR + 检索；不阻塞 HTTP 请求。

## GET /api/search/jobs/{job_id}

需要 service token。状态：`queued → running → succeeded | failed`。

成功时带 `result`（与下方同步搜索响应同构）与 `search_id`；OCR 失败时 `stage:"ocr"`、无 result。
单次 OCR 超时 `TSC_OCR_TIMEOUT`（默认 120s），最多 `TSC_OCR_ATTEMPTS`（默认 3）次。

## POST /api/search/photo（同步兼容，内部工具）

语义同上，直接等待 OCR；DeepTutor 页面不再使用。

## POST /api/search/text

JSON `{"text": "...", "use_llm": false}`；服务端回归/审计用。

## POST /api/lesson-access

需要 service token。Body `{question_id, revision_id?, ttl_seconds?}`。
返回 `{question_id, revision_id, expires_at, access_token}`；revision 不匹配 → 409。

## GET /api/teaching-bundles/{question_id}?revision_id=&language=zh-CN

- service token 可读；
- 或携带 `access_token` 且 `question_id / revision_id` 与令牌一致、未过期；
- 否则 401。**仅凭 URL 不能获取带答案的 Teaching Bundle。**

返回 Teaching Bundle；revision 不是当前 published → 409；脚本未过校验 → 422。

## 决策阈值（fail-closed，pre-prod 收紧）

| 决策 | 条件 | 可否自动进入讲题 |
| --- | --- | --- |
| `high_confidence` | top ≥ 0.68、margin ≥ 0.08、证据 ≥ 3、LLM verdict=`match`（启用时） | 是 |
| `ambiguous` | top ≥ 0.45 但未达高置信 | 否，必须用户确认 |
| `low_confidence` | 0.12 ≤ top < 0.45 | 否（学生端禁用） |
| `no_match` | 无候选 ≥ 0.12 | 否 |

真实手机手写/噪声样本的 top 分常落在 0.30–0.40；把 ambiguous 下限从 0.30 提高到 0.45 后，
这些样本稳定进入 `low_confidence`，而正式 20 题的 ambiguous 样本（0.59–0.66）不受影响。

## 版本与缓存

缓存键：`question_id|revision_id|language|script_schema_version|prompt_version|model|renderer_version`；
磁盘路径逐段重复该键；缓存命中仍会重新跑校验。新 revision 产生新目录，旧脚本绝不覆盖。

## 安全边界

- 只读：快照与守卫均以 `default_transaction_read_only=on` 连接；不写 QCore。
- 检索响应不含答案/解析；Teaching Bundle 含答案，仅服务端签发、短期、按题绑定。
- 上传文件只存本地 `data/photo/uploads`，job 记录在 `data/photo/jobs`，均 gitignored。
