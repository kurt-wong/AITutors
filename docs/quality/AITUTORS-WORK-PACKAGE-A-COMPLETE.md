# AITUTORS WORK PACKAGE A — COMPLETE REPORT

- 日期：2026-11-26
- 状态：**A1–A5 COMPLETE**
- 性质：QCore 发布事实锁定 + subject/grade 导出修复 + 隔离重导 + 生产 catalog 替换
- 未启动：six-subject-kg 映射、DeepTutor 统一入口
- 未改变：QCore 数据、发布状态、历史、索引

---

## 1. 执行摘要

工作包 A 已完成：

1. 确认生产 QCore 数据源和当前有效发布清单；
2. 解释 `qcore_revisions.publication_state` 与 `qcore_state_history` 的 187 条差异；
3. 锁定当前发布清单：**169 published / 18 withdrawn / 6 unpublished**；
4. 修正 subject/grade 导出路径，改用 candidate.source 权威值；
5. 隔离重导 catalog，169/169 验证通过；
6. 替换生产 catalog 并重启 Compiler；
7. 验证生产 QCore 数据零变化。

---

## 2. A1：发布状态事实锁定

### 数据源

```text
QCORE_DATABASE_URL
→ postgresql+psycopg2://...@127.0.0.1:55432/qcore_six_subject_accept_01
```

Compiler `data/qcore/meta.json` 也指向 `qcore_six_subject_accept_01`。

### 权威机制

`Question Core/question_core/persistence/repository.py:537-542`：

> `qcore_revisions.review_state / publication_state / completeness` 是创建时快照；
> `qcore_state_history` 是当前生命周期状态的唯一权威。

### 最新 state_history

| 状态 | revisions |
|---|---:|
| published | 169 |
| withdrawn | 18 |
| unpublished | 6 |
| 合计 | 193 |

187 条列值差异完全解释：

```text
169 published + 18 withdrawn = 187
6 unpublished = 6 条一致
```

18 withdrawn 全部有更高 revision 的 published 替代；6 unpublished 从未发布。

### 当前发布清单

```text
published = 169 questions / 169 revisions
SHA256 = 9a852ddc1d9849fbd9acf6d6194975363669637c384c5947c7ce6c01960be02f
```

证据：

```text
_dsh/workpackage_a/authoritative_published.json
_dsh/workpackage_a/published_hash_preimage.txt
```

N-A 哈希勘误：preimage 为 169 行 `question_id:revision_id`（按 question_id、revision_number 排序），无尾随换行；复算命令：

```powershell
(Get-FileHash "_dsh/workpackage_a/published_hash_preimage.txt" -Algorithm SHA256).Hash.ToLower()
```

结果与 `9a852ddc...` 一致；不是无法复现的校验值。

与 Compiler：

| 项 | 数量 |
|---|---:|
| published qids | 169 |
| catalog qids | 169 |
| bundle qids | 169 |
| published without bundle | 0 |
| bundle without published | 0 |

结论：

- 169 是当前有效发布清单；
- 列级 0 是创建时投影；
- 不需要恢复/重建 169；
- 18 withdrawn 不恢复；
- 6 unpublished 保持。

---

## 3. A2：subject/grade 导出修复

### 根因

- `qcore_candidates.payload.source.subject/grade` 有完整权威值（193/193）；
- Revision 本身没有 subject/grade；
- `semantic/export.py` / `qcore_source.build_snapshot` 使用 `source_document_id` 关键词推导；
- 导出了错误/缺失的元数据。

### 代码修复

提交：

```text
5fbc6d8c7 fix(qcore): use candidate source for subject and grade
```

文件：

```text
Teaching Script Compiler/tsc_compiler/qcore_source.py
Teaching Script Compiler/tsc_compiler/semantic/export.py
```

新增 `load_revision_source_metadata(session)`：

- 连接键：`revision.payload.content == candidate.payload.core.content`；
- 读取 `candidate.payload.source.subject/grade`；
- 对没有 instance 行的 newer revision，用 `question_id` 回退；
- 不再用文件名猜学科；
- `build_catalog_entry` 增加 `grade`。

---

## 4. A3：隔离重导

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
questions_scanned=175
published_bundles=169
skipped_unpublished=6
catalog_size=169
read_only=on
```

subject 分布：

```text
化学 29 / 数学 44 / 物理 34 / 生物 37 / 语文 7 / 英语 18
```

grade：

```text
高三 169
```

---

## 5. A4：一致性与内容不变

证据：

```text
_dsh/workpackage_a/a2_a3_verification.json
```

| 检查 | 结果 |
|---|---:|
| old/new catalog qids | 169/169 一致 |
| subject/grade vs candidate.source | 0 mismatch |
| missing source | 0 |
| content_hash/search_text/answer/printed_number/source_document_id diff | 0 |
| old/new bundle revision/content_hash diff | 0 |
| 生产 QCore 写入 | 0 |

结论：

- 只改元数据来源；
- 题目内容、Revision 身份、bundle 内容未变；
- 没有 publish/Admission/索引重建。

---

## 6. A5：生产部署与运行

已执行：

1. 备份旧 catalog：

```text
_dsh/workpackage_a/production_qcore_before_a2
```

2. 替换生产：

```text
Teaching Script Compiler/data/qcore
  catalog.json
  meta.json
  bundles/*.json
```

3. 重启 Compiler 8820。

运行核验：

```text
/health status=ok
published=169
catalog_size=169
```

4. production guard 与冻结基线全等：

```text
qcore_questions 175
qcore_revisions 193
qcore_state_history 585
published 169
unpublished 6
```

5. 生产 QCore 数据、发布状态、历史、索引均未改写。

---

## 7. 测试

```text
Teaching Script Compiler full pytest: 64 passed
```

---

## 8. 产物

```text
docs/quality/AITUTORS-QCORE-PUBLICATION-STATE-RECONCILIATION-01.md
docs/quality/AITUTORS-WORK-PACKAGE-A-01.md
docs/quality/AITUTORS-WORK-PACKAGE-A-A2-A4.md
docs/quality/AITUTORS-WORK-PACKAGE-A-COMPLETE.md

_dsh/workpackage_a/authoritative_published.json
_dsh/workpackage_a/a2_a3_verification.json
_dsh/workpackage_a/catalog_snapshot/
_dsh/workpackage_a/production_qcore_before_a2/
_dsh/workpackage_a/guard_after_a.json
```

提交：

```text
5fbc6d8c7 fix(qcore): use candidate source for subject and grade
7d6a91f2d docs(quality): record work package A export verification
```

---

## 9. 明确边界

- 工作包 A 已完成；
- **B 阶段未启动**：four thousand eight hundred twenty-nine node mapping 未跑；
- **DeepTutor 统一入口未开发**；
- 6 条 unpublished 仍未发布；
- 18 条 withdrawn 不恢复；
- 169 条 published 未被重新 publish；
- 生产 Compiler 已使用修正后的 catalog，但 QCore 内容未变。

---

## 10. 结论

```text
A1 发布事实锁定 = COMPLETE
A2 导出修复 = COMPLETE
A3 隔离重导 = COMPLETE
A4 内容/身份验证 = COMPLETE
A5 生产部署与运行 = COMPLETE
```

工作包 A 已完整跑通。下一步才可进入 B（4,829 节点 LLM 映射）。
