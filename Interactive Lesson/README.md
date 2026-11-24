# Interactive Lesson（互动讲题播放器）

只读的 TeachingScript 播放器：从 Question Core 的 Teaching Bundle API 取一份已通过校验的讲题脚本，按步骤在网页上播放。它不生成脚本、不判分、不做 TTS、不读数据库。

- 技术栈：Vite + React 18 + TypeScript（strict）+ KaTeX
- 契约：[`docs/CONTRACT.md`](docs/CONTRACT.md)
- 脚本权威结构：`Teaching Script Compiler/schema/teaching_script.schema.json`

## 运行

```powershell
cd "D:\Project\AITutors\Interactive Lesson"
npm install
npm run dev -- --port 8821
```

打开（参数按实际题目替换）：

```text
http://127.0.0.1:8821/?question_id=<uuid>&revision_id=<uuid>&api=http://127.0.0.1:8820
```

生产构建与预览：

```powershell
npm run build      # tsc --noEmit && vite build，产物在 dist/
npm run preview -- --port 8821
```

测试：

```powershell
npm test
```

### URL 参数

| 参数 | 必填 | 说明 |
| --- | --- | --- |
| `question_id` | 是 | 题目 ID；缺省显示配置错误，不发起请求。 |
| `revision_id` | 建议 | 服务端校验是否为当前 published revision；不一致返回 409。 |
| `api` | 否 | API 根地址，默认 `http://127.0.0.1:8820`。 |
| `language` | 否 | 固定请求 `zh-CN`。 |
| `reducedMotion` | 否 | `1` / `true` / `yes` / `on` 时禁用动画效果。 |

## 架构

```text
src/
  App.tsx                  URL 解析、加载状态机、错误/校验拦截、响应式根节点
  api.ts                   fetch bundle、HTTP 错误 → 中文提示、响应结构校验
  types.ts                 TeachingBundle / TeachingScript 类型
  params.ts                URL 参数解析（纯函数）
  messaging.ts             iframe postMessage 协议与 follow-up 消息构造
  player/timeline.ts       纯播放时间线（可见性、效果窗口、自动进下一步、结束态）
  components/LessonPlayer.tsx  主时钟、控制、步骤导航、键盘、父窗口消息
  components/BoardView.tsx     board block 渲染（含图片占位与表格滚动）
  components/MathText.tsx      `$...$` / `$$...$$` 拆分 + KaTeX 渲染
  components/FollowUpBox.tsx   最小追问入口
  hooks/useReducedMotion.ts    系统减少动态效果偏好
  styles.css               响应式 / 可访问性 / 动画样式
tests/
  timeline.spec.ts         纯时间线单测（假时间、边界、结束态）
  api.spec.ts              URL 构造与 409/404/422/5xx/网络错误映射
  mathtext.spec.tsx        `$...$`/`$$...$$` 拆分与非法 LaTeX 容错
  player.spec.tsx          组件 + App 错误路径 + 键盘 + 消息 + 减少动态
  followup.spec.tsx        追问消息 payload 与父窗口回答
  fixtures/synthetic_bundle.ts  自编「分苹果」合成夹具（不含真题内容）
```

### 数据流

```text
URL ──parseLessonParams──▶ App ──fetchTeachingBundle──▶ TeachingBundle
                              │
                     validation.status !== "pass" ──▶ 拦截页（不挂载播放器）
                              │ pass
                              ▼
                        LessonPlayer
             ┌────────────────┴────────────────┐
      rAF tick → playerReducer(timeline)   BoardView(effects, elapsed)
```

### 播放语义

- **单一主时钟**：`performance.now()` + 每个播放器**一个** `requestAnimationFrame` 循环；`playerReducer` 只接收每帧 delta，所有时间计算是纯函数。
- 进入 step 从 0 计时；`elapsed >= step.duration_ms` 自动进入下一步。
- 最后一步结束后进入 `ended`，停在结束态，不自动循环。用户再按播放会从第 1 步重新开始（显式操作）。
- `show` effect 之前 block 用 `hidden` 隐藏；`highlight` / `focus` / `pulse` 在 `[at_ms, at_ms + duration_ms)` 内生效（无 `duration_ms` 则持续到 step 结束）。
- 上一步 / 下一步 / 步骤列表 / 重播都会把 step 内 `elapsed` 归零。
- `prefers-reduced-motion: reduce` 或 `?reducedMotion=1`：不渲染色块 pulse 动画，highlight/focus 保留静态强调；计时与显示/隐藏语义不变。

### iframe 消息

子 → 父（`window.parent.postMessage(message, "*")`）：

```json
{"source":"interactive-lesson","type":"ready","payload":{"question_id":"...","revision_id":"...","steps":5}}
{"source":"interactive-lesson","type":"step_change","payload":{"step_id":"s2","index":1,"total":5,"goal":"..."}}
{"source":"interactive-lesson","type":"completed","payload":{"question_id":"...","revision_id":"..."}}
{"source":"interactive-lesson","type":"followup_request","payload":{
  "question_id":"...","revision_id":"...","step_id":"s2","step_goal":"...",
  "speech":"...","source_refs":["exp:1"],"question":"学习者在输入框里写的问题"}}
```

父 → 子：

```json
{"source":"deeptutor","type":"play"}
{"source":"deeptutor","type":"pause"}
{"source":"deeptutor","type":"goto_step","payload":{"step_id":"s3"}}
{"source":"deeptutor","type":"followup_answer","payload":{"text":"..."}}
```

`ready` 在有效脚本首次渲染后发送一次；播放器初始为暂停状态，停在 `init_step`（缺省第 1 步），不会自动播放。

## 错误处理

| 情况 | 表现 |
| --- | --- |
| HTTP 409 | 显示「该 revision 不是当前发布版本」，不渲染播放器。 |
| `script.validation.status !== "pass"` | 显示「脚本未通过校验」+ 失败检查项名称，不渲染播放器。 |
| 网络错误 / 404 / 422 / 5xx / JSON 结构错误 | 中文错误说明 + 「重试加载」按钮。 |
| `question_id` 缺失 | 显示配置错误与 URL 示例。 |

## 响应式与可访问性

- 375px 宽度下无页面级横向溢出（`html/body` 约束 + 全部容器 `max-width:100%`）。
- 公式在自己的容器内横向滚动；表格放入 `.table-scroll` 横向滚动；图片 `max-width:100%` 等比缩放。
- 控制按钮最小 44×44px，步骤按钮 40px 高。
- 文本可选中（无 canvas）；图片始终有 `alt`；步骤变化由 `aria-live="polite"` 区域播报；图标按钮均有 `aria-label`。
- 根节点 `data-testid="lesson-root"`、`data-responsive="mobile-first"`、`data-reduced-motion="true|false"`；测试据此断言响应式样式标记存在（jsdom 不做布局，故没有伪造布局断言）。

## 刻意不做（out of scope）

- 不生成 / 改写教学脚本，不调用编译器或 LLM。
- 不读 Question Core 数据库，不引入第二个题目事实源。
- 不判分、不做 TTS / 音频、不做视频导出。
- 不在播放器内回答追问；只把问题转发给父窗口，等待 `followup_answer`。
- 不做多题队列、账号、埋点、持久化。

## 已知契约空白与取舍

1. `followup_request` 契约只列了步骤上下文，没有承载学习者输入文本的字段；本实现追加 `question`（父窗口用它作为学生问题），其余字段语义不变。
2. 真实 bundle 的 `text` 中除 `$...$` 外还会出现 `$$...$$`（display math）；`splitMathText` 两种都支持，且不把未闭合的 `$` 当公式。
3. `init_step` 未在 CONTRACT 正文中定义语义；本实现把它作为初始暂停步骤，找不到时回退第 1 步。
4. 结束态下按「播放」会显式从第 1 步重播（不是自动循环）；按「重播当前步」只重置当前步。
5. 图片 URL 存在但加载失败（如 404）时，`onError` 切换到「图片未解析」占位并显示 asset id，避免破图。
6. `final_answer` 属于可选展示；本实现仅在讲完（ended）后的结束横幅展示，避免提前泄露答案。
