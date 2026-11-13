# AGENTS.md — AITutors 项目规则

> 项目级长期规则，跨会话、跨 Agent 生效。修改需 Owner 明示。
> 最后更新：2026-11-13（Owner 裁决：Question 交付四项验收条件 + 源元素关联最小机制 + 八项原则）

## 0. 适用范围

Question Core、Preprocessing（OCR/切分/Manifest 生成）、Strict Adapter、数据导入与修复的全部工作。

## 1. P0 原则：原始 PDF 是唯一内容事实源

入库目标是**忠实数字化原始 PDF**，不是替出卷者纠错，也不是制作一份经学科专家校订的试卷。

1. PDF 内容正确与否，不影响其作为入库依据。错字、答案错误、选项错位、缺图、解析矛盾，一律忠实保留。
2. OCR 只负责还原 PDF，不负责修正 PDF。OCR 与 PDF 不一致时，修 OCR。
3. Manifest 只负责理解与结构化 PDF，不替 PDF 做事实校订。
4. Adapter 只负责完整映射 Manifest 已确定的信息，不得擅自纠错或改写。
5. PDF 内部存在矛盾时，保留矛盾，不擅自裁定哪一处正确。
6. 未经 Owner 明确授权，不得因 PDF 局部错误而修正、替换或排除题目。

### 1.1 判定表

| 情况 | 正确处理 | 禁止 |
| --- | --- | --- |
| OCR 把 `VO₂⁺` 识别成 `VO₂` | 修复 OCR，恢复 PDF 原文 | 反过来修改 PDF 或接受丢失 |
| PDF 本身答案印错 | 按 PDF 入库 | 按学科知识改成“正确答案” |
| 题干与解析矛盾 | 两处分别保留 + 来源定位 + 冲突标记 | 二选一、静默统一 |
| PDF 缺少某题所需图片 | 记录源文件缺失（asset missing / UNRESOLVED） | 凭空补图、当作答案不存在 |
| Manifest 把 PDF 错字改成正确字 | 阻止静默纠正，记录冲突 | 让 LLM 自行“修正” |
| Manifest 漏提 PDF 中的答案 | 修 Manifest 后重导 | 视为“PDF 本来没有答案” |
| Adapter 漏映射已确定信息 | 修 Adapter 后重导 | 在 DB 手工补答案 |
| 展示层重复/映射问题 | 修展示层 | 反向改 Question Core 数据 |

### 1.2 两条边界

- **保留 PDF 错误 ≠ 允许数据库丢失 PDF 的错误信息。** 选项、答案、解析及三者关联、来源定位，都应尽可能完整保留。
- **修复只针对数字化失真**（OCR 识别错、版面/公式丢失、字段漏映射、静默纠正）；不针对 PDF 事实本身。

## 2. 来源定位与冲突表达（Manifest 职责）

Manifest 必须能区分：

- PDF 实际写了什么（verbatim，不改写）；
- 写在哪里（page / region / 栏位 / source locator）；
- 不同位置是否矛盾（conflict）；
- 哪些内容可确定映射；
- 哪些因源文件缺陷无法确定（保留 `NOT_OBSERVABLE` / `UNRESOLVED`）。

禁止用一个来源覆盖另一个来源。冲突必须保留双份事实与各自定位，由下游按需呈现，而不是在生成阶段裁定。

## 3. 根因分类词表

| 分类 | 含义 |
| --- | --- |
| `OCR_SOURCE_ERROR` | OCR 偏离 PDF 原文（修 OCR） |
| `MANIFEST_LLM_UNDERSTANDING` | LLM 理解/抽取漏项（有留痕才可用；否则标 `(inferred)`） |
| `MANIFEST_POSTPROCESSING` | fixer/后处理破坏已抽取内容 |
| `MANIFEST_VALIDATION_GAP` | 校验未覆盖，问题漏过 |
| `ADAPTER_FIELD_OMISSION` | Adapter 丢弃 Manifest 已确定字段 |
| `ADAPTER_CONDITION_ERROR` | Adapter 条件分支误判 |
| `ADAPTER_STRUCTURE_LOSS` | Adapter 结构降级导致逐项归属丢失 |
| `CONTRACT_EXPRESSION_GAP` | 契约无法表达源事实（如图片答案） |
| `SOURCE_DOCUMENT_INTERNAL_CONFLICT` | PDF 内部区域互相矛盾；忠实保留即可，**不是纠错任务**（U4 属此类） |
| `SOURCE_DOCUMENT_DEFECT` | 源文件缺失/损坏导致无法数字化（缺页、缺图、扫描不可读） |
| `DISPLAY_MAPPING_ISSUE` | 展示层问题，不改 Question Core |
| `NOT_OBSERVABLE` / `UNRESOLVED` | 证据不可得 / 无法判定 |

## 4. 已裁决口径（QCORE-MANIFEST-ADAPTER-ROOT-CAUSE-01）

| 题目 | 根因 | 处置 |
| --- | --- | --- |
| 化学 Q3、语文 Q2 | `ADAPTER_FIELD_OMISSION` | 修 Adapter 映射后重导 |
| 化学 Q8 | `OCR_SOURCE_ERROR`（VO₂⁺）+ `ADAPTER_STRUCTURE_LOSS` | 修 OCR + 逐子归属（8 空位/6 小问） |
| 化学 Q10 | `OCR_SOURCE_ERROR` + Owner P-1 | 忠实还原版面/公式；P-1 是否维持由 Owner 确认 |
| 化学 Q11 | `MANIFEST_LLM_UNDERSTANDING`（inferred） | 补 (2) 后重导，不直接改库 |
| 化学 Q12 | `MANIFEST_LLM_UNDERSTANDING`（inferred）+ Owner P-3 + 契约图片答案缺口 | 图片答案按源内容保留；契约需表达图片答案 |
| 语文 Q8 | `OCR_SOURCE_ERROR`（苦干→苦十） | 修 OCR |
| 语文 Q12 | `OCR_SOURCE_ERROR`（张琪/张珙）+ LLM 静默纠正 | 两处均保留，禁止统一 |
| 英语 U3 | `DISPLAY_MAPPING_ISSUE` | 展示层去重，不改 Question Core |
| 英语 U4 | `SOURCE_DOCUMENT_INTERNAL_CONFLICT` | 忠实入库，保留选项/答案/解析及冲突定位；不纠正、不换卷、不排除 |
| 英语 U9 | — | 正向对照，无需修复 |
| 英语 U10 | `UNRESOLVED` | 待 Owner 定义 essay 答案口径 |

## 5. 工作方式约束

- 诊断阶段只读；修复需 Owner 明确任务指令。
- 不得为通过校验而改数据、改题或排除题目。
- 不得在 DB 手工补答案绕过上游修复；修复后重导受影响 Unit。
- DeepTutor 阶段 B 暂停，待 Owner 授权。

## 6. Question 交付标准与源元素关联原则（2026-11-13 Owner 裁决）

### 6.1 四项验收条件（每道 Question 必须同时满足）

| 要求 | 验收标准 |
| --- | --- |
| 内容完整 | PDF 中属于该题的内容没有遗漏 |
| 结构正确 | 题干/材料/小问/选项/图片/公式/表格关系正确 |
| 内容忠实 | 没有擅自改写、补充、丢弃、错配源内容 |
| 来源可追溯 | 可定位原 PDF 页面与区域，并能判断问题发生在哪一处理阶段 |

这四项是**结果要求**，不指定技术实现。数量一致不等于内容一致，内容一致不等于结构一致。

### 6.2 八项原则

1. 原始 PDF 唯一事实源，不擅自纠正源文件。
2. OCR 双轨信息充分利用：Markdown 表达内容，JSON 表达结构与定位，图片保留真实资源。
3. 源元素身份采用最小机制：**封存 OCR Run 内可唯一定位即可**，不建跨 Run 永久身份体系。
4. Manifest 负责结构与来源关联：LLM 识别关系，确定性机制传递源事实。
5. Adapter 负责确定性传递：不重新识别、不生成、不改写、不静默丢弃。
6. Question Core 保存完整业务内容；外部 Provenance 保存必要来源证据，两者经 Question/Revision 关联。
7. 验证从“数量”升级到“内容、结构、来源”；文件存在只是基础条件，不是正确性证明。
8. 人工校准服务于自动化：有限人工核验用于发现系统性问题，逐步转向自动 Gate 与风险分层。

### 6.3 源元素身份（最小机制）

- 身份上下文：`OCR Run ID → source_document_id → page → element_ref`；只要求在**封存 Run 内**唯一。
- 优先复用 JSONL 原生 `block_id`；`block_order` **不得**宣称跨 Run 稳定；`bbox`/`polygon`/`label`/`content_hash` 是位置与内容证据，不作身份。
- 不建跨 Run 身份继承、不建元素拆分/合并生命周期管理、不建独立元素身份服务。
- 引用失败必须显式 `provenance_missing`，禁止推断补齐（与 R-02 fail-closed 同原则）。

### 6.4 分层职责（一句话）

| 层 | 职责 | 不负责 |
| --- | --- | --- |
| 原始 PDF | 唯一事实源 | 被修正 |
| PaddleOCR | 识别与结构化表达（页/坐标/类型/顺序） | 决定 Question 业务结构 |
| Preprocessing | 语义识别与结构组织（Unit/材料/小问/答案归属） | 创造源事实 |
| Manifest | 结构声明 + 源元素关联 + 缺失/冲突状态 | 作为真实性证明（`resolved` 不算证据） |
| Strict Adapter | 确定性映射并传递来源引用 | 重新识别/切题/生成 |
| Question Core | 完整业务内容 + 块级来源引用 | 存 OCR 原始 JSON / 维护溯源平台 |
| Provenance | 文件级哈希 + Run/版本 + 元素定位 | 建独立数据库 / 记录全部执行细节 |

### 6.5 三层验证

- **L1 完整性**（文件/引用/字段）：基础门槛，不作正确性证明。
- **L2 源数据一致性**（PDF↔JSON↔MD↔Manifest）：**当前最薄弱，优先补强**。
- **L3 Question 保真**（Candidate/Question 的内容、结构、来源引用）。

三个必须区分：

1. **OCR 识别准确性 ≠ 数据传递准确性**：后半段全对也不能证明忠实 PDF。
2. **源数据存在 ≠ 归属正确**：文件存在、哈希正确，仍可能挂错题。
3. **来源可追溯 ≠ 来源正确**：引用齐全也可能引错，最终须回 PDF 区域核对。

### 6.6 禁止清单（防复杂度膨胀）

- 不得假设 OCR JSON 字段，必须实测；不得把 MD 图片引用数、JSON block 数、Manifest 条目数当同一分母。
- 不得把 `resolved: true` 当作文件实际存在的证据。
- 不新增元素身份服务、跨 Run 身份继承、全量 MD↔JSON 双向映射平台、独立 Provenance 数据库。
- 不将 OCR 原始 JSON 全量写入 Question Core；不重写 R-02；不全量重构 Preprocessing/Manifest/Adapter。
- 不改 Question Core Schema、Student API、DeepTutor 业务，除非证据证明现有结构无法表达必要来源关系。
- 不因孤立缺陷扩展为全量历史治理；不把逐题人工审核变成规模化生产的永久门槛。

### 6.7 已知事实基线（2026-11-13 实测，后续判断起点）

- `.ocr_raw.jsonl` 已存在且含元素级结构：`layoutParsingResults[].prunedResult{width,height,layout_det_res,parsing_res_list[block_label,block_id,block_bbox,block_order,block_polygon_points,group_id,block_content]}` + `markdown.images`；现存于 `Preprocessing/runs/qcore_answer_fidelity_02` 与 `runs/qcore_preimport_02`（三卷 385801/491194/333963 B；**字节量相同不等于 SHA256 相同，须实测**）。
- 工作副本 `Ocr-markdown/<年级>/<学科>/` 只有 `.md` + `_imgs/`；JSONL 未纳入正式 Run 产物。
- 化学四组数字属**四个不同层**，不可当同一分母：MD 图片引用 43 / OCR image block 41 / 磁盘 jpg 41 / manifest `image_assets` 45。
- `image_assets` 是 manifest **顶层扁平表**（chem 45 / chn 2 / eng 6）；图片归属由 entry 的 `line_no` 落到 unit 行区间推定，unit 不持有该字段。
- 化学 Q12 有 5 条 asset_ref 在整棵 Preprocessing 树中无文件、在本次 OCR JSONL 中无源元素，manifest 却标 `resolved: true`；**根因待查，取证前禁止归因 LLM 或 OCR**。其中 3 条位于 materials（发布后即学生可见），当前 revision 为 `incomplete/not_ready/unpublished`。
- `qcore_asset_refs` 106 行 = 53 distinct asset × 2（candidate/revision 双绑定）。
- MD 双轨：导入读 R1 封存副本（`scripts_import.py:119`），manifest 生成读 `Ocr-markdown` 工作副本；两轨人工同步、无自动校验。
- `extra_image_blocks` 无代码重建器（声明仅存于 gitignored `runs/`，靠 P0 记录的 SHA256 补偿）。
- 落库身份：`qcore_question_instances.source_document_id = ctx.paper_id`（卷名，`admission.py:158`）；与 `mapper.py:1724/1841` 的 `paper/unit` 复合串（幂等键/attribution）是两条链，不得混用。

### 6.8 实施顺序（三阶段，不得并行扩张）

1. **查清现状 + 最小契约**：只读；不改生产代码、不改数据库。
2. **三份固定 PDF 重跑 + 源元素级验证**：全新隔离库，Run-1 纯自动 / Run-2 含声明覆盖。
3. **按证据最小补强**：每项须有缺陷证据、最小代码范围、测试与独立复核；禁止借机重构。

## 7. 变更记录

| 日期 | 变更 | 依据 |
| --- | --- | --- |
| 2026-11-10 | 确立“原始 PDF 唯一内容事实源”为 P0；U4 改判 `SOURCE_DOCUMENT_INTERNAL_CONFLICT`；新增词表项与判定表 | Owner 会话裁决 |
| 2026-11-13 | 新增 §6：Question 交付四项验收条件、八项原则、源元素身份最小机制、分层职责、L1–L3 验证、禁止清单、已知事实基线、三阶段实施顺序 | Owner 会话裁决（CALIBRATION-01 指导思想同步） |
