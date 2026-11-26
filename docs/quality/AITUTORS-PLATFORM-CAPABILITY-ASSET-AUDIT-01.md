# AITUTORS-PLATFORM-CAPABILITY-ASSET-AUDIT-01

- 日期：2026-11-26
- 性质：只读盘点（未改代码、未写 QCore、未启动新服务）
- 范围：P0 DeepTutor 原生能力 + P1 QCore 现有 NLP 资产
- 相关外部资产：`D:\Project\NLP\six-subject-kg`、`D:\Project\Mytutors`
- 工作包 A 事实核查：[AITUTORS-WORK-PACKAGE-A-01.md](AITUTORS-WORK-PACKAGE-A-01.md)

---

## 0. 结论先行

1. **不重建聊天、附件、文件解析、LLM 调用。** DeepTutor 已有聊天/附件/vision/流式/会话持久化；缺的是 QCore 优先路由、LLM 兜底和异步入库，不是基础聊天设施。
2. **QCore 当前是内容保真库，不是知识库。** 没有知识点、技能、难度、先修/题目关系字段；`subject/grade` 在 candidate.source 中存在且已填充（例外不是数据缺失），但 Revision/导出层没有直接携带，导出器仍用 `source_document_id` 推导学科。
3. **外部 `six-subject-kg` 是候选资产，不是 QCore 已接入事实。** 4,829 节点/4,584 边、57 条题目映射；许可（mmlong PolyForm NC）和映射可信度都未解决。
4. **必须先把 QCore 的确定性字段和导出事实补起来，再做 LLM/NLP。** 先修正 candidate.source → catalog/export 的 subject/grade 传递，再建立 question type/capability、paper/curriculum 轴；知识点映射放在后面。
5. **个人学习模型可复用 DeepTutor 的 learning/mastery/error 基础设施。** 它已有 `KnowledgePoint`、`QuizAttempt`、`ErrorRecord`、掌握度与判分逻辑；但它是 per-mastery-path，不是 QCore 全局知识模型。
6. **发布状态已锁定：** 当前配置数据源 `qcore_six_subject_accept_01` 的 `qcore_state_history` 最新 snapshot 为 **169 published / 18 withdrawn / 6 unpublished**；`qcore_revisions.publication_state` 全部 `unpublished` 只是创建时投影。169 published 与 Compiler catalog/bundles **169/169 身份一致**，不是 stale。

---

## 1. DeepTutor 原生能力盘点

### 1.1 可直接复用

| 能力 | 证据 | 结论 |
|---|---|---|
| 聊天附件选择 | `web/lib/doc-attachments.ts:27,35-157,213-217,237-245` | 可复用；图片 + PDF/DOCX/XLSX/PPTX + 文本类 |
| 附件限额 | `web/lib/attachment-limits.ts:28-31`; `deeptutor/utils/document_extractor.py:71-74` | 20MB/文件、25MB/轮、16 图/12MB |
| 附件持久化 | `deeptutor/core/turn_request.py:55-63`; `services/session/turns/executor.py:322-374`; `services/storage/attachment_store.py` | 可复用；base64 over WS + AttachmentStore |
| PDF/DOCX/XLSX/PPTX 提取 | `deeptutor/utils/document_extractor.py:262-598,1302+` | 可复用；无 legacy `.doc/.xls/.ppt` |
| 可选 parsing/OCR 引擎 | `services/parsing/service.py:78-133`; engines 目录 | 可复用，但默认 `text_only`；OCR 需安装/选择/开启 |
| 图片送 vision model | `services/llm/multimodal.py:133-189,366-377`; `executor.py:487-498` | 可复用；图片不自动 OCR |
| LLM provider | `services/provider_registry.py:208`; `data/user/settings/model_catalog.json` | 可复用 |
| 流式输出 | `services/llm/factory.py:529-632`; `runtime/stream_bus.py` | 可复用 |
| turn/session/message | `services/session/sqlite_store.py:282-365`; `api/routers/unified_ws.py:44` | 主集成点 |
| chat/ask_questions/deep_solve | `agents/chat/capability.py:12`; capabilities | 均接收 `UnifiedContext.attachments` |
| 学习/掌握/错题 | `deeptutor/learning/models.py:25-180`; `mastery.py`; `grading.py` | 已有个人学习模型基础，可扩展 |

### 1.2 确认的缺口

1. **legacy `.doc/.xls/.ppt` 不支持**（composer、extractor、parser 全无）。
2. 聊天 PDF **不会自动 OCR**；只有全局选择 OCR 引擎才可能解析，扫描件没有 per-request OCR fallback。
3. 图片附件**不 OCR**，只送 vision model；模型不支持视觉时会被剥离。
4. 没有聊天附件 multipart 上传端点；base64 over WS，服务端校验弱。
5. **没有通用后台任务/队列 API**；只有 KB indexing journal + SSE + cancel，以及 task board。
6. 聊天与 QCore teach **没有共享 question identity**；photo flow 不创建 DeepTutor session/message/attachment。
7. 普通 chat/deep_solve 没有强制 citation/provenance 契约；只有 deep_research 有 CitationManager。
8. QCore/OCR/lesson 端点 localhost 固定 + token in `.env`，没有统一 readiness。

---

## 2. QCore 现有 NLP 资产

### 2.1 有什么

| 资产 | 状态 | 证据 |
|---|---|---|
| Question/Revision/Instance | 有 | `Question Core/.../contracts/v1/question.py`, `persistence/models.py:60` |
| 题干/材料/选项/答案/解析 | 有 | `content.py`, `answer.py` |
| 复合题/子题 | 有 | `content.py:241` |
| 图片/表格/公式 | 有 | 1166 语料统计；部分 unresolved assets |
| question_type | 有，10 类在用 | `common.py:137` |
| BM25 索引 | 有，已审计 | `semantic/retrieval.py:162`；stage1 报告 |
| dense embeddings | 有实验索引 | `index_final` 1166 / `index_prod` 175 |
| StudentUploadCandidate | **schema 有，未实现** | `schema/v1/question_core.schema.json` |
| DeepTutor learning/mastery/error | 原生有 | `deeptutor/learning/models.py` |

### 2.2 没有什么

| 缺口 | 状态 | 影响 |
|---|---|---|
| knowledge point / skill / taxonomy | 无表/无字段 | 无法做全局知识模型 |
| difficulty | 无 | 无法难度分层 |
| prerequisite / question relations | 无持久关系表 | 无法做学习路径 |
| subject/grade | candidate.source **已填充**；Revision/导出层未直接携带 | 导出器用 `source_document_id` 推导，需改为使用 candidate.source 权威值 |
| student attempt/wrong question | QCore 无 | 个人模型只能先靠 DeepTutor learning |
| dual-source wrong question | 无 | 教师批改/自报/系统判错未统一 |
| publication 真相 | state_history 最新：169 published / 18 withdrawn / 6 unpublished；列级 0 是创建时投影 | 已锁定，不再是待核查矛盾 |

### 2.3 关键数据问题

- `qcore_candidates.payload.source.subject/grade` **存在且已填充**；子代理最初查 `payload->'core'->'source'`，路径错误，结论不成立。
- Revision 本身不含 subject/grade；`semantic/export.py` 与 `qcore_source.py` 用 `source_document_id` 关键词推导学科，未使用 candidate.source。
- 这不是“Adapter 丢失”，而是 **导出/索引层忽略了权威 source 字段**；修复点是 catalog/export 的读取，不是回填 207 条数据。
- 上游 Preprocessing manifest 也带 grade/subject，可作为交叉校验。
- `qcore_revisions.publication_state` 是创建时投影，全部 `unpublished`；`qcore_state_history` 才是当前权威。
- 最新 snapshot：published 169、withdrawn 18、unpublished 6；18 withdrawn 均有更新 revision 的 published 替代。
- 169 published 清单 SHA256：`9a852ddc1d9849fbd9acf6d6194975363669637c384c5947c7ce6c01960be02f`。
- Compiler catalog/bundle 169 与 state_history 169 逐身份一致；`index_prod` 175 包含 6 unpublished，不是 published-only 索引。

---

## 3. 外部知识图谱资产（six-subject-kg）

已确认存在：

```text
D:\Project\NLP\six-subject-kg
  4,829 nodes / 4,584 edges / 0 dangling
  4,182 mmlong + 18 goralcao gap + 629 Mytutors
  57 question→node mappings / 36 questions
```

边界：

- **不是 QCore 已接入事实**；QCore 当前没有 knowledge 字段；
- `NLP` 的 629 个 Mytutors 节点实际上是 Mytutors `taxonomy_nodes` 926 的子集；L4 树和 57 条映射不是第二套独立知识树，而是 Mytutors 发布版的派生快照；真正新增的是 mmlong/goralcao 的外部合并层。
- 57 条映射与当前 `qcore_g4_final_01` 的 207 个 question_id **重叠为 0**；不能按“已有 57 条映射”计入当前 QCore 知识能力。
- 42 条 LLM 映射需人工复核；
- mmlong 许可为 README 的 PolyForm Noncommercial + 无 LICENSE 文件，商用/对外发布前必须确认；
- `aligned_to` 292 条是候选对齐，不是 verified 映射。

结论（Owner 2026-11-26 裁决）：**`six-subject-kg` 的 4,829 节点就是规范底座**；Mytutors 926/629 是其中一个来源层，不是替代规范树。映射由**统一 LLM** 生成，不做人工映射审查；节点后续可继续丰富。

这意味着：

- 4,829 节点不是候选层，而是当前 NLP 知识层的正式底座；
- 57 条旧映射只作为历史样例，必须针对当前 QCore 全量重跑；
- LLM 输出必须统一 schema、统一 prompt、统一模型版本；
- 人工不逐条审查，但自动校验、版本、证据、置信度、许可是独立门槛；
- 许可问题不是“人工审查”，是使用场景合规 gate，不能混为一谈。

---

## 4. 双层模型的可复用边界

### 4.1 全局层（学科/题目能力）

- 应由 QCore 的真实题目 + 确定性字段开始：
  1. 修正 catalog/export 使用 candidate.source 的 subject/grade；
  2. question_type + content bits + composite depth + answer form；
  3. paper/curriculum metadata；
  4. duplicate/variant grouping；
  5. 再引入外部 KG 候选映射；
  6. 最后 LLM 标签 + 自动一致性/覆盖率 Gold Set（不做逐条人工审查）。
- **不要**先导入 4,829 节点再反推题目；先有题目身份和确定性轴。

### 4.1.1 错题双来源的实际落点

| 来源 | 现有能力 | 缺口 |
|---|---|---|
| 教师批改错题 | DeepTutor learning 只有 `source_type` 概念；QCore 无错题表 | 无 teacher-graded 来源、无批改证据字段 |
| 学生自报错题 | QCore `StudentUploadCandidate` schema 有上传来源/PII/分发策略 | **无实现路径**；DeepTutor 无 self_reported 来源 |
| 系统判错 | DeepTutor `QuizAttempt` / `ErrorRecord` / `grade_answer` 已有 | 未绑定 QCore revision 之外的全局知识节点 |
| 统一错题记录 | 无统一表 | 需统一 source/evidence/question identity，且不把一次错误当薄弱结论 |

这一块应复用 DeepTutor learning，不要把 QCore 改成学习记录库。

### 4.2 个体层（学生学习）

- DeepTutor 已有 `KnowledgePoint`、`QuizAttempt`、`ErrorRecord`、`LearningEvidence`、mastery/recency 权重、grade_answer/classify_error。
- 可复用为个人学习模型基础；
- 需要扩展：
  - source_type：qcore / student_upload / teacher_graded / self_reported / system_graded；
  - QCore revision_id + global node id 映射；
  - 统一外部错题与系统错题；
  - 不把一次错误直接等同于知识薄弱。

---

## 5. 推荐实施顺序（按 Owner 战略调整）

| 优先级 | 工作 | 说明 |
|---|---|---|
| P0-0 | **发布状态已锁定** | state_history latest：169 published / 18 withdrawn / 6 unpublished；列级 0 是创建时投影，不是重置 |
| P0-1 | 修正 catalog/export 的 subject/grade 来源 | candidate.source 已有权威值；导出器不应再用 `source_document_id` 推导；不是 207 条回填 |
| P0-2 | 文件入口补齐 | `.doc` 转换/拒绝策略；扫描 PDF/图片 OCR 选择；服务端格式校验 |
| P1 | QCore 确定性能力轴 | type/content/composite/paper/duplicate；全部可从现有字段得到 |
| P1.5 | 外部 KG 评估 | 许可、57 映射复核、292 对齐候选；不直接生产 |
| P2 | 统一入口 | DeepTutor chat composer + QCore-first route + LLM fallback；不新建聊天 |
| P3 | 异步入库 | 复用 KB indexing journal/SSE；StudentUploadCandidate；Admission 后才写 QCore |
| P4 | 学习数据 | 外部错题/系统错题双来源；复用 DeepTutor learning |
| P5 | 个体模型 | global node ↔ QCore revision ↔ attempt/error |
| P6 | 个性化教学 | QCore 选题/教学脚本 |

---

## 6. 统一入口的最小集成点

```text
DeepTutor ChatComposer / /ws start_turn
  → 附件 base64 + parser/extractor / vision
  → 目标题定位（沿用 QCoreTeach/TSC 结构恢复）
  → QCore published search
      命中：QCore 答案/解析/TeachingScript
      未命中：chat/deep_solve LLM 回答 + “AI 生成”标签
  → 用户拿到结果
  → 异步：StudentUploadCandidate + 源文件/OCR/LLM 草稿
  → Preprocessing/Admission
```

不要新建：

- 第二套聊天系统；
- 第二套附件上传；
- 第二套 LLM provider 调用；
- 第二套通用队列。

---

## 7. 未验证 / 需 Owner 决策

未验证：

- 当前实际安装/启用哪个 parsing/OCR engine；
- 当前 LLM 是否真的接受图片；
- QCore published 真相已锁定为 169；列级 0 是创建时投影，不需要解释为 reset；
- `six-subject-kg` 57 映射与当前 QCore 的重叠（审计文档声称 0，未重跑）；
- 外部 KG 许可是否允许目标使用场景。

需 Owner 决策：

1. published 真相与统一入口的发布门禁；
2. `.doc` 是否必须支持，还是转换后支持；
3. mmlong 许可与商用边界；
4. 已裁决：以 `six-subject-kg` 4,829 节点为规范底座，LLM 统一映射，不做人工逐条审查；
5. 是否允许将外部 KG 作为正式底座（Owner 已裁决：允许；许可风险另行处理）；
6. 统一入口是否先做 DeepTutor 内最小路由，不新开页面。

---

## 8. 结论

P0/P1 盘点完成。最重要的三个判断：

1. **DeepTutor 原生能力足够支撑入口，不要重复造。**
2. **QCore 当前没有全局 NLP 知识模型；先补确定性字段和发布状态。**
3. **外部 six-subject-kg 值得保留为候选资产，但许可、映射和语义契约未解决前不能进生产。**

下一步不应直接开发聊天页面，而应先处理 P0-0/P0-1/P0-2，再决定 P1 的知识图谱导入边界。
