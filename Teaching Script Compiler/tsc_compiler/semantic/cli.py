"""CLI for Semantic Retrieval V1: export / build / search / evaluate."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .embedding import DenseEmbedder
from .export import export_catalog, write_catalog
from .retrieval import SemanticConfig, SemanticIndex


def _load_catalog(path: Path) -> list[dict[str, Any]]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(raw, dict):
        return list(raw.get("entries") or [])
    return list(raw)


def cmd_export(args: argparse.Namespace) -> int:
    entries = export_catalog(args.database_url)
    out = write_catalog(entries, args.out)
    print(json.dumps({"entries": len(entries), "out": str(out)}, ensure_ascii=False))
    return 0


def cmd_build(args: argparse.Namespace) -> int:
    catalog = _load_catalog(Path(args.catalog))
    embedder = DenseEmbedder(args.model_path or None)
    index = SemanticIndex.from_catalog(catalog, embedder=embedder)
    meta = index.save(args.out)
    print(json.dumps(meta, ensure_ascii=False, indent=2))
    return 0


def cmd_search(args: argparse.Namespace) -> int:
    embedder = DenseEmbedder(args.model_path or None)
    index = SemanticIndex.load(args.index, embedder=embedder)
    result = index.search(args.query, top_k=args.top_k)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def _relation_of(result: dict[str, Any], expected_ids: set[str], expected_relation: str) -> str:
    if result["decision"] == "exact":
        exact = result.get("exact") or {}
        if expected_relation == "exact" and exact.get("question_id") in expected_ids:
            return "exact"
        return "false_exact"
    if result["decision"] == "similar":
        ids = {c.get("question_id") for c in result.get("similar") or []}
        return "similar" if ids & expected_ids else "false_similar"
    return "unknown"


def cmd_evaluate(args: argparse.Namespace) -> int:
    embedder = DenseEmbedder(args.model_path or None)
    overrides = {}
    if args.exact_dense is not None:
        overrides["exact_dense"] = args.exact_dense
    if args.exact_lexical is not None:
        overrides["exact_lexical"] = args.exact_lexical
    if args.exact_margin is not None:
        overrides["exact_margin"] = args.exact_margin
    if args.similar_dense is not None:
        overrides["similar_dense"] = args.similar_dense
    if args.similar_lexical is not None:
        overrides["similar_lexical"] = args.similar_lexical
    index = SemanticIndex.load(
        args.index, config=SemanticConfig(**overrides), embedder=embedder
    )
    rows = [
        json.loads(line)
        for line in Path(args.queries).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    per_query = []
    for row in rows:
        result = index.search(
            row["text"],
            top_k=args.top_k,
            exclude_ids=set(row.get("exclude_question_ids") or []),
        )
        expected = set(row.get("expected_question_ids") or [])
        predicted = _relation_of(result, expected, str(row.get("expected_relation") or ""))
        per_query.append(
            {
                "query_id": row.get("query_id"),
                "expected_relation": row.get("expected_relation"),
                "predicted": predicted,
                "decision": result["decision"],
                "top1": (result.get("candidates") or [{}])[0],
                "expected_ids": sorted(expected),
                "top_k_ids": [c["question_id"] for c in result.get("candidates") or []],
                "top1_margin": result.get("top1_margin"),
            }
        )

    def rate(pred: str, expected: str) -> dict[str, float]:
        subset = [r for r in per_query if r["expected_relation"] == expected]
        if not subset:
            return {"n": 0, "recall": 0.0}
        hit = sum(1 for r in subset if r["predicted"] == pred)
        return {"n": len(subset), "recall": round(hit / len(subset), 4)}

    predicted_exact = [r for r in per_query if r["predicted"] == "exact"]
    predicted_similar = [r for r in per_query if r["predicted"] == "similar"]
    exact_precision = (
        sum(1 for r in predicted_exact if r["expected_relation"] == "exact") / len(predicted_exact)
        if predicted_exact
        else 0.0
    )
    similar_precision = (
        sum(1 for r in predicted_similar if r["expected_relation"] == "similar") / len(predicted_similar)
        if predicted_similar
        else 0.0
    )
    report = {
        "queries": len(per_query),
        "thresholds": index.config.as_dict(),
        "dense_enabled": embedder.available,
        "accuracy": round(
            sum(1 for r in per_query if r["predicted"] == r["expected_relation"]) / max(1, len(per_query)),
            4,
        ),
        "exact_recall": rate("exact", "exact"),
        "similar_recall": rate("similar", "similar"),
        "unknown_recall": rate("unknown", "unknown"),
        "exact_precision": round(exact_precision, 4),
        "similar_precision": round(similar_precision, 4),
        "false_exact": [
            {"query_id": r["query_id"], "top1": r["top1"].get("question_id")}
            for r in per_query
            if r["predicted"] == "false_exact"
        ],
        "per_query": per_query,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "per_query"}, ensure_ascii=False, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m tsc_compiler.semantic.cli")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("export", help="read-only QCore -> catalog JSON (includes unpublished)")
    p.add_argument("--out", required=True)
    p.add_argument("--database-url", default=None)
    p.set_defaults(func=cmd_export)

    p = sub.add_parser("build", help="build dense+lexical index")
    p.add_argument("--catalog", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--model-path", default=None)
    p.set_defaults(func=cmd_build)

    p = sub.add_parser("search", help="search one query")
    p.add_argument("--index", required=True)
    p.add_argument("--query", required=True)
    p.add_argument("--top-k", type=int, default=10)
    p.add_argument("--model-path", default=None)
    p.set_defaults(func=cmd_search)

    p = sub.add_parser("evaluate", help="evaluate against a labelled JSONL set")
    p.add_argument("--index", required=True)
    p.add_argument("--queries", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--top-k", type=int, default=10)
    p.add_argument("--model-path", default=None)
    p.add_argument("--exact-dense", type=float, default=None)
    p.add_argument("--exact-lexical", type=float, default=None)
    p.add_argument("--exact-margin", type=float, default=None)
    p.add_argument("--similar-dense", type=float, default=None)
    p.add_argument("--similar-lexical", type=float, default=None)
    p.set_defaults(func=cmd_evaluate)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
