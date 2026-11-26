# AITUTORS-QCORE-KG-HISTORICAL-DIAGNOSIS-01

- 日期：2026-11-26
- 样本：166 道题 × 3 份有效运行（full-v1、rep2、rep3）
- 目的：判断历史 Primary 不一致中，多少可由上层化解决
- 不做逐题纠错，不做新全量映射

---

## 1. 总览

| 指标 | 数值 | 比例 |
|---|---:|---:|
| 题数 | 166 | 100% |
| 细粒度 Primary 完全一致 | 64 | 38.6% |
| level=3 粗分类完全一致 | 124 | 74.7% |
| 细粒度不同但 level=3 收敛 | 60 | 36.1% |
| level=3 仍不一致 | 42 | 25.3% |
| 严格可解析 level=3 样本 | 107 | — |
| 严格样本 level=3 一致 | 83 | 77.6% |
| level=2 模块严格一致 | 95/107 | 88.8% |
| level=1 学科严格一致 | 106/107 | 99.1% |
| 含 fallback 的题 | 59 | 35.5% |

---

## 2. 差异类型

### A. 同一上层、不同细节点

**60 题**：

- 三次运行选择了同一 level=3 章节下的不同细节点；
- 细粒度看起来不一致；
- 上移到 level=3 后一致。

这类差异应由 Secondary 吸收，不应继续当作 Primary 不稳定。

### B. Primary / Supporting 角色变化

**74 / 166 题**存在至少一次角色变化：

- 某节点在一轮是 Primary，另一轮是 Supporting；
- 说明核心/辅助边界需要显式区分；
- V2 Schema 用 role 字段表达，不把 Supporting 当 Secondary。

### C. 真实上层分类分歧

**42 题**：

- 即使上移到 level=3，仍不一致；
- 原因包括：
  - 题目本身跨两个知识领域；
  - 图谱缺少合适章节；
  - LLM 对“主要考查”判断不同；
  - 无 level=3 可解析节点。

### D. 图谱层级缺口

**246 / 975 个 primary 节点**没有 level=3：

- 无法直接上层化；
- fallback 到学科根会损失语义；
- 这是 V2 全量的硬阻断之一。

### E. 粒度问题

QCore 当前 catalog 没有结构化 subquestion 身份：

- 不能可靠把综合题拆成小问级；
- 本任务不强制拆分；
- V2 schema 保留能力，但不能声称已验证。

---

## 3. 结论

1. 上层化可解释/吸收 **60/102** 个非细粒度一致差异（约 58.8%）；
2. 剩余 **42 题**仍是上层分类真实分歧；
3. 因此 Primary 上层化是必要方向，但**不能仅靠改层级就达到 90%**；
4. 还需要：
   - PrimaryCategoryIndex；
   - mmlong 上层对齐；
   - 更明确的“主考查领域”判定；
   - 对无上层节点的显式 fallback 规则。

---

## 4. 数据

```text
_dsh/workpackage_c/hierarchy_diagnosis_v2.json
_dsh/workpackage_c/hierarchy_compatibility.json
_dsh/workpackage_c/pilot_20.json
```
