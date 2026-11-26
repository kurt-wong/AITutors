# EULER-QUESTION-SEGMENT-RECOVERY-01 — MIMO Review Request

- 日期：2026-11-26
- 提交方：DSH
- 请复核：实现是否足以关闭本题；已知限制是否必须阻断
- 状态：**IMPLEMENTATION_COMPLETE_WITH_KNOWN_SOURCE_LIMITS / MIMO_PENDING**

---

## 1. 目标回顾

修复四个 False Exact（RP05/RP39/RP40/RP43）暴露的链路问题：

```text
照片 → OCR raw → 题目结构 → 目标选择 → Query → BM25 → Judge → QCore 确认
```

原则：

- QCore 是唯一题目/修订/答案/解析来源；
- 只要照片可见内容能定位 QCore 题，QCore 补全材料和小问；不要求用户补材料；
- 结构/目标不确定时，不自动 Exact；
- 不写生产 QCore，不切默认模型。

## 2. 实现清单

| 项 | 文件 | 状态 |
|---|---|---|
| 结构安全内核 | `Teaching Script Compiler/tsc_compiler/semantic/question_structure.py` | 完成 |
| 结构回归 | `Teaching Script Compiler/tests/test_question_structure.py` | 11 passed |
| OCR raw 保留 | `Teaching Script Compiler/tsc_compiler/photo/ocr_client.py` | 完成 |
| Compiler structure/共享材料 | `Teaching Script Compiler/tsc_compiler/api.py` | 完成 |
| DeepTutor 目标选择 | `DeepTutor/web/components/qcore/QCoreTeachPage.tsx` | 完成 |
| 文本检索代理 | `DeepTutor/web/app/api/qcore-teach/search-text/route.ts` | 完成 |
| 浏览器 E2E | `DeepTutor/web/tests/e2e/qcore-teach-target.audit.ts` | 2 passed |
| Assisted gold 复核 | `runs/qcore_semantic_expansion_01/v11/structure_recovery/` | 完成 |
| 生产 guard | `_dsh/semantic_expansion_01/segment_recovery_guard.json` | 与冻结基线全等 |

## 3. 验证结果

| 项 | 结果 |
|---|---|
| Compiler full pytest | 64 passed |
| 结构专项 | 11 passed |
| DeepTutor unit | 5 passed |
| DeepTutor `tsc --noEmit` | pass |
| DeepTutor `npm run build` | pass |
| Browser E2E | 2 passed（多题目标选择 + 单题跳过） |
| 真实 API smoke | structure=ambiguous, units 5-8 |
| OCR v2 | 24/24 ok，raw 全保存 |
| 生产 QCore | 175/193/169，与基线全等 |

E2E 命令：

```powershell
cd DeepTutor/web
$env:WEB_BASE_URL="http://127.0.0.1:3100"
npx playwright test tests/e2e/qcore-teach-target.audit.ts --project=ui-audit --workers=1
```

## 4. 四回归结果

| 样本 | 目标 | 结果 |
|---|---|---|
| RP05 | Q16–19 | 可见 Q16–19 内容进入 Query；材料缺失不要求补拍 |
| RP39 | Q6–8 | 长江经济带材料 + Q6/Q7/Q8；无 Q5 |
| RP40 | Q21–22 | 太阳能光热电站材料 + Q21/Q22；无页码 |
| RP43 | Q33 | Q33；无 Q32(4) 尾部 |

四条均为 `ambiguous`，不会自动 Exact。

## 5. Assisted gold 复核

- 24/24 有 verdict；
- 9 条人工 pass；
- 12 条人工 issue 后按 note 确定性裁剪（页面标题/上题尾部/页码/下一段材料）；
- 3 条 OCR 源限制：
  - RP04 原文下划线未被 OCR 保留；
  - RP05 Q16/Q17 题号未识别；
  - RP13 21/22/23 空题号不稳定。

这 3 条不是 Query 拼接错误，未伪造 OCR 内容。

产物：

```text
assisted_gold_final_24.json
review_summary.json
reviewed/*.json
```

## 6. 测试边界（更正）

**不重复测试 OCR 识别质量。** Preprocessing 管线已经多次调用 OCR API，并产出封存 OCR/Manifest；本任务不重跑 OCR 质量评测。

本任务的浏览器 E2E 测的是 **DeepTutor 拍照链路**，不是 OCR 模型：

```text
浏览器上传
  → /api/qcore-teach/search 同源代理
  → Compiler job（202）
  → /api/qcore-teach/jobs/{id} 轮询
  → search result 的 structure
  → 多题目标选择
  → /api/qcore-teach/search-text
  → 候选
```

因此：

- E2E 固定 OCR job 结果，只验证代理/轮询/结构/目标选择/Query；
- 不把 OCR 队列可用性作为本任务验收门槛；
- 真实 API smoke 已确认 Photo search 返回 `structure=ambiguous, units 5-8`；
- 3 条 OCR 源限制属于源保真，不在本任务 Query/结构逻辑内修复。

## 7. 已知限制（请 MIMO 判定是否阻断）

1. **OCR 质量不重复测试**：Preprocessing 已覆盖；本任务 E2E 固定 OCR 边界，不等待远端 OCR 队列。
2. **3 条 OCR 源限制**：RP04/RP05/RP13 需要 OCR/PDF 层面处理，不应在 Query 里伪造。
3. **12 条 auto-cleaned 没有第二次人工逐条复核**：来自人工 note 的确定性裁剪。
4. **assisted gold 不是独立人工从零标注**：人工只做 verdict，未逐条重建 segments。

## 7. 请 MIMO 回答

1. 上述实现是否足以关闭“四 False Exact 的结构/目标选择根因”？
2. 真实 OCR 队列阻塞是否应作为外部环境限制，而不是本次实现失败？
3. 3 条 OCR 源限制是否可以以 `known_ocr_limit` 关闭，还是一律阻断？
4. Assisted gold + 人工 verdict 是否满足本轮回归标准，还是必须独立人工逐条金标？
5. 是否允许进入下一阶段，还是必须先补真实整图 E2E？

## 8. 提交物

- 根仓：`0d44fa1d7`、`4014ed433`（已推送 `origin/main`）
- DeepTutor：`3a3b84ec7`（已推送 `fork/aitutor/deeptutor-integration`）
- 报告：`docs/quality/EULER-QUESTION-SEGMENT-RECOVERY-01-ASSISTED-GOLD.md`
- 代码：上述结构/OCR/API/UI/E2E 文件
