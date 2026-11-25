# 题库外题目资产准入设计（UNKNOWN-ASSET-ADMISSION-V1）

- 任务：`EULER-QCORE-SEMANTIC-EXPANSION-01` / Track C
- 性质：**架构与生命周期设计，不进入完整实现**
- 适用：用户拍照 / 文本输入 / 文档输入等“题库外题目”
- 目标：让 LLM 可以参与新题生产，但只有通过统一 Evidence / Validation / Admission 的结果才能获得 QCore 事实身份
- 本轮不改生产 QCore Schema、不改生产数据、不实现 Unknown Solver

---

## 0. 结论先行

1. **LLM 不得直接创建/修改 Question 或 Revision。**
2. LLM 参与生成的题目可以成为 QCore 资产，但必须走完：
   `Candidate → Validation → Admission → Question/Revision`。
3. 未通过 Admission 的一切产物（OCR 观察、ParsedProblem、LLMAnalysis、GeneratedSolution、TeachingScript）都是**会话产物/候选产物**，不是 QCore 事实，不得被下一次会话当作事实来源。
4. **来源证据（Source Evidence）与内容正确性证据（Content Correctness Evidence）必须分开。**
   “LLM 生成了答案” 不等于 “答案已被验证”。
5. 现有契约已经预留了学生上传分支（`StudentUploadSource` / `StudentUploadCandidate`）与 `SourceKind.STUDENT_UPLOAD`，但**没有执行器/准入器使用它**；本轮设计复用这些契约，只提出最小兼容扩展。

---

## 1. 边界与角色

| 角色 | 可以做 | 不可以做 |
| --- | --- | --- |
| 学生端（DeepTutor） | 上传图片/文本、确认候选、提问、查看已发布讲题 | 写 QCore；把会话结果当事实 |
| LLM | 解析题目、生成候选答案/解析、辅助验证、辅助相似度判断 | 授予事实身份；把生成答案标为 official；直接持久化 Question |
| Validation | 确定性校验、独立求解、证据核对、身份判定 | 自行放宽门槛；把“未验证”写成“已验证” |
| Admission | 决定 Candidate 是否成为 Question/Revision；绑定初始状态 | 自动 publish；跳过证据/权限检查 |
| Human Review | 批准、发布、裁决冲突、确认题库外题目是否入公共库 | 用人工结论替代缺失的来源证据 |
| Semantic Retrieval | 返回 Exact / Similar / Unknown | 把 Similar 当 Exact；合并身份 |

---

## 2. 生命周期（总览）

```text
User Input
  → Raw Source
  → OCR
  → ParsedProblem
  → LLMAnalysis
  → GeneratedSolution
  → Candidate
  → Validation
  → Admission
  → Question / Revision
```

两条分支必须共存：

```text
用户拍照 → Unknown → LLM 解析 → 验证 → Admission → QCore
用户拍照 → Unknown → LLM 解析 → 验证失败 → Session 结束 / 人工 Review
```

---

## 3. 每个阶段的数据边界

| 阶段 | 数据是什么 | 谁产生 | 是否持久化 | 后续流程可读 | 事实身份 | 失败处理 |
| --- | --- | --- | --- | --- | --- | --- |
| User Input | 原始上传文件/文本（图片、PDF、粘贴文本） | 用户 | 是（内容寻址对象存储） | 仅本会话 + 审核者 | 否 | 拒绝上传；记录原因；不产生候选 |
| Raw Source | 原始字节 + SHA-256 + MIME + 上传者 + 时间 | 系统 | 是（不可变） | 是（只读） | 否（来源事实，不是题目事实） | 哈希/类型校验失败即终止 |
| OCR | 页面文本、bbox、block、置信度、引擎版本 | OCR 服务 | 是（会话级） | 是（本会话/审核） | 否（观察值） | 可重试；失败不进入解析 |
| ParsedProblem | 题干/材料/选项/小问/题号/结构树 | 解析器 + LLM | 是（会话级） | 是（本会话/审核） | 否 | 结构不完整 → 候选不成立 |
| LLMAnalysis | 题型判断、知识点、结构假设、风险 | LLM | 是（会话级，带模型/版本/时间） | 是（本会话/审核） | 否 | 失败降级为“无分析”，不得伪造 |
| GeneratedSolution | 生成答案、解析、推导步骤、置信度 | LLM / 求解器 | 是（会话级） | 是（本会话/审核） | 否 | 失败 → 无答案候选；不得填“推测答案” |
| Candidate | 结构化候选（内容 + 答案 + 证据 + 来源 + 权限） | Candidate Builder | 是（候选表/会话） | 是（审核/Admission） | 否（候选身份，不是题目身份） | 校验失败 → rejected/held，不写 Question |
| Validation | 校验报告（结构/答案/证据/身份/权限） | 确定性校验器 + 独立求解 | 是（随候选/审核记录） | 是（Admission/复核） | 否 | fail-closed，不得“跳过继续” |
| Admission | 决定：新建 Question / 复用已有 / 拒绝 / 挂起 | Admission | 是（决定 + 理由） | 是（审计） | 是（只有这一步授予事实身份） | 拒绝/挂起；候选保留可追溯 |
| Question / Revision | QCore 正式资产 | Admission 持久化 | 是（生产库） | 是（按可见性） | 是 | 不可变历史；修订产生新 Revision |

> 关键点：**只有 Admission 这一步可以把“候选”翻译成“事实”。** 其他阶段的持久化都只是证据/会话，不构成题目身份。

---

## 4. 与现有代码/契约的映射

### 4.1 已经存在的部分（可直接复用）

| 现有资产 | 位置 | 用途 |
| --- | --- | --- |
| `StudentUploadSource` | `Question Core/question_core/contracts/v1/candidate.py:192` | 学生上传来源：`uploaded_by`、`upload_blob_hash`、`observations`、PII/分发默认保守 |
| `OcrObservation` | 同上 `:173` | OCR 观察值：role/text/confidence/page/bbox/engine |
| `StudentUploadCandidate` | 同上 `:415` | 学生上传候选（内容 + 来源） |
| `CandidateCore` | 同上 `:239` | 通用候选核心：content/answers/evidence/completeness/identity/ingestion/visibility |
| `AnswerBase` | `.../answer.py:113` | 答案证据类别、完整性、attribution、missing_reason、statements |
| `AnswerEvidenceKind` | `.../common.py:224` | 答案证据来源分类（answer_lines / table_row / inline / absent） |
| `SourceKind` | `.../common.py:100` | 来源类型：`STUDENT_UPLOAD` / `OCR_OUTPUT` / `HUMAN_REVIEW` / `DERIVED` |
| `Admission` | `Question Core/strict_adapter/admission.py:50` | 当前准入：内容审计 → 契约校验 → 初始状态绑定；**不自动批准/发布** |
| `QuestionRow.embedding_ref` | `.../persistence/models.py:96` | 已预留的 embedding 引用列（当前未使用） |
| `identity_fingerprint` | `QuestionRow` / `QuestionIdentity` | 现有身份指纹；用于重复检测的确定性辅助 |
| `QuestionInstance` | `.../models.py:144` | 同一题在不同试卷中的出现（source_document_id/paper_segment_id/printed_number） |
| `EvidenceRecord` / `EvidenceConflict` | `.../models.py:252,291` | 来源证据与冲突留痕 |
| `Revision` 不可变 + `state_history` | `.../models.py:105,194` | 修订历史与状态快照 |

### 4.2 目前缺失的部分

1. **没有 Student Upload 执行器**：`StudentUploadCandidate` 只被测试和 golden sample 使用；`mapper.py` / `generic_executor.py` 只处理 `PreprocessingCandidate`。
2. **Admission 不区分来源类型**：它只接受 `UnitMapping`（Preprocessing 映射结果），没有“题库外候选”的验证/准入入口。
3. **没有答案可信度语义**：`AnswerEvidenceKind` 说明“答案从哪来”，但没有说明“答案是否被验证、由谁验证、验证方法是什么”。
4. **没有题目关系表**：没有 `variant` / `similar` / `exact_duplicate` 的持久关系；`identity_fingerprint` 只能做确定性指纹。
5. **没有会话产物存储契约**：当前没有“上传会话/候选草稿”的正式表；不能把会话结果混进 QCore。
6. **`embedding_ref` 没有使用契约**：谁写、写什么格式、何时失效都未定义。

---

## 5. 来源类型、答案来源、验证状态、发布状态必须分开

四个维度**不得合并**：

| 维度 | 取值（建议） | 说明 |
| --- | --- | --- |
| 来源类型 `source_type` | `preprocessing` / `student_upload` / `human_authored` / `derived` | 题目从哪来 |
| 答案来源 `answer_source` | `official` / `verified_derivation` / `human_verified` / `llm_generated` / `pending_verification` / `rejected` | 答案是谁给的 |
| 验证状态 `verification_status` | `unverified` / `machine_checked` / `independently_solved` / `human_confirmed` / `failed` | 答案被怎么验证 |
| 发布状态 `publication_state` | `unpublished` / `published` / `withdrawn` | 学生是否可见 |

约束：

- `answer_source=llm_generated` 时，`verification_status` 不得是 `human_confirmed`，除非有独立人工记录。
- `verification_status=unverified` 的答案不得进入 `published`。
- `answer_source=official` 只能由**源文件明确给出官方答案**的路径产生；LLM 生成不得标 official。
- `student_upload` 默认 `owner_scope=student`、`pii_status=suspected`、`distribution_policy=no_redistribution`（现有契约已强制）。

---

## 6. 两类证据

### 6.1 Source Evidence（来源证据）

回答：**系统实际收到的题目是什么？**

必须包含：

- 原始文件（图片/PDF/文本）及其 SHA-256；
- 上传者、时间、MIME、大小；
- OCR 引擎/版本/参数/时间；
- OCR 观察值（role/text/confidence/page/bbox）；
- 源定位（page/region/block id）；
- 若来自 PDF：source_document_id、页码、版面块。

存储：内容寻址对象存储 + `EvidenceRecord(role=stem/option/material/answer, source_kind=student_upload/ocr_output)`。
要求：**不可变**；同一上传多次 OCR 产生多个 Run，不覆盖旧 Run。

### 6.2 Content Correctness Evidence（内容正确性证据）

回答：**生成的题目、答案、解析为什么可信？**

可以包括：

- 官方答案（源文件明确给出）；
- 可验证推导（符号/数值/量纲/边界检查）；
- 独立求解（第二次独立方法/工具）；
- 规则校验（题型-答案类型一致性、选项数量、填空槽位）；
- 多路径一致性（不同方法得到同一答案）；
- 人工确认（明确记录 who/when/how）。

禁止：

- 把“LLM 自己生成了答案”当作“答案已经被验证”；
- 把“多个 LLM 说一样”当作独立验证（除非确实使用了独立方法/工具）；
- 把“看起来合理”当作证据。

---

## 7. 题目身份：Exact / Similar / Variant / Related

| 关系 | 判定 | 处置 |
| --- | --- | --- |
| Exact Identity | 同一道题（题干/选项/小问/答案实质一致） | **不得重复创建 Question**；复用已有 Question，新增 Instance/Revision（按来源与修订策略） |
| Variant | 同一母题的结构/数值/设问变式 | 允许成为新的 Question；建立 `variant_of` 关系；不得覆盖原题 |
| Similar | 题型/知识点/结构相近但不是同题 | 只建立检索关系；**不得**合并、覆盖、冒充原题 |
| Related | 同一材料/同一组题/同一知识点 | 只做关系标签；不影响身份 |

原则：

> **相似不等于相同，变式不等于重复。**

身份判定顺序（Admission 前必须完成）：

```text
1. 规范化文本 + identity_fingerprint  → 命中 Exact？
2. 语义检索 Top-K + 结构化对齐        → 是否 Variant？
3. 语义相似但非同一题                → Similar（仅关系）
4. 均不命中                          → 新 Question
```

- Exact 命中：**不创建新 Question**；把本次来源作为新的 Instance/Evidence 绑定到已有 Question；若内容有实质差异，进入 Revision 流程（需人工确认）。
- Variant：创建新 Question + `variant_of` 关系，保留母题引用。
- Similar：只写入关系/检索索引，不写题目身份。
- 任何身份判定失败/歧义：**fail-closed**，不合并、不新建，转人工。

---

## 8. Admission Gates（题库外路径）

| Gate | 检查 | Fail 处置 |
| --- | --- | --- |
| G0 Permission | `owner_scope=student`；PII 状态；分发策略；不得声称 public_bank | 拒绝；不产生候选 |
| G1 Source Integrity | 原始文件哈希存在、字节可读、OCR Run 封存 | 拒绝；保留原始上传 |
| G2 Structure | 题干/材料/选项/小问/题号结构完整；无跨题污染 | held（可重试解析） |
| G3 Identity | Exact / Variant / Similar / New 判定完成且有证据 | 歧义即 held；禁止猜测合并 |
| G4 Answer | 答案来源与验证状态合法；生成答案不得标 official；完整性与题型一致 | rejected/held；不得发布 |
| G5 Explanation | 解析中每个事实可回溯到来源或可验证推导；不得引入来源外条件 | rejected/held |
| G6 Evidence | 来源证据 + 正确性证据齐全；引用可解析；冲突显式保留 | held |
| G7 Review | 人工批准；发布是独立动作 | 保持 unpublished |

准入结果只允许：

- `admitted_new`（新 Question/Revision，初始 `pending_review`/`unpublished`）；
- `admitted_existing`（绑定已有 Question，新增 Instance/Revision）；
- `held`（证据不足/结构歧义，保留候选）；
- `rejected`（权限/来源/内容不可接受）。

**Admission 不自动 publish。** 与现有 `admission.py` 的“Admission 只绑定初始状态”一致。

---

## 9. 什么情况下 LLM 输出只能停留在 Session

必须同时满足以下条件，才允许离开 Session 进入 Candidate/Admission：

1. 原始来源已保存且哈希可核；
2. OCR 已完成且观察值可定位；
3. 题目结构已解析（题干/材料/选项/小问/答案归属明确）；
4. 身份判定完成（Exact/Variant/Similar/New）；
5. 答案有来源与验证状态（生成答案必须有正确性证据或明确 `pending_verification`）；
6. 解析中的事实可回溯；
7. 权限/PII/分发策略已确定；
8. 通过 G0–G7。

任一不满足：

- 只能作为 Session 产物保存（带 TTL），供本次讲题/追问使用；
- 不得写入 QCore；
- 不得在下次会话中被自动当作事实；
- 不得进入公共题库；
- 需要时可以转人工 Review，但 Review 也必须补证据，而不是“人工说可以就可以”。

---

## 10. 什么情况下 LLM 参与生成的题目可以成为 QCore 资产

满足以下全部条件：

1. 来源为 `student_upload` / `human_authored` / `derived` 之一，来源事实完整；
2. 结构解析通过（G2）；
3. 身份判定为 New 或 Variant（Exact 走复用，不新建）；
4. 答案来源明确，验证状态达到门槛：
   - 选择题/填空题：至少 `machine_checked` + 规则校验；进入公共库前需 `independently_solved` 或 `human_confirmed`；
   - 解答题/作文：至少 `human_confirmed`（当前阶段）；
5. 解析每个事实可回溯或可验证；
6. 来源证据与正确性证据齐全；
7. 通过 G0–G7；
8. 人工批准（review_state=approved）后才允许 `published`。

满足后：**允许正式创建 QCore Question/Revision 资产。** 这是本设计的核心结论。

---

## 11. 最小兼容扩展建议（不本轮实施）

> 原则：优先使用现有 JSONB payload / 可选字段，避免大范围 Schema 重构；任何 Schema 变更交 Owner + MIMO 复核。

### 11.1 合同层（可先加可选字段）

在 `AnswerBase` 增加可选 `answer_provenance`：

```json
{
  "answer_source": "llm_generated",
  "verification_status": "machine_checked",
  "generated_by": {"provider": "deepseek", "model": "deepseek-flash", "version": "..."},
  "verification_methods": ["rule_check", "independent_solver"],
  "verified_by": null,
  "verified_at": null,
  "confidence": 0.72
}
```

- 默认 `None`，旧数据不受影响；
- `PreprocessingCandidate` 不强制该字段；
- `StudentUploadCandidate` 在 Admission 前必须提供；
- 禁止用 `answer_source=official` 覆盖源文件声明。

### 11.2 候选层

在 `CandidateCore` 增加可选 `validation`：

```json
{
  "gates": {"G0": "pass", "G1": "pass", "G2": "pass", "G3": "held", "...": "..."},
  "identity_decision": {"relation": "variant", "target_question_id": "...", "evidence": "..."},
  "issues": [...],
  "validated_at": "..."
}
```

同样默认 `None`，不破坏旧候选。

### 11.3 持久层（下一阶段迁移）

新增表（建议）：

| 表 | 关键列 | 用途 |
| --- | --- | --- |
| `qcore_question_relations` | `relation_id`, `source_question_id`, `target_question_id`, `relation_type`(`exact_duplicate`/`variant_of`/`similar`/`related`), `score`, `evidence`, `created_by`, `created_at` | 变式/相似/重复关系；唯一约束防重复边 |
| `qcore_upload_sessions` | `session_id`, `uploaded_by`, `blob_hash`, `status`, `expires_at`, `created_at` | 会话产物生命周期 |
| `qcore_candidate_validations` | `candidate_id`, `gate`, `status`, `detail`, `created_at` | 校验证据（也可放 candidate payload） |

**不建议本轮直接改生产 Schema。** 先用可选 payload 字段承载，等 MIMO 复核与 Owner 裁决后再迁移。

### 11.4 `embedding_ref` 契约

- 写入者：Semantic Index Builder（离线）；
- 内容：内容寻址的向量文件引用 + 模型/版本/维度/归一化方式；
- 失效：题目内容变更/模型变更/索引重建；
- QCore 只存引用，不存大向量；
- 无引用不影响读取，检索层可回退到文本索引。

---

## 12. 与现有 QCore 状态的兼容性

| 现状 | 影响 | 结论 |
| --- | --- | --- |
| `StudentUploadCandidate` 已存在但无执行器 | 设计可复用契约 | 下一阶段新增 `student_upload_executor`，不改现有 Preprocessing 路径 |
| Admission 只接受 `UnitMapping` | 题库外路径无入口 | 新增独立 admission 入口，复用 Gate/State 逻辑，不重写 Preprocessing Admission |
| `AnswerEvidenceKind` 无验证语义 | 无法表达“LLM 生成但已验证” | 用可选 `answer_provenance` 扩展，不替换现有枚举 |
| 无关系表 | 无法持久 Variant/Similar | 新增关系表，不改 Question/Revision 主表 |
| 生产库已 169 published | 不能被本轮实验污染 | 本轮所有实验在隔离库；生产零写入 |
| `identity_fingerprint` 已有 | 可做确定性 Exact 辅助 | 与语义 Top-K 组合，不单独决定身份 |

---

## 13. 工作示例

### 13.1 用户拍照 → Exact（已有题）

1. 上传图片，保存 hash；
2. OCR，得到观察值；
3. Semantic Retrieval 返回 Exact（高置信 + margin + 数字/结构一致）；
4. 不创建新 Question；
5. 绑定已有 Question/Revision，进入讲题；
6. 会话结束，不写 QCore 新资产。

### 13.2 用户拍照 → Unknown → 生成候选 → 验证失败

1. 上传图片；
2. OCR / 解析 / LLM 生成答案；
3. 身份判定为 New；
4. G4 失败（生成答案无法独立验证 / 解析含来源外条件）；
5. 结果 `rejected` 或 `held`；
6. 会话产物保留 TTL；不写 QCore；
7. 学生本次仍可看到“无法可靠讲题”，不得把生成答案当官方。

### 13.3 用户拍照 → Unknown → 生成候选 → Admission → QCore

1–3 同上；
4. G4 通过（如选择题：规则校验 + 独立求解一致）；
5. G5 解析可回溯；
6. G6 来源证据/正确性证据齐全；
7. G7 人工批准；
8. Admission 创建 Question/Revision，初始 `pending_review`/`unpublished`；
9. 人工 `approve` + `publish` 后学生可见；
10. 若与已有题为 Variant，建立 `variant_of` 关系，不覆盖原题。

---

## 14. 下一阶段实现验收（建议）

1. 新增 `student_upload_executor`，但**默认关闭**，不接生产流量；
2. 单元测试覆盖：Exact 不新建、Variant 建关系、Similar 不冒充、Unknown fail-closed；
3. 答案来源/验证状态不可伪造（LLM 输出无法写 `official`/`human_confirmed`）；
4. 会话产物 TTL 与清理；
5. 权限：student upload 不得 `public_bank`；
6. 生产 QCore 零写入；
7. 通过 MIMO 独立复核 + Owner 裁决后才可上线。

---

## 15. 明确不做（本轮与下一阶段边界）

- 不做完整 Unknown Solver 自动入库生产线；
- 不做自动发布；
- 不做自动合并重复题；
- 不做跨题库大规模迁移；
- 不做评分/Rubric；
- 不做知识图谱/Ontology；
- 不改生产 QCore Schema（本轮）。

---

## 16. 待 Owner / MIMO 裁决的问题

1. 题库外题目进入**公共题库**的批准人是谁？是否需要双人复核？
2. `student_upload` 的所有权/授权：学生是否有权把题目贡献给公共库？需要什么明示同意？
3. 解答题/作文的“可验证”标准：当前建议至少 `human_confirmed`，是否接受其他证据？
4. 变式题的边界：数值变化/设问变化/材料变化分别算 Variant 还是 Similar？需要学科规则。
5. 重复题判定：Exact 是否允许跨来源自动绑定 Instance，还是必须人工确认？
6. `answer_provenance` 是放 `AnswerBase` 还是独立表？本轮建议先放可选 payload。
