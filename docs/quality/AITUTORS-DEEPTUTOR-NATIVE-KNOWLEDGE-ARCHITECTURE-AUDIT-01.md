# AITUTORS-DEEPTUTOR-NATIVE-KNOWLEDGE-ARCHITECTURE-AUDIT-01

- 日期：2026-11-27
- 性质：只读架构审计
- 审计对象：当前集成 DeepTutor 代码版本
  - `deeptutor/__version__.py` = `1.7.3`
  - checkout = `v1.7.3-18-ge7d525a88`
  - 提交 `e7d525a88eccf57498c6f376fe0b00a4ba81860a`
  - 不以 GitHub 最新上游替代
- QCore 写入：0
- DeepTutor 业务代码修改：0
- 数据库修改：0
- 新映射任务：0

---

## 1. 最终结论

```text
DeepTutor 原生能力 = 个体学习模型完整，全局学科知识模型不具备
KnowledgePoint = 每个 Mastery Path 内部的学习目标，不是 QCore 4,829 规范节点
Mastery Path = 可复用学习循环，但不能直接消费 QCore 全局知识关系
学习证据/SRS = 已具备，可承载 QCore 作答；但 knowledge_point_id 目前为空
RAG = 文档检索能力，不等同于学科知识图谱
题库 = 原生 notebook_entries 与 QCore lane 尚未统一
```

**不应让 QCore 另建一套 Mastery/证据系统；应通过适配层接入 DeepTutor 原生学习聚合。**

---

## 2. KnowledgePoint

定义位置：

```text
deeptutor/learning/models.py:81
```

字段：

```python
class KnowledgePoint:
    id: str
    name: str
    type: KnowledgeType  # memory/concept/procedure/design
    module_id: str
    prerequisite_ids: list[str]
    topic_source_ids: list[str]
    required_visual_tasks: [...]
```

关键事实：

1. `id` 是路径内局部 ID，不是全局学科节点 ID；
2. 生成逻辑在 `deeptutor/learning/topic_generation.py:399-438`：
   - `objective_id = f"{module_id}_kp{kp_index}"` 或新实体 ID；
   - 名称、类型来自 LLM 生成的 topic draft；
   - 没有 QCore 4,829 node_id 字段；
3. `module_id` 指向同一路径的 `LearningModule`；
4. `prerequisite_ids` 只在校验后引用同路径的目标（`objective_relations.py`）；
5. `topic_source_ids` 是来源证据，不是知识节点身份。

结论：

```text
DeepTutor KnowledgePoint = per-topic learning objective
≠ QCore global knowledge node
```

不能直接合并，也不能假设同名即同一节点。

---

## 3. Mastery Path

定义：

```text
deeptutor/learning/models.py:98  LearningModule
deeptutor/learning/models.py:750 LearningProgress
deeptutor/learning/models.py:62  LearningStage
```

结构：

```text
LearningProgress
  modules: LearningModule[]
    knowledge_points: KnowledgePoint[]
  current_stage: diagnostic/explain/feynman_check/practice/error_diagnosis/review/completed
  mastery_levels
  qualitative_mastery
  quiz_attempts
  error_records
  learning_evidence
  repetition_states
  review_queue
```

生成与存储：

- `topic_generation.py` 从 `TopicSource`（book/notebook/KB/file/chat/question_bank/cowriter）生成模块和目标；
- `LearningStore` 使用 SQLite 聚合（`learning/storage.py`），`mastery_paths` 表保存 `LearningProgress` JSON；
- 路径实体 ID 由路径 ID + 模块/目标序号生成；
- 一个路径最多 8–20 个模块，每模块最多 7 个目标（`topic_generation.py:29-35`）。

结论：

- Mastery Path 是**学习循环与个体进度模型**，可以复用；
- 它的知识结构是**按主题即时生成**，不是全局 4,829 节点；
- QCore 若要消费，需要把 QCore 节点映射为路径目标或外部 canonical 字段，而不是替换其本地 ID。

---

## 4. 学习证据与掌握度

### 4.1 数据结构

```text
QuizAttempt      models.py:123
ErrorRecord      models.py:163
LearningEvidence models.py:182
RepetitionState  models.py:216
ReviewTask       models.py:240
```

`QuizAttempt` 关键字段：

```text
question_id
revision_id        # QCore revision
source_type        # qcore / notebook
knowledge_point_id
module_id
is_correct / result
error_type
voided / void_reason
visual_context
```

`LearningEvidence`：

```text
question_id, revision_id, source_type, knowledge_point_id
result=correct/incorrect/partial/ungraded
quality, hints_used, attempt_count, confidence
```

`ErrorRecord`：

```text
question_id, revision_id, source_type, attempt_id
knowledge_point_id, module_id, error_type
status: active/retrying/review/graduated
```

### 4.2 掌握度计算

`deeptutor/learning/mastery.py:24`：

```python
compute_mastery(correctness)
```

- 最近 5 次尝试，recency weights `(0.5,0.7,0.85,0.95,1.0)`；
- 1 次尝试 cap 0.5；2 次 cap 0.8；
- 不把一次错误直接判“不会”；
- 与 SRS 的 `repetition_states` 分开：掌握度和复习安排在两个模型里。

### 4.3 证据的真实边界

- QCore Practice 当前以 `review_only` 运行：
  - `QuizAttempt.is_correct=None`；
  - `LearningEvidence.result="ungraded"`；
  - 不伪造正确/错误；
  - 不建 ErrorRecord（除非有合法判分）。
- 这已经在 `qc_learning.py:137-162` 注释和代码中明确。

结论：

```text
DeepTutor 学习证据模型可复用
QCore 作答可用 qid/rid 进入
但 knowledge_point_id 目前为空
```

---

## 5. QCore 集成现状

### 5.1 题目读取

`deeptutor/api/routers/practice.py`：

- `/qcore/proxy/student/questions`
- `/qcore/proxy/student/questions/{question_id}`
- `/qcore/state/{question_id}?revision_id=...`
- `/qcore/review`

题目内容通过 QCore Student API 透传，不落 DeepTutor 内容库。

### 5.2 作答记录

`deeptutor/services/practice/qc_learning.py`：

```python
QC_BOOK_ID = "qcore-practice"
state_key(question_id, revision_id) = f"qcore:{question_id}:{revision_id}"
```

写入原生聚合：

```text
QuizAttempt.source_type="qcore"
LearningEvidence.source_type="qcore"
```

但：

```python
knowledge_point_id=""
module_id=""
```

代码注释明确：

> 未映射题目使用 CONCEPT 调度档位，**不是知识点映射**；
> knowledge_point_id 保持空串，映射待 NLP 知识层。

### 5.3 答案通道

`deeptutor/services/practice/qc_answer_key.py`：

- 服务端读取 QCore `/internal/published/<question_id>`；
- token 保护；
- 只读当前 published revision；
- 不缓存；
- 不向浏览器暴露。

结论：

- QCore 身份（qid/rid）已经进入 DeepTutor 学习记录；
- 知识节点关联尚未建立；
- QCore Practice 是独立学习 lane，不等同于原生 notebook question bank。

---

## 6. 原生题库与 QCore

### 6.1 notebook_entries

`deeptutor/services/session/sqlite_store.py:367`：

```text
notebook_entries
  id INTEGER PRIMARY KEY
  session_id
  origin_type / origin_ref / turn_id
  question_id TEXT        # 内容/导入身份，不是 QCore qid
  question, options, correct_answer, explanation
  source
  mastery_path_id
  knowledge_point_id
  ...
```

`PracticeStore` 以 `entry_id` 为主键（`practice/storage.py`）。

### 6.2 QCore lane

`qc_learning.py` 不创建 `notebook_entries`，而是把 QCore 作答写入：

```text
LearningProgress.quiz_attempts/learning_evidence/repetition_states
```

因此当前有两条题库路径：

```text
notebook_entries (native question bank)
QCore practice lane (qid/rid-native learning records)
```

两者尚未共用统一题目身份。

结论：

- 不能简单把 QCore qid 塞进 notebook_entries 的 `question_id`；
- 需要显式 `source_type=qcore` + `question_id/revision_id` 身份契约；
- 当前 QCore lane 是隔离的正确起点。

---

## 7. RAG / 知识图谱

### 7.1 RAG

`deeptutor/tools/rag_tool.py` + `services/rag/factory.py`：

支持：

```text
llamaindex (default, hybrid BM25 + vector)
pageindex / pageindex-oss
graphrag
lightrag / lightrag-server
ima
weknora
kiwix
```

`deeptutor/services/rag/pipelines/llamaindex` 默认 profile 为 `hybrid`，BM25/vector 融合。

### 7.2 知识图谱

- GraphRAG/LightRAG 是**知识库/文档级检索图**；
- 不是 QCore 4,829 学科知识树；
- 不能把 RAG 图当作规范学科知识模型；
- DeepTutor 没有内置的 K12 全局知识点层级树。

结论：

```text
RAG = 文档检索基础设施
Knowledge Graph = 检索图/实体图
QCore KG = 规范学科知识层
三者不能互相替代
```

---

## 8. 最终问题回答

| 问题 | 结论 |
|---|---|
| DeepTutor 是否已有可复用全局知识模型？ | **没有**；有完整的 Mastery Path 和局部 KnowledgePoint，没有 QCore 级全局学科分类 |
| KnowledgePoint 能否承载 QCore 节点？ | **不能直接复用**；它是路径局部学习目标，需增加 canonical_node_id 适配，不能同名合并 |
| Mastery Path 能否直接消费 QCore 关系？ | **不能直接**；需要把 QCore 节点/关系映射为路径模块、目标或 external reference |
| 现有学习证据能否支撑个体模型？ | **已具备**：QuizAttempt/LearningEvidence/ErrorRecord/SRS；QCore 作答可进入 |
| 是否存在重复建设？ | **有**；再建一套 mastery/证据系统会重复。应复用 DeepTutor 聚合 |
| QCore 需要补什么？ | 稳定 node_id、题目→节点映射、revision 身份契约、canonical 字段/适配接口 |

---

## 9. 应停止/应复用的建设

### 应停止

- 不要在 QCore 内再建一套 Mastery Path；
- 不要另建学生证据/复习队列；
- 不要把 RAG/GraphRAG 当成学科知识图谱；
- 不要把 DeepTutor 局部 KnowledgePoint 与 QCore 4,829 直接合并。

### 应复用

- DeepTutor `LearningProgress` 聚合；
- `QuizAttempt` / `LearningEvidence` / `ErrorRecord`；
- `RepetitionState` / SRS；
- `Mastery Path` 学习循环；
- 原生题目/错题统计；
- QCore `qid/rid` 身份。

---

## 10. 最小适配方向

不修改 DeepTutor 代码，仅提出契约：

```text
QCore canonical node_id
  ↔ DeepTutor KnowledgePoint.canonical_node_id (新增适配字段)
  ↔ Mastery Path target

QCore question_id/revision_id
  ↔ QuizAttempt.question_id/revision_id + source_type=qcore
  ↔ LearningEvidence / ErrorRecord

QCore mapping version
  ↔ learning evidence metadata
```

原则：

- QCore 负责题目、revision、规范节点与全局映射；
- DeepTutor 负责学生、路径、作答、证据、掌握度；
- 不在任一侧复制另一侧的事实源。

---

## 11. 审计边界

- 只读代码；
- 未修改 QCore；
- 未修改 DeepTutor；
- 未修改数据库；
- 未启动知识映射；
- 未启动 DeepTutor 消费入口。

---

## 12. 关键文件索引

```text
deeptutor/learning/models.py
deeptutor/learning/topic_generation.py
deeptutor/learning/mastery.py
deeptutor/learning/service.py
deeptutor/learning/storage.py
deeptutor/learning/objective_relations.py
deeptutor/learning/scheduler.py
deeptutor/services/practice/qc_learning.py
deeptutor/services/practice/qc_answer_key.py
deeptutor/services/practice/storage_qc.py
deeptutor/api/routers/practice.py
deeptutor/services/session/sqlite_store.py
deeptutor/tools/rag_tool.py
deeptutor/services/rag/factory.py
deeptutor/services/rag/pipelines/llamaindex
```
