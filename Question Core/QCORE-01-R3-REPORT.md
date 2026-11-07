# QCORE-01-R3 — 契约核心不变量修复

**执行方**：MIMO
**依据**：Owner 裁决（QCORE-01-R2 不通过，保留设计，F1–F4 + N1/N5/N7/N8/N9 最小修复）
**状态**：已完成，停止开发，等待 DSH 定点复审
**日期**：2026-11-07

---

## 1. 修复范围

本轮**仅**处理以下内容：

| 编号 | 问题 | 修复内容 |
|---|---|---|
| **F1** | 关键 Evidence 冲突不阻止审批 | Revision validator + approve/publish 双路径拒绝 `unresolved+critical` |
| **F2** | Strict 边界与完整性脱节 | `not_attributable→incomplete` 强制；`table_row` 必须有 locator+value；答案缺失→候选 incomplete |
| **F3** | Student Upload 权限字段矛盾 | 权限字段移至 source 分支单一来源；`public_bank` 拒绝；默认 `suspected`/`no_redistribution`；删除 `or True` |
| **F4** | Revision 可被原地修改 | 全模型 `frozen=True` + `tuple` 容器（深层不可变）；`content_hash` 与内容规范哈希强制一致 |
| **N1** | `candidate_id: object` | → `UUID` |
| **N5** | IngestionIdentity 接受空哈希 | → 至少一个输入哈希强制 |
| **N7** | EvidenceConflict 与 Evidence target_path 可不一致 | → 必须同一字段 |
| **N8** | ALL_MODELS 缺 CandidateCore | → 补入（45 个模型） |
| **N9** | Golden Aggregate digest 测试跳过 | → 固定 UUID/时间戳，全量断言 |

**未处理**（Owner 裁定后移）：N2（explanation_blocks 类型）、N3（图片/材料悬空引用）、N4（content_hash 规范化算法版本化）、N6（撤回后重新发布）。

---

## 2. 项目归属确认

契约资产已从 `DeepTutor/integrations/question_core/` 迁移至独立项目：

```
D:\Project\AITutors\Question Core\
├── question_core/              # Python 包
│   ├── contracts/v1/           # 9 个契约模块
│   ├── schema/v1/              # JSON Schema（生成物）
│   └── golden/v1/              # Golden Snapshot + Contract Manifest
├── tests/                      # 13 个测试文件
└── QCORE-01-R3-REPORT.md
```

- DeepTutor `integrations/` 目录**已清理**（全部为本轮新建，无既有代码）
- DeepTutor 既有 3 处修改 + 3 个未跟踪文件**零触碰**
- 导入路径 `question_core.contracts.v1`，与 DeepTutor 解耦

---

## 3. F1 — Evidence 冲突阻止审批与发布

### 修复机制（双路径）

**路径 A — Revision 模型层（权威）**：`Revision._state_binding` validator 在 state 为 `approved` 或 `published` 时检查 `evidence.unresolved_critical()`，发现即拒绝构造。

**路径 B — 状态转换函数（纵深防御）**：`approve_revision` / `publish_revision` 增加可选 `evidence` 参数，调用 `has_blocking_conflicts(evidence)` 后拒绝。

### 覆盖矩阵

| 情况 | 行为 |
|---|---|
| `unresolved + is_critical=True` | **拒绝** approved / published |
| `human_adjudicated + resolved_by + winner` | 允许 |
| `is_critical=False`（非关键冲突） | 允许 |
| 无冲突 | 允许 |

---

## 4. F2 — Strict 与完整性联动

### 新增约束

1. **`StrictAnswerDeclaration`**：`table_row` 必须有 `table_row_locator` + `declared_value`（缺一拒绝）。
2. **`PreprocessingCandidate` validator**：
   - `answer_declaration.attribution=not_attributable` → `core.completeness` 必须 `incomplete`
   - 任一 answer 为 `absent`/`unknown` → `core.completeness` 必须 `incomplete`
3. **语义澄清**：`answer_completeness`（TypedAnswer 级）表达单个答案的完整性；`core.completeness`（Candidate 级）是全候选完整性。答案缺失或无法归属 → 候选整体 incomplete → 不具备审批资格（但审核工作台仍可完整查看）。

---

## 5. F3 — 权限字段统一

### 修复前（矛盾类）

```
core.owner_scope = public_bank     vs    source.owner_scope = student
core.pii_status = none             vs    source.pii_status = suspected
core.distribution_policy = unknown vs    source.distribution_policy = no_redistribution
```

### 修复后（单一来源）

- `CandidateCore` **删除** `owner_scope` / `pii_status` / `distribution_policy`
- `PreprocessingSource` **新增** 三项（默认 `public_bank` / `none` / `unknown`）
- `StudentUploadSource` 已有三项，新增校验：
  - `owner_scope=public_bank` **拒绝**（公开化是显式后续动作）
  - 默认 `pii_status=SUSPECTED`（照片可能含姓名）
  - 默认 `distribution_policy=NO_REDISTRIBUTION`
- Golden Snapshot 中矛盾已消除
- `or True` 断言已删除，替换为 `not hasattr(core, "owner_scope")` 等有效断言

---

## 6. F4 — 不可变性与 hash 绑定

### 深层不可变

- 全部 45 个契约模型 `frozen=True`（`ContractModel` 基类）
- 全部 31 个集合字段 `list[X]` → `tuple[X, ...]`（原地修改也不可能）
- `QuestionIdentity` / `Revision` / `ApprovalRecord` / `PublicationRecord` 全部不可变

### content_hash 可验证

```
content_hash == canonical_content_hash(content, answers, explanation_blocks)
```

- `canonical_content_hash(*models)`：`model_dump(mode="json")` → canonical JSON → SHA-256
- `Revision` validator 强制一致性（不一致拒绝构造）
- `Revision.create()` 类方法：正确构造入口，hash 自动派生
- **注意**：此为 N4 的最小版本（provisional algorithm v0），QCORE-02 前须正式化算法与版本

---

## 7. N1/N5/N7/N8/N9 修复

| 编号 | 修复 | 验证测试 |
|---|---|---|
| N1 | `candidate_id: UUID` | `test_rejects_non_uuid` |
| N5 | IngestionIdentity 拒绝空哈希 | `test_empty_hashes_rejected` |
| N7 | Conflict target_path 必须与 Evidence 一致 | `test_conflict_target_mismatch_rejected` |
| N8 | ALL_MODELS 含 CandidateCore（45 个） | `test_candidate_core_in_all_models` |
| N9 | Golden Aggregate digest 全量断言 | `test_aggregate_digest_is_stable` |

---

## 8. 反例测试

`tests/test_invariants.py` 25 项，逐一构造 DSH 反例并断言拒绝：

- **F1** × 4：未解决冲突拒 approved / 拒 published / 已解决允许 / 非关键允许
- **F2** × 3：not_attributable+complete 拒 / table_row 无 locator 拒 / 无 value 拒
- **F3** × 4：public_bank 拒 / core 无权限字段 / 保守默认值 / golden 无矛盾
- **F4** × 8：content/嵌套/identity/审批/发布记录不可改 / hash 不匹配拒 / answers 不可追加
- **N** × 6：N1/N5/N7/N8/N9 各项

---

## 9. 测试执行命令与实际结果

### 命令

```powershell
cd "D:\Project\AITutors\Question Core"
D:\Project\AITutors\DeepTutor\.venv\Scripts\python.exe -m pytest tests -v --tb=short
```

### 结果

```
============================= 242 passed in 0.67s =============================
```

**242 passed / 0 failed / 0 errors**

| 分类 | 项数 |
|---|---|
| 原有回归（schema/answer/evidence/state/content/candidate/strict/idempotency/visibility/question/real_samples） | 217 |
| F1–F4 + N1–N9 反例测试 | 25 |
| **合计** | **242** |

原有 217 项**零回归**。

---

## 10. Schema / Manifest

| 项 | 值 |
|---|---|
| schema_hash | `0cba7f5a0c0f85bb024bbb99fda381f2a20e0e4a783390a1e4b3710a601a4f14` |
| 模型数 | 45（+CandidateCore） |
| $defs 数 | 60 |
| JSON Schema | draft 2020-12 |
| 磁盘 schema == 重新生成 | ✅ |
| manifest hash == computed | ✅ |

---

## 11. Git 状态

### Question Core（新项目，无 git 仓库）

全部文件为新建。路径：`D:\Project\AITutors\Question Core\`

### DeepTutor

| 项 | 值 |
|---|---|
| 分支 | `main` @ `60fb3bdf` (release: v1.7.2) |
| 本轮改动 | **零** |
| 既有修改 | `mimic_source.py` / `add_documents.py` / `kb.py` — **未触碰** |
| 既有未跟踪 | `preprocessed_source.py` / `preprocessed_papers.py` / `test_preprocessed_papers.py` — **未触碰** |
| `integrations/` | 已清理（本轮新建后随迁移移除） |

---

## 12. 与 V3 隔离确认

- 本轮**零文件**来自 V3 / AITutor-X / Preprocessing 代码
- 契约模块仅依赖 Pydantic v2 标准库
- 未导入 / 未引用 / 未修改任何旧管线模块
- Preprocessing 样本验证**只读**

---

## 13. 已知限制

1. **content_hash 算法为 provisional**（N4 后续）：当前 canonical JSON + SHA-256，QCORE-02 前须正式化算法版本与变更策略。
2. **explanation_blocks 类型**（N2 后续）：当前 `tuple`（untyped）。
3. **图片/材料悬空引用**（N3 后续）：当前不检查 `ImageBlock.asset_id` 是否存在于 `assets`。
4. **撤回后无法重新发布**（N6 后续）：`WITHDRAWN → PUBLISHED` 转换已允许，但需验证 hash 一致性——在 Publication 服务阶段处理。
5. **无数据库 / 无 API / 无 Adapter**（符合禁令）。

---

## 14. 明确未做事项

- ✗ PostgreSQL / Alembic / FastAPI / Strict Adapter / 审核前端
- ✗ 真实 Question 导入 / 批量试卷导入
- ✗ Preprocessing 修改 / 旧 V3 E2E 重跑
- ✗ N2 / N3 / N4 / N6 完整实现
- ✗ 架构重做 / 模型重写

---

**停止开发，等待 DSH 定点复审。**

DSH 复审范围（Owner 裁定）：验证 F1–F4 反例是否真正失败、N1/N5/N7/N8/N9 是否修复、原有 217 项无回归、Revision 不可变与 hash 绑定不可绕过。不重审架构，不重查 48 份样本。
