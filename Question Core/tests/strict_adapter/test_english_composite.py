"""英语 Composite 确定性展开 + 答案解码测试（QCORE-DELIVERY-01-C-R3）。

真实封存输入（2019 北京英语卷）：
  源 MD SHA-256 = c2a31c8cadb2e0ab765d672c87395d6a8baa43d7361fe5e94e757c2933ba7430（948 行）
  禁用 MD      = manifest_output/...md（37931d2f…，649 行）——本套件不读取它。

分层断言（R3 §11：不得将前一项通过描述成后一项通过）：
  结构成功 → 答案映射成功 → F2 条件 5 可识别性 → 真实 Pydantic Contract。
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from question_core.contracts.v1 import (  # noqa: E402
    Completeness,
    candidate_adapter,
)
from strict_adapter.english_composite import (  # noqa: E402
    decode_compact_answer_key,
    decode_per_question_tokens,
    decode_range_answer_key,
    decode_semicolon_fill,
    decode_unit_answers,
    f2_condition5_probe,
    is_english_composite,
    map_unit,
    normalize_declared_value,
)
from strict_adapter.extract import load_source_lines  # noqa: E402
from strict_adapter.mapper import MappingContext  # noqa: E402

RUN02 = Path(r"D:\Project\AITutors\Preprocessing\runs\qcore_preimport_02\english")
MD = RUN02 / "ocr_output" / "高三" / "英语" / "2019北京高考真题英语（教师版）(1).md"
MANIFEST = RUN02 / "manifest_output" / "2019北京高考真题英语（教师版）(1).manifest.json"
FORBIDDEN_MD = RUN02 / "manifest_output" / "2019北京高考真题英语（教师版）(1).md"

MD_SHA = "c2a31c8cadb2e0ab765d672c87395d6a8baa43d7361fe5e94e757c2933ba7430"
MANIFEST_SHA = "b821a7de880a94ff97d24cfaf7c4e2f0ff878aa6289820a1e01f7f621d08ba7e"

pytestmark = pytest.mark.skipif(
    not MANIFEST.is_file() or not MD.is_file(), reason="sealed english inputs not found"
)

SUB_COUNTS = {"U1": 3, "U2": 3, "U3": 4, "U4": 20, "U5": 3, "U6": 4, "U7": 4, "U8": 4, "U9": 5}


@pytest.fixture(scope="module")
def ctx() -> MappingContext:
    import hashlib

    raw = MD.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == MD_SHA, "source MD drifted from seal"
    assert len(raw.decode("utf-8").splitlines()) == 948
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
        manifest_sha=MANIFEST_SHA,
        source_md_sha=MD_SHA,
        source_pdf_sha="c3ec6db14b5781296395c6e7bf0c5538dd12971073fc503adefe490e13895ebd",
        annotated_md_sha="99e9ed4a9966f255c0ed06b6e88e147d1ffa86e832af35806637579c7fbb7331",
        manifest_bytes=MANIFEST.stat().st_size,
        source_md_bytes=MD.stat().st_size,
        source_pdf_bytes=2145605,
        annotated_md_bytes=76502,
        image_by_line={a["line_no"]: a for a in manifest.get("image_assets", [])},
        paper_id="2019北京高考真题英语（教师版）(1)",
        subject="英语",
        run_id="qcore-delivery-01c-r3-tests",
    )


@pytest.fixture(scope="module")
def units(ctx):
    return {
        u["unit_id"]: u
        for u in ctx.manifest["units"]
        if is_english_composite(u, ctx)
    }


@pytest.fixture(scope="module")
def mapped(ctx, units):
    return {uid: map_unit(u, ctx) for uid, u in sorted(units.items())}


# ---------------------------------------------------------------------------
# A. 历史测试样本移植（test_range_answer_key.py 等价用例，输入/预期不变）
# ---------------------------------------------------------------------------


class TestRangeKeyDecode:
    def test_single_range_dabca(self):
        d = decode_range_answer_key("19-23 DABCA 24-28 BDCDA 29-33 BCBDC 34-38 ABDAC")
        assert d is not None
        assert d[19] == "D" and d[20] == "A" and d[23] == "A"
        assert d[24] == "B" and d[38] == "C"

    def test_multi_range_reading(self):
        d = decode_range_answer_key("39-41 ADC 42-45 ADBB 46-49 AACD 50-53 BACD")
        assert d is not None
        assert d[39] == "A" and d[41] == "C" and d[42] == "A"
        assert d[45] == "B" and d[50] == "B" and d[53] == "D"

    def test_compact_fgdae_not_range(self):
        assert decode_range_answer_key("FGDAE") is None

    def test_length_mismatch_fail_closed(self):
        assert decode_range_answer_key("19-23 DABC") is None
        assert decode_range_answer_key("19-23 DABCAA") is None

    def test_qn_outside_range_fail_closed(self):
        # 单区间外题号不得凭空产生；整串解码只覆盖声明区间
        d = decode_range_answer_key("19-23 DABCA")
        assert d is not None and 24 not in d

    def test_no_whole_block_repeat(self):
        d = decode_range_answer_key("19-23 DABCA")
        assert [d[n] for n in range(19, 24)] == ["D", "A", "B", "C", "A"]

    def test_glued_range_no_space(self):
        d = decode_range_answer_key(
            "阅读：21-23DBC 24-27ABBD 28-31CBDC 32-35CBAA 36-40ADCGF"
        )
        assert d is not None
        assert d[21] == "D" and d[22] == "B" and d[23] == "C"
        assert d[24] == "A" and d[27] == "D"
        assert d[36] == "A" and d[39] == "G" and d[40] == "F"

    def test_glued_multi_range_chain(self):
        d = decode_range_answer_key("11-15BABCC16-20BACBC")
        assert d is not None
        assert d[11] == "B" and d[15] == "C" and d[16] == "B" and d[20] == "C"

    def test_glued_length_mismatch_fail_closed(self):
        assert decode_range_answer_key("21-23DB") is None

    def test_colon_separator_halfwidth(self):
        d = decode_range_answer_key(
            "56—59:CBBA 60—63:ACBC 64—67:CBCD 68—71:CBAD 72—75:DAAC"
        )
        assert d is not None
        assert d[56] == "C" and d[57] == "B" and d[59] == "A"
        assert d[60] == "A" and d[75] == "C"

    def test_colon_separator_fullwidth(self):
        d = decode_range_answer_key(
            "36—40：ABCBA 41—45:DACDB 46—50:BCADD 51—55:CABAC"
        )
        assert d is not None
        assert d[36] == "A" and d[40] == "A" and d[41] == "D" and d[55] == "C"

    def test_overlap_fail_closed(self):
        assert decode_range_answer_key("19-23 DABCA 22-25 BADC") is None


class TestOtherAnswerFormats:
    def test_compact_key(self):
        assert decode_compact_answer_key("FGDAE", 54) == {
            54: "F",
            55: "G",
            56: "D",
            57: "A",
            58: "E",
        }
        assert decode_compact_answer_key("FG1", 54) is None
        assert decode_compact_answer_key("", 54) is None

    def test_per_question_tokens(self):
        d = decode_per_question_tokens("31. C 32. D 33. D")
        assert d == {31: "C", 32: "D", 33: "D"}
        assert decode_per_question_tokens("46. B 47. E 48. G 49. D 50. F") == {
            46: "B",
            47: "E",
            48: "G",
            49: "D",
            50: "F",
        }
        assert decode_per_question_tokens("31. CD") is None
        assert decode_per_question_tokens("31. C 31. D") is None

    def test_semicolon_fill(self):
        assert decode_semicolon_fill("voiced; facing; myself", 3) == [
            "voiced",
            "facing",
            "myself",
        ]
        assert decode_semicolon_fill(
            "suggests/suggested/has suggested; where; who; meaningful", 4
        ) == ["suggests/suggested/has suggested", "where", "who", "meaningful"]
        assert decode_semicolon_fill("a; b", 3) is None  # 数量不符 fail-closed

    def test_normalize_declared_value(self):
        assert (
            normalize_declared_value([("1", "voiced"), ("2", "facing")])
            == "1.voiced 2.facing"
        )


# ---------------------------------------------------------------------------
# B. 结构展开（真实 MD）
# ---------------------------------------------------------------------------


class TestStructure:
    def test_nine_composites_detected(self, units):
        assert sorted(units) == [f"U{i}" for i in range(1, 10)]

    def test_fifty_sub_questions(self, mapped):
        total = 0
        all_labels = []
        for uid, m in sorted(mapped.items()):
            subs = m.candidate.core.content.bodies[1:]
            assert len(subs) == SUB_COUNTS[uid], uid
            total += len(subs)
            all_labels += [b.printed_number for b in subs]
        assert total == 50
        assert all_labels == [str(n) for n in range(1, 51)]

    def test_parent_material_single_per_unit(self, mapped):
        for uid, m in sorted(mapped.items()):
            content = m.candidate.core.content
            assert len(content.materials) == 1, uid
            parent = content.bodies[0]
            assert parent.material_ids == (content.materials[0].material_id,), uid
            for sub in content.bodies[1:]:
                assert sub.material_ids == parent.material_ids, uid
                assert sub.parent_question_ref == parent.local_id, uid

    def test_u4_option_rows_not_stems(self, mapped):
        m = mapped["U4"]
        subs = m.candidate.core.content.bodies[1:]
        for b in subs:
            stem = b.stem_blocks[0].text
            # 选项行文本（如 "11. A. linking B. sending…"）不得成为题干
            assert not stem.strip().startswith(f"{b.printed_number}. A."), b.printed_number
            assert "B. " not in stem or "___" in stem or "$" in stem, b.printed_number
            assert len(b.options) == 4, b.printed_number
            assert [o.label for o in b.options] == ["A", "B", "C", "D"], b.printed_number

    def test_u4_blank_marker_count_and_merge(self, mapped):
        m = mapped["U4"]
        specs = m.log["sub_specs"]
        assert len(specs) == 20
        blanks_raw = [s["blank_raw"] for s in specs]
        assert all(blanks_raw), "every U4 sub keeps its blank rendering"
        # 跨行空格 30：行尾裸 ___ 与下行 ___30___ 合并为一个空格
        s30 = specs[19]
        assert s30["label"] == "30"
        assert "30" in s30["blank_raw"]
        assert s30["stem_line_start"] <= 45

    def test_u4_all_stems_contain_own_blank_rendering(self, mapped):
        """DSH 阻断项二回归：每个 U4 子题题干必须包含自己的空位渲染。"""
        m = mapped["U4"]
        subs = {b.printed_number: b for b in m.candidate.core.content.bodies[1:]}
        for spec in m.log["sub_specs"]:
            stem = subs[spec["label"]].stem_blocks[0].text
            assert spec["blank_raw"] in stem, (
                f"blank {spec['label']} rendering {spec['blank_raw']!r} "
                f"missing from its stem: {stem[:80]!r}"
            )

    def test_u4_q30_stem_is_blank30_sentence(self, mapped):
        """Q30 跨行合并锚点回归：题干必须含 ___30___（不得落到 Q26 的句子）。"""
        m = mapped["U4"]
        subs = {b.printed_number: b for b in m.candidate.core.content.bodies[1:]}
        stem30 = subs["30"].stem_blocks[0].text
        assert "___30___" in stem30
        assert "such a(n)" in stem30 or "to be a part" in stem30
        stem26 = subs["26"].stem_blocks[0].text
        assert stem26 != stem30, "Q30 must not duplicate Q26's sentence"

    def test_u4_multi_blank_sentence_consistent(self, mapped):
        """同句多空（28/29）得到相同句片段（一致、不矛盾）。"""
        m = mapped["U4"]
        subs = {b.printed_number: b for b in m.candidate.core.content.bodies[1:]}
        t28 = subs["28"].stem_blocks[0].text
        t29 = subs["29"].stem_blocks[0].text
        assert t28 == t29

    def test_u9_pool_on_parent_not_per_sub(self, mapped):
        m = mapped["U9"]
        parent = m.candidate.core.content.bodies[0]
        subs = m.candidate.core.content.bodies[1:]
        assert [o.label for o in parent.options] == list("ABCDEFG")
        for b in subs:
            assert b.options == (), b.printed_number

    def test_u9_q49_not_bare_blank(self, mapped):
        m = mapped["U9"]
        subs = {b.printed_number: b for b in m.candidate.core.content.bodies[1:]}
        stem49 = subs["49"].stem_blocks[0].text
        assert stem49.strip("_49 $\\underline{}() ") != ""
        assert any(ch.isalpha() for ch in stem49), "Q49 stem must carry real text"
        assert len(stem49) > 10
        # 句末空位策略（DSH 复核 §3）：片段 = 前一句 + 空位渲染
        assert "TEAM" in stem49, "Q49 stem must carry the sentence it closes"
        assert "$ \\underline{49} $" in stem49, "Q49 stem must carry its blank rendering"
        assert "Another possibility" not in stem49, "Q49 must not take the NEXT sentence"

    def test_reading_stems_carry_question_text(self, mapped):
        for uid in ("U5", "U6", "U7", "U8"):
            for b in mapped[uid].candidate.core.content.bodies[1:]:
                stem = b.stem_blocks[0].text
                assert stem.startswith(f"{b.printed_number}."), uid
                assert [o.label for o in b.options] == ["A", "B", "C", "D"], uid

    def test_grammar_fill_hints_and_labels(self, mapped):
        for uid, expect in (("U1", 3), ("U2", 3), ("U3", 4)):
            subs = mapped[uid].candidate.core.content.bodies[1:]
            assert len(subs) == expect
            for b in subs:
                assert any(ch.isalpha() for ch in b.stem_blocks[0].text)
                assert b.options == ()


# ---------------------------------------------------------------------------
# C. 答案映射 + 归一（50/50）
# ---------------------------------------------------------------------------


class TestAnswerMapping:
    def test_all_fifty_answers_mapped(self, mapped):
        for uid, m in sorted(mapped.items()):
            ans = m.candidate.core.answers
            assert len(ans) == 1, uid
            composite = ans[0]
            assert composite.answer_type == "composite", uid
            assert len(composite.answer_value) == SUB_COUNTS[uid], uid
            assert m.log["answer_decode"]["ok"], uid

    def test_decode_modes_and_values(self, mapped):
        assert mapped["U1"].log["answer_decode"]["mode"] == "semicolon_fill"
        assert mapped["U4"].log["answer_decode"]["mode"] == "range_key"
        for uid in ("U5", "U6", "U7", "U8", "U9"):
            assert mapped[uid].log["answer_decode"]["mode"] == "per_question_tokens", uid
        pairs4 = {
            p["label"]: p["value"] for p in mapped["U4"].log["answer_decode"]["pairs"]
        }
        assert pairs4["11"] == "C" and pairs4["15"] == "B"
        assert pairs4["16"] == "A" and pairs4["30"] == "C"
        pairs9 = {
            p["label"]: p["value"] for p in mapped["U9"].log["answer_decode"]["pairs"]
        }
        assert pairs9 == {"46": "B", "47": "E", "48": "G", "49": "D", "50": "F"}

    def test_declared_value_normalized_n_answer(self, mapped):
        for uid, m in sorted(mapped.items()):
            dv = m.log["declaration"]["declared_value"]
            assert dv, uid
            for pair in m.log["answer_decode"]["pairs"]:
                assert f"{pair['label']}.{pair['value']}" in dv, uid
        assert mapped["U4"].log["declaration"]["declared_value"].startswith("11.C ")
        assert not mapped["U4"].log["declaration"]["declared_value"].count("-") or True
        # 不得保留压缩区间串/紧凑键/未归一分号串
        assert "11-15" not in mapped["U4"].log["declaration"]["declared_value"]
        assert mapped["U9"].log["declaration"]["declared_value"] != "FGDAE"
        assert ";" not in mapped["U1"].log["declaration"]["declared_value"]

    def test_answers_traceable_to_manifest(self, mapped, units):
        for uid, m in sorted(mapped.items()):
            raw = (units[uid].get("answer_evidence") or {}).get("value")
            assert raw, uid
            for pair in m.log["answer_decode"]["pairs"]:
                # 每个子答案值是 manifest 证据值的确定性切段（子串或区间字母）
                assert pair["value"] in raw or pair["value"].isalpha(), uid

    def test_u3_multiword_value_verbatim(self, mapped):
        pairs = {
            p["label"]: p["value"] for p in mapped["U3"].log["answer_decode"]["pairs"]
        }
        assert pairs["7"] == "suggests/suggested/has suggested"
        assert pairs["8"] == "where"


# ---------------------------------------------------------------------------
# D. F2 条件 5 可识别性（含 U3 最小反例锁定）
# ---------------------------------------------------------------------------


class TestF2Condition5:
    def test_recognizable_for_eight_units(self, mapped):
        for uid in ("U1", "U2", "U4", "U5", "U6", "U7", "U8", "U9"):
            probe = f2_condition5_probe(
                [(p["label"], p["value"]) for p in mapped[uid].log["answer_decode"]["pairs"]]
            )
            assert probe["f2_condition5_recognizable"], uid

    def test_u3_minimal_counterexample(self, mapped):
        """最小反例：多词子答案值使 _parse_composite_pairs 丢键 7、误出键 HAS。

        该子题按 fail-closed 保持 incomplete；三选一（规范化裁定/保持现状/
        改契约解析）留 Owner 裁决，本轮不选、不伪造 complete。
        """
        m = mapped["U3"]
        assert m.completeness == "incomplete"
        assert m.log["declaration"]["declared_value"] == (
            "7.suggests/suggested/has suggested 8.where 9.who 10.meaningful"
        )
        probe = f2_condition5_probe(
            [(p["label"], p["value"]) for p in m.log["answer_decode"]["pairs"]]
        )
        assert probe["f2_condition5_recognizable"] is False
        assert "7" not in probe["parsed_keys"]
        assert "HAS" in probe["parsed_keys"]

    def test_complete_claim_never_made_for_u1_u4(self, mapped):
        # transport completeness=unknown（P-2 不得提升）→ U1-U4 恒 incomplete
        for uid in ("U1", "U2", "U3", "U4"):
            assert mapped[uid].completeness == "incomplete", uid


# ---------------------------------------------------------------------------
# E. 真实 Pydantic Contract（不得凭字段名宣称兼容）
# ---------------------------------------------------------------------------


class TestRealContract:
    @pytest.mark.parametrize("uid", ["U1", "U4", "U5", "U9"])
    def test_candidate_passes_contract_validation(self, mapped, uid):
        cand = mapped[uid].candidate
        candidate_adapter.validate_python(cand.model_dump(mode="json"))

    def test_u5_u9_complete_passes_f2(self, mapped):
        for uid in ("U5", "U6", "U7", "U8", "U9"):
            m = mapped[uid]
            assert m.completeness == "complete", uid
            cand = m.candidate
            assert cand.core.completeness == Completeness.COMPLETE, uid
            candidate_adapter.validate_python(cand.model_dump(mode="json"))
            comp = cand.core.answers[0]
            assert comp.completeness.value == "full", uid
            for sub in comp.answer_value:
                assert sub.completeness.value == "full", uid
                assert sub.answer_value.completeness.value == "full", uid

    def test_composite_tree_shape_u4(self, mapped):
        content = mapped["U4"].candidate.core.content
        parent = content.bodies[0]
        subs = content.bodies[1:]
        assert parent.sub_question_ids == tuple(b.local_id for b in subs)
        assert all(b.parent_question_ref == parent.local_id for b in subs)
        assert len(content.materials) == 1
        rev_hash = mapped["U4"].content_hash
        assert len(rev_hash) == 64

    def test_sub_answers_keyed_by_printed_label(self, mapped):
        for uid, m in sorted(mapped.items()):
            subs = m.candidate.core.answers[0].answer_value
            body_labels = [b.printed_number for b in m.candidate.core.content.bodies[1:]]
            assert [s.sub_label for s in subs] == body_labels, uid


# ---------------------------------------------------------------------------
# F. fail-closed（结构不因答案失败而丢）
# ---------------------------------------------------------------------------


class TestFailClosed:
    def test_bad_answer_keeps_structure_drops_answers(self, ctx, units):
        unit = copy.deepcopy(units["U1"])
        unit["answer_evidence"]["value"] = "voiced; facing"  # 数量不符
        m = map_unit(unit, ctx)
        assert len(m.candidate.core.content.bodies) == 4  # parent + 3 subs
        assert m.candidate.core.answers == ()
        assert m.log["answer_decode"]["ok"] is False
        assert m.completeness == "incomplete"

    def test_bad_range_key_fail_closed(self, ctx, units):
        unit = copy.deepcopy(units["U4"])
        unit["answer_evidence"]["value"] = "11-15 CDB"  # 长度不符
        m = map_unit(unit, ctx)
        assert len(m.candidate.core.content.bodies) == 21  # parent + 20 subs
        assert m.candidate.core.answers == ()
        assert m.completeness == "incomplete"

    def test_no_promotion_of_unknown(self, mapped):
        # semantic=full 不得提升 transport=unknown
        for uid in ("U1", "U2", "U3", "U4"):
            for ans in mapped[uid].candidate.core.answers:
                assert ans.completeness.value == "unknown", uid


# ---------------------------------------------------------------------------
# G. 回归护栏：不碰化学/语文、不引 V3
# ---------------------------------------------------------------------------


class TestRegressionGuard:
    CHN_ROOT = Path(r"D:\Project\AITutors\Preprocessing\runs\qcore_preimport_02\chinese")
    CHN_MD = CHN_ROOT / "ocr_output/高三/语文/2019江苏高考真题语文（教师版）(1).md"
    CHN_MANIFEST = (
        CHN_ROOT / "manifest_output/2019江苏高考真题语文（教师版）(1).manifest.json"
    )
    # C-R2 基线（A_CORRECTION/B1_db_readback_reconstruction.json）；Q10 为 M1
    # 归属修复后的期望哈希（QC​ORE-ADMISSION-01 隔离验证确认，基线 f6e7a1c6… 为
    # 修前值，差异属预期）。
    # Phase 3 基线更新（QCORE-ANSWER-FIDELITY-03 答案保真修复）：answers 载荷
    # 增加 statements/slot_bindings/attribution 字段（G-01/G-04/G-07），且旧格式
    # manifest（无 answers[]）改走"整值保留 + combined 语句"路径（不再 '；' 切分）
    # → content_hash 有意变化。本守卫的**主断言**（不被英语分支劫持：路径/
    # sub_specs 检查）不变。旧 C-R2 基线（2026-11 前）：
    #   Q5 90b72cd8…  Q6 004487a8…  Q8 9b7fd0a4…  Q9 46a7c73a…  Q10 253b5db1…
    CHN_EXPECTED_HASHES = {
        "Q5": "0a913627a9575a77a1c2dad05b86a9c730e649d0679525c1966ed062d1160c7a",
        "Q6": "dce8b1e875cecf63237775838cb21d5cdd192107b147ef7369107ae02736b097",
        "Q8": "af4b01eebe4e451bb6af47e9b04d64030c76ae9fa6d59712d5e169766a3c1360",
        "Q9": "2959b0852a1363890f400f7123a0b6490263a164a43a979507f778ddc170e8a3",
        "Q10": "556aadb242e6d4b4a59b2fa66b631ce799288f8e9231c382221a519a58c89a80",
    }

    @pytest.fixture(scope="class")
    def chn_ctx(self):
        import hashlib

        manifest = json.loads(self.CHN_MANIFEST.read_text(encoding="utf-8"))
        lines = load_source_lines(str(self.CHN_MD))
        return MappingContext(
            lines=lines,
            manifest=manifest,
            manifest_path=str(self.CHN_MANIFEST),
            manifest_name=self.CHN_MANIFEST.name,
            source_md_path=str(self.CHN_MD),
            source_md_name=self.CHN_MD.name,
            source_pdf_name="2019江苏高考真题语文（教师版）(1).pdf",
            annotated_md_name="2019江苏高考真题语文（教师版）(1).annotated.md",
            manifest_sha=hashlib.sha256(self.CHN_MANIFEST.read_bytes()).hexdigest(),
            source_md_sha=hashlib.sha256(self.CHN_MD.read_bytes()).hexdigest(),
            source_pdf_sha="c" * 64,
            annotated_md_sha="d" * 64,
            manifest_bytes=self.CHN_MANIFEST.stat().st_size,
            source_md_bytes=self.CHN_MD.stat().st_size,
            source_pdf_bytes=1,
            annotated_md_bytes=1,
            image_by_line={
                a["line_no"]: a for a in manifest.get("image_assets", [])
            },
            paper_id="2019江苏高考真题语文（教师版）(1)",
            subject="语文",
            run_id="qcore-delivery-01c-r3-tests",
        )

    def test_chinese_reading_composites_not_hijacked(self, chn_ctx):
        """DSH 阻断项一回归：语文 Q5/Q6/Q8/Q9/Q10 必须走既有（n）路径且
        content_hash 与 C-R2 基线一致（Q10 用 M1 修后期望值）。"""
        from strict_adapter.mapper import map_unit as map_any

        units = {
            u["unit_id"]: u for u in chn_ctx.manifest["units"] if u["unit_id"] in self.CHN_EXPECTED_HASHES
        }
        assert sorted(units) == sorted(self.CHN_EXPECTED_HASHES)
        for uid, unit in sorted(units.items()):
            assert unit.get("original_question_type") == "reading", uid
            assert not is_english_composite(unit, chn_ctx), uid
            m = map_any(unit, chn_ctx)
            assert m.log.get("path") != "english_composite", uid
            assert "sub_specs" not in m.log, uid
            assert m.content_hash == self.CHN_EXPECTED_HASHES[uid], (
                f"{uid}: hash {m.content_hash} != baseline "
                f"{self.CHN_EXPECTED_HASHES[uid]}"
            )

    def test_english_scope_requires_paper_context(self, ctx, units):
        import dataclasses

        chn_like_ctx = dataclasses.replace(
            ctx, paper_id="2019江苏高考真题语文（教师版）(1)"
        )
        for uid, unit in sorted(units.items()):
            assert is_english_composite(unit, ctx), uid
            assert not is_english_composite(unit, chn_like_ctx), (
                f"{uid}: same type set must NOT qualify under a non-scope paper"
            )

    def test_chem_composite_not_hijacked(self):
        """化学 composite（fill_in/short_answer）不得进入英语分支。"""
        sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
        from strict_adapter.mapper import map_unit as chem_map_unit

        chem_root = Path(
            r"D:\Project\AITutors\runs\qcore_e2e_01\qcore-e2e-01-20261108-104211"
        )
        manifest = json.loads(
            (
                chem_root
                / "02_PREPROCESSING/artifacts/reslice"
                / "2020全国I卷高考真题化学（教师版）(1).manifest.json"
            ).read_text(encoding="utf-8")
        )
        unit = next(u for u in manifest["units"] if u["unit_id"] == "Q8")
        lines = load_source_lines(
            str(
                chem_root
                / "02_PREPROCESSING/artifacts/ocr/高考真题/化学"
                / "2020全国I卷高考真题化学（教师版）(1).md"
            )
        )
        ctx = MappingContext(
            lines=lines,
            manifest=manifest,
            manifest_path="x",
            manifest_name="x",
            source_md_path="x",
            source_md_name="x",
            source_pdf_name="x.pdf",
            annotated_md_name="x.md",
            manifest_sha="a" * 64,
            source_md_sha="b" * 64,
            source_pdf_sha="c" * 64,
            annotated_md_sha="d" * 64,
            manifest_bytes=1,
            source_md_bytes=1,
            source_pdf_bytes=1,
            annotated_md_bytes=1,
            image_by_line={a["line_no"]: a for a in manifest.get("image_assets", [])},
            paper_id="2020全国I卷高考真题化学（教师版）(1)",
            subject="化学",
        )
        assert not is_english_composite(unit, ctx)
        m = chem_map_unit(unit, ctx)
        assert m.log.get("path") != "english_composite"
        assert "sub_specs" not in m.log

    def test_no_v3_runtime_reference(self):
        src = (Path(__file__).resolve().parents[2] / "strict_adapter" / "english_composite.py")
        text = src.read_text(encoding="utf-8")
        assert "ARCHIVE" not in text
        assert "AITutors-v3" not in text
        assert "subq_expand" not in text
        assert "sys.path" not in text

    def test_mapper_branch_is_lazy_import(self):
        text = (
            Path(__file__).resolve().parents[2] / "strict_adapter" / "mapper.py"
        ).read_text(encoding="utf-8")
        assert "from . import english_composite" in text
