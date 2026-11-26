# AITUTORS WORK PACKAGE A — A2/A3/A4 执行报告

- 日期：2026-11-26
- 代码提交：`5fbc6d8c7b4402746b4fd71abbc191d004db178d`
- QCore 生产写入：0
- 发布状态变更：0
- 知识映射/统一入口：未启动

---

## A2. 导出路径修复

修改：

```text
Teaching Script Compiler/tsc_compiler/qcore_source.py
Teaching Script Compiler/tsc_compiler/semantic/export.py
```

新增 `load_revision_source_metadata(session)`：

- 以 `revision.payload.content == candidate.payload.core.content` 做确定性连接；
- 读取 `candidate.payload.source.subject/grade`；
- 对没有 instance 行的新 revision，按 `question_id` 回退到同题的 candidate source；
- 不再用 `source_document_id` 关键词推导作为 primary；
- 只有 source 不可达时保留 `subject_of()` fallback。

`build_catalog_entry` 增加 `grade` 字段；catalog/bundle 的 subject/grade 现在来自 candidate.source。

### 连接覆盖

- 193 revisions；
- content-equality 连接 193 条；
- 4 个 newer revision 没有自己的 instance 行，通过 question_id 回退；
- 169 published catalog 的 subject/grade 全部可解析。

---

## A3. 隔离重导

隔离目录：

```text
_dsh/workpackage_a/catalog_snapshot/qcore
```

命令：

```powershell
cd "D:\Project\AITutors\Teaching Script Compiler"
$env:TSC_DATA_DIR="_dsh\workpackage_a\catalog_snapshot"
python -X utf8 -m tsc_compiler.cli snapshot
```

结果：

```text
questions_scanned 175
published_bundles 169
skipped_unpublished 6
catalog_size 169
read_only on
```

隔离 catalog：

- 169 条；
- subject 分布：化学 29、数学 44、物理 34、生物 37、语文 7、英语 18；
- grade：高三 169；
- 与 candidate.source 的 subject/grade mismatch = **0**。

---

## A4. 内容与身份不变验证

验证文件：

```text
_dsh/workpackage_a/a2_a3_verification.json
```

| 检查 | 结果 |
|---|---|
| old/new catalog qids | 169/169，完全一致 |
| subject/grade 与 candidate.source | 0 mismatch |
| missing source | 0 |
| content_hash/search_text/answer/printed_number/source_document_id diff | 0 |
| old/new bundle revision/content_hash diff | 0 |
| 生产 QCore 写入 | 0 |

结论：

- 只修正了 subject/grade 的读取来源；
- Question/Revision 内容、身份、bundle 未变；
- 没有 publish/Admission/索引重建；
- 生产 QCore 数据边界未改变。

---

## A5. 生产部署与运行核验

已完成：

- 旧 catalog 备份：`_dsh/workpackage_a/production_qcore_before_a2`
- 隔离 catalog 替换生产 `Teaching Script Compiler/data/qcore`
- 169 catalog / 169 bundles；
- Compiler 重启后 `/health`：`status=ok`、`published=169`；
- 生产 catalog grade：169 条全部 `高三`；
- production guard 与冻结基线全等：

```text
qcore_questions 175 / revisions 193 / state_history 585
published 169 / unpublished 6
```

生产 QCore 数据未改写、未 publish。

---

## 测试

```text
Teaching Script Compiler full pytest: 64 passed
```

---

## 当前边界

- A1–A5 完成；
- 生产 catalog 已替换并重启 Compiler；
- QCore 生产数据、发布状态、历史、索引均未改变；
- B 阶段 six-subject-kg 映射、DeepTutor 统一入口仍未启动；
- 已完成生产 catalog 替换和 Compiler 重启；后续只需 MIMO 复查。

---

## 产物

```text
_dsh/workpackage_a/catalog_snapshot/
_dsh/workpackage_a/a2_a3_verification.json
docs/quality/AITUTORS-WORK-PACKAGE-A-A2-A4.md
```
