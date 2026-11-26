# AITUTORS-QCORE-KG-MAPPING-PILOT-01

- 日期：2026-11-26
- 状态：**PILOT COMPLETE / THRESHOLDS MET / FULL MAPPING PENDING OWNER**
- 范围：20 道 published QCore Questions，4,829 节点，BM25 top-30，统一 LLM
- 人工审查：无
- QCore 写入：0
- DeepTutor 统一入口：未启动

---

## 1. 规范与输入

- 节点底座：`D:\Project\NLP\six-subject-kg\data\unified\merged_knowledge_points_plus_curriculum.json`
  - 4,829 nodes；
  - 不创建新节点；没有合适节点输出 unmapped。
- QCore：`qcore_six_subject_accept_01` 的 169 published questions。
- 样本：20 道，按学科分层：
  - 数学 4、英语 4、语文 3、物理 3、化学 3、生物 3。
- 候选：BM25，subject filter，top_k=30；
  - query 加入 section/question_type；English reading 类加“阅读理解/细节/信息/定位/主旨/语篇”查询扩展；
  - 不引入 Embedding。
- LLM：`deepseek-flash`，temperature 0，`mapping-v1` prompt，JSON object，max_tokens 6000。
- 运行目录：
  ```text
  _dsh/workpackage_b/pilot/
  ```
- 最终运行：
  ```text
  run_20261126_193011_retry.json
  ```

---

## 2. 最终结果

| 指标 | 结果 |
|---|---:|
| 样本 | 20 |
| 自动校验通过 | **20 / 20** |
| 通过率 | **100%** |
| unmapped | **0** |
| primary nodes 总数 | 38 |
| primary 平均 | 1.9 |
| API 空 JSON | 0 |

### 稳定性

固定 5 道已通过样本重跑：

| 项 | 结果 |
|---|---:|
| 重跑有效 | 5/5 |
| primary 集合完全一致 | **5/5 = 100%** |
| supporting 集合完全一致 | 4/5 = 80% |

### 成本与延迟

正式 20 题（含重试）：

```text
total_tokens = 169,999
latency_sum = 335.81s
```

稳定性 5 题：

```text
total_tokens = 39,105
```

合计：

```text
tokens = 209,104
```

这是 token 用量，不是货币成本；货币成本需按当前 provider 价格换算。

---

## 3. 自动校验

通过项：

- JSON schema；
- node_id 在候选集；
- node_id 存在；
- subject 一致；
- primary 1–3 / supporting 0–5；
- evidence quote 是题目原文的一个连续片段；
- 无重复 node；
- confidence 范围；
- unmapped 与 primary 不冲突；
- 幂等键/候选集 hash/model/prompt 记录。

证据匹配做了规范化：去除 LaTeX 分隔符、`\text{}`/`\mathrm{}` 包裹、反斜杠、空白和标点，再要求 quote 是题文本子串；不改变题目内容。

---

## 4. 失败项的根因与修复

### 4.1 English 4/4 unmapped（已修复）

根因：

- 初始 BM25 query 只用题干/材料/选项；
- English 节点名多为中文语法/功能/写作节点，英文题干与中文节点缺少词面重叠；
- 前 30 没有“阅读细节/信息定位”节点，LLM 合法输出 unmapped。

修复：

- BM25 query 增加 section、question_type；
- English reading 类加入“阅读理解/细节/信息/定位/主旨/语篇”查询扩展；
- 仍是 BM25，不引入 Embedding。

结果：最终 0 unmapped，English 4 题全部有映射。

### 4.2 Evidence quote 不是连续片段（已修复）

根因：

- LLM 把多个小问拼接成一个 quote；
- 数学/物理 quote 含 LaTeX 格式差异；
- 自动校验严格拒绝。

修复：

- Prompt 要求 evidence_quote 必须是原文一个连续片段；
- 校验规范化 `\text{}` / `\mathrm{}` / LaTeX 分隔符；
- 不伪造证据。

结果：最终 20/20 通过。

### 4.3 API 空 JSON / 截断（已修复）

根因：

- 个别题在 completion budget 内只返回 reasoning，没有有效 JSON；
- 重试后仍有 1 条失败。

修复：

- completion budget 提到 6000；
- 重试机制；
- 失败只做重试，不伪造结果。

结果：最终 0 条空 JSON。

---

## 5. 门槛对照

| 指标 | 建议门槛 | 本次 |
|---|---:|---:|
| 自动校验通过 | ≥95% | **100%** |
| unmapped | ≤10% | **0%** |
| primary 稳定性 | ≥90% | **100%** |
| API 空输出 | 0 | **0** |

结论：

```text
PILOT THRESHOLDS MET
```

---

## 6. 语义质量边界

自动校验只能证明：

- 结构正确；
- 节点来自候选；
- 学科一致；
- 证据确实来自题目；
- 可重跑、可版本化。

它**不能**证明 LLM 选择的节点在学科语义上一定正确。本轮没有人工逐条审查，符合既定原则；因此：

- Pilot 的结论是“映射管线达到自动质量门槛”；
- 不是“4,829 节点映射已全部语义正确”。

---

## 7. 当前决策

- B Pilot 完成；
- 全量 169 题映射**尚未启动**，需要 Owner 根据 Pilot 门槛结果决定；
- 不启动 DeepTutor 统一入口；
- 不写 QCore；
- 不创建新节点。

---

## 8. N-A 哈希勘误

`9a852ddc...` 的精确 preimage：

```text
_dsh/workpackage_a/published_hash_preimage.txt
```

169 行 `question_id:revision_id`，按 question_id、revision_number 排序，无尾随换行。

复算：

```powershell
(Get-FileHash "_dsh/workpackage_a/published_hash_preimage.txt" -Algorithm SHA256).Hash.ToLower()
```

结果与 `9a852ddc...` 一致，N-A 关闭。
