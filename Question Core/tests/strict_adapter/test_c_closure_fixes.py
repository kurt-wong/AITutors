"""C-CLOSURE 定点修复回归：C2 Manifest JSON Pointer 定位 + C1 答案区图 + 学生端资产过滤。

只测受影响行为；不落库、不触碰封存产物。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from question_core.contracts.v1 import (  # noqa: E402
    Asset,
    Completeness,
    EvidenceRole,
    EvidenceStatus,
    ImageBlock,
    PublicationState,
    QuestionAggregate,
    QuestionBody,
    QuestionContent,
    QuestionIdentity,
    QuestionInstance,
    Revision,
    SingleChoiceAnswer,
    SourceKind,
    StateSnapshot,
    TextBlock,
    Visibility,
    approve_revision,
    canonical_content_hash,
    publish_revision,
)
from strict_adapter.extract import load_source_lines  # noqa: E402
from strict_adapter.mapper import MappingContext, map_all  # noqa: E402
from strict_adapter.student_api import build_student_detail  # noqa: E402

RUN_ROOT = Path(r"D:\Project\AITutors\runs\qcore_e2e_01\qcore-e2e-01-20261108-104211")
OCR_DIR = RUN_ROOT / "02_PREPROCESSING" / "artifacts" / "ocr" / "高考真题" / "化学"
RESLICE_DIR = RUN_ROOT / "02_PREPROCESSING" / "artifacts" / "reslice"
SRC_MD = OCR_DIR / "2020全国I卷高考真题化学（教师版）(1).md"
MANIFEST = RESLICE_DIR / "2020全国I卷高考真题化学（教师版）(1).manifest.json"
ANNOTATED = RESLICE_DIR / "2020全国I卷高考真题化学（教师版）(1).annotated.md"

pytestmark = pytest.mark.skipif(
    not MANIFEST.is_file(), reason="sealed Phase-B manifest not found"
)


@pytest.fixture(scope="module")
def mappings():
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    ctx = MappingContext(
        lines=load_source_lines(str(SRC_MD)),
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
        run_id="qcore-e2e-01-20261108-104211",
    )
    return {m.unit_id: m for m in map_all(ctx)}


class TestC2ManifestJsonPointer:
    @pytest.mark.parametrize("unit_id,idx", [("Q10", 9), ("Q12", 11)])
    def test_disputed_locator_is_manifest_json_pointer(
        self, mappings, unit_id, idx
    ):
        recs = [
            r
            for r in mappings[unit_id].candidate.core.evidence.records
            if r.evidence_status == EvidenceStatus.DISPUTED
        ]
        assert len(recs) == 1, unit_id
        rec = recs[0]
        assert rec.source.source_kind == SourceKind.PREPROCESSING_MANIFEST
        assert len(rec.locators) == 1
        loc = rec.locators[0]
        assert loc.kind == "json_pointer"
        assert loc.pointer == f"/units/{idx}/answer_evidence/value"
        assert loc.line_start is None and loc.line_end is None
        # raw_value 保持 Manifest declared_value 原样（不得改写为源文原文）
        assert rec.raw_value and "；" in rec.raw_value
        assert "C-CLOSURE C2" in rec.note

    @pytest.mark.parametrize("unit_id", ["Q10", "Q12"])
    def test_disputed_still_not_attributable(self, mappings, unit_id):
        m = mappings[unit_id]
        assert m.candidate.source.answer_declaration.attribution == "not_attributable"
        assert m.candidate.core.completeness == Completeness.INCOMPLETE
        assert m.candidate.core.answers == ()


class TestC1AnswerImages:
    def test_q12_answer_images_registered_as_review_assets(self, mappings):
        m = mappings["Q12"]
        by_id = {a.asset_id: a for a in m.candidate.core.content.assets}
        for asset_id, sha in (
            ("img_in_image_box_150_396_396_557",
             "46b9a8063a8c0d9075ce2af7c0dfa94fc4f04c0255522d09804631742fada131"),
            ("img_in_image_box_534_397_602_549",
             "9e1caf829e03c511a072d01bbe32a0d0f9f31d2bf9c2240450149a6ede64137f"),
        ):
            a = by_id[asset_id]
            assert a.content_hash == sha
            assert a.storage_path.startswith("_imgs/")
            assert a.target_path == "/answers"
            assert "ANSWER-AREA" in a.note

    def test_q12_answer_image_evidence_review_only(self, mappings):
        recs = [
            r
            for r in mappings["Q12"].candidate.core.evidence.records
            if r.evidence_role == EvidenceRole.ASSET
        ]
        assert len(recs) == 2
        for r in recs:
            assert r.visibility == Visibility.REVIEW_ONLY
            assert r.target_path == "/answers"
            assert r.source.source_kind == SourceKind.SOURCE_MARKDOWN
            assert r.locators[0].kind == "line_range"
        lines = sorted(r.locators[0].line_start for r in recs)
        assert lines == [741, 749]

    def test_answer_images_never_in_visible_blocks(self, mappings):
        """两张答案图不得出现在任何学生可见内容块中。"""
        m = mappings["Q12"]
        for body in m.candidate.core.content.bodies:
            for b in body.stem_blocks:
                assert getattr(b, "kind", "") != "image" or b.asset_id not in (
                    "img_in_image_box_150_396_396_557",
                    "img_in_image_box_534_397_602_549",
                )
            for o in body.options:
                for b in o.blocks:
                    assert getattr(b, "kind", "") != "image" or b.asset_id not in (
                        "img_in_image_box_150_396_396_557",
                        "img_in_image_box_534_397_602_549",
                    )
        for mat in m.candidate.core.content.materials:
            for b in mat.blocks:
                assert getattr(b, "kind", "") != "image" or b.asset_id not in (
                    "img_in_image_box_150_396_396_557",
                    "img_in_image_box_534_397_602_549",
                )


class TestStudentAssetFilter:
    def _published_aggregate(self):
        from uuid import uuid4

        qid, rid = uuid4(), uuid4()
        content = QuestionContent(
            bodies=(
                QuestionBody(
                    local_id="q",
                    question_type="single_choice",
                    stem_blocks=(
                        TextBlock(text="题干"),
                        ImageBlock(asset_id="stem_pic"),
                    ),
                ),
            ),
            assets=(
                Asset(
                    asset_id="stem_pic",
                    storage_path="_imgs/stem_pic.jpg",
                    content_hash="a" * 64,
                    mime_type="image/jpeg",
                ),
                Asset(
                    asset_id="img_in_image_box_150_396_396_557",
                    storage_path="_imgs/img_in_image_box_150_396_396_557.jpg",
                    content_hash="46b9a8063a8c0d9075ce2af7c0dfa94fc4f04c0255522d09804631742fada131",
                    mime_type="image/jpeg",
                    target_path="/answers",
                ),
            ),
        )
        ans = SingleChoiceAnswer(
            answer_value="A",
            completeness="full",
            evidence_kind="answer_lines",
        )
        ch = canonical_content_hash(content, ans)
        snap = StateSnapshot(
            revision_id=rid,
            content_hash=ch,
            completeness=Completeness.COMPLETE,
            review="pending_review",
            publication="unpublished",
        )
        snap = approve_revision(snap, approved_by="t", content_hash=ch)
        snap = publish_revision(snap, acted_by="t", content_hash=ch)
        rev = Revision.create(
            question_id=qid,
            revision_id=rid,
            revision_number=1,
            question_type="single_choice",
            content=content,
            answers=(ans,),
            state=snap,
        )
        inst = QuestionInstance(
            question_id=qid, revision_id=rid, source_document_id="p", ordinal=1
        )
        return QuestionAggregate(
            identity=QuestionIdentity(question_id=qid),
            revisions=(rev,),
            instances=(inst,),
            state_history=(snap,),
        )

    def test_referenced_stem_asset_visible_answer_asset_hidden(self):
        detail = build_student_detail(self._published_aggregate(), submitted=True)
        asset_ids = [a["asset_id"] for a in detail["content"]["assets"]]
        assert asset_ids == ["stem_pic"]
        blob = json.dumps(detail, ensure_ascii=False)
        assert "img_in_image_box_150_396_396_557" not in blob
        assert "46b9a8063a8c" not in blob
