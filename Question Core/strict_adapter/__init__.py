"""Strict Adapter: deterministic Preprocessing Manifest → Question Core mapping.

QCORE-E2E-01 阶段 C。唯一职责：把本轮已封存的 Preprocessing 产物按 QCORE-01
已验收契约确定性地映射为 Candidate，再经契约校验、Admission、持久化、回读、
学生 API 验证完成 Question 交付。

禁止：重新 OCR / Reslice / 识别结构 / 猜测答案；导入 ARCHIVE V1–V3 旧管线。

版本记录：
* 0.1.0 — 阶段 C 初版映射。
* 0.1.1 — QCORE-E2E-01-C-CLOSURE：① Manifest 来源的 DISPUTED 证据改用
  Manifest JSON Pointer 定位（不再以 OCR md 行号冒充 Manifest 行号）；
  ② 答案区图片登记为审核专用 Asset（target_path=/answers）+ ASSET 证据
  （visibility=review_only）；③ 学生端资产清单收紧为可见内容块实际引用集。
* 0.1.2 — QCORE-DELIVERY-02-R1 阻断修复：① 同行多选项按印刷标记切分
  （B1，不再产出空选项块）；② subject 改由 MappingContext 试卷级显式
  传递并 fail-closed（B2，移除 SUBJECT_AUTHORITY 单卷硬编码）；
  ③ 英语选项块补齐真实行定位（B3，块级 line_start/line_end）。
* 0.2.0 — QCORE-ANSWER-FIDELITY-03 答案保真（G-01–G-12 + Owner D-1/D-2）：
  ① Manifest answers[] 逐条消费（sub_label/slot_id/form/source_region/
  evidence_lines/asset_ref/status），废除 '；' 切分降级；② composite 逐
  子问 CompositeSubAnswer + slot_bindings 归属（化学/语文推广英语形态）；
  ③ inline_in_explanation → declared（解析区答案恢复 TypedAnswer）；
  ④ 图片答案 AssetSlot + canonical asset_id（answer_image）；争议空位
  None + 全冲突版本 statements（不选边）；answer_conflicts[] → statements
  + EvidenceConflict(conflict_origin=source_internal，G-08 不阻断)；
  ⑤ P-1/P-3 纸卷作用域（owner_override_reason）+ disputed 归属保答案；
  ⑥ essay（Owner D-1）：范文只进 Explanation，0 TypedAnswer 不判缺答案。
"""

ADAPTER_VERSION = "strict-adapter/0.2.0"

__all__ = ["ADAPTER_VERSION"]
