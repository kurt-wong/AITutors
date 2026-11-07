# QCORE-01-R4 — 最终契约不变量补齐

**执行方**：MIMO
**依据**：Owner 对 QCORE-01-R3 DSH 定点复审报告的裁决
**状态**：已完成，停止开发，等待 DSH 最后一次定点复审
**日期**：2026-11-07
**工作目录**：`D:\Project\AITutors\Question Core`

---

## 1. 修改文件清单

| 文件 | 变更 |
|---|---|
| `question_core/contracts/v1/common.py` | 新增 `UnsafeModelCopyError`；`ContractModel.model_copy` 封闭非空 update；文档标注 `model_construct` 禁用 |
| `question_core/contracts/v1/candidate.py` | F2：`_strict_completeness_link` 重写为五条件强制；新增 `_assert_declared_value_represented` |
| `question_core/contracts/v1/state.py` | 三处 `model_copy(update=…)` → `_transition()`（走 `model_validate`） |
| `question_core/contracts/v1/__init__.py` | 导出 `UnsafeModelCopyError` |
| `tests/test_invariants.py` | 追加 12 项 R4 反例（F2×6 + F4×6） |
| `tests/test_state_machine.py` | `test_review_only_visibility…` 补 `answer_declaration` |
| `tests/golden_samples.py` | `model_copy(update=…)` → `model_validate` |
| `tests/test_evidence.py` | `model_copy(update=…)` → `model_validate` |
| `tests/test_question_revision.py` | `model_copy(update=…)` → `model_validate` |
| `tests/test_state_machine.py` | `model_copy(update=…)` → `model_validate`（aggregate 测试） |

**Schema/Golden 重新生成**：hash 不变（`0cba7f5a…`），模型结构未改动。

---

## 2. F2 修复：PreprocessingCandidate complete 五条件

### 校验规则

当 `core.completeness == COMPLETE` 时，**全部**满足：

| 条件 | 不满足时错误 |
|---|---|
| 1. `source.answer_declaration` 存在 | `answer_declaration to be present` |
| 2. `attribution` ≠ `not_attributable` | `requires an attributable answer_declaration` |
| 3. `core.answers` 非空 | `at least one TypedAnswer` |
| 4. 每个 Answer 的 `completeness == FULL` | `completeness to be 'full'` |
| 5. `declared_value` 有对应 TypedAnswer | `declared answer to be represented` |

`completeness == INCOMPLETE` 的 Candidate 不受五条件约束，始终可构造。

### 反例修复前后

| 反例 | 修复前 | 修复后 |
|---|---|---|
| declaration=None + complete + 无答案 | ❌ 通过 | ✅ 拒绝（条件 1） |
| declaration=declared + complete + 无 TypedAnswer | ❌ 通过 | ✅ 拒绝（条件 3） |
| answer completeness=partial + core complete | ❌ 通过 | ✅ 拒绝（条件 4） |
| answers=() + core complete | ❌ 通过 | ✅ 拒绝（条件 3） |
| incomplete Candidate | ✅ 可构造 | ✅ 仍可构造 |
| incomplete + declared + partial answer | ✅ 可构造 | ✅ 仍可构造 |

---

## 3. F4/F1 修复：model_copy(update=…) 封闭

### 机制

`ContractModel.model_copy` 覆写：
- `update=None` / `update={}` → 正常复制
- `update=非空` → 抛出 `UnsafeModelCopyError`

### state.py 迁移

三处 `snapshot.model_copy(update=…)` 替换为 `_transition(snapshot, **updates)`，内部走 `snapshot.model_dump(mode="json")` + merge + `StateSnapshot.model_validate(data)`，触发完整校验。

### model_construct 文档标注

`ContractModel` docstring 明确：`model_construct` 是 Pydantic 低层不安全构造入口，不属于正常契约对象创建路径，业务代码禁止使用。本轮不封锁。

### 反例修复前后

| 反例 | 修复前 | 修复后 |
|---|---|---|
| `rev.model_copy(update={"content": 篡改})` | ❌ 成功，hash 不变 | ✅ `UnsafeModelCopyError` |
| `rev.model_copy(update={"evidence": 新bundle})` | ❌ 成功，绕过 F1 | ✅ `UnsafeModelCopyError` |
| `rev.model_copy(update={"state": approved_state})` | ❌ 成功，绕过审批门禁 | ✅ `UnsafeModelCopyError` |
| `ident.model_copy(update={"question_id": …})` | ❌ 成功，身份被改写 | ✅ `UnsafeModelCopyError` |
| `rev.model_copy()`（无 update） | ✅ 正常 | ✅ 仍正常 |
| `rev.model_copy(update={})` | ✅ 正常 | ✅ 仍正常 |

---

## 4. 测试执行命令与实际结果

### 命令

```powershell
cd "D:\Project\AITutors\Question Core"
D:\Project\AITutors\DeepTutor\.venv\Scripts\python.exe -m pytest tests -q --tb=short
```

### 结果

```
============================= 254 passed in 0.61s =============================
```

**254 passed / 0 failed / 0 errors**

| 分类 | 项数 |
|---|---|
| R3 原有回归（schema/answer/evidence/state/content/candidate/strict/idempotency/visibility/question/real_samples） | 217 |
| R3 反例（F1–F4 + N1–N9） | 25 |
| **R4 新增反例（F2 complete 五条件 ×6 + F4 model_copy ×6）** | **12** |
| **合计** | **254** |

R3 的 242 项**零回归**。254 = 242 + 12。

---

## 5. Schema / Manifest / Golden 检查

| 项 | 值 |
|---|---|
| schema_hash | `0cba7f5a0c0f85bb024bbb99fda381f2a20e0e4a783390a1e4b3710a601a4f14` |
| 磁盘 schema == 重新生成 | ✅ |
| manifest hash == computed | ✅ |
| Golden digest（3 份） | 与 `golden_digests.json` 一致 |
| 模型数 | 45 |
| $defs 数 | 57 |

---

## 6. 旧系统隔离确认

| 检查项 | 结果 |
|---|---|
| 契约代码导入 V3 / AITutor-X 运行时 | ✅ 零 |
| 契约代码导入 DeepTutor 模块 | ✅ 零 |
| 契约代码导入 Preprocessing 代码 | ✅ 零 |
| 外部依赖 | 仅 Pydantic v2 + 标准库 |
| 契约代码中残留 `model_copy(update=非空)` 调用 | ✅ 零（仅 override 本身与 docstring） |

---

## 7. 未处理事项

| 编号 | 内容 | 状态 |
|---|---|---|
| N2 | `explanation_blocks` 类型 | 后移（Adapter 前） |
| N3 | 图片/材料悬空引用 | 后移（Adapter 前） |
| N4 | content_hash 规范化算法版本化 | 后移（QCORE-02 前） |
| N6 | 撤回后重新发布 | 后移（Publication 服务阶段） |
| model_construct 封锁 | 文档标注已完成，不封锁 | 后移（Pydantic API 加固） |

---

## 8. 停止条件确认

- ✅ 仅修复 F2 + F4/F1 两项
- ✅ 未新增 PostgreSQL / Alembic / FastAPI / Strict Adapter / 审核前端
- ✅ 未重新设计架构 / 重写模型
- ✅ 未处理 N2/N3/N4/N6
- ✅ 未修改 DeepTutor / Preprocessing / V3
- ✅ 保留 R3 全部已通过修复

**停止开发，等待 DSH 最后一次定点复审。**

---

## 附录：R4 反例测试清单

| 测试 | 验证 |
|---|---|
| `test_declaration_none_plus_complete_rejected` | F2-1 |
| `test_declared_but_no_typed_answer_rejected` | F2-2 |
| `test_partial_answer_plus_complete_rejected` | F2-3 |
| `test_empty_answers_plus_complete_rejected` | F2-4 |
| `test_incomplete_candidate_still_constructible` | F2-5 |
| `test_incomplete_with_declared_answer_still_constructible` | F2-5b |
| `test_revision_content_cannot_be_replaced_via_model_copy` | F4-1 |
| `test_revision_evidence_cannot_be_replaced_via_model_copy` | F4-2 |
| `test_revision_state_cannot_bypass_approval_gate` | F4-3 |
| `test_question_identity_id_cannot_be_rewritten` | F4-4 |
| `test_plain_model_copy_still_works` | F4-5 |
| `test_empty_update_dict_also_rejected_or_passes` | F4-6 |
