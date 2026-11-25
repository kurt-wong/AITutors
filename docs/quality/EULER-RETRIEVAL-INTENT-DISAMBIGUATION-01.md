# EULER-RETRIEVAL-INTENT-DISAMBIGUATION-01

- 执行：DSH
- 日期：2026-11-25
- 范围：RP05 / RP39 / RP40 / RP43 四个 False Exact 逐样本取证
- Judge：`qwythos-9b:latest`（本地，9.2B Q4_K_M）
- **状态：主因已定位为 target-segment/分段错误；不是 Judge 能力不足；用户意图歧义是交互问题，不是这四个错误的唯一根因**

---

# 0. 结论

1. **四个 False Exact 都有 target-segment/分段错误**，不是“Judge 随机选相邻题”。
2. 用**完整目标题文本**作为 query、同一 Judge、同一候选集重跑：
   - 四个错误样本 **4/4 正确**；
   - 全部 90 条 **90/90 正确，False Exact=0，Unknown=0**。
3. 因此：
   - **没有观察到独立的 `JUDGE_DISCRIMINATION_FAILURE`**；
   - 原阶段二的 4 个错误，是“错误的题段/Query 送进 Judge”造成的；
   - Judge 在错误 Query 下生成了引用 prompt 外文本的 evidence，那是**输入错误诱发的假证据**，不是稳定能力缺陷。
4. **用户意图歧义仍然存在**：整页照片含多题时，即使分段完美，用户仍可能想选另一道；这需要交互解决，但不能把这四个错误简单归因于用户意图。

---

# 1. 四个样本的证据

## RP05 — IMG_8127（语文 Q16–19）

- 照片：`Interactive Lesson/tests/pic/V11/IMG_8127.jpeg`
- 目标：`ba64363b...`（Q16–19 题组）
- OCR 只切出：18、19、20 三段；**Q16/Q17 的题号未被 OCR 识别**，内容并入段前。
- Stage2 target-segment 实际选中：**Q18**，不是 Q16–19。
- Judge 选中：`C06` 名人故居 Q19/20；该候选文本**不在送给 Judge 的 Q18 段中**。
- 完整目标题 Query 重跑：**正确选中 C10**。

**分类：**
- 主：`SEGMENT_SPLIT`（Q16–19 题组被拆散，16/17 未成段）
- 次：`USER_INTENT_AMBIGUITY`（照片同时有 Q16–19 与 Q20）
- 不成立：`JUDGE_DISCRIMINATION_FAILURE`（完整 Query 4/4 中）

## RP39 — IMG_8161（地理 Q6–8 题组）

- 照片：`IMG_8161.jpeg`
- 目标：`975c888d...`（Q6–8 复合题）
- OCR 段：5、6、7、8；target-segment 选中 **Q8**，不是 Q6–8 题组。
- Judge 选中：`C18` Q3–5；Q3/Q4 不在照片 OCR，Q5 只在段 5，不在选中的 Q8 段。
- 完整目标题 Query 重跑：**正确选中 C02**。

**分类：**
- 主：`SEGMENT_SPLIT` + `GROUP_OWNERSHIP`（复合题/共享材料被拆成独立段）
- 次：`USER_INTENT_AMBIGUITY`（Q5–8 同页）
- 不成立：`JUDGE_DISCRIMINATION_FAILURE`（完整 Query 正确）

## RP40 — IMG_8162（地理 Q21–22）

- 照片：`IMG_8162.jpeg`
- 目标：`2db13d58...`（Q21–22 题组）
- OCR 段：19、20、21、22；target-segment 选中 **Q21**，不是 Q21–22。
- Judge 选中：`C20` Q19–20；Q19/Q20 在同一照片中可见，但不在选中的 Q21 段中。
- 完整目标题 Query 重跑：**正确选中 C03**。

**分类：**
- 主：`SEGMENT_SPLIT`（Q21–22 题组被拆开）
- 强次：`USER_INTENT_AMBIGUITY`（Q19–22 全部可见，用户可能想选 Q19/20）
- 不成立：`JUDGE_DISCRIMINATION_FAILURE`（完整 Query 正确）

## RP43 — IMG_8165（政治 Q33）

- 照片：`IMG_8165.jpeg`
- 目标：`093a30c3...`（Q33）
- OCR 段：仅 33；但段 33 的开头混入了 **Q32 的小问（4）** 文本。
- Judge 选中：`C18` Q32，依据正是混入的 Q32（4）文本。
- 完整目标题 Query 重跑：**正确选中 C05**。

**分类：**
- 主：`SEGMENT_MERGE`（上一题 Q32 的尾部小问被并入 Q33 段）
- 强次：`USER_INTENT_AMBIGUITY`（Q32(4) 与 Q33 同页可见）
- 不成立：`JUDGE_DISCRIMINATION_FAILURE`（完整 Query 正确）

---

# 2. 分类汇总

| 样本 | SEGMENT_MERGE | SEGMENT_SPLIT | GROUP_OWNERSHIP | USER_INTENT_AMBIGUITY | JUDGE_DISCRIMINATION_FAILURE |
|---|---:|---:|---:|---:|---:|
| RP05 | — | **主** | — | 次 | 未观察到 |
| RP39 | — | **主** | **主** | 次 | 未观察到 |
| RP40 | — | **主** | — | **强次** | 未观察到 |
| RP43 | **主** | — | — | **强次** | 未观察到 |

关键：

- **四个都有分段/题组边界错误**；
- **RP40/RP43 同时存在真实的用户意图歧义**；
- **没有独立 Judge 能力失败**：完整目标 Query 下 90/90 正确。

---

# 3. 为什么不是“Judge 选相邻题”

Stage2 的错误 Query 是一个不完整的题段；Judge 看到的候选却包含完整题。它选了一个在**完整照片**里存在、但不在**当前 Query 段**中的候选。

这会产生两种表象：

1. 在整页语境里看起来像“相邻题误选”；
2. 在 Judge Prompt 语境里其实是“候选文本不在 Query 中”。

用完整目标题 Query 重跑后，Judge 全部正确，说明：

> 不是 Judge 不能区分相邻题，而是 target-segment 没有把目标题完整、正确地送进 Judge。

---

# 4. 交互原则

## 4.1 单题

直接检索；候选 + 用户确认。

## 4.2 多题

不能自动 Top1。应：

1. 识别题目区域/题号；
2. 展示题段；
3. **用户点击目标题号/区域**；
4. 对选定段执行 BM25；
5. 展示候选；
6. 身份确认后才进入 QCore 讲题。

## 4.3 Judge 使用边界

- 只在用户已选定目标段后调用；
- 只允许从候选中选；
- 如果 Judge 选中的候选文本**不在当前 Query 段**，直接判为无效/Unknown；
- LLM confidence 不能作为身份凭证；
- 证据必须能在 Query/候选文本中定位。

## 4.4 何时要求用户选择

- 单题且高置信：可直接展示候选；
- 多题/题组/材料题边界不清：**必须让用户选择目标**；
- 不是“每次都让用户选”，而是“系统无法可靠确定唯一目标时让用户选”。

---

# 5. 回归与口径修正

## 5.1 阶段一 target-segment 指标作废

阶段一的 `target-segment recall 100%` 使用了“三字组重叠最大”的启发式选段，**不是 oracle 分段**。

四个样本证明该启发式会选错：

- RP05 选中 Q18，而非 Q16–19；
- RP39 选中 Q8，而非 Q6–8；
- RP40 选中 Q21，而非 Q21–22。

因此：

- `photo-any-segment recall 100%` 仍成立（目标在某个段内）；
- **`target-segment 100%` 不能作为“分段正确”的证据**；
- 不得再把它当作 segmentation 的验收指标。

## 5.2 阶段二 Oracle 指标修正

- Stage2 的 88.9% 是“错误 target-segment 下的 Judge 表现”；
- 真正 Oracle Query Judge：**90/90 正确，0 False Exact**；
- Stage2 应保留为“坏 Query 回归”，不与 Judge 能力上限混报。

## 5.3 四个回归样本

RP05、RP39、RP40、RP43 进入专项回归：

- 输入：原照片/OCR；
- 断言：不得把非目标题当 Exact；
- 断言：target-segment 必须覆盖完整目标题组；
- 断言：Judge 选中的候选文本必须在 Query 段中；
- 断言：多题照片必须要求用户选择目标。

---

# 6. 最终判断

- **Embedding 不是当前瓶颈**：BM25 分段候选覆盖已足够，且完整 Query 下 Judge 90/90。
- **当前真正的问题是“如何把用户目标题正确地切成 Query”**，不是“如何让 Judge 更聪明”。
- **用户意图歧义**是产品交互问题，必须通过题目区域/题号选择解决；不能靠 LLM 或 Embedding 猜。
- **不启动 A/B/C Embedding 对比**；先修题段与交互。
- **不修改 QCore 正式题目，不切换生产默认模型。**

---

# 7. 证据

| 内容 | 路径 |
|---|---|
| 四例完整 Query 重跑 | `runs/qcore_semantic_expansion_01/v11/bge_m3/intent_four_full_query.json` |
| 90 条完整 Query Oracle | `runs/qcore_semantic_expansion_01/v11/bge_m3/stage2_true_oracle_query.json` |
| Stage2 原始错误 | `runs/qcore_semantic_expansion_01/v11/bge_m3/stage2_oracle_judge.json` |
| 阶段一结果 | `runs/qcore_semantic_expansion_01/v11/bge_m3/stage1_bm25_segmented.json` |
| 四张原图 | `Interactive Lesson/tests/pic/V11/IMG_8127.jpeg`、`IMG_8161.jpeg`、`IMG_8162.jpeg`、`IMG_8165.jpeg` |
