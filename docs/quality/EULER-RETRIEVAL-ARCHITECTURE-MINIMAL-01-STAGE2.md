# EULER-RETRIEVAL-ARCHITECTURE-MINIMAL-01 — 阶段二：Oracle LLM Judge

- 执行：DSH
- 日期：2026-11-25
- Judge：`qwythos-9b:latest`（本地 Ollama，9.2B / Q4_K_M；**不是 qwen3.5:9b——该 tag 当前不存在**）
- 数据：45 渲染 + 45 真机
- 候选：目标题 + 19 个 BM25 近邻干扰项，随机打乱；目标始终在候选内
- 状态：**Oracle 部分通过；真机仍有 4 个相邻题 False Exact；不进入生产**

> **2026-11-25 修正：** 本文的 Stage2 使用启发式 target-segment；四例 False Exact 的主因是 **target-segment/分段错误**，不是 Judge 能力不足。用完整目标题 Query、同一 Judge、同一候选重跑：四例 **4/4 正确**，全部 90 条 **90/90 正确、0 False Exact**。因此本文的“Judge 部分通过”应理解为“坏 Query 回归”，不是 Judge 上限。详见 `docs/quality/EULER-RETRIEVAL-INTENT-DISAMBIGUATION-01.md`。

---

## 1. 目的

阶段一已经证明目标题在 top-5 内，阶段二只测：

> 候选里明确包含正确题时，LLM 能否选出目标题，而不是选相邻题或拒绝。

这是 **Oracle Judge**，不是完整 BM25+LLM 链路；目标始终存在。

---

## 2. 方法

- 渲染：直接用单题文本；
- 真机：用阶段一的 target-segment（按题号切段 + 目标题干三字组匹配）作为 query；
- 候选 = 目标 + BM25 top19 干扰项，随机打乱为 C01–C20；
- 候选文本统一截断为 `stem + options` 的 280 字符；
- 同一 Prompt、同一模型、temperature=0、`format=json`、`num_ctx=12288`；
- 只允许返回候选 ID 或 `unknown`；
- 统计 Exact 正确、False Exact、Unknown、非法 ID、延迟。

---

## 3. 结果

| 数据集 | Exact 正确 | False Exact | Unknown | 非法 ID | 准确率 | 平均延迟 | P95 |
|---|---:|---:|---:|---:|---:|---:|---:|
| 渲染 45 | **43** | **0** | 2 | 0 | **95.6%** | 2.75s | 3.66s |
| 真机 45 | **40** | **4** | 1 | 0 | **88.9%** | 2.91s | 4.32s |
| 合计 90 | 83 | 4 | 3 | 0 | 92.2% | — | — |

无非法 ID，无模型编造候选。

---

## 4. 错误明细

### 4.1 渲染 Unknown（2）

- H2001（语文 Q11）：题组/多小问，Judge 选择未知；
- H2005（语文 Q16–19）：题组，Judge 选择未知。

属于 fail-closed，不是 False Exact。

### 4.2 真机 False Exact（4）

| 样本 | 目标 | Judge 选择 | 现象 |
|---|---|---|---|
| RP05 | 语文 Q16–19 | 名人故居 Q19/20 组 | 选中同页相邻题组 |
| RP39 | 地理 Q6 | 地理 Q3–5 题组 | 选中同页相邻题组 |
| RP40 | 地理 Q21–22 | 地理 Q19–20 | 选中同页相邻题 |
| RP43 | 政治 Q33 | 政治 Q32 | 选中同页相邻题 |

四个错误的共同点：

- **目标候选确实在候选集中**；
- Judge 选择的是**同一张照片里也可见的相邻题**；
- 不是选到照片外的题，也不是编造 ID；
- 根因是 **query 题段仍包含多道题/题组边界不清**，不是候选召回不足。

真机 1 个 Unknown：RP13（英语阅读），Judge 选择未知，属于保守拒绝。

---

## 5. 判断

### 5.1 Oracle Judge 可用，但真机题段还不够细

- 渲染单题：95.6% 正确、0 False Exact；
- 真机：88.9% 正确、4 False Exact；
- 4 个错误全部是“相邻题”而非“候选缺失”。

所以：

> **BM25 召回不是当前瓶颈；当前瓶颈是题段边界和用户目标选择。**

### 5.2 这还不能证明 BM25+LLM 的最终产品效果

- Oracle 强制包含目标；真实 BM25 不带 Oracle 时目标仍在 top5（阶段一），所以候选差异不大；
- 但真机错误说明：**即使目标在候选里，LLM 也可能选相邻题**；
- 要解决，必须：
  1. 更细的题段切分（单题/单小问）；
  2. 多候选 + 用户选择，不自动 Top1；
  3. 或在 Judge 中显式要求“相邻题不能算 Exact”。

### 5.3 当前不需要 Embedding

- 阶段一：分段 BM25 top5 覆盖 100%；
- 阶段二：候选不缺，错在题段边界/目标选择；
- Embedding 不能直接解决“同一页相邻题”的目标歧义；
- 因此本轮仍不引入 Embedding 作为必需组件。

---

## 6. 限制

- 只有 45 渲染 + 45 真机；
- 候选文本截断 280 字符，可能影响 Judge；
- Oracle 的 target-segment 用三字组匹配，真机题组边界仍可能错；
- 未测 Similar/Unknown 独立金标；
- 未测 BM25+LLM 的非 Oracle 完整链路；
- `qwythos-9b` 不代表云端 LLM 能力；`qwen3.5:9b` 当前不存在。

---

## 7. 建议下一步

不要直接做 A/B/C Embedding 对比；先做：

1. **题段边界修复**：尤其题组、多小问、材料题；
2. **多候选用户选择**：目标题由用户点选，不自动 Top1；
3. 在这些前提下再跑 **BM25+LLM 非 Oracle** 与 **BGE+BM25+LLM** 的最终对比。

如果题段边界不修复，A/B/C 的差异会被“选中相邻题”淹没，实验没有决策价值。

---

## 8. 证据

| 内容 | 路径 |
|---|---|
| 阶段二脚本 | `_dsh/semantic_expansion_01/stage2_oracle_judge.py` |
| 阶段二原始结果 | `runs/qcore_semantic_expansion_01/v11/bge_m3/stage2_oracle_judge.json` |
| 阶段一报告 | `docs/quality/EULER-RETRIEVAL-ARCHITECTURE-MINIMAL-01-STAGE1.md` |
| 阶段一结果 | `runs/qcore_semantic_expansion_01/v11/bge_m3/stage1_bm25_segmented.json` |
