# 03_FIDELITY_MATRIX_SUMMARY.md — Manifest→Candidate 保真追踪矩阵汇总

> 任务：QCORE-ANSWER-FIDELITY-03 ｜ 生成器：`_scripts/build_fidelity_matrix.py`（可复算）
> 机器可读全量矩阵：`02_FIDELITY_MATRIX.json`（38 Units × 144 条目逐条结果）。

## 1. 全量计数核验

| 项 | 期望 | 实测 | 判定 |
| -- | -- | -- | -- |
| units | 38 | 38 | PASS |
| answer_items | 144 | 144 | PASS |
| composite_units | 21 | 21 | PASS |
| composite_sub_labels | 97 | 97 | PASS |
| manifest_image_assets | 49 | 49 | PASS |
| answer_image_slots | 2 | 2 | PASS |

分卷：

| 卷 | Units | 答案条目 | composite Units | composite 小问 | 图片资产 | 图片答案槽 | 冲突组 |
| -- | -- | -- | -- | -- | -- | -- | -- |
| chem | 12 | 47 | 5 | 26 | 41 | 2 | 4 |
| chn | 15 | 41 | 7 | 21 | 2 | 0 | 1 |
| eng | 11 | 56 | 9 | 50 | 6 | 0 | 2 |

## 2. 逐条结果分布（六类，工单 §5）

| 类别 | 含义 | 条数 |
| -- | -- | -- |
| 1 | 已映射至 Candidate 答案 | 12 |
| 2 | 已映射至 composite 小问/答案槽位 | 120 |
| 3 | 已映射为图片答案资产引用 | 2 |
| 4 | 已按 Owner D-1 作 Explanation 处理 | 8 |
| 5 | 已按合法冲突结构保留 | 2 |
| 6 | 确实无法映射 | 0 |

**未映射项：0 条**（无）

## 3. 12 道抽检题结果

| 样本 | 结果 |
| -- | -- |
| 化学 Q3 | inline_in_explanation → SingleChoiceAnswer("A")，statements@explanation_area L338 |
| 化学 Q8 | 1 CompositeAnswer：6 小问 8 槽，slot_bindings 逐空归属 |
| 化学 Q10 | 7 条全保留（4 小问），attribution=disputed（P-1 冻结），DISPUTED 证据在案 |
| 化学 Q11 | 9 条 / 4 小问逐槽映射 |
| 化学 Q12 | 7 条：2 AssetSlot（canonical asset_id）+ (6) 图文混合双槽；P-3 DISPUTED 在案 |
| 语文 Q2 | inline_in_explanation → SingleChoiceAnswer("A")，statements@explanation_area L473 |
| 语文 Q8 | 3 小问 3 答案对象分立（(1)=SingleChoice D），多点内容整段保留不切分 |
| 语文 Q12 | (2)#2 争议空 None + 3 版本 statements（stem/answer/explanation 三区可区分），不选边 |
| 英语 U3 | 4 小问逐条映射，"suggests/suggested/has suggested" verbatim 保留 |
| 英语 U4 | 20 小问（11–30）全展开；14/15 两组冲突双版本（选项区/解析区可区分）；source_internal 不阻断 |
| 英语 U9 | 5 小问（46–50）映射；共享选项池（A–G）挂父 body 不破坏 |
| 英语 U10 | 0 TypedAnswer；范文进 Explanation 带定位；不判缺答案（D-1） |

## 4. 硬性验收对应

- 38 Units 全部映射验证：`02_FIDELITY_MATRIX.json` per_paper.units。
- 144 条目逐条可定位：rows[] 每条含 category/target/derived_from_manifest_fields；
  `candidate_target` 为 RFC 6901 JSON Pointer（基座 = CandidateCore，`/answers/0/…` 约定），
  **写盘前逐条解析，解析失败即报错**（DSH B1 防复发）；类别 4（作文，Owner D-1）的 target
  为处置描述串而非指针（范文在 Explanation 行区，见 evidence_lines/explanation 覆盖）。
- 49 资产引用：manifest image_assets=49（41/2/6）；Candidate 注册数见 per_paper.registered_asset_ids。
- 2 图片答案槽：chem Q12 (5)#1/(6)#2 → AssetSlot(assets=[AnswerAssetRef(role=answer_value)])，canonical asset_id 唯一命中。
- 综合题结构：composite=21，每 unit 仅 1 个 Question Candidate（1 个顶层 CompositeAnswer）。
- 冲突/作文：7 组 source_internal 冲突两存不阻断；8 条作文条目（chn Q11×2、U10×3、U11×3）全部 Explanation 处置。
