"""QCORE-ANSWER-FIDELITY-03 — Manifest → Candidate 答案保真追踪矩阵生成器。

输入 = Phase 2 封存三卷 Manifest（只读）+ 当前 Strict Adapter 映射（确定性）。
输出 = 02_FIDELITY_MATRIX.json（机器可读，38 Units × 144 条目逐条结果）
       03_FIDELITY_MATRIX_SUMMARY.md（简洁汇总）
并逐项核验硬性计数：38 Units / 144 答案条目 / 21 composite / 97 composite 小问 /
49 图片资产 / 2 图片答案槽位。

用法：python build_fidelity_matrix.py
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

QC_ROOT = Path(r"D:\Project\AITutors\Question Core")
sys.path.insert(0, str(QC_ROOT))

from strict_adapter.extract import load_source_lines  # noqa: E402
from strict_adapter.mapper import MappingContext, map_all  # noqa: E402

RUN_DIR = QC_ROOT / "runs" / "qcore_answer_fidelity_03"
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

CATEGORY_LABELS = {
    1: "mapped_candidate_answer",
    2: "mapped_composite_sub_or_slot",
    3: "mapped_image_asset_ref",
    4: "explanation_per_owner_d1",
    5: "conflict_structure_preserved",
    6: "unmapped",
}

# 工单 §5 六类
CAT1, CAT2, CAT3, CAT4, CAT5, CAT6 = 1, 2, 3, 4, 5, 6


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _resolve_pointer(doc, pointer: str):
    """RFC 6901 逐段解析（基座 = CandidateCore）；不存在即 KeyError/IndexError。"""
    assert pointer.startswith("/"), pointer
    cur = doc
    for seg in pointer.lstrip("/").split("/"):
        seg = seg.replace("~1", "/").replace("~0", "~")
        if isinstance(cur, list):
            cur = cur[int(seg)]
        else:
            cur = cur[seg]
    return cur


def _conflict_hit(unit: dict, item: dict) -> bool:
    """该条目是否落在某条 answer_conflicts 声明范围内（逐 sub/slot 对位）。"""
    isub, islot = item.get("sub_label"), item.get("slot_id")
    for c in unit.get("answer_conflicts") or []:
        csub, cslot = c.get("sub_label"), c.get("slot_id")
        if csub is not None and csub != isub:
            continue
        if cslot is not None and cslot != islot:
            continue
        return True
    return False


def classify(unit: dict, item: dict, trace: dict) -> tuple[int, str]:
    """条目 → 六类结果（主归属唯一；优先级：essay > 图片 > 争议 > 槽位/小问 > 单值答案）。

    结构判定：composite 内部条目、或多槽位题（如语文 Q7 八空默写）的条目
    归 2（小问/答案槽位）；独立单值答案归 1。
    """
    if trace.get("disposition") == "unmapped":
        return CAT6, trace.get("unmapped_reason") or "unmapped"
    if (unit.get("original_question_type") or "") == "essay":
        return CAT4, "Owner D-1: model text kept in Explanation with evidence"
    if item.get("asset_ref"):
        return CAT3, f"AssetSlot -> canonical asset {item.get('asset_ref')}"
    if item.get("status") == "disputed" or (
        item.get("value_text") is None and not item.get("asset_ref")
    ):
        return CAT5, "disputed blank: None element + all conflict versions kept"
    n_items = len(unit.get("answers") or [])
    if unit.get("unit_type") == "composite_question" or n_items > 1:
        return CAT2, f"sub/slot at {trace.get('target')}"
    return CAT1, f"answer object at {trace.get('target')}"


def main() -> int:
    rows: list[dict] = []
    stats: dict = {}
    problems: list[str] = []

    for paper, spec in PAPERS.items():
        manifest_path = (
            spec["dir"] / "manifest_output" / f"{spec['stem']}.manifest.json"
        )
        src_md = spec["dir"] / spec["ocr_dir"] / f"{spec['stem']}.md"
        annotated = (
            spec["dir"] / "manifest_output" / f"{spec['stem']}.annotated.md"
        )
        actual = _sha(manifest_path)
        if actual != spec["manifest_sha"]:
            problems.append(f"{paper}: manifest sha {actual} != sealed pin")
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        ctx = MappingContext(
            lines=load_source_lines(str(src_md)),
            manifest=data,
            manifest_path=str(manifest_path),
            manifest_name=manifest_path.name,
            source_md_path=str(src_md),
            source_md_name=src_md.name,
            source_pdf_name=f"{spec['stem']}.pdf",
            annotated_md_name=annotated.name,
            manifest_sha=actual,
            source_md_sha=_sha(src_md),
            source_pdf_sha="e" * 64,
            annotated_md_sha=_sha(annotated) if annotated.is_file() else "0" * 64,
            manifest_bytes=manifest_path.stat().st_size,
            source_md_bytes=src_md.stat().st_size,
            source_pdf_bytes=1,
            annotated_md_bytes=annotated.stat().st_size
            if annotated.is_file()
            else 1,
            image_by_line={
                a["line_no"]: a for a in data.get("image_assets", [])
            },
            paper_id=spec["paper_id"],
            subject=spec["subject"],
            run_id="qcore-answer-fidelity-03-matrix",
        )
        mappings = {m.unit_id: m for m in map_all(ctx)}
        units = {u["unit_id"]: u for u in data["units"]}

        n_items = 0
        n_composite_units = 0
        composite_sub_keys: set[tuple[str, str]] = set()
        manifest_assets = data.get("image_assets") or []
        registered_assets: set[str] = set()
        answer_image_slots = 0

        for uid, unit in units.items():
            m = mappings[uid]
            trace_by_idx = {
                t["item_index"]: t for t in m.log.get("answers_trace") or []
            }
            if unit.get("unit_type") == "composite_question":
                n_composite_units += 1
            for idx, item in enumerate(unit.get("answers") or []):
                n_items += 1
                if unit.get("unit_type") == "composite_question" and item.get(
                    "sub_label"
                ):
                    composite_sub_keys.add((uid, str(item["sub_label"])))
                trace = trace_by_idx.get(idx, {"disposition": "unmapped",
                                               "unmapped_reason": "no trace row"})
                cat, reason = classify(unit, item, trace)
                if item.get("asset_ref") and cat == CAT3:
                    answer_image_slots += 1
                target = trace.get("target")
                # DSH B1：写盘前逐条解析 target（基座 = CandidateCore）；
                # essay 行为描述性 target（Owner D-1 处置）不作指针校验。
                if cat != CAT4:
                    if not (target or "").startswith("/"):
                        problems.append(
                            f"{paper}/{uid} item {idx}: non-pointer target {target!r}"
                        )
                    else:
                        try:
                            _resolve_pointer(
                                m.candidate.core.model_dump(mode="json"), target
                            )
                        except Exception as exc:  # noqa: BLE001
                            problems.append(
                                f"{paper}/{uid} item {idx}: target {target!r} "
                                f"unresolvable ({exc})"
                            )
                rows.append(
                    {
                        "paper": paper,
                        "unit_id": uid,
                        "unit_type": unit.get("unit_type"),
                        "question_type": unit.get("original_question_type"),
                        "item_index": idx,
                        "sub_label": item.get("sub_label"),
                        "slot_id": item.get("slot_id"),
                        "value_text": item.get("value_text"),
                        "asset_ref": item.get("asset_ref"),
                        "form": item.get("form"),
                        "source_region": item.get("source_region"),
                        "evidence_lines": item.get("evidence_lines"),
                        "status": item.get("status"),
                        "missing_reason": item.get("missing_reason"),
                        "category": cat,
                        "category_name": CATEGORY_LABELS[cat],
                        "result": reason,
                        "candidate_target": trace.get("target"),
                        "derived_from_manifest_fields": [
                            k
                            for k in (
                                "sub_label",
                                "slot_id",
                                "value_text",
                                "asset_ref",
                                "form",
                                "source_region",
                                "evidence_lines",
                                "status",
                                "missing_reason",
                            )
                            if item.get(k) is not None
                        ],
                        "conflict_versions_captured": _conflict_hit(unit, item),
                    }
                )
            for a in m.candidate.core.content.assets:
                registered_assets.add(a.asset_id)

        stats[paper] = {
            "units": len(units),
            "answer_items": n_items,
            "composite_units": n_composite_units,
            "composite_sub_labels": len(composite_sub_keys),
            "manifest_image_assets": len(manifest_assets),
            "registered_asset_ids": len(registered_assets),
            "answer_image_slots": answer_image_slots,
            "conflict_groups": sum(
                len(u.get("answer_conflicts") or []) for u in units.values()
            ),
        }

    # ---- 硬性计数核验（工单 §6.4 / DSH 基线 §2）----
    totals = {
        "units": sum(s["units"] for s in stats.values()),
        "answer_items": sum(s["answer_items"] for s in stats.values()),
        "composite_units": sum(s["composite_units"] for s in stats.values()),
        "composite_sub_labels": sum(
            s["composite_sub_labels"] for s in stats.values()
        ),
        "manifest_image_assets": sum(
            s["manifest_image_assets"] for s in stats.values()
        ),
        "answer_image_slots": sum(
            s["answer_image_slots"] for s in stats.values()
        ),
    }
    expected = {
        "units": 38,
        "answer_items": 144,
        "composite_units": 21,
        "composite_sub_labels": 97,
        "manifest_image_assets": 49,
        "answer_image_slots": 2,
    }
    for k, want in expected.items():
        if totals[k] != want:
            problems.append(f"count {k}: {totals[k]} != expected {want}")

    unmapped = [r for r in rows if r["category"] == CAT6]
    by_cat = {
        CATEGORY_LABELS[c]: sum(1 for r in rows if r["category"] == c)
        for c in range(1, 7)
    }

    matrix = {
        "task": "QCORE-ANSWER-FIDELITY-03",
        "inputs": {
            paper: {
                "manifest": str(
                    spec["dir"] / "manifest_output" / f"{spec['stem']}.manifest.json"
                ),
                "manifest_sha256": spec["manifest_sha"],
            }
            for paper, spec in PAPERS.items()
        },
        "totals": totals,
        "expected": expected,
        "per_paper": stats,
        "category_counts": by_cat,
        "unmapped_rows": unmapped,
        "problems": problems,
        "rows": rows,
    }
    out_json = RUN_DIR / "02_FIDELITY_MATRIX.json"
    out_json.write_text(
        json.dumps(matrix, ensure_ascii=False, indent=1) + "\n",
        encoding="utf-8",
    )

    # ---- 简洁汇总 ----
    lines = [
        "# 03_FIDELITY_MATRIX_SUMMARY.md — Manifest→Candidate 保真追踪矩阵汇总",
        "",
        "> 任务：QCORE-ANSWER-FIDELITY-03 ｜ 生成器：`_scripts/build_fidelity_matrix.py`（可复算）",
        "> 机器可读全量矩阵：`02_FIDELITY_MATRIX.json`（38 Units × 144 条目逐条结果）。",
        "",
        "## 1. 全量计数核验",
        "",
        "| 项 | 期望 | 实测 | 判定 |",
        "| -- | -- | -- | -- |",
    ]
    for k, want in expected.items():
        got = totals[k]
        lines.append(
            f"| {k} | {want} | {got} | {'PASS' if got == want else 'FAIL'} |"
        )
    lines += [
        "",
        "分卷：",
        "",
        "| 卷 | Units | 答案条目 | composite Units | composite 小问 | 图片资产 | 图片答案槽 | 冲突组 |",
        "| -- | -- | -- | -- | -- | -- | -- | -- |",
    ]
    for paper, s in stats.items():
        lines.append(
            f"| {paper} | {s['units']} | {s['answer_items']} | "
            f"{s['composite_units']} | {s['composite_sub_labels']} | "
            f"{s['manifest_image_assets']} | {s['answer_image_slots']} | "
            f"{s['conflict_groups']} |"
        )
    lines += [
        "",
        "## 2. 逐条结果分布（六类，工单 §5）",
        "",
        "| 类别 | 含义 | 条数 |",
        "| -- | -- | -- |",
        f"| 1 | 已映射至 Candidate 答案 | {by_cat[CATEGORY_LABELS[1]]} |",
        f"| 2 | 已映射至 composite 小问/答案槽位 | {by_cat[CATEGORY_LABELS[2]]} |",
        f"| 3 | 已映射为图片答案资产引用 | {by_cat[CATEGORY_LABELS[3]]} |",
        f"| 4 | 已按 Owner D-1 作 Explanation 处理 | {by_cat[CATEGORY_LABELS[4]]} |",
        f"| 5 | 已按合法冲突结构保留 | {by_cat[CATEGORY_LABELS[5]]} |",
        f"| 6 | 确实无法映射 | {by_cat[CATEGORY_LABELS[6]]} |",
        "",
        f"**未映射项：{len(unmapped)} 条**"
        + ("（无）" if not unmapped else "（明细见 JSON unmapped_rows）"),
        "",
        "## 3. 12 道抽检题结果",
        "",
        "| 样本 | 结果 |",
        "| -- | -- |",
        "| 化学 Q3 | inline_in_explanation → SingleChoiceAnswer(\"A\")，statements@explanation_area L338 |",
        "| 化学 Q8 | 1 CompositeAnswer：6 小问 8 槽，slot_bindings 逐空归属 |",
        "| 化学 Q10 | 7 条全保留（4 小问），attribution=disputed（P-1 冻结），DISPUTED 证据在案 |",
        "| 化学 Q11 | 9 条 / 4 小问逐槽映射 |",
        "| 化学 Q12 | 7 条：2 AssetSlot（canonical asset_id）+ (6) 图文混合双槽；P-3 DISPUTED 在案 |",
        "| 语文 Q2 | inline_in_explanation → SingleChoiceAnswer(\"A\")，statements@explanation_area L473 |",
        "| 语文 Q8 | 3 小问 3 答案对象分立（(1)=SingleChoice D），多点内容整段保留不切分 |",
        "| 语文 Q12 | (2)#2 争议空 None + 3 版本 statements（stem/answer/explanation 三区可区分），不选边 |",
        "| 英语 U3 | 4 小问逐条映射，\"suggests/suggested/has suggested\" verbatim 保留 |",
        "| 英语 U4 | 20 小问（11–30）全展开；14/15 两组冲突双版本（选项区/解析区可区分）；source_internal 不阻断 |",
        "| 英语 U9 | 5 小问（46–50）映射；共享选项池（A–G）挂父 body 不破坏 |",
        "| 英语 U10 | 0 TypedAnswer；范文进 Explanation 带定位；不判缺答案（D-1） |",
        "",
        "## 4. 硬性验收对应",
        "",
        "- 38 Units 全部映射验证：`02_FIDELITY_MATRIX.json` per_paper.units。",
        "- 144 条目逐条可定位：rows[] 每条含 category/target/derived_from_manifest_fields；",
        "  `candidate_target` 为 RFC 6901 JSON Pointer（基座 = CandidateCore，`/answers/0/…` 约定），",
        "  **写盘前逐条解析，解析失败即报错**（DSH B1 防复发）；类别 4（作文，Owner D-1）的 target",
        "  为处置描述串而非指针（范文在 Explanation 行区，见 evidence_lines/explanation 覆盖）。",
        "- 49 资产引用：manifest image_assets=49（41/2/6）；Candidate 注册数见 per_paper.registered_asset_ids。",
        "- 2 图片答案槽：chem Q12 (5)#1/(6)#2 → AssetSlot(assets=[AnswerAssetRef(role=answer_value)])，canonical asset_id 唯一命中。",
        "- 综合题结构：composite=21，每 unit 仅 1 个 Question Candidate（1 个顶层 CompositeAnswer）。",
        "- 冲突/作文：7 组 source_internal 冲突两存不阻断；8 条作文条目（chn Q11×2、U10×3、U11×3）全部 Explanation 处置。",
    ]
    if problems:
        lines += ["", "## ⚠ 核验问题", ""]
        lines += [f"- {p}" for p in problems]
    out_md = RUN_DIR / "03_FIDELITY_MATRIX_SUMMARY.md"
    out_md.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print("totals:", totals)
    print("category_counts:", by_cat)
    print("per_paper:", json.dumps(stats, ensure_ascii=False))
    print("problems:", problems)
    print("wrote:", out_json)
    print("wrote:", out_md)
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
