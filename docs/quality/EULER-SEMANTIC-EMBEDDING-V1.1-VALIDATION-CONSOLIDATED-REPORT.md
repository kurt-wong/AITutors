# EULER-SEMANTIC-EMBEDDING-V1.1-ISOLATED-VALIDATION
## 任务总报告（含渲染 Holdout 与真实照片两次验证）

- 执行方：DSH
- 独立复核：MIMO（待提交）
- 裁决方：Owner
- 日期：2026-11-25
- 基线：AITutors `b0010dbed`
- 当前 HEAD：`8df070a43`（已推送 `origin/main`）
- 当前生产默认：**BGE-small-zh-v1.5 / Semantic Retrieval V1，未切换**
- V1.1 候选：`embeddinggemma-2:latest`，冻结配置 `.74/.85/.55`

---

# 0. 执行摘要

本轮完成了 Semantic Retrieval V1.1 的隔离实施与两次照片验证：

1. **渲染 Holdout 验证（45 条，单题裁剪）**
   - BGE：20/45，False Exact = 0；
   - gemma-2：23/45，False Exact = 0；
   - 18 条独立负向：双方均 18/18 Unknown；
   - 结论：**渲染数据上技术安全通过，但无真实手机照片独立证据**，当时判 `INSUFFICIENT EVIDENCE`。

2. **真实手机照片验证（45 张，整页/多题照片）**
   - BGE：20/45，False Exact = **4**；
   - gemma-2：16/45，False Exact = **4**；
   - 4 个错误全部是“照片里同时有多道题，模型选中了同一照片中的相邻题”，Top1 均在照片中可见，不是凭空匹配。
   - 结论：**严格目标判定 FAIL**；双方都失败，根因包含“未单题裁剪”的输入协议问题。

3. **后续多候选原型（Owner 选择整页拍照 + 用户选择）**
   - 整页 OCR 分题 → 每题候选项 → 用户选择；
   - 45 张真机照片中，gemma 的目标题 **45/45 进入 top-10**；BGE 44/45；
   - 两模型 `auto_exact = 0`，不再自动输出单一 Exact；
   - 结论：**多候选原型 PASS（候选覆盖）**，但需要 UI 和用户选择验证，生产仍不切换。

**一句话结论：**

> V1.1 的工程隔离完成；单题渲染数据上 gemma 略优；真实多题照片上双方都出现错误 Exact；改为多候选后目标覆盖显著改善，但尚未证明生产可用。当前不应切换默认模型，也不应把 embedding 当作 Exact 的最终权威。

---

# 1. 任务背景与边界

## 1.1 目标

验证 `embeddinggemma-2` 是否具备成为 Semantic Retrieval V1.1 默认 Embedding 模型的资格：

1. 独立 Adapter + 独立索引；
2. 不修改 BGE V1 默认路径/阈值/索引；
3. 在独立 Holdout 上验证 Exact 安全性与 Unknown fail-closed；
4. 真实手机照片验证；
5. 不切换生产默认模型，不写生产 QCore。

## 1.2 硬边界

- 未修改生产 QCore 的 Question/Revision/Instance/Answer/Asset/Evidence；
- 未执行生产 Admission/Publish/Withdraw；
- 未修改 BGE V1 默认模型、阈值、索引、入口；
- 未修改 DeepTutor、Preprocessing、Track C；
- 未用 LLM 参与 Exact 判定；
- 未通过放宽规则或特判提高指标；
- 生产 guard 与冻结基线全等（175/193/585/169，published 169）。

---

# 2. 实现与模型身份

## 2.1 新增代码

```text
Teaching Script Compiler/tsc_compiler/semantic/v11/
  config.py      # 冻结 .74/.85/.55 + config_hash
  model.py       # Ollama embeddinggemma-2 adapter
  index.py       # 独立 namespace / model digest / 索引校验
  multi.py       # 整页分题 + 多候选 + 用户选择
  cli.py         # identity / build / search / verify / multi
tests/test_semantic_v11.py
```

关键行为：

- 独立 model digest、dim、config hash、corpus hash 校验；
- 不匹配直接拒绝，不静默回退 BGE；
- 空文本/超长文本/模型不可用 fail-closed；
- 不静默截断；批量分块，避免一次提交 1166 条导致 Ollama runner 失败；
- 多候选层永不返回 `auto_exact`。

## 2.2 模型身份

| 项 | 值 |
|---|---|
| 模型 | `embeddinggemma-2:latest` |
| digest | `f4981a15b99858ad1f2e0729416e526be7b4f428291b40082b9e4f7b27b5f62f` |
| 大小 | 1,284,852,670 B |
| 参数/量化 | 271M / Q8_0 |
| 元数据维度 | 512 |
| API 实际维度 | **768** |
| 元数据 context | 262144 |
| Runner 实际 context | **131072** |
| 索引 | 1166 docs / 768 dim / 10.8 MB |
| config_hash | `aae25d73605ae08ec895ae68fc961683be36b50d487841e62b786006cbf45024` |

元数据维度/context 与运行时不一致，均已显式记录；索引按实际 768 维构建。

## 2.3 性能

| 项 | 结果 |
|---|---:|
| 冷启动首条 | 3.11 s |
| 热单条 | 0.025 s |
| 批量 8 条 | 0.093 s |
| 1166 文档索引 | 约 23 s |
| 94 条查询 | 约 2.1 s |
| VRAM | 486 MB |

---

# 3. 数据与标签

## 3.1 开发集（历史，不独立）

- 38 条 Exact（18 条 9 科 + 20 条生产数学）；
- 37 条真机负向；
- 19 组 Similar/Hard-negative 配对；
- 这些数据参与过模型选型/阈值选择，**不能算独立验证**。

## 3.2 渲染 Holdout R2（独立，单题裁剪）

- 45 条，9 科 ×5；27 holdout + 18 confirm；
- 排除所有开发 query 的 question_id；
- 从封存 PDF 用文本搜索定位题目区域、200dpi 渲染、1.2° 旋转、JPEG；
- 33 个候选因无法可靠裁剪/OCR/stem 校验失败被记录为 skipped，未静默删除；
- manifest SHA-256：`42c2fcef00f6eed8184a1540752159b8eb43409102b58452ccd04692891819e5`；
- **capture_mode = rendered_photo_style，不是真实手机拍摄。**

### R1 渲染缺陷（重要事故）

第一次 Holdout R1 使用旧裁剪函数，大量题目回退为“整页”，导致 query 与标签不对应；R1 出现 3 个“False Exact”（H001/H036/H040）。逐条核对确认是**整页 fallback 的标签错位，不是模型误放**。

- R1 图片已归档 `v11/holdout/images_invalid_r1/`；
- R1 结果不进入任何模型指标；
- R2 改为文本搜索 + stem 校验后，45 条有效，双方 0 False Exact。

## 3.3 真实手机照片（独立，整页/多题）

- 45 张，iPhone 12 Pro Max；
- 原始相机文件名 `IMG_8123.jpeg`–`IMG_8167.jpeg`，**未改名、未裁切**；
- OCR 45/45 status=ok（PaddleOCR-VL-1.5）；
- 标签按冻结 Holdout 顺序 + OCR 覆盖率配对；44/45 的 Top1 与目标顺序一致；
- 6 张低置信度人工看图核对：IMG_8124、8127、8128、8157、8158、8161；
- manifest SHA-256：`e407ba721836606789444b1e3c2c0a07ab1c7060c03c1d5fd6b1f5bae37378a2`；
- **capture_mode = real_camera**。

照片中至少 5 张包含多道题：

- IMG_8130：数学 Q11–Q13；
- IMG_8131：数学 Q12–Q17；
- IMG_8154：历史 Q29–Q30；
- IMG_8156：历史 Q8–Q10；
- IMG_8158：地理 Q3–Q7。

---

# 4. 验证一：渲染 Holdout（单题裁剪）

## 4.1 Exact

| 模型 | 全部 45 | Holdout 27 | Confirm 18 | False Exact | Precision |
|---|---:|---:|---:|---:|---:|
| BGE V1 | 20（44.4%） | 14/27 | 6/18 | **0** | 1.00 |
| gemma-2 V1.1 | **23（51.1%）** | 15/27 | 8/18 | **0** | 1.00 |

分科：

| 学科 | BGE | gemma |
|---|---:|---:|
| 语文 | 1/5 | 1/5 |
| 数学 | 3/5 | 3/5 |
| 英语 | 3/5 | 2/5 |
| 物理 | 4/5 | 5/5 |
| 化学 | 1/5 | 2/5 |
| 生物 | 2/5 | 4/5 |
| 历史 | 4/5 | 4/5 |
| 地理 | 0/5 | 0/5 |
| 政治 | 2/5 | 2/5 |

gemma 提升集中在物理/化学/生物；英语略降；地理双方 0/5。

## 4.2 独立负向

| 模型 | Unknown | False Exact | False Similar |
|---|---:|---:|---:|
| BGE | 18/18 | 0 | 0 |
| gemma-2 | 18/18 | 0 | 0 |

## 4.3 真机 legacy 回归（非独立）

| 集合 | BGE | gemma-2 |
|---|---|---|
| Owner test1/test2（Q4 正向） | 2/2 Exact | 2/2 Exact |
| PREPROD 37 条真机负向 | 37/37 Unknown | 37/37 Unknown |

这些曾用于开发，不能算独立证据。

## 4.4 Similar（非独立）

生产 175 语料，7 正例/12 hard negative：

| 模型 | Similar Recall | Hard-negative Unknown | False Similar |
|---|---:|---:|---:|
| BGE | 6/7 | 11/12 | 1（PN02） |
| gemma-2 | 4/7 | 12/12 | 0 |

gemma Similar Recall 较低，但 hard-negative 更干净。

## 4.5 阶段结论

- 渲染单题数据上，gemma +3 Exact，0 False Exact；
- 但当时**没有真实手机照片独立证据**，也没有独立 Similar 金标；
- 阶段状态：`INSUFFICIENT EVIDENCE`，不切换生产。

---

# 5. 验证二：真实手机照片（整页/多题）

## 5.1 严格目标结果

按“每张照片的目标题”判定：

| 模型 | Exact | Recall | False Exact | Similar | Unknown |
|---|---:|---:|---:|---:|---:|
| BGE V1 | 20/45 | 44.4% | **4** | 11 | 10 |
| gemma-2 V1.1 | 16/45 | 35.6% | **4** | 9 | 16 |

**双方都没有达到 False Exact = 0。**

分科：

| 学科 | BGE Exact / False | gemma Exact / False |
|---|---:|---:|
| 语文 | 2 / 0 | 2 / 0 |
| 数学 | 1 / 1 | 0 / 1 |
| 英语 | 5 / 0 | 3 / 0 |
| 物理 | 3 / 0 | 3 / 0 |
| 化学 | 1 / 0 | 2 / 0 |
| 生物 | 2 / 0 | 0 / 0 |
| 历史 | 0 / 2 | 1 / 2 |
| 地理 | 2 / 1 | 3 / 1 |
| 政治 | 4 / 0 | 2 / 0 |

## 5.2 四个 False Exact 逐条

| 照片 | 目标 | 实际 Top1 | 模型 | Top1 在同一照片中可见 | Top1 文本覆盖率 |
|---|---|---|---|---|---|
| IMG_8131 | 数学 Q14 | 数学 Q15 | BGE | 是 | 1.00 |
| IMG_8130 | 数学 Q12 | 数学 Q13 | gemma | 是 | 1.00 |
| IMG_8154 | 历史 Q30 | 历史 Q29 | BGE + gemma | 是 | 0.769 |
| IMG_8156 | 历史 Q8 | 历史 Q9 | BGE + gemma | 是 | 1.00 |
| IMG_8158 | 地理 Q6 | 地理 Q3–Q5 题组 | BGE + gemma | 是 | 1.00 |

关键观察：

- **没有一条 Top1 不在照片中**；
- 不是“把照片外的题认成 Exact”，而是“照片里有多道题，选了另一道”；
- 5 张多题照片贡献了全部 8 个模型级 False Exact（4 + 4）；
- 这是**输入粒度/目标选择问题**，不是单纯的 embedding 语义错误。

## 5.3 为什么仍然判 FAIL

任务书的 Exact 语义是“可以确认输入对应的目标题”。一张照片里有 Q14 和 Q15，用户要 Q14，系统返回 Q15，仍然是错误 Exact。

BGE 也 4 个 False Exact，说明不是 V1.1 独有缺陷；但也不能反过来说 gemma 更好——gemma 真实照片 Exact 反而低于 BGE（16 vs 20）。

## 5.4 阶段结论

- 真实照片严格目标验证：**FAIL**；
- 不切换生产默认模型；
- 现有“单一 Exact”交互不适合整页/多题照片；
- 需要单题裁剪，或改为多候选用户选择。

---

# 6. 后续：多候选交互原型

Owner 选择：允许整页拍照，系统返回多个候选，由用户选择目标题；不再用单一 Exact 决策。

## 6.1 实现

`tsc_compiler/semantic/v11/multi.py`：

1. 按行首题号把整页 OCR 切段；
2. 每段检索 top-5；
3. 整页检索 top-10 兜底；
4. 按 question_id 去重、排序；
5. 顶层 `auto_exact = null`、`status = needs_user_selection`；
6. 每条候选 `requires_user_selection = true`。

CLI：

```bash
python -m tsc_compiler.semantic.v11.cli multi \
  --index runs/qcore_semantic_expansion_01/v11/index_gemma2 \
  --query "<整页 OCR 文本>"
```

## 6.2 45 张真机照片候选覆盖

| 模型 | @1 | @3 | @5 | @10 | 目标缺失 | 平均候选数 |
|---|---:|---:|---:|---:|---|---:|
| BGE V1 | 64.4% | 88.9% | 93.3% | 97.8% | IMG_8142 | 15.24 |
| gemma-2 | **71.1%** | **91.1%** | **95.6%** | **100%** | **无** | 14.67 |

- gemma：45/45 目标进入 top-10；
- BGE：44/45；
- `auto_exact_count = 0`；
- 之前单一 Exact 的 4 个 False Exact，在多候选模式下变成“候选由用户选择”，不再自动错题。

## 6.3 结论

- 多候选原型：**PASS（候选覆盖）**；
- 但平均约 15 个候选，UI 负担明显；
- 建议默认 top-5、展开 top-10，按题号分组；
- 生产仍不切换，多候选只是 V1.1 candidate 交互。

---

# 7. 关键发现

## 7.1 输入粒度比模型差异更大

同一批 45 题：

| 数据集 | BGE | gemma | False Exact |
|---|---:|---:|---:|
| 渲染单题裁剪 | 20/45 | 23/45 | 0 / 0 |
| 真机整页多题 | 20/45 | 16/45 | 4 / 4 |

- 单题裁剪：gemma +3；
- 整页多题：gemma -4；
- 阈值未变，差异主要来自**输入粒度/多题页面**。

## 7.2 单一 Exact 不适合整页拍照

整页照片中，系统无法知道用户要哪道题；返回一个 Exact 必然有选错风险。

- 多题页面需要“多候选 + 用户选择”；
- 或强制单题裁剪；
- 不能靠调 embedding 阈值解决。

## 7.3 “False Exact”不等于“模型幻觉”

本轮 4 个 False Exact 的 Top1 全部在照片中可见；模型没有编造照片外的题，而是选了相邻题。

这仍然算严格目标的错误，但根因分类不同：

- **模型语义误配**：Top1 不在照片中；
- **输入粒度/目标选择错误**：Top1 在照片中，但不是用户目标。

本轮属于后者。

## 7.4 Embedding 是候选召回，不是身份权威

- OCR 不需要 embedding；
- embedding 只负责“题库候选召回/排序”；
- 最终 Exact 需要词法/题号/选项/数字/来源证据；
- 多候选 + 用户选择可以降低对 embedding 正确性的依赖；
- 真实数据没有证明“必须升级 gemma”，也没有证明“embedding 一定优于词法”。

## 7.5 LLM 可做重排，不适合替代全库向量召回

- LLM 直接对 1166 题做全库匹配：上下文/成本/延迟/幻觉/非确定性都不合适；
- LLM 适合对 embedding/词法召回的 top-20 做 rerank；
- 任何 LLM 参与 Exact 都必须有硬证据和人工确认，不能单独裁定。

---

# 8. 当前状态

| 项 | 状态 |
|---|---|
| V1.1 隔离 Adapter/索引 | 完成 |
| 渲染 Holdout | 0 False Exact，但仅 rendered_photo_style |
| 真实照片严格目标 | **FAIL（双方各 4 False Exact）** |
| 多候选原型 | 候选覆盖 PASS（gemma top-10 45/45） |
| 生产默认模型 | **BGE V1，未切换** |
| 生产 QCore | 零写入，guard 全等 |
| 测试 | 53 passed |
| 独立 Similar 金标 | 未建立 |
| 真实 UI/用户选择日志 | 未实现 |

**结论：V1.1 不是生产就绪状态；当前只能作为隔离候选和讨论原型。**

---

# 9. 提交与证据

## 9.1 提交

| 提交 | 内容 |
|---|---|
| `b0010dbed` | 选型结论：gemma-2 主候选 |
| `efe8caab4` | V1.1 隔离 Adapter/索引/测试 |
| `dd10ca0cc`、`a5984c440` | 渲染 Holdout 报告与基线更新 |
| `4bc72c394` | 真机严格目标 FAIL 报告 |
| `8df070a43` | 多候选交互实现与报告 |

HEAD：`8df070a43`，已推送 `origin/main`。

## 9.2 关键证据

| 内容 | 路径 |
|---|---|
| V1.1 代码 | `Teaching Script Compiler/tsc_compiler/semantic/v11/` |
| 渲染 Holdout R2 | `runs/qcore_semantic_expansion_01/v11/holdout/holdout_manifest_r2.json` |
| R1 无效图 | `runs/qcore_semantic_expansion_01/v11/holdout/images_invalid_r1/` |
| 真实照片 OCR | `runs/qcore_semantic_expansion_01/v11/real_photos/real_photos_ocr.jsonl` |
| 真实照片标签 | `runs/qcore_semantic_expansion_01/v11/real_photos/real_photos_manifest.json` |
| 真实照片单 Exact 评测 | `runs/qcore_semantic_expansion_01/v11/real_photos/real_photos_eval.json` |
| 多候选评测 | `runs/qcore_semantic_expansion_01/v11/real_photos/multi_candidate_eval.json` |
| 渲染报告 | `docs/quality/EULER-SEMANTIC-EMBEDDING-V1.1-ISOLATED-VALIDATION-01.md` |
| 真机报告 | `docs/quality/EULER-SEMANTIC-EMBEDDING-V1.1-REAL-PHOTO-VALIDATION-01.md` |
| 多候选报告 | `docs/quality/EULER-SEMANTIC-EMBEDDING-V1.1-MULTI-CANDIDATE-01.md` |

---

# 10. 建议与待讨论问题

## 10.1 明确建议

1. **生产默认继续 BGE V1，不切换 gemma。**
2. **单一 Exact 不应直接用于整页/多题照片。**
3. 整页拍照必须走：
   - 单题裁剪，或
   - 多候选 + 用户选择。
4. 多候选默认 top-5，展开 top-10；按题号分组，禁止自动选中 top1。
5. 在补独立 Similar 金标和真实用户选择数据前，不做生产切换。

## 10.2 需要与 ChatGPT 讨论的问题

1. **交互契约**：整页拍照是否正式允许？候选 top-5 还是 top-10？用户选择如何记录/回滚？
2. **标签协议**：真实照片按“单题目标”还是“整页内任意可见题”？两者指标不可混用。
3. **Embedding 是否值得保留**：是否先做 lexical-only / dense-only / fused 消融，再决定是否继续投入模型升级？
4. **LLM 的角色**：只做 top-20 rerank，还是做查询理解/多题切分？如何防止幻觉和 prompt injection？
5. **BGE vs gemma**：真实数据没有证明 gemma 更优，是否应直接保留 BGE、停止模型升级？
6. **验收标准**：如果走多候选，验收应该按“目标进入 top-k”还是“用户最终选对率”？
7. **下一步实验**：建议先做 45 真机 + 45 渲染的同口径消融，而不是继续换模型。

---

# 11. 一句话给讨论方

> 这不是“embedding 模型选型成功/失败”的简单问题；真实数据暴露的是：**整页多题照片不能用单一 Exact，embedding 只能做候选召回，最终需要多候选/用户选择或强单题裁剪。** 当前最稳妥的生产策略是保留 BGE V1，不切换 gemma，先验证交互与词法/结构化方案。
