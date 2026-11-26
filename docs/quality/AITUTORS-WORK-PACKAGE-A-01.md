# AITUTORS WORK PACKAGE A — QCore 数据基础与事实锁定

- 日期：2026-11-26
- 性质：只读审计 + 隔离验证方案；未修改生产 QCore
- 适用前置：工作包 A（不跑映射、不开发入口）

---

## A0. 结论

1. **当前本地所有 QCore DB 的 published 列表为空**；只读查询 `publication_state='published'` 返回 0 行。
2. **Compiler 的 169 published 是 2026-11-24 的 stale snapshot**，不是当前 DB 状态。
3. `index_prod` 有 175 个 qid，不是 published-only 索引；`index_final` 1166 个 qid。不能把 169/175 当当前发布事实。
4. **subject/grade 没有丢失**：`qcore_candidates.payload.source.subject/grade` 已填充；真正的问题是 catalog/export 用 `source_document_id` 推导学科，忽略了 candidate.source 的权威值。
5. 因此 P0-1 不是“207 条回填”，而是 **修正导出/索引读取路径**。
6. 在工作包 A 完成前，不应把任何 QCore 检索结果当作正式发布结果，也不应启动全量知识映射。

---

## A1. P0-0：published 真相

### 只读查询

连接：`127.0.0.1:55432`，只读事务；数据库清单 13 个 `qcore_*`。

结果：

| 数据库 | questions | revisions | published rows |
|---|---:|---:|---:|
| qcore_six_subject_accept_01 | 175 | 193 | 0 |
| qcore_g4_final_01 | 207 | 207 | 0 |
| qcore_semantic_expansion_01 | 1166 | 1166 | 0 |
| qcore_student_integration_01 | 38 | 40 | 0 |
| qcore_english_repair_01 | 175 | 187 | 0 |
| qcore_qiqi_repair_01 | 175 | 189 | 0 |
| qcore_qiqi_rereocr_01 | 175 | 193 | 0 |
| qcore_prebulk_accept_01 | 64 | 105 | 0 |
| qcore_d9_drill_01 | 184 | 184 | 0 |

所有 revision 的 `publication_state` 均为 `unpublished`，review 为 `pending_review` 或 `not_ready`。

**当前发布清单：空**  
**published list SHA256：**

```text
e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
```

（这是空字符串的 SHA256。）

### 与 Compiler snapshot 的矛盾

`Teaching Script Compiler/data/qcore/meta.json`：

```json
{
  "built_at": "2026-11-24T14:08:16Z",
  "database": "qcore_six_subject_accept_01",
  "published_bundles": 169,
  "questions_scanned": 175
}
```

`index_prod`：

- docs = 175
- qids = 175
- qid SHA256 = `9dea79b3...`

这说明：

- 169 是 11-24 构建时的历史快照；
- index_prod 是 175 条（不是 169 条 published-only）；
- 当前 DB 已经没有任何 published revision；
- **不能用 169 或 175 作为当前发布清单**。

### 必须由 Owner/后续任务决定

- 这是“发布状态被重置”还是“生产/隔离库选错”；
- 是否重新走 publish/Admission；
- Compiler 是否必须 fail-closed 到“0 published”，不能继续读 stale snapshot；
- 169 个旧 bundle 是否隔离/重建。

未做：没有重建索引、没有 publish、没有改 DB。

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
当前 QCore 本地 published = 0
169 = stale snapshot
subject/grade = candidate.source 中存在
导出器 = 忽略 candidate.source
```

所以工作包 A 的下一步不是“回填”，而是：

1. 确定哪个 DB/流程是当前生产事实源；
2. 修复导出器读取 candidate.source；
3. 隔离重导验证；
4. 再由 Owner 决定是否重新 publish。

---

## A6. 产物

- 只读探针输出：`_dsh/workpackage_a/p0_publication_truth.json`
- 源字段探针：`_dsh/workpackage_a/source_probe.py`
- 本报告：`docs/quality/AITUTORS-WORK-PACKAGE-A-01.md`
