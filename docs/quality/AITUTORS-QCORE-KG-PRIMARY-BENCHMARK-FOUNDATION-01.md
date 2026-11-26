# AITUTORS-QCORE-KG-PRIMARY-BENCHMARK-FOUNDATION-01

- 日期：2026-11-26
- 状态：**FOUNDATION BUILT / V2 FULL MAPPING NOT APPROVED**
- 性质：Primary 分类基准 + 节点对齐 + 固定测试集
- QCore 写入：0
- 4,829 节点修改：0
- 外部数据合并：0
- DeepTutor 入口：0

---

## 1. 最终裁决

```text
PrimaryCategoryIndex = BUILT
外部数据 = 仅审计，不合并
4,182 节点对齐 = BASELINE BUILT (2,271 mapped / 1,911 unmapped)
固定 Primary 基准 = PROVISIONAL, 20 题
169 题 V2 全量 = NOT APPROVED
```

原因：

- 仍有 **1,911 / 4,182** mmlong 节点无法用现有教材路径对齐；
- 20 题基准中 **7/20** 需要回退到学科根；
- 模块级 Primary 严格一致性 **88.8%**，仍低于 90%；
- 基准是 provisional silver，不是专家 gold，不能用于宣称语义准确率。

---

## 2. 交付物

### 2.1 PrimaryCategoryIndex

文件：

```text
_dsh/workpackage_d/primary_category_index_v1.json
```

来源：现有 629 个 `mytutors_curriculum` 节点。

| 层级 | 数量 |
|---|---:|
| level=1 学科根 | 6 |
| level=2 模块 | 35 |
| level=3 章节 | 136 |
| 合计 | 177 |

约束：

- 不修改原节点；
- 不引入外部分类；
- 保留原 node_id、名称、parent、subject、source；
- 作为独立分类视图，不是新知识树。

### 2.2 外部数据审计

见：

[AITUTORS-QCORE-KG-EXTERNAL-DATA-AUDIT-01.md](AITUTORS-QCORE-KG-EXTERNAL-DATA-AUDIT-01.md)

结论：

- K12-KGraph 数据集 CC BY-NC-SA 4.0，代码 MIT；仅可隔离研究，不可商用合并；
- China Skill Taxonomy 许可证未核实，待审计；
- CnK12Taxonomy ODbL/CC BY-SA，不能随意并入；
- 33,765 数据集暂缓；
- **本轮未导入任何外部数据**。

### 2.3 节点对齐

文件：

```text
_dsh/workpackage_d/node_primary_alignment_v1.jsonl
_dsh/workpackage_d/node_alignment_stats_v1.json
```

| 来源 | 总数 | 已对齐 | 未对齐 |
|---|---:|---:|---:|
| mmlong818 | 4,182 | 2,271 | 1,911 |
| mytutors_curriculum | 629 | 629 | 0 |
| goralcao_supplement | 18 | 0 | 18 |
| 合计 | 4,829 | **2,900** | **1,929** |

覆盖率：

```text
2,900 / 4,829 = 60.1%
```

对齐方法：

- mytutors：沿 `parent_code/level` 取 level=2 模块；
- mmlong：`textbooks[].chapter_path` 精确匹配 level=3/4 名称，再回到 level=2；
- 无可靠路径：显式 `unmapped`；
- 不创建父节点，不修改图谱。

### 2.4 固定 Primary 基准

文件：

```text
_dsh/workpackage_d/primary_benchmark_v1.json
_dsh/workpackage_d/benchmark_result_v1.json
```

- 20 题，覆盖六科；
- 固定 `question_id` / `revision_id` / expected category；
- `label_status=provisional_silver`；
- 不是专家 gold，不能用于对外宣称语义准确率。

基准统计：

| 项 | 数值 |
|---|---:|
| 题数 | 20 |
| 含学科根 fallback | 7 |
| 有效 level=2/3 覆盖 | 13 / 20 = 65% |
| 预期类别层级 | level=1 7 个；level=2 17 个；level=3 0 |

### 2.5 基准结果

| 运行 | 类别匹配 | 覆盖率 |
|---|---:|---:|
| full-v1（基准来源） | 20/20（循环，不作准确率） | 20/20 |
| rep2 | 18/20 | 20/20 |
| rep3 | 17/20 | 19/20 |

解释：

- `full-v1` 是基准来源，不能当作独立准确率；
- rep2/rep3 是相对基准的重复一致性；
- 7 题 fallback 到学科根，说明有效上层覆盖不足；
- 不能把这 20 题结果外推为 169 题准确率。

---

## 3. 关键结论

### 3.1 PrimaryCategoryIndex 可用

- 177 个分类项来自现有 629 课程节点；
- 6/35/136 层级完整；
- 不依赖外部数据；
- 可版本化、可撤销；
- 适合作为 Primary 的固定候选域。

### 3.2 节点对齐仍是瓶颈

- 4,182 mmlong 中 2,271 可对齐，1,911 不可；
- 加 18 个 goralcao，共 1,929 未对齐；
- 未对齐节点不能强行归到学科根；否则会制造“高稳定性、低价值”的假象。

### 3.3 稳定性仍不足

历史 166 题：

```text
细粒度 Primary 一致 = 38.6%
level=3 一致 = 74.7%
level=3 严格样本 = 77.6%
level=2 模块严格 = 88.8%
```

20 题基准：

```text
rep2 与 full 的类别匹配 = 18/20
rep3 与 full 的类别匹配 = 17/20
```

没有达到 90% 的 V2 门槛。

### 3.4 外部数据不能解决许可证问题

K12-KGraph 的数据集是 CC BY-NC-SA 4.0：

- 可以研究其层级/分类方法；
- 不能把数据并入商业产品；
- 不能把“代码 MIT”误当“数据可商用”。

因此本轮没有用外部数据充覆盖率。

---

## 4. 为什么 V2 全量仍不批准

两个硬阻断：

1. **覆盖**：1,911/4,182 mmlong 无可靠上层；
2. **稳定性**：模块严格 88.8%，20 题基准 fallback 7/20。

如果现在跑 169 题 V2：

- 大量题目只能 fallback 到学科根；
- Primary 看起来稳定，但失去“函数/数列/力与运动”等中层语义；
- 不能作为 DeepTutor 的稳定知识维度。

---

## 5. 下一步

### 推荐任务

`AITUTORS-QCORE-KG-PRIMARY-ALIGNMENT-02`

范围：

1. 对 1,911 个未对齐 mmlong 节点做 **批量 LLM 分类**，候选域固定为 PrimaryCategoryIndex；
2. 自动校验：node 存在、subject 一致、evidence、confidence；
3. 仍无法可靠分类的保持 unmapped；
4. 完成 20–30 题固定基准的 **专家/规则双轨复核**；
5. 重新计算 coverage-adjusted Primary stability；
6. 达标后才启动 169 V2。

### 明确不做

- 不直接跑 169 V2；
- 不合并 K12-KGraph / China Skill / CnK12 数据；
- 不修改 4,829 节点；
- 不创建新节点；
- 不做 4,829 人工逐条审核；
- 不启动 DeepTutor。

---

## 6. 边界自检

- QCore 写入：0；
- QCore 发布状态变化：0；
- 知识节点修改：0；
- 外部数据导入：0；
- 169 V2 重跑：0；
- Embedding 选型：0；
- DeepTutor：0；
- 历史映射保留。

---

## 7. 数据与证据

```text
_dsh/workpackage_d/primary_category_index_v1.json
_dsh/workpackage_d/node_primary_alignment_v1.jsonl
_dsh/workpackage_d/node_alignment_stats_v1.json
_dsh/workpackage_d/primary_benchmark_v1.json
_dsh/workpackage_d/benchmark_result_v1.json
_dsh/workpackage_d/guard_after_hierarchy.json
```
