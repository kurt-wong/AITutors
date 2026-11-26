# EULER-QUESTION-SEGMENT-RECOVERY-01 — C3/C4/C5 收尾结果

- 日期：2026-11-26
- 状态：`MIMO_CONDITIONAL_PASS` 条件项 C3/C4/C5 补强完成
- 性质：assisted boundary gold + real OCR E2E + sample recheck

## C3 — Block-level 边界记录

产物：`runs/qcore_semantic_expansion_01/v11/structure_recovery/ocr_v2/boundary_gold_24.json`

- 24/24 样本有 block-level segments、target segment、material block、query_text；
- 状态：reliable 1、ambiguous 23、incomplete 0；
- 22 条目标题号与 OCR 可见题号匹配；
- 2 条题号偏移已显式标记：
  - RP05：期望 16–19，OCR 仅见 18/19；
  - RP18：期望 12，OCR 可见 13。

性质：**assisted block boundary**，由 raw OCR block + target_qid 生成，不是独立人工从零边界金标。

## C4 — 真实整图浏览器 E2E

测试：`DeepTutor/web/tests/e2e/qcore-teach-real.audit.ts`

- 真实上传 `IMG_8161.jpeg`；
- 真实 OCR job；
- 目标选择 Q6/Q7/Q8；
- 真实 `/api/qcore-teach/search-text`；
- 候选出现；
- 断言提交 Query 含“长江经济带”和 Q8。

结果：**1 passed（2.3m）**。

证据：真实 job `a0956ebf789f4d45b70a` succeeded；页面到达候选。

## C5 — auto_cleaned 抽样

从 12 条 `auto_cleaned_after_human_issue` 中固定种子抽取 5 条：

```text
RP18, RP40, RP01, RP02, RP10
```

结果：**5/5 pass**，旧 issue note 中的被引文本均已从当前 Query 消失。

证据：`c5_sample_review.json`，seed `20261126`。

## 仍未关闭

- C3 是 assisted boundary，不是独立人工逐条金标；
- RP05/RP18 的 OCR 题号偏移保留为 `known_ocr_limit`；
- 12 条 auto_cleaned 只做了 5 条抽样，不是 12 条二次全复核；
- 真实 E2E 只覆盖多题目标选择，不覆盖单题/综合题/不确定结构四场景全矩阵。

因此仍不能写 `MIMO_PASS`；C3/C4/C5 的条件补强已完成，交 MIMO 复查。
