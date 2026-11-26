# AITUTORS-QCORE-KG-FULL-MAPPING-01

- 日期：2026-11-26
- 状态：**FULL MAPPING PRODUCED / STABILITY FAILED / NOT APPROVED FOR CONSUMPTION**
- 范围：169 published QCore Questions → 4,829 节点
- 人工审查：无
- QCore 写入：0
- DeepTutor 统一入口：未启动
- 派生层：PostgreSQL `mytutor_annotation.qcore_kg_mapping`

---

## 1. 输入与版本

| 项 | 值 |
|---|---|
| QCore | `qcore_six_subject_accept_01`，169 published |
| 知识节点 | 4,829，`merged_knowledge_points_plus_curriculum.json` |
| 节点 SHA256 | `623e383b4d0b125a2a8ecd8b8cc46d9d6fb584e51ca5720dd4a073621d89e149` |
| QCore catalog SHA256 | `7be66ce7c97bf51386f6bdada7617552b925a4105ea829a18d75142238018122` |
| published 清单 SHA256 | `cfa7942c60e598ad1ddccc14520f1dd015dcefa40d016f50ea188097e91a3084` |
| 候选 | BM25 + subject filter，top_k=30 |
| LLM | `deepseek-flash`（alias） |
| Prompt | `mapping-v1` |
| 重复调用 | temperature 0，seed 42 |

---

## 2. 全量结果

### 2.1 状态

| 状态 | 数量 |
|---|---:|
| validated | 160 |
| unmapped | 9 |
| rejected | 0 |
| 合计 | 169 |

自动校验通过：**169/169**（unmapped 是合法结果）。

### 2.2 覆盖

```text
validated coverage = 160/169 = 94.7%
unmapped = 9/169 = 5.3%
```

unmapped 分布：

| 学科 | unmapped |
|---|---:|
| 英语 | 4 |
| 数学 | 2 |
| 语文 | 2 |
| 化学 | 1 |
| 物理 | 0 |
| 生物 | 0 |

### 2.3 节点与 confidence

| 项 | 数值 |
|---|---:|
| primary nodes | 335 |
| supporting nodes | 267 |
| unique nodes used | 490 / 4,829 |
| confidence high (≥0.8) | 301 |
| confidence mid (0.6–0.8) | 204 |
| confidence low (<0.6) | 97 |

### 2.4 成本

```text
full-v1 tokens = 1,467,084
rep2 tokens = 1,455,740
rep3 tokens = 1,426,866
stability10 tokens = 87,507
合计 = 4,437,197 tokens
```

这是 token 用量，不是货币成本。

---

## 3. 稳定性：未通过

### 3.1 Full 抽样复跑

固定 10 道 validated 题：

| 指标 | 结果 |
|---|---:|
| 有效复跑 | 10/10 |
| primary 集合完全一致 | **5/10 = 50%** |
| supporting 集合完全一致 | 3/10 = 30% |

门槛要求 primary ≥90%，实际 50%，**不通过**。

### 3.2 三轮两两一致性

对 169 题做 leave-one-out 两两共识比较（有 166 题三对可用）：

```text
pair-consensus primary equal = 106 / 166 = 63.9%
```

这说明 primary 选择存在系统性不稳定，不是 10 题抽样偶然。

### 3.3 尝试过的优化

- temperature 0；
- seed 42；
- 固定 prompt / top_k / subject filter；
- 提高 max_tokens；
- 重试空 JSON；
- 三轮多数票生成 `full-v2-consensus`。

结果：

- `full-v2-consensus` 仍是 160 validated / 9 unmapped；
- primary 多数票无法解决模型在不同轮次选择不同 primary 集合的问题。

---

## 4. 失败根因

### 4.1 直接根因

**模型对 primary 节点集合的选择不稳定**。

即使：

- temperature=0；
- seed=42；
- 固定候选集、prompt、输入 revision；

同一道题的 primary 集合仍会在不同调用中变化。

因此：

- 自动校验通过只能证明“结构/证据/候选约束”正确；
- 不能证明“同一输入跨调用稳定”；
- 不满足 primary 稳定性 ≥90% 的全量消费门槛。

### 4.2 机制性原因

- `deepseek-flash` 是 **alias**，不是不可变模型版本；
- API 不提供可验证的精确模型 revision；
- 相同 alias 的后端行为可能变化；
- 单次映射不能作为稳定语义事实。

### 4.3 不是以下原因

- 不是 BM25 候选为空（169 题均有 top-30）；
- 不是 schema 错误（169/169 自动校验）；
- 不是 evidence 缺失（全部通过）；
- 不是 QCore 数据问题；
- 不是人工审查缺失。

---

## 5. 派生层状态

数据库：

```text
mytutor_annotation.qcore_kg_mapping
```

表：

```text
mapping_runs
question_node_map
```

版本：

```text
full-v1              # 单次全量
full-v2-consensus    # 三轮多数票，仍不稳定
```

幂等性：

```text
full-v1 rows = 169
distinct (question_id, revision_id) = 169
```

未写入 QCore Question/Revision；未修改发布状态。

---

## 6. 生产边界

- 不切换检索/教学服务；
- 不把 full-v1 / full-v2 作为生产消费；
- 不启动 DeepTutor 统一入口；
- 9 条 unmapped 保持 unmapped；
- 不创建新节点；
- 不人工逐条审核。

---

## 7. 最终结论

```text
FULL MAPPING DATA PRODUCED
AUTO VALIDATION PASSED
PRIMARY STABILITY FAILED
NOT APPROVED FOR CONSUMPTION
```

全量映射数据和统计已经建立，可作为：

- 第一版候选映射数据集；
- 节点覆盖/分布分析材料；
- 后续稳定性优化的基线。

但它**不能**作为 stable semantic mapping 进入生产消费。

---

## 8. 下一步（未执行）

必须先解决 primary 稳定性，二选一：

1. **固定可验证的精确模型版本**（provider/model revision）；
2. **多轮共识 + 明确的 primary 选择规则**，并重新定义稳定性验收；
3. 或把 primary 限定为单一核心节点，supporting 单独容忍变化。

在稳定性 ≥90% 前，不启动 DeepTutor 消费。

---

## 9. 证据

```text
_dsh/workpackage_b/full/full_20261126_201105_stats.json
_dsh/workpackage_b/full/full_stats_final.json
_dsh/workpackage_b/full/stability_10.json
_dsh/workpackage_b/full/consensus_stats.json
_dsh/workpackage_b/full/pair_stability.py 输出
_dsh/workpackage_b/full/guard_after_full.json
_dsh/workpackage_a/published_hash_preimage.txt
```

QCore guard：与冻结基线全等。QCore 写入：0。
