# AITUTORS-QCORE-DEEPTUTOR-KNOWLEDGE-CONTRACT-01

- 日期：2026-11-27
- 状态：**CONTRACT DESIGN COMPLETE / IMPLEMENTATION NOT STARTED**
- 性质：QCore 全局知识模型 ↔ DeepTutor 个体学习模型的语义契约
- 修改代码：0
- 修改数据库：0
- 启动映射/生产：0

---

## 1. 最终结论

```text
QCore = 全局题目事实 + 规范知识节点 + 题目知识映射
DeepTutor = 学习目标 + 学习路径 + 学习证据 + 掌握度 + SRS
中间层 = 只读、版本化的语义关联与投影
```

不允许：

- 用 QCore node_id 替换 DeepTutor `KnowledgePoint.id`；
- 在 QCore 再建 Mastery Path / 证据 / 复习队列；
- 把 RAG 图当作规范学科知识体系；
- 把 QCore qid 直接塞进原生 `notebook_entries.question_id`；
- 无版本地把旧学习证据解释成新映射结果。

正式契约版本：

```text
qcore-dt-knowledge-contract/v1
```

---

## 2. 实体边界

### 2.1 QCore 实体

| 实体 | 身份 | 所有者 | 说明 |
|---|---|---|---|
| `KnowledgeNode` | `node_id`（现有 `my:` / `mml:` / `goralcao:`） | QCore | 规范知识节点，不因学生学习变化 |
| `Question` | `question_id` | QCore | 题目身份，跨 Revision 稳定 |
| `Revision` | `revision_id` | QCore | 题目内容版本；发布状态由 QCore 权威 |
| `QuestionNodeMapping` | `(question_id, revision_id, mapping_version, node_id, role)` | QCore 派生层 | 题目考查的知识关系 |
| `MappingVersion` | `mapping_version`（不可变） | QCore 派生层 | 候选/模型/规则的可追溯快照 |

### 2.2 DeepTutor 实体

| 实体 | 身份 | 所有者 | 说明 |
|---|---|---|---|
| `MasteryPath` | `path_id` | DeepTutor | 学习路径/主题聚合 |
| `LearningModule` | `(path_id, module_id)` | DeepTutor | 路径内模块 |
| `KnowledgePoint` | `(path_id, kp_id)` | DeepTutor | **局部学习目标**，不是全局节点 |
| `QuizAttempt` | `(path_id, attempt_id)` | DeepTutor | 作答记录，含 qid/rid/source_type |
| `LearningEvidence` | `evidence_id` | DeepTutor | 复习/评估证据 |
| `ErrorRecord` | `error_id` | DeepTutor | 错题记录 |
| `RepetitionState` | `(path_id, kp_id)` 或 qcore 键 | DeepTutor | 复习调度状态 |
| `Mastery` | `(path_id, kp_id)` | DeepTutor | 局部掌握度 |

### 2.3 关联层实体

| 实体 | 身份 | 所有者 |
|---|---|---|
| `ObjectiveNodeLink` | `(path_id, kp_id, canonical_node_id, mapping_version)` | 集成层 |
| `EvidenceMappingBinding` | `evidence_id` | 集成层（只读派生） |
| `CanonicalMasteryProjection` | `(learner_id, canonical_node_id, mapping_version, as_of)` | 集成层（只读投影） |
| `ErrorEvidenceProjection` | `error_event_id` | 集成层（只读投影） |

关联层不复制题目内容，不复制学习路径，不拥有掌握度事实。

---

## 3. 身份契约

### 3.1 Canonical Node ID

```text
canonical_node_id = QCore KnowledgeNode.node_id
```

- 保留现有命名空间，不重新编码；
- 必须存在于 QCore 知识节点快照；
- 不创建新节点；
- QCore 节点版本由 `node_catalog_version` 标识。

### 3.2 Question / Revision

```text
QuestionRef = (question_id, revision_id)
```

- `question_id` 是跨 Revision 的题目身份；
- `revision_id` 是内容/发布版本；
- 映射以 `QuestionRef` 为键，不以题面文本为键；
- 历史证据保留作答时 `revision_id`。

### 3.3 DeepTutor 局部 ID

```text
ObjectiveRef = (path_id, kp_id)
```

- `kp_id` 永远不是 QCore node_id；
- `Path` 内部先修关系继续使用 `kp_id`；
- 一个 `kp_id` 可链接多个 `canonical_node_id`；
- 一个 `canonical_node_id` 可被多个 `kp_id` 引用。

### 3.4 多对多

禁止在 `KnowledgePoint` 上只加一个 `canonical_node_id` 字段作为唯一关系。

正式关系：

```text
ObjectiveNodeLink
  path_id
  kp_id
  canonical_node_id
  relation: primary | secondary | supporting | prerequisite
  mapping_version
  confidence
  source: qcore_mapping | human_curated | imported
```

即使未来在 `KnowledgePoint` 上增加缓存字段，也只作 denormalized cache，权威仍是 link 表。

---

## 4. QuestionNodeMapping 合约

```text
QuestionNodeMapping
  question_id
  revision_id
  mapping_version
  node_id
  role: primary | secondary | supporting
  parent_primary_node_id   # secondary 专用
  confidence
  evidence_quote
  source_run_id
  created_at
```

约束：

- `node_id` 必须存在；
- `role=primary` 必须来自 PrimaryCategoryIndex；
- `role=secondary` 必须挂到一个 primary；
- `role=supporting` 必须有 role/reason；
- 同一 `(question_id, revision_id, mapping_version, node_id, role)` 唯一；
- `mapping_version` 不可变，不可原地修改；
- 新映射必须生成新版本。

---

## 5. 学习证据合约

DeepTutor 现有字段可直接承载题目身份：

```text
QuizAttempt:
  question_id
  revision_id
  source_type = qcore | notebook | ...
  knowledge_point_id    # 局部目标；可为空
  module_id

LearningEvidence:
  evidence_id
  question_id
  revision_id
  source_type
  knowledge_point_id
  result
  quality
```

### 5.1 证据到知识节点的绑定

新增只读绑定：

```text
EvidenceMappingBinding
  evidence_id
  question_id
  revision_id
  mapping_version
  canonical_node_ids[]
  role_by_node
  bound_at
```

规则：

- `mapping_version` 取作答/复习当时生效的版本；
- 旧证据永远保留旧版本，不因新映射重写；
- 若作答时无映射，记录 `mapping_version=null`，不推断；
- 绑定是派生数据，不写回 `LearningEvidence`；
- 同一 evidence 可关联多个 canonical nodes（多标签），但只算一次 attempt。

### 5.2 去重键

```text
dedupe_key =
  source_type
  + question_id
  + revision_id
  + attempt_id
```

- QCore 作答的 `attempt_id` 使用 `request_id`；
- 原生题库使用其 `attempt_id` / entry event；
- 同一学生、同一题、同一 revision、同一次提交只计一次；
- 多知识节点映射不会重复计 attempt，只增加节点归属。

---

## 6. 掌握度聚合合约

### 6.1 不复制 Mastery

DeepTutor 的 `mastery_levels` 继续按局部 `KnowledgePoint` 存储，不写 canonical 掌握度。

### 6.2 只读投影

```text
CanonicalMasteryProjection
  learner_id
  canonical_node_id
  mapping_version_set[]
  evidence_count
  correct_count
  partial_count
  incorrect_count
  mastery_score
  as_of
```

计算：

- 复用 DeepTutor `compute_mastery` 的 recency-weight 规则；
- 按 canonical node 聚合来自所有路径的 evidence；
- 每个 evidence 只贡献一次；
- 一条 evidence 映射到多个节点时，每个节点各得到该 evidence，但 attempt 计数不重复；
- `mapping_version` 不同则不混合，除非查询明确指定跨版本策略；
- 无 evidence → `null`，不是 0；
- `ungraded` 不进入正确率/掌握度。

### 6.3 多路径

同一 canonical node 可被多个 Mastery Path 的 `KnowledgePoint` 引用。聚合时：

- 按 canonical node 汇总所有 path evidence；
- 保留 per-path 视图；
- 不把不同 path 的局部 mastery 相加；
- 只在 canonical 层重新计算，不反向覆盖局部值。

---

## 7. 错题与两类来源

| 来源 | 证据入口 | 特征 |
|---|---|---|
| 学生上传外部错题 | `notebook_entries` + `origin_type=external_import` | 非 QCore；无 revision 时为空 |
| DeepTutor 内部练习 | `QuizAttempt` / `ErrorRecord` | `source_type=notebook` |
| QCore Practice | `QcLearningStore` → `QuizAttempt`/`LearningEvidence` | `source_type=qcore`，qid/rid |

统一投影：

```text
ErrorEvidenceProjection
  error_event_id
  origin_type
  source_type
  question_id
  revision_id
  attempt_id
  error_type
  grading_source: system | teacher | self
  mastery_path_id
  knowledge_point_id
  canonical_node_ids[]
  created_at
```

原则：

- 不合并原始表；
- 保留判分来源；
- `ungraded` 不进入错误/掌握度；
- 人工自报与系统判错不能伪装成同一证据。

---

## 8. 版本与历史解释

### 8.1 版本

```text
contract_version
node_catalog_version
mapping_version
prompt_version
model_id / model_version
```

- `mapping_version` 是不变快照；
- 任何映射修订都创建新版本；
- `node_catalog_version` 标识 4,829 节点快照；
- `model_id` 记录实际 provider/model，不仅是 alias。

### 8.2 历史

- 学习证据永远携带作答时 `revision_id` 和映射版本绑定；
- 新映射不能追溯改写旧证据的解释；
- 需要“当前视图”时重新投影，但旧投影必须可复现；
- 题目 revision 变化后，旧 evidence 不自动套用新 revision 映射。

---

## 9. 数据所有权

| 数据 | 所有者 | 可写方 | 可读方 |
|---|---|---|---|
| Question / Revision / 发布状态 | QCore | QCore | DeepTutor / 集成层 |
| KnowledgeNode / 关系 | QCore | QCore | 集成层 |
| QuestionNodeMapping | QCore 派生层 | QCore mapping job | DeepTutor / 集成层 |
| MasteryPath / Module / KP | DeepTutor | DeepTutor | 集成层 |
| QuizAttempt / Evidence / Error | DeepTutor | DeepTutor | 集成层 |
| Mastery / SRS | DeepTutor | DeepTutor | 集成层 |
| ObjectiveNodeLink | 集成层 | 集成层 | QCore 只读 / DT 只读 |
| CanonicalMasteryProjection | 集成层 | 集成层 | DT 只读 |

禁止：

- QCore 写 DeepTutor 学习状态；
- DeepTutor 写 QCore 题目/节点/映射；
- 集成层修改原始证据；
- 任意一侧把另一侧事实复制成第二事实源。

---

## 10. 接口边界

### 10.1 QCore → 集成层

```text
GET /contract/nodes/{node_id}
GET /contract/questions/{question_id}/revisions/{revision_id}/mappings?version=...
GET /contract/mapping-versions/{version}
```

只读；返回 node/ref/mapping；不含学生信息。

### 10.2 DeepTutor → 集成层

```text
GET /contract/learners/{learner_id}/evidence?canonical_node_id=...
GET /contract/learners/{learner_id}/mastery?as_of=...
```

只读投影；不返回题库内容。

### 10.3 事件

DeepTutor 在写入 QCore 作答时保留：

```text
question_id
revision_id
source_type=qcore
attempt_id/request_id
```

集成层在证据写入后异步建立 `EvidenceMappingBinding`；不得阻塞或伪造作答。

---

## 11. 与现有代码的兼容性

| 现有结构 | 兼容性 | 处理 |
|---|---|---|
| `KnowledgePoint` `extra=ignore` | 可加字段但不持久 | 用外部 link 表，不强塞单值 |
| `LearningProgress` JSON | 不应加必填字段 | 用 sidecar association/projection |
| `QuizAttempt.revision_id/source_type` | **已兼容** | 直接使用 |
| `LearningEvidence.revision_id/source_type` | **已兼容** | 直接使用 |
| `ErrorRecord.revision_id/source_type` | **已兼容** | 直接使用 |
| `LearningEvidence` 无 mapping_version | 需 sidecar binding | 不修改现有模型 |
| `notebook_entries.question_id` | 不具备 QCore 身份 | 保留 `source_type=qcore` 隔离；不强行混用 |
| `AssessmentRecord` 无 revision_id | 不适合 QCore lane | QCore 走 `QuizAttempt`/`LearningEvidence` |
| `mastery_levels` 局部键 | 不能直接全局聚合 | canonical projection 只读派生 |
| RAG/GraphRAG | 文档检索图 | 不参与 node identity |

兼容结论：

```text
最小侵入方案可行
无需修改 QCore/DeepTutor 现有数据结构
关联层以 sidecar + read projection 实现
```

---

## 12. 必须保持的不变量

1. `KnowledgePoint.id` 与 `canonical_node_id` 不同。
2. `canonical_node_id` 必须存在于指定 `node_catalog_version`。
3. 一个 `kp_id` 可关联多个 canonical nodes。
4. 一个 canonical node 可被多个 `kp_id` 关联。
5. 同一 evidence 只计一次 attempt。
6. 每个 evidence 必须可追溯到 `question_id`、`revision_id`、`source_type`、`attempt_id`（可得时）。
7. 每个 canonical mastery 必须记录 `mapping_version` 和 `as_of`。
8. 旧证据不被新映射静默重解释。
9. `ungraded` 不进入掌握度和错误统计。
10. QCore 与 DeepTutor 不互写对方事实源。

---

## 13. 关闭条件

本契约任务完成条件：

- 实体边界明确；
- 身份与多对多关系明确；
- 掌握度聚合规则明确；
- 两类错题证据入口明确；
- 数据所有权明确；
- 现有代码兼容性已核查；
- 不修改生产代码/数据库。

本契约**不包含**：

- QCore 题目 V2 全量映射；
- Gold Benchmark 建设；
- DeepTutor 代码改造；
- 学生掌握度算法替换；
- 生产接入。

---

## 14. 最终裁决

```text
QCore 与 DeepTutor 应保持双事实源
通过只读、版本化、多对多关联层连接
不合并 KnowledgePoint 与 Global Node
不复制 Mastery/Evidence
```

下一步才是：

1. 按本契约建立关联层 schema；
2. 建立独立 Node/Question Gold；
3. 再决定 Primary/Secondary 映射是否达到可消费质量。

---

## 15. 契约文件

```text
docs/quality/AITUTORS-QCORE-DEEPTUTOR-KNOWLEDGE-CONTRACT-01.md
docs/quality/AITUTORS-QCORE-DEEPTUTOR-KNOWLEDGE-CONTRACT-V1.json
```
