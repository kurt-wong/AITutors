# EULER-SEMANTIC-EMBEDDING-V1.1-MULTI-CANDIDATE-01

- 执行：DSH
- 日期：2026-11-25
- 决策来源：Owner 选择“整页拍照 → 返回多个候选 → 用户选择目标题”
- 关联：`EULER-SEMANTIC-EMBEDDING-V1.1-REAL-PHOTO-VALIDATION-01`
- 数据：45 张真实相机照片（iPhone 12 Pro Max，原始文件名）
- 冻结配置：`.74/.85/.55`，未调阈值
- 代码：`tsc_compiler/semantic/v11/multi.py` + CLI `multi`
- **状态：候选覆盖原型 PASS；生产默认模型仍不切换**

---

## 1. 交互契约

整页照片允许包含多道题；系统**不再返回单一自动 Exact**，而是：

1. 按题号把整页 OCR 切成多个问题段；
2. 每段检索 top-5 候选；
3. 整页再检索 top-10 作为兜底；
4. 按 `question_id` 去重、按分数排序；
5. 返回候选列表（默认最多 20），每条都标记 `requires_user_selection=true`；
6. 顶层 `auto_exact=null`，`status=needs_user_selection`。

用户从候选中选择目标题后，才进入后续讲题/确认流程。

关键点：

- **不允许**系统直接选 top1 作为 Exact；
- **不允许**把候选列表中的错误题当作已确认身份；
- 候选只是“供用户选择”，不是 Question 身份变更。

---

## 2. 实现

`tsc_compiler/semantic/v11/multi.py`：

- `split_questions()`：按行首题号 `1. / 2、/ 3．` 切段；
- `MultiCandidateIndex.search()`：
  - 每段独立检索；
  - 整页检索兜底；
  - 合并去重；
  - 每条候选带 `rank/relation/segments/requires_user_selection`；
  - 永不设置自动 Exact。

CLI：

```bash
python -m tsc_compiler.semantic.v11.cli multi \
  --index runs/qcore_semantic_expansion_01/v11/index_gemma2 \
  --query "<整页 OCR 文本>"
```

测试：`tests/test_semantic_v11.py` 新增分题与“绝不 auto_exact”测试，当前 **8 passed**。

---

## 3. 45 张真机照片结果

指标：目标题是否出现在候选列表前 k 位。

| 模型 | @1 | @3 | @5 | @10 | @20 | 目标缺失 | 平均候选数 |
|---|---:|---:|---:|---:|---:|---|---:|
| BGE V1 | 64.4% | 88.9% | 93.3% | **97.8%** | 97.8% | IMG_8142 | 15.24 |
| gemma-2 V1.1 | **71.1%** | **91.1%** | **95.6%** | **100%** | **100%** | **无** | 14.67 |

- gemma 的 45 个目标全部进入 top-10；
- BGE 仅差 1 张（IMG_8142），top-10 为 97.8%；
- 两模型 `auto_exact_count = 0`，即没有任何自动单一 Exact 决策。

### 与单一 Exact 的对比

| 模式 | BGE | gemma | 错误 Exact |
|---|---:|---:|---:|
| 单一 Exact（上一轮） | 20/45 | 16/45 | 4 / 4 |
| 多候选 top-10 | **44/45** | **45/45** | **0 自动 Exact** |

多候选层把“选错题”转化为“候选里让用户选”，从机制上消除了自动错题；但候选覆盖不等于最终正确率，必须依赖用户选择。

---

## 4. 候选列表的用户负担

平均 15 个候选对 UI 偏多。建议：

- 默认展示 **top-5**（gemma 95.6%，BGE 93.3%）；
- “查看更多”展开到 top-10（gemma 100%，BGE 97.8%）；
- 按题号段分组展示，而不是纯分数列表；
- 用户选择后才确认，不自动选中 top1。

---

## 5. 限制

1. 仅 45 张照片、9 科；不是统计显著结论。
2. 候选覆盖依赖 OCR 分题；若 OCR 把两题粘成一段，可能漏候选。
3. BGE 在 IMG_8142 上目标不在 top-20，说明分题/整页兜底仍有边界。
4. 还没有真实 UI；“用户选择”目前是 API 契约，不是已实现页面。
5. 仍没有独立 Similar 金标；本报告只评估 Exact 目标覆盖。
6. 生产默认模型未切换；BGE V1 仍是默认单 Exact 路径。

---

## 6. 结论与下一步

结论：

- **多候选原型 PASS**：gemma 在 45/45 张整页照片中把目标题放进 top-10，且不再自动输出单一 Exact；
- BGE 为 44/45；
- 这证明“整页拍照 + 多候选 + 用户选择”在候选覆盖上可行；
- 但不等于生产可用：需要 UI、用户选择日志、候选排序和误选成本评估。

下一步：

1. 设计候选选择 UI（top-5 + 查看更多、按题号分组）；
2. 用真实用户选择记录评估“用户能否在候选中选中目标题”；
3. 保留 BGE V1 单 Exact 路径；gemma 多候选仅作为 V1.1 candidate；
4. 任何生产切换另立任务，不因本报告自动启用。

---

## 7. 证据

| 内容 | 路径 |
|---|---|
| 多候选实现 | `Teaching Script Compiler/tsc_compiler/semantic/v11/multi.py` |
| 测试 | `Teaching Script Compiler/tests/test_semantic_v11.py` |
| 45 张真机评测 | `runs/qcore_semantic_expansion_01/v11/real_photos/multi_candidate_eval.json` |
| 单一 Exact 真机评测 | `runs/qcore_semantic_expansion_01/v11/real_photos/real_photos_eval.json` |
| 真机失败报告 | `docs/quality/EULER-SEMANTIC-EMBEDDING-V1.1-REAL-PHOTO-VALIDATION-01.md` |
