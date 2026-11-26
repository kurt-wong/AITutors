# AITUTORS-QCORE-KG-EXTERNAL-DATA-AUDIT-01

- 日期：2026-11-26
- 性质：外部数据源调查与许可证审计
- 结论：**只作结构参考，不合并进规范资产**
- 未下载/未导入任何外部数据到 AITutors 知识资产

---

## 1. K12-KGraph

| 项 | 内容 |
|---|---|
| 项目 | `haolpku/K12-KGraph` |
| 数据集许可证 | **CC BY-NC-SA 4.0** |
| 代码许可证 | MIT（`LICENSE-CODE`） |
| 数据规模（公开资料） | 10,685 节点 / 23,278 关系 / 23,640 评测题 / 2,267 训练样本 |
| 学科 | 数学、物理、化学、生物 |
| 关系 | `is_a`、`prerequisites_for`、`tests_concept`、`is_part_of` 等 |

已核实：数据集的 `LICENSE` 明确为 CC BY-NC-SA 4.0，并说明数据集源自人教版教材，NonCommercial 用于避免商业再利用冲突；代码单独 MIT。

### 对 AITutors 的可用性

- 可用于**隔离研究、结构比较、分类设计参考**；
- 不能把其数据并入商业产品/正式知识资产；
- 不能因为代码 MIT 就认为数据集可商用；
- 本轮**未导入** K12-KGraph 数据。

---

## 2. China Skill Taxonomy

| 项 | 内容 |
|---|---|
| 项目 | `goralcao/china-skill-taxonomy` |
| 公开资料规模 | 1,268 微主题 / 1,629 先修依赖 / 12 学科 |
| 覆盖 | 数学、语文、英语、物理、化学、生物、历史、地理、道德与法治、思想政治、科学、技术 |
| 许可证 | **本轮未独立核实** |
| 与现有图谱关系 | 当前 4,829 中有 18 个 `goralcao_supplement` 节点；不能等同于完整项目 |

### 结论

- 可作为跨学科分类/课标对齐的**待审参考**；
- 未核实许可证前，不导入、不合并、不作为正式分类依据；
- 需单独完成许可证、字段、来源、版本审计。

---

## 3. CnK12Taxonomy

| 项 | 内容 |
|---|---|
| 项目 | `LiXizhi/CnK12Taxonomy` |
| 许可证（公开说明） | 数据库 ODbL 1.0；原创内容 CC BY-SA 4.0 |
| 覆盖 | 义务教育阶段为主，不应视为完整高中体系 |
| 用途 | 研究中层分类、课标/知识点关系 |

### 结论

- ODbL 对衍生数据库有 share-alike 要求，不能随意并入闭源/商业知识资产；
- 未取得完整许可证审查前，不导入；
- 本轮**未使用**其数据。

---

## 4. 33,765 节点数据集

公开资料声称：

- 33,765 知识点；
- 21,536 关系；
- 347 教材；
- 17 学科。

但来源、完整性、许可证和社区验证不足；本轮**仅列入候选，不作为基础数据源**。

---

## 5. 审计结论

| 数据源 | 结论 |
|---|---|
| K12-KGraph | 仅隔离研究/结构参考；数据集 NC，不能商用合并 |
| China Skill Taxonomy | 许可证未核实；待审计，不导入 |
| CnK12Taxonomy | ODbL/CC BY-SA；不导入 |
| 33,765 数据集 | 来源/许可未核实；暂缓 |
| 现有 4,829 | 本轮唯一实际使用的节点底图 |

因此：

```text
PrimaryCategoryIndex 仅由现有 629 个课程节点构建
4,182 mmlong 仅用现有教材路径对齐
未合并任何外部数据
```

这也是本轮“可撤销、可追溯、无许可证污染”的边界。

---

## 6. 参考

- [K12-KGraph repository](https://github.com/haolpku/K12-KGraph)
- [K12-KGraph dataset](https://huggingface.co/datasets/lhpku20010120/K12-KGraph)
- [K12-KGraph LICENSE](https://raw.githubusercontent.com/haolpku/K12-KGraph/main/LICENSE)
- [China Skill Taxonomy](https://github.com/goralcao/china-skill-taxonomy)
- [CnK12Taxonomy](https://github.com/LiXizhi/CnK12Taxonomy)
