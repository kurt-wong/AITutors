# AITUTORS QCORE ↔ SIX-SUBJECT-KG MAPPING STANDARD 01

- 日期：2026-11-26
- Owner 裁决：`six-subject-kg` **4,829 节点是规范底座**；映射由**统一 LLM** 生成；**不做人工逐条审查**。
- 性质：NLP 语义映射标准（derived annotation），不是 QCore 事实写入。

---

## 1. 固定边界

```text
QCore = 题目/答案/解析/来源的事实源
six-subject-kg 4,829 = 知识节点规范底座
LLM mapping = derived semantic annotation
DeepTutor = 消费语义映射与 QCore 的教学入口
```

- 映射不修改 QCore 的题干、答案、解析、发布状态。
- 映射是独立、可重建、可版本化的语义层。
- LLM 不创建新节点；节点不够时输出 `unmapped`，节点扩充另行进行。
- 节点扩充后，映射可重跑；旧映射保留版本。

---

## 2. 映射单位

默认按 **QCore question** 映射，保留 revision：

```json
{
  "question_id": "...",
  "revision_id": "...",
  "mapping_scope": "question",
  "subquestion_ref": null
}
```

需要细到小问时使用：

```json
{"mapping_scope":"subquestion","subquestion_ref":"(1)"}
```

一个 question 可以有多条映射（不同小问/不同 role）。

---

## 3. 统一 LLM 标准

必须统一：

| 项 | 要求 |
|---|---|
| provider/model | 单一固定模型；记录 model id |
| prompt | 单一 `mapping_prompt_version`，不得按题改写 |
| temperature | 0 |
| output schema | 固定 JSON schema |
| candidate set | 统一 candidate generator + top_k |
| seed/version | 记录 seed、prompt hash、candidate hash |
| 运行 | 同一批次、同一模型、同一版本 |

建议候选生成：

1. 用 QCore question 的 stem/material/options 构造检索文本；
2. 用 4,829 节点的 name/summary/aliases 建 BM25 + dense 候选；
3. 取 top_k（建议 30）；
4. LLM 只能在候选里选，不能凭空造 node_id；
5. 没有合适节点 → `unmapped` + reason。

---

## 4. 输出 Schema

```json
{
  "question_id": "...",
  "revision_id": "...",
  "mapping_scope": "question",
  "subquestion_ref": null,
  "primary_nodes": [
    {
      "node_id": "mml:math:...",
      "confidence": 0.91,
      "evidence_quote": "题干/材料中的原文片段",
      "rationale": "为什么这是核心考查点"
    }
  ],
  "supporting_nodes": [
    {
      "node_id": "mml:...",
      "confidence": 0.73,
      "evidence_quote": "...",
      "rationale": "..."
    }
  ],
  "unmapped": false,
  "unmapped_reason": "",
  "model": "固定 model id",
  "prompt_version": "mapping-v1",
  "candidate_set_hash": "...",
  "created_at": "..."
}
```

约束：

- `primary_nodes` 1–3；
- `supporting_nodes` 0–5；
- 不允许重复 node_id；
- `evidence_quote` 必须能在题目文本中按规范化后子串匹配；
- `node_id` 必须存在于 4,829 节点 catalog；
- 节点 subject 必须与 QCore question subject 一致；
- 不允许 LLM 输出未在候选集中的 node_id。

---

## 5. 自动校验（替代人工审查）

每条映射入库前自动执行：

1. JSON schema；
2. node_id 存在；
3. node_id 在候选集中；
4. subject 一致；
5. 数量边界；
6. evidence_quote 可匹配；
7. 重复 node；
8. confidence 范围；
9. 同一 question/revision 的幂等键；
10. model/prompt/candidate hash 完整。

不通过 → 不写入 `validated` 表；写入 `rejected` 记录，保留原因，可重跑。

置信度分层：

```text
high  >= 0.80
mid   0.60–0.79
low   < 0.60
```

低置信不丢弃，但标记 `confidence_tier=low`；是否用于教学由产品策略决定，不引入人工逐条审查。

---

## 6. 存储

建议独立于 QCore 内容表：

```text
knowledge_nodes          # 4,829 节点，source/layer/subject
knowledge_aliases        # 节点别名
question_node_map        # LLM 映射，版本化
mapping_runs             # model/prompt/candidate hash/统计
mapping_rejects          # 自动校验失败
```

- `question_node_map` 是 derived layer；
- 不写 `qcore_questions/revisions` 内容；
- 可按 `question_id/revision_id/node_id/model/prompt_version` 查询；
- 保留旧版本，支持重跑。

PostgreSQL 即可；暂不引入 Neo4j。

---

## 7. 全量映射流程

```text
1. 导出当前 QCore 全部 question/revision（1166/全量）
2. 载入 4,829 节点 catalog（source/layer/subject/name/summary/aliases）
3. 对每题生成 top_k 节点候选
4. 统一 LLM 输出 schema
5. 自动校验
6. 写 question_node_map（success/rejected）
7. 统计：coverage、primary/supporting 分布、low confidence、unmapped
8. 重跑只换版本，不覆盖历史
```

不做人工逐条 review；自动统计和抽样指标只用于发现系统性问题，不作为发布前逐条审批。

---

## 8. 许可边界

4,829 节点中包含 mmlong818 的 PolyForm Noncommercial 声明（且仓库无 LICENSE 文件）。

- 技术映射可以先做；
- 商用/对外发布前必须完成许可确认或替换来源；
- 这不属于“人工审查环节”，是数据合规 gate；
- 不能因为 LLM 能映射就视为可商用。

---

## 9. 与 QCore/DeepTutor 的消费关系

```text
QCore question/revision
  → question_node_map
  → knowledge_nodes
  → DeepTutor 选题/教学/学习计划
```

- QCore 仍是题目事实源；
- 知识映射只提供“这题考查什么”；
- 不反向修改 QCore；
- 题目与节点的映射可以重跑、可撤销、可版本化。

---

## 10. 首个实施目标

不做人工映射审查，直接做可重复的 LLM 映射管线：

1. 建立 4,829 节点 catalog 与别名索引；
2. 选一个固定 LLM/prompt，先跑 20–50 题 pilot，验证自动校验通过率；
3. 自动指标达标后跑全量；
4. 输出 mapping coverage 和 low-confidence 统计；
5. 不把“57 条旧映射”当已有覆盖；它和当前 QCore 是 0 重叠。

---

## 11. 结论

- 规范底座：4,829 节点；
- 标注者：统一 LLM；
- 人工审查：不做逐条审查；
- 质量保证：自动 schema/ID/evidence/subject/version 校验 + 指标；
- QCore：只读事实源；
- 存储：PostgreSQL derived mapping layer；
- 许可：独立合规 gate，不是映射审查。
