# AITUTORS-QCORE-PUBLICATION-STATE-RECONCILIATION-01

- 日期：2026-11-26
- 执行：DSH（只读）
- 目标：解释 `qcore_revisions.publication_state` 与 `qcore_state_history` 的差异，锁定当前有效发布清单
- 结论：**169 是当前有效发布清单；列级 0 是创建时投影，不是发布状态**
- 未修改：QCore 数据、发布状态、历史、索引、bundle

---

## 1. 数据源身份

运行配置：

```text
Teaching Script Compiler/.env.local
QCORE_DATABASE_URL=postgresql+psycopg2://qcore_app:***@127.0.0.1:55432/qcore_six_subject_accept_01
```

Compiler `data/qcore/meta.json`：

```json
{
  "database": "qcore_six_subject_accept_01",
  "published_bundles": 169,
  "built_at": "2026-11-24T14:08:16Z"
}
```

因此：

- **当前配置的 QCore 数据源 = `qcore_six_subject_accept_01`**；
- `qcore_g4_final_01`、`qcore_semantic_expansion_01`、`qcore_*_repair` 等是历史/隔离/实验库；
- 不能按数据库名或数据量推生产归属，以上是配置 + snapshot 双重证据。

---

## 2. 双状态源的解释

### 2.1 列是创建时投影

`question_core/persistence/repository.py:537-542` 明确：

```text
State history: the ONLY authority for current lifecycle state.

The review_state / publication_state / completeness columns on
qcore_revisions are creation-time snapshots for cheap queries; they
are never read back as "the current state". Everything below goes
through the append-only qcore_state_history table.
```

因此：

- `qcore_revisions.publication_state` = 创建时值，不能当当前发布状态；
- `qcore_state_history` 最新 snapshot = 当前权威状态；
- 两者不一致不是“DB reset”，而是设计上的投影/权威分离。

### 2.2 193 条 Revision 的逐条核对

`qcore_state_history` 共 585 行，覆盖 175 个 question；每个 revision 都有 snapshot。

按每个 revision 的最新 snapshot：

| 当前状态 | 数量 |
|---|---:|
| published | **169** |
| withdrawn | **18** |
| unpublished | **6** |
| 合计 revisions | **193** |

`qcore_revisions.publication_state` 全部是 `unpublished`（创建时值），所以：

```text
169 published + 18 withdrawn = 187 条不一致
6 unpublished = 6 条一致
```

**187/193 的差异已完全解释，不是双写随机错误。**

### 2.3 18 条 withdrawn 的去向

18 条 withdrawn 全部有**更高 revision_number 的 published revision**：

- 09ff9350: rev1 → rev2
- 2bc0ff83: rev1 → rev2
- 2bd8e075: rev1 → rev2
- 3137baec: rev1/2/3 → rev4
- 3a9d28d1: rev1/2 → rev3
- 505532ad, 580e95ee, 8b8287a7, 8dceea0a, a0804511, ac838d5d, bd2eadf1: rev1 → rev2
- 7a87e6a2: rev1/2/3 → rev4

所以 18 条是**旧 revision 被新 revision 取代后的 withdrawn 记录**，不是当前可发布题。

6 条 unpublished 从未发布：

```text
1aafeb9b, 7755fbb1, a5affbcc, b6d7de24, be15c050, f61d5995
```

这与 Compiler `skipped_unpublished=6` 完全一致。

---

## 3. 当前有效发布清单

### 3.1 169 条

从最新 state snapshot 取 `publication=published`：

```text
published = 169
published questions = 169
```

清单 SHA256（question_id:revision_id，按 question_id/revision 排序）：

```text
9a852ddc1d9849fbd9acf6d6194975363669637c384c5947c7ce6c01960be02f
```

证据文件：

```text
_dsh/workpackage_a/authoritative_published.json
```

### 3.2 与 Compiler 的对应

| 项 | 数量 |
|---|---:|
| published qids | 169 |
| catalog qids | 169 |
| bundle qids | 169 |
| published ∩ catalog | 169 |
| catalog without published | 0 |
| published without catalog | 0 |
| published without bundle | 0 |
| bundle without published | 0 |

结论：Compiler 的 169 catalog/bundle 与最新 state_history 的 169 published **身份一致**，不是 stale 发布清单。

### 3.3 `index_prod` 的 175

`index_prod` 是 **175 qid**，包含 6 条 unpublished；它不是 published-only 索引，不能直接当发布清单。Compiler meta 的 169 来自 published filter，二者不矛盾。

---

## 4. P0-1：subject/grade 事实

对 `qcore_six_subject_accept_01` 的 193 条 candidate：

```text
subject null = 0
grade null = 0
```

`payload->'source'` 有完整字段：

```json
{"grade":"高三","subject":"语文","source_document_id":".../U1"}
```

真正问题：

- Revision 本身没有 subject/grade；
- `semantic/export.py` / `qcore_source.build_snapshot` 用 `source_document_id` 关键词推导学科；
- 没有读取 `candidate.payload.source` 的权威值。

所以：

```text
不是 207/193 条回填
不是 Adapter 丢失
是导出/索引路径忽略权威 source
```

修正方向：catalog/export 优先读 candidate.source；不可达才回退 manifest/source_document_id；不得用题干猜测或文件名覆盖。

---

## 5. 当前发布状态判断

```text
生产数据源: qcore_six_subject_accept_01
当前 authority: qcore_state_history latest snapshot
已发布: 169 revisions / 169 questions
已撤回: 18 old revisions（均有更新 published revision）
未发布: 6 questions
published list SHA256: 9a852ddc...
Compiler catalog/bundles: 169/169 匹配
```

“列级 0 published”是**创建时投影**，不是当前发布状态；“169 是 stale snapshot”这一表述应撤回；169 是有效当前发布清单，且与 bundle 身份一致。

---

## 6. 结论对后续的影响

- P0-0 **已锁定**：当前有效发布清单是 169，不是 0；
- 169 不应恢复/重建，它已经是当前有效清单；
- 18 withdrawn 是历史旧 revision，不应恢复；
- 6 unpublished 保持未发布；
- P0-1 修复可以进入：只需要改导出器读取 candidate.source，不需要回填；
- 在导出修复和隔离重导验证完成前，仍不应启动全量知识映射；
- 不修改任何 QCore 数据/发布状态/索引。

---

## 7. 只读证据文件

```text
_dsh/workpackage_a/authoritative_published.json
_dsh/workpackage_a/reconciliation.json
_dsh/workpackage_a/p0_publication_truth.json
```

相关代码权威注释：

```text
Question Core/question_core/persistence/repository.py:537-542
```
