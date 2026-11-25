# EULER-RETRIEVAL-ARCHITECTURE-MINIMAL-01 — 最终关闭记录

- 裁决方：Owner
- 执行：DSH
- 日期：2026-11-26
- 状态：**CLOSED / ACCEPTED**
- 关联：
  - `EULER-RETRIEVAL-ARCHITECTURE-MINIMAL-01`
  - `EULER-RETRIEVAL-INTENT-DISAMBIGUATION-01`
  - `EULER-SEMANTIC-RETRIEVAL-BGE-M3-EVALUATION-01`

---

# 1. 最终结论

本轮检索架构最小实验达到预期目的，正式关闭。

已经证明：

> 当前主要矛盾不是 Embedding 缺失，也不是 Judge 模型不够大，而是**照片中的题目结构尚不能稳定恢复为完整、准确、可验证的检索 Query**。

后续工程资源应集中在：

```text
OCR / 题目结构恢复
  → 用户目标选择
  → BM25 候选召回
  → Evidence-grounded Judge
  → QCore 身份确认
```

而不是继续扩充 Embedding / Reranker / ColBERT 模型种类。

---

# 2. 已接受的事实

| 事项 | 结果 | 证据 |
|---|---|---|
| 阶段一执行路径 | **纯 BM25**，无 Embedding/HTTP/向量检索 | 代码审计 + 动态阻断，`blocked_calls=[]` |
| 阶段一 `photo-any-segment Recall@5` | 45 渲染 + 45 真机 = **100%** | `stage1_bm25_segmented.json` |
| 阶段一 `target-segment Recall@5` | **撤销验收意义**；三字组启发式不是 oracle 分段 | 四例反证 |
| Stage2 真机 88.9% | 保留为“错误 Query 条件下的历史结果” | `stage2_oracle_judge.json` |
| Oracle Full-Query Judge | **90/90，False Exact=0，Unknown=0** | `stage2_true_oracle_query.json` |
| 四个 False Exact 主因 | **题目结构/分段/题组归属错误** | `EULER-RETRIEVAL-INTENT-DISAMBIGUATION-01.md` |
| 独立 Judge 能力失败 | **未观察到** | 完整 Query 下 90/90 |
| 生产检索链路 | **尚未验证** | 未做真实用户端到端 |

关键边界：

- `photo-any-segment 100%` 只说明目标进入某个分段的候选；
- 不说明目标题被完整、正确切分；
- 不说明生产端到端成功；
- Oracle Full-Query 90/90 是**诊断性上限**，不是生产准确率。

---

# 3. 冻结的架构原则

1. **BM25 是当前默认候选召回基线**，不依赖 Embedding。
2. **Embedding 是可选 Provider**，不属于 QCore 必需基础设施。
3. **LLM Judge 只负责候选比较**，不能创建 Question ID，也不能直接认定正式身份。
4. **题目结构恢复先于候选判断**；不完整 Query 不应进入自动 Exact 流程。
5. **多题照片必须支持目标选择**，不能把用户意图交给模型猜测。
6. **Evidence-grounded 是身份确认的必要条件**：模型引用依据必须能回溯到真实 OCR 文本；候选题完整文本不必逐字出现在 Query 中，但引用证据必须存在。
7. **Unknown 是合法结果**，不能为提高自动匹配率而放宽身份确认标准。

---

# 4. 正式关闭事项

| 项目 | 状态 |
|---|---|
| BM25-only 代码路径核实 | 通过 |
| BM25 `photo-any-segment Recall@5` | 通过 |
| `target-segment` 旧指标 | 撤销验收意义 |
| Oracle Full-Query Judge 90/90 | 通过（诊断） |
| 四个 False Exact 根因定位 | 通过 |
| 生产检索链路 | 尚未验证 |
| Embedding A/B/C | 暂停 |
| BGE-M3 / sparse / ColBERT / reranker 扩展 | 暂停 |
| 生产默认模型切换 | 不执行 |
| QCore 正式数据变更 | 不执行 |

---

# 5. 下一阶段：EULER-QUESTION-SEGMENT-RECOVERY-01

建议作为独立任务启动，但**先做只读根因定位，不直接改正则**。

## 5.1 工作方向一：根因定位与通用性

以 RP05 / RP39 / RP40 / RP43 为回归起点，检查：

- OCR 漏题号时，是否有上下文恢复机制；
- 题组和共享材料能否作为独立结构单元；
- 连续小问是否被误识别为新题；
- 上一题尾部是否污染下一题；
- OCR 行序、版面位置、题号、题组提示是否被联合利用；
- `split_questions()` 的输入/输出/调用链，以及责任层在 OCR、Preprocessing、检索分段还是交互层。

**不能把四个样本分别打补丁。** 必须先归类为通用缺陷或不同责任层。

## 5.2 工作方向二：最小修复与回归

- 保留原始 OCR 输入和历史结果；
- 不修改原始 PDF；
- 不修改 QCore 正式题目；
- 不调整 BM25 阈值，不引入 Embedding；
- 四个样本进入永久回归；
- 额外真实样本验证是否引入新的错误合并/拆分；
- 无法可靠恢复的结构标记为不确定，不猜测补齐。

## 5.3 工作方向三：交互闭环

Interactive Lesson 区分：

- 单题照片；
- 多道独立题目；
- 综合题/共享材料题组；
- 题目边界不确定。

多题时展示题目区域或题号，用户明确选择目标；选择后才构造 Query、执行 BM25、调用 Judge。

不是每张照片都强制用户选择；只有系统无法可靠确定唯一目标时才进入显式选择。

---

# 6. 不做

- 不启动 A/B/C Embedding 对比；
- 不恢复 BGE-M3 / sparse / ColBERT / reranker；
- 不为了通过四个样本写特例正则；
- 不修改生产 QCore、不切默认模型；
- 不把 Oracle 90/90 当作生产准确率；
- 不把 `photo-any-segment 100%` 当作分段正确率。

---

# 7. 证据索引

| 内容 | 路径 |
|---|---|
| 阶段一 | `docs/quality/EULER-RETRIEVAL-ARCHITECTURE-MINIMAL-01-STAGE1.md` |
| 阶段二 | `docs/quality/EULER-RETRIEVAL-ARCHITECTURE-MINIMAL-01-STAGE2.md` |
| 四例归因 | `docs/quality/EULER-RETRIEVAL-INTENT-DISAMBIGUATION-01.md` |
| BM25 provenance | `runs/qcore_semantic_expansion_01/v11/bge_m3/stage1_provenance.json` |
| Oracle full query | `runs/qcore_semantic_expansion_01/v11/bge_m3/stage2_true_oracle_query.json` |
| 四例完整 Query | `runs/qcore_semantic_expansion_01/v11/bge_m3/intent_four_full_query.json` |

---

**最终状态：检索架构最小实验 CLOSED / ACCEPTED。下一阶段转入结构恢复与交互闭环。**
