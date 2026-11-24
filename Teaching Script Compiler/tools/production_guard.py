# -*- coding: utf-8 -*-
"""Production zero-change guard.

Reads the production Question Core database through a READ ONLY transaction and
emits counts plus a SHA-256 digest of every content-bearing table. Run it before
and after the pilot; equal digests prove no Question/Revision/Answer/History row
was changed.

    python -X utf8 tools/production_guard.py --out data/reports/guard_before.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from tsc_compiler.config import load_settings  # noqa: E402

TABLES = [
    ("qcore_questions", ["question_id", "identity_fingerprint"]),
    ("qcore_question_instances", None),
    ("qcore_revisions", None),
    ("qcore_state_history", None),
    ("qcore_answer_rows", None),
    ("qcore_asset_refs", None),
    ("qcore_evidence_records", None),
    ("qcore_evidence_conflicts", None),
    ("qcore_material_refs", None),
]


def table_columns(session, table: str) -> list[str]:
    rows = session.execute(
        text(
            "select column_name from information_schema.columns "
            "where table_schema='public' and table_name=:t order by ordinal_position"
        ),
        {"t": table},
    )
    return [r[0] for r in rows]


def digest_rows(session, table: str) -> tuple[int, str]:
    columns = table_columns(session, table)
    order = "question_id" if "question_id" in columns else columns[0]
    if table == "qcore_state_history":
        order = "question_id, position"
    if table == "qcore_answer_rows":
        order = "revision_id, position"
    select = ", ".join(columns)
    query = f"select {select} from {table} order by {order}"
    hasher = hashlib.sha256()
    count = 0
    for row in session.execute(text(query)):
        payload = {}
        for name, value in zip(columns, row):
            if hasattr(value, "isoformat"):
                value = value.isoformat()
            payload[name] = value
        hasher.update(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
        )
        hasher.update(b"\n")
        count += 1
    return count, hasher.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    settings = load_settings()
    if not settings.qcore_database_url:
        raise SystemExit("QCORE_DATABASE_URL missing")
    engine = create_engine(
        settings.qcore_database_url,
        connect_args={"options": "-c default_transaction_read_only=on"},
        future=True,
    )
    session_factory = sessionmaker(bind=engine, future=True)
    report = {"database": engine.url.database, "tables": {}}
    with session_factory() as session:
        read_only = session.execute(text("show transaction_read_only")).scalar()
        report["transaction_read_only"] = str(read_only)
        for table, _ in TABLES:
            count, digest = digest_rows(session, table)
            report["tables"][table] = {"rows": count, "sha256": digest}
        latest = session.execute(
            text(
                "with latest as (select distinct on (question_id) question_id, snapshot "
                "from qcore_state_history order by question_id, position desc) "
                "select snapshot->>'publication', count(*) from latest group by 1 order by 2 desc"
            )
        ).all()
        report["publication_states"] = {str(k): int(v) for k, v in latest}
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: v["rows"] for k, v in report["tables"].items()}, ensure_ascii=False))
    print(json.dumps(report["publication_states"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
