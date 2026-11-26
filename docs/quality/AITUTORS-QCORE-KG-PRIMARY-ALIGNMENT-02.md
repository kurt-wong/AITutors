# AITUTORS-QCORE-KG-PRIMARY-ALIGNMENT-02

- 日期：2026-11-26
- 状态：**NODE ALIGNMENT COMPLETE / V2 FULL MAPPING NOT APPROVED**
- 性质：1,911 个未对齐 mmlong 节点的 Primary 分类
- 模型：`deepseek-flash`，固定 temperature=0、seed=42
- 候选域：PrimaryCategoryIndex（177 项）
- QCore 写入：0
- 节点修改：0
- 169 题 V2 重跑：0

---

## 1. 最终结论

```text
Primary 节点覆盖率 = 91.0%
覆盖后 Primary 稳定性 = 90.5%
全样本 Primary 稳定性 = 80.1%
20 题基准 = 18/20 有类别，rep2 15/20，rep3 14/20
169 题 V2 = NOT APPROVED
```

覆盖率大幅改善，但不能用“有覆盖子集”的 90.5% 掩盖：

- 19/166 题仍无完整类别；
- 20 题基准只有 75% 匹配；
- 437 个节点仍未对齐。

---

## 2. 对齐执行

### 输入

- 1,911 个 mmlong 节点，无可靠教材路径；
- 候选域：35 模块 + 136 章节 + 6 学科根；
- 分学科批量，最多 20 节点/批；
- 12 并发；
- 自动校验：category 存在、subject 一致、confidence 范围；
- 不创建新节点。

### 结果

| 项 | 数值 |
|---|---:|
| 输入未对齐 mmlong | 1,911 |
| LLM 对齐 | 1,506 |
| LLM unmapped | 405 |
| 跨学科被拒绝 | 14 |
| 最终未对齐 | 419 |

合并 v1 + v2：

| 来源 | 总数 | 已对齐 | 未对齐 |
|---|---:|---:|---:|
| mmlong818 | 4,182 | 3,763 | 419 |
| mytutors_curriculum | 629 | 629 | 0 |
| goralcao_supplement | 18 | 0 | 18 |
| 合计 | 4,829 | **4,392** | **437** |

覆盖率：

```text
4,392 / 4,829 = 91.0%
mmlong: 3,763 / 4,182 = 90.0%
```

confidence：

```text
high (>=0.8) = 4,319
mid (0.6-0.8) = 69
low (<0.6) = 4
```

所有 4,392 个映射均通过：

- category_id 存在于 PrimaryCategoryIndex；
- subject 与节点一致；
- confidence 范围合法。

产物：

```text
_dsh/workpackage_d/node_primary_alignment_v2.jsonl
_dsh/workpackage_d/node_alignment_stats_v2.json
```

---

## 3. Primary 稳定性

使用 166 题 × 三份已有运行（full-v1、rep2、rep3），不新增题目映射：

| 指标 | 结果 |
|---|---:|
| 类别完全一致 | 133/166 = **80.1%** |
| 三份运行都有类别覆盖 | 147/166 = 88.6% |
| 有覆盖子集内类别一致 | 133/147 = **90.5%** |
| 无完整类别的题 | 19/166 |

解释：

- **原始全样本稳定性 80.1%**，仍低于 90%；
- **coverage-adjusted 90.5%**，说明已覆盖部分基本达标；
- 19 题没有完整类别是覆盖缺口，不是“稳定”；
- 不能对外宣称 169 题已达到 90%。

数据：

```text
_dsh/workpackage_d/v2_coarse_stability.json
```

---

## 4. 固定 20 题基准

使用固定 20 题，映射到 v2 类别：

| 运行 | 类别匹配 | 覆盖率 |
|---|---:|---:|
| full（基准来源，循环） | 20/20 | 18/20 |
| rep2 | 15/20 | 16/20 |
| rep3 | 14/20 | 15/20 |

解释：

- full 是基准来源，不能作为独立准确率；
- rep2/rep3 相对基准为 75% / 70%；
- 低于 90%，**不能启动 V2 全量**；
- 基准本身仍是 provisional silver，不是专家 gold。

数据：

```text
_dsh/workpackage_d/benchmark_result_v2.json
```

---

## 5. 未对齐节点

最终 437 个：

| 来源 | 数量 |
|---|---:|
| mmlong818 | 419 |
| goralcao_supplement | 18 |

分布：

| 学科 | 未对齐 |
|---|---:|
| 英语 | 272 |
| 语文 | 107 |
| 化学 | 37 |
| 物理 | 20 |
| 生物 | 1 |
| 数学 | 0 |

14 个化学节点的教材路径指向生物内容，已显式拒绝跨学科 Primary，不做强行映射。

英语/语文未对齐主要是：

- 节点语义贴近文学/语篇分析；
- 现有 136 章节多数是教材单元，不是阅读技能；
- 课程分类缺少细粒度阅读策略节点。

---

## 6. 为什么仍不启动 169 V2

### 可以启动的理由

- 节点覆盖率 91.0%；
- 有覆盖子集稳定性 90.5%；
- 分类域固定、可撤销、无 QCore 写入。

### 不能启动的理由

1. **全样本稳定性 80.1%**，不是 90%；
2. **19/166 题仍无完整类别**；
3. **20 题基准 rep2/3 仅 15/14**；
4. 437 个节点仍未对齐，英语/语文尤甚；
5. 基准不是专家 gold，不能把 90.5% 当作语义准确率。

因此：

```text
ALIGNMENT-02 = COMPLETE
V2 FULL = NOT APPROVED
```

---

## 7. 下一步

建议 `AITUTORS-QCORE-KG-PRIMARY-ALIGNMENT-03`：

1. 处理 419 个 mmlong 未对齐：
   - 英语阅读/语篇节点优先；
   - 语文文学/语篇节点优先；
   - 仍无合适类别保持 unmapped；
2. 处理 18 个 goralcao 节点；
3. 为 14 个跨学科化学节点建立显式例外规则，不强行改学科；
4. 将 20 题基准升级为独立标注 gold（不由 full-v1 生成）；
5. 重算 coverage-adjusted stability；
6. 达标后才启动 169 V2。

明确不做：

- 不直接跑 169 V2；
- 不合并外部数据到规范资产；
- 不修改 4,829 节点；
- 不创建新节点；
- 不启动 DeepTutor。

---

## 8. 外部数据状态

AITutors 非商业，K12-KGraph 等 NC 数据可用，但仍保留 attribution/ShareAlike。

本轮未导入任何外部数据；对齐 100% 基于现有节点与教材路径。

---

## 9. 边界自检

- QCore 写入：0；
- QCore 发布状态变化：0；
- 4,829 节点修改：0；
- 新节点创建：0；
- 169 V2：0；
- DeepTutor：0；
- 外部数据合并：0；
- 历史映射保留。

---

## 10. 数据

```text
_dsh/workpackage_d/node_primary_alignment_v2.jsonl
_dsh/workpackage_d/node_alignment_stats_v2.json
_dsh/workpackage_d/v2_coarse_stability.json
_dsh/workpackage_d/benchmark_result_v2.json
```
