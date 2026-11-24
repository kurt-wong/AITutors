"""Command line entry point (``python -m tsc_compiler.cli ...``)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .config import ensure_dirs, load_settings
from .qcore_source import build_snapshot, load_meta


def _print(payload) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=1))


def cmd_snapshot(_args: argparse.Namespace) -> int:
    settings = load_settings()
    meta = build_snapshot(settings)
    _print(meta)
    return 0


def cmd_compile(args: argparse.Namespace) -> int:
    from .service import compile_catalog

    settings = load_settings()
    ensure_dirs(settings)
    outcomes = compile_catalog(
        settings,
        question_ids=args.question_id or None,
        subject=None if args.all else (args.subject or "数学"),
        force=args.force,
        limit=args.limit,
    )
    payload = [o.to_dict() for o in outcomes]
    if args.out:
        from .service import write_json

        write_json(args.out, payload)
    summary = {
        "total": len(payload),
        "pass": sum(1 for o in payload if o["status"] == "pass"),
        "fail": sum(1 for o in payload if o["status"] != "pass"),
        "from_cache": sum(1 for o in payload if o["from_cache"]),
        "failures": [
            {k: o[k] for k in ("question_id", "code", "message")}
            for o in payload
            if o["status"] != "pass"
        ],
    }
    _print(summary)
    return 0 if summary["fail"] == 0 else 1


def cmd_report(args: argparse.Namespace) -> int:
    from .service import report_rows, write_json

    settings = load_settings()
    rows = report_rows(settings)
    rows.sort(
        key=lambda r: (
            str(r.get("source_document_id") or ""),
            r.get("printed_number") or "",
        )
    )
    if args.out:
        write_json(args.out, rows)
    _print(
        {
            "questions": len(rows),
            "with_script": sum(1 for r in rows if r["teaching_script"]),
            "pass": sum(1 for r in rows if r["validation"] == "pass"),
            "out": args.out,
        }
    )
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn

    from .api import create_app

    settings = load_settings()
    ensure_dirs(settings)
    app = create_app(settings)
    uvicorn.run(app, host=args.host, port=args.port, log_level=args.log_level)
    return 0


def cmd_meta(_args: argparse.Namespace) -> int:
    settings = load_settings()
    _print(load_meta(settings))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="tsc", description="Teaching Script Compiler")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("snapshot", help="read-only QCore snapshot").set_defaults(
        func=cmd_snapshot
    )

    compile_parser = sub.add_parser("compile", help="compile + validate scripts")
    compile_parser.add_argument("--subject", default="数学")
    compile_parser.add_argument(
        "--all", action="store_true", help="every published subject"
    )
    compile_parser.add_argument("--question-id", action="append", default=[])
    compile_parser.add_argument("--limit", type=int, default=None)
    compile_parser.add_argument("--force", action="store_true")
    compile_parser.add_argument("--out", default=None)
    compile_parser.set_defaults(func=cmd_compile)

    report_parser = sub.add_parser("report", help="per-question acceptance table")
    report_parser.add_argument("--out", default=None)
    report_parser.set_defaults(func=cmd_report)

    serve_parser = sub.add_parser("serve", help="HTTP API for search + bundles")
    serve_parser.add_argument("--host", default="127.0.0.1")
    serve_parser.add_argument("--port", type=int, default=8820)
    serve_parser.add_argument("--log-level", default="info")
    serve_parser.set_defaults(func=cmd_serve)

    sub.add_parser("meta", help="snapshot metadata").set_defaults(func=cmd_meta)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    Path(args.__dict__.get("out") or ".").parent.mkdir(parents=True, exist_ok=True)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
