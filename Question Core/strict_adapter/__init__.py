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
"""

ADAPTER_VERSION = "strict-adapter/0.1.1"

__all__ = ["ADAPTER_VERSION"]
