# QCORE-01-R5 — 多类型答案声明一致性修复

**执行方**：MIMO
**依据**：Owner 对 QCORE-01-R4 DSH 复审报告的裁决
**状态**：已完成，停止开发，等待 DSH 最后一次定点复审
**日期**：2026-11-07
**工作目录**：`D:\Project\AITutors\Question Core`

---

## 1. 修改文件清单

| 文件 | 变更 |
|---|---|
| `question_core/contracts/v1/candidate.py` | 重写 `_assert_declared_value_represented`；新增类型感知辅助函数（`_norm` / `_parse_choice_labels` / `_parse_blank_items` / `_parse_composite_pairs` / `_answer_matches_declared` / `_match_composite` / `_match_multi_step`）；条件 4 增加递归子答案 completeness 检查 |
| `tests/test_invariants.py` | 追加 21 项 R5 反例（`TestF2MultiTypeDeclaredValueMatching`） |

**Schema/Golden/Manifest**：hash 不变（`0cba7f5a…`），模型结构零改动。

---

## 2. `_assert_declared_value_represented` 修复

### 核心变更

从「any answer contains declared_value as substring」改为「type-aware, deterministic full correspondence」。

### 各类型匹配规则

| 答案类型 | 匹配原则 | 通过条件 | 拒绝条件 |
|---|---|---|---|
| **单选** | 规范化后精确匹配 | `B` ≡ `B`（含全角 `Ｂ`） | `C` ≠ `B` |
| **多选** | 标签**集合完全相等**（非子集） | `BC` ≡ `("B","C")`；`A、C` ≡ `("A","C")` | `A` ≠ `("A","C")`；`B` ≠ `("A","C")`；`ABCD` ≠ `("A","C")` |
| **多空填空** | 逐项按顺序对应 | `(1).B (2).D (3).A (4).C` ≡ `("B","D","A","C")` | 缺一项；顺序颠倒 |
| **复合题** | 递归检查，全子题覆盖 | `9.D 10.B` ≡ Sub(9,D)+Sub(10,B)；`(1).A (2).C` ≡ Sub((1),A)+Sub((2),C) | 缺子答案；子答案不 FULL；只覆盖部分子答案 |
| **多步骤** | 全步骤+final_result 逐项出现 | 步骤1+步骤2+final 都在声明中 | 缺任一步骤；缺 final_result |

### 关键边界（Owner 裁定）

1. **不做局部匹配**：`A` 不能匹配 `("A","C")`（集合必须完全相等）
2. **复合递归**：父级声明不能掩盖缺失/不完整的子答案
3. **不猜语义**：无法确定对应关系 → 保留 `incomplete`

---

## 3. 各类型通过/拒绝反例

### 单选

| 声明 | 答案 | 结果 |
|---|---|---|
| `B` | SingleChoice("B") | ✅ 通过 |
| `C` | SingleChoice("B") | ❌ 拒绝 |
| `Ｂ`（全角） | SingleChoice("B") | ✅ 通过 |

### 多选

| 声明 | 答案 | 结果 |
|---|---|---|
| `BC` | MultiChoice(["B","C"]) | ✅ 通过 |
| `A、C` | MultiChoice(["A","C"]) | ✅ 通过 |
| `ABC` | MultiChoice(["A","B","C"]) | ✅ 通过 |
| `A` | MultiChoice(["A","C"]) | ❌ 拒绝（部分匹配） |
| `B` | MultiChoice(["A","C"]) | ❌ 拒绝（错误标签） |
| `ABCD` | MultiChoice(["A","C"]) | ❌ 拒绝（多余标签） |

### 多空填空

| 声明 | 答案 | 结果 |
|---|---|---|
| `(1).B (2).D (3).A (4).C` | FillBlank(["B","D","A","C"]) | ✅ 通过 |
| `B,D,A,C` | FillBlank(["B","D","A","C"]) | ✅ 通过 |
| `(1).B (2).D (3).A` | FillBlank(["B","D","A","C"]) | ❌ 拒绝（缺项） |
| `(1).C (2).D (3).A (4).B` | FillBlank(["B","D","A","C"]) | ❌ 拒绝（错序） |

### 复合题

| 声明 | 答案 | 结果 |
|---|---|---|
| `9.D 10.B` | Composite[Sub(9,D), Sub(10,B)] | ✅ 通过 |
| `(1).A (2).C` | Composite[Sub((1),A), Sub((2),C)] | ✅ 通过 |
| `9.D` | Composite[Sub(9,D), Sub(10,B)] | ❌ 拒绝（缺子答案） |
| `9.D 10.B` | Composite[Sub(9,D,FULL), Sub(10,B,PARTIAL)] | ❌ 拒绝（子答案不完整） |

### 多步骤

| 声明 | 答案 | 结果 |
|---|---|---|
| `解：设物质的量为 n，n = cV = 0.010 mol。答：0.010 mol` | MultiStep(["设物质的量为 n","n = cV = 0.010 mol"], final="0.010 mol") | ✅ 通过 |
| `设物质的量为 n，n = cV` | MultiStep(["设物质的量为 n","n = cV"], final="0.010 mol") | ❌ 拒绝（缺 final） |
| `解：设物质的量为 n` | MultiStep(["设物质的量为 n","n = cV = 0.010 mol"], final="0.010 mol") | ❌ 拒绝（缺步骤） |

---

## 4. 测试执行命令与实际结果

### 命令

```powershell
cd "D:\Project\AITutors\Question Core"
D:\Project\AITutors\DeepTutor\.venv\Scripts\python.exe -m pytest tests -q --tb=short
```

### 结果

```
collected 275 items
275 passed in 0.63s
```

**275 collected / 275 passed / 0 failed / 0 errors**

| 分类 | 项数 |
|---|---|
| R3 原有回归 | 217 |
| R3 不变量测试 | 25 |
| R4 新增测试 | 12 |
| **R5 新增多类型反例** | **21** |
| **合计** | **275** |

R4 的 254 项**零回归**。275 = 254 + 21。

---

## 5. Schema / Manifest / Golden 检查

| 项 | 值 |
|---|---|
| schema_hash | `0cba7f5a0c0f85bb024bbb99fda381f2a20e0e4a783390a1e4b3710a601a4f14` |
| 磁盘 schema == 生成 | ✅ |
| manifest hash == computed | ✅ |
| Golden digest（3 份） | 无非预期变化 |
| 模型结构改动 | **零** |

---

## 6. 旧系统隔离确认

| 检查项 | 结果 |
|---|---|
| 导入 V3 / AITutor-X / DeepTutor / Preprocessing | ✅ 零 |
| 外部依赖 | 仅 Pydantic v2 + 标准库 |
| Answer 模型重构 | 无 |
| 新增 Answer 类型 | 无 |

---

## 7. 未处理事项

| 编号 | 内容 | 状态 |
|---|---|---|
| N2 | `explanation_blocks` 类型 | 后移 |
| N3 | 图片/材料悬空引用 | 后移 |
| N4 | content_hash 算法版本化 | 后移 |
| N6 | 撤回后重新发布 | 后移 |

---

## 8. 停止条件确认

- ✅ 仅修复 `_assert_declared_value_represented` 多类型匹配
- ✅ 保留 R4 五项完整性规则，未删除第五项
- ✅ 未重构 Answer 模型 / 新增类型 / 改架构
- ✅ 未修改 DeepTutor / Preprocessing / V3
- ✅ 未处理 N2/N3/N4/N6
- ✅ R3/R4 全部测试零回归

**停止开发，等待 DSH 对多类型答案一致性及既有回归做最后一次定点复审。**

---

## 9. DSH 复审残余阻塞修复（R5-FIX）

### 问题

`_assert_answer_fully_complete` 只对 `answer_type == "composite"` 递归，未对 `"composite_sub"` 递归到内层 `TypedAnswer`。CompositeSubAnswer 标 `full` 但内层 `SingleChoiceAnswer` 为 `partial` 时被放过。

### 修复

`candidate.py` — 递归条件扩展：

```python
if atype == "composite":
    for sub in ans.answer_value:
        self._assert_answer_fully_complete(sub)
elif atype == "composite_sub":
    self._assert_answer_fully_complete(ans.answer_value)  # ← 新增
```

### 4 项反例测试

| 测试 | 场景 | 结果 |
|---|---|---|
| `test_wrapper_full_inner_partial_rejected` | wrapper=full + inner SingleChoice=partial | ✅ 拒绝 |
| `test_grandchild_partial_rejected` | wrapper=full → inner Composite=full → 孙子=partial | ✅ 拒绝 |
| `test_full_chain_accepted` | 全链路 full | ✅ 通过 |
| `test_incomplete_never_blocked` | incomplete 不受影响 | ✅ 可构造 |

### 回归

```
279 passed in 0.61s
```

279 collected / 279 passed / 0 failed / 0 errors（275 + 4 新增）。

Schema hash `0cba7f5a…` 不变，模型结构零改动。
