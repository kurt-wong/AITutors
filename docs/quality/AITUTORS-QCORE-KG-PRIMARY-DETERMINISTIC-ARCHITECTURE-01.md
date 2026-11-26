# AITUTORS-QCORE-KG-PRIMARY-DETERMINISTIC-ARCHITECTURE-01

- 日期：2026-11-26
- 状态：**MECHANISM VALIDATED / PRODUCTION NOT READY**
- 性质：固定节点对齐 + Secondary 识别 + 确定性 Primary 派生
- v2 冻结，v3 不进入正式链
- QCore 写入：0
- 4,829 节点修改：0
- 169 V2：0

---

## 1. 最终裁决

```text
v2 节点对齐表 = FROZEN BASELINE
Secondary -> Primary 确定性派生 = VALID MECHANISM
Secondary 识别 = NEW BOTTLENECK
独立 Gold = NOT YET AVAILABLE
169 V2 = NOT APPROVED
```

核心结论：

- **固定 v2 节点归属后，同一 Secondary 集合必然派生相同 Primary；**
- 但 LLM 对 Secondary 的识别仍不稳定，且比直接 Primary 覆盖更低；
- 没有独立 Gold，不能把重复一致率当准确率；
- 因此不能启动 169 V2。

---

## 2. v2 冻结审计

manifest：

```text
_dsh/workpackage_d/primary_node_alignment_v2_manifest.json
```

| 项 | 数值 |
|---|---:|
| rows | 4,829 |
| unique node_id | 4,829 |
| mapped | 4,392 |
| unmapped | 437 |
| invalid category rows | 0 |
| sha256 | `5f47cb00832c5fd4b9c5ac8a3a0138463cef30f27dc1d648554a8e1504df7d19` |

规则：

- 每个节点最多一个 Primary category；
- category 必须存在于 PrimaryCategoryIndex；
- subject 必须一致；
- v3 只作实验，不进入正式链；
- 未映射节点保留 unmapped，不强行补。

---

## 3. 确定性派生

算法：

```text
given secondary_node_ids:
  categories = unique sorted(
    v2[secondary_id].category_id
    for secondary_id in secondary_node_ids
    if v2[secondary_id].category_id exists
  )
  unmapped_secondary = secondary ids without category
```

性质：

- 同一 `secondary_node_ids` + 同一 v2 hash → 同一 Primary 集合；
- 多 Secondary 落到同一 Primary → 去重；
- 多独立 Primary → 保留，不强行合并；
- unmapped Secondary → 显式记录，不产生假 Primary；
- 没有随机性、没有 LLM 直接选 Primary。

验证：

```text
same input repeated derivation: 20/20 identical
```

这是机制级确定性，不是语义正确性。

---

## 4. 20 题 Secondary-only 验证

输入：

- 20 道 published 题，六科分层；
- 固定 BM25 top-30；
- 固定 `deepseek-flash`；
- Prompt 只要求 Secondary 节点，不要求 Primary；
- 输出经 schema/evidence/候选校验；
- 用 v2 固定表派生 Primary。

结果：

| 指标 | 结果 |
|---|---:|
| 自动校验通过 | 16/20 |
| 有 Secondary | 14/20 |
| 派生 Primary 覆盖 | 14/20 |
| 直接 LLM Primary 覆盖 | 18/20 |
| 直接 vs 派生 Primary 完全匹配 | 12/20 |

失败：

- 4 条 API/JSON 失败；
- 4 条有效但 Primary 集合不同；
- 派生覆盖率低于直接 Primary。

结论：

- 确定性派生本身成立；
- 但 **Secondary 识别成为新瓶颈**；
- 不能假设“先识别 Secondary 再派生”会自动优于直接 Primary；
- 覆盖从 18/20 降到 14/20。

数据：

```text
_dsh/workpackage_d/secondary_only_pilot_20.json
_dsh/workpackage_d/secondary_pilot_compare.json
```

---

## 5. Gold 状态

### 5.1 Node Gold

当前 v2 是 **LLM 辅助对齐基线**，不是独立 Node Gold。

它能作为固定分类层，但不能证明每个节点归属语义正确。

### 5.2 Question Gold

当前没有独立 Question Gold。

此前的 20 题 benchmark 是 `provisional_silver`，部分由 full-v1 派生，不能作为准确率 Gold。

### 5.3 必须区分

| 指标 | 能说明 | 不能说明 |
|---|---|---|
| 重复一致率 90.5% | 输出可重复 | 分类正确 |
| 覆盖 91% | 有类别 | 类别正确 |
| Node alignment | 可派生 | 语义 gold |

没有独立 Gold 时，不能对外宣称准确率。

---

## 6. 最终结论

### 可以接受的

- v2 可作为固定 Primary 分类层；
- Secondary→Primary 是确定性的；
- 不再让 LLM 每道题直接选 Primary；
- v3 覆盖实验不进入正式链。

### 不能接受的

- 437 个未映射节点；
- Secondary-only 覆盖低于直接 Primary；
- 16/20 校验通过、14/20 有 Primary；
- 没有独立 Node/Question Gold；
- 12/20 直接/派生不一致。

因此：

```text
ARCHITECTURE MECHANISM = ACCEPTED
PRODUCTION READINESS = NOT ACCEPTED
169 V2 = NOT APPROVED
```

---

## 7. 下一步（不启动 V2）

优先级：

1. **独立 Node Gold**：从教材/课程关系建立，不继承 v2；
2. **独立 Question Gold**：20–30 题，不由 full-v1 生成；
3. **Secondary 识别质量**：提高覆盖/证据，不追求 v4 覆盖率；
4. 用 Gold 评估 v2 派生，而不是继续看重复一致率；
5. 达标后才讨论 169 V2。

明确不做：

- 不再补覆盖率；
- 不再用最近分类强行填充；
- 不重跑 169；
- 不修改 4,829 节点；
- 不启动 DeepTutor；
- 不把 v3 当正式映射。

---

## 8. 交付

```text
docs/quality/AITUTORS-QCORE-KG-PRIMARY-DETERMINISTIC-ARCHITECTURE-01.md
_dsh/workpackage_d/primary_node_alignment_v2_manifest.json
_dsh/workpackage_d/secondary_only_pilot_20.json
_dsh/workpackage_d/secondary_pilot_compare.json
```

QCore 零写入；知识图谱零修改。
