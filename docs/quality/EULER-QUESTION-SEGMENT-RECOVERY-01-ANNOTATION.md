# EULER-QUESTION-SEGMENT-RECOVERY-01 — 人工结构金标标注说明

- 目的：为 24 张真实照片（4 个回归 + 20 个额外）建立**独立人工结构金标**
- 标注对象：**原始照片 + raw OCR blocks**，不是 QCore 候选、不是 BM25 结果
- 输出：每张照片一条 JSON 记录
- 预计耗时：每张 2–3 分钟；24 张约 1–1.5 小时

---

## 1. 每张照片要填什么

```json
{
  "sample_id": "RP39",
  "file": "IMG_8161.jpeg",
  "target_qid": "975c888d-...",
  "status": "ambiguous",
  "segments": [
    {
      "segment_id": "S1",
      "block_ids": [0],
      "kind": "question",
      "printed_number": "5",
      "parent_segment_id": null,
      "material_block_ids": []
    },
    {
      "segment_id": "S2",
      "block_ids": [4, 5, 6],
      "kind": "group",
      "printed_number": "6-8",
      "parent_segment_id": null,
      "material_block_ids": [1, 2, 3]
    }
  ],
  "target_segment_ids": ["S2"],
  "target_material_block_ids": [1, 2, 3],
  "query_text": "（按下方规则拼接）",
  "query_sha256": "（对 query_text 做 SHA-256）",
  "notes": "Q5 是独立题；Q6-8 共享长江经济带材料；目标是 Q6-8"
}
```

字段定义：

| 字段 | 含义 |
|---|---|
| `status` | `reliable`：唯一目标且结构清晰；`ambiguous`：多题/边界不确定，需要用户选目标；`incomplete`：**没有可靠 QCore 候选/新增题，无法作答**；`invalid`：边界冲突。**照片里少材料本身不等于 incomplete：只要可见内容能定位 QCore 题，QCore 会补全材料。** |
| `segments` | 照片中所有题目/题组；以 raw OCR block 为最小单位 |
| `kind` | `question`（独立题）、`group`（共享材料题组）、`subquestion`（题组内小问）、`orphan`（无法归属的尾部/片段） |
| `block_ids` | 该题占用的 raw OCR block id（不要跨 block 补 OCR 没有的字） |
| `material_block_ids` | 该题组共享材料对应的 block ids |
| `target_segment_ids` | 用户目标题所在的 segment |
| `query_text` | 对目标题构造的完整 Query；**必须只由 OCR 原文拼接** |
| `query_sha256` | `sha256(query_text.encode("utf-8"))` |

---

## 2. 标注步骤

1. 打开原图。
2. 打开对应 `raw_blocks.json`（预填工作表里有 block id、label、bbox、text）。
3. 按 block 顺序，把**每道题/题组**标成一个 segment。
4. 遇到共享材料 block，放进 `material_block_ids`，不要塞进某一道题的题干。
5. 上一题的小问/选项尾巴，标成 `kind: "orphan"`，不要归到下一题。
6. 选择 `target_segment_ids`（照片中用户实际想找的那道题/题组）。
7. 按规则拼 `query_text`：
   - 先放 `target_material_block_ids` 的 block 文本（按原顺序）；
   - 再放 `target_segment_ids` 内所有 block 文本（按原顺序）；
   - 不包含未选中的相邻题；
   - 不包含 `orphan`。
8. 标记 `status`；如果 `status != reliable`，`target_segment_ids` 仍要填，但系统必须要求用户确认，不能自动 Exact。
9. 计算 `query_sha256`。
10. 第二遍复核：只看照片/OCR，不看 QCore 候选题，确认没有用候选反推 Query。

---

## 3. 四个回归样本的标注要点

### RP39 / IMG_8161

- raw blocks：
  - block 0：Q5 独立题；
  - block 1：长江经济带共享材料；
  - block 2/3：图表；
  - block 4/5/6：Q6/Q7/Q8；
  - block 7：下一页开头，不属于本题。
- 金标：
  - S1 = block 0，`question`，number 5；
  - S2 = block 4-6，`group`，number 6-8，`material_block_ids=[1,2,3]`；
  - `target_segment_ids=["S2"]`；
  - `status="ambiguous"`（多题页面，用户必须选）；
  - Query = material block 1 + Q6/Q7/Q8 block 4-6；不含 Q5。

### RP40 / IMG_8162

- block 0/1：Q19/Q20；
- block 2：太阳能光热电站共享材料；
- block 5/6：Q21/Q22；
- 金标：
  - S1 = block 0，Q19；
  - S2 = block 1，Q20；
  - S3 = block 5-6，`group`，number 21-22，material=[2,3,4]；
  - target S3，status ambiguous；
  - Query = material 2 + Q21/Q22；不含 Q19/Q20。

### RP43 / IMG_8165

- block 0 开头是上一题 Q32 的小问（4），是 `orphan`；
- block 1 是 Q33；
- 金标：
  - S1 = block 0，`orphan`，不属于 Q33；
  - S2 = block 1，Q33；
  - target S2；
  - Query 只含 block 1，不含 Q32(4)；
  - status ambiguous（照片含上一题尾巴，用户需确认）。

### RP05 / IMG_8127

- 照片上方 Q16/Q17 的题号未被 OCR 识别；OCR 只有 Q18/Q19/Q20；
- 共享材料在上一页，照片里没有；
- **关键：不要要求用户补材料。** 可见的 Q16–19 内容足以定位 QCore 的 Q16–19；QCore 本身带完整材料和全部小问。
- 金标：
  - 把 Q16–19 可见内容合成一个 `group` 题段（block 2-5），题号写 `16-19`；
  - `status="ambiguous"`（因为同页还有 Q20，多题需要用户选目标；不是因为材料缺失）；
  - `target_segment_ids` 指向该题组；
  - **`query_text` 用可见 OCR 内容即可，不要留空**；
  - notes 写 `共享材料在上一页未拍入；若候选确认到 QCore Q16-19，由 QCore 补全材料`；
  - 只有“无 QCore 候选/新增题”时才标 `incomplete` 并提示补拍材料。

---

## 4. 判定规则

- **不得用 QCore 候选题的文字补 OCR**；
- **不得把上一题尾部当作下一题材料**；
- **不得把未选中的相邻题并入 Query**；
- **不确定就标 ambiguous**；只有“无 QCore 候选/新增题”才标 incomplete；
- Query 是检索证据，允许只含照片可见内容；QCore 命中后由 QCore 提供完整材料；
- 不要把 QCore 的材料反向抄进 Query；也不要因为照片缺材料就让 Query 留空；
- 同一道题的题组必须保留完整小问；不要只截一个子问。

---

## 5. 输出与验收

把每张照片的一条 JSON 放进：

`runs/qcore_semantic_expansion_01/v11/structure_recovery/gold_worksheet/completed/`

文件名：`<sample_id>.json`。

验收只看：

- 24 条记录齐全；
- 每条的 `segments` 覆盖原始照片中的目标题；
- `query_text` 只由 OCR block 拼接；
- `status` 明确；
- `query_sha256` 可复算；
- RP05/RP39/RP40/RP43 四条与上面要点一致。

完成后即可把 `completed/` 交回；不需要写代码，也不需要改 QCore。
