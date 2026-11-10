"""Content Audit 正式入口测试（QCORE-DELIVERY-02-R1-CLOSEOUT）。

三组断言：
1. R1 已验证的 10 个审计正反例（8 阻断 + 2 通过）——规则语义回归；
2. 正式唯一入口 enforce_content_audit 的 fail-closed 门禁；
3. 正式导入路径（admit）强制经过该门禁——历史审计入口不得绕过正式规则。

使用真实封存 Manifest（2020 全国Ⅰ卷化学教师版，12 units）只读驱动；
测试不修改任何封存产物。
"""
from __future__ import annotations

import dataclasses
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from strict_adapter.admission import admit  # noqa: E402
from strict_adapter.content_audit import (  # noqa: E402
    ContentAuditError,
    audit_unit,
    enforce_content_audit,
)
from strict_adapter.extract import load_source_lines  # noqa: E402
from strict_adapter.mapper import MappingContext, map_all  # noqa: E402

RUN_ROOT = Path(r"D:\Project\AITutors\runs\qcore_e2e_01\qcore-e2e-01-20261108-104211")
OCR_DIR = RUN_ROOT / "02_PREPROCESSING" / "artifacts" / "ocr" / "高考真题" / "化学"
RESLICE_DIR = RUN_ROOT / "02_PREPROCESSING" / "artifacts" / "reslice"
SRC_MD = OCR_DIR / "2020全国I卷高考真题化学（教师版）(1).md"
MANIFEST = RESLICE_DIR / "2020全国I卷高考真题化学（教师版）(1).manifest.json"
ANNOTATED = RESLICE_DIR / "2020全国I卷高考真题化学（教师版）(1).annotated.md"

needs_sealed_input = pytest.mark.skipif(
    not MANIFEST.is_file(), reason="sealed Phase-B manifest not found"
)


# ---------------------------------------------------------------------------
# 第 1 组：R1 十个正反例（8 阻断 + 2 通过）——与 audit_rules_test.py 同源
# ---------------------------------------------------------------------------

SRC = ["A. 甲 B. 乙 C. 丙 D. 丁", "【答案】A", "【解析】略"]


def base_rec(**kw):
    rec = {
        "unit_id": "T1",
        "source_lines": SRC,
        "source_line_count": len(SRC),
        "manifest_option_lines": [(1, 1)],
        "options": [
            {"label": lb,
             "blocks": [{"kind": "text", "text": t, "line_start": 1,
                         "line_end": 1}],
             "line_start": 1, "line_end": 1}
            for lb, t in (("A", "甲"), ("B", "乙"), ("C", "丙"), ("D", "丁"))
        ],
        "stem_blocks": [],
        "material_blocks": [],
        "explanation_blocks": [
            {"kind": "text", "text": "【解析】略", "line_start": 3,
             "line_end": 3},
        ],
        "options_shape": "option_items",
    }
    rec.update(kw)
    return rec


class TestR1Counterexamples:
    """R1 §7.3 十个正反例：前 8 类错误必须阻断，后 2 类正常必须通过。"""

    def test_1_empty_option_textblock_blocked(self):
        rec = base_rec()
        rec["options"][1]["blocks"][0]["text"] = ""
        out = audit_unit(rec)
        assert out["status"] == "FAIL"
        assert any(p.startswith("A:") for p in out["problems"])

    def test_2_same_line_four_options_unmapped_blocked(self):
        rec = base_rec()
        for o in rec["options"]:
            o["blocks"][0]["text"] = ""
        out = audit_unit(rec)
        assert out["status"] == "FAIL"
        assert sum(p.startswith("A:") for p in out["problems"]) == 4

    def test_3_option_uncovered_lines_blocked(self):
        out = audit_unit(base_rec(option_uncovered_lines=[1]))
        assert out["status"] == "FAIL"
        assert any(p.startswith("B:") for p in out["problems"])

    def test_4_text_without_locator_blocked(self):
        rec = base_rec()
        rec["options"][0]["blocks"][0]["line_start"] = None
        rec["options"][0]["blocks"][0]["line_end"] = None
        out = audit_unit(rec)
        assert out["status"] == "FAIL"
        assert any("missing line locator" in p for p in out["problems"])

    def test_5_locator_out_of_range_blocked(self):
        rec = base_rec()
        rec["options"][0]["blocks"][0]["line_start"] = 99
        rec["options"][0]["blocks"][0]["line_end"] = 99
        out = audit_unit(rec)
        assert out["status"] == "FAIL"
        assert any("illegal line range" in p for p in out["problems"])

    def test_6_locator_text_mismatch_blocked(self):
        rec = base_rec()
        rec["options"][0]["blocks"][0]["text"] = "内容与源行不符"
        out = audit_unit(rec)
        assert out["status"] == "FAIL"
        assert any("traceable=false" in p for p in out["problems"])

    def test_7_traceable_null_blocked(self):
        rec = base_rec()
        rec["explanation_blocks"][0]["line_start"] = None
        rec["explanation_blocks"][0]["line_end"] = None
        out = audit_unit(rec)
        assert out["status"] == "FAIL"
        assert any("traceable=null" in p or "missing line locator" in p
                   for p in out["problems"])

    def test_8_traceable_false_blocked(self):
        rec = base_rec()
        rec["explanation_blocks"][0]["text"] = "杜撰解析"
        out = audit_unit(rec)
        assert out["status"] == "FAIL"
        assert any("traceable=false" in p for p in out["problems"])

    def test_9_normal_same_line_options_pass(self):
        out = audit_unit(base_rec())
        assert out["status"] == "ok", out["problems"]

    def test_10_u9_shared_pool_pass(self):
        pool_src = ["A. 甲", "B. 乙", "C. 丙", "D. 丁", "E. 戊", "F. 己", "G. 庚"]
        rec = {
            "unit_id": "U9",
            "source_lines": pool_src,
            "source_line_count": len(pool_src),
            "manifest_option_lines": [(1, 7)],
            "options": [
                {"label": lb,
                 "blocks": [{"kind": "text", "text": t, "line_start": i + 1,
                             "line_end": i + 1}],
                 "line_start": i + 1, "line_end": i + 1}
                for i, (lb, t) in enumerate(zip("ABCDEFG", "甲乙丙丁戊己庚"))
            ],
            "stem_blocks": [],
            "material_blocks": [],
            "explanation_blocks": [],
            "options_shape": "option_items",
        }
        out = audit_unit(rec)
        assert out["status"] == "ok", out["problems"]


# ---------------------------------------------------------------------------
# 第 2/3 组：正式唯一入口与导入路径门禁（真实封存输入）
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def ctx() -> MappingContext:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    lines = load_source_lines(str(SRC_MD))
    return MappingContext(
        lines=lines,
        manifest=manifest,
        manifest_path=str(MANIFEST),
        manifest_name=MANIFEST.name,
        source_md_path=str(SRC_MD),
        source_md_name=SRC_MD.name,
        source_pdf_name="2020全国I卷高考真题化学（教师版）(1).pdf",
        annotated_md_name=ANNOTATED.name,
        manifest_sha="585230ba63148b2e5714c31d0d6dd0b38c26cdb7b1456f65ba11296fc47f5d18",
        source_md_sha="dee902ef16540079ed8eef3fef5a44443ecd58b48c801b229513aebe9524c1ef",
        source_pdf_sha="e58e921daca6b049214e87d0c2284ca91cc04e62745348ec4b7037b0059ba2be",
        annotated_md_sha="0" * 64,
        manifest_bytes=MANIFEST.stat().st_size,
        source_md_bytes=SRC_MD.stat().st_size,
        source_pdf_bytes=1201552,
        annotated_md_bytes=ANNOTATED.stat().st_size,
        image_by_line={a["line_no"]: a for a in manifest.get("image_assets", [])},
        paper_id="2020全国I卷高考真题化学（教师版）(1)",
        subject="化学",
        run_id="qcore-closeout-02-audit-tests",
    )


@pytest.fixture(scope="module")
def mappings(ctx):
    return {m.unit_id: m for m in map_all(ctx)}


@needs_sealed_input
class TestFormalEntrypoint:
    """唯一正式入口 enforce_content_audit 的 fail-closed 语义。"""

    def test_enforce_passes_on_real_mapping(self, mappings, ctx):
        out = enforce_content_audit(mappings["Q1"], ctx)
        assert out["status"] == "ok", out["problems"]

    def test_enforce_passes_on_all_twelve_units(self, mappings, ctx):
        for unit_id, mapping in sorted(mappings.items()):
            out = enforce_content_audit(mapping, ctx)
            assert out["status"] == "ok", (unit_id, out["problems"])

    def test_enforce_raises_when_manifest_unit_missing(self, mappings, ctx):
        empty_ctx = dataclasses.replace(ctx, manifest={"units": []})
        with pytest.raises(ContentAuditError, match="manifest unit not found"):
            enforce_content_audit(mappings["Q1"], empty_ctx)

    def test_enforce_fail_closes_when_rules_fail(self, mappings, ctx,
                                                 monkeypatch):
        def fake_audit(rec):
            return {"status": "FAIL", "problems": ["A: forced"], "details": {}}

        monkeypatch.setattr(
            "strict_adapter.content_audit.audit_unit", fake_audit)
        with pytest.raises(ContentAuditError, match="content audit FAIL"):
            enforce_content_audit(mappings["Q1"], ctx)

    def test_rules_function_is_the_one_used_by_gate(self, mappings, ctx,
                                                    monkeypatch):
        """门禁调用的就是 audit_unit 本体——规则与入口不可分离。"""
        seen: list[dict] = []

        def spy_audit(rec):
            seen.append(rec)
            return audit_unit(rec)

        monkeypatch.setattr(
            "strict_adapter.content_audit.audit_unit", spy_audit)
        out = enforce_content_audit(mappings["Q1"], ctx)
        assert out["status"] == "ok"
        assert seen and seen[0]["unit_id"] == "Q1"


@needs_sealed_input
class TestFormalPathGate:
    """正式导入路径（admit）强制经过审计门禁——无旁路。"""

    def test_admit_log_contains_content_audit_result(self, mappings, ctx):
        res = admit(mappings["Q1"], ctx, ordinal=1)
        assert res.validated and res.admitted
        assert res.log["content_audit"]["status"] == "ok"

    def test_admit_fail_closes_when_gate_raises(self, mappings, ctx,
                                                monkeypatch):
        """审计失败必须阻断准入：历史审计器的假阳性放行不得绕过本门禁。"""

        def boom(mapping, ctx_):
            raise ContentAuditError("Q1: content audit FAIL: [forced]")

        monkeypatch.setattr(
            "strict_adapter.admission.enforce_content_audit", boom)
        with pytest.raises(ContentAuditError, match="content audit FAIL"):
            admit(mappings["Q1"], ctx, ordinal=1)

    def test_admit_fail_closes_when_rules_fail(self, mappings, ctx,
                                               monkeypatch):
        """规则层 FAIL → 门禁抛错 → admit 不产出任何可入库实体。"""

        def fake_audit(rec):
            return {"status": "FAIL", "problems": ["B: forced"], "details": {}}

        monkeypatch.setattr(
            "strict_adapter.content_audit.audit_unit", fake_audit)
        with pytest.raises(ContentAuditError, match="content audit FAIL"):
            admit(mappings["Q1"], ctx, ordinal=1)
