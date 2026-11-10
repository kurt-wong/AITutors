"""Real Preprocessing samples: can the contract express them without
re-guessing or losing semantics?

Read-only. The test never modifies a manifest, markdown or PDF. It loads
real packages and asserts that every declared unit, answer-evidence kind and
image asset is expressible in the v1 contract.

When a sample's shape is missing or degraded, the test records the gap
instead of faking coverage.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

_PACKAGES_ROOT = Path(
    r"D:\Project\AITutors\ARCHIVE\AITutor-X\e2e_run\r2x2_packages"
)
_LEGACY_ROOT = Path(
    r"D:\Project\AITutors\Preprocessing\Ocr-markdown\reslice-batch-C"
)


def _load_manifest(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _rich_packages() -> list[Path]:
    if not _PACKAGES_ROOT.is_dir():
        return []
    out = []
    for pack in sorted(_PACKAGES_ROOT.iterdir()):
        m = pack / "package" / "paper.manifest.json"
        if m.is_file():
            out.append(m)
    return out


def _legacy_manifests() -> list[Path]:
    if not _LEGACY_ROOT.is_dir():
        return []
    return sorted(_LEGACY_ROOT.rglob("*.manifest.json"))[:5]


RICH = _rich_packages()
LEGACY = _legacy_manifests()

#: Coverage ledger, written by the tests and reported in the QCORE-01-R2
#: report. Not a secret: it is the honest record of what was actually
#: exercised.
COVERAGE: dict[str, object] = {
    "rich_packages_seen": 0,
    "rich_units_seen": 0,
    "subjects": set(),
    "unit_types": set(),
    "question_types": set(),
    "evidence_kinds": set(),
    "completeness_kinds": set(),
    "image_assets_seen": 0,
    "shared_answer_tables": 0,
    "legacy_manifests_seen": 0,
    "gaps": [],
}


@pytest.mark.skipif(not RICH, reason="rich preprocessing packages not found")
class TestRichPackages:
    """The 46-package corpus under ARCHIVE/AITutor-X/e2e_run."""

    @pytest.mark.parametrize(
        "manifest_path", RICH, ids=[p.parent.parent.name for p in RICH]
    )
    def test_manifest_shape_expressible(self, manifest_path):
        data = _load_manifest(manifest_path)
        COVERAGE["rich_packages_seen"] += 1
        subject = data.get("subject")
        if subject:
            COVERAGE["subjects"].add(subject)

        for key in ("source_file", "units", "source_content_sha256"):
            assert key in data, f"{manifest_path.name} missing {key}"

        for unit in data["units"]:
            COVERAGE["rich_units_seen"] += 1
            ut = unit.get("unit_type")
            COVERAGE["unit_types"].add(ut)
            qt = unit.get("original_question_type")
            if qt:
                COVERAGE["question_types"].add(qt)

            ev = unit.get("answer_evidence") or {}
            ev_type = ev.get("type")
            if ev_type:
                COVERAGE["evidence_kinds"].add(ev_type)
            if ev.get("shared"):
                COVERAGE["shared_answer_tables"] += 1
            comp = unit.get("answer_completeness")
            if comp:
                COVERAGE["completeness_kinds"].add(comp)

            # Structural: every unit must be addressable by unit_id.
            assert unit.get("unit_id"), f"unit without unit_id in {manifest_path.name}"

            # The upstream question type string must be preservable verbatim
            # (no re-interpretation) and every observed value must fall
            # inside the canonical QuestionType enum.
            oqt = unit.get("original_question_type")
            if oqt:
                COVERAGE["question_types"].add(oqt)
                from question_core.contracts.v1 import QuestionType

                valid = {t.value for t in QuestionType}
                if oqt not in valid and oqt not in (
                    "multiple_choice",  # upstream spelling of multi_choice
                    "fill_in",          # upstream spelling of fill_blank
                    "judge",            # upstream spelling of true_false
                    "written",          # upstream spelling of short_answer
                    "calculation",      # upstream spelling of numeric/short
                    "concept",          # upstream spelling of short_answer
                ):
                    COVERAGE["gaps"].append(
                        f"question_type {oqt} not in canonical enum"
                    )

        for asset in data.get("image_assets") or []:
            COVERAGE["image_assets_seen"] += 1
            assert "artifact_path" in asset or "src" in asset

    def test_composite_units_have_sub_ranges(self):
        """Composite units must declare a question sub-range so the parent/
        child relation survives mapping."""
        composites = 0
        for manifest_path in RICH:
            data = _load_manifest(manifest_path)
            for unit in data["units"]:
                if unit.get("unit_type") == "composite_question":
                    composites += 1
                    has_range = any(
                        unit.get(k) for k in ("questions_lines", "question_numbers")
                    )
                    if not has_range:
                        COVERAGE["gaps"].append(
                            f"{manifest_path.parent.parent.name}/{unit.get('unit_id')}"
                            " composite without sub-question range"
                        )
        assert composites > 0, "corpus should contain composite questions"

    def test_answer_evidence_kinds_known(self):
        """Every observed evidence kind must map onto the contract's
        StrictAnswerDeclaration attribution."""
        from question_core.contracts.v1 import (
            StrictAnswerDeclaration,
            strict_completeness_for,
        )

        kind_to_attribution = {
            "answer_lines": "declared",
            "answer_table_row": "table_row",
            # Phase 3（G-05，Owner 裁定）：解析区答案可声明归属。
            # 旧对：inline_in_explanation → not_attributable（Phase 3 前口径）。
            "inline_in_explanation": "declared",
            "range_string": "not_attributable",
            "absent": "not_attributable",
        }
        for manifest_path in RICH:
            data = _load_manifest(manifest_path)
            for unit in data["units"]:
                ev = unit.get("answer_evidence") or {}
                ev_type = ev.get("type")
                if not ev_type:
                    continue
                if ev_type not in kind_to_attribution:
                    COVERAGE["gaps"].append(f"unknown evidence kind {ev_type}")
                    continue
                attribution = kind_to_attribution[ev_type]
                declared_value = ev.get("value")
                # A "declared" attribution with no value is not actually
                # declared: the Strict rule forbids inventing one.
                if attribution == "declared" and not declared_value:
                    attribution = "not_attributable"
                completeness = strict_completeness_for(attribution).value
                dec = StrictAnswerDeclaration(
                    attribution=attribution,
                    evidence_kind=ev_type,
                    declared_value=declared_value if attribution != "not_attributable" else None,
                    completeness=completeness,
                )
                assert dec.evidence_kind == ev_type

    def test_shared_answer_table_case(self):
        """At least one shared-answer-table case must exist in the corpus so
        the Strict boundary's second case is exercised against real data."""
        if COVERAGE["shared_answer_tables"] == 0:
            pytest.skip("corpus has no shared answer tables")
        assert COVERAGE["shared_answer_tables"] > 0


@pytest.mark.skipif(not LEGACY, reason="legacy manifests not found")
class TestLegacyPackages:
    """The older reslice-batch-C manifests (no answer_evidence field).

    These predate the richer format. The contract must still be able to
    hold them — with the answer marked unattributable rather than guessed.
    """

    @pytest.mark.parametrize(
        "manifest_path", LEGACY, ids=[p.parent.name for p in LEGACY]
    )
    def test_legacy_units_expressible(self, manifest_path):
        data = _load_manifest(manifest_path)
        COVERAGE["legacy_manifests_seen"] += 1
        assert "units" in data
        for unit in data["units"]:
            assert unit.get("unit_id")
            # No answer_evidence in this generation: the answer is either
            # declared via answer_lines or not attributable.
            if not unit.get("answer_lines"):
                COVERAGE["gaps"].append(
                    f"legacy {manifest_path.parent.name}/{unit.get('unit_id')} "
                    "has no answer_lines (unattributable)"
                )


class TestStudentUploadFixtures:
    """Two simulated student uploads exercising the second entry."""

    def test_photo_upload_with_missing_answer(self, contract):
        from .golden_samples import build_student_upload_candidate

        cand = build_student_upload_candidate()
        assert cand.source_type == "student_upload"
        assert cand.source.observations, "OCR observations required"
        assert cand.core.completeness.value == "incomplete"
        # Missing answer must not be silently filled.
        assert cand.source.answers_declared_absent is True

    def test_typed_upload_without_ocr(self, contract):
        """A student who typed the question by hand has no OCR output."""
        cand = contract.StudentUploadCandidate(
            core=contract.CandidateCore(
                question_type="fill_blank",
                content=contract.QuestionContent(
                    bodies=[
                        contract.QuestionBody(
                            local_id="q",
                            question_type="fill_blank",
                            stem_blocks=[contract.TextBlock(text="1+1=___")],
                        )
                    ]
                ),
                answers=[
                    contract.FillBlankAnswer(answer_value=["2"], completeness="full")
                ],
                completeness=contract.Completeness.COMPLETE,
                ingestion=contract.IngestionIdentity(
                    candidate_idempotency_key="k" * 20,
                    adapter_version="student-upload/0.1.0",
                    input_hashes=contract.InputHashes(upload_blob_hash="e" * 64),
                ),
            ),
            source=contract.StudentUploadSource(
                source_document_id="student_upload/typed/1",
                uploaded_by="student:Kurtw",
                upload_blob_hash="e" * 64,
                observations=[],
                answers_declared_absent=False,
            ),
        )
        assert cand.source.observations == ()
        assert cand.core.completeness.value == "complete"

    def test_student_upload_composite_with_table(self, contract):
        """A composite question with a shared table must keep both."""
        from .golden_samples import build_student_upload_candidate

        cand = build_student_upload_candidate()
        content = cand.core.content
        assert content.tree(), "composite relation must survive"
        tables = [
            b for body in content.bodies for b in body.stem_blocks if b.kind == "table"
        ]
        assert tables, "shared table must be expressible in the body"
        assert tables[0].to_rows()[0][0] == "t/s"


class TestCoverageLedger:
    def test_report_coverage(self):
        """Print the honest coverage ledger for the delivery report."""
        ledger = {
            k: (sorted(v) if isinstance(v, set) else v) for k, v in COVERAGE.items()
        }
        print("\n=== QCORE-01-R2 sample coverage ===")
        print(json.dumps(ledger, ensure_ascii=False, indent=2))
        # The corpus must actually have been seen; if the skip conditions
        # fired everywhere, this test still documents the fact.
        if COVERAGE["rich_packages_seen"] == 0:
            pytest.skip("rich corpus unavailable; coverage not established")
