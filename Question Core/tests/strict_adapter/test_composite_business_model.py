"""Composite Unit 业务模型不变量测试（QCORE-DELIVERY-01-C-R4）。

锁定 Owner C-R4 业务口径：
  9 个 composite Unit → 9 个 Candidate/Question/Revision/Instance；
  50 个**内部小问**保留在各自 Question 的 content 树内
  （parent_question_ref / sub_question_ids），不获得独立 Question 身份；
  Question Type（作答形式）与 Unit Type（组织结构）严格分离，
  composite/standalone 不得作为 Question Type。

只读内存构造（admit 不落库）；真实封存 Manifest。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from question_core.contracts.v1 import (  # noqa: E402
    QuestionType,
    UnitType,
    candidate_adapter,
)
from strict_adapter.admission import admit  # noqa: E402
from strict_adapter.english_composite import is_english_composite, map_unit  # noqa: E402
from strict_adapter.extract import load_source_lines  # noqa: E402
from strict_adapter.mapper import MappingContext  # noqa: E402

RUN02 = Path(r"D:\Project\AITutors\Preprocessing\runs\qcore_preimport_02\english")
MD = RUN02 / "ocr_output" / "高三" / "英语" / "2019北京高考真题英语（教师版）(1).md"
MANIFEST = RUN02 / "manifest_output" / "2019北京高考真题英语（教师版）(1).manifest.json"
MD_SHA = "c2a31c8cadb2e0ab765d672c87395d6a8baa43d7361fe5e94e757c2933ba7430"

pytestmark = pytest.mark.skipif(
    not MANIFEST.is_file() or not MD.is_file(), reason="sealed english inputs not found"
)

SUB_COUNTS = {"U1": 3, "U2": 3, "U3": 4, "U4": 20, "U5": 3, "U6": 4, "U7": 4, "U8": 4, "U9": 5}
FORBIDDEN_QUESTION_TYPES = {"composite", "standalone"}


@pytest.fixture(scope="module")
def ctx() -> MappingContext:
    import hashlib

    assert hashlib.sha256(MD.read_bytes()).hexdigest() == MD_SHA
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    return MappingContext(
        lines=load_source_lines(str(MD)),
        manifest=manifest,
        manifest_path=str(MANIFEST),
        manifest_name=MANIFEST.name,
        source_md_path=str(MD),
        source_md_name=MD.name,
        source_pdf_name="2019北京高考真题英语（教师版）(1).pdf",
        annotated_md_name="2019北京高考真题英语（教师版）(1).annotated.md",
        manifest_sha="b821a7de880a94ff97d24cfaf7c4e2f0ff878aa6289820a1e01f7f621d08ba7e",
        source_md_sha=MD_SHA,
        source_pdf_sha="c3ec6db14b5781296395c6e7bf0c5538dd12971073fc503adefe490e13895ebd",
        annotated_md_sha="99e9ed4a9966f255c0ed06b6e88e147d1ffa86e832af35806637579c7fbb7331",
        manifest_bytes=MANIFEST.stat().st_size,
        source_md_bytes=MD.stat().st_size,
        source_pdf_bytes=2145605,
        annotated_md_bytes=76502,
        image_by_line={a["line_no"]: a for a in manifest.get("image_assets", [])},
        paper_id="2019北京高考真题英语（教师版）(1)",
        run_id="qcore-delivery-01c-r4-tests",
    )


@pytest.fixture(scope="module")
def aggregates(ctx):
    """9 个 Unit → 9 个 (mapping, aggregate)（admit 仅内存构造，不落库）。"""
    out = {}
    ordinal = 0
    for u in ctx.manifest["units"]:
        if not is_english_composite(u, ctx):
            continue
        m = map_unit(u, ctx)
        ordinal += 1
        res = admit(m, ctx, ordinal=ordinal)
        assert res.validated and res.admitted
        out[u["unit_id"]] = (m, res.aggregate)
    return out


class TestQuestionIdentityCounts:
    def test_nine_units_nine_questions(self, aggregates):
        assert sorted(aggregates) == [f"U{i}" for i in range(1, 10)]
        total_q = total_r = total_i = total_subs = 0
        for uid, (m, agg) in sorted(aggregates.items()):
            # 一个 composite Unit ↔ 一个 Candidate/Question/Revision/Instance
            assert len(agg.revisions) == 1, uid
            assert len(agg.instances) == 1, uid
            assert agg.identity is not None, uid
            content = agg.revisions[0].content
            subs = content.bodies[1:]
            assert len(subs) == SUB_COUNTS[uid], uid
            total_q += 1
            total_r += len(agg.revisions)
            total_i += len(agg.instances)
            total_subs += len(subs)
        assert total_q == 9
        assert total_r == 9
        assert total_i == 9
        assert total_subs == 50

    def test_internal_sub_questions_hold_no_identity(self, aggregates):
        """内部小问不得持有独立 Question/Revision/Instance 身份。"""
        all_labels = []
        for uid, (m, agg) in sorted(aggregates.items()):
            subs = agg.revisions[0].content.bodies[1:]
            for b in subs:
                for field_name in ("question_id", "revision_id", "instance_id"):
                    assert not hasattr(b, field_name) or getattr(b, field_name) is None, (
                        uid,
                        b.local_id,
                    )
                assert b.parent_question_ref is not None, (uid, b.local_id)
                all_labels.append(b.printed_number)
        assert all_labels == [str(n) for n in range(1, 51)]

    def test_question_ids_distinct_per_unit(self, aggregates):
        ids = [str(agg.identity.question_id) for _, agg in aggregates.values()]
        assert len(set(ids)) == 9


class TestCompositeInternalStructure:
    def test_tree_and_shared_material(self, aggregates):
        for uid, (m, agg) in sorted(aggregates.items()):
            content = agg.revisions[0].content
            parent = content.bodies[0]
            subs = content.bodies[1:]
            assert len(content.materials) == 1, uid
            mid = content.materials[0].material_id
            assert parent.material_ids == (mid,), uid
            for b in subs:
                assert b.parent_question_ref == parent.local_id, uid
                assert b.material_ids == (mid,), uid
            assert list(parent.sub_question_ids) == [b.local_id for b in subs], uid

    def test_option_pool_not_scattered(self, aggregates):
        m9, agg9 = aggregates["U9"]
        parent = agg9.revisions[0].content.bodies[0]
        subs = agg9.revisions[0].content.bodies[1:]
        assert [o.label for o in parent.options] == list("ABCDEFG")
        for b in subs:
            assert b.options == (), b.printed_number
        m4, agg4 = aggregates["U4"]
        p4 = agg4.revisions[0].content.bodies[0]
        assert p4.options == ()
        for b in agg4.revisions[0].content.bodies[1:]:
            assert [o.label for o in b.options] == ["A", "B", "C", "D"], b.printed_number


class TestTypeAxes:
    def test_composite_standalone_never_question_type(self, aggregates):
        for uid, (m, agg) in sorted(aggregates.items()):
            for b in agg.revisions[0].content.bodies:
                assert b.question_type.value not in FORBIDDEN_QUESTION_TYPES, (
                    uid,
                    b.local_id,
                    b.question_type.value,
                )
                assert isinstance(b.question_type, QuestionType)

    def test_sub_question_types_are_real_answer_forms(self, aggregates):
        """内部小问 Question Type = 真实作答形式：填空/单选（含 A-G 池单选）。"""
        expect = {"U1": "fill_blank", "U2": "fill_blank", "U3": "fill_blank"}
        for uid, (m, agg) in sorted(aggregates.items()):
            want = expect.get(uid, "single_choice")
            for b in agg.revisions[0].content.bodies[1:]:
                assert b.question_type.value == want, (uid, b.printed_number)

    def test_unit_type_axis_separate(self, aggregates):
        for uid, (m, agg) in sorted(aggregates.items()):
            for b in agg.revisions[0].content.bodies:
                assert isinstance(b.unit_type, UnitType)
                assert b.unit_type == UnitType.COMPOSITE_QUESTION, (uid, b.local_id)
                # 两轴取值域不相交：UnitType 值不得出现在 question_type
                assert b.question_type.value not in {
                    "composite_question",
                    "standalone_question",
                }

    def test_contract_validation(self, aggregates):
        for uid, (m, agg) in sorted(aggregates.items()):
            candidate_adapter.validate_python(m.candidate.model_dump(mode="json"))


class TestR3ResultsUnbroken:
    def test_u3_status_preserved(self, aggregates):
        m3, _ = aggregates["U3"]
        assert m3.completeness == "incomplete"
        assert m3.log["declaration"]["declared_value"].startswith(
            "7.suggests/suggested/has suggested"
        )

    def test_u4_q30_and_u9_q49_preserved(self, aggregates):
        _, agg4 = aggregates["U4"]
        subs4 = {b.printed_number: b for b in agg4.revisions[0].content.bodies[1:]}
        assert "___30___" in subs4["30"].stem_blocks[0].text
        _, agg9 = aggregates["U9"]
        subs9 = {b.printed_number: b for b in agg9.revisions[0].content.bodies[1:]}
        assert "TEAM" in subs9["49"].stem_blocks[0].text
        assert "Another possibility" not in subs9["49"].stem_blocks[0].text
