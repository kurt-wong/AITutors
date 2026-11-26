# EULER-QUESTION-SEGMENT-RECOVERY-01 — 执行报告

- 日期：2026-11-26
- 执行：DSH
- 状态：**DSH_PARTIAL / MIMO_NOT_READY**
- 原因：结构内核、OCR raw、题组共享材料、目标选择 UI、20 例结构状态金标已落地；但浏览器 E2E、逐题完整人工边界金标和表级快照报告尚未完成，不能按任务书宣称 DSH_COMPLETE。

---

## 1. 已完成

### 1.1 四例根因复核

四个 False Exact 的责任层已确认：

| 样本 | 主要缺陷 | 责任层 |
|---|---|---|
| RP05 | Q16–19 题组被拆散；OCR 未保留 16/17 题号 | OCR/分段 |
| RP39 | Q6–8 复合题拆散；共享材料归属 | 题组结构 |
| RP40 | Q21–22 拆散 | 分段 |
| RP43 | Q32 小问尾部混入 Q33 | OCR/相邻边界 |

完整 Query 重跑 90/90、0 False Exact；主因不是 Judge。

### 1.2 OCR raw 保留与重跑

- `ocr_client.py` 新增 `include_raw`：保留原始 JSONL（含 `layoutParsingResults`、`parsed_res_list`、`block_bbox`、`block_order`），并记录 `raw_sha256`。
- 独立目录：`runs/qcore_semantic_expansion_01/v11/structure_recovery/ocr_v2/`。
- 重跑 24 张：4 个回归样本 + 20 个额外真实照片。
- 24/24 OCR status=ok；原始 JSONL 全部保存。
- 新旧文本对比：7/24 文本发生变化；四个回归样本文本未变。
- manifest：`ocr_v2_manifest.json`，记录输入 SHA、raw SHA、text SHA、模型、耗时、旧/新差异。

### 1.3 结构恢复安全内核

新增 `tsc_compiler/semantic/question_structure.py`：

- 题号分段；
- 前缀/共享材料识别；
- 题号缺失 → `incomplete`；
- 多题 → `ambiguous` + `requires_selection`；
- 上一题小问尾部 → 标记 `QUESTION_TAIL_CONTAMINATION`，默认排除出 Query；
- 无法可靠恢复时不自动 Exact。

四例回归测试 `tests/test_question_structure.py`：**10 passed**。

### 1.4 Compiler API

- `/api/search/photo/jobs` 结果新增 `structure` 字段；
- `/api/search/text` 结果新增 `structure` 字段；
- 原有上传、OCR、searchPhoto、候选展示接口保留。

### 1.5 DeepTutor QCoreTeachPage

- 保留上传/OCR/searchPhoto/候选/讲题；
- 新增 `target_selection` 阶段：
  - OCR 多题/结构不确定时，展示题号题段；
  - 用户勾选目标题段后，调用 `/api/qcore-teach/search-text`；
  - Compiler 用选中的文本执行 BM25；
  - 不会自动把整页文本当成一道题；
  - 上一题尾部前缀默认排除。
- 新增代理路由 `web/app/api/qcore-teach/search-text/route.ts`。
- `tests/qcore-teach.spec.tsx`：**5 passed**，包含“多题必须选择目标”测试。
- `tsc --noEmit` 通过。

### 1.6 20 个额外真实样本的结构审计

- 20 张额外照片全部重跑 raw OCR；
- 用原始 OCR block 中的题号与结构内核 units 对比：**20/20 题号序列一致**；
- 人工 contact-sheet/OCR 状态核对：18 ambiguous、1 reliable（IMG_8136）、1 ambiguous（IMG_8133，上一题尾部）；
- 状态金标与内核：**20/20 一致**；
- 证据：`structure_audit_20.json`、`structure_gold_20.json`。

注意：这是 **状态级人工审计**；逐题完整边界/共享材料人工金标仍未完成。

---

## 2. 未完成 / 不能宣称完成

### 2.1 题组共享材料已实现（本轮补齐）

- raw OCR 的独立 material block 会挂到后续 Q6/Q7/Q8 或 Q21/Q22；
- UI 选择题组后，Query 自动包含共享材料；
- RP39 的“长江经济带…”和 RP40 的“太阳能光热电站…”已验证进入 Query；
- RP43 的 Q32(4) 尾部不再被当作 Q33 的 context。

### 2.2 20 个额外样本没有逐题完整人工边界金标

已有 20 例状态级人工审计（status 20/20），但没有逐张人工核定所有题段边界、共享材料归属和 Query 文本。任务书要求的完整人工结构金标未完成。

### 2.3 浏览器 E2E 未执行

DeepTutor QCoreTeachPage 目前只有 Vitest 组件测试，没有启动完整 DeepTutor/Compiler/OCR 服务的 Playwright E2E。单题、多题、综合题、不确定结构四种浏览器场景未验证。

### 2.4 生产零变化

已运行现有 production guard：

- QCore 计数与 `guard_preprod.json` **完全相等**；
- 175 questions / 193 revisions / 169 published；
- 未写生产 QCore。

但任务书要求的“数据变更前后表级快照”没有单独再做一遍完整报告。

---

## 3. 测试与提交

| 项 | 结果 |
|---|---|
| Compiler full pytest | **64 passed** |
| 结构专项 | **11 passed** |
| DeepTutor qcore-teach | **5 passed** |
| DeepTutor `tsc --noEmit` / `npm run build` | 通过 |
| 生产 guard | 与冻结基线全等 |
| OCR v2 | 24/24 ok，raw 全部保存 |
| 20 例状态金标 | 20/20 一致 |

提交：

- AITutors 根仓：`80780c7de`、`a930ef996`、`975f99ad5`（已推送 `origin/main`）
- DeepTutor：`60e56673e`、`a23cc5648`（已推送 `fork/aitutor/deeptutor-integration`）

---

## 4. 结论

本轮已经把工作从“检索模型”推进到“题目结构 + 用户目标选择”，并完成了：

- 四例根因；
- OCR raw 保留与 24 张重跑；
- 结构安全内核与四例回归；
- 题组共享材料进入 Query（RP39/RP40）；
- DeepTutor 多题目标选择入口；
- 20 例状态级人工审计。

但**不能**按任务书标记 `DSH_COMPLETE`。剩余必须补齐：

1. 20 例的逐题完整边界/共享材料人工金标；
2. 浏览器 E2E（单题、多题、综合题、不确定结构）；
3. 表级快照报告（目前只有 production guard 计数全等）。

在补齐前，不应进入 MIMO 独立复核，也不应宣称生产可用。
