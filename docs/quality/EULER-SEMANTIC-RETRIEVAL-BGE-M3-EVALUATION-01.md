# EULER-SEMANTIC-RETRIEVAL-BGE-M3-EVALUATION-01

- 执行：DSH
- 日期：2026-11-25
- 目标：按 ChatGPT 建议，评估 BGE-M3 / BM25 / hybrid / reranker，而不是只比较单一 dense 模型
- 数据：45 渲染 Holdout + 45 真实手机照片 + 1166 QCore corpus
- 生产：**未切换默认模型，未写 QCore，未改 BGE V1**
- **最终状态：INCONCLUSIVE（不替换 BGE V1）**

---

# 0. 执行摘要

本地 BGE-M3 通过 LocModel/llama.cpp 部署，实际提供的是 **dense-only `/v1/embeddings`**；**没有暴露 BGE-M3 的 sparse / multi-vector 输出**。因此本轮只能验证：

- BGE-M3 dense；
- BM25 词法基线；
- dense + BM25 加权 / RRF hybrid；
- BGE reranker（`bge-reranker-v2-m3`）。

核心结果（候选目标是否进入 top-k）：

| 数据集 | 最佳方法 | @1 | @10 |
|---|---|---:|---:|
| 渲染 Holdout 45 | gemma-2 dense / BGE-M3+BM25 α=.7 | 95.6% | 100% |
| 真实照片 45 | gemma-2 / BGE-M3+BM25 α=.7 | 68.9% | 100% |

但：

- **BGE-M3 dense 单独没有超过当前 BGE-small / gemma-2**；
- **BM25 单独非常强**，真实照片 @10 已达 97.8%；
- **dense+BM25 加权**能到 100% @10，但 @1 与 gemma 持平，不能证明是 BGE-M3 的贡献；
- **BGE reranker 在当前 Q4 部署 + 整页/长 OCR 输入下严重退化**，不可用；
- **BGE-M3 的核心 sparse/multi-vector 能力没有被本地服务暴露**，因此不能得出“BGE-M3 架构无效”的结论，但也不能得出“值得替换”的结论。

**结论：不替换 BGE V1。若要继续验证 BGE-M3 的架构价值，必须先部署真正输出 sparse/multi-vector 的 FlagEmbedding 服务，并改用 segment-level rerank。**

---

# 1. 本地部署与模型身份

## 1.1 启动情况

用户给出的端点最初没有监听。检查发现 LocModel 已经下载模型，但服务进程未启动。本轮使用 LocModel 自带 llama.cpp 引擎启动：

```text
C:\Users\Kurtw\AppData\Local\LocModel\engines\b12626-cuda-12.4\llama-server.exe
```

参数：

```text
BGE-M3:
  -m D:\AI-Models\bge-m3\bge-m3-Q4_K_M.gguf
  --embedding --pooling cls
  --host 127.0.0.1 --port 8788
  -c 8192 -b 8192 -ub 8192 -ngl all -np 1

Reranker:
  -m D:\AI-Models\bge-reranker-v2-m3\bge-reranker-v2-m3-Q4_K_M.gguf
  --rerank --pooling rank
  --host 127.0.0.1 --port 8787
  -c 8192 -b 8192 -ub 8192 -ngl all -np 1
```

第一次启动的物理 batch 只有 512，导致 566-token 输入报错；调整为 `-b 8192 -ub 8192` 后正常。

## 1.2 模型身份

| 模型 | 文件 | 大小 | SHA-256 | 维度/上下文 |
|---|---|---:|---|---|
| BGE-M3 | `bge-m3-Q4_K_M.gguf` | 437,778,496 B | `6d39681b26c61279ac1f82db35a04a05009e94c415b51c858ff571489a82fc06` | 1024 dim / 8192 ctx |
| BGE reranker v2 m3 | `bge-reranker-v2-m3-Q4_K_M.gguf` | 438,376,864 B | `e186a244ed455b4ab66ec64339ce7427a6ae13f5c0b5e544de96e50f0f8b3673` | cross-encoder / 8192 ctx |

- 端点：`http://127.0.0.1:8788/v1/embeddings`、`http://127.0.0.1:8787/v1/rerank`；
- BGE-M3 实际返回 **1024 维**；
- 1166 docs 建索引 **约 20 秒**，163 次调用，310,209 tokens；
- 最长文档 5,761 tokens；最长查询 8,065 tokens（< 8192，未观察到截断）；
- 单条 embedding 约 0.06s；batch8 约 0.16s；
- reranker 20 条短文档约 0.12s；本轮 178 次调用约 128s（长文档约 0.7s/次）；
- 运行中 GPU 约 3.4GB / 8GB（含两个服务和旧服务）。

## 1.3 关键限制：没有 sparse / multi-vector

`/v1/embeddings` 只返回 dense 向量；`/v1/models` 没有 sparse 或 multi-vector 字段。llama.cpp 的 `--embedding` 模式不输出 BGE-M3 的 lexical weights / ColBERT multi-vector。

因此：

- **BGE-M3 sparse 未实测**；
- **BGE-M3 multi-vector 未实测**；
- 本轮用 **BM25** 作为 lexical/sparse 的替代基线；
- 不能把“dense+BM25”结果等同于“BGE-M3 dense+sparse”。

---

# 2. 数据与评测口径

## 2.1 数据

| 数据集 | 数量 | 说明 |
|---|---:|---|
| QCore corpus | 1166 | 9 科 Track A |
| 渲染 Holdout R2 | 45 | 27 holdout + 18 confirm，单题裁剪 |
| 真实手机照片 | 45 | iPhone 12 Pro Max，整页/多题，原始文件名 |
| 开发集 Exact | 38 | 18 9科 + 20 生产数学；生产题不在 1166 corpus，未混入主表 |

本轮主表只用 **1166 语料内的 45+45**，避免跨 corpus 目标缺失。

## 2.2 指标

不先问“Exact 阈值命中率”，而问 **正确 Question 是否进入候选 top-k**：

- Coverage@1/3/5/10/20；
- 目标不在 top-50 记为 missing；
- 不做阈值调参，不根据结果改 `.74/.85` 或 BGE 配置。

## 2.3 方法

1. **BGE-small dense**（生产 V1 基线）
2. **gemma-2 dense**（V1.1 候选）
3. **BGE-M3 dense**
4. **BM25**（词法基线）
5. **dense + BM25 RRF**
6. **dense + BM25 加权融合**（α=0.3/0.5/0.7，归一化后线性组合）
7. **BGE reranker** 对 hybrid/dense top-20 重排

---

# 3. 结果

## 3.1 渲染 Holdout（45，单题裁剪）

| 方法 | @1 | @3 | @5 | @10 | @20 | missing |
|---|---:|---:|---:|---:|---:|---:|
| BGE-small | 86.7% | 95.6% | 95.6% | 95.6% | 100% | 0 |
| gemma-2 | **95.6%** | 100% | 100% | 100% | 100% | 0 |
| BGE-M3 dense | 93.3% | 97.8% | 97.8% | 100% | 100% | 0 |
| BM25 | 91.1% | 100% | 100% | 100% | 100% | 0 |
| BGE-M3 + BM25 RRF | 93.3% | 100% | 100% | 100% | 100% | 0 |
| 加权 α=0.7 | **95.6%** | 100% | 100% | 100% | 100% | 0 |
| 加权 α=0.5 | 93.3% | 100% | 100% | 100% | 100% | 0 |
| 加权 α=0.3 | 93.3% | 100% | 100% | 100% | 100% | 0 |
| BGE reranker（hybrid top20） | 66.7% | 75.6% | 77.8% | 88.9% | 100% | 0 |
| BGE reranker（dense top20） | 68.9% | 73.3% | 75.6% | 86.7% | 100% | 0 |

观察：

- BGE-M3 dense 比 BGE-small 好，但**没有超过 gemma**；
- BM25 已到 100% @3，说明单题裁剪下词法极强；
- 加权 α=0.7 与 gemma 并列 95.6% @1；
- reranker 明显把排序弄坏（93.3% → 66.7% @1）。

## 3.2 真实照片（45，整页/多题）

| 方法 | @1 | @3 | @5 | @10 | @20 | missing |
|---|---:|---:|---:|---:|---:|---:|
| BGE-small | **68.9%** | 91.1% | 93.3% | 93.3% | 93.3% | 1 |
| gemma-2 | **68.9%** | 86.7% | 91.1% | 97.8% | 100% | 0 |
| BGE-M3 dense | 64.4% | 84.4% | 86.7% | 93.3% | 95.6% | 1 |
| BM25 | 64.4% | 88.9% | 93.3% | 97.8% | 97.8% | 0 |
| BGE-M3 + BM25 RRF | 62.2% | 82.2% | 88.9% | 95.6% | 100% | 0 |
| 加权 α=0.7 | **68.9%** | 84.4% | 93.3% | **100%** | 100% | 0 |
| 加权 α=0.5 | 66.7% | 86.7% | 93.3% | 97.8% | 100% | 0 |
| 加权 α=0.3 | 64.4% | 88.9% | 93.3% | 97.8% | 100% | 0 |
| BGE reranker（hybrid top20） | **6.7%** | 13.3% | 15.6% | 33.3% | 100% | 0 |
| BGE reranker（dense top20） | 6.7% | 8.9% | 15.6% | 35.6% | 95.6% | 2 |

观察：

- 真实照片上 BGE-M3 dense **低于** BGE-small/gemma @1；
- BM25 的 @10 已经 97.8%；
- 加权 α=0.7 达到 100% @10，但 @1 与 gemma 持平；
- RRF 不如加权；
- reranker 在真实整页照片上几乎把目标排到末尾（@1 6.7%），不可用。

## 3.3 Reranker 异常说明

- reranker 对明显短 pair 正常（“苹果颜色”等测试正确）；
- 但对真实/长 OCR 输入，目标分数经常低于无关文档；
- 已尝试 `--pooling rank`，分数不变；
- 可能原因：
  - Q4_K_M 量化对 cross-encoder 影响；
  - 整页/多题 query 过长、OCR 噪声；
  - 长文档截断/注意力稀释；
  - 未做 segment-level rerank。
- **不能据此否定 BGE reranker 全系列**；只能结论：**当前部署 + 整页输入不可用**。

---

# 4. 与 ChatGPT 预期的差异

ChatGPT 预期 BGE-M3 的 **dense + sparse + multi-vector** 可能带来架构升级。实际本地部署：

1. **sparse 未暴露**：无法验证 lexical weights；
2. **multi-vector 未暴露**：无法验证 ColBERT late interaction；
3. 只能用 BM25 代替 sparse；
4. dense-only BGE-M3 没有超过 gemma/BGE；
5. hybrid 加权有提升，但提升主要来自 BM25 的 lexical 信号，不能归因于 BGE-M3；
6. reranker 当前不可用。

因此，本轮回答的是：

> **在当前 llama.cpp dense-only 部署下，BGE-M3 不值得替换 BGE V1。**

而不是：

> BGE-M3 架构无效。

---

# 5. 结论

1. **不替换生产默认 BGE-small。**
2. **BGE-M3 dense 不优于 gemma-2，也不稳定优于 BGE-small。**
3. **BM25 是不可忽视的强基线**：单题和整页 @10 都很高。
4. **dense+BM25 加权是可行方向**，但当前收益不足以证明需要 BGE-M3；需要真正的 sparse 权重再测。
5. **reranker 需要换部署/分段再测**，当前结论是不可用，不是“reranker 无用”。
6. **BGE-M3 sparse / multi-vector 必须在 FlagEmbedding 或支持该输出的服务上单独验证**；llama.cpp dense-only 不能代表 BGE-M3 的完整能力。

推荐下一步：

- 用 FlagEmbedding 部署 BGE-M3，输出 dense + sparse + multi-vector；
- 做真正的 `dense+sparse`、`dense+sparse+multi-vector`、segment-level rerank；
- 同一 45+45 数据、同一候选 recall 口径；
- 仍不切换生产，先证明增量。

---

# 6. 证据

| 内容 | 路径 |
|---|---|
| BGE-M3 client | `_dsh/semantic_expansion_01/bge_m3_client.py` |
| 向量构建 | `_dsh/semantic_expansion_01/build_bge_m3_embeddings.py` |
| 主评测 | `_dsh/semantic_expansion_01/evaluate_bge_m3.py` |
| 加权融合 | `_dsh/semantic_expansion_01/eval_fusion.py` |
| 原始评测结果 | `runs/qcore_semantic_expansion_01/v11/bge_m3/bge_m3_eval.json` |
| 加权融合结果 | `runs/qcore_semantic_expansion_01/v11/bge_m3/fusion_eval.json` |
| 查询/文档元数据 | `runs/qcore_semantic_expansion_01/v11/bge_m3/queries_meta.json`、`docs_meta.json` |
| 既有 V1.1 报告 | `docs/quality/EULER-SEMANTIC-EMBEDDING-V1.1-VALIDATION-CONSOLIDATED-REPORT.md` |
