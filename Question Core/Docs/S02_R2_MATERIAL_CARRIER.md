# S02 R2 · 材料载体图片归属裁决与证据

本文件记录 S02 R2 收尾对"19 张材料载体图片"的归属裁决（不重写 R2 归属算法）。

## 结论

- 52 张 `figures[]` 带非空 `applies_to`；
- 非材料载体图（33 张）：按声明落位，0 例无记录不一致；
- 材料载体图（19 张）：图的 evidence 行位于 `materials[]` 区间内，
  **物理 owner = 该材料**；`applies_to` 表示"消费该材料的子问清单"；
- 19 张的声明子问全部在 `materials_used` 中引用该材料（consumers_ok = 19/19），
  因此归属成立；未拆散材料块，未改 R2 算法。

## 代码行为

`mapper._merge_extras_and_figures`：

- 材料载体内图片不再记 `figure_applies_to_material_carried`（R1 过渡日志），
  改记 `figure_material_carrier_owner`：
  `{asset_id, carrier_materials[], declared_consumers[], consumers[{sub_id, materials_used[], carrier_ok}], consumers_ok}`；
- 任一消费者未引用载体材料 → 额外记 `figure_applies_to_consumer_mismatch`，
  该 unit 按 `uncertainty` 处理，不静默；
- 非材料载体图仍按 R1 C6 声明优先。

## 证据

- 审计：`_dsh/s02_r1_01/r1_overall_verify.json → applies_to`：
  figures=52，single=25，multi=27，mismatch=0，material_carried=19，
  consumer_mismatch=0，unlogged_mismatch=0；
- 覆盖：化学（2022乙 U8、2023山东 U17/U18/U19）、数学（2023全国I U18）、
  生物（2023山东 U21/U22/U23/U24/U25）、语文（2022乙 U2）；
- 回归：881 passed / 6 既有基线 / 12 PG 环境错误；G8/G9 未改。

## 边界

- 不重写 `figure_attribution` / AF5 布局判定；
- 不修改 Manifest 生产规则、不重导；
- 材料内容保持原有载体，未因声明拆块。
