# AGENTS.md — AITutors 项目规则

> 项目级长期规则，跨会话、跨 Agent 生效。修改需 Owner 明示。
> 最后更新：2026-11-10（Owner 裁决：原始 PDF 为唯一内容事实源）

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

## 6. 变更记录

| 日期 | 变更 | 依据 |
| --- | --- | --- |
| 2026-11-10 | 确立“原始 PDF 唯一内容事实源”为 P0；U4 改判 `SOURCE_DOCUMENT_INTERNAL_CONFLICT`；新增词表项与判定表 | Owner 会话裁决 |
