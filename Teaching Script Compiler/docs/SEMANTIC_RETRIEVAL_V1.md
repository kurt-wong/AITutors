# Semantic Retrieval V1 — 设计、阈值与真实数据评测

- 任务：`EULER-QCORE-SEMANTIC-EXPANSION-01` / Track B
- 代码：`Teaching Script Compiler/tsc_compiler/semantic/`
- 性质：Question 语义表示 + Top-K 检索 + Exact/Similar/Unknown 三态判定
- 边界：不建知识图谱、不做 Ontology、不做推荐系统、不做相似题生成

---

## 1. 能力边界

```text
Question
  → Semantic Representation（bge-small-zh-v1.5 稠密向量 + 词法/字符证据）
  → Top-K Retrieval
  → Ranking / Confidence
  → Exact / Similar / Unknown
```

输出包含：

- `candidate.question_id` / `revision_id` / `subject` / `printed_number`
- `score`（融合分）、`dense`、`lexical`、`lexical_parts`
- `number_overlap`、`option_overlap`
- `relation`（exact / similar / below_threshold）
- `decision`（exact / similar / unknown）、`reason`、`top1_margin`
- `duplicate_group`（内容完全相同的重复题标记）

**三态语义**

| 决策 | 含义 | 行为 |
| --- | --- | --- |
| `exact` | 同一道题 | 可直接进入现有 QCore 讲题路径 |
| `similar` | 不是同一题，但是有价值的参考题 | 只作为相似题/参考题返回，不得冒充原题 |
| `unknown` | 没有可靠结果 | **fail-closed**，不进入讲题 |

---

## 2. 表示与检索

三层证据：

1. **Dense**：`BAAI/bge-small-zh-v1.5`（512 维，mean pooling + L2 normalize，CPU）。
   - 模型不 vendored；`TSC_EMBEDDING_MODEL` 指向本地目录。
   - 缺失时自动退化为词法/字符层，不阻断服务。
2. **Lexical**：复用已冻结的 photo-search 索引（CJK bigram + 数字 + LaTeX 命令 + ASCII，IDF 覆盖率 + BM25）。
3. **Character 3-gram**：字符级余弦（包含在 lexical base 中）。

融合分：`0.65 × dense + 0.35 × lexical_base`（无 dense 时只用 lexical_base）。

索引只从 QCore catalog 构建；查询不能新增文档。`embedding_ref` 列已存在，但 V1 不写库，索引落盘为 `docs.json + embeddings.npy`。

---

## 3. 三态判定（fail-closed）

### 3.1 Exact

必须同时满足：

- `dense ≥ 0.84`；
- 词法覆盖率（`lexical_parts.lexical`）`≥ 0.55`；
- top1 与 top2 的分数/dense margin `≥ 0.02`（或内容完全相同的重复题）；
- 候选题干数字被 query 覆盖 `≥ 0.5`；
- 若 query 与候选都暴露 A–D 选项：选项逐项字符重叠均值 `≥ 0.40`；
- 若 query 没有选项（纯题干片段）：要求 `dense ≥ 0.93`，或 query 规范化文本包含于候选（长度比 ≥0.6）。

第二候选只有**真正接近**（margin < 0.02）才会把结果降为 `unknown`；仅仅过线但明显落后不会阻断 top1。

### 3.2 Similar

- 未达到 Exact；
- `dense ≥ 0.80`；
- 词法覆盖率 `≥ 0.55`；
- margin `≥ 0`。

Similar 永不计为 Exact；返回最多 3 条，并标注 `relation=similar`。

### 3.3 Unknown

其余一律 `unknown`，`exact=None`。低置信不返回候选作为“可靠题”，调用方不得自动讲题。

### 3.4 为什么用 lexical 作为硬门

真机负向样本（手写/非 QCore 试卷）的 dense 可以到 **0.91**，但词法覆盖率只有 **0.35–0.51**；真实拍照正向样本的词法覆盖率为 **0.60–0.86**。只靠 dense 会把无关题目判成 Exact，因此身份必须同时满足 dense + lexical + 数字/选项约束。

---

## 4. 评测集（全部来自真实题库/真实 OCR，不伪造数据）

| 集合 | 来源 | 数量 | 说明 |
| --- | --- | ---: | --- |
| Exact | PILOT-01 photo audit 20 条真实拍照 crop OCR | 20 | 数学；每题有 ground-truth question_id |
| Unknown | PREPROD-01 37 条真实手机负向 OCR（手写/非 QCore 试卷） | 37 | 期望 `unknown` |
| Similar | 生产 175 题中人工筛选的 7 组“同知识点、不同题”配对 | 7 | 查询 A、排除 A、期望 B 出现在 similar |
| Hard negative | 同科但明确无关的 12 组配对 | 12 | 期望 `unknown`，不得 exact/similar |

数据文件：`_dsh/semantic_expansion_01/eval/`（`queries_exact.jsonl`、`queries_unknown.jsonl`、`queries_pairs.jsonl`）。
所有 query 文本都来自已有 OCR 产物或人工配对，不是构造的“简单测试句”。

---

## 5. 评测结果（V1 最终阈值）

### 5.1 Exact（20 条真实拍照 OCR）

| 指标 | 值 |
| --- | ---: |
| Exact Recall | **0.65**（13/20） |
| Exact Precision | **1.00**（0 个 false exact） |
| 错误类型 | 1 条 top1 错误、2 条低 dense 未判、1 条 OCR 截断、1 条选项/词法不足、2 条相似题未达 exact |

未命中的 7 条均已人工核对：没有把错误题自动放行。

### 5.2 Unknown（37 条真实负向）

| 指标 | 值 |
| --- | ---: |
| Unknown 判定率 | **1.00**（37/37） |
| False Exact | **0** |
| False Similar | **0** |

### 5.3 Similar / Hard Negative（19 组人工配对）

| 指标 | 值 |
| --- | ---: |
| Similar Recall | **0.857**（6/7） |
| Similar Precision | **1.00** |
| Hard-negative Unknown | **0.917**（11/12） |
| False Exact | **0** |

结论：

- **Exact 与 Similar 已明确分开**：Similar 集 0 个 Exact 误判。
- **Unknown fail-closed 成立**：37 条真机负向 0 条被自动讲题。
- 代价是 Exact Recall 0.65；这是保守阈值的刻意结果（精度优先），后续可用更多 9 科真实照片扩样本再校准，不通过放宽阈值换 Recall。

---

## 6. 与现有拍照搜索的关系

现有拍照搜索（`tsc_compiler/photo/search.py`）保持不变：

- OCR 异步 Job、超时/重试、high/ambiguous/low、用户确认、fail-closed 均未改；
- Semantic V1 是**独立模块 + CLI**，可被现有搜索调用，但 V1 默认不替换现有决策；
- 若接入，建议作为 `semantic` 附加字段返回，不改变既有 `decision` 与 `may_teach`；
- 相似题只在 `decision=similar` 时展示，且不得进入讲题。

---

## 7. 代码与复现

```bash
# 1) 只读导出 QCore（含未发布，用于 Track A 评测）
python -m tsc_compiler.semantic.cli export --out data/semantic/catalog.json

# 2) 建索引（需要本地 bge-small-zh-v1.5）
TSC_EMBEDDING_MODEL=/path/to/bge-small-zh-v1.5 \
python -m tsc_compiler.semantic.cli build --catalog data/semantic/catalog.json --out data/semantic/index

# 3) 查询
python -m tsc_compiler.semantic.cli search --index data/semantic/index --query "..."

# 4) 评测
python -m tsc_compiler.semantic.cli evaluate --index data/semantic/index --queries queries.jsonl --out report.json
```

测试：`Teaching Script Compiler/tests/test_semantic_retrieval.py`（Exact / Duplicate / Unknown / 阈值报告）。

---

## 8. 明确不做

- 知识图谱 / Ontology / 跨学科知识网络；
- Cross Encoder 大规模体系；
- 推荐系统 / 学习画像 / 个性化；
- 相似题、变式题自动生成；
- 修改 Question 身份或自动合并重复题（V1 只标记 `duplicate_group`，合并需上游人工/迁移）。

---

## 9. 后续（不在本轮实现）

1. 用 9 科更多真实照片扩 Exact/Unknown 评测集；
2. 用人工确认的变式题对建立 Similar/Variant 金标；
3. 把 Similar 作为拍照搜索的附加结果接入，保持现有阈值与确认流程；
4. 将 embedding 索引纳入 `embedding_ref` 契约（内容寻址 + 模型版本）。
