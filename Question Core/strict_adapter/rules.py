"""Mapping policy for the Strict Adapter.

Every rule here is traceable to one of:

* QCORE-01 已验收契约（`question_core.contracts.v1`）及其参考测试：
  `tests/test_strict_boundary.py:148-156`、`tests/test_real_samples.py:159-165`
  的 `kind_to_attribution` 规范映射；
* Owner 阶段 B / 阶段 C 裁决（P-1 / P-2 / P-3、Q8–Q12 口径）；
* 阶段 B 审查报告 `02_PREPROCESSING/01_PREPROCESSING_AUDIT.md` §6。

本模块不做任何语义判断；唯一的作用是把已裁决口径表达成可校验的常量与纯函数。
"""

from __future__ import annotations

from . import ADAPTER_VERSION

# ---------------------------------------------------------------------------
# 契约规范映射：answer_evidence.type → StrictAnswerDeclaration.attribution
# 依据：tests/test_strict_boundary.py:148-156（参数化 (kind, attribution) 对）
#       tests/test_real_samples.py:159-165（kind_to_attribution 字典）
# ---------------------------------------------------------------------------

KIND_TO_ATTRIBUTION: dict[str, str] = {
    "answer_lines": "declared",
    "answer_table_row": "table_row",
    "inline_in_explanation": "not_attributable",
    "range_string": "not_attributable",
    "absent": "not_attributable",
}

# ---------------------------------------------------------------------------
# Owner 裁决覆盖（优先于默认映射）——阶段 B P-1 / P-3
# 审计报告 §6.1：Q10 答案标签重复/顺序错乱/压缩合并；Q12 value 含非源文的
# 图片语义描述。二者即使 answer_evidence.type=answer_lines 也不得声明 declared。
#
# QCORE-DELIVERY-01-C-R2 M1 最小修复：键从 unit_id 升为稳定的 source/document
# identity（source_document_id = paper_id/unit_id），明确限定**来源试卷身份 +
# Unit 身份**。原键仅 unit_id 会跨卷误伤（化学 P-1/P-3 裁决误命中语文同名
# Q10/Q12）。这两条覆盖**仅适用于 2020 全国Ⅰ 化学卷**的 Q10/Q12。
# ---------------------------------------------------------------------------

OWNER_ATTRIBUTION_OVERRIDES: dict[str, str] = {
    "2020全国I卷高考真题化学（教师版）(1)/Q10": "not_attributable",  # P-1 (chem only)
    "2020全国I卷高考真题化学（教师版）(1)/Q12": "not_attributable",  # P-3 (chem only)
}

OWNER_OVERRIDE_REASONS: dict[str, str] = {
    "2020全国I卷高考真题化学（教师版）(1)/Q10": (
        "P-1 (audit §6.1, 2020全国Ⅰ化学 Q10 only): answer label duplication/"
        "order scrambling, paragraph compression and semantic completion in "
        "manifest value; per-item source attribution not confirmable"
    ),
    "2020全国I卷高考真题化学（教师版）(1)/Q12": (
        "P-3 (audit §6.1, 2020全国Ⅰ化学 Q12 only): manifest value contains "
        "image semantic descriptions absent from source lines; must not pose "
        "as source answer evidence"
    ),
}

# ---------------------------------------------------------------------------
# 答案完整性：manifest.answer_completeness（transport 确定性字段）→
# AnswerCompleteness。P-2：Q8–Q12 = unknown 是唯一正式口径；
# answer_completeness_semantic 仅为 LLM 快照，不得覆盖（本模块不读取它）。
# ---------------------------------------------------------------------------

COMPLETENESS_MAP: dict[str, str] = {
    "full": "full",
    "partial": "partial",
    "unknown": "unknown",
    "absent": "absent",
}

#: 只允许降低、不允许提升的单调规则（"不得擅自提升"）。
COMPLETENESS_ORDER = {"absent": 0, "unknown": 1, "partial": 2, "full": 3}

# ---------------------------------------------------------------------------
# 原始题型 → 契约 QuestionType（三卷 manifest 声明的取值；未知取值 fail-closed）。
# 目标值全部是 contracts.v1.common.QuestionType 既有枚举，不新增语义：同名恒等；
# fill_in→fill_blank、multiple_choice→multi_choice 为同义命名转换（填空/多选）。
# QCORE-DELIVERY-01-C 最小修复：原表仅化学卷两型，语文/英语卷声明的 reading/…
# 会 fail-closed 阻断 26/38 units，故按契约既有枚举补齐确定性映射。
# ---------------------------------------------------------------------------

QUESTION_TYPE_MAP: dict[str, str] = {
    "single_choice": "single_choice",
    "short_answer": "short_answer",
    "multiple_choice": "multi_choice",
    "fill_in": "fill_blank",
    "reading": "reading",
    "reading_expression": "reading_expression",
    "essay": "essay",
    "cloze": "cloze",
    "grammar_fill": "grammar_fill",
    "seven_to_five": "seven_to_five",
}

# ---------------------------------------------------------------------------
# 学科（R1 B2 修复）：不得使用任何单卷硬编码常量。subject 由导入入口按
# 试卷级配置显式写入 MappingContext.subject，经 standalone 与 composite
# 两条映射路径传入 Candidate.source.subject；缺失即 fail-closed（mapper
# 抛错），禁止从文件名/内容/LLM 推断，禁止静默默认（原 SUBJECT_AUTHORITY
# 单卷硬编码已移除——三卷 manifest.subject=None (N-1) 时曾错误回退"化学"）。
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# 子问印刷标签切分（Composite 父子结构）
# 只按题面印刷标签（行首 （n） / (n)）做确定性分段；切点记录进执行日志。
# 不识别新结构、不猜题号——标签本身是源文内容。
# ---------------------------------------------------------------------------

SUB_LABEL_PATTERN = r"^[（(]\s*(\d+)\s*[）)]"

# ---------------------------------------------------------------------------
# 英语 composite 分支适用范围（QCORE-DELIVERY-01-C-R3 §1.2 显式限定）。
# 仅下列已封存英语卷的 composite Unit 走英语确定性展开分支。语文卷同样声明
# reading/composite_question（Q5/Q6/Q8/Q9/Q10），不得仅凭题型跨卷推断——
# DSH R3 复核阻断项一。范围外一律走既有（n）标签切分路径。
# ---------------------------------------------------------------------------

ENGLISH_COMPOSITE_SCOPE_PAPERS: frozenset[str] = frozenset(
    {
        "2019北京高考真题英语（教师版）(1)",
    }
)

# ---------------------------------------------------------------------------
# 纯函数
# ---------------------------------------------------------------------------


def resolve_attribution(unit: dict, source_document_id: str) -> tuple[str, str]:
    """返回 (attribution, 依据说明)。禁止任何猜测：无 value 的 declared 降级。

    ``source_document_id``（= paper_id/unit_id）限定覆盖规则的来源试卷身份 +
    Unit 身份，避免仅凭题号跨卷误命中（M1）。
    """
    unit_id = unit.get("unit_id", "")
    ev = unit.get("answer_evidence") or {}
    kind = ev.get("type") or "absent"
    value = ev.get("value")

    if source_document_id in OWNER_ATTRIBUTION_OVERRIDES:
        return "not_attributable", OWNER_OVERRIDE_REASONS[source_document_id]

    attribution = KIND_TO_ATTRIBUTION.get(kind)
    if attribution is None:
        # 契约未覆盖的证据类型 fail-closed：不得声明归属。
        return "not_attributable", f"unknown evidence kind {kind!r}: fail-closed"

    if attribution == "declared" and not value:
        # tests/test_real_samples.py:178-181：declared 无 value 不算 declared。
        return (
            "not_attributable",
            "evidence kind answer_lines but no declared value: "
            "Strict rule forbids inventing one",
        )
    if attribution == "table_row" and (not value or not ev.get("table_row_locator")):
        return (
            "not_attributable",
            "table_row without locator/value: not attributable",
        )
    return attribution, f"contract kind_to_attribution[{kind!r}]"


def answer_completeness(unit: dict) -> str:
    """transport 字段映射；不得使用 answer_completeness_semantic。"""
    raw = (unit.get("answer_completeness") or "unknown").lower()
    return COMPLETENESS_MAP.get(raw, "unknown")


def question_type(unit: dict) -> str:
    oqt = unit.get("original_question_type") or ""
    mapped = QUESTION_TYPE_MAP.get(oqt)
    if mapped is None:
        raise ValueError(
            f"original_question_type {oqt!r} not in QUESTION_TYPE_MAP: "
            "fail-closed, no catch-all degradation"
        )
    return mapped


__all__ = [
    "ADAPTER_VERSION",
    "COMPLETENESS_MAP",
    "COMPLETENESS_ORDER",
    "KIND_TO_ATTRIBUTION",
    "OWNER_ATTRIBUTION_OVERRIDES",
    "OWNER_OVERRIDE_REASONS",
    "QUESTION_TYPE_MAP",
    "SUB_LABEL_PATTERN",
    "answer_completeness",
    "question_type",
    "resolve_attribution",
]
