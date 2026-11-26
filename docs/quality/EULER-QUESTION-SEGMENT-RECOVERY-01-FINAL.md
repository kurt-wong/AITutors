# EULER-QUESTION-SEGMENT-RECOVERY-01 — FINAL REPORT（供 MIMO 复查）

- 日期：2026-11-26
- 执行：DSH
- 状态：`MIMO_CONDITIONAL_PASS / C1–C5 CLOSED / MIMO_RE_REVIEW_READY`
- MIMO 独立结论：`_dsh/semantic_expansion_01/PBA_SEGMENT_RECOVERY_MIMO_VERIFICATION.md`

---

## 1. 目标

修复四个 False Exact：

- RP05：Q16–19 题组被拆散，OCR 缺 16/17 题号；
- RP39：Q6–8 复合题拆散，共享材料归属错误；
- RP40：Q21–22 拆散；
- RP43：Q32(4) 尾部混入 Q33。

原则：

- QCore 是唯一题目/修订/答案/解析来源；
- 照片可见内容能定位 QCore 题时，QCore 补全材料和全部小问；
- 不要求用户补材料，不把整页自动当一道题；
- 结构/目标不确定时，不自动 Exact；
- 不写生产 QCore，不切默认模型。

---

## 2. 实现

### 2.1 结构安全内核

`Teaching Script Compiler/tsc_compiler/semantic/question_structure.py`

- 题号分段、前缀/共享材料识别；
- 题号缺失 → `ambiguous`/`incomplete`（安全降级）；
- 上一题尾部污染 → `QUESTION_TAIL_CONTAMINATION`，默认排除；
- raw block material 映射到后续题段；
- `query_for()` 支持 material + 选中题段。

测试：`Teaching Script Compiler/tests/test_question_structure.py`，11 passed。

### 2.2 OCR raw 保留

`Teaching Script Compiler/tsc_compiler/photo/ocr_client.py`

- `include_raw=True` 保留 `layoutParsingResults`、`parsing_res_list`、`block_bbox`、`block_order`、raw SHA；
- 不覆盖历史。

### 2.3 Compiler API

`Teaching Script Compiler/tsc_compiler/api.py`

- photo/text search 返回 `structure`；
- photo OCR 使用 raw JSONL 生成 material context。

### 2.4 DeepTutor 目标选择

- `DeepTutor/web/components/qcore/QCoreTeachPage.tsx`
  - 多题/结构不确定 → 目标选择；
  - 选中后走 `/api/qcore-teach/search-text`；
  - 单题直接候选。
- `DeepTutor/web/app/api/qcore-teach/search-text/route.ts`
- `DeepTutor/web/lib/qcore-teach/client.ts`

### 2.5 E2E

- Mock OCR 边界：`DeepTutor/web/tests/e2e/qcore-teach-target.audit.ts` → 2 passed；
- 真实整图：`DeepTutor/web/tests/e2e/qcore-teach-real.audit.ts` → 1 passed（2.3m）。

---

## 3. 四回归结果

| 样本 | 目标 | 结果 |
|---|---|---|
| RP05 | Q16–19 | 可见 Q16–19 内容进 Query；材料缺失不要求补拍 |
| RP39 | Q6–8 | 长江经济带材料 + Q6/Q7/Q8；无 Q5 |
| RP40 | Q21–22 | 太阳能光热电站材料 + Q21/Q22；无页码 |
| RP43 | Q33 | Q33；无 Q32(4) 尾部 |

四条均为 `ambiguous`，不自动 Exact。

---

## 4. OCR raw 与 assisted gold

### 4.1 重跑

- 24/24 OCR ok；
- 7/24 新旧文本变化；
- 四个回归文本未变；
- raw 全部保存：
  ```text
  runs/qcore_semantic_expansion_01/v11/structure_recovery/ocr_v2/
  ```

### 4.2 Assisted gold 复核

- 9 条人工 pass；
- 12 条人工 issue → 按 note 确定性裁剪；
- 3 条 OCR 源限制：
  - RP04 下划线；
  - RP05 Q16/Q17 题号；
  - RP13 空题号。

产物：

```text
assisted_gold_24.json
assisted_gold_final_24.json
review_summary.json
reviewed/*.json
```

### 4.3 Block boundary（C3）

`boundary_gold_24.json`

- 24/24 block-level segments；
- status：reliable 1、ambiguous 23；
- 22/24 题号匹配；
- RP05/RP18 题号偏移已显式标记；
- 性质：assisted block boundary，不是独立人工逐条金标。

### 4.4 C5 抽样

从 12 条 auto_cleaned 固定种子抽 5 条：

```text
RP18, RP40, RP01, RP02, RP10
```

结果：5/5 pass，旧 issue 引用文本均已从 Query 消失。

证据：`c5_sample_review.json`。

---

## 5. 测试与生产零变化

| 项 | 结果 |
|---|---|
| Compiler full pytest | 64 passed |
| 结构专项 | 11 passed |
| DeepTutor unit | 5 passed |
| `tsc --noEmit` | pass |
| `npm run build` | pass |
| Mock E2E | 2 passed |
| Real E2E | 1 passed（2.3m） |
| 生产 guard | 175/193/585/169，与冻结基线全等 |
| QCore 写入 | 0 |

---

## 6. 复现命令

### Compiler

```powershell
cd "D:\Project\AITutors\Teaching Script Compiler"
python -X utf8 -m tsc_compiler.cli serve --host 127.0.0.1 --port 8820 --log-level warning
```

### Web

```powershell
cd "D:\Project\AITutors\DeepTutor\web"
npx next start -p 3100
```

### E2E

```powershell
cd "D:\Project\AITutors\DeepTutor\web"
$env:WEB_BASE_URL="http://127.0.0.1:3100"
npx playwright test tests/e2e/qcore-teach-target.audit.ts --project=ui-audit --workers=1
npx playwright test tests/e2e/qcore-teach-real.audit.ts --project=ui-audit --workers=1
```

真实 E2E 依赖远端 OCR；队列满时只重试测试，不将其判为代码失败。

---

## 7. 提交

### AITutors

```text
0dd6f9137 chore: sync DeepTutor real E2E gitlink
e648758b0 docs(quality): record C3/C4/C5 closure results
eb6da8ffc docs(quality): close MIMO C1/C2 conditions
88584f92f chore: sync DeepTutor gitlink and annotation delivery
5d260d553 docs(quality): separate OCR quality from photo path E2E
87b7856b2 docs(quality): prepare MIMO review packet
```

### DeepTutor

```text
e7d525a88 test(qcore): real photo OCR target-selection E2E
3a3b84ec7 test(qcore): browser E2E for target selection and shared material
```

gitlink：

```text
DeepTutor 160000 e7d525a88eccf57498c6f376fe0b00a4ba81860a
```

---

## 8. 明确不声称

- 不声称 `MIMO_PASS`；
- 不声称独立人工逐条边界金标；
- 不声称真实四场景 E2E 全矩阵完成；
- 不声称 3 条 OCR 源限制已修复；
- 不声称 12 条 auto_cleaned 全部二次人工复核（只做 5 条抽样）。

## 9. 请 MIMO 复查

重点检查：

1. C1/C2/C3/C4/C5 是否满足关闭条件；
2. assisted boundary gold 是否可作为条件关闭材料；
3. 真实 E2E 单场景是否足够，还是必须四场景全矩阵；
4. RP05/RP18 题号偏移是否应保持 `known_ocr_limit`；
5. 是否允许以 `MIMO_CONDITIONAL_PASS` 正式关闭。
