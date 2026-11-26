# AITUTORS-QCORE-KG-EXTERNAL-DATA-AUDIT-01

- 日期：2026-11-26
- 性质：外部数据源调查与许可证审计
- 结论：**非商业项目可用；保留署名/ShareAlike/ODbL 义务；本轮仍未导入**
- 本次审计后的许可证阻断已解除：AITutors 已明确为完全不商用
- 但“可用”不等于“已合并”；本轮仍只使用现有 4,829 节点
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

- AITutors 完全不商用，因此 CC BY-NC-SA 的 NonCommercial 条款不再构成阻断；
- 仍必须保留 attribution、许可证链接、修改说明；
- 若基于其数据形成衍生数据集，需按 ShareAlike 同样开放；
- 代码 MIT 与数据 CC BY-NC-SA 仍分别适用；
- 本轮**未导入** K12-KGraph 数据；可在后续隔离对齐任务中使用。

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

- 可作为跨学科分类/课标对齐的**外部参考**；
- 仍需核实许可证、字段、来源、版本，并保留 attribution；
- 未核实前不合并；非商业使用不改变署名/许可义务。

---

## 3. CnK12Taxonomy

| 项 | 内容 |
|---|---|
| 项目 | `LiXizhi/CnK12Taxonomy` |
| 许可证（公开说明） | 数据库 ODbL 1.0；原创内容 CC BY-SA 4.0 |
| 覆盖 | 义务教育阶段为主，不应视为完整高中体系 |
| 用途 | 研究中层分类、课标/知识点关系 |

### 结论

- ODbL 的 share-alike 义务仍然存在；非商业使用不豁免；
- 可用于非商业研究/对齐，但衍生数据库需按 ODbL 处理；
- 未取得完整许可证审查前不合并；
- 本轮**未使用**其数据。

---

## 4. 33,765 节点数据集

公开资料声称：

- 33,765 知识点；
- 21,536 关系；
- 347 教材；
- 17 学科。

但来源、完整性、许可证和社区验证不足；本轮**仅列入候选，不作为基础数据源**；非商业项目不消除来源审计要求。

---

## 5. 审计结论

| 数据源 | 结论 |
|---|---|
| K12-KGraph | 非商业可用；CC BY-NC-SA，保留 attribution/ShareAlike；本轮未导入 |
| China Skill Taxonomy | 非商业可用；许可证仍未核实完整条款，待审计，不导入 |
| CnK12Taxonomy | 非商业可用；ODbL/CC BY-SA 义务保留；不导入 |
| 33,765 数据集 | 来源/许可未核实；暂缓 |
| 现有 4,829 | 本轮唯一实际使用的节点底图 |

因此：

```text
PrimaryCategoryIndex 仅由现有 629 个课程节点构建
4,182 mmlong 仅用现有教材路径对齐
本轮未合并任何外部数据
```

非商业状态解除了 NC 阻断，但不改变“本轮未导入”的事实；后续任务可按 attribution/ShareAlike 使用。

---

## 6. 参考

- [K12-KGraph repository](https://github.com/haolpku/K12-KGraph)
- [K12-KGraph dataset](https://huggingface.co/datasets/lhpku20010120/K12-KGraph)
- [K12-KGraph LICENSE](https://raw.githubusercontent.com/haolpku/K12-KGraph/main/LICENSE)
- [China Skill Taxonomy](https://github.com/goralcao/china-skill-taxonomy)
- [CnK12Taxonomy](https://github.com/LiXizhi/CnK12Taxonomy)
