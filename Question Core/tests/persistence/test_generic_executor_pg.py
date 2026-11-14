# -*- coding: utf-8 -*-
"""Generic execution entry × real PostgreSQL: persistence + idempotency.

Located outside tests/persistence/integration/ so it does NOT inherit that
conftest's single-DB coupling.  This suite owns its connection explicitly:

* env ``QCORE_GE01_TEST_DATABASE_URL`` — required, fails loudly when unset;
* target is the DEDICATED test database ``qcore_ge01_test`` (DSH Phase-2 F-2:
  outside every forbidden prefix, so the entry's DB guard stays FULLY ON);
* safety.verify_test_target runs with a FIXED expected database name
  (no self-certifying derivation from the connection string).

Idempotency and readback cases seed their own writes AND run over an
INDEPENDENT per-call paper identity (Owner Phase-2 residual #1): the
idempotency key derives from `paper_id/unit_id`, so each test call owns
a fresh idem-key space.  The first run therefore really writes and the
repeat run really hits the duplicate path on EVERY pytest invocation -
including repeated runs against the same persistent test database - so
the DB re-read assertions after the repeat run are never vacuous.
"""

from __future__ import annotations

import os
import sys
from dataclasses import replace
from pathlib import Path
from uuid import UUID, uuid4

import pytest

_QCORE_ROOT = Path(__file__).resolve().parents[2]
if str(_QCORE_ROOT) not in sys.path:
    sys.path.insert(0, str(_QCORE_ROOT))

from strict_adapter import ADAPTER_VERSION  # noqa: E402
from strict_adapter.generic_executor import (  # noqa: E402
    DEFAULT_FORBIDDEN_DBS,
    FORBIDDEN_DB_PREFIXES,
    PaperInput,
    run_papers,
    validate_target_db_name,
)
from question_core.persistence import (  # noqa: E402
    DatabaseSettings,
    QuestionCoreRepository,
    create_db_engine,
    session_scope,
)
from tests.persistence.integration.safety import verify_test_target  # noqa: E402

pytestmark = pytest.mark.pg

EXPECTED_DB = "qcore_ge01_test"

E2E = _QCORE_ROOT.parent / "runs" / "qcore_e2e_01" / "qcore-e2e-01-20261108-104211"
CHEM_MD = E2E / "02_PREPROCESSING" / "artifacts" / "ocr" / "高考真题" / "化学" / "2020全国I卷高考真题化学（教师版）(1).md"
CHEM_MANIFEST = E2E / "02_PREPROCESSING" / "artifacts" / "reslice" / "2020全国I卷高考真题化学（教师版）(1).manifest.json"
CHEM_PDF = (
    _QCORE_ROOT.parent / "Preprocessing" / "maintainess" / "PDF" / "2020全国I卷高考真题化学（教师版）(1).pdf"
)

SEALED = pytest.mark.skipif(
    not (CHEM_MANIFEST.is_file() and CHEM_MD.is_file() and CHEM_PDF.is_file()),
    reason="sealed chem artifacts not found",
)


def _test_url() -> str:
    url = os.environ.get("QCORE_GE01_TEST_DATABASE_URL", "").strip()
    if not url:
        pytest.fail(
            "QCORE_GE01_TEST_DATABASE_URL is not set. This suite requires the "
            "dedicated test database qcore_ge01_test (explicit URL only)."
        )
    return url


@pytest.fixture(scope="module")
def ge01_url() -> str:
    url = _test_url()
    # 固定期望库名，禁止从连接串派生（避免自证）
    evidence = verify_test_target(url, expected_database=EXPECTED_DB)
    # verify_test_target already hard-fails (UnsafeTestTarget) on any
    # mismatch - including the fixed expected_database check.  This
    # assertion pins the returned evidence to that same expected value
    # (DSH Phase-2 residual #2: no always-true assert remains).
    assert evidence["database"] == EXPECTED_DB
    return url


@pytest.fixture(scope="module")
def chem_paper() -> PaperInput:
    return PaperInput(
        paper_id="2020全国I卷高考真题化学（教师版）(1)",
        subject="化学",
        manifest_path=CHEM_MANIFEST,
        source_md_path=CHEM_MD,
        source_pdf_path=CHEM_PDF,
        annotated_md_path=None,
    )


def _run(ge01_url: str, paper: PaperInput, out_dir: Path, run_id: str) -> dict:
    """Run the entry with the DB guard FULLY ON (default forbidden sets)."""
    assert validate_target_db_name(EXPECTED_DB)["pass"], "guard must accept the dedicated test db"
    os.environ["QCORE_DATABASE_URL"] = ge01_url
    return run_papers(
        [paper],
        EXPECTED_DB,
        out_dir,
        run_id,
        dry_run=False,
        # 守卫全开：默认禁写集 + 默认禁写前缀（qcore_ge01_test 不在其中）
        forbidden=DEFAULT_FORBIDDEN_DBS,
        forbidden_prefixes=FORBIDDEN_DB_PREFIXES,
    )


def _independent_paper(base: PaperInput) -> PaperInput:
    """Independent test data (Owner Phase-2 residual #1).

    derive_idempotency_key hashes "{paper_id}/{unit_id}" into the key,
    so a unique per-call paper_id gives this test call its own idem-key
    space: the first run always writes for real, the repeat run always
    exercises the duplicate path.  Scope note: the sealed owner
    overrides (rules.OWNER_ATTRIBUTION_OVERRIDES) are keyed by the
    original "{paper_id}/{unit_id}" and do not hit under the variant
    identity; this suite validates entry mechanics (write / idempotency /
    readback), not the sealed attribution adjudication.
    """
    return replace(base, paper_id=f"{base.paper_id}::ge01pg::{uuid4().hex[:8]}")


@SEALED
class TestGuardActuallyOn:
    def test_guard_rejects_protected_databases(self):
        for name in ("aitutors", "qcore_student_integration_01", "qcore_answer_fidelity_03_pgtest"):
            assert validate_target_db_name(name)["pass"] is False
        assert validate_target_db_name(EXPECTED_DB)["pass"] is True

    def test_rejected_target_stops_before_any_write(self, tmp_path, ge01_url, chem_paper):
        os.environ["QCORE_DATABASE_URL"] = ge01_url
        with pytest.raises(Exception, match="rejected"):
            run_papers(
                [chem_paper], "qcore_student_integration_01",
                tmp_path / "out", "guard-stop", dry_run=False,
                forbidden=DEFAULT_FORBIDDEN_DBS, forbidden_prefixes=FORBIDDEN_DB_PREFIXES,
            )


@SEALED
class TestPersistenceAndIdempotency:
    def test_persist_and_readback(self, tmp_path, ge01_url, chem_paper):
        """Owner five-step behavior: write -> idempotent re-run -> DB re-read.

        1. deterministic input (sealed chem artifacts + independent identity)
        2. first execution writes for real (fresh idem-key space)
        3. second execution is recognised as idempotent (zero new rows)
        4. the expected Questions stay readable from the DB across the
           repeat run - re-read through the repository below
        5. assertions cover actual counts and content, not just "no error"
        """
        paper = _independent_paper(chem_paper)
        # ---- (2) first execution: real write ----
        s1 = _run(ge01_url, paper, tmp_path / "run1", "ge-pg-persist")
        t1 = s1["totals"]
        assert t1["map_failed"] == 0, s1["papers"]
        assert t1["persist_rolled_back"] == 0, s1["papers"]
        assert t1["persist_committed"] == t1["admitted"] > 0, (
            "first run over a fresh idem-key space must commit every "
            "admitted unit"
        )
        rb1 = s1.get("readback", {}).get("units", [])
        assert len(rb1) == t1["persist_committed"], (
            "readback must cover every committed unit of this execution"
        )
        expected: dict[str, str] = {}
        for pr in s1["papers"]:
            for u in pr.get("units", []):
                if u.get("admitted"):
                    expected[u["question_id"]] = u["content_hash"]
        assert set(expected) == {u["question_id"] for u in rb1}
        for u in rb1:
            assert u["ok"], u
            assert u["revision_count"] == 1, u
            assert u["instance_count"] == 1, u
            assert u["instance_source_document_id"] == [paper.paper_id], u
        # ---- (3) second execution: idempotent, zero new rows ----
        s2 = _run(ge01_url, paper, tmp_path / "run2", "ge-pg-idem")
        t2 = s2["totals"]
        assert t2["persist_rolled_back"] == 0, s2["papers"]
        assert t2["persist_committed"] == 0, "idempotent re-run must not insert"
        assert t2["persist_skipped_duplicate"] == t2["admitted"] == t1["admitted"]
        for pr in s2["papers"]:
            for u in pr.get("units", []):
                if u.get("admitted"):
                    assert u["persist"] == "skipped_duplicate", u
                    assert u.get("existing_candidate_id"), u
        # ---- (4)(5) after the repeat run the SAME expected Questions are
        # still readable in full (counts + content) ----
        engine = create_db_engine(DatabaseSettings(url=ge01_url, dbname=EXPECTED_DB))
        try:
            with session_scope(engine) as session:
                repo = QuestionCoreRepository(session)
                reread = 0
                for qid_s, content_hash in expected.items():
                    agg = repo.get_question_aggregate(UUID(qid_s))
                    assert len(agg.revisions) == 1, qid_s
                    assert len(agg.instances) == 1, qid_s
                    assert agg.revisions[0].content_hash == content_hash, qid_s
                    assert (
                        str(agg.instances[0].source_document_id) == paper.paper_id
                    ), qid_s
                    reread += 1
                assert reread == t2["admitted"] > 0
        finally:
            engine.dispose()

    def test_second_run_zero_new_rows(self, tmp_path, ge01_url, chem_paper):
        # F-3 自含播种 + Owner Phase-2 residual #1：独立 paper 身份使播种跑
        # 在每次 pytest 会话都是真实写入，零新行断言不再依赖执行历史。
        paper = _independent_paper(chem_paper)
        self_seed = _run(ge01_url, paper, tmp_path / "seed", "ge-pg-seed")
        st = self_seed["totals"]
        assert st["persist_rolled_back"] == 0, self_seed["papers"]
        assert st["persist_committed"] == st["admitted"] > 0, (
            "seed run must really write (fresh idem-key space), otherwise "
            "the zero-new-rows assertion below would be vacuous"
        )
        s2 = _run(ge01_url, paper, tmp_path / "run2", "ge-pg-idem")
        t = s2["totals"]
        assert t["persist_rolled_back"] == 0, s2["papers"]
        assert t["persist_committed"] == 0, "idempotent re-run must not insert"
        assert t["persist_skipped_duplicate"] == t["admitted"] > 0

    def test_entry_declares_package_adapter_version(self):
        assert ADAPTER_VERSION == "strict-adapter/0.2.0"

    def test_per_paper_outputs_written(self, tmp_path, ge01_url, chem_paper):
        out = tmp_path / "outs"
        _run(ge01_url, chem_paper, out, "ge-pg-outputs")
        paper_dir = next((out / "papers").iterdir())
        for fname in ("mapping.json", "admission.json", "persistence.json", "readback.json"):
            assert (paper_dir / fname).is_file(), fname
        assert (out / "run_summary.json").is_file()
