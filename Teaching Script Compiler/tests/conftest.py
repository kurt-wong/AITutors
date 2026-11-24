# -*- coding: utf-8 -*-
"""Synthetic Question Core bundles — invented content only, no exam data."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tsc_compiler.config import Settings


def make_bundle(
    *,
    question_id: str = "11111111-1111-1111-1111-111111111111",
    revision_id: str = "22222222-2222-2222-2222-222222222222",
    revision_number: int = 1,
    question_type: str = "single_choice",
    stem: str = "1. 已知集合 $ M=\\{1,2\\} $，则 $ M\\cup\\{3\\}= $（ ）",
    options: list[tuple[str, str]] | None = None,
    answer_type: str = "single_choice",
    answer_value="A",
    answer_display="A",
    explanation: list[str] | None = None,
    assets: list[dict] | None = None,
) -> dict:
    options = options or [
        ("A", "$ \\{1,2,3\\} $"),
        ("B", "$ \\{1,2\\} $"),
        ("C", "$ \\{3\\} $"),
        ("D", "$ \\{1\\} $"),
    ]
    explanation = explanation or [
        "【分析】先求并集。",
        "【详解】$ M\\cup\\{3\\}=\\{1,2,3\\} $，故选 A．",
    ]
    bodies = [
        {
            "local_id": "u1",
            "question_type": question_type,
            "printed_number": "1",
            "stem_blocks": [
                {"kind": "text", "text": stem, "line_start": 10, "line_end": 10}
            ],
            "options": [
                {
                    "label": label,
                    "blocks": [
                        {"kind": "text", "text": text, "line_start": 12, "line_end": 12}
                    ],
                }
                for label, text in options
            ],
            "parent_question_ref": None,
            "sub_question_ids": [],
        }
    ]
    return {
        "question_id": question_id,
        "revision_id": revision_id,
        "revision_number": revision_number,
        "question_type": question_type,
        "content_hash": "a" * 64,
        "subject": "数学",
        "source_document_id": "synthetic-paper",
        "printed_number": "1",
        "section": "一、选择题",
        "content": {"bodies": bodies, "materials": [], "assets": assets or []},
        "answers": [
            {
                "answer_type": answer_type,
                "answer_value": answer_value,
                "answer_display": answer_display,
                "grading_rule": "exact",
                "completeness": "full",
                "attribution": "attributed",
                "statements": [
                    {
                        "statement_id": "u1-st1",
                        "value_text": str(answer_value),
                        "locators": [{"kind": "line_range", "line_start": 60, "line_end": 60}],
                    }
                ],
            }
        ],
        "explanation_blocks": [
            {"kind": "text", "text": text, "line_start": 50 + index * 2, "line_end": 50 + index * 2}
            for index, text in enumerate(explanation)
        ],
        "assets": assets or [],
    }


@pytest.fixture()
def settings(tmp_path: Path) -> Settings:
    data = tmp_path / "data"
    (data / "qcore" / "bundles").mkdir(parents=True)
    return Settings(
        data_dir=data,
        qcore_root=tmp_path,
        qcore_database_url="",
        asset_allowlist=tmp_path / "missing.json",
        llm_rerank=False,
        llm_api_key="",
        ocr_token="",
    )


def write_snapshot(settings: Settings, bundles: list[dict]) -> list[dict]:
    """Write catalog.json + bundles for API/search tests."""
    catalog = []
    for bundle in bundles:
        path = settings.data_dir / "qcore" / "bundles" / f"{bundle['question_id']}.json"
        path.write_text(json.dumps(bundle, ensure_ascii=False), encoding="utf-8")
        catalog.append(
            {
                "question_id": bundle["question_id"],
                "revision_id": bundle["revision_id"],
                "revision_number": bundle["revision_number"],
                "question_type": bundle["question_type"],
                "subject": bundle.get("subject"),
                "source_document_id": bundle.get("source_document_id"),
                "printed_number": bundle.get("printed_number"),
                "section": bundle.get("section"),
                "content_hash": bundle.get("content_hash"),
                "answer_display": bundle["answers"][0].get("answer_display"),
                "answer_count": 1,
                "answer_attribution": ["attributed"],
                "has_image": any(a.get("kind") == "image" for b in bundle["content"]["bodies"] for a in b["stem_blocks"]),
                "has_table": False,
                "has_math": True,
                "explanation_blocks": len(bundle["explanation_blocks"]),
                "stem_text": bundle["content"]["bodies"][0]["stem_blocks"][0]["text"],
                "material_text": "",
                "options_text": "\n".join(
                    block["text"]
                    for option in bundle["content"]["bodies"][0]["options"]
                    for block in option["blocks"]
                ),
                "explanation_text": "\n".join(b["text"] for b in bundle["explanation_blocks"]),
                "search_text": bundle["content"]["bodies"][0]["stem_blocks"][0]["text"],
                "asset_ids": [],
                "unresolved_assets": [],
                "published": True,
            }
        )
    (settings.data_dir / "qcore" / "catalog.json").write_text(
        json.dumps(catalog, ensure_ascii=False), encoding="utf-8"
    )
    (settings.data_dir / "qcore" / "meta.json").write_text(
        json.dumps({"counts": {"published_bundles": len(catalog)}}), encoding="utf-8"
    )
    return catalog
