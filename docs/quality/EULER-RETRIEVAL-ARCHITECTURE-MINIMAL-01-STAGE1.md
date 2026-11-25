# EULER-RETRIEVAL-ARCHITECTURE-MINIMAL-01 — 阶段一：BM25-only 分段候选覆盖

- 执行：DSH
- 日期：2026-11-25
- 阶段：**只测检索，不调用 LLM，不使用 Embedding**
- 数据：45 渲染 Holdout + 45 真实手机照片 + 1166 QCore corpus
- 状态：**阶段一 PASS（候选召回）；阶段二待 LLM Judge 确认**

> **2026-11-25 修正：** 本文的 `target-segment` 100% 使用“三字组重叠最大”的启发式选段，不是 oracle 分段；RP05/RP39/RP40 已证明它会选错题组段（例如 RP39 选中 Q8 而非 Q6–8）。**该 target-segment 指标不得作为分段正确性的证据。** `photo-any-segment` 100% 仍成立。详见 `docs/quality/EULER-RETRIEVAL-INTENT-DISAMBIGUATION-01.md`。

---

## 1. 目的

在引入任何 LLM Judge 之前，先回答：

> 只靠 BM25，能否把正确题送进候选？

同时必须先把整页照片切成题目段，否则测到的是“整页混题”，不是检索能力。

---

## 2. 方法

- 渲染 Holdout：单题文本，直接 BM25；
- 真实照片：用 V1.1 `split_questions()` 按题号切段，再对每段 BM25；
- 两种口径：
  1. **photo-any-segment**：目标题进入任意段的 top-k；
  2. **target-segment**：用与目标题干的三字组重叠选出目标段（诊断用 oracle 分段），再看目标段 top-k；
- 统计 Recall@5/10/20；不调阈值，不调用 LLM，不使用 embedding。

---

## 3. 结果

| 数据集 | 平均段数 | photo-any-segment @5/@10/@20 | target-segment @5/@10/@20 |
|---|---:|---:|---:|
| 渲染 45 | 1.02 | **100% / 100% / 100%** | **100% / 100% / 100%** |
| 真实 45 | 3.13 | **100% / 100% / 100%** | **100% / 100% / 100%** |

目标题排名分布：

| 数据集 | target 段 rank=1 | rank=2 | 缺失 |
|---|---:|---:|---:|
| 渲染 | 42/45 | 3/45 | 0 |
| 真实 | 43/45 | 2/45 | 0 |

真实照片分段数分布：1 段 7 张，2 段 16 张，3 段 10 张，4 段 3 张，5 段 5 张，6/7/15 段各 1–2 张。

---

## 4. 关键结论

1. **分段后 BM25 的候选召回不是当前瓶颈**：45+45 全部进入 top-5。
2. 之前“真实照片 BM25 @10 97.8%”是**整页 query** 的结果；分段后提升到 100%，说明多题分段比换模型更关键。
3. **在 1166 题、45+45 查询上，Embedding 对召回没有增量证据**。
4. 但这是 **candidate recall**，不是最终 Exact；LLM Judge 仍可能选错候选，必须进入阶段二。

---

## 5. 限制

- 只有 45 渲染 + 45 真机，不能外推到十万题长尾；
- target-segment 用 oracle 分段选择，实际系统的分段错误仍会造成失败；
- BM25 在 1166 题上强，不代表 10 万题上仍足够；
- 未测 LLM 判断、False Exact、Similar/Unknown；
- 未测用户选择成本。

---

## 6. 阶段二：LLM Judge

原计划用本地 `qwen3.5:9b`，但当前 Ollama 实际没有这个模型：

- `qwen3.5:0.8b`：873M，太小，不适合做 Judge；
- `qwythos-9b:latest`：9.2B / Q4_K_M，可作为本地候选；
- `qwen3.6-35b-128k`：35B，8GB GPU 不适合；
- 无 `qwen3.5:9b` tag。

阶段二需要确认：

1. 拉取真正的 `qwen3.5:9b`；
2. 或用现有 `qwythos-9b` 做本地 Judge；
3. 或用云端 API（需隐私/成本确认）。

阶段二设计（待确认后执行）：

- Oracle 候选：目标题 + 19 个干扰项，随机打乱；
- 统一候选字段、统一 prompt、同一模型、同一参数；
- LLM 只返回候选 question_id 或 Unknown；
- 统计 False Exact、Exact/Similar/Unknown、成本和延迟；
- 不用 LLM 生成新题、不用 confidence 直接认定身份。

---

## 7. 证据

| 内容 | 路径 |
|---|---|
| 阶段一脚本 | `_dsh/semantic_expansion_01/stage1_bm25_segmented.py` |
| 阶段一结果 | `runs/qcore_semantic_expansion_01/v11/bge_m3/stage1_bm25_segmented.json` |
| 分段实现 | `Teaching Script Compiler/tsc_compiler/semantic/v11/multi.py` |
| 真实照片标签 | `runs/qcore_semantic_expansion_01/v11/real_photos/real_photos_manifest.json` |
| 渲染 Holdout | `runs/qcore_semantic_expansion_01/v11/holdout/holdout_manifest_r2.json` |
