# AITUTORS-QCORE-KG-PRIMARY-ALIGNMENT-03

- 日期：2026-11-26
- 状态：**COVERAGE IMPROVED / STABILITY NOT IMPROVED / V3 NOT AUTHORITATIVE**
- 性质：对 437 个未对齐节点做定向补齐
- QCore 写入：0
- 节点修改：0
- 169 V2：0

---

## 1. 最终结论

```text
v2 对齐（已验证基线）
  mapped 4,392 / 4,829 = 91.0%
  covered stability = 133/147 = 90.5%

v3 补齐（候选，不作为正式基线）
  mapped 4,782 / 4,829 = 99.0%
  full stability = 133/166 = 80.1%
  covered stability = 126/156 = 80.8%
  benchmark rep2/rep3 = 15/20, 14/20

169 V2 = NOT APPROVED
```

**覆盖率提高到 99%，没有带来质量提高。**

v3 的 390 条新增映射中，很多是“最近可用分类”，属于覆盖扩展，不是稳定语义。

---

## 2. v3 执行

1. 从 437 个未对齐节点开始；
2. 仅对 mmlong 的 419 个节点做定向 LLM；
3. 候选域固定为 PrimaryCategoryIndex；
4. 允许 `unmapped`；
5. 12 节点/批，8 并发；
6. 自动校验 category 存在、subject 一致、confidence。

结果：

| 项 | 数量 |
|---|---:|
| 输入未对齐 | 419 mmlong |
| 新增映射 | 390 |
| 仍 unmapped | 29 |
| 加上 goralcao | 47 总未映射 |

v3 全量：

| 来源 | 总数 | 已映射 | 未映射 |
|---|---:|---:|---:|
| mmlong818 | 4,182 | 4,153 | 29 |
| mytutors_curriculum | 629 | 629 | 0 |
| goralcao_supplement | 18 | 0 | 18 |
| 合计 | 4,829 | **4,782** | **47** |

覆盖率：

```text
4,782 / 4,829 = 99.0%
```

所有映射 category 合法、subject 一致；无 invalid。

---

## 3. 稳定性对比

| 指标 | v2 基线 | v3 补齐 |
|---|---:|---:|
| 总映射 | 4,392 (91.0%) | 4,782 (99.0%) |
| 全样本类别一致 | 133/166 = 80.1% | 133/166 = 80.1% |
| 有覆盖题数 | 147 | 156 |
| 有覆盖内一致 | 133/147 = **90.5%** | 126/156 = **80.8%** |
| benchmark rep2 | 15/20 | 15/20 |
| benchmark rep3 | 14/20 | 14/20 |

结论：

- v3 增加了 9 个“有类别覆盖”的题；
- 但其中有 7 个类别集合不一致；
- 因此 **covered stability 从 90.5% 降到 80.8%**；
- 99% 覆盖率是表面改善，不应作为 V2 依据。

---

## 4. 为什么 v3 不进入正式基线

1. v3 用“最接近分类”策略，允许语义相关即可选；
2. 这会把不确定节点强行归入某个模块/章节；
3. 覆盖率上升，但跨运行类别集合更不稳定；
4. 20 题基准没有改善；
5. 没有独立 gold 证明新增映射正确。

因此：

```text
v2 = authoritative alignment baseline
v3 = candidate coverage experiment
```

不删除 v3，保留为后续分析数据，但不作为正式 Primary mapping。

---

## 5. 剩余未对齐

47 个：

| 来源 | 数量 |
|---|---:|
| mmlong818 | 29 |
| goralcao_supplement | 18 |

这 47 个不是主要瓶颈。主要瓶颈已经从“覆盖”转为：

- Primary 类别集合本身不稳定；
- benchmark 不是独立 gold；
- 模型对同一节点/题目的上层判断会变。

即使把 47 个全部强行映射，也不能解决 80% 稳定性。

---

## 6. 最终裁决

```text
PRIMARY-ALIGNMENT-03 = COMPLETE (COVERAGE EXPERIMENT)
AUTHORITATIVE BASELINE = v2 (4,392 mapped, 91.0%)
PRIMARY COVERAGE-ADJUSTED STABILITY = 90.5% (v2)
FULL-SAMPLE STABILITY = 80.1%
169 V2 = NOT APPROVED
```

不能启动 V2 的原因不再是“覆盖率不够”，而是：

1. 全样本稳定性 80.1%；
2. v3 提高覆盖反而降低 covered stability；
3. 20 题基准仅 15/14；
4. 没有独立专家 gold。

---

## 7. 下一步建议

停止继续追求覆盖率。建议：

1. 将 20 题基准升级为独立 gold（不由 full-v1 生成）；
2. 对 Primary 类别集合做稳定性仲裁（固定分类规则，而不是最近类别）；
3. 只对 47 个剩余节点做人工/规则确认，不再扩大 LLM 覆盖；
4. 重新评估 v2；
5. 达标后才启动 169 V2。

明确不做：

- 不再用“最近分类”提高覆盖率；
- 不直接跑 169 V2；
- 不修改 4,829 节点；
- 不创建新节点；
- 不启动 DeepTutor。

---

## 8. 数据

```text
_dsh/workpackage_d/node_primary_alignment_v2.jsonl   # 已验证基线
_dsh/workpackage_d/node_primary_alignment_v3.jsonl   # 候选覆盖实验
_dsh/workpackage_d/node_alignment_stats_v3.json
_dsh/workpackage_d/v3_stability.json
_dsh/workpackage_d/benchmark_result_v3.json
```

QCore 生产数据零变化。
