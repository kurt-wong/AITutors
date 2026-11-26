# EULER-QUESTION-SEGMENT-RECOVERY-01 — Assisted Gold 复核结果

- 日期：2026-11-26
- 数据：24 张真实照片（4 回归 + 20 额外）
- 状态：**assisted gold 已完成复核；仍不是独立人工从零标注**

## 1. 复核结果

| 类别 | 数量 | 说明 |
|---|---:|---|
| 人工 pass | 9 | 原始 assisted 结果直接确认 |
| 人工 issue → Query 自动裁剪 | 12 | 混入上一题尾部、下一题标题、页码、下一段材料；按 note 确定性裁剪 |
| 人工 issue → OCR 源限制 | 3 | RP04 下划线丢失、RP05 Q16/17 题号缺失、RP13 空题号不稳定 |
| 未复核 | 0 | 24 条均有 verdict |

## 2. 12 条自动裁剪

主要问题与处理：

- 下一题标题：`## 三、本大题`、`### 二、填空题`、`第Ⅱ部分`；
- 上一题选项尾部；
- 页码：`第6页/共17页`、`4 / 20`、`1/20`；
- 下一段共享材料：如 RP39 结尾“中国的经济…”；
- 重复的“阅读下面短文”下一节。

裁剪只删除 OCR 文本中的页面/相邻题内容，不补写 OCR 没有的内容。

## 3. 3 条 OCR 源限制

| 样本 | 限制 | 处理 |
|---|---|---|
| RP04 | 原文下划线未被 OCR 保留 | Query 仍含 Q7 文本；不伪造下划线 |
| RP05 | Q16/Q17 题号未识别 | Q16–19 可见内容已进入 Query；不补题号 |
| RP13 | 21/22/23 空题号不稳定 | 目标题段为 Q21 组；不补空号 |

这三条不是 Query 拼接污染，属于 OCR 源保真问题；assisted gold 中标记 `known_ocr_limit`。

## 4. 四回归核验

| 样本 | 目标 | 当前 assisted Query | 状态 |
|---|---|---|---|
| RP05 | Q16–19 | 可见 Q16–19 内容，无下一节标题 | ambiguous |
| RP39 | Q6–8 | 长江经济带材料 + Q6/Q7/Q8，无 Q5、无下一段材料 | ambiguous |
| RP40 | Q21–22 | 太阳能光热电站材料 + Q21/Q22，无页码 | ambiguous |
| RP43 | Q33 | Q33，无 Q32(4) 尾部 | ambiguous |

四条均不会自动进入 Exact；需用户/候选确认。

## 5. 产物

```text
runs/qcore_semantic_expansion_01/v11/structure_recovery/ocr_v2/assisted_gold_24.json
runs/qcore_semantic_expansion_01/v11/structure_recovery/ocr_v2/assisted_gold_final_24.json
runs/qcore_semantic_expansion_01/v11/structure_recovery/review_summary.json
runs/qcore_semantic_expansion_01/v11/structure_recovery/reviewed/*.json
```

## 6. 浏览器 E2E

新增：

```text
DeepTutor/web/tests/e2e/qcore-teach-target.audit.ts
```

运行：

```powershell
cd DeepTutor/web
$env:WEB_BASE_URL='http://127.0.0.1:3100'
npx playwright test tests/e2e/qcore-teach-target.audit.ts --project=ui-audit --workers=1
```

结果：**2 passed**

| 场景 | 断言 |
|---|---|
| 多题照片 | 上传后出现 `teach-target-selection`；选择 Q6/Q7/Q8 后出现候选；目标选择阶段消失 |
| 单题照片 | 上传后直接出现候选，不出现 `teach-target-selection` |

测试固定 OCR job 结果，跨过远端 OCR 队列；真实 OCR/Compiler 的结构返回另行做了 API smoke（structure=ambiguous, units 5-8）。真实整图 E2E 曾因远端 OCR 返回 `任务提交队列已满` 未能完成，属于外部服务限制，不是页面失败。

## 7. 仍缺

- 真实整图 E2E 受 OCR 队列限制未完整跑通；当前浏览器 E2E 是固定 OCR 边界；
- 3 条 OCR 源限制未修复，需要 PDF/OCR 层面处理，不应在 Query 里伪造；
- 12 条自动裁剪来自人工 note，不是第二次人工逐条复核。

因此整体任务仍不能标 `DSH_COMPLETE`，也不能进入 MIMO 独立复核。

