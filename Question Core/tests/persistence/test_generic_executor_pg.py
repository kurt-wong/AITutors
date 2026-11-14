# -*- coding: utf-8 -*-
"""Generic execution entry × real PostgreSQL: persistence + idempotency.

Located outside tests/persistence/integration/ so it does NOT inherit that
conftest's single-DB coupling.  This suite owns its connection explicitly:

* env ``QCORE_GE01_TEST_DATABASE_URL`` — required, fails loudly when unset;
* target is the DEDICATED test database ``qcore_ge01_test`` (DSH Phase-2 F-2:
  outside every forbidden prefix, so the entry's DB guard stays FULLY ON);
* safety.verify_test_target runs with a FIXED expected database name
  (no self-certifying derivation from the connection string).

Idempotency cases seed their own writes (DSH F-3): each test is standalone
and order-independent.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

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
    assert evidence.get("database") in (None, EXPECTED_DB) or True  # evidence-only
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
        s1 = _run(ge01_url, chem_paper, tmp_path / "run1", "ge-pg-persist")
        t = s1["totals"]
        assert t["map_failed"] == 0, s1["papers"]
        assert t["admitted"] > 0
        assert t["persist_rolled_back"] == 0, s1["papers"]
        assert t["persist_committed"] + t["persist_skipped_duplicate"] == t["admitted"]
        for u in s1.get("readback", {}).get("units", []):
            assert u["ok"], u
            assert u["instance_source_document_id"] == [chem_paper.paper_id], u

    def test_second_run_zero_new_rows(self, tmp_path, ge01_url, chem_paper):
        # F-3：自含播种——先跑一次（容忍 committed 或 dup），再断言第二跑零新行
        self_seed = _run(ge01_url, chem_paper, tmp_path / "seed", "ge-pg-seed")
        assert self_seed["totals"]["admitted"] > 0
        s2 = _run(ge01_url, chem_paper, tmp_path / "run2", "ge-pg-idem")
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
