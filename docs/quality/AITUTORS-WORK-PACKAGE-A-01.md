# AITUTORS WORK PACKAGE A — QCore 数据基础与事实锁定

- 日期：2026-11-26
- 性质：只读审计 + 隔离验证方案；未修改生产 QCore
- 适用前置：工作包 A（不跑映射、不开发入口）

---

## A0. 结论

1. **当前有效发布清单 = 169 published revisions / 169 questions**；`qcore_revisions.publication_state` 列是创建时投影，不能当当前状态。
2. **state_history 是唯一权威**：最新 snapshot 为 published 169、withdrawn 18、unpublished 6；187/193 条列值与历史差异已完全解释。
3. 18 withdrawn 全部有更高 revision 的 published 替代；6 unpublished 与 Compiler `skipped_unpublished=6` 一致。
4. **169 不是 stale snapshot**：Compiler catalog/bundle 的 169 与 state_history 的 169 逐身份一致。
5. **subject/grade 没有丢失**：193/193 candidate.source 都有；真正的问题是 catalog/export 用 `source_document_id` 推导学科，忽略了权威值。
6. 因此 P0-1 不是“207 条回填”，而是 **修正导出/索引读取路径**。
7. 工作包 A 的 P0-0 已锁定；可以进入 P0-1 隔离修复，但仍不启动全量映射。

---

## A1. P0-0：published 真相

### 权威来源

`Question Core/question_core/persistence/repository.py:537-542` 明确：

> `qcore_revisions.review_state / publication_state / completeness` 是创建时快照，不读回作为当前状态；`qcore_state_history` 是唯一当前生命周期权威。

### 最新 state_history

| 状态 | revisions |
|---|---:|
| published | 169 |
| withdrawn | 18 |
| unpublished | 6 |
| 合计 | 193 |

列级值全部是 `unpublished`（创建时），所以 187 条不一致 = 169 published + 18 withdrawn；6 条一致为 unpublished。

18 条 withdrawn 均有更高 revision_number 的 published revision 替代；6 条 unpublished 从未发布。

### 当前发布清单

```text
published = 169 questions / 169 revisions
SHA256 = 9a852ddc1d9849fbd9acf6d6194975363669637c384c5947c7ce6c01960be02f
```

证据：`_dsh/workpackage_a/authoritative_published.json`。

### 与 Compiler 对应

| 项 | 数量 |
|---|---:|
| published qids | 169 |
| catalog qids | 169 |
| bundle qids | 169 |
| published ∩ catalog | 169 |
| published without bundle | 0 |

169 不是 stale；它与 catalog/bundle 身份一致。

`index_prod` 175 qid 包含 6 unpublished，不是 published-only 索引；不能把 175 当发布清单。

### 结论

- 当前有效发布 = **169**；
- 18 withdrawn 是旧 revision，不恢复；
- 6 unpublished 保持未发布；
- 不需要重建/恢复发布清单；
- 需要修正的是导出路径，不是发布状态。

---

## A2. P0-1：subject/grade 传递

### 事实

`qcore_candidates.payload.source` 已包含：

```json
{
  "grade": "高三",
  "subject": "语文",
  "source_document_id": "2022全国乙卷高考真题语文（教师版）(1)/U1"
}
```

抽样统计：

- `qcore_six_subject_accept_01`：数学 45、生物 37、英语 36、物理 34、化学 32、语文 9；
- `qcore_semantic_expansion_01`：政治/历史/生物/英语/数学/地理等；
- `qcore_g4_final_01`：生物/数学/化学/英语/物理/语文。

**所以不是数据缺失，也不是 Adapter 丢失。**

### 真正的问题

`Revision` 本身没有 subject/grade；`semantic/export.py` 与 `qcore_source.py` 使用：

```python
subject = subject_of(source_document_id)
```

即按文件名关键词推导，而不是使用 candidate.source 的权威字段。

### 正确修复方向

1. catalog/export 读取 `candidate.source.subject/grade`；
2. 若 candidate 不可达，才回退到 manifest/source_document_id；
3. 不得用题干猜测，也不得用文件名覆盖权威值；
4. 保持 Question/Revision 内容和身份不变；
5. 在隔离库重导 catalog，验证 subject/grade 分布与 candidate.source 一致。

这不是 207 条回填，而是**导出路径修复 + 隔离重导验证**。

---

## A3. P0-2：文件入口事实

- `.doc/.xls/.ppt` 不支持；
- 扫描 PDF 默认不 OCR（`text_only`）；
- 图片附件只送 vision，不 OCR；
- 没有 multipart 聊天上传端点；
- 没有通用后台队列；只有 KB indexing journal。

这些属于工作包 A 的入口前置，不属于知识映射。

---

## A4. 隔离验证方案（不写生产）

```text
1. 克隆/复制目标 QCore DB 到隔离库（或使用现有隔离库）
2. 修复 catalog/export：candidate.source → subject/grade
3. 重导 catalog
4. 对比：
   - subject/grade 与 candidate.source 100% 一致
   - Question/Revision 内容 hash 不变
   - published 状态不变（当前为 0）
5. 输出 diff 报告；不发布、不写生产
```

验收：

- 不产生任何 QCore 内容修改；
- 不产生 publish；
- subject/grade 分布可追溯；
- published 清单仍为空，直到 Owner 决定重新发布。

---

## A5. 当前唯一可信结论

```text
生产数据源 = qcore_six_subject_accept_01
当前权威 = state_history latest snapshot
published = 169 revisions / 169 questions
withdrawn = 18 old revisions（均有更新 published）
unpublished = 6
published hash = 9a852ddc...
Compiler catalog/bundles = 169/169 匹配
subject/grade = 193/193 candidate.source 有值
导出器 = 忽略 candidate.source
```

所以工作包 A 的下一步不是“恢复发布”，而是：

1. 修正 catalog/export 读取 candidate.source 的 subject/grade；
2. 隔离重导验证；
3. 不改发布状态，不重建生产索引；
4. 验证完成后再考虑 B 阶段映射。

---

## A6. 产物

- 只读探针输出：`_dsh/workpackage_a/p0_publication_truth.json`
- 源字段探针：`_dsh/workpackage_a/source_probe.py`
- 本报告：`docs/quality/AITUTORS-WORK-PACKAGE-A-01.md`
