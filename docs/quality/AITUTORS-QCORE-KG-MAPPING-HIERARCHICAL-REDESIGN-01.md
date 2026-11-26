# AITUTORS-QCORE-KG-MAPPING-HIERARCHICAL-REDESIGN-01

- 日期：2026-11-26
- 状态：**SEMANTIC ARCHITECTURE DEFINED / V2 FULL MAPPING NOT READY**
- 性质：语义架构重构，不是 169 题重跑，不是模型调参
- QCore 写入：0
- 知识图谱修改：0
- DeepTutor 入口：未启动

---

## 1. 最终裁决

### 1.1 架构裁决

```text
Primary      = 稳定上层知识分类（curriculum module / chapter）
Secondary    = Primary 范围内的具体知识点
Supporting   = 先修、辅助、方法、相关但非主要考查
```

三层语义独立，不能把 Primary 自动改成父节点、Secondary 自动改成子节点。

### 1.2 执行裁决

```text
分层语义方向 = ACCEPTED
169 题 V2 全量重映射 = NOT READY
原因 = Primary 上层覆盖不足 + 稳定性仍未达 90%
```

历史映射 `full-v1` / `full-v2-consensus` 保留，不修改、不删除。

---

## 2. 三个维度的正式定义

### 2.1 Primary：稳定上层分类

Primary 的任务是**分类稳定性**，不是穷举细节。

规则：

1. 只能从现有课程层级节点中选择；
2. 优先 `level=2` 模块；必要时 `level=3` 章节；
3. `level=1` 学科根只作为显式 fallback，并必须标记；
4. 禁止把 mmlong 细粒度叶子节点直接作为 Primary；
5. 同一题原则上 1–3 个 Primary；
6. 多核心领域不能为稳定性强行合并。

### 2.2 Secondary：具体考查内容

1. 必须挂在某个 Primary 下；
2. 可来自 level=4 或 mmlong 细节点；
3. 可多个，但不追求填满；
4. 每个节点保留 evidence、confidence；
5. 节点不能表达时标 `pending_refinement`，不创建新节点；
6. Secondary 的精细度不作为 Primary 稳定性阻断项。

### 2.3 Supporting：辅助知识与方法

1. 表示先修、辅助、方法、相关背景；
2. 不得因为是“更具体”就自动归入 Supporting；
3. 与 Primary/Secondary 不重复表达同一核心考查；
4. 必须带 role：`prerequisite | auxiliary_knowledge | method | related`。

### 2.4 Unmapped

`unmapped` 是合法结果，不允许为了覆盖率强行映射。

原因枚举：

```text
no_suitable_primary_category
no_suitable_secondary_node
graph_gap
insufficient_source_text
```

---

## 3. 知识图谱层级兼容性

详细报告：

[AITUTORS-QCORE-KG-HIERARCHY-COMPATIBILITY-01.md](AITUTORS-QCORE-KG-HIERARCHY-COMPATIBILITY-01.md)

关键事实：

| 项 | 数值 |
|---|---:|
| 总节点 | 4,829 |
| mytutors_curriculum | 629 |
| mmlong818 | 4,182 |
| goralcao_supplement | 18 |
| 有 parent_code/level 的节点 | 629 |
| level=1 学科根 | 6 |
| level=2 模块 | 35 |
| level=3 章节 | 136 |
| level=4 具体 | 452 |
| 可解析到 level=3 的节点 | 2,859 / 4,829 |
| 不可解析到 level=3 的节点 | 1,970 / 4,829 |

结论：

- 现有 4,829 节点**不是完整父子树**；
- 只有 629 个课程节点有显式层级；
- 4,182 个 mmlong 节点没有 parent；
- 4,182 个 mmlong 中有 2,271 个能通过教材 chapter_path 对齐到 level=3；
- 1,911 个 mmlong + 18 个 goralcao 无法解析上层。

这是本任务最重要的结构限制。

---

## 4. 169 题历史差异诊断

详细结果：

```text
_dsh/workpackage_c/hierarchy_diagnosis_v2.json
```

样本：166 题具有三份有效运行（full-v1、rep2、rep3）。

| 指标 | 结果 |
|---|---:|
| 细粒度 Primary 完全一致 | 64 / 166 = 38.6% |
| level=3 粗分类完全一致 | 124 / 166 = 74.7% |
| level=3 严格可解析样本一致 | 83 / 107 = 77.6% |
| level=2 模块严格样本一致 | 95 / 107 = 88.8% |
| level=1 学科严格样本一致 | 106 / 107 = 99.1% |
| 细粒度差异但 level=3 收敛 | 60 题 |
| level=3 仍不一致 | 42 题 |
| 含上层 fallback 的题 | 59 / 166 |

解释：

1. **60 题**的不一致可以通过上移到 level=3 收敛；
2. **42 题**即使上移后仍不一致，属于真实分类争议或图谱缺口；
3. 59 题中存在无法解析到 level=3 的节点，只能 fallback 到学科根；
4. 因此“把 Primary 上移”能显著改善，但不能单独解决全部稳定性。

### 4.1 差异类型

| 类型 | 数量/说明 |
|---|---:|
| 同一上层、不同细节点 | 60 题可由 level=3 收敛 |
| Primary/Supporting 角色变化 | 74 / 166 存在角色变化 |
| 真实上层分类分歧 | 42 题 level=3 仍不一致 |
| 图谱层级缺口 | 246 / 975 个 primary 节点无 level=3 |
| 综合题粒度问题 | QCore 当前无结构化 subquestion 身份，未做小问级验证 |

---

## 5. Question / Subquestion 粒度规则

### 5.1 Question 级

适用于：

- 单一考查目标；
- 多个小问共享同一核心知识体系；
- 各小问只是同一目标的不同形式。

### 5.2 Subquestion 级

适用于：

- 不同小问具有独立核心知识目标；
- Question 级会丢失小问差异；
- 不同小问需要不同 Primary。

### 5.3 当前数据边界

QCore catalog 当前字段：

```text
question_id, revision_id, question_type, subject, grade,
stem_text, material_text, options_text, answer_*,
explanation_*, search_text, ...
```

没有结构化 `subquestion_id` / `subquestion_ref`。

因此：

- **本任务不强制拆分小问**；
- Schema V2 保留 `mapping_scope=subquestion` 和 `subquestion_ref`；
- 只有 QCore/源结构提供小问身份时，才允许 subquestion 级映射；
- 不能仅凭题干里的 `(1)(2)` 文本推断小问身份。

---

## 6. Mapping Schema V2

正式 Schema：

[AITUTORS-QCORE-KG-MAPPING-SCHEMA-V2.json](AITUTORS-QCORE-KG-MAPPING-SCHEMA-V2.json)

核心约束：

- `primary` 必须 `^my:`，不允许 mmlong 叶子；
- `secondary.parent_primary_node_id` 必须指向某个 primary；
- `supporting.role` 区分先修/辅助/方法/相关；
- `mapping_scope` 支持 question/subquestion；
- `subquestion` 必须有 `subquestion_ref`；
- 保留 model/prompt/candidate/run 来源；
- `unmapped` 原因枚举；
- 不创建新 node_id。

建议的 Primary 候选索引：

```text
35 个 level=2 模块
136 个 level=3 章节
6 个 level=1 学科根（仅 fallback）
```

---

## 7. 20 题小样本语义验证

样本：按学科分层的 20 道题，复用已有三份运行，不做新全量、不做新模型调用。

详细结果：

```text
_dsh/workpackage_c/pilot_20.json
```

| 指标 | 结果 |
|---|---:|
| 样本 | 20 |
| 细粒度 Primary 一致 | 10 / 20 = 50% |
| level=3 粗分类一致 | 16 / 20 = 80% |
| 严格可解析样本 | 13 |
| 严格 level=3 一致 | 11 / 13 = 84.6% |

结论：

- 分层确实把一致性从 50% 提升到 80%；
- 但仍未达到 90% 的 Primary 稳定性门槛；
- 小样本证明方向有效，**不证明已可全量 V2**。

---

## 8. 稳定性指标定义

V2 不能沿用旧的“细粒度 Primary 集合完全一致率”。

正式指标：

### Primary Stability

```text
同一 question_id、revision_id、mapping_version、model、prompt、candidate policy
在独立重复运行中，Primary 上层 category 集合完全一致的比例。
```

- Primary category 取 level=2 模块；无模块时取 level=3；仅无上层时标 fallback 到 level=1。
- 目标：≥90%。

### Secondary Validity

不要求集合完全一致，要求：

- node 有效；
- parent primary 正确；
- evidence 可追溯；
- 无重复角色；
- `pending_refinement` 可接受。

### Supporting Boundary

- 不得与 Primary/Secondary 表达同一核心考查；
- 角色变化必须记录；
- 不设集合一致率硬门槛。

---

## 9. 为什么不能直接做 169 题 V2

三个硬条件未满足：

1. **覆盖不足**
   - 1,970 / 4,829 节点无法解析 level=3；
   - 975 个 primary 节点中 246 个没有 level=3；
   - 59 / 166 题需要 fallback 到学科根。

2. **稳定性不足**
   - level=2 严格样本 88.8%；
   - level=3 严格样本 77.6%；
   - 20 题 pilot 80%；
   - 均低于 90%。

3. **粒度未验证**
   - QCore 当前没有结构化 subquestion 身份；
   - subquestion 映射只能保留 schema 能力，不能在本轮声称已验证。

---

## 10. 最小兼容方案

不修改 4,829 节点、不重建图谱：

### PrimaryCategoryIndex

由现有节点派生：

```text
level=1: 6
level=2: 35
level=3: 136
```

### mmlong 对齐

- 使用 `textbooks[].chapter_path` 对齐到 level=3；
- 已覆盖 2,271 / 4,182；
- 剩余 1,911 不为映射强行造父节点；
- 无上层时显式 fallback 到学科根并标记 `primary_fallback=true`。

### 映射约束

- Primary 只从 PrimaryCategoryIndex 选；
- Secondary 从 4,829 细节点选；
- Supporting 独立；
- 不修改图谱；
- 不改 QCore。

---

## 11. 下一步建议

### 建议任务

`AITUTORS-QCORE-KG-PRIMARY-CATEGORY-RESOLVER-01`

目标：

1. 建立 35 模块 / 136 章节 / 6 根的派生 PrimaryCategoryIndex；
2. 完成 mmlong → level=3 的最小对齐；
3. 对 20–30 题跑 V2 小样本；
4. 验证 Primary 模块级稳定性 ≥90%；
5. 通过后，才允许 169 题 V2 全量。

### 不允许立即做

- 不直接重跑 169 题 V2；
- 不做全图人工审查；
- 不创建新节点；
- 不把 level=1 fallback 当作成功覆盖；
- 不启动 DeepTutor 消费。

---

## 12. 边界自检

- QCore 数据写入：0；
- QCore 发布状态变更：0；
- 知识节点创建/修改：0；
- 169 题重跑：0；
- 模型选型/Prompt 大调参：0；
- Embedding 引入：0；
- DeepTutor 入口：0；
- 历史映射保留：是。

---

## 13. 交付物

```text
docs/quality/AITUTORS-QCORE-KG-MAPPING-HIERARCHICAL-REDESIGN-01.md
docs/quality/AITUTORS-QCORE-KG-HIERARCHY-COMPATIBILITY-01.md
docs/quality/AITUTORS-QCORE-KG-MAPPING-SCHEMA-V2.json

_dsh/workpackage_c/hierarchy_compatibility.json
_dsh/workpackage_c/hierarchy_diagnosis_v2.json
_dsh/workpackage_c/pilot_20.json
```
