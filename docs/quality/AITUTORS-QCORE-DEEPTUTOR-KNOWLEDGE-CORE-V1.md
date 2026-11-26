# AITUTORS-QCORE-DEEPTUTOR-KNOWLEDGE-CORE-V1

- 日期：2026-11-27
- 状态：**CORE CONTRACT DEFINED / NO SCHEMA IMPLEMENTATION**
- 性质：精简版第一阶段契约
- 完整目标架构：[AITUTORS-QCORE-DEEPTUTOR-KNOWLEDGE-CONTRACT-01.md](AITUTORS-QCORE-DEEPTUTOR-KNOWLEDGE-CONTRACT-01.md)
- 代码修改：0
- 数据库修改：0

---

## 1. 裁决

```text
架构方向 = ACCEPTED
V1 完整契约 = NOT IMPLEMENTED AS-IS
当前进入 Schema = NO
当前优先级 =
  知识语义基线
  > 题目映射质量
  > 真实学习消费验证
  > 最小关联层
```

V1 Core 只解决**现在必须确定**的语义与身份关系。

不包含：

- 跨路径掌握度聚合；
- CanonicalMasteryProjection；
- 提前物化的 EvidenceMappingBinding；
- 全量 ErrorEvidenceProjection；
- ObjectiveNodeLink 强制表；
- 完整双向 API；
- 跨路径 SRS；
- 多版本历史投影平台。

这些进入未来扩展，需真实消费需求触发。

---

## 2. 三个层次不能合并

| 概念 | 回答的问题 | 归属 |
|---|---|---|
| Knowledge Hierarchy | 这个知识点在学科体系中处于什么位置？ | QCore 知识模型 |
| Question Knowledge Mapping | 这道题实际考查哪些知识？ | QCore 派生映射层 |
| Learning Objective | 学生需要学会什么？ | DeepTutor 学习目标 |

三者相关，但不等价。

因此：

- KnowledgePoint ≠ QCore node；
- Learning Objective ≠ Secondary；
- 不能因为节点是另一个节点的子节点，就断言它在题目中是 Supporting；
- 知识层级关系与题目考查角色是两套语义。

---

## 3. V1 Core 实体

### 3.1 QCore KnowledgeNode

```text
node_id
name
subject
level
node_catalog_version
```

约束：

- 现有命名空间保留；
- 不创建新节点；
- 不把未验证的父节点补齐当作规范事实；
- 4,829 节点与 35/136 课程分类的关系可以记录，但不等于完整知识树。

### 3.2 QCore Question / Revision

```text
QuestionRef = (question_id, revision_id)
```

- `question_id`：跨 Revision 的题目身份；
- `revision_id`：内容/发布版本；
- 发布状态由 QCore 权威；
- 历史证据保留作答时 Revision。

### 3.3 QuestionNodeMapping

```text
QuestionNodeMapping
  question_id
  revision_id
  mapping_version
  node_id
  role: primary | secondary | supporting
  parent_primary_node_id  # secondary 可选
  confidence
  evidence_quote
  source_run_id
```

约束：

- 一个题目可以有多个 node（多对多）；
- 一个 node 可被多道题引用；
- `role` 是题目考查角色，不是知识层级；
- `primary` 来自稳定的上层分类域；
- `secondary` 表达具体考查内容；
- `supporting` 表达先修/辅助/方法；
- 允许无 Secondary、无 Supporting、unmapped；
- `mapping_version` 不可变。

### 3.4 DeepTutor KnowledgePoint

保持现有：

```text
KnowledgePoint.id          # 路径内局部 ID
module_id
name
type
prerequisite_ids           # 同路径内
```

V1 不要求：

- 给每个 KnowledgePoint 加 canonical_node_id；
- 建立 ObjectiveNodeLink 表；
- 把所有学习目标映射到 QCore 节点。

理由：临时解释任务、文档主题、综合目标不一定需要全局节点归属。

### 3.5 DeepTutor LearningEvidence

已有字段：

```text
evidence_id
question_id
revision_id
source_type
knowledge_point_id  # 局部，可为空
attempt_id
result
quality
```

V1 规则：

- 学习证据保留题目/Revision 身份；
- 不复制题目内容；
- 不复制 QCore 映射；
- `ungraded` 不进入正确率/错误/掌握度；
- QCore Practice 继续使用 `source_type=qcore`。

---

## 4. 历史解释与版本

### 4.1 不物化 EvidenceBinding

一条 evidence 已具备：

```text
question_id
revision_id
source_type
attempt_id
```

QCore 映射可按：

```text
(question_id, revision_id, mapping_version)
```

查询还原知识节点。

因此 V1 不要求为每条 evidence 生成节点绑定副本。

只有在未来出现性能或审计需求时，再物化 sidecar。

### 4.2 映射版本

- `mapping_version` 是不可变快照；
- 题目映射变化必须新版本；
- 学习证据应能确定当时使用的版本；
- 旧证据不被新映射静默重解释；
- 版本兼容/迁移策略暂不预设。

### 4.3 去重

V1 去重键必须包含学生身份：

```text
learner_id
+ source_type
+ question_id
+ revision_id
+ attempt_id
```

或使用全局唯一提交事件 ID。

QCore `request_id` 必须定义为**幂等提交标识**：

- 同一 request_id 重放 → 同一作答；
- 不得把每次 HTTP 请求自动当成新 attempt；
- 不同学生不能共用 attempt_id。

---

## 5. 掌握度

V1 不计算 canonical mastery。

DeepTutor 继续使用：

```text
LearningProgress.mastery_levels    # 局部 kp
LearningEvidence
compute_mastery
SRS
```

V1 只要求：

- 学习证据可按 `question_id/revision_id` 追溯；
- 映射版本可确定；
- 未来需要全局掌握度时，再基于真实数据和算法验证建立只读投影。

当前不定义：

- 跨路径权重；
- 不同难度证据合并；
- 不同 mapping_version 的混合；
- canonical mastery API。

---

## 6. 数据所有权

| 数据 | 所有者 | 写入方 |
|---|---|---|
| KnowledgeNode / Question / Revision / 发布 | QCore | QCore |
| QuestionNodeMapping / mapping_version | QCore 派生层 | QCore mapping job |
| MasteryPath / KP / Module | DeepTutor | DeepTutor |
| QuizAttempt / LearningEvidence / ErrorRecord | DeepTutor | DeepTutor |
| Mastery / SRS | DeepTutor | DeepTutor |
| 可选教学关联 | 未来集成层 | 未来集成层 |

禁止：

- QCore 写 DeepTutor 学习状态；
- DeepTutor 写 QCore 题目/节点/映射；
- 复制另一侧事实为第二事实源；
- 把 RAG 图当规范知识体系。

---

## 7. 最小闭环

V1 只要求支持以下查询/流程：

```text
QCore Question / Revision
  → QuestionNodeMapping
  → DeepTutor QuizAttempt (source_type=qcore, qid/rid)
  → LearningEvidence
  → 按知识点维度查看学习证据
```

初期可以回答：

- 学生在哪些知识节点上做过题？
- 哪些题做错了？
- 哪些错误重复出现？
- 哪些节点有足够证据？
- 哪些节点没有足够证据判断掌握度？

不要求：

- 自动生成 Mastery Path；
- 跨路径掌握度；
- 全局掌握度评分；
- 个性化推荐。

---

## 8. 未来扩展

| 模块 | 状态 | 触发条件 |
|---|---|---|
| ObjectiveNodeLink | Future | 出现真实学习目标↔节点关联需求 |
| EvidenceMappingBinding | Future | 查询性能/审计需要物化 |
| CanonicalMasteryProjection | Future | 真实跨路径数据证明需要且算法通过 |
| ErrorEvidenceProjection | Future | 统一错题流程真正落地 |
| 跨路径 Mastery | Future | 验证证据可比性 |
| 跨版本 Mastery | Future | 定义版本兼容策略 |
| 完整双向 API | Future | 真实消费场景确定 |
| 跨路径 SRS | Future | 有明确学习安排需求 |

这些模块不在 V1 建表，不在 V1 定义接口。

---

## 9. 调整后的执行顺序

```text
1. 知识语义基线
   4,829 节点 + 35/136 分类边界
   不追求 100% 覆盖
2. 独立 Node / Question Gold
   不继承 full-v1 LLM 输出
3. Primary / Secondary 映射质量
   比较规则、约束 LLM、拒绝机制
4. 真实 DeepTutor 消费验证
   小批已发布题目 → 学习证据查询
5. 最小关联层
   由真实消费结果决定表/索引/API
6. Future Extensions
   按需求逐项启用
```

**不在映射质量验证前建 Schema。**

---

## 10. 关闭条件

V1 Core 完成条件：

- 实体边界明确；
- Question/Revision 身份明确；
- QuestionNodeMapping 多对多与角色明确；
- mapping_version 不可变；
- 学习证据保留 qid/rid/attempt；
- 去重包含 learner_id 或全局事件 ID；
- QCore/DeepTutor 所有权明确；
- 不建 Projection、关联 API、跨路径掌握度。

---

## 11. 最终裁决

```text
V1 CORE = DEFINED
SCHEMA IMPLEMENTATION = NOT STARTED
CANONICAL MASTERY = DEFERRED
OBJECTIVE LINK = OPTIONAL FUTURE
169 V2 = NOT APPROVED
```

V1 Core 只保证：

```text
题目知识语义可追溯
映射版本不可变
学习证据可回到题目/Revision
两侧事实不互写
```

这已经足够支撑下一阶段的 Gold 与映射质量验证；不需要提前建设平台。
