# EULER-PREPROCESSING-PIPELINE-QUALITY-01

- 状态：**长期质量 / 缺陷收敛项目，不属于当前主线阻断项**
- 冻结日期：2026-11-25
- 来源：`EULER-QCORE-SEMANTIC-EXPANSION-01` Track A 的 75 份真实 PDF 压力测试
- 冻结基线：`KNOWN-QUALITY-GAPS-BASELINE-20261125`
- 机器可读样本：`docs/quality/known_quality_gaps_20261125.json`
- 当前主线：Semantic Retrieval V1（冻结）、Track C（设计采纳）、Euler PREPROD（已关闭）**均不因本 backlog 重开**

---

## 0. 项目性质

本项目不是“把 75 份修到 100%”的交付任务，而是把真实数据暴露出的**通用管线风险模式**沉淀为长期质量资产：

1. 分类；
2. 留证；
3. 形成回归样本；
4. 按真实数据逐步收敛；
5. 不在主线任务里临时放宽任何 Gate。

**锁定 ≠ 判定所有样本都是 Bug。** 其中一部分（G8 显式不确定、2 份真截断）是 Gate 正确工作的结果。

---

## 1. 冻结基线数字

| 阶段 | 数量 | 说明 |
|---|---:|---|
| PDF 完成 OCR | 75 | 全部有 `.md + .ocr_raw.jsonl` |
| Manifest 就绪 | 64 | 11 份被 G8/G9 阻断 |
| 产生 Question | **56** | 8 份零题 |
| Question 入隔离库 | **1,166** | 9 科 |
| Gate 阻断 | 11 | G8=6、G9=5；16 个 gate 文件中有 5 个后来重跑成功 |
| 零题文档 | 8 | **全部 `ocr_source_defect`，不是 Map Failed** |
| Essay NO_ANSWER | 33 | 已入 QCore，仅 TeachingScript 未生成 |
| BGE Exact（9 科 18 条） | 9/18 | Precision 1.00，0 false exact |

---

## 2. 四类已锁定问题

### A. G8：Manifest LLM 显式不确定（6 份）

**样本**：

| sample | 文档 | 单元 |
|---|---|---|
| T046 | 2024北京八十中高二（上）期中化学（教师版）(1) | U18 |
| T047 | 2024北京清华附中朝阳学校高三10月月考化学（教师版）(1) | U4 |
| T060 | 2022北京北师大附中高三（上）期中生物（教师版）(1) | U19 |
| T066 | 2024北京理工大附中高一6月月考地理（教师版） | U18 |
| T071 | 2023北京昌平高一（上）期末政治（教师版） | U25 |
| T072 | 2024北京西城高一（上）期末政治（教师版）(1) | U26 |

**统一原因**：`explicit_uncertainty（结构不确定声明，不伪装确定）`。  
**定性**：Manifest LLM 主动声明结构不确定，G8 正确 fail-closed，**不是代码 Bug**。  
**当前动作**：锁定；**不放宽 Gate**。  
**长期研究**：哪些版面特征触发 uncertainty；OCR/layout evidence 能否降低不确定率；哪些 uncertainty 可安全转成确定性规则；哪些必须永久 fail-closed。

### B. G9：Manifest 结构区间错误（5 份）

| sample | 文档 | 观测到的缺陷 |
|---|---|---|
| T006 | 2026北京十五中高二4月统练语文（教师版）(1) | 24 项行区间越界，如 `[1121,1129]` vs `n_lines=255`（LLM 生成不存在的行号） |
| T049 | 2024北京四中高三保温卷化学（教师版）(1) | `S3 [447,447]` 与 `S4 [447,449]` 交叉 |
| T057 | 2021北京平谷高三一模生物（教师版）(1) | 子小问 `[245,245]` 不在父问 `[223,244]` 内（parent/child containment 失败） |
| T062 | 2023北京大兴高一（下）期末历史（教师版）(1) | 小问 `[431..]` 落在单元 `[993,1019]` 之外（unit/subquestion 行号错配） |
| T063 | 2023北京房山高一（上）期末历史（教师版） | 15 项行区间越界，如 `[3336,3336]` vs `n_lines=652` |

**定性**：Manifest LLM 的结构区间错误被 G9 正确拦截；**不是 Preprocessing 确定性代码缺陷**。  
**当前动作**：锁定；保持 fail-closed。  
**长期方向**：行号存在性约束、parent/child containment、sibling non-overlap、OCR JSONL/bbox 第二证据。

### C. Strict Adapter OCR↔PDF 截断门（8 份零题）

**重要更正**：这 8 份不是 Map Failed，全部是 `ocr_source_defect`，失败在 `Question Core/strict_adapter/generic_executor.py` 的 `check_ocr_truncation`（`ocr_source_check`），在 mapping/admission 之前。

| 子类 | sample | 文档 | 差异 | 处置 |
|---|---|---|---|---|
| **真截断** | T004 | 2018北京一零一中学高二（下）期中语文（教师版）(1) | 缺 `"的区域"`（4 字） | **保持阻断**，重 OCR/核源 |
| **真截断** | T037 | 2018全国Ⅲ卷高考真题物理（教师版）(1) | 缺 `"m/s,则它在该介质中的波长为0.32m"`（20 字） | **保持阻断**，重 OCR/核源 |
| 格式误报 | T025 | 2023北京一六六中高二（上）期中英语（教师版）(1) | PDF 全小写无空格，OCR 正常大小写/空格 | 作为归一化回归样本 |
| 格式误报 | T041 | 2022北京大峪中学高一（上）期中化学（教师版） | 缺填空下划线 `____。` | 同上 |
| 格式误报 | T042 | 2023北京十一中高一（上）期中化学（教师版） | 缺 `________________________` | 同上 |
| 格式误报 | T044 | 2025北京五中高二（下）期中化学（教师版）(1) | 缺 `___________`（多处） | 同上 |
| 格式误报 | T050 | 2026北京高考真题化学（教师版）(1) | 缺填空下划线 | 同上 |
| 格式误报 | T054 | 2024北京丰台高二（下）期中生物（A卷）（教师版）(1) | 缺填空下划线 | 同上 |

**定性**：Gate 的“防止真截断”能力是有效的；问题在归一化不足，把空白下划线/大小写/空格当成内容缺失。  
**当前动作**：锁定；**不现场修**；真截断保持阻断。  
**长期方向**：比较前剥离空白下划线、纯排版字符、大小写/空格差异；只对 CJK/字母数字实质内容缺失报警；用这 8 个样本做回归，确保真截断检测不下降。

### D. Essay TeachingScript 缺少教学契约（33 题）

- 33/33 已入 QCore（**不是被拒绝的 Question**）；
- 33/33 `answers=[]`，没有 TypedAnswer；这是当前契约允许的（Owner D-1：作文范文放 Explanation）；
- 24/33 有非空 Explanation（中位数 592 字，5–17 blocks）；9/33 Explanation 也为空；
- Compiler 在 `compiler.py:542-544` 先检查 TypedAnswer，因此抛 `NO_ANSWER`，**未读取 Explanation**。

**定性**：QCore → TeachingScript 的题型覆盖缺口，不是 Question 数据异常，也不是 Preprocessing 质量问题。  
**当前动作**：锁定；**不改 QCore 数据契约、不制造 TypedAnswer**。  
**长期方向**：独立 `Essay → Explanation-based TeachingScript` 教学契约；范文是教学素材/参考答案内容，不是 TypedAnswer，也不是评分答案。

---

## 3. 已锁定但不属于“缺陷修复”的能力限制

### E. BGE-small 512-token

- 模型：`BAAI/bge-small-zh-v1.5`，512 dim，`max_position_embeddings=512`；
- 9 科 Exact：9/18 = 0.50，Precision 1.00；
- 已知限制：长题干语义稀释；
- 当前动作：**保持 V1 冻结基线**，不静默替换。

### F. qwen3-embedding:4b（已验证候选，不进入当前生产）

- Ollama 本地模型：4B，2560 dim，context 40960，Q4_K_M；
- 9 科 Exact：10/18 = 0.556；Unknown 37/37；但 E017 出现 1 个 `false_similar`（top1 错题）；
- 建索引约 166 秒（1166 题）；
- 结论：**V1.1 候选**，需重新校准阈值/长文本分块/池化后再比较；**不得静默替换 BGE**。

---

## 4. 当前主线的封闭口径

| 问题 | 当前定性 | 当前动作 | 长期项目 |
|---|---|---|---|
| G8 × 6 | LLM 显式不确定 | 锁定，不放宽 Gate | Manifest 理解能力 |
| G9 × 5 | 结构区间错误 | 锁定，保持 fail-closed | Manifest 结构验证 |
| OCR 真截断 × 2 | 真源缺失 | 锁定为阻断案例 | OCR 质量 |
| OCR 格式误报 × 6 | 截断门归一化不足 | 锁定，不现场修 | Strict Adapter 归一化 |
| Essay × 33 | Compiler 题型覆盖缺口 | 不改 QCore | Essay Teaching Contract |
| BGE 512 | V1 模型能力限制 | 保持 V1 冻结 | Semantic V1.1 |

### 锁定原则

1. 11 份 G8/G9 不作为当前生产阻断。
2. 8 份 OCR source defect 不再称为 Map Failed。
3. 2 份真截断保留为阻断样本。
4. 6 份格式误报作为 Strict Adapter 回归样本。
5. 33 份 essay `NO_ANSWER` 不作为 Question 数据异常。
6. Essay 通过独立 Teaching Contract 解决。
7. BGE-small 继续作为 V1 冻结基线。
8. qwen3-embedding:4b 仅作为 V1.1 候选，不进入当前生产。
9. 所有样本、错误类型、触发条件、当前结论进入长期回归资产。
10. 当前主线不因这些问题重开已通过的 Euler PREPROD / Semantic V1 工作。

---

## 5. 长期项目验收（不是本轮验收）

每个子项独立立项、独立验收：

1. 根因分类完成（不是只记录 Gate 名称）；
2. 只修通用缺陷，不针对单份样本写特判；
3. 在冻结的 8/11/33 样本上做回归；
4. 真截断检测能力不下降；
5. 不放宽 Exact/Similar/Unknown 的 fail-closed；
6. 生产 QCore 零写入；
7. 经 MIMO 独立复核 + Owner 裁决后才进入生产。

---

## 6. 证据

| 内容 | 路径 |
|---|---|
| 机器可读样本清单 | `docs/quality/known_quality_gaps_20261125.json` |
| 逐卷统计 | `runs/qcore_semantic_expansion_01/track_a_per_paper.md` |
| Gate 原始文件 | `runs/qcore_semantic_expansion_01/production/preprocessing/**/*.gate.json` |
| 零题执行记录 | `runs/qcore_semantic_expansion_01/execution/import_final/papers/` |
| 编译结果 | `runs/qcore_semantic_expansion_01/compile_final.json` |
| Semantic A/B | `_dsh/semantic_expansion_01/eval/final/report_exact_qwen3.json` |
| 总报告 | `_dsh/semantic_expansion_01/EULER_QCORE_SEMANTIC_EXPANSION_01_REPORT.md` |
