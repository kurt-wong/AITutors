"""QCORE-ANSWER-FIDELITY-03 定向验证：12 道 Owner 抽检题（跨三卷）+ 反例。

输入 = Phase 2 封存 Manifest（DSH PASS 终态）：
* chem 2020全国I卷  manifest_sha a0135baf…
* chn  2019江苏卷    manifest_sha f411de80…
* eng  2019北京卷    manifest_sha 75ac87fb…
只读封存产物；断言 Phase 1 契约设计 + Owner D-1/D-2 裁决全部生效。
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from question_core.contracts.v1 import (  # noqa: E402
    AssetSlot,
    Completeness,
    candidate_adapter,
)
from strict_adapter.extract import load_source_lines  # noqa: E402
from strict_adapter.mapper import MappingContext, map_all  # noqa: E402

P2 = Path(r"D:\Project\AITutors\Preprocessing\runs\qcore_answer_fidelity_02")

PAPERS = {
    "chem": {
        "dir": P2 / "chemistry",
        "stem": "2020全国I卷高考真题化学（教师版）(1)",
        "paper_id": "2020全国I卷高考真题化学（教师版）(1)",
        "subject": "化学",
        "manifest_sha": "a0135baf8729e2a035381e7085acc17b39e3d3c5e009f15e9d6fa50f85e122f4",
        "ocr_dir": Path("ocr_output") / "高三" / "化学",
    },
    "chn": {
        "dir": P2 / "chinese",
        "stem": "2019江苏高考真题语文（教师版）(1)",
        "paper_id": "2019江苏高考真题语文（教师版）(1)",
        "subject": "语文",
        "manifest_sha": "f411de80b7eaf94225d191222e4de093bf891af3045e479f9bfe8113167257d4",
        "ocr_dir": Path("ocr_output") / "高三" / "语文",
    },
    "eng": {
        "dir": P2 / "english",
        "stem": "2019北京高考真题英语（教师版）(1)",
        "paper_id": "2019北京高考真题英语（教师版）(1)",
        "subject": "英语",
        "manifest_sha": "75ac87fbb40a637ac4e6ad9a9e286e4a78c1f6b65f6e5a3cc877d3b543df1d0e",
        "ocr_dir": Path("ocr_output") / "高三" / "英语",
    },
}


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _build_mappings(paper: str) -> dict:
    spec = PAPERS[paper]
    manifest = spec["dir"] / "manifest_output" / f"{spec['stem']}.manifest.json"
    src_md = spec["dir"] / spec["ocr_dir"] / f"{spec['stem']}.md"
    annotated = spec["dir"] / "manifest_output" / f"{spec['stem']}.annotated.md"
    assert manifest.is_file() and src_md.is_file(), (manifest, src_md)
    assert _sha(manifest) == spec["manifest_sha"], f"{paper} sealed manifest changed"
    data = json.loads(manifest.read_text(encoding="utf-8"))
    ctx = MappingContext(
        lines=load_source_lines(str(src_md)),
        manifest=data,
        manifest_path=str(manifest),
        manifest_name=manifest.name,
        source_md_path=str(src_md),
        source_md_name=src_md.name,
        source_pdf_name=f"{spec['stem']}.pdf",
        annotated_md_name=annotated.name,
        manifest_sha=_sha(manifest),
        source_md_sha=_sha(src_md),
        source_pdf_sha="e" * 64,
        annotated_md_sha=_sha(annotated) if annotated.is_file() else "0" * 64,
        manifest_bytes=manifest.stat().st_size,
        source_md_bytes=src_md.stat().st_size,
        source_pdf_bytes=1,
        annotated_md_bytes=annotated.stat().st_size if annotated.is_file() else 1,
        image_by_line={a["line_no"]: a for a in data.get("image_assets", [])},
        paper_id=spec["paper_id"],
        subject=spec["subject"],
        run_id="qcore-answer-fidelity-03-spotcheck",
    )
    return {m.unit_id: m for m in map_all(ctx)}


@pytest.fixture(scope="module")
def chem():
    return _build_mappings("chem")


@pytest.fixture(scope="module")
def chn():
    return _build_mappings("chn")


@pytest.fixture(scope="module")
def eng():
    return _build_mappings("eng")


def _slot_count(comp) -> int:
    return sum(len(s.answer_value.answer_value) for s in comp.answer_value)


# ===========================================================================
# 12 道抽检题（工单 §5 表 + DSH Phase3 基线 §5）
# ===========================================================================


class TestSpotcheckChem:
    def test_q3_inline_to_single_choice(self, chem):
        m = chem["Q3"]
        assert m.completeness == "complete"
        ans = m.candidate.core.answers[0]
        assert ans.answer_type == "single_choice"
        assert ans.answer_value == "A"
        assert ans.evidence_kind.value == "inline_in_explanation"
        assert ans.statements[0].source_region == "explanation_area"
        assert ans.statements[0].locators[0].line_start == 338

    def test_q8_six_subs_eight_slots(self, chem):
        comp = chem["Q8"].candidate.core.answers[0]
        assert comp.answer_type == "composite"
        assert len(comp.answer_value) == 6
        assert _slot_count(comp) == 8
        for sub in comp.answer_value:
            assert sub.sub_body_local_id, sub.sub_label
            for b in sub.answer_value.slot_bindings:
                assert b.sub_label is not None

    def test_q10_seven_items_kept_disputed(self, chem):
        m = chem["Q10"]
        comp = m.candidate.core.answers[0]
        assert comp.answer_type == "composite"
        assert comp.attribution == "disputed"
        assert _slot_count(comp) == 7
        assert len(comp.answer_value) == 4
        # P-1 冻结记录仍在（不丢）
        assert any(
            r.evidence_status.value == "disputed" and "P-1" in (r.note or "")
            for r in m.candidate.core.evidence.records
        )

    def test_q11_nine_items_four_subs(self, chem):
        comp = chem["Q11"].candidate.core.answers[0]
        assert comp.answer_type == "composite"
        assert len(comp.answer_value) == 4
        assert _slot_count(comp) == 9

    def test_q12_image_and_mixed_slots(self, chem):
        m = chem["Q12"]
        comp = m.candidate.core.answers[0]
        assert _slot_count(comp) == 7
        by = {s.sub_label.strip("()（）"): s for s in comp.answer_value}
        inner5 = by["5"].answer_value
        assert isinstance(inner5.answer_value[0], AssetSlot)
        assert (
            inner5.answer_value[0].assets[0].role == "answer_value"
        )
        inner6 = by["6"].answer_value
        assert inner6.answer_value[0] == "6"
        assert isinstance(inner6.answer_value[1], AssetSlot)
        # canonical asset 与 Candidate Asset 哈希一致（DSH 口径）
        assets = {a.asset_id: a for a in m.candidate.core.content.assets}
        for ref in (
            inner5.answer_value[0].assets[0].asset_id,
            inner6.answer_value[1].assets[0].asset_id,
        ):
            assert ref in assets
            assert assets[ref].asset_role == "answer_image"
            assert len(assets[ref].content_hash) == 64


class TestSpotcheckChn:
    def test_q2_inline_to_single_choice(self, chn):
        m = chn["Q2"]
        assert m.completeness == "complete"
        ans = m.candidate.core.answers[0]
        assert ans.answer_type == "single_choice"
        assert ans.answer_value == "A"
        assert ans.statements[0].source_region == "explanation_area"
        assert ans.statements[0].locators[0].line_start == 473

    def test_q8_three_subs_not_merged(self, chn):
        comp = chn["Q8"].candidate.core.answers[0]
        assert comp.answer_type == "composite"
        assert len(comp.answer_value) == 3
        by = {s.sub_label.strip("()（）"): s for s in comp.answer_value}
        assert by["1"].answer_value.answer_type == "single_choice"
        assert by["1"].answer_value.answer_value == "D"
        assert by["2"].answer_value.answer_type == "fill_blank"
        # 多点内容整段保留（不 '；' 切分丢失）
        text2 = by["2"].answer_value.answer_value[0]
        assert "从所拿工资" in text2 and "从扑过去" in text2

    def test_q12_three_version_conflict(self, chn):
        m = chn["Q12"]
        comp = m.candidate.core.answers[0]
        by = {s.sub_label.strip("()（）"): s for s in comp.answer_value}
        inner2 = by["2"].answer_value
        assert inner2.answer_value[1] is None  # 争议空位不选边
        assert inner2.answer_conflict == "source_conflict"
        slot_stmts = [s for s in inner2.statements if s.slot_index == 1]
        assert len(slot_stmts) == 3
        regions = {s.source_region for s in slot_stmts}
        assert regions == {"stem_area", "answer_area", "explanation_area"}
        values = {s.value_text for s in slot_stmts}
        assert values == {"张珙", "张琪"}
        # (1)(3) 不受影响；(2) 其余两空照常
        assert by["1"].answer_value.answer_value[0].startswith("然青莲")
        assert inner2.answer_value[0] == "西厢记"
        assert inner2.answer_value[2] == "崔莺莺"
        assert "杜甫" in by["3"].answer_value.answer_value[0]
        # 三版本证据 + source_internal 冲突登记
        assert m.candidate.core.evidence.conflicts
        assert (
            m.candidate.core.evidence.conflicts[0].conflict_origin
            == "source_internal"
        )
        assert len(m.candidate.core.evidence.conflicts[0].evidence_ids) == 3

    def test_q13_multi_choice_inline(self, chn):
        ans = chn["Q13"].candidate.core.answers[0]
        assert ans.answer_type == "multi_choice"
        assert set(ans.answer_value) == {"A", "D"}
        assert ans.attribution == "attributed"


class TestSpotcheckEng:
    def test_u3_four_items_verbatim(self, eng):
        comp = eng["U3"].candidate.core.answers[0]
        assert comp.answer_type == "composite"
        assert len(comp.answer_value) == 4
        vals = [
            s.answer_value.answer_value[0]
            for s in comp.answer_value
        ]
        assert vals[0] == "suggests/suggested/has suggested"
        assert vals[1:] == ["where", "who", "meaningful"]
        # 解析区来源保留
        for s in comp.answer_value:
            assert s.answer_value.statements[0].source_region == "explanation_area"

    def test_u4_twenty_slots_two_conflict_groups(self, eng):
        m = eng["U4"]
        comp = m.candidate.core.answers[0]
        assert comp.answer_type == "composite"
        assert len(comp.answer_value) == 20
        labels = [s.sub_label for s in comp.answer_value]
        assert labels == [str(n) for n in range(11, 31)]
        by = {s.sub_label: s for s in comp.answer_value}
        assert by["14"].answer_value.answer_value == "D"
        assert by["15"].answer_value.answer_value == "B"
        assert by["30"].answer_value.answer_value == "C"
        # 2 组双版本冲突：选项区(stem_area) vs 解析区可区分
        assert by["14"].answer_conflict == "source_conflict"
        assert by["15"].answer_conflict == "source_conflict"
        stmts14 = {
            (s.value_text, s.source_region)
            for s in by["14"].statements
            if s.note and "source_conflict" in s.note
        }
        assert stmts14 == {
            ("wandered", "stem_area"),
            ("conversations", "explanation_area"),
        }
        stmts15 = {
            (s.value_text, s.source_region)
            for s in by["15"].statements
            if s.note and "source_conflict" in s.note
        }
        assert stmts15 == {
            ("conversations", "stem_area"),
            ("greeted", "explanation_area"),
        }
        origins = {c.conflict_origin for c in m.candidate.core.evidence.conflicts}
        assert origins == {"source_internal"}
        assert m.candidate.core.evidence.blocking_conflicts() == []

    def test_u9_five_slots_shared_pool_intact(self, eng):
        m = eng["U9"]
        comp = m.candidate.core.answers[0]
        assert len(comp.answer_value) == 5
        by = {s.sub_label: s for s in comp.answer_value}
        assert [by[str(n)].answer_value.answer_value for n in range(46, 51)] == [
            "B", "E", "G", "D", "F",
        ]
        # 共享选项池挂父 body（不破坏）
        parent = [
            b for b in m.candidate.core.content.bodies
            if b.parent_question_ref is None
        ][0]
        assert len(parent.options) == 7

    def test_u10_essay_explanation_only(self, eng):
        """Owner D-1：作文范文只进 Explanation，0 TypedAnswer，不判缺答案。"""
        m = eng["U10"]
        assert m.candidate.core.question_type.value == "essay"
        assert m.candidate.core.answers == ()
        assert m.completeness == "complete"  # 不判缺答案/不完整
        assert m.state_plan == "approve_publish"
        assert len(m.explanation_blocks) >= 1
        # 范文条目来源区域/行区由证据保留
        log_trace = m.log.get("answers_trace") or []
        assert log_trace, "essay items must be traced"
        assert all(
            t["disposition"] == "explanation_per_owner_d1" for t in log_trace
        )


class TestOwnerD1Essay:
    def test_chn_q11_essay_explanation_only(self, chn):
        m = chn["Q11"]
        assert m.candidate.core.question_type.value == "essay"
        assert m.candidate.core.answers == ()
        assert m.completeness == "complete"
        assert m.state_plan == "approve_publish"

    def test_eng_u11_essay_explanation_only(self, eng):
        m = eng["U11"]
        assert m.candidate.core.answers == ()
        assert m.completeness == "complete"

    def test_essay_not_flagged_missing(self, eng, chn):
        """D-1 规则 3：不得因范文存在而标记答案缺失/不完整。"""
        for paper, uid in ((eng, "U10"), (eng, "U11"), (chn, "Q11")):
            m = paper[uid]
            assert m.completeness != "incomplete", uid
            dec = m.candidate.source.answer_declaration
            # 归属声明不声称有正式 TypedAnswer 来源
            assert dec.attribution in ("declared", "not_attributable"), uid

    def test_essay_evidence_keeps_regions(self, eng):
        m = eng["U10"]
        regions = {
            r.source_region
            for r in m.candidate.core.evidence.records
            if r.target_path == "/explanation_blocks"
        }
        assert "explanation_area" in regions


class TestOwnerD2Conflicts:
    def test_source_conflicts_never_block(self, chem, chn, eng):
        for paper in (chem, chn, eng):
            for uid, m in paper.items():
                assert m.candidate.core.evidence.blocking_conflicts() == [], uid

    def test_conflict_units_keep_both_versions(self, chem, chn, eng):
        # 全部 7 组源内冲突各有 >=2 条版本记录
        seen = 0
        for paper in (chem, chn, eng):
            for uid, m in paper.items():
                for c in m.candidate.core.evidence.conflicts:
                    if c.conflict_origin == "source_internal":
                        seen += 1
                        assert len(c.evidence_ids) >= 2, (uid, c.target_path)
        assert seen == 7, seen

    def test_conflict_not_converted_to_plain_answer(self, chn):
        """D-2：冲突不得静默转普通无冲突答案——争议空位保持 None+双/三版本。"""
        comp = chn["Q12"].candidate.core.answers[0]
        by = {s.sub_label.strip("()（）"): s for s in comp.answer_value}
        inner2 = by["2"].answer_value
        assert 1 in [
            i for i, v in enumerate(inner2.answer_value) if v is None
        ]
        assert by["2"].answer_conflict == "source_conflict"


class TestOverrideScope:
    def test_chn_q12_unaffected_by_chem_p3(self, chn):
        """F 作用域：语文 Q12 不得命中化学 Q12 的 P-3 覆盖。"""
        m = chn["Q12"]
        comp = m.candidate.core.answers[0]
        # 不是 P-3 的 disputed 全冻结：仅争议空位子问 disputed
        by = {s.sub_label.strip("()（）"): s for s in comp.answer_value}
        assert by["1"].attribution == "attributed"
        assert by["3"].attribution == "attributed"
        assert by["2"].attribution == "disputed"
        # 无 P-3 DISPUTED manifest 记录
        assert not any(
            "P-3" in (r.note or "") for r in m.candidate.core.evidence.records
        )

    def test_chn_q10_unaffected_by_chem_p1(self, chn):
        m = chn["Q10"]
        assert not any(
            "P-1" in (r.note or "") for r in m.candidate.core.evidence.records
        )


# ===========================================================================
# 内容保真反例（工单 §6.1）：非法形态必须被契约拒绝
# ===========================================================================


class TestFidelityCounterexamples:
    def test_none_slot_without_conflict_rejected(self):
        from pydantic import ValidationError

        from question_core.contracts.v1 import FillBlankAnswer

        with pytest.raises(ValidationError, match="source_conflict"):
            FillBlankAnswer(answer_value=("a", None))

    def test_none_slot_without_version_statements_rejected(self):
        from pydantic import ValidationError

        from question_core.contracts.v1 import (
            AnswerStatement,
            FillBlankAnswer,
        )

        with pytest.raises(ValidationError, match="two"):
            FillBlankAnswer(
                answer_value=("a", None),
                answer_conflict="source_conflict",
                statements=(
                    AnswerStatement(
                        statement_id="s1",
                        value_text="张琪",
                        slot_index=1,
                    ),
                ),
            )

    def test_none_slot_with_versions_accepted(self):
        from question_core.contracts.v1 import (
            AnswerStatement,
            FillBlankAnswer,
        )

        fb = FillBlankAnswer(
            answer_value=("a", None),
            answer_conflict="source_conflict",
            statements=(
                AnswerStatement(
                    statement_id="s1", value_text="张琪", slot_index=1
                ),
                AnswerStatement(
                    statement_id="s2", value_text="张珙", slot_index=1
                ),
            ),
        )
        assert fb.answer_value[1] is None

    def test_missing_sub_answer_must_not_claim_full(self):
        from pydantic import ValidationError

        from question_core.contracts.v1 import CompositeSubAnswer

        with pytest.raises(ValidationError, match="full"):
            CompositeSubAnswer(
                sub_label="（1）",
                answer_value=None,
                completeness="full",
            )

    def test_absent_sub_answer_requires_missing_reason(self):
        from pydantic import ValidationError

        from question_core.contracts.v1 import CompositeSubAnswer

        with pytest.raises(ValidationError, match="missing_reason"):
            CompositeSubAnswer(
                sub_label="（1）",
                answer_value=None,
                completeness="absent",
            )

    def test_missing_reason_with_full_rejected(self):
        from pydantic import ValidationError

        from question_core.contracts.v1 import FillBlankAnswer

        with pytest.raises(ValidationError, match="missing_reason"):
            FillBlankAnswer(
                answer_value=("x",),
                completeness="full",
                missing_reason="extraction_gap",
            )

    def test_no_fabricated_slot_split_on_semicolon(self, chn):
        """G-04 反例：'；' 多点内容不得被切分成伪空位。"""
        comp = chn["Q8"].candidate.core.answers[0]
        by = {s.sub_label.strip("()（）"): s for s in comp.answer_value}
        inner2 = by["2"].answer_value
        assert len(inner2.answer_value) == 1  # 1 item = 1 slot，不按 '；' 切
        assert "；" in inner2.answer_value[0]

    def test_all_38_units_round_trip(self, chem, chn, eng):
        """全部映射结果可经契约 adapter 往返（每个校验器重跑）。"""
        count = 0
        for paper in (chem, chn, eng):
            for uid, m in paper.items():
                cand = m.candidate
                candidate_adapter.validate_python(cand.model_dump(mode="json"))
                count += 1
        assert count == 38

    def test_new_answer_shapes_persistence_round_trip(self):
        """AssetSlot/None/statements 新结构经序列化往返不丢。"""
        from question_core.contracts.v1 import (
            AnswerAssetRef,
            AnswerStatement,
            AssetSlot,
            CompositeAnswer,
            CompositeSubAnswer,
            FillBlankAnswer,
            typed_answer_adapter,
        )

        ans = CompositeAnswer(
            answer_value=(
                CompositeSubAnswer(
                    sub_label="（1）",
                    answer_value=FillBlankAnswer(
                        answer_value=(
                            "6",
                            AssetSlot(
                                assets=(
                                    AnswerAssetRef(
                                        asset_id="img_x",
                                        role="answer_value",
                                    ),
                                )
                            ),
                            None,
                        ),
                        answer_conflict="source_conflict",
                        statements=(
                            AnswerStatement(
                                statement_id="s1",
                                value_text="张琪",
                                slot_index=2,
                            ),
                            AnswerStatement(
                                statement_id="s2",
                                value_text="张珙",
                                slot_index=2,
                            ),
                        ),
                    ),
                ),
            ),
        )
        payload = ans.model_dump(mode="json")
        restored = typed_answer_adapter.validate_python(payload)
        assert restored == ans
        inner = restored.answer_value[0].answer_value
        assert isinstance(inner.answer_value[1], AssetSlot)
        assert inner.answer_value[2] is None
        assert len(inner.statements) == 2

    def test_item_count_across_papers_is_144(self, chem, chn, eng):
        """答案条目追踪完备性：144 条全部进入映射日志追踪。"""
        total = 0
        for paper in (chem, chn, eng):
            for uid, m in paper.items():
                total += len(m.log.get("answers_trace") or [])
        assert total == 144, total


# ===========================================================================
# DSH R1 回归（B1/B2）：target 可解析 + 逐答案 evidence_kind provenance
# ===========================================================================


def _resolve_pointer(doc, pointer: str):
    """RFC 6901 逐段解析；路径不存在则 KeyError/IndexError。"""
    assert pointer.startswith("/"), pointer
    cur = doc
    for seg in pointer.lstrip("/").split("/"):
        seg = seg.replace("~1", "/").replace("~0", "~")
        if isinstance(cur, list):
            cur = cur[int(seg)]
        else:
            cur = cur[seg]
    return cur


class TestTraceTargetsResolvable:
    """DSH B1：answers_trace.candidate_target 必须逐条可解析（无越界下标）。"""

    def test_all_pointer_targets_resolve(self, chem, chn, eng):
        checked = 0
        for paper in (chem, chn, eng):
            for uid, m in paper.items():
                # 指针约定基座 = CandidateCore（/answers/0/...；与 DSH 独立
                # 验证 PHASE3_VERIFY6 同口径）
                dump = m.candidate.core.model_dump(mode="json")
                for t in m.log.get("answers_trace") or []:
                    target = t.get("target") or ""
                    if not target.startswith("/"):
                        # essay 行为描述性 target（Owner D-1 处置），不作指针
                        assert t.get("disposition") == "explanation_per_owner_d1", (
                            uid,
                            t,
                        )
                        continue
                    _resolve_pointer(dump, target)  # 不存在即抛
                    checked += 1
        assert checked == 136, checked

    def test_single_value_answers_point_at_value_field(self, chem, chn):
        """单值题/单选子问：指向值字段本身，不带槽位下标（DSH B1 形态）。"""
        q3 = chem["Q3"].log["answers_trace"][0]
        assert q3["target"] == "/answers/0/answer_value"
        q13 = chn["Q13"].log["answers_trace"][0]
        assert q13["target"] == "/answers/0/answer_value"
        q8 = chn["Q8"]
        t_sub1 = q8.log["answers_trace"][0]
        assert (
            t_sub1["target"]
            == "/answers/0/answer_value/0/answer_value/answer_value"
        )
        dump = q8.candidate.core.model_dump(mode="json")
        assert _resolve_pointer(dump, t_sub1["target"]) == "D"

    def test_fill_blank_targets_keep_slot_index(self, chem):
        q8 = chem["Q8"]
        t0 = q8.log["answers_trace"][0]
        assert t0["target"].endswith("/answer_value/answer_value/0")
        dump = q8.candidate.core.model_dump(mode="json")
        assert _resolve_pointer(dump, t0["target"]).startswith("加快酸浸")


class TestEnglishEvidenceKindProvenance:
    """DSH B2：逐答案 evidence_kind 与 Manifest answer_evidence.type 一致
    （顶层 / CompositeSubAnswer / inner 三层同源）。"""

    @staticmethod
    def _all_layers(comp):
        layers = [comp]
        for sub in comp.answer_value:
            layers.append(sub)
            layers.append(sub.answer_value)
        return layers

    @pytest.mark.parametrize("uid", ["U1", "U2", "U3"])
    def test_u1_u3_all_layers_inline_in_explanation(self, eng, uid):
        comp = eng[uid].candidate.core.answers[0]
        for layer in self._all_layers(comp):
            assert (
                layer.evidence_kind.value == "inline_in_explanation"
            ), (uid, layer.answer_type)

    def test_u4_all_layers_range_string(self, eng):
        comp = eng["U4"].candidate.core.answers[0]
        for layer in self._all_layers(comp):
            assert layer.evidence_kind.value == "range_string", layer.answer_type

    @pytest.mark.parametrize("uid", ["U5", "U6", "U7", "U8", "U9"])
    def test_u5_u9_all_layers_answer_lines(self, eng, uid):
        comp = eng[uid].candidate.core.answers[0]
        for layer in self._all_layers(comp):
            assert layer.evidence_kind.value == "answer_lines", (uid, layer.answer_type)
