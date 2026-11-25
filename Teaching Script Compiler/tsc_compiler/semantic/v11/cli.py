"""CLI for the isolated V1.1 candidate (does not touch V1 defaults)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .config import V11Config
from .index import V11Index
from .model import DEFAULT_BASE_URL, DEFAULT_MODEL, OllamaGemmaEmbedder
from .multi import MultiCandidateIndex


def _load_catalog(path: str) -> list[dict]:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    return raw["entries"] if isinstance(raw, dict) else raw


def cmd_identity(args: argparse.Namespace) -> int:
    adapter = OllamaGemmaEmbedder(args.model, base_url=args.base_url)
    print(json.dumps(adapter.identify().as_dict(), ensure_ascii=False, indent=2))
    return 0


def cmd_build(args: argparse.Namespace) -> int:
    adapter = OllamaGemmaEmbedder(args.model, base_url=args.base_url, max_chars=args.max_chars)
    catalog = _load_catalog(args.catalog)
    index = V11Index.build(catalog, adapter, args.out, namespace=args.namespace)
    print(json.dumps(index.identity_summary(), ensure_ascii=False, indent=2))
    return 0


def cmd_search(args: argparse.Namespace) -> int:
    adapter = OllamaGemmaEmbedder(args.model, base_url=args.base_url)
    index = V11Index.load(args.index, adapter, expected_config=V11Config())
    result = index.search(args.query, top_k=args.top_k)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    adapter = OllamaGemmaEmbedder(args.model, base_url=args.base_url)
    index = V11Index.load(args.index, adapter, expected_config=V11Config())
    print(json.dumps(index.identity_summary(), ensure_ascii=False, indent=2))
    print(json.dumps({"ok": True, "config_hash": V11Config().config_hash}, ensure_ascii=False))
    return 0


def cmd_multi(args: argparse.Namespace) -> int:
    adapter = OllamaGemmaEmbedder(args.model, base_url=args.base_url)
    index = V11Index.load(args.index, adapter, expected_config=V11Config())
    result = MultiCandidateIndex(index).search(args.query, per_segment=args.per_segment, whole_page=args.whole_page)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m tsc_compiler.semantic.v11.cli")
    sub = parser.add_subparsers(dest="command", required=True)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--model", default=DEFAULT_MODEL)
    common.add_argument("--base-url", default=DEFAULT_BASE_URL)

    p = sub.add_parser("identity", parents=[common])
    p.set_defaults(func=cmd_identity)

    p = sub.add_parser("build", parents=[common])
    p.add_argument("--catalog", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--namespace", default="semantic_v11_gemma2")
    p.add_argument("--max-chars", type=int, default=100_000)
    p.set_defaults(func=cmd_build)

    p = sub.add_parser("search", parents=[common])
    p.add_argument("--index", required=True)
    p.add_argument("--query", required=True)
    p.add_argument("--top-k", type=int, default=10)
    p.set_defaults(func=cmd_search)

    p = sub.add_parser("verify", parents=[common])
    p.add_argument("--index", required=True)
    p.set_defaults(func=cmd_verify)

    p = sub.add_parser("multi", parents=[common])
    p.add_argument("--index", required=True)
    p.add_argument("--query", required=True)
    p.add_argument("--per-segment", type=int, default=5)
    p.add_argument("--whole-page", type=int, default=10)
    p.set_defaults(func=cmd_multi)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
