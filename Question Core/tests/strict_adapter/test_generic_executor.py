# -*- coding: utf-8 -*-
"""Tests for the formal generic execution entry (strict_adapter.generic_executor).

Layer 1-2 of the plan in GENERIC_EXECUTION_ENTRY_DESIGN.md §7:
input contract, DB target guard, context building, dry-run orchestration
(single/multi paper, failure isolation), static properties (no V3, no hardcodes).
Persistence/idempotency with real PostgreSQL lives in
tests/persistence/integration/test_generic_executor_pg.py.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_QCORE_ROOT = Path(__file__).resolve().parents[2]
if str(_QCORE_ROOT) not in sys.path:
    sys.path.insert(0, str(_QCORE_ROOT))

from strict_adapter.generic_executor import (  # noqa: E402
    DatabaseTargetError,
    DEFAULT_FORBIDDEN_DBS,
    InputContractError,
    PaperInput,
    build_context,
    load_paper_descriptors,
    run_papers,
    validate_target_db_name,
)
from strict_adapter import ADAPTER_VERSION  # noqa: E402

# ---- sealed artifact locations (same convention as test_admission.py) ----
E2E = _QCORE_ROOT.parent / "runs" / "qcore_e2e_01" / "qcore-e2e-01-20261108-104211"
CHEM_MD = E2E / "02_PREPROCESSING" / "artifacts" / "ocr" / "高考真题" / "化学" / "2020全国I卷高考真题化学（教师版）(1).md"
CHEM_MANIFEST = E2E / "02_PREPROCESSING" / "artifacts" / "reslice" / "2020全国I卷高考真题化学（教师版）(1).manifest.json"
CHEM_ANN = E2E / "02_PREPROCESSING" / "artifacts" / "reslice" / "2020全国I卷高考真题化学（教师版）(1).annotated.md"
CHEM_PDF = (
    _QCORE_ROOT.parent / "Preprocessing" / "maintainess" / "PDF" / "2020全国I卷高考真题化学（教师版）(1).pdf"
)
R1_WS = _QCORE_ROOT.parent / "Question Core" / "runs" / "qcore_s2q_repair_01_r1" / "workspace"
# chn sealed inputs (T117 manifest + R1 md)
CHN_MANIFEST = (
    _QCORE_ROOT.parent
    / "Question Core"
    / "runs"
    / "qcore_student_fidelity_image_repair_01"
    / "inputs"
    / "chinese"
    / "2019江苏高考真题语文（教师版）(1).manifest.json"
)
CHN_MD = R1_WS / "chinese" / "ocr_output" / "高三" / "语文" / "2019江苏高考真题语文（教师版）(1).md"
CHN_PDF = (
    _QCORE_ROOT.parent / "Preprocessing" / "maintainess" / "PDF" / "2019江苏高考真题语文（教师版）(1).pdf"
)

SEALED_CHEM = pytest.mark.skipif(
    not (CHEM_MANIFEST.is_file() and CHEM_MD.is_file() and CHEM_PDF.is_file()),
    reason="sealed chem artifacts not found",
)
SEALED_CHN = pytest.mark.skipif(
    not (CHN_MANIFEST.is_file() and CHN_MD.is_file() and CHN_PDF.is_file()),
    reason="sealed chn artifacts not found",
)


def _desc(tmp_path: Path, name: str, **over) -> Path:
    d = {
        "paper_id": "试卷X（教师版）(1)",
        "subject": "化学",
        "manifest_path": "m.manifest.json",
        "source_md_path": "s.md",
        "source_pdf_path": "p.pdf",
    }
    d.update(over)
    p = tmp_path / name
    p.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    return p


def _touch_inputs(tmp_path: Path) -> None:
    (tmp_path / "m.manifest.json").write_text(
        json.dumps({"units": [], "image_assets": []}), encoding="utf-8"
    )
    (tmp_path / "s.md").write_text("L1\n", encoding="utf-8")
    (tmp_path / "p.pdf").write_bytes(b"%PDF-1.4")


class TestInputContract:
    def test_missing_required_field_fails_closed(self, tmp_path):
        _touch_inputs(tmp_path)
        p = _desc(tmp_path, "d.json", subject="")
        with pytest.raises(InputContractError, match="missing required fields"):
            load_paper_descriptors(p)

    def test_blank_subject_fails_closed(self, tmp_path):
        _touch_inputs(tmp_path)
        p = _desc(tmp_path, "d.json", subject="   ")
        with pytest.raises(InputContractError):
            load_paper_descriptors(p)

    def test_missing_file_fails_closed(self, tmp_path):
        _touch_inputs(tmp_path)
        p = _desc(tmp_path, "d.json", source_md_path="nope.md")
        with pytest.raises(InputContractError, match="source_md_path not found"):
            load_paper_descriptors(p)

    def test_relative_paths_resolve_against_descriptor_dir(self, tmp_path):
        _touch_inputs(tmp_path)
        p = _desc(tmp_path, "d.json")
        papers = load_paper_descriptors(p)
        assert papers[0].manifest_path == (tmp_path / "m.manifest.json").resolve()
        assert papers[0].subject == "化学"

    def test_duplicate_paper_id_rejected(self, tmp_path):
        _touch_inputs(tmp_path)
        p = tmp_path / "papers.json"
        d = {
            "paper_id": "X",
            "subject": "化学",
            "manifest_path": "m.manifest.json",
            "source_md_path": "s.md",
            "source_pdf_path": "p.pdf",
        }
        p.write_text(json.dumps([d, d]), encoding="utf-8")
        with pytest.raises(InputContractError, match="duplicate paper_id"):
            load_paper_descriptors(p)

    def test_single_object_accepted_as_one_paper(self, tmp_path):
        _touch_inputs(tmp_path)
        p = _desc(tmp_path, "d.json")
        assert len(load_paper_descriptors(p)) == 1


class TestDbTargetGuard:
    def test_shared_and_online_dbs_rejected(self):
        for name in ("aitutors", "aitutors_test", "qcore_student_integration_01"):
            assert validate_target_db_name(name)["pass"] is False

    def test_historical_verification_prefixes_rejected(self):
        for name in ("qcore_delivery_02", "qcore_e2e_01_phase_c", "qcore_dev_test",
                     "qcore_missing_slot_01_import"):
            assert validate_target_db_name(name)["pass"] is False

    def test_bad_pattern_rejected(self):
        for name in ("", "1abc", "MiXeD", "has-dash", "a" * 80):
            assert validate_target_db_name(name)["pass"] is False

    def test_fresh_target_accepted(self):
        assert validate_target_db_name("qcore_batch_pv01_r1")["pass"] is True

    def test_extra_forbidden_extends(self):
        assert validate_target_db_name(
            "qcore_batch_pv01_r1", forbidden=DEFAULT_FORBIDDEN_DBS | {"qcore_batch_pv01_r1"}
        )["pass"] is False

    def test_run_papers_rejects_forbidden_db_before_any_work(self, tmp_path):
        _touch_inputs(tmp_path)
        papers = load_paper_descriptors(_desc(tmp_path, "d.json"))
        with pytest.raises(DatabaseTargetError, match="rejected"):
            run_papers(papers, "qcore_student_integration_01", tmp_path / "out", "t1", dry_run=True)


class TestBuildContext:
    @SEALED_CHEM
    def test_chem_context_carries_authoritative_identity(self):
        p = PaperInput(
            paper_id="2020全国I卷高考真题化学（教师版）(1)",
            subject="化学",
            manifest_path=CHEM_MANIFEST,
            source_md_path=CHEM_MD,
            source_pdf_path=CHEM_PDF,
            annotated_md_path=CHEM_ANN if CHEM_ANN.is_file() else None,
        )
        ctx, meta = build_context(p, "test-run")
        assert ctx.paper_id == p.paper_id
        assert ctx.subject == "化学"
        assert ctx.run_id == "test-run"
        assert len(ctx.manifest["units"]) > 0
        assert len(ctx.lines) > 0
        assert meta["annotated_md_resolution"] in (
            "explicit",
            "derived_same_stem",
            "fallback_manifest_itself",
        )

    @SEALED_CHEM
    def test_manifest_without_units_rejected(self, tmp_path):
        bad = tmp_path / "bad.manifest.json"
        bad.write_text(json.dumps({"image_assets": []}), encoding="utf-8")
        p = PaperInput(
            paper_id="X", subject="化学", manifest_path=bad,
            source_md_path=CHEM_MD, source_pdf_path=CHEM_PDF, annotated_md_path=None,
        )
        with pytest.raises(InputContractError, match="units"):
            build_context(p, "t")


class TestDryRunOrchestration:
    @SEALED_CHEM
    def test_single_paper_dry_run(self, tmp_path):
        papers = [
            PaperInput(
                paper_id="2020全国I卷高考真题化学（教师版）(1)",
                subject="化学",
                manifest_path=CHEM_MANIFEST,
                source_md_path=CHEM_MD,
                source_pdf_path=CHEM_PDF,
                annotated_md_path=None,
            )
        ]
        s = run_papers(papers, "qcore_ge01_dryrun", tmp_path / "out", "t-dry", dry_run=True)
        assert s["adapter_version"] == ADAPTER_VERSION
        assert s["totals"]["papers"] == 1
        assert s["totals"]["map_failed"] == 0
        assert s["totals"]["admitted"] > 0
        assert s["totals"]["persist_committed"] == 0  # dry-run never persists
        # per-unit ordinals are deterministic 1..N within the paper
        units = s["papers"][0]["units"]
        assert [u["ordinal"] for u in units] == list(range(1, len(units) + 1))
        assert (tmp_path / "out" / "run_summary.json").is_file()

    @SEALED_CHEM
    @SEALED_CHN
    def test_multi_paper_isolation_no_cross_talk(self, tmp_path):
        papers = [
            PaperInput(
                paper_id="2020全国I卷高考真题化学（教师版）(1)", subject="化学",
                manifest_path=CHEM_MANIFEST, source_md_path=CHEM_MD,
                source_pdf_path=CHEM_PDF, annotated_md_path=None,
            ),
            PaperInput(
                paper_id="2019江苏高考真题语文（教师版）(1)", subject="语文",
                manifest_path=CHN_MANIFEST, source_md_path=CHN_MD,
                source_pdf_path=CHN_PDF, annotated_md_path=None,
            ),
        ]
        s = run_papers(papers, "qcore_ge01_dryrun", tmp_path / "out", "t-multi", dry_run=True)
        assert s["totals"]["papers"] == 2
        chem = next(p for p in s["papers"] if p["paper_id"].startswith("2020"))
        chn = next(p for p in s["papers"] if p["paper_id"].startswith("2019"))
        assert chem["subject"] == "化学" and chn["subject"] == "语文"
        # both mapped successfully and independently
        assert chem["mapped_count"] > 0 and chn["mapped_count"] > 0
        # unit-id namespaces stay within their own paper (no shared counters)
        assert all(u.get("unit_id") for u in chem["units"])
        assert all(u.get("unit_id") for u in chn["units"])

    @SEALED_CHEM
    def test_bad_paper_does_not_block_other_papers(self, tmp_path):
        bad_md = tmp_path / "bad.md"
        bad_md.write_text("x\n", encoding="utf-8")
        bad_manifest = tmp_path / "bad.manifest.json"
        bad_manifest.write_text("{not json", encoding="utf-8")
        papers = [
            PaperInput(
                paper_id="BAD", subject="化学", manifest_path=bad_manifest,
                source_md_path=bad_md, source_pdf_path=CHEM_PDF, annotated_md_path=None,
            ),
            PaperInput(
                paper_id="2020全国I卷高考真题化学（教师版）(1)", subject="化学",
                manifest_path=CHEM_MANIFEST, source_md_path=CHEM_MD,
                source_pdf_path=CHEM_PDF, annotated_md_path=None,
            ),
        ]
        s = run_papers(papers, "qcore_ge01_dryrun", tmp_path / "out", "t-iso", dry_run=True)
        bad = next(p for p in s["papers"] if p["paper_id"] == "BAD")
        good = next(p for p in s["papers"] if p["paper_id"].startswith("2020"))
        assert bad["status"] == "paper_input_failed" and bad["error"]
        assert good["mapped_count"] > 0  # unaffected

    @SEALED_CHEM
    def test_unit_map_failure_is_recorded_not_skipped_silently(self, tmp_path):
        # corrupt one unit so map_unit raises; others must still map
        manifest = json.loads(CHEM_MANIFEST.read_text(encoding="utf-8"))
        manifest["units"][0] = {**manifest["units"][0], "stem_lines": ["not-an-int"]}
        corrupted = tmp_path / "corrupted.manifest.json"
        corrupted.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
        papers = [
            PaperInput(
                paper_id="2020全国I卷高考真题化学（教师版）(1)", subject="化学",
                manifest_path=corrupted, source_md_path=CHEM_MD,
                source_pdf_path=CHEM_PDF, annotated_md_path=None,
            )
        ]
        s = run_papers(papers, "qcore_ge01_dryrun", tmp_path / "out", "t-mfail", dry_run=True)
        units = s["papers"][0]["units"]
        failed = [u for u in units if u["status"] == "map_failed"]
        mapped = [u for u in units if u["status"] != "map_failed"]
        assert failed and failed[0]["error"], "failure must be recorded with reason"
        assert mapped, "other units must still map (no silent batch skip)"


class TestStaticProperties:
    def _source(self) -> str:
        return (_QCORE_ROOT / "strict_adapter" / "generic_executor.py").read_text(encoding="utf-8")

    def test_no_v3_runtime_imports(self):
        src = self._source()
        for token in ("TaskExecutor", "runner_b2", "annotation_adapter",
                      "resolved_span_adapter", "_gb03_n2wt", "PreprocessingImportService"):
            assert token not in src, f"V3 token leaked into entry: {token}"

    def test_no_paper_subject_hardcodes(self):
        src = self._source()
        for token in ("2020全国", "2019江苏", "2019北京", "高考真题", "化学", "语文", "英语"):
            assert token not in src, f"paper/subject literal hardcoded: {token}"

    def test_no_temporary_runs_dependency(self):
        src = self._source()
        assert "runs/" not in src and "runs\\" not in src
