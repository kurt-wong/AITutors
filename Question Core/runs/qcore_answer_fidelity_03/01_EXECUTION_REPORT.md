# 01_EXECUTION_REPORT.md — QCORE-ANSWER-FIDELITY-03 执行报告

> 任务：Adapter 答案保真实现与验证 ｜ 执行方：MIMO ｜ 独立复核：DSH
> 阶段：Phase 3（Contract + Adapter 答案保真）｜ 日期：2026-11-11
> 依据：Phase 1 契约设计（DSH PASS）+ Phase 2 三卷封存 Manifest（DSH PASS）
> + Owner D-1/D-2 裁决（本工单）+ DSH PHASE3_REVIEW_BASELINE 复核口径。
> 输入 = Phase 2 封存 Manifest（哈希核验在案）；未运行 OCR/LLM/Preprocessing；
> 未触碰 `qcore_delivery_02`、Admission/Publication/Student API、DeepTutor。
> **修订记录**：DSH 首轮复核 FAIL（B1/B2 阻断 + B3 随同）→ **R1 一次定向修订已闭环**
> （见 §11），修订范围严格限定 DSH §8 四项复审要点。

---

## 1. 结论

**三项交付（A 代码变更 / B 保真追踪矩阵 / C 本报告）已完成并经 R1 定向修订，待 DSH 复审。**

- 38 Units × 144 答案条目**逐条**映射验证，未映射 0 条（矩阵 `02_FIDELITY_MATRIX.json`，
  candidate_target **写盘前逐条解析**，136 条指针全部可解析）。
- 12 道抽检题全部达到 DSH Phase3 基线 §5 的期望形态（§3；DSH 首轮独立复核亦通过）。
- 49 图片资产注册 49（41/2/6 全保留）；2 图片答案槽关联 canonical asset_id。
- 作文（D-1）：8 条范文条目全部进 Explanation，0 TypedAnswer，不判缺答案。
- 源内冲突（D-2）：7 组全部两存/三存、可区分来源、不选边、0 阻断。
- 回归测试 **555 passed**（含 DSH 沙箱受阻项 `test_pydantic_is_single_source_of_truth`，本环境通过）。

**尚存真实阻断项：无**（R1 修订后）。非阻断观察见 §8。

---

## 2. 修改了哪些映射逻辑

### 2.1 Contract（`question_core/`，契约版本 1.0.0 → **1.1.0**，加性变更）

按 Phase 1 02 §4 变更清单实施（5 新模型 + 12 字段/类型增量 + 4 处规则修正）；
**EssayAnswer 不新增**（Owner D-1 覆盖 Phase 1 推荐，DSH 基线 §0.3）。

| 变更 | 内容 |
| --- | --- |
| 新模型 | `AnswerStatement`（statement_id/value_text/form/source_region/sub_label/slot_index/locators）、`SlotBinding`（slot_index/slot_id/sub_label/sub_body_local_id）、`AnswerAssetRef`（asset_id/role）、`AssetSlot`（assets≥1） |
| AnswerBase +5 字段 | `attribution`（attributed/partially_attributed/unattributed/disputed）、`answer_conflict`（none/source_conflict）、`missing_reason`、`statements`、`slot_bindings` |
| 槽位值联合 | `FillBlankAnswer.answer_value: tuple[str \| AssetSlot \| None]`（元组形态不变，旧数据全 str 零迁移）；`None` 仅限争议空位：须 `answer_conflict=source_conflict` 且该槽位 statements ≥2 条冲突版本（契约校验器强制） |
| CompositeSubAnswer | + `sub_body_local_id`；`answer_value` 可 `None`（缺答案小问如实落位；None 不得伪装 full，absent 须 missing_reason） |
| EvidenceRecord | + `value_form`（verbatim/compressed/combined/descriptive）、`source_region`（6 值；option_area 词表缺口维持 CONTRACT_EXPRESSION_GAP 记录不扩） |
| EvidenceConflict | + `conflict_origin`（source_internal/pipeline_disagreement，默认后者）；`EvidenceBundle.blocking_conflicts()`：**source_internal 不阻断**（G-08/Owner D-2），Revision F1 与 state.py 阻断判定同步分流 |
| Asset | `asset_role` + `answer_image`（查询便利） |
| G-07 | `StrictAnswerDeclaration._strict_boundary` 移除"not_attributable⇒强制 incomplete"（归属轴与完整性轴解耦）；`STRICT_BOUNDARY_RULES` 文本同步 |
| G-12 | F2 条件 2 改归属轴判定（not_attributable 不得配 attributed 答案）；条件 4 对 `composite_sub.answer_value=None` 显式分支；`_answer_matches_declared` 增 fill_blank 元素联合（str 归一比较 / AssetSlot 按 asset_id 集 / None 位按"声明值该位缺失或冲突版本"判定）与 composite 缺答案子问分支（声明段缺失才算一致） |
| D-1（F2） | essay 题 COMPLETE 豁免条件 3/4/5（范文在 Explanation，不因无 TypedAnswer 判缺） |
| 工件 | JSON Schema / golden ×3 / golden_digests / contract_manifest 随 1.1.0 重生成（schema_hash `b688da07…`，旧 `a09c051f…`；golden digests 前值记录于 `tests/persistence/test_serialize.py` 基线注释） |

### 2.2 Strict Adapter（`strict_adapter/`，0.1.2 → **0.2.0**）

| 修复 | 位置与内容 |
| --- | --- |
| A. 答案类型/来源映射（G-05） | `rules.KIND_TO_ATTRIBUTION["inline_in_explanation"]` = `not_attributable` → **`declared`**；`_build_answers` 重写为 answers[] 驱动。化学 Q3/语文 Q2 → 正式 SingleChoiceAnswer（证据 kind=inline_in_explanation，statements@explanation_area）。真正无法归属仅剩"declared 无 value/未知 kind fail-closed"两类，均带原因 |
| B. CompositeAnswer/小问归属（G-04/G-06） | 化学/语文 composite 全部走 CompositeAnswer：每 `sub_label` 一个 `CompositeSubAnswer`（`sub_body_local_id` 指向 QuestionBody，chem/chn 实测 50 小问全命中；英语分支 sub_label 与 body printed_number 一致对应、`sub_body_local_id` 暂未接线——非阻断观察 §8.1），inner 类型按题型+值形确定性判定（单选/多选/fill_blank 槽位联合）；`slot_bindings` 由 `answers[].slot_id/sub_label` 派生（slot_id 缺省按 `(n)#1`/`ans#k` 约定派生）。**废除 `value.split("；")` 降级**；旧格式 manifest（无 answers[]）整值保留 + combined 语句，不伪造槽位。英语分支同步补 statements/slot_bindings/attribution |
| C. 图片答案（G-02） | `answers[].asset_ref`（无扩展名 stem）→ 唯一命中 `image_assets` → canonical asset_id；槽位值 `AssetSlot(assets=[AnswerAssetRef(role="answer_value")])`；资产登记 `asset_role="answer_image"`。化学 Q12 (5)#1、(6)#2 落位，(6) 图文混合双槽 `["6", AssetSlot]`；题干/材料图引用不受影响 |
| D. 冲突与 None（G-01/G-09/G-11/D-2） | `answer_conflicts[]` 全量消费：每版本一条 `AnswerStatement`（verbatim + source_region + evidence_lines 定位）挂到对应槽位/子问/顶层答案，`answer_conflict=source_conflict` 标记；每版本一条 ACTIVE 证据 + `EvidenceConflict(conflict_origin="source_internal", is_critical=True)`——**不选边、不合并、不阻断**。争议空位 `None` 仅在合法冲突槽出现（2 条：chem Q9(6)#1、chn Q12(2)#2）。单元级冲突（chem Q1/Q5/Q9(1)）两版本同样保留可区分 |
| E. 信息保真 | `answers[]/answer_evidence/sub_label/slot_id/answer_conflicts/answer_completeness/source_region/evidence_lines/asset_ref/form/status/missing_reason/inline_in_explanation` 逐字段消费进 Candidate 对象/槽位/语句/证据；逐条追踪日志 `log.answers_trace`（144 行）为矩阵输入 |
| F. 作用域（G-05-F） | mapper 两处裸 `("Q10","Q12")` 判断改 `rules.owner_override_reason(paper_id/unit_id)`（纸卷作用域）；新增跨卷反例测试（语文 Q10/Q12 不命中化学 P-1/P-3）。`run_c_closure.py` 的 `("Q10","Q12")` 经查为**单卷运行目标清单**（`qid_by_unit` 只含本运行单卷条目），非跨卷策略判断，已加注释定性（不改行为） |
| G. Explanation/作文（D-1） | essay 单元（chn Q11、eng U10/U11）：0 TypedAnswer；范文条目全部保留在 Explanation 行区 + 证据（source_region=explanation_area）；完整性按"范文被解析行区覆盖"判 **complete**（三卷实测覆盖：chn Q11 1047–1091 ⊇ 1051–1077；U10 873–903；U11 925–948），不判缺答案/不完整，state_plan=approve_publish |
| P-1/P-3 | override 命中（仅化学 Q10/Q12）语义升级：**7+7 条答案全部保留**，`attribution="disputed"`（归属口径冻结）+ note=P-1/P-3 原因；DISPUTED manifest 值证据（C2 JSON Pointer）保留；transport 仍 `not_attributable`/declared_value=None（"不得声称 declared"维持），与答案层 disputed 归属满足 F2 归属轴一致性 |

### 2.3 完整性判定口径（G-07 解耦后）

- 非作文：`core.completeness = COMPLETE ⟺ 全部 TypedAnswer 为 FULL`（内容轴；transport `answer_completeness` 为唯一完整性权威 P-2 不变）。
- 作文：解析区范文覆盖全部条目行区 ⇒ COMPLETE（Owner D-1 规则 3）。
- `declaration.completeness` 同步取内容轴（不再由归属轴连坐）。

---

## 3. 12 道抽检题验证结果（工单 §5 + DSH 基线 §5）

| 样本 | 期望 | 实测（`test_phase3_answer_fidelity.py` 断言） |
| --- | --- | --- |
| 化学 Q3 | inline→SingleChoiceAnswer | **PASS**：`single_choice("A")`，evidence_kind=inline_in_explanation，statement@explanation_area L338，core=complete |
| 化学 Q8 | 6 小问/8 槽归属 | **PASS**：1 CompositeAnswer，6 subs（sub_body_local_id=q8-s1…s6），slot_bindings 1/2/2/1/1/1=8 槽 |
| 化学 Q10 | 7 条保留（P-1→disputed） | **PASS**：4 subs/7 槽全保留，全部 attribution=disputed，statements form=compressed/verbatim 如实标注，P-1 DISPUTED 证据在案，core=incomplete（transport unknown） |
| 化学 Q11 | 9 条逐小问映射 | **PASS**：4 subs/9 槽（(2) 双槽、(3)(4) 三槽） |
| 化学 Q12 | AssetSlot+canonical，图文同槽 | **PASS**：(5)#1=`AssetSlot(img_in_image_box_150_396_396_557)`；(6)=`["6", AssetSlot(img_in_image_box_534_397_602_549)]`；两资产 answer_image + 内容哈希一致；P-3 DISPUTED 在案 |
| 语文 Q2 | inline→SingleChoiceAnswer | **PASS**：`single_choice("A")`，statement@explanation_area L473 |
| 语文 Q8 | 逐小问不合并 | **PASS**：3 subs；(1)=SingleChoice("D")；(2)(3) 多点内容**整段保留**（'；' 不切分） |
| 语文 Q12 | 三版本冲突保真 | **PASS**：(2)#2=None 争议空 + 3 条 statements（张珙@stem L1105 / 张琪@answer L1143 / 张琪@explanation L1135），regions 三值可区分；EvidenceConflict 3 证据 source_internal；(1)(2)#1/#3 不受影响 |
| 英语 U3 | 4 条映射重复不丢 | **PASS**：4 subs；`suggests/suggested/has suggested`（form=combined）verbatim 保留 + where/who/meaningful |
| 英语 U4 | 20 条+2 组双版本 | **PASS**：20 subs（11–30）；14→"D"、15→"B"、30→"C"；冲突 statements：(wandered@stem)/(conversations@explanation)、(conversations@stem)/(greeted@explanation)；2 组 source_internal 不阻断 |
| 英语 U9 | 5 条+共享选项池 | **PASS**：46–50 = B/E/G/D/F；A–G 选项池挂父 body 完好 |
| 英语 U10 | 0 TypedAnswer，不判缺失 | **PASS**：answers=()，completeness=complete，approve_publish，范文 3 条 disposition=explanation_per_owner_d1，证据保留 explanation_area |

---

## 4. 38 Units / 144 答案条目全量结果

矩阵：`02_FIDELITY_MATRIX.json`（逐条：category/target/derived_from_manifest_fields）；汇总：`03_FIDELITY_MATRIX_SUMMARY.md`；生成器：`_scripts/build_fidelity_matrix.py`（可复算，哈希钉扎封存 Manifest）。

| 项 | 期望 | 实测 | 判定 |
| --- | --- | --- | --- |
| Units | 38（12/15/11） | 38（12/15/11） | PASS |
| 答案条目 | 144（47/41/56） | 144（47/41/56） | PASS |
| composite Units | 21（5/7/9） | 21（5/7/9） | PASS |
| composite 小问 | 97（26/21/50） | 97（26/21/50） | PASS |
| 图片资产 | 49（41/2/6） | manifest 49；Candidate 注册 49（41/2/6，零丢失） | PASS |
| 图片答案槽 | 2 | 2 | PASS |

逐条六类分布（合计 144）：

| 类别 | 条数 |
| --- | --- |
| 1 已映射至 Candidate 答案（独立单值题） | 12 |
| 2 已映射至 composite 小问/答案槽位 | 120 |
| 3 已映射为图片答案资产引用 | 2 |
| 4 已按 Owner D-1 作 Explanation 处理 | 8 |
| 5 已按合法冲突结构保留（争议空位） | 2 |
| 6 确实无法映射 | **0** |

综合题结构：21 个 composite Unit 各产生 **1 个 Question Candidate**（1 个顶层 CompositeAnswer；小问仅 CompositeSubAnswer，无独立 Question 身份——`test_composite_single_question_candidate` 断言）。冲突 7 组（chem Q1/Q5/Q9×2、chn Q12、eng U4×2）版本数 2/2/2/2/3/2/2，全部登记 source_internal。

---

## 5. 49 资产与 2 图片答案槽

- 三卷 `image_assets` 共 49（chem 41 / chn 2 / eng 6）；映射后 Candidate `content.assets` 注册 **49/49**（每卷逐一相等，无引用破坏）。
- 2 图片答案槽：chem Q12 (5)#1、(6)#2 → `AssetSlot` + `AnswerAssetRef(role="answer_value")`，canonical asset_id=stem，与 `Asset.content_hash` 一致（DSH 口径"同 stem 唯一命中 + 内容哈希一致"通过；`_register_answer_asset` 对 stem 非唯一命中 fail-closed）。
- 两图同时保有答案区证据登记（C1 review_only ASSET 记录不变）。

---

## 6. 作文（D-1）与源内冲突（D-2）实现结果

**D-1**：essay 3 单元（chn Q11、eng U10、U11）共 8 条条目 → 全部 Explanation 处置（类别 4）；
Contract 未新增 EssayAnswer/任何作文答案类型；`_answer_matches_declared`/F2 对 essay 豁免 TypedAnswer 要求；
三单元 core=complete、approve_publish，**未标记答案缺失/不完整**；范文原文/来源区域/证据定位保留。
（附注：旧格式 manifest 无逐条 answers[] 时 P-1/P-3 单元仍走"不产 TypedAnswer"legacy 路径——无逐条声明可保，不得从整串捏造；Phase 2 封存三卷的 7+7 条已全量保留。）

**D-2**：7 组冲突全部：多版本 statements（逐字 + source_region + 行区）+ 多条 ACTIVE 证据 + `EvidenceConflict(conflict_origin="source_internal")`；
`answer_conflict=source_conflict` 标记到位；争议空位 None 不选边；
**0 个 blocking conflict**（`blocking_conflicts()` 全卷为空；F1/state 阻断仅对 pipeline_disagreement 生效）；
导入/发布不受冲突单独阻断（admission 绑定测试通过），亦不等于自动批准（approve/publish 仍不由映射触发）。

---

## 7. 测试结果

命令：`python -m pytest tests -q --ignore=tests/persistence/integration`（system python 3.12.9）
**555 passed, 0 failed**（基线 497 passed；净增 58 = 新增 Phase 3 套件 44（含 R1 回归 13）+ F2 改写 +12 + B3 一致性 +1 + 改写净差）。分组：

| 组 | 数量 | 说明 |
| --- | --- | --- |
| strict_adapter 全部 | 242 | 含 12 题抽检套件、R1 回归（B1 指针解析/B2 evidence_kind 三层）、real-manifest（Phase 2 fixture）49、英语 R3 51、R4/R1/审计门禁等 |
| 契约层（tests/*.py） | 282 | Contract/Golden/Schema/F2/Candidate/状态机/边界表；含 `test_pydantic_is_single_source_of_truth`（DSH 沙箱受阻项，本环境 PASS）与 B3 工件一致性断言 `test_manifest_inventory_covers_schema_defs` |
| persistence 非 PG | 31 | 序列化往返（含新结构 AssetSlot/None/statements 往返测试） |
| persistence/integration | 未运行 | 需活体 PG；工单禁止触碰真实交付库，留待专用测试库环境执行 |

工单 §6.5 清单对应：Contract 测试 ✓／Strict Adapter 测试 ✓／R1 导入修复回归 ✓（test_extract B1、test_rules B2、test_english_option_locators B3、test_content_audit_rules）／英语 Composite R3/R4/R5 ✓（test_english_composite、test_composite_business_model、test_invariants R5 断言）／Candidate 完整性与答案绑定 ✓（test_candidate + F2 组）／内容保真反例 ✓（`TestFidelityCounterexamples`）＋ DSH R1 回归 ✓（`TestTraceTargetsResolvable`：136 条指针逐条可解析 + 单值/槽位形态断言；`TestEnglishEvidenceKindProvenance`：U1–U3 全层 inline_in_explanation、U4 全层 range_string、U5–U9 全层 answer_lines）。

**复跑与最终测试记录（CLOSEOUT 核定，须区分表述）**：

- MIMO 执行：**555 passed**（上表口径，`python -m pytest tests -q --ignore=tests/persistence/integration`，system python 3.12.9）。
- DSH 独立复跑：**554 passed + 1 环境性 error**——受阻项为 `test_pydantic_is_single_source_of_truth`，已通过等价 `write_artifacts` 验证确认等价通过。
- `tests/persistence/integration`（PG 集成）：**本轮未执行**（工单禁止触碰 `qcore_delivery_02`，留待 Phase 4 专用测试库环境），不得记为通过。
- 最终提交记录与对外说明以以上区分表述为准，**不得简化为"555 tests passed"**。

**旧断言有意识改写清单（DSH 基线 §7，非删除）**：
`test_mapper_real_manifest.py`（fixture 切 Phase 2 `a0135baf…` + TestOwnerRulings 全组按新口径重写）；
`test_strict_boundary.py`（inline 规范对 → declared；not_attributable+complete 构造改为解耦断言）；
`test_real_samples.py:159-165` 规范对同改；`test_rules.py` inline 两例重写；
`test_admission.py` Q3 用例改为"解析区答案恢复"正例（not_ready 用例改用 Q8/Q10）；
`test_invariants.py` F2 旧反例改写为归属轴三例；`test_english_composite.py` 语文哈希基线更新（答案载荷有意变化，主断言"不被英语分支劫持"不变）；`test_serialize.py` schema 哈希基线更新（沿用 R5 基线变更声明体例）。

---

## 8. 阻断项与非阻断观察

**真实阻断项：无。**

非阻断观察（不影响本轮交付，不转新治理任务；括注为 DSH 首轮 §6 的处置）：
1. R3/R4 英语/语文回归套件沿用其历史封存 fixture（`qcore_preimport_02`，MANIFEST_SHA 钉扎）作回归身份；**本轮验证矩阵与 12 题抽检只用 Phase 2 封存三卷**（哈希钉扎 + 复算断言）。
2. `strict_completeness_for` 帮助函数保留原映射（advisory）；G-07 已移除其强制耦合，Adapter 以内容轴判定完整性。（DSH §6.2：后续清理项，非本轮阻断——维持。）
3. DSH 非阻断项 3（"Phase 3 需在 meta 真实落 pipeline_sha256"）属 Preprocessing 生成链路（新 OCR/LLM 运行时生效），本轮无生成动作，不在范围。
4. CONTRACT_EXPRESSION_GAP（`option_area` 词表缺口）维持 Phase 2 记录，归 Contract 团队；OCR 层失真归 Preprocessing（均不在本轮范围）。
5. `tests/persistence/integration`（PG 集成）待专用测试库环境补跑。
6. 英语 composite 的 `sub_body_local_id=None`（DSH §6.1）：body 与 sub_label 已一致对应、不影响答案对应；**已收窄 §2.2 表述**，接线属后续增量（接线会变更答案载荷哈希，留待下轮以免扰动本轮复审基线）。
7. 作文 8 条 matrix `candidate_target` 为处置描述串（DSH §6.3）：已在矩阵汇总 §4 **注明列语义**（类别 4 不作指针校验，行内 evidence_lines 指向范文行区）。

---

## 9. 代码变更文件与提交信息

**Contract**（`Question Core/question_core/`）：
`contracts/v1/answer.py`（AnswerStatement/SlotBinding/AnswerAssetRef/AssetSlot、AnswerBase 5 字段、FillBlank 槽位联合+校验、CompositeSubAnswer 放宽+校验）、
`contracts/v1/evidence.py`（value_form/source_region/conflict_origin/blocking_conflicts）、
`contracts/v1/content.py`（asset_role+answer_image）、`contracts/v1/question.py`（F1 分流）、
`contracts/v1/state.py`（阻断分流）、`contracts/v1/candidate.py`（G-07/G-12/D-1 F2）、
`contracts/v1/common.py`（CONTRACT_VERSION=1.1.0）、`contracts/v1/__init__.py`（导出）、
`contracts/v1/manifest.py`（R1 B3：ALL_MODELS 补 4 模型）、
`schema/v1/question_core.schema.json` + `golden/v1/*`（1.1.0 重生成）。

**Adapter**（`Question Core/strict_adapter/`）：
`__init__.py`（0.2.0 变更记录）、`rules.py`（inline→declared、owner_override_reason）、
`mapper.py`（answers[] 全量消费、_annotate_conflicts、_build_evidence 重写、答案图/essay 助手、map_unit 重排；R1 B1：`_value_target_base` target 按 inner 类型生成）、
`english_composite.py`（answers[] 优先解码、逐子新字段、冲突标注、追踪日志；R1 B2：三层 evidence_kind 同源 Manifest kind）、
`run_c_closure.py`（作用域定性注释，零行为变更）。

**Tests**（`Question Core/tests/`）：
新增 `strict_adapter/test_phase3_answer_fidelity.py`（12 题抽检 + D-1/D-2 + 反例 + R1 B1/B2 回归）；
改写 `strict_adapter/test_mapper_real_manifest.py`、`test_rules.py`、`test_admission.py`、`test_english_composite.py`、
`test_strict_boundary.py`、`test_real_samples.py`、`test_invariants.py`、`persistence/test_serialize.py`；
`test_schema.py` 增 R1 B3 工件一致性断言。

**交付物**（`Question Core/runs/qcore_answer_fidelity_03/`）：
`02_FIDELITY_MATRIX.json`、`03_FIDELITY_MATRIX_SUMMARY.md`、`_scripts/build_fidelity_matrix.py`（含 target 解析校验）、本报告（含 §11 R1 闭环）。

**提交信息（QCORE-ANSWER-FIDELITY-03-CLOSEOUT 实际使用，Owner 指定 subject）**：

```
feat(qcore): implement answer fidelity contract and adapter

QCORE-ANSWER-FIDELITY-03 closeout. Contract 1.0.0 -> 1.1.0:
AnswerStatement/SlotBinding/AnswerAssetRef/AssetSlot (no EssayAnswer);
AnswerBase attribution/answer_conflict/missing_reason/statements/
slot_bindings; fill_blank slot union str|AssetSlot|None with disputed-None
legality; CompositeSubAnswer optional answer_value; EvidenceRecord
value_form/source_region; EvidenceConflict conflict_origin (source_internal
never blocks, Owner D-2); F2 attribution-axis + essay exemption (Owner
D-1); schema/golden regenerated (schema_hash b688da07..., contract models
45 -> 49). Strict Adapter 0.1.2 -> 0.2.0: consume manifest answers[]
item-by-item; composite CompositeAnswer with slot_bindings +
sub_body_local_id; inline_in_explanation -> declared (chem Q3 / chn Q2
restored); AssetSlot canonical image answers (chem Q12); answer_conflicts
-> version statements + source_internal conflicts (no side pick); P-1/P-3
paper-scoped with items kept under disputed attribution; essays ->
Explanation only, never flagged missing. Fidelity matrix: 38/38 units,
144/144 answer items, 0 unmapped.

Tests: MIMO run 555 passed (pytest tests -q
--ignore=tests/persistence/integration); DSH rerun 554 passed + 1
environment error (test_pydantic_is_single_source_of_truth, equivalent
write_artifacts verification). PostgreSQL integration tests NOT executed
(reserved for Phase 4 dedicated test DB; qcore_delivery_02 untouched).
Phase 2 sealed inputs unchanged (manifest SHA a0135baf.../f411de80.../
75ac87fb... re-verified at closeout). Non-blocking observations
registered as follow-up increments; no functional change in closeout.
```

---

## 10. 复核入口（DSH）

1. 矩阵与计数：`02_FIDELITY_MATRIX.json`（totals/expected/per_paper/rows）+ `_scripts/build_fidelity_matrix.py` 复算（**生成器已内置 target 逐条解析校验**）。
2. 12 题断言：`tests/strict_adapter/test_phase3_answer_fidelity.py`（含 D-1/D-2/反例/144 追踪完备 + R1 回归）。
3. 契约 diff：`contracts/v1/*`（1.0.0→1.1.0）+ schema_hash `a09c051f…→b688da07…` + `contract_manifest.models` 45→49。
4. 测试基线变更均有注释声明（test_serialize/test_english_composite/test_strict_boundary 等）。
5. 封存输入未改：三卷 Manifest 哈希 `a0135baf…/f411de80…/75ac87fb…`（生成器断言钉扎）。

---

## 11. R1 定向修订闭环（DSH 首轮复核 B1/B2/B3）

> 修订纪律：仅针对 DSH §3/§4/§5 阻断与随同项各修一次，不扩展范围；
> DSH §2 已独立通过的内容不重做。

### B1（高）candidate_target 18/136 不可解析 → 已闭环

- **根因**（`strict_adapter/mapper.py`）：target 一律追加槽位下标 `/{j}`，
  对 `single_choice`/`multi_choice`（值为标量/标签元组）越界或不精确。
- **修复**：新增 `_value_target_base(inner_type, base, j)`——仅 `fill_blank`/`multi_step`
  逐槽元组带 `/{j}`；`single_choice`/`multi_choice`/`numeric`/`expression`/`chemical`
  指向值字段本身。复合/独立/legacy 三条路径统一接入。
  - chem Q1–Q7、chn Q1–Q4 → `/answers/0/answer_value`（无 `/0`）；
  - chn Q5(1)(2)/Q8(1)/Q9(1)(2)/Q10(1)(2) 等单选子问 → `…/answer_value/answer_value`（无 `/0`）；
  - chn Q13（MultiChoice "AD"）→ `/answers/0/answer_value`（指向值字段，不再指首标签）。
- **防复发**：生成器 `build_fidelity_matrix.py` 写盘前对全部指针行逐条解析
  （基座 = CandidateCore，与 DSH PHASE3_VERIFY6 同口径），失败即入 problems 报错；
  回归断言 `TestTraceTargetsResolvable`（136 条全解析 + 单值/槽位形态 + 值内容抽查）。
- **矩阵**：`02_FIDELITY_MATRIX.json` / `03_…SUMMARY.md` 已重生成，`problems=[]`。

### B2（中）英语 U1–U4 逐答案 evidence_kind 硬编码 answer_lines → 已闭环

- **根因**（`strict_adapter/english_composite.py::build_composite_answer`）：
  inner（FillBlank/SingleChoice）与 CompositeSubAnswer 硬编码 `ANSWER_LINES`，仅顶层取 Manifest kind。
- **修复**：三层统一使用 `answer_evidence.type` 派生的同一 `evidence_kind`
  （`absent` → answer_lines 兜底不变）。
  - U1/U2/U3 全层 `inline_in_explanation`；U4 全层 `range_string`；U5–U9 全层 `answer_lines`（未改坏）。
- **回归**：`TestEnglishEvidenceKindProvenance`（3+1+5 例，逐层断言）。

### B3（低）contract_manifest models 清单缺 4 模型 → 已闭环

- **根因**：`question_core/contracts/v1/manifest.py` `ALL_MODELS` 手工清单未随 1.1.0 更新（45）。
- **修复**：补 `AnswerStatement/SlotBinding/AnswerAssetRef/AssetSlot`（49）；
  `write_artifacts` 重生成 `contract_manifest.json`（schema_hash 不变 `b688da07…`，$defs 本已含 4 模型）。
- **工件一致性断言**：`test_manifest_inventory_covers_schema_defs`——schema `$defs`
  全部对象型契约模型必须在 ALL_MODELS（反向允许 3 根模型在 schema 顶层 properties）。

### DSH §8 复审四要点对照

| 要点 | 状态 |
| --- | --- |
| 18 条 target 全部可解析 + matrix 可复算（重生成、无 problems） | ✅ 136 条指针全解析（18 修复 + Q13 精确化），生成器校验内置，problems=[] |
| U1–U4 全层 evidence_kind 一致，U5–U9 不回归 | ✅ 回归断言 9 例全绿 |
| contract_manifest.models 含 4 新模型，schema/manifest 再生成全等 | ✅ 49 模型；write_artifacts 重生成；一致性断言在案 |
| 全量测试复跑；封存 Manifest/OCR/DB 哈希与计数不变 | ✅ 555 passed；三卷 Manifest 哈希钉扎断言通过（OCR/DB 未触碰） |

---

## 12. CLOSEOUT：非阻断观察处置登记与提交前核验（QCORE-ANSWER-FIDELITY-03-CLOSEOUT）

> 依据 Owner 收口指令：本轮仅做非阻断观察处置登记、提交前核验、Git 固化。
> **不再进行功能开发，不重开 Phase 1/2/3 审查，不扩大技术范围。**

### 12.1 非阻断观察处置登记（正式收口，不得转为新一轮修复/审查任务）

| # | 非阻断观察 | 本轮处置 | 结论 |
| --- | --- | --- | --- |
| 1 | 英语 50 个 composite 小问 `sub_body_local_id=None` | 登记为后续增量，本轮不修改（body 与 sub_label 对应正确、答案映射无误；接线会变更答案载荷哈希，避免扰动复审基线） | 关闭（后续增量） |
| 2 | `strict_completeness_for` 保留旧 advisory 映射 | 强制耦合已解除（G-07），不影响当前行为；保留，不做无关清理 | 关闭（保留现状） |
| 3 | 作文 8 条 matrix `candidate_target` 为处置描述 | 按 D-1 属 Explanation 处置描述，非 JSON Pointer；保留现有列语义说明（矩阵汇总 §4） | 关闭 |
| 4 | 旧格式 Manifest fixture content_hash 更新 | 有意行为变化（答案载荷结构升级）；保留测试内变更声明注释；Phase 4 产生新 Revision | 关闭（保留变更说明） |
| 5 | `option_area` 词表缺口（CONTRACT_EXPRESSION_GAP） | 维持 Phase 2 既有记录，归 Contract 团队；不扩大本轮范围 | 关闭（留原记录） |
| 6 | PostgreSQL integration tests 未运行 | **明确登记为未验证**；不得写成通过；列为 Phase 4 正式导入前独立验证事项 | 关闭（未验证登记） |
| 7 | Preprocessing `pipeline_sha256` 未落入 meta | 本轮未运行 Preprocessing 生成链路；不要求补做/重新生成（新 OCR/LLM 运行时生效） | 关闭（范围外） |

### 12.2 提交前核验结果

| 核验项 | 结果 |
| --- | --- |
| Git 仓库 / 分支 / HEAD | `D:/Project/AITutors`（含 Question Core 子目录），分支 `main`，HEAD `672a99e`（`fix(question-core): finalize r1 strict import validation`） |
| 远端状态 | `git fetch origin` 后 `main...origin/main` 无 ahead/behind，远端无未预期新提交 |
| 预期变更纳入 | Contract 9 文件 + schema + golden 5 文件、Adapter 5 文件、Tests 10 文件（含新增 `test_phase3_answer_fidelity.py`）、交付物 4 文件（矩阵/汇总/生成器/本报告） |
| 交付物提交范围 | `runs/` 被 `.gitignore:86` 忽略，4 个交付文件按 Owner 指令 `git add -f` 精确纳入 |
| 禁止内容排除 | `_dsh/`、根 `AGENTS.md`（非 Phase 3 范围）、原始 PDF/OCR MD/Manifest 源数据/图片（位于 Preprocessing 子模块，未纳入）、无密钥/.env/运行数据库文件 |
| 子模块指针 | `DeepTutor`/`Preprocessing` 均呈既有脏状态（锁文件、pytest 缓存、历史遗留与 untracked `runs/`），**指针变更不纳入本次提交**，本轮未触碰 |
| Phase 2 封存 Manifest 未修改 | 三卷 manifest SHA 精确复核一致：`a0135baf8729e2a035381e7085acc17b39e3d3c5e009f15e9d6fa50f85e122f4` / `f411de80b7eaf94225d191222e4de093bf891af3045e479f9bfe8113167257d4` / `75ac87fbb40a637ac4e6ad9a9e286e4a78c1f6b65f6e5a3cc877d3b543df1d0e`；OCR MD SHA 亦一致（`dee902ef1654…` / `0f130df0da29…` / `c2a31c8cadb2…`） |
| `qcore_delivery_02` 未写入 | 本轮零 DB 操作；DSH 复核计数不变（38 units，answers 54，evidence 164，conflicts 0，assets 98，materials 42，revision content_hash digest `114d7938…`）；PG 集成套件未运行 |
| 范围外意外变更 | 无（工作区差异均属 Phase 3 Contract/Adapter/Tests/Schema/Golden 既定清单） |

### 12.3 测试结果最终记录（区分表述，禁止简化）

- MIMO：**555 passed**。
- DSH：**554 passed + 1 环境性 error**（`test_pydantic_is_single_source_of_truth`，等价 `write_artifacts` 验证通过）。
- PostgreSQL integration tests：**未执行**。

### 12.4 收口声明

本轮完成后正式关闭 QCORE-ANSWER-FIDELITY-03。**不自动启动 Phase 4**、不重导三卷、不修改真实交付数据库、不启动 DeepTutor 阶段 B；Phase 4（隔离数据库重新导入与数据修复）须等待 Owner 单独授权。
