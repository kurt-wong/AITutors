"""D9 — source-anchored Question identity (Owner ruling 2026-11-23).

Covers the contract that made re-processing mint duplicate Questions:
identity must be a function of ``(paper_segment, section, question_numbers)``
and the original source hash, and never of manifest / OCR / adapter versions.
"""

from __future__ import annotations

import pytest

from question_core.contracts.v1 import (
    IdentityAnchor,
    IdentityAnchorError,
    build_section_id,
    derive_identity_key,
    normalize_section_label,
)
from question_core.persistence.identity_resolve import (
    AmbiguousIdentityError,
    InstanceSlot,
    resolve_identity,
)
from strict_adapter.mapper import MappingContext, identity_anchor_for, section_ids_for

PDF_SHA = "a" * 64


def make_ctx(units: list[dict], *, paper_id: str = "paper-1", segment: str = "") -> MappingContext:
    return MappingContext(
        lines=[],
        manifest={"units": units},
        manifest_path="m.json",
        manifest_name="m.json",
        source_md_path="s.md",
        source_md_name="s.md",
        source_pdf_name="p.pdf",
        annotated_md_name="a.md",
        manifest_sha="b" * 64,
        source_md_sha="c" * 64,
        source_pdf_sha=PDF_SHA,
        annotated_md_sha="d" * 64,
        manifest_bytes=1,
        source_md_bytes=1,
        source_pdf_bytes=1,
        annotated_md_bytes=1,
        paper_id=paper_id,
        paper_segment_id=segment,
    )


class TestIdentityKey:
    def test_key_scheme_and_stability(self):
        anchor = IdentityAnchor("paper-1", "sec#1", (1,), PDF_SHA)
        key = derive_identity_key(anchor)
        assert key.startswith("qk2_")
        # Deriving twice must be identical (pure function).
        assert key == derive_identity_key(IdentityAnchor("paper-1", "sec#1", (1,), PDF_SHA))

    def test_manifest_and_ocr_changes_cannot_change_the_key(self):
        """The D9 defect: manifest/md hashes used to be part of the key.

        The anchor has no field for them, so regenerating a manifest or an OCR
        markdown cannot mint a new identity. This is the behavioural contract
        the old ``qk1_`` key violated.
        """
        ctx_a = make_ctx([{"unit_id": "U1", "section": "", "question_numbers": [1]}])
        ctx_b = make_ctx([{"unit_id": "U1", "section": "", "question_numbers": [1]}])
        ctx_b.manifest_sha = "e" * 64
        ctx_b.source_md_sha = "f" * 64
        unit = {"unit_id": "U1", "section": "", "question_numbers": [1]}
        assert derive_identity_key(identity_anchor_for(unit, ctx_a)) == derive_identity_key(
            identity_anchor_for(unit, ctx_b)
        )

    def test_different_question_numbers_different_key(self):
        a = IdentityAnchor("paper-1", "sec#1", (1,), PDF_SHA)
        b = IdentityAnchor("paper-1", "sec#1", (2,), PDF_SHA)
        assert derive_identity_key(a) != derive_identity_key(b)

    def test_different_source_pdf_different_key(self):
        a = IdentityAnchor("paper-1", "sec#1", (1,), PDF_SHA)
        b = IdentityAnchor("paper-1", "sec#1", (1,), "b" * 64)
        assert derive_identity_key(a) != derive_identity_key(b)

    def test_different_paper_segment_different_key(self):
        a = IdentityAnchor("paper-1", "sec#1", (1,), PDF_SHA)
        b = IdentityAnchor("paper-1/听力A", "sec#1", (1,), PDF_SHA)
        assert derive_identity_key(a) != derive_identity_key(b)

    def test_missing_anchor_inputs_rejected(self):
        with pytest.raises(IdentityAnchorError):
            derive_identity_key(IdentityAnchor("", "sec#1", (1,), PDF_SHA))
        with pytest.raises(IdentityAnchorError):
            derive_identity_key(IdentityAnchor("paper-1", "sec#1", (), PDF_SHA))
        with pytest.raises(IdentityAnchorError):
            derive_identity_key(IdentityAnchor("paper-1", "sec#1", (1,), ""))


class TestSectionLabelStability:
    """The same paper's section text drifted across five manifests."""

    @pytest.mark.parametrize(
        "raw",
        [
            "【化学—选修3：物质结构与性质】",
            "[化学-选修5：有机化学基础]",
            "化学-选修5：有机化学基础",
        ],
    )
    def test_brackets_dashes_and_width_are_noise(self, raw):
        normalised = normalize_section_label(raw)
        assert "【" not in normalised and "[" not in normalised
        assert "—" not in normalised and "－" not in normalised

    def test_drifted_variants_converge(self):
        a = normalize_section_label("【化学—选修5：有机化学基础】")
        b = normalize_section_label("化学-选修5：有机化学基础")
        assert a == b

    def test_empty_label_stays_empty(self):
        assert normalize_section_label(None) == ""
        assert normalize_section_label("") == ""

    def test_section_id_carries_ordinal(self):
        assert build_section_id("一、选择题", 1) == "一、选择题#1"
        assert build_section_id("一、选择题", 2) == "一、选择题#2"


class TestSectionRuns:
    def test_same_label_contiguous_keeps_one_section(self):
        units = [
            {"unit_id": "U1", "section": ""},
            {"unit_id": "U2", "section": ""},
            {"unit_id": "U3", "section": "选修3"},
        ]
        ids = section_ids_for(units)
        assert ids["U1"] == ids["U2"] == "#1"
        assert ids["U3"] == "选修3#1"

    def test_inserting_a_question_inside_a_section_does_not_shift_following_ids(self):
        before = [
            {"unit_id": "U1", "section": "一、选择题"},
            {"unit_id": "U2", "section": "二、非选择题"},
        ]
        after = [
            {"unit_id": "U1", "section": "一、选择题"},
            {"unit_id": "U1b", "section": "一、选择题"},
            {"unit_id": "U2", "section": "二、非选择题"},
        ]
        assert section_ids_for(before)["U2"] == section_ids_for(after)["U2"]

    def test_repeated_non_contiguous_label_gets_its_own_ordinal(self):
        units = [
            {"unit_id": "U1", "section": "听力"},
            {"unit_id": "U2", "section": "阅读"},
            {"unit_id": "U3", "section": "听力"},
        ]
        ids = section_ids_for(units)
        assert ids["U1"] == "听力#1"
        assert ids["U3"] == "听力#2"


class TestAnchorFromUnit:
    def test_uses_question_numbers_not_printed_number(self):
        """English composite units carry a section-relative printed_number."""
        units = [
            {"unit_id": "U1", "section": "第一部分 听力", "printed_number": "1",
             "question_numbers": [1]},
            {"unit_id": "U2", "section": "第二部分 阅读", "printed_number": "1",
             "question_numbers": [21, 22, 23]},
        ]
        ctx = make_ctx(units)
        anchor = identity_anchor_for(units[1], ctx)
        assert anchor.question_numbers == (21, 22, 23)

    def test_missing_question_numbers_fail_closed(self):
        units = [{"unit_id": "U1", "section": "", "printed_number": "1"}]
        with pytest.raises(IdentityAnchorError):
            identity_anchor_for(units[0], make_ctx(units))

    def test_non_integer_question_numbers_fail_closed(self):
        units = [{"unit_id": "U1", "section": "", "question_numbers": ["12A"]}]
        with pytest.raises(IdentityAnchorError):
            identity_anchor_for(units[0], make_ctx(units))

    def test_segment_id_is_used_when_declared(self):
        units = [{"unit_id": "U1", "section": "", "question_numbers": [1]}]
        ctx = make_ctx(units, paper_id="tj-eng", segment="tj-eng/听力A")
        assert identity_anchor_for(units[0], ctx).paper_segment_id == "tj-eng/听力A"


class TestResolver:
    def _slot(
        self,
        qid: str,
        section: str,
        nums: tuple[int, ...],
        ordinal: int,
        segment: str = "paper-1",
    ):
        from uuid import uuid5, NAMESPACE_URL

        return InstanceSlot(
            question_id=uuid5(NAMESPACE_URL, qid),
            paper_segment_id=segment,
            section=section,
            question_numbers=nums,
            ordinal=ordinal,
        )

    def test_exact_match(self):
        q1 = self._slot("q1", "一、选择题", (1,), 1)
        q2 = self._slot("q2", "二、非选择题", (2,), 2)
        res = resolve_identity(
            [q1, q2],
            paper_segment_id="paper-1",
            section_id="一、选择题#1",
            question_numbers=(1,),
        )
        assert res.question_id == q1.question_id
        assert res.matched_by == "exact" and res.section_drift is False

    def test_section_drift_falls_back_only_when_unique(self):
        q1 = self._slot("q1", "第一部分 听力", (1,), 1)
        # incoming manifest labelled the same question differently
        res = resolve_identity(
            [q1],
            paper_segment_id="paper-1",
            section_id="听力#1",
            question_numbers=(1,),
        )
        assert res.question_id == q1.question_id
        assert res.matched_by == "question_numbers" and res.section_drift is True

    def test_ambiguous_section_drift_fails_closed(self):
        q1 = self._slot("q1", "第一部分", (1,), 1)
        q2 = self._slot("q2", "第二部分", (1,), 2)
        with pytest.raises(AmbiguousIdentityError):
            resolve_identity(
                [q1, q2],
                paper_segment_id="paper-1",
                section_id="第三部分#1",
                question_numbers=(1,),
            )

    def test_no_match_means_new_question(self):
        q1 = self._slot("q1", "", (1,), 1)
        res = resolve_identity(
            [q1], paper_segment_id="paper-1", section_id="#1", question_numbers=(9,)
        )
        assert res.question_id is None and res.matched_by == "none"

    def test_empty_slots_means_new_question(self):
        res = resolve_identity(
            [], paper_segment_id="paper-1", section_id="#1", question_numbers=(1,)
        )
        assert res.question_id is None

    def test_duplicate_printed_numbers_in_same_section_fail_closed(self):
        """D9: real duplicate numbering must not be silently resolved."""
        q1 = self._slot("q1", "会考", (1,), 1)
        q2 = self._slot("q2", "会考", (1,), 2)
        with pytest.raises(AmbiguousIdentityError):
            resolve_identity(
                [q1, q2],
                paper_segment_id="paper-1",
                section_id="会考#1",
                question_numbers=(1,),
            )

    # ---- C2: segment isolation -------------------------------------------

    def test_same_number_in_other_segment_is_never_matched(self):
        a1 = self._slot("a1", "第一部分", (1,), 1, segment="paper/segA")
        b1 = self._slot("b1", "第一部分", (1,), 1, segment="paper/segB")
        res = resolve_identity(
            [a1, b1],
            paper_segment_id="paper/segB",
            section_id="第一部分#1",
            question_numbers=(1,),
        )
        assert res.question_id == b1.question_id, "must resolve inside its own segment"

    def test_cross_segment_section_drift_cannot_reuse(self):
        """MIMO's counterexample: A has Q1, incoming is B with drifted section."""
        a1 = self._slot("a1", "第一部分", (1,), 1, segment="paper/segA")
        res = resolve_identity(
            [a1],
            paper_segment_id="paper/segB",
            section_id=" drifted-label#1",
            question_numbers=(1,),
        )
        assert res.question_id is None
        assert res.matched_by == "none"

    def test_missing_incoming_segment_fails_closed(self):
        a1 = self._slot("a1", "第一部分", (1,), 1, segment="paper/segA")
        with pytest.raises(IdentityAnchorError):
            resolve_identity(
                [a1], paper_segment_id="", section_id="第一部分#1", question_numbers=(1,)
            )

    def test_legacy_slot_is_single_segment_default(self):
        """A legacy row (segment read back as the paper id) matches only that default."""
        legacy = self._slot("legacy", "第一部分", (1,), 1, segment="paper-1")
        ok = resolve_identity(
            [legacy],
            paper_segment_id="paper-1",
            section_id="第一部分#1",
            question_numbers=(1,),
        )
        assert ok.question_id == legacy.question_id
        other = resolve_identity(
            [legacy],
            paper_segment_id="paper-1/听力A",
            section_id="第一部分#1",
            question_numbers=(1,),
        )
        assert other.question_id is None

class TestImportPathSegmentPlumbing:
    """C2: both formal import paths must carry paper_segment_id."""

    def test_paper_input_carries_optional_segment(self, tmp_path):
        from strict_adapter.generic_executor import PaperInput

        for name in ("m.json", "s.md", "p.pdf"):
            (tmp_path / name).write_text("{}", encoding="utf-8")
        paper = PaperInput.from_dict(
            {
                "paper_id": "tj-eng",
                "subject": "英语",
                "manifest_path": "m.json",
                "source_md_path": "s.md",
                "source_pdf_path": "p.pdf",
                "paper_segment_id": "tj-eng/听力A",
            },
            tmp_path,
        )
        assert paper.paper_segment_id == "tj-eng/听力A"

    def test_paper_input_without_segment_defaults_to_empty(self, tmp_path):
        from strict_adapter.generic_executor import PaperInput

        for name in ("m.json", "s.md", "p.pdf"):
            (tmp_path / name).write_text("{}", encoding="utf-8")
        paper = PaperInput.from_dict(
            {
                "paper_id": "tj-eng",
                "subject": "英语",
                "manifest_path": "m.json",
                "source_md_path": "s.md",
                "source_pdf_path": "p.pdf",
            },
            tmp_path,
        )
        assert paper.paper_segment_id == ""

class TestPublishedRevisionRead:
    """C1 read side: only the revision whose latest snapshot is published."""

    @staticmethod
    def _build():
        from uuid import uuid4

        from question_core.contracts.v1 import QuestionAggregate, QuestionIdentity
        from tests.persistence.synthetic import (
            make_published_revision,
            make_rich_revision,
        )

        qid = uuid4()
        rev1 = make_published_revision(qid, revision_number=1, revision_id=uuid4())
        rev2 = make_rich_revision(qid, revision_number=2, revision_id=uuid4())

        def aggregate(history):
            return QuestionAggregate(
                identity=QuestionIdentity(question_id=qid),
                revisions=(rev1, rev2),
                instances=(),
                state_history=tuple(history),
            )

        return aggregate, rev1, rev2

    def test_published_revision_returns_the_published_one(self):
        aggregate, rev1, _ = self._build()
        assert aggregate([rev1.state]).published_revision().revision_id == rev1.revision_id

    def test_superseded_revision_is_not_returned(self):
        from question_core.contracts.v1 import withdraw_publication

        aggregate, rev1, _ = self._build()
        withdrawn = withdraw_publication(
            rev1.state, acted_by="test", content_hash=rev1.content_hash
        )
        # new revision exists but has no published snapshot yet
        assert aggregate([withdrawn]).published_revision() is None

    def test_new_revision_is_returned_after_it_is_published(self):
        from question_core.contracts.v1 import (
            Completeness,
            ReviewState,
            StateSnapshot,
            approve_revision,
            publish_revision,
            withdraw_publication,
        )

        aggregate, rev1, rev2 = self._build()
        withdrawn = withdraw_publication(
            rev1.state, acted_by="test", content_hash=rev1.content_hash
        )
        pending = StateSnapshot(
            revision_id=rev2.revision_id,
            content_hash=rev2.content_hash,
            completeness=Completeness.COMPLETE,
            review=ReviewState.PENDING_REVIEW,
        )
        approved = approve_revision(
            pending, approved_by="reviewer", content_hash=rev2.content_hash
        )
        published = publish_revision(
            approved, acted_by="publisher", content_hash=rev2.content_hash
        )
        assert (
            aggregate([withdrawn, published]).published_revision().revision_id
            == rev2.revision_id
        )

    def test_two_published_revisions_fail_closed(self):
        from question_core.contracts.v1 import (
            Completeness,
            ReviewState,
            StateSnapshot,
            approve_revision,
            publish_revision,
        )

        aggregate, rev1, rev2 = self._build()
        pending = StateSnapshot(
            revision_id=rev2.revision_id,
            content_hash=rev2.content_hash,
            completeness=Completeness.COMPLETE,
            review=ReviewState.PENDING_REVIEW,
        )
        published2 = publish_revision(
            approve_revision(pending, approved_by="reviewer", content_hash=rev2.content_hash),
            acted_by="publisher",
            content_hash=rev2.content_hash,
        )
        with pytest.raises(ValueError, match="multiple published revisions"):
            aggregate([rev1.state, published2]).published_revision()

    def test_student_detail_is_not_served_when_no_published_revision(self):
        from question_core.contracts.v1 import withdraw_publication
        from strict_adapter.student_api import build_student_detail

        aggregate, rev1, _ = self._build()
        withdrawn = withdraw_publication(
            rev1.state, acted_by="test", content_hash=rev1.content_hash
        )
        agg = aggregate([withdrawn])
        # Owner D2-A: the question is temporarily not servable; the student
        # API must not fall back to the superseded revision.
        assert build_student_detail(agg, submitted=False) is None

