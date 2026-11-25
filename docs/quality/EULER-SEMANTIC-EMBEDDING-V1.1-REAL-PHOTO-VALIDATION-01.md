# EULER-SEMANTIC-EMBEDDING-V1.1-REAL-PHOTO-VALIDATION-01

- 执行：DSH
- 日期：2026-11-25
- 关联：`EULER-SEMANTIC-EMBEDDING-V1.1-ISOLATED-VALIDATION-01`
- 真实照片：`Interactive Lesson/tests/pic/V11/`，45 张 iPhone 12 Pro Max 原图，未改文件名
- 标签 manifest SHA-256：`e407ba721836606789444b1e3c2c0a07ab1c7060c03c1d5fd6b1f5bae37378a2`
- 冻结配置：`.74/.85/.55`，未因本次结果调整
- **最终状态：FAIL（strict target）**
- **2026-11-25 后续：Owner 选择“整页拍照 + 多候选 + 用户选择”；隔离原型 gemma 45/45 目标进入 top-10、BGE 44/45，且不再自动输出单一 Exact。见 `docs/quality/EULER-SEMANTIC-EMBEDDING-V1.1-MULTI-CANDIDATE-01.md`。生产默认仍不切换。**
- **生产默认模型：不切换，BGE V1 继续冻结**

---

## 1. 结论

45 张真实相机照片上，按“每张照片的目标题”严格判定：

| 模型 | Exact | Exact Recall | False Exact | Similar | Unknown |
|---|---:|---:|---:|---:|---:|
| BGE V1 | 20/45 | 44.4% | **4** | 11 | 10 |
| gemma-2 V1.1 | 16/45 | 35.6% | **4** | 9 | 16 |

**双方都没有达到 False Exact = 0。**

但逐条核对后，4 个 False Exact **全部是照片中同时出现多道题，模型选中了同一张照片里的另一道题**；没有一条是匹配到照片中不存在的题。根因是拍摄输入不是“单题裁剪”，而是整页/多题照片。

因此：

- **严格目标判定：FAIL**；
- **模型身份安全性：没有观察到“凭空错题”**，观察到的是“多题页面中的目标选择错误”；
- BGE 与 gemma 都被这个问题击中，不能把责任单独归给 V1.1；
- 但 gemma 在真实照片上的 Exact（16）低于 BGE（20），没有表现出升级收益；
- 无论根因如何，**本轮不授权生产切换**。

---

## 2. 照片与 OCR

- 45 张，iPhone 12 Pro Max，原始文件名 `IMG_8123.jpeg`–`IMG_8167.jpeg`；
- 未改名、未裁切、未旋转；
- OCR：45/45 status=ok（PaddleOCR-VL-1.5）；
- 部分照片是**对电脑屏幕拍摄**（能看到任务栏/窗口），不是纯纸质拍摄；属于真实输入，但拍摄质量不均。

标签冻结方法：

- 相机文件按名称排序，与冻结 Holdout 的 45 个目标顺序配对；
- OCR 文本覆盖率校验：44/45 的 top1 与目标顺序一致；
- 低置信度 6 张人工看图核对：IMG_8124（语文 Q22）、IMG_8127（语文 Q16—19）、IMG_8128（数学 Q20）、IMG_8157（历史 Q7）、IMG_8158（地理 Q6）、IMG_8161（地理 Q6）；
- 标签不是由 BGE/gemma 生成的。

---

## 3. 分科结果

| 学科 | BGE Exact / False | gemma Exact / False |
|---|---:|---:|
| 语文 | 2 / 0 | 2 / 0 |
| 数学 | 1 / 1 | 0 / 1 |
| 英语 | 5 / 0 | 3 / 0 |
| 物理 | 3 / 0 | 3 / 0 |
| 化学 | 1 / 0 | 2 / 0 |
| 生物 | 2 / 0 | 0 / 0 |
| 历史 | 0 / 2 | 1 / 2 |
| 地理 | 2 / 1 | 3 / 1 |
| 政治 | 4 / 0 | 2 / 0 |

gemma 在化学、地理略好；英语、生物明显低于 BGE；历史双方都被多题照片击中。

---

## 4. 四个 False Exact 逐条

| 照片 | 目标 | 实际 Top1 | 模型 | Top1 是否在同一照片中可见 | 说明 |
|---|---|---|---|---|---|
| IMG_8131 | 数学 Q14 | 数学 Q15 | BGE | 是（覆盖率 1.00） | 照片同时含 Q12–Q17 |
| IMG_8130 | 数学 Q12 | 数学 Q13 | gemma | 是（覆盖率 1.00） | 照片同时含 Q11–Q13 |
| IMG_8154 | 历史 Q30 | 历史 Q29 | BGE + gemma | 是（覆盖率 0.769） | 照片同时含 Q29–Q30 |
| IMG_8156 | 历史 Q8 | 历史 Q9 | BGE + gemma | 是（覆盖率 1.00） | 照片同时含 Q8–Q10 |
| IMG_8158 | 地理 Q6 | 地理 Q3–Q5 题组 | BGE + gemma | 是（覆盖率 1.00） | 照片同时含 Q3–Q7 |

> 表中 IMG_8131 与 IMG_8130 是不同模型各自的数学错题；历史 Q30/Q8 与地理 Q6 是两模型共同命中同一错误。

结论：

- **没有一条 Top1 不在照片中**；
- 模型不是“把照片外的题认成 Exact”，而是“照片里有多道题，选了另一道”；
- 这属于**输入粒度/目标选择**问题，不是单纯的 embedding 误识别。

---

## 5. 为什么仍判 FAIL

任务书的 Exact 规则是“可以确认输入对应的 QCore 正式题目”。本次输入是多题页面，用户目标是其中一道；系统返回了另一道，仍然是错误 Exact。

不能因为“另一道也在照片里”就把它算作正确：

- 用户要的是目标题；
- 系统只返回一个 Exact，没有“多题候选/请选择”的交互；
- 因此严格目标判定必须记 False Exact。

同时，BGE 也有 4 个 False Exact，说明这不是 V1.1 独有缺陷；但也不能反过来证明 gemma 更好。gemma 的真实照片 Exact 反而低于 BGE。

---

## 6. 与渲染 Holdout 的差异

| 数据集 | BGE | gemma | False Exact |
|---|---:|---:|---:|
| 渲染 Holdout R2（45，单题裁剪） | 20/45 | 23/45 | 0 / 0 |
| 真实照片（45，多题页面） | 20/45 | 16/45 | 4 / 4 |

差异说明：

- 单题裁剪时，gemma 有 +3 Exact 优势；
- 真实多题页面时，gemma 的收益消失并转为 -4；
- 主要变量是**输入粒度和拍摄质量**，不是阈值（阈值全程未改）。

---

## 7. 必须修复的输入协议

在继续验证 V1.1 前，必须二选一：

1. **单题拍摄/裁剪**：一张照片只保留目标题（题干+材料+选项+小问），不要把相邻题拍进来；
2. **多题交互**：允许一张照片含多题，系统返回多个候选，由用户选择目标题；此时不能用“单一 Exact”作为决策。

本轮 45 张里至少 5 张含多题（IMG_8130/8131/8154/8156/8158）；这 5 张贡献了全部 4 个严格 False Exact（其中数学两张分别击中两个模型）。

---

## 8. 最终建议

1. **不切换生产默认模型。**
2. **V1.1 真实照片严格验证判 FAIL**；保留候选实现，不进入生产。
3. 请按“单题裁剪”重拍/裁剪至少以下题（或定义多题交互）：
   - 数学 Q14（IMG_8131）
   - 数学 Q12（IMG_8130）
   - 历史 Q30（IMG_8154）
   - 历史 Q8（IMG_8156）
   - 地理 Q6（IMG_8158）
4. 重新冻结一版真实照片后，用同一 `.74/.85/.55` 复验；不得调阈值后混报。
5. 若产品允许整页拍照，必须先做多题候选/用户选择，再谈 V1.1 切换。

---

## 9. 证据

| 内容 | 路径 |
|---|---|
| 45 张原图 | `Interactive Lesson/tests/pic/V11/` |
| OCR | `runs/qcore_semantic_expansion_01/v11/real_photos/real_photos_ocr.jsonl` |
| 冻结标签 | `runs/qcore_semantic_expansion_01/v11/real_photos/real_photos_manifest.json` |
| 匹配记录 | `runs/qcore_semantic_expansion_01/v11/real_photos/real_photo_matches.json` |
| 真实照片评测 | `runs/qcore_semantic_expansion_01/v11/real_photos/real_photos_eval.json` |
| 渲染 Holdout 报告 | `docs/quality/EULER-SEMANTIC-EMBEDDING-V1.1-ISOLATED-VALIDATION-01.md` |
