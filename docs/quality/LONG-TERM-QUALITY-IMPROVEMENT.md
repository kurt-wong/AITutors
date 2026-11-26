# Long-term Quality Improvement — Segment Recovery Follow-ups

- 建立日期：2026-11-26
- 来源任务：`EULER-QUESTION-SEGMENT-RECOVERY-01`
- Owner 裁决：三项验证从当前任务验收范围剥离，转入长期质量提升，不再作为本任务 `MIMO_PASS` 前置条件
- 当前任务状态：`MIMO_CONDITIONAL_PASS (CONDITIONS CLEARED / TASK CLOSED UNDER CONDITIONAL)`

## 1. 转入长期清单的事项

| 事项 | 当前状态 | 后续质量目标 |
|---|---|---|
| 真实照片搜题四场景 E2E | 已完成多题场景真实整图 E2E（1 passed）；mock 覆盖单题 | 补单题、综合题、结构不确定场景的真实链路 |
| 24 条边界独立人工金标 | 已有 assisted block boundary；24/24 有记录，22/24 题号匹配 | 建立从原始 OCR 证据出发的独立人工边界金标 |
| 12 条 auto_cleaned 全量复核 | 已固定种子抽 5/5 通过 | 完成剩余 7 条逐条复核 |

这些是验证覆盖度提升，不是已确认的代码缺陷；不自动启动、不为了历史测试单独制造大规模工作。

## 2. 继续冻结的已知限制

不自动启动，继续保留可追溯性：

- RP05、RP18、RP04、RP13 的 OCR/PDF 源限制；
- 11 份 G8/G9 阻断样本；
- 8 份 `ocr_source_defect` 样本。

## 3. 边界

- 不阻塞 `EULER-QUESTION-SEGMENT-RECOVERY-01`；
- 不重开已提交的结构/OCR/API/UI/E2E 代码；
- 不追形式上的 `MIMO_PASS`；
- 后续只结合真实产品流程和新增样本逐步完成。

## 4. 当前任务关闭依据

- C1 gitlink：已同步 `e7d525a88eccf57498c6f376fe0b00a4ba81860a`；
- C2 交付边界：已清理并提交；
- C3：assisted block boundary 已记录；
- C4：真实多题 E2E 通过；
- C5：抽样 5/5；
- 生产 QCore：零写入、零变化；
- 详细报告：`docs/quality/EULER-QUESTION-SEGMENT-RECOVERY-01-FINAL.md`。
