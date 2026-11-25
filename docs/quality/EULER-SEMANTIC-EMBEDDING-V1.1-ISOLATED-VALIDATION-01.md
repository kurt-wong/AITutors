# EULER-SEMANTIC-EMBEDDING-V1.1-ISOLATED-VALIDATION-01

- 执行：DSH
- 独立复核：MIMO（待提交）
- 最终裁决：Owner
- 日期：2026-11-25
- 代码提交：`efe8caab4`（隔离 Adapter/索引/测试）
- 基线：AITutors `b0010dbed`（任务开始时 `b0010dbed` 已推送）
- 冻结候选：`embeddinggemma-2:latest`，`exact_dense=0.74 / similar_dense=0.85 / similar_lexical=0.55`
- **最终状态：INSUFFICIENT EVIDENCE（不足以授权生产默认切换）**

---

## 0. 结论

V1.1 候选的**工程隔离实现完成**，并在独立渲染 Holdout 上通过了 Exact 安全底线：

- 独立 Holdout：BGE **20/45**、gemma-2 **23/45**；两者 **False Exact = 0**；
- 独立负向：BGE **18/18 Unknown**、gemma-2 **18/18 Unknown**；
- BGE V1 未被修改，生产 QCore guard 全等。

但本轮**不能给出 PASS / 生产切换资格**，原因是任务书要求的“新增九科真实拍摄照片 ≥45 张”没有可用来源：本轮只能用**从封存 PDF 渲染的 photo-style crop**，再加上已有的 2 张 Owner 真机照片和 37 张真机负向（均非独立）。同时，独立 Similar 正例金标也未建立。

因此最终状态为 **INSUFFICIENT EVIDENCE**：技术实现与渲染 Holdout 的安全性通过，但真实照片独立证据不足，**不切换生产默认模型**。

---

## 1. 边界与未越界证明

- 未修改 BGE V1 默认模型、阈值、索引或决策路径。
- 未写入生产 QCore；所有实验在 `runs/qcore_semantic_expansion_01/v11/` 与 `_dsh/`。
- 未修改 Question/Revision/Instance/Answer/Asset/Evidence 契约。
- 未修改 DeepTutor、Preprocessing、Track C 设计。
- 未用 LLM 参与 Exact 判定，未补写题干/答案。
- 未放松任何 Exact/Similar/Unknown 规则；V1.1 使用独立的 `SemanticConfig`，共享的只是未修改的 V1 决策引擎。

---

## 2. 代码与架构

新增：

```text
Teaching Script Compiler/tsc_compiler/semantic/v11/
  __init__.py
  config.py      # 冻结 .74/.85/.55 + config_hash
  model.py       # Ollama embeddinggemma-2 adapter（digest/维度/长度/失败关闭）
  index.py       # 独立命名空间/模型绑定/索引校验
  cli.py         # identity / build / search / verify
tests/test_semantic_v11.py
```

关键设计：

- **模型身份**：记录 Ollama `digest`，索引加载时校验 name/digest/dim；不一致直接拒绝。
- **维度**：模型元数据 `embedding_length=512`，但 `/api/embed` 实际返回 **768**；adapter 以实际探测维度 768 为准，并在 identity 中记录 `dimension_mismatch_metadata_vs_api=true`。
- **不静默截断**：配置 `max_chars=100000`，超长/空文本直接 fail-closed；不存在“悄悄截断后当作完整题”。
- **批量**：adapter 内部分批（batch=8），避免一次提交 1166 条导致 Ollama runner/tokenize 失败。
- **独立索引**：`namespace=semantic_v11_gemma2`，独立 `docs.json/embeddings.npy/meta.json`；meta 绑定 model digest、dim、config_hash、corpus_sha256、docs_sha256。
- **不污染 V1**：BGE 索引 `_dsh/semantic_expansion_01/index_final` 保持原路径与原字节；V1.1 索引在 `runs/.../v11/index_gemma2`。

---

## 3. 模型身份与索引

| 项 | 值 |
|---|---|
| 模型 | `embeddinggemma-2:latest` |
| digest | `f4981a15b99858ad1f2e0729416e526be7b4f428291b40082b9e4f7b27b5f62f` |
| 大小 | 1,284,852,670 B |
| 参数/量化 | 271M / Q8_0 |
| 元数据维度 | 512 |
| API 实际维度 | **768** |
| 元数据 context | 262144 |
| Runner 实际 context | **131072**（`/api/ps`） |
| 索引 | 1166 docs / 768 dim / 10,827,272 B |
| config_hash | `aae25d73605ae08ec895ae68fc961683be36b50d487841e62b786006cbf45024` |
| corpus_sha256 | `7da837fc09417036f05011f5894260256f7722a43a87c6271860a87f3cba3a55` |

> 元数据与运行时 context 不一致、元数据与 API 维度不一致，均已显式记录；索引按实际 768 维构建，不按元数据猜测。

---

## 4. 数据划分

| 数据集 | 用途 | 独立性 | 规模 |
|---|---|---|---|
| Historical Development | 选型/阈值（已有） | 开发集 | 38 Exact + 37 真机负向 + 19 Similar/Hard 配对 |
| **Independent Holdout R2** | 本轮主验证 | 与开发 query 的 question_id 完全不重叠 | **45**（27 holdout + 18 confirm），9 科 ×5 |
| Independent Negatives | Unknown/Hard 负向 | 来自 75 份之外 PDF | **18**（9 科 ×2 页） |
| Legacy Real Camera | 真机回归 | **非独立**（已用于 PREPROD/开发） | 2 正 + 37 负 |

### 4.1 Holdout R2

- 冻结文件：`runs/qcore_semantic_expansion_01/v11/holdout/holdout_manifest_r2.json`
- manifest SHA-256：`42c2fcef00f6eed8184a1540752159b8eb43409102b58452ccd04692891819e5`
- 45/45 OCR ok；27 holdout + 18 confirm；每科 5。
- 开发 query 的 question_id 全部排除；`dev_query_ids_sha256` 写入 manifest。
- **capture_mode = rendered_photo_style**：从封存 PDF 用文本搜索定位题目区域、200dpi 渲染、1.2° 旋转、JPEG。
- 33 个候选因无法可靠裁剪或 OCR/stem 校验失败被记录为 `skipped`，未静默删除。
- 这仍然不是真实手机拍摄；见 §8。

### 4.2 第一次 Holdout（R1）无效及纠正

R1 使用旧的 `render_question_image`，大量题目落入 `full_page_fallback`，导致 query 是整页而标签是该页之外的题。R1 出现 3 个“False Exact”（H001/H036/H040），逐条核对后确认是**渲染/标签缺陷，不是模型误放**：

- H001：query 是卷首整页，期望题在后续页面；
- H036/H040：query 是地理卷首整页，期望题在第 10 页之后。

R1 的 45 张图已归档到 `v11/holdout/images_invalid_r1/`，R1 结果仅作为“渲染缺陷证据”，**不进入任何模型指标**。R2 改用文本搜索定位 + stem 校验后重建。

### 4.3 独立负向

- 冻结文件：`v11/negatives/negative_manifest.json`
- SHA-256：`d31650a785b7021b3c304c138e69dee688af0e33263455a2678f4637fda2731d`
- 9 科 ×2 页 = 18；来自 75 份之外的 PDF；同样为 rendered photo-style，非真机。
- 标签：`unknown`，`expected_question_ids=[]`。

---

## 5. 独立 Holdout 结果

### 5.1 Exact

| 模型 | 全部 45 | Holdout 27 | Confirm 18 | False Exact | Exact Precision |
|---|---:|---:|---:|---:|---:|
| BGE V1（冻结） | **20（44.4%）** | 14/27 | 6/18 | **0** | **1.00** |
| gemma-2 V1.1 | **23（51.1%）** | 15/27 | 8/18 | **0** | **1.00** |

- gemma-2 +3 Exact，0 False Exact；两个 split 都没有错误放行。
- 所有 45 条均按冻结 `.74/.85/.55` 运行，未根据 Holdout 调阈值。

### 5.2 分科 Exact

| 学科 | BGE | gemma-2 |
|---|---:|---:|
| 语文 | 1/5 | 1/5 |
| 数学 | 3/5 | 3/5 |
| 英语 | 3/5 | 2/5 |
| 物理 | 4/5 | **5/5** |
| 化学 | 1/5 | **2/5** |
| 生物 | 2/5 | **4/5** |
| 历史 | 4/5 | 4/5 |
| 地理 | 0/5 | 0/5 |
| 政治 | 2/5 | 2/5 |

gemma-2 的提升集中在物理/化学/生物；英语略降；地理两模型都是 0/5（长材料 + 图表 + 选项）。

### 5.3 独立负向

| 模型 | Unknown | False Exact | False Similar |
|---|---:|---:|---:|
| BGE V1 | **18/18** | 0 | 0 |
| gemma-2 V1.1 | **18/18** | 0 | 0 |

### 5.4 真机回归（非独立）

| 集合 | BGE | gemma-2 |
|---|---|---|
| Owner test1/test2（Q4 正向） | 2/2 Exact | 2/2 Exact |
| PREPROD 37 条真机负向 | 37/37 Unknown | 37/37 Unknown |

这两组都曾用于开发/选型，**不能算独立证据**；只证明候选没有破坏已通过的 PREPROD 行为。

### 5.5 Similar（非独立）

生产 175 语料、7 正例/12 hard negative（开发集）：

| 模型 | Similar Recall | Hard-negative Unknown | False Similar |
|---|---:|---:|---:|
| BGE V1 | 6/7 | 11/12 | 1（PN02） |
| gemma-2 V1.1 | 4/7 | **12/12** | **0** |

gemma-2 的 Similar Recall 低于 BGE，但 Hard-negative 更干净。该集合不独立，**不能作为 V1.1 Similar 的最终验收**。

---

## 6. False Exact / False Similar 明细

**R2 有效 Holdout：False Exact = 0（BGE 与 gemma-2 均为 0）。**

R1 的 3 个 false exact（H001/H036/H040）已逐条调查：

- 全部是整页 fallback 导致 query 与 label 不对应；
- 不是 gemma-2 把不同题判成同一题；
- R1 数据已隔离，不计入模型指标；
- R2 通过文本搜索 + stem 校验修复，0 false exact。

Similar 的 false positive 必须在报告中同时披露正例命中、false similar 总数、hard-negative false similar；本轮 gemma-2 在独立负向上 false similar=0，但在非独立 Similar 集上为 0/12 hard，正例 4/7。

---

## 7. 性能与稳定性

| 项 | 结果 |
|---|---:|
| 冷启动（模型加载后首条） | **3.11 s** |
| 热单条 | **0.025 s** |
| 批量 8 条 | **0.093 s** |
| 1166 文档索引构建 | **约 23 s** |
| 94 条查询 | **约 2.1 s** |
| 索引磁盘 | **10.8 MB** |
| 模型显存（`/api/ps` size_vram） | **486 MB** |
| 重复同文本 cosine | **1.0**，数组完全相等 |
| 空文本 / 超长文本 | fail-closed（`V11InputError`） |
| Ollama 不可用 | fail-closed（`V11ModelUnavailable`） |
| 模型 digest/维度不匹配 | 索引加载拒绝（`V11IndexMismatch`） |

未发生静默 fallback 到 BGE；失败即报错。

---

## 8. 为什么不是 PASS

任务书要求“新增九科真实拍摄照片，建议 ≥45 张，每科 ≥5”。本轮实际可用：

- **真实手机照片**：只有 Owner 的 test1/test2（2 张，且已被 PREPROD 使用）；
- **真实手机负向**：37 张（已被 PREPROD/选型使用）；
- **本轮新增**：45 张 Holdout + 18 张负向，全部是 **从 PDF 渲染的 photo-style 图像**，不是摄像头拍摄。

因此：

1. 独立 Exact 安全性在“渲染图”上通过，但不能等价于“真实拍摄”；
2. 独立 Similar 正例金标没有建立；
3. 无法证明“不同光照/角度/裁剪/真实 OCR 噪声”下的稳定性。

按任务书三类结论，只能给 **INSUFFICIENT EVIDENCE**，不能给 PASS，也不能给 FAIL（没有在有效数据上触发安全失败）。

---

## 9. BGE V1 零变化

| 检查 | 结果 |
|---|---|
| V1 默认配置 | `.84/.80/.55`，未变 |
| V1 索引 `index_final` | 未写入；`docs.json`/`embeddings.npy` 哈希保持 |
| V1 默认入口 | 未改 |
| Compiler 测试 | **51 passed**（45 原 + 6 V1.1） |
| 生产 guard | 与 `guard_preprod.json` **完全相等**（175/193/585/169） |
| 生产事务只读 | on |

V1.1 索引与 V1 索引：

- V1：`_dsh/semantic_expansion_01/index_final`（BGE，512 dim）
- V1.1：`runs/.../v11/index_gemma2`（gemma-2，768 dim，独立 namespace）
- 两者 docs 相同（1166），embeddings 不同，meta/config 独立；V1.1 不覆盖 V1。

---

## 10. 最终建议

1. **不切换生产默认模型。** BGE V1 继续冻结。
2. **保留 V1.1 Candidate 实现**（`efe8caab4`）与索引/评测证据；它不是生产入口。
3. **下一步由 Owner 提供真实手机照片**：9 科 ×5，最好覆盖不同角度/光照/裁剪；在拿到照片前，不再用渲染图宣称真实照片泛化。
4. **建立独立 Similar/Variant 金标**（人工核定），再复验 gemma-2 的 Similar 4/7 是否可接受。
5. 在真实照片 + 独立 Similar 到位后，用**同一冻结配置** `.74/.85/.55` 重跑一次；任何调阈值都必须新开评测版本，不能混报。

---

## 11. 证据

| 内容 | 路径 |
|---|---|
| V1.1 代码 | `Teaching Script Compiler/tsc_compiler/semantic/v11/` |
| 测试 | `Teaching Script Compiler/tests/test_semantic_v11.py` |
| Holdout R2 manifest | `runs/qcore_semantic_expansion_01/v11/holdout/holdout_manifest_r2.json` |
| Holdout R1 无效图 | `runs/qcore_semantic_expansion_01/v11/holdout/images_invalid_r1/` |
| 独立负向 manifest | `runs/qcore_semantic_expansion_01/v11/negatives/negative_manifest.json` |
| Holdout 评测 | `runs/qcore_semantic_expansion_01/v11/eval/holdout_eval.json` |
| 独立负向评测 | `runs/qcore_semantic_expansion_01/v11/eval/independent_negatives_eval.json` |
| 真机回归 | `runs/qcore_semantic_expansion_01/v11/eval/legacy_real_camera_positive.json`、`legacy_real_camera_negatives.json` |
| Similar 回归 | `runs/qcore_semantic_expansion_01/v11/eval/pairs_prod_comparison.json` |
| 性能/稳定性 | `runs/qcore_semantic_expansion_01/v11/eval/performance_stability.json` |
| 生产 guard | `_dsh/semantic_expansion_01/v11_guard_after.json` |
