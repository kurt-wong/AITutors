# AITUTORS-QCORE-KG-HIERARCHY-COMPATIBILITY-01

- 日期：2026-11-26
- 性质：只读结构调查
- 数据：`six-subject-kg` unified 4,829 nodes + 4,584 relations
- 结论：**现有图谱不是完整父子树；Primary 上层分类需要最小兼容索引**

---

## 1. 节点结构

| 项 | 数量 |
|---|---:|
| 总节点 | 4,829 |
| `mytutors_curriculum` | 629 |
| `mmlong818` | 4,182 |
| `goralcao_supplement` | 18 |

字段差异：

- mytutors 节点有 `parent_code`、`level`、`structural_type`；
- mmlong 节点没有 `parent_id`、`parent_code`、`level`；
- goralcao 节点没有父子层级。

---

## 2. 课程层级

mytutors 629 节点：

| level | 数量 | 含义 |
|---|---:|---|
| 1 | 6 | 学科根 |
| 2 | 35 | 模块/册 |
| 3 | 136 | 章节 |
| 4 | 452 | 具体知识点 |

- `parent_code` 非空：623；
- 根节点（无 parent_code）：6；
- 层级关系可沿 `parent_code` 回溯到 level=3。

### 可作为 Primary 的层级

- level=2：35 个模块，最适合作为稳定上层；
- level=3：136 个章节，可作为次级上层；
- level=1：6 个学科，只适合显式 fallback。

---

## 3. 关系结构

关系总数 4,584：

| 类型 | 数量 |
|---|---:|
| prerequisite | 1,974 |
| leads-to | 912 |
| contains | 623 |
| sequence | 446 |
| related | 317 |
| aligned_to | 292 |
| shared_concept | 12 |
| application | 8 |

关键判断：

- 只有 `contains` 与 mytutors `parent_code` 可视为层级关系；
- `prerequisite` / `leads-to` 是学习顺序/先修关系，**不是父子包含**；
- `aligned_to` 可用于 mmlong 到课程节点的局部对齐，但不能覆盖全部。

---

## 4. mmlong 上层可解析性

方法：

1. 读取 `textbooks[].chapter_path`；
2. 按 `>` 拆分章节路径；
3. 去掉“第X章/第X节”前缀；
4. 与 mytutors level=3 名称精确匹配；
5. 匹配后回溯其 level=3 祖先。

结果：

| 来源 | 可解析到 level=3 | 不可解析 |
|---|---:|---:|
| mmlong818 | 2,271 | 1,911 |
| mytutors_curriculum | 588 | 41 |
| goralcao_supplement | 0 | 18 |
| 合计 | **2,859 / 4,829** | **1,970 / 4,829** |

注意：

- 这是**文本路径对齐**，不是修改图谱；
- 2,271 个 mmlong 节点有教材路径可对齐；
- 1,911 个 mmlong 节点没有足够的上层路径；
- 不能为了覆盖率强行给它们造父节点。

---

## 5. 已用 Primary 节点覆盖

对 166 题 × 三份运行的 975 个 primary 节点：

| 来源 | 数量 |
|---|---:|
| 教材路径对齐 level=3 | 698 |
| mytutors 祖先 level=3 | 31 |
| 无 level=3 | 246 |

结论：

- 729 / 975 = 74.8% 的 primary 节点可解析到 level=3；
- 246 / 975 = 25.2% 无 level=3；
- 因此 169 题不能全部用 level=3 作为 Primary；
- 59 / 166 题需要 fallback 到学科根。

---

## 6. 兼容性结论

### 可直接复用

- 629 个 mytutors 节点的 parent_code/level；
- 35 个 level=2 模块；
- 136 个 level=3 章节；
- 6 个 level=1 学科根；
- 教材 chapter_path 可对齐的 2,271 个 mmlong 节点。

### 不能直接复用

- 4,182 个 mmlong **没有显式父节点**；
- `leads-to` / `prerequisite` 不能当父子关系；
- 1,911 个 mmlong 没有可靠教材章节路径；
- 18 个 goralcao 无层级。

### 最小兼容方案

不修改图谱，派生：

```text
PrimaryCategoryIndex
  - level=1: 6
  - level=2: 35
  - level=3: 136
```

- Primary 只从该索引选；
- mmlong 通过教材路径对齐；
- 无对齐时 fallback 到学科根并显式标记；
- Secondary 仍从 4,829 细节点选；
- 不创建新节点，不重建图谱。

---

## 7. 对映射的实际影响

1. 现有 full-v1 的 Primary 多为 mmlong 细节点，不能直接当 V2 Primary；
2. 上层化只能覆盖约 75% 的已用 primary 节点；
3. 剩余 25% 若强制 fallback 到学科根，会损失“函数/数列”这类中层语义；
4. 因此 V2 全量映射前，必须先完成 PrimaryCategoryIndex 和 mmlong 对齐；
5. 这是映射前置条件，不是全图谱治理工程。

---

## 8. 证据

```text
_dsh/workpackage_c/hierarchy_compatibility.json
_dsh/workpackage_c/hierarchy_diagnosis_v2.json
```

未修改任何节点、关系或 QCore 数据。
