# Semantic Embedding 选型 — 2026-11-25

- 任务：`SEMANTIC-RETRIEVAL-V1.1-EMBEDDING-EVALUATION` 前置选型
- 范围：Ollama 本地 4 个 embedding 模型
- 结论：**embeddinggemma-2:latest 作为 V1.1 主候选；qwen3-embedding:0.6b 作为轻量备选；BGE-small 继续作为 V1 冻结基线**
- 性质：工程选型，不是统计显著性的最终结论

---

## 1. 候选模型

| 模型 | 参数 | 维度 | 上下文 | 量化 | 磁盘 |
|---|---:|---:|---:|---|---:|
| `BAAI/bge-small-zh-v1.5`（V1 基线） | ~24M | 512 | 512 | F16 | 91MB |
| `nomic-embed-text:latest` | 137M | 768 | 2048 | F16 | 274MB |
| `qwen3-embedding:0.6b` | 596M | 1024 | 32768 | Q8_0 | 639MB |
| `qwen3-embedding:4b` | 4B | 2560 | 40960 | Q4_K_M | 2.5GB |
| `embeddinggemma-2:latest` | 271M | 768 | 262144 | Q8_0 | 1.3GB |

`embeddinggemma-2` 同时带 vision/audio capability，但本次只用文本 embedding。

---

## 2. 评测方法

两套冻结语料：

| 语料 | 文档 | Exact 查询 | Unknown 负向 | Similar/Hard-negative |
|---|---:|---:|---:|---:|
| Track A（9 科） | 1166 | 18 条真实 crop OCR | 37 条真机负向 | — |
| 生产 175（6 科） | 175 | 20 条真实拍照 OCR | 37 条真机负向 | 7 正例 + 12 hard negative |

评测分两层：

1. **Dense-only Recall@1 / MRR**：排除 lexical 影响，只看 embedding 的身份排序能力。
2. **V1 fused 决策**：`0.65 × dense + 0.35 × lexical`，沿用 Exact/Similar/Unknown 规则，逐模型校准 `exact_dense` 与 `similar_dense`。

**安全工作点**：Exact 取 0 false exact 下最高命中；Similar 取 Unknown 37/37 且 Hard-negative 0 false similar 下最高命中。

---

## 3. 结果

### 3.1 Dense-only

| 模型 | Track A Recall@1 | 生产 Recall@1 | 负向 top1 p95 |
|---|---:|---:|---:|
| nomic-embed-text | 0.722 | **0.900** | 0.794 |
| qwen3-embedding:0.6b | **0.833** | 0.850 | 0.765 |
| qwen3-embedding:4b | 0.778 | 0.850 | **0.721** |
| embeddinggemma-2 | 0.722 | 0.850 | 0.837 |

Dense-only 只能看排序；真正可用性要看融合决策。

### 3.2 安全工作点（0 false exact；Unknown 37/37；除 BGE 冻结基线外 0 hard false-similar）

| 模型 | 配置 | Exact（38） | False Exact | Unknown | Similar（7） | Hard-negative Unknown（12） | 建索引 | 94 查询 |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| BGE-small（V1 冻结） | .84/.80/.55 | 22 | 0 | 37/37 | **6** | 11/12（+1 false similar） | 秒级 CPU | 秒级 |
| nomic-embed-text | .70/.85/.55 | 21 | 0 | 37/37 | 2 | **12/12** | 47s | 4.3s |
| qwen3-embedding:0.6b | .70/.85/.55 | 23 | 0 | 37/37 | 1 | **12/12** | 50s | 6.1s |
| qwen3-embedding:4b | .70/.80/.55 | 23 | 0 | 37/37 | 2 | **12/12** | 166s | 23.7s |
| **embeddinggemma-2** | **.74/.85/.55** | **24** | **0** | **37/37** | 4 | **12/12** | **~23s** | **~2s** |

> BGE 的 6/7 Similar 伴随 1 个 hard-negative false-similar（PN02）；此前报告里的“Similar Precision 100%”是分母漏算 `false_similar` 的指标 bug，正确口径是 6/7。BGE 作为冻结基线保留，不参与本轮重调。

Exact 拆分：

| 模型 | Track A /18 | 生产 /20 | 合计 /38 |
|---|---:|---:|---:|
| BGE-small | 9 | 13 | 22 |
| nomic | 8 | 13 | 21 |
| qwen0.6b | 10 | 13 | 23 |
| qwen4b | 10 | 13 | 23 |
| **gemma-2** | **11** | **13** | **24** |

### 3.3 放宽 Similar 到 .80 的代价

若把 gemma-2 的 `similar_dense` 放回 .80：

- Exact 仍为 24/38，Similar 升到 **6/7**；
- 但 Unknown 变为 **36/37**，Hard-negative false-similar 变为 **1/12**；
- 具体是 PU28（物理直线加速题）与 PN13（数学几何题）被误标为 similar。

**结论：Fail-closed 优先，gemma 采用 `.85` 的 Similar 门槛；4/7 Similar 是可接受代价，Similar 只展示参考，不进入讲题。**

---

## 4. 结论

### 主选：`embeddinggemma-2:latest`

- 安全工作点 `.74/.85/.55`：Exact **24/38**、0 false exact、Unknown **37/37**、Hard-negative **12/12**、Similar 4/7；
- 262k context，长题干不再被 512 截断；
- 1166 题建索引约 **23 秒**，94 条查询约 **2 秒**；
- 1.3GB / 768 维，成本可接受。

### 备选：`qwen3-embedding:0.6b`

- 23/38 Exact、0 false exact、37/37 Unknown、12/12 Hard-negative；
- 639MB / 1024 维 / 32k context，比 4b 更轻；
- Similar 只有 1/7，适合“Exact + fail-closed 优先、Similar 暂时弱化”的部署。

### 不作为默认

- `qwen3-embedding:4b`：Exact 与 0.6b 相同，Similar 更弱，2.5GB/166s，性价比低；保留为对照。
- `nomic-embed-text`：2048 context 太短，长题截断；Exact 21/38。
- `BGE-small`：继续作为 V1 冻结基线，不立即替换；512 context 是明确短板。

---

## 5. 限制与下一步

1. Exact 只有 38 条（18 + 20），Similar 仅 7 正例/12 hard negative；阈值是在同一评测集上选的，存在选择偏差，不能宣称统计泛化。
2. 本轮只做“选型”，**不修改 V1 代码/阈值/生产决策**。
3. V1.1 实施前需要：
   - 用独立 holdout 或新增 9 科真实照片复核 `.74/.85`；
   - 明确 Similar 的展示策略（4/7 是否足够，是否加 rerank）；
   - 处理 embeddinggemma-2 的模型体积/部署方式（Ollama 服务化 vs 本地文件）；
   - 保持 Exact 0 false exact 与 Unknown fail-closed 不回退。

---

## 6. 证据

| 内容 | 路径 |
|---|---|
| 三模型（nomic/qwen0.6/qwen4b）原始对比 | `_dsh/semantic_expansion_01/selection/embedding_model_comparison.json` |
| 四模型 targeted 配置 | `_dsh/semantic_expansion_01/selection/embedding_targeted_configs.json` |
| 评测脚本 | `_dsh/semantic_expansion_01/embedding_selection.py`、`quick_config.py` |
| 冻结评测集 | `_dsh/semantic_expansion_01/eval/` |
