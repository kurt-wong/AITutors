# Interactive Lesson — 接口契约（pilot 1.0）

本应用只做一件事：**播放 TeachingScript**。它是只读渲染层，不读数据库、不改题目、
不生成教学内容。

## 1. 启动形态

```powershell
cd "D:\Project\AITutors\Interactive Lesson"
npm install
npm run dev -- --port 8821        # 开发/验收
npm run build                     # 产物在 dist/（可静态托管）
```

访问：`http://127.0.0.1:8821/?question_id=<uuid>&revision_id=<uuid>&api=http://127.0.0.1:8820&access_token=<短期令牌>`

- `question_id` 必填；`revision_id` 建议携带，服务端会校验它是当前 published revision，
  不一致返回 409（旧 revision 的脚本仍可追溯，但不作为当前讲题播放）。
- `access_token` 由 Teaching Bundle 服务端的 `/api/lesson-access` 签发，只对单题 + 单 revision
  有效、默认 15 分钟；缺失/过期/跨题都会 401，播放器不挂载。
- `api` 缺省 `http://127.0.0.1:8820`。

## 2. 数据来源

`GET {api}/api/teaching-bundles/{question_id}?revision_id=...&language=zh-CN`

响应（Teaching Bundle，节选）：

```json
{
  "question_id": "...",
  "revision_id": "...",
  "revision_number": 1,
  "language": "zh-CN",
  "script": { ...TeachingScript... },
  "question": {"subject": "数学", "source_document_id": "...", "printed_number": "1",
               "question_type": "single_choice", "title": "...", "content_hash": "..."},
  "init_step": "s1",
  "from_cache": true
}
```

TeachingScript 的权威结构见
`Teaching Script Compiler/schema/teaching_script.schema.json`。播放器只依赖：

- `script.steps[]`：`step_id / goal / source_refs / board[] / speech / subtitle / duration_ms / effects[]`
- `script.final_answer`（用于结论徽标，可选展示）
- `script.title / printed_number / question_type`（头部信息）
- `script.validation.status` 必须为 `pass`，否则显示“脚本未通过校验”，不进入播放。

Board block 类型：`heading | text | math | image | table | callout | choice | blank`。

- `text` / `callout` / `choice` / `heading` 的文本里允许内联 `$...$` 数学，必须用 KaTeX 渲染。
- `math` 用 `latex`。
- `image` 用 `url`（可能为 null，null 时显示 alt + “图片未解析”）、`alt` 必填。
- `table` 用 `rows: string[][]`，单元格里允许 `$...$`。

## 3. 播放语义

- **单一主时钟**：`performance.now()` + `requestAnimationFrame`，不得为每个 block 建计时器。
- 每个 step 有 `duration_ms`；进入 step 从 0 开始计时。
- `effects[]` 相对该 step 起点：`show` 之前该 block 不可见；`highlight/focus/pulse` 是视觉强调。
- 控制：播放 / 暂停 / 上一步 / 下一步 / 重播当前步 / 进度（当前步内时间 + 总步数）。
- 当前 step 结束后自动进入下一步；最后一步结束停在结束态（不自动循环）。
- 键盘：`Space` 播放/暂停，`←/→` 上/下一步，`Home` 回到第一步，`End` 到最后一步，
  `R` 重播当前步。焦点在按钮上时不要拦截这些键。
- `prefers-reduced-motion: reduce` 或 `?reducedMotion=1`：禁用 highlight/pulse 的动画，
  只保留显示/隐藏与静态强调；时钟照常推进。

## 4. 响应式 / 可访问性

- 375px 宽度下：不横向溢出；公式可读（允许公式自身横向滚动）；图片等比缩放；
  表格可横向滚动；控制条按钮 ≥ 40px 触控高度且可操作。
- 文本必须可选择、非 canvas；图片有 alt；步骤变化通过 `aria-live="polite"` 播报；
  控件有可读的 `aria-label`。

## 5. 与 DeepTutor 的消息协议（iframe）

子窗口 → 父窗口（`window.parent.postMessage`，`targetOrigin: "*"`）：

```json
{"source":"interactive-lesson","type":"ready","payload":{"question_id":"...","revision_id":"...","steps":5}}
{"source":"interactive-lesson","type":"step_change","payload":{"step_id":"s2","index":1,"total":5,"goal":"..."}}
{"source":"interactive-lesson","type":"completed","payload":{"question_id":"...","revision_id":"..."}}
{"source":"interactive-lesson","type":"followup_request","payload":{
  "question_id":"...","revision_id":"...","step_id":"s2","step_goal":"...",
  "speech":"...","source_refs":["exp:1"],"question":"学生在播放器里输入的问题"}}
```

父窗口 → 子窗口：

```json
{"source":"deeptutor","type":"play"}
{"source":"deeptutor","type":"pause"}
{"source":"deeptutor","type":"goto_step","payload":{"step_id":"s3"}}
```

播放器在自身内显示一个“追问”输入框（最小入口）：提交时只发 `followup_request`
（含当前 step 上下文），不自己回答；父窗口若回传
`{"source":"deeptutor","type":"followup_answer","payload":{"text":"..."}}` 则展示答案。

## 6. 明确不做

- 不生成/改写教学脚本；不读 QCore 数据库；不判分；不做 TTS；不做视频导出；
  不引入第二个题目事实源。
