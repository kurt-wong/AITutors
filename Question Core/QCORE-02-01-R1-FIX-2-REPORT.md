# QCORE-02-01-R1-FIX-2 执行报告（R2 修订版）— State History 数据完整性最小修复

执行方：MIMO ｜ 审查方：DSH ｜ 范围：F1–F7 定点修复 + 证据链修订

## 0. 修订说明（本版替代初版报告）

DSH 复审结论：**F1–F7 代码与数据库行为通过**（DSH 已在主库独立重跑 392/392 并复核触发器与迁移），
但初版报告的 JUnit 证据链存在硬伤——初版 JUnit（`results_r1fix2_full.xml`，09:34:28 运行）与 DSH 在
09:36:21 对主库的观测（alembic 旧 head、无触发器、config.py 仍接受 asyncpg）在时间线上矛盾，
无法证明"该 JUnit 就是在 qcore_dev_test 上运行的"。

本版按 DSH 要求完成三项补齐：

1. 以 `QCORE_TEST_DATABASE_URL` 指向 `qcore_dev_test` **重新生成 JUnit**（`results_r1fix2_full_v2.xml`）；
2. 报告中写明 JUnit 的 host/port/db/user（不含密码）；
3. 以单会话连续证据链（目标库安检 → JUnit → 落库状态复查）消除时间线歧义，并如实说明初版矛盾的分析结论。

**功能结论不变：F1–F7 全部修复属实。报告证据链以本版为准。**

## 1. 权威测试证据链（R2，单会话连续采集）

以下三步在同一条命令链中连续执行（2026-11-08 +08:00）：

**STEP 1 目标库安检（09:59:55，任何 DDL/写入之前）**——`safety.verify_test_target` 实测输出：

```text
TARGET: database=qcore_dev_test  user=qcore_app  host=127.0.0.1  port=55432
        server_version=PostgreSQL 16.15 (Debian 16.15-1.pgdg13+2)
        superuser=False  createdb=False  createrole=False
        legacy_aitutors_databases=0
```

即 **本次 JUnit 的测试目标库 = `qcore_dev_test` @ `127.0.0.1:55432`，用户 `qcore_app`（非超管）**，
实例零 `aitutors*` 库（非旧 V3）。连接驱动 `postgresql+psycopg2`（同步）。

**STEP 2 全量测试（09:59:55 → 10:00:30）**：

```text
python -m pytest tests -q --junitxml=results_r1fix2_full_v2.xml
392 passed in 35.01s
```

**STEP 3 落库状态复查（10:00:31）**：

```text
[qcore_dev_test]         alembic_version=7e8f9a0b1c2d
                         triggers=[qcore_revisions_immutable, qcore_state_history_immutable]
                         functions=2  state_history_rows=0（测试清理后）
[qcore_dev_test_migrate] alembic_version=7e8f9a0b1c2d（同上）
```

JUnit 跑完后主库立即可查到 0003 迁移与两个触发器——JUnit 与主库状态**同会话闭合**。
JUnit 文件：`Question Core/results_r1fix2_full_v2.xml`（tests=392, failures=0, errors=0）。

## 2. 初版 JUnit 时间线矛盾的分析（如实记录）

已核实的事实：

- 初版 JUnit：tests=392，timestamp `2026-11-08T09:34:28.669954+08:00`，hostname `kurt-neo`，mtime 09:35:04。
- 0003 迁移文件创建于 09:27:51（早于该次运行）；`config.py` 驱动白名单在该次运行前已落盘。
- 该次运行的 `target_evidence` 夹具在任何 DDL 之前强制校验 dbname == `qcore_dev_test`（否则整套件直接失败）；
  `test_raw_update_rejected` 等触发器依赖测试若无触发器不可能通过（UPDATE 不抛错即 fail）。
  该次 392 全过 ⇒ 运行时主库必已应用 0003。
- 套件内不存在对主库执行 downgrade 的代码路径（唯一 `downgrade base` 只作用于
  `QCORE_MIGRATION_TEST_DATABASE_URL` 指向的 `qcore_dev_test_migrate`，且有 dbname 安检锁定）。
- 09:35 之后 MIMO 侧仅执行 docker/文件/报告操作，无任何数据库连接。
- `config.py` 在该次运行的 392 项中包含 `test_asyncpg_url_rejected`（通过）——
  与"09:36 时 config.py 仍接受 asyncpg"的观测无法并存于同一文件视图。
- 容器日志在 09:30–10:00 窗口无 DDL 错误或异常记录。
- 当前两库均在 `7e8f9a0b1c2d` 且触发器齐备（DSH 重跑后与本次复查一致）。

分析结论（不掩饰未解部分）：

- 初版 JUnit **无法事后重新锚定**到 09:36 的观测状态，故不作为验收证据；
- 上述"运行内不可能性"（dbname 安检 + 触发器依赖测试）表明矛盾更可能出在
  **09:36 的探针观测面**（连接目标或文件视图与 JUnit 运行不一致），而非测试实际连错库；
  但 MIMO 无法复现 09:36 的观测，**该点保留为未解释项**，不做虚假归因；
- 本版以第 1 节的单会话闭环证据链取代初版 JUnit，作为 MIMO 侧权威测试证据；
- DSH 独立重跑（同目标 `qcore_dev_test`@55432，392/392，迁移与触发器复核通过）为双方一致的验收证据。

## 3. 三项 State History 缺陷的修复方式

文件：`question_core/persistence/repository.py`

**缺陷 1（未知 Revision 可写入）→ F1**：`append_state_snapshot` 严格顺序校验——
按 `snapshot.revision_id` 查询 `qcore_revisions`，查不到立即 `NotFoundError` 且不写入；
原 `if row is not None and ...` 静默放行模式已删除。

**缺陷 2（content_hash 不校验）→ F2**：比对 `snapshot.content_hash` 与 `RevisionRow.content_hash`，
不一致 `PersistenceError` 且不写入。

**缺陷 3（current-state 回退创建快照）→ F4**：`get_revision_current_state` 的 payload 回退分支整体删除；
无 History 返回 `None`。`get_current_state`/`get_question_aggregate` 复核确认只读 History，
Revision payload 内创建时快照仅作创建记录保留，不冒充当前状态。

## 4. 三类非法追加与关键行为实测

| 场景 | 预期 | 实际 | 测试 |
|---|---|---|---|
| 未知 revision_id | `NotFoundError` | ✅ 未写入 | `TestStrictAppendValidation::test_unknown_revision_rejected` |
| Revision 属于其他 Question | `PersistenceError` | ✅ | `test_foreign_question_revision_rejected` |
| content_hash 不匹配 | `PersistenceError` | ✅ | `test_content_hash_mismatch_rejected` |
| 合法 Revision + 正确 hash | 正常追加 | ✅ | `test_valid_revision_and_hash_append_ok` |
| 非法追加失败后 | 无新增记录 | ✅ | `test_failed_append_leaves_no_rows` |
| 聚合读取 | 不含无效 StateSnapshot | ✅ | `test_aggregate_contains_no_invalid_snapshots` |
| 无 State History | current-state = `None`（含创建快照的 Revision 也如此） | ✅ | `TestNoHistoryMeansNone::test_no_history_returns_none_even_with_creation_snapshot` |
| 有 State History | 返回最新有效状态 | ✅ | `test_with_history_returns_latest` |
| Raw SQL UPDATE history | 数据库拒绝（"append-only"） | ✅ | `TestStateHistoryDbProtection::test_raw_update_rejected` |
| Raw SQL DELETE history | 数据库拒绝（"append-only"） | ✅ | `test_raw_delete_rejected` |
| 失败事务不破坏历史 | 内容逐字段不变 | ✅ | `test_failed_mutation_preserves_history` |
| Revision 内容不可变仍有效 | "immutable" 拒绝 | ✅ | `test_revision_immutability_still_enforced` |
| asyncpg URL | 配置阶段拒绝 | ✅（直接实测 REJECT） | `test_config.py::test_asyncpg_url_rejected` |
| 同步 URL | 正常接受 | ✅（直接实测 ACCEPT×2） | `test_sync_driver_urls_accepted` |

## 5. 新增 Migration 版本

- **`7e8f9a0b1c2d`**（0003，head）：`1230cc4692f1 → 4b7c1d2e9a01 → 7e8f9a0b1c2d`，0001/0002 未动。
- 内容：`qcore_state_history_immutable` 触发器（BEFORE UPDATE OR DELETE，INSERT 放行）+ 同名回退函数；
  `downgrade()` 对称回收。
- 重复执行不产生重复对象（`test_repeated_upgrade_creates_no_duplicate_objects`：双次升级后触发器恰 2、函数恰 2）；
  数据保留测试通过。

## 6. asyncpg URL 配置限制

`config.py` 与 `safety.py` 统一白名单 `{"postgresql", "postgresql+psycopg2"}`。
本轮直接实测：`postgresql+asyncpg://…` → `ConfigurationError`（"SYNCHRONOUS SQLAlchemy layer"）；
`postgresql://…`、`postgresql+psycopg2://…` → 接受。未引入任何异步支持。

## 7. 完整测试数量（R2 权威跑）

| 测试类别 | 通过 | 失败 | 错误 |
|---|---|---|---|
| QCORE-01 契约测试 | 279 | 0 | 0 |
| 持久化单元测试（含 asyncpg 配置 2 项） | 31 | 0 | 0 |
| PostgreSQL 集成测试 | 75 | 0 | 0 |
| Migration 测试 | 7 | 0 | 0 |
| **合计** | **392** | **0** | **0** |

原始输出：`results_r1fix2_full_v2.xml`（权威）与 `results_r1fix2_full.xml`（初版，保留备查）。
原有 377 项零回归。全部真实 PostgreSQL，无 Mock/SQLite。

## 8. Schema Hash 与 Golden 对比

- Schema Hash：`0cba7f5a0c0f85bb024bbb99fda381f2a20e0e4a783390a1e4b3710a601a4f14`（不变）。
- contracts / golden / schema：零 diff（git status 空输出）。
- QCORE-01 契约未做任何修改。

## 9. 文件修改清单（本任务，与初版一致）

| 文件 | 变更 |
|---|---|
| `question_core/persistence/repository.py` | F1/F2/F3 严格校验；F4 删 fallback |
| `question_core/persistence/models.py` | state-history 触发器 SQL 常量 |
| `question_core/persistence/config.py` | F7 驱动白名单 |
| `migrations/versions/7e8f9a0b1c2d_state_history_append_only.py` | 新增 0003 |
| `tests/persistence/integration/test_pg_state_history.py` | +12 项反例 |
| `tests/persistence/integration/test_pg_migration.py` | +1 项触发器唯一性 |
| `tests/persistence/test_config.py` | +2 项 URL 配置 |
| `tests/persistence/integration/safety.py` | 驱动白名单对齐 |
| `Question Core/results_r1fix2_full_v2.xml` | 新增（R2 权威 JUnit） |
| `Question Core/QCORE-02-01-R1-FIX-2-REPORT.md` | 本报告（R2 修订版） |

## 10. Git 状态

- 未提交、未 Push、未 Rebase/Reset/Clean；HEAD 不变。
- Submodule 指针未动；contracts/golden/schema 零 diff。
- 根仓库变更项与初版报告一致（Infrastructure/、Question Core/ 工作区文件）。

## 11. Docker 三容器未动确认

| 容器 | 状态 | 说明 |
|---|---|---|
| `Aitutor-postgresql` | Up（healthy），ID 未变 | postgres:16.15 / 127.0.0.1:55432 / aitutor_postgresql_data |
| `Aitutor-minio` | Up（healthy），ID 未变 | quay.io/minio/minio:RELEASE.2025-09-07T16-13-09Z / 127.0.0.1:59000-59001 |
| `Aitutor-redis` | Up（healthy），ID 未变 | redis:8.10.1-alpine / 127.0.0.1:56379 |

本轮未删除/重建容器、Volume、数据库，未修改用户权限与 Infrastructure 配置。

## 12. 最终裁决建议

- **功能验收：PASS**（与 DSH 复审一致；DSH 主库独立重跑 392/392 + 本次 R2 闭环证据链互相印证）。
- **报告验收**：初版缺陷已按 DSH 三项要求补齐（JUnit 重跑 + 目标库写明 + 矛盾如实说明）。
  初版时间线矛盾中"MIMO 无法复现 09:36 观测"部分如实保留为未解释项，不做虚假归因。

本任务到此停止，等待 Owner 与 DSH 复核，不自动启动 QCORE-02-02。
