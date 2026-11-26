# AITUTORS-QCORE-KG-MAPPING-PILOT-01

- 日期：2026-11-26
- 状态：**PILOT COMPLETE / FULL MAPPING NOT APPROVED**
- 范围：20 道 published QCore Questions，4,829 节点，BM25 top-30，统一 LLM
- 人工审查：无
- QCore 写入：0
- DeepTutor 统一入口：未启动

---

## 1. 规范与输入

- 知识节点底座：`D:\Project\NLP\six-subject-kg\data\unified\merged_knowledge_points_plus_curriculum.json`
  - 4,829 nodes；
  - 不创建新节点；没有合适节点输出 unmapped。
- QCore 来源：`qcore_six_subject_accept_01` 的 169 published questions。
- 样本：20 道，按学科分层：
  - 数学 4、英语 4、语文 3、物理 3、化学 3、生物 3。
- 候选召回：BM25，subject filter，top_k=30。
- LLM：`deepseek-flash`，temperature 0，`mapping-v1` prompt，JSON object。
- 运行目录：
  ```text
  _dsh/workpackage_b/pilot/
  ```
- 正式运行：
  ```text
  run_20261126_185841_retry_retry.json
  ```

---

## 2. 映射结果

### 2.1 自动校验

| 项 | 数值 |
|---|---:|
| 样本 | 20 |
| 自动校验通过 | 19 |
| 自动校验失败 | 1 |
| 通过率 | 95% |

失败样本：

```text
化学 #11
error: NoneType object has no attribute 'group'
```

这是 LLM 返回空/非 JSON（重试后仍失败），不是 schema 或证据校验失败。

### 2.2 Unmapped

4 条 unmapped，全部是英语：

```text
英语 #11, #12, #13, #14
```

LLM 的 unmapped 理由示例：

> 题目主要考查旅游娱乐类说明文的细节信息定位，候选节点偏重语法、功能表达或写作支架，未涉及阅读细节检索这一核心考查能力。

这说明问题是**候选节点覆盖/taxonomy 缺口**，不能直接判定 LLM 映射错误。

### 2.3 映射数量

19 个有效结果：

- primary nodes 总数：26；
- 平均 primary ≈1.37；
- supporting nodes 数量 0–5；
- 4 条合法 unmapped。

---

## 3. 稳定性

固定 5 道已通过样本重跑：

| 项 | 结果 |
|---|---:|
| 重跑有效 | 5/5 |
| primary 集合完全一致 | 4/5 |
| supporting 集合完全一致 | 2/5 |

结论：

- primary 稳定性 80%，未达到建议的全量阈值 90%；
- supporting 稳定性较低（40%），说明 supporting 语义边界仍需固定；
- 不能以单次 95% schema 通过率代替语义稳定性。

证据：

```text
_dsh/workpackage_b/pilot/stability_5.json
```

---

## 4. 成本与延迟

正式 20 题（含重试）：

```text
total_tokens = 143,930
latency_sum = 313.39s
```

稳定性 5 题：

```text
total_tokens = 36,200
```

合计：

```text
tokens = 180,130
```

这是 token 用量，不是货币成本；货币成本需按当前 provider 价格换算。

---

## 5. 自动校验项

通过项：

- JSON schema；
- node_id 在候选集；
- node_id 存在；
- subject 一致；
- primary 1–3 / supporting 0–5；
- evidence quote 在题目文本；
- 无重复 node；
- confidence 范围；
- unmapped 与 primary 不冲突；
- 幂等键/候选集 hash/model/prompt 记录。

证据匹配做了规范化：去除 LaTeX 分隔符、反斜杠、空白和标点，再要求 quote 是题文本子串；不改变题目内容。

---

## 6. 关键发现

1. **BM25 top-30 对多数数学/物理/化学/生物题可用**，自动校验通过。
2. **英语阅读题出现 4/4 unmapped**，候选节点主要是语法/功能/写作节点，缺“阅读细节检索”类节点；这是 4,829 节点覆盖问题，不是简单 prompt 问题。
3. **1 条化学题 LLM 返回空 JSON**，重试仍失败；需要 API/模型稳定性处理。
4. **primary 稳定性 80%**，不满足全量阈值；supporting 稳定性 40%，边界更弱。
5. 因此不应直接全量映射；应先补英语候选/节点覆盖和模型输出稳定性，再重跑 20–50 题 pilot。

---

## 7. 门槛建议

Pilot 结果对照建议门槛：

| 指标 | 建议 | 本次 |
|---|---:|---:|
| 自动校验通过 | ≥95% | 95% |
| unmapped | ≤10% | 20% |
| primary 稳定性 | ≥90% | 80% |
| API 空输出 | 0 | 1/20 |

结论：**PILOT 完成，但 FULL MAPPING NOT APPROVED**。

---

## 8. 下一步（未执行）

1. 补 English 阅读/细节类节点或改进候选覆盖；
2. 对空 JSON 增加 provider-level retry/截断处理；
3. 重跑 20–50 题 pilot；
4. 达到门槛后才考虑全量 169/后续题目。

不启动 DeepTutor 统一入口；不写 QCore。

---

## 9. N-A 哈希勘误

`9a852ddc...` 的精确 preimage 已生成：

```text
_dsh/workpackage_a/published_hash_preimage.txt
```

169 行 `question_id:revision_id`，按 question_id、revision_number 排序，无尾随换行。

复算：

```powershell
(Get-FileHash "_dsh/workpackage_a/published_hash_preimage.txt" -Algorithm SHA256).Hash.ToLower()
```

结果与 `9a852ddc...` 一致；不是无法复现的校验值。
