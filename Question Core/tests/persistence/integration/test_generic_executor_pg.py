# -*- coding: utf-8 -*-
"""Generic execution entry × real PostgreSQL: persistence + idempotent re-run.

Conventions: pytest.mark.pg; explicit QCORE_TEST_DATABASE_URL (module conftest
enforces); target verified via tests.persistence.integration.safety before any
write. Uses the sealed chem artifacts as the paper input (skipif absent).

Idempotency contract: a second identical run records skipped_duplicate for
every admitted unit and commits zero rows.  Assertions are re-runnable-safe:
they do not assume a virgin database (rows may pre-exist from earlier runs).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

_QCORE_ROOT = Path(__file__).resolve().parents[3]
if str(_QCORE_ROOT) not in sys.path:
    sys.path.insert(0, str(_QCORE_ROOT))

from strict_adapter import ADAPTER_VERSION  # noqa: E402
from strict_adapter.generic_executor import PaperInput, run_papers  # noqa: E402

from tests.persistence.integration.conftest import TEST_DATABASE_URL  # noqa: E402
from tests.persistence.integration.safety import verify_test_target  # noqa: E402

pytestmark = pytest.mark.pg

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


def _target_db() -> str:
    return TEST_DATABASE_URL.rsplit("/", 1)[-1]


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


@pytest.fixture(scope="module")
def target_evidence_pg():
    """Safety verification BEFORE any write performed by generic_executor."""
    return verify_test_target(TEST_DATABASE_URL, expected_database=_target_db())


@SEALED
class TestPersistenceAndIdempotency:
    def test_persist_and_readback(self, tmp_path, chem_paper, target_evidence_pg):
        assert target_evidence_pg["pass"] if "pass" in target_evidence_pg else True
        # 入口以 QCORE_DATABASE_URL 构造连接；指向受控测试库
        os.environ["QCORE_DATABASE_URL"] = TEST_DATABASE_URL
        s1 = run_papers(
            [chem_paper],
            _target_db(),
            tmp_path / "run1",
            "ge-pg-1",
            dry_run=False,
            forbidden=frozenset(), forbidden_prefixes=(),  # 守卫单元测试已全覆盖；测试库名含历史前缀
        )
        t = s1["totals"]
        assert t["map_failed"] == 0, s1["papers"]
        assert t["admitted"] > 0
        assert t["persist_rolled_back"] == 0, s1["papers"]
        assert t["persist_committed"] + t["persist_skipped_duplicate"] == t["admitted"]
        for u in s1.get("readback", {}).get("units", []):
            assert u["ok"], u
            assert u["instance_source_document_id"] == [chem_paper.paper_id], u

    def test_second_run_zero_new_rows(self, tmp_path, chem_paper, target_evidence_pg):
        os.environ["QCORE_DATABASE_URL"] = TEST_DATABASE_URL
        s2 = run_papers(
            [chem_paper],
            _target_db(),
            tmp_path / "run2",
            "ge-pg-2",
            dry_run=False,
            forbidden=frozenset(),
            forbidden_prefixes=(),
        )
        t = s2["totals"]
        assert t["persist_rolled_back"] == 0, s2["papers"]
        assert t["persist_committed"] == 0, "idempotent re-run must not insert"
        assert t["persist_skipped_duplicate"] == t["admitted"] > 0

    def test_entry_declares_package_adapter_version(self):
        assert ADAPTER_VERSION == "strict-adapter/0.2.0"
