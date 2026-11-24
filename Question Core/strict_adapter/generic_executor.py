"""正式通用试卷处理执行入口（QCORE-GENERIC-EXECUTION-CHAIN-01 G1）。

当前活跃架构中的通用执行组织层：输入契约解析 → MappingContext 构造 →
现有核心函数调用（extract.load_source_lines / mapper.map_unit / admission.admit /
persistence.save_candidate_with_question）→ 结构化执行日志。

职责边界（任务书 §3.4）：只负责输入解析校验、文件-Manifest 关联、运行配置解析、
数据库目标确认、构造 MappingContext、调用现有核心函数、组织执行日志与失败追踪。
不重新识别 PDF / 不重新切题 / 不生成改写 Manifest / 不判断答案 / 不生成内容 /
不绕过 Mapper 或 Admission / 不直接 SQL 写业务表 / 不复制 Repository /
不改变 Question/Revision/Approval/Publication 业务规则。

用法：
    python -m strict_adapter.generic_executor --paper  paper.json \\
        --target-db qcore_batch_pv01_r1 --out-dir <dir> [--dry-run]
    python -m strict_adapter.generic_executor --papers-file papers.json \\
        --target-db qcore_batch_pv01_r1 --out-dir <dir> [--run-id <id>]

输入契约（每卷一个 JSON 描述符）：
    {
      "paper_id": "…（卷级权威标识）",
      "subject": "…（卷级权威学科值，由调用方按学科目录提供）",
      "manifest_path": "…manifest.json",
      "source_md_path": "…ocr md",
      "source_pdf_path": "…pdf",
      "annotated_md_path": "…annotated.md"   // 可选
    }
路径相对描述符所在目录解析；哈希/字节数由入口现算，不信任外部声明。
禁止把试卷名/学科/Run ID/文件名/库名/Unit 数硬编码进代码。

幂等：candidate_idempotency_key + adapter_version 查重（与 mapper 落库同源的
包级 ADAPTER_VERSION），命中 skipped_duplicate 不落行。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import traceback
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

# ---------------------------------------------------------------------------
# 版本身份：唯一来源 = 包级常量（与 mapper 落库一致；见 ADAPTER_VERSION_IDENTITY_REPORT.md）
# ---------------------------------------------------------------------------
from . import ADAPTER_VERSION  # noqa: E402
from .admission import admit  # noqa: E402
from .extract import load_source_lines  # noqa: E402
from .mapper import MappingContext, map_unit  # noqa: E402

DB_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{2,62}$")

# 禁写集合：共享库 + 在线交付库 + 既有验证库前缀（双重防御：精确名 + 前缀）
DEFAULT_FORBIDDEN_DBS = frozenset(
    {
        "aitutors",
        "aitutors_test",
        "qcore_student_integration_01",
    }
)
FORBIDDEN_DB_PREFIXES = (
    "aitutors",
    "qcore_student_integration",
    "qcore_delivery",
    "qcore_e2e",
    "qcore_llm",
    "qcore_missing",
    "qcore_s2q",
    "qcore_image_repair",
    "qcore_answer_fidelity",
    "qcore_dev_test",
    "qcore_preimport",
)

_REQUIRED_FIELDS = ("paper_id", "subject", "manifest_path", "source_md_path", "source_pdf_path")


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


class InputContractError(ValueError):
    """输入描述符违反契约（fail-closed，不猜测、不补全）。"""


class DatabaseTargetError(RuntimeError):
    """数据库目标校验失败（写前阻断）。"""


# ---------------------------------------------------------------------------
# 输入契约
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PaperInput:
    paper_id: str
    subject: str
    manifest_path: Path
    source_md_path: Path
    source_pdf_path: Path
    annotated_md_path: Path | None
    #: D9 C2: optional logical paper segment. Empty means "single-segment
    #: default" — the mapping context then uses ``paper_id``. This is a
    #: pass-through only; the descriptor format gains no required field and no
    #: Manifest rule is added here.
    paper_segment_id: str = ""

    @classmethod
    def from_dict(cls, d: dict, base_dir: Path) -> "PaperInput":
        if not isinstance(d, dict):
            raise InputContractError("paper descriptor must be a JSON object")
        missing = [k for k in _REQUIRED_FIELDS if not str(d.get(k) or "").strip()]
        if missing:
            raise InputContractError(f"paper descriptor missing required fields: {missing}")
        for k in ("paper_id", "subject"):
            if not re.search(r"\S", str(d[k])):
                raise InputContractError(f"{k} must be non-blank (authoritative metadata)")
        paths = {}
        for k in ("manifest_path", "source_md_path", "source_pdf_path", "annotated_md_path"):
            raw = str(d.get(k) or "").strip()
            if not raw:
                paths[k] = None
                continue
            p = Path(raw)
            paths[k] = (base_dir / p).resolve() if not p.is_absolute() else p.resolve()
        for k in ("manifest_path", "source_md_path", "source_pdf_path"):
            if not paths[k].is_file():
                raise InputContractError(f"{k} not found: {paths[k]}")
        if paths["annotated_md_path"] is not None and not paths["annotated_md_path"].is_file():
            raise InputContractError(f"annotated_md_path not found: {paths['annotated_md_path']}")
        return cls(
            paper_id=str(d["paper_id"]).strip(),
            subject=str(d["subject"]).strip(),
            manifest_path=paths["manifest_path"],
            source_md_path=paths["source_md_path"],
            source_pdf_path=paths["source_pdf_path"],
            annotated_md_path=paths["annotated_md_path"],
            paper_segment_id=str(d.get("paper_segment_id") or "").strip(),
        )


def load_paper_descriptors(path: Path) -> list[PaperInput]:
    base_dir = path.parent
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        data = [data]
    if not isinstance(data, list) or not data:
        raise InputContractError("papers file must be a non-empty JSON array (or single object)")
    papers = [PaperInput.from_dict(d, base_dir) for d in data]
    ids = [p.paper_id for p in papers]
    if len(set(ids)) != len(ids):
        raise InputContractError(f"duplicate paper_id in inputs: {ids}")
    return papers


# ---------------------------------------------------------------------------
# MappingContext 构造
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# OCR↔PDF 截断门（QCORE-OCR-TRUNCATION-GATE-01）
#
# 背景：adapter 只拿到 OCR 文本，看不到像素；2022 甲卷 15 选项 B 曾被 OCR 截断
# 为「…any given co」（PDF 印的是「…any given country」），一路进了学生端。
# 这里在**新导入**时对题区做一次确定性比对：OCR 行若恰好是某条 PDF 文本行的
# 严格前缀（且长度差 > 阈值），即判定为截断，fail-closed 挡住该卷。
# 只查截断，不查重复（重复的假阳性高，交给人/规则 G）；不回溯已发布数据。
# ---------------------------------------------------------------------------

#: 题区在 MD 里到此为止（答案/解析区不做学生可见性要求）。
_ANSWER_AREA_MARK = re.compile(r"参考答案|【答案】|【解析】|答案与解析")
_OCR_MEDIA_LINE = re.compile(r"^\s*(?:<(?:div|table|img|p)\b|!\[)")
_OCR_TRUNC_MIN_LEN = 20
_OCR_TRUNC_MIN_GAP = 3


def _ocr_norm_line(s: str) -> str:
    import unicodedata

    s = unicodedata.normalize("NFKC", s or "")
    s = s.translate(str.maketrans({"’": "'", "‘": "'", "“": '"', "”": '"'}))
    s = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", s)
    s = re.sub(r"<[^>]+>", " ", s)
    return re.sub(r"\s+", "", s).lower()


def ocr_question_area(md_lines: list[str]) -> list[tuple[int, str]]:
    """题区行（1-based，遇到第一个答案/解析标记即停）。"""
    out: list[tuple[int, str]] = []
    for i, ln in enumerate(md_lines, 1):
        if _ANSWER_AREA_MARK.search(ln):
            break
        out.append((i, ln))
    return out


def find_truncated_lines(
    md_lines: list[str],
    pdf_lines: list[str],
    *,
    min_len: int = _OCR_TRUNC_MIN_LEN,
    min_gap: int = _OCR_TRUNC_MIN_GAP,
) -> list[dict]:
    """OCR 行是某条 PDF 文本行的严格前缀（且少 > min_gap 字符）= 截断。

    纯函数，便于单测；不做 I/O。
    """
    pdf_norm = [p for p in (_ocr_norm_line(x) for x in pdf_lines) if p]
    pdf_set = set(pdf_norm)
    hits: list[dict] = []
    for line_no, raw in ocr_question_area(md_lines):
        if _OCR_MEDIA_LINE.match(raw):
            continue
        n = _ocr_norm_line(raw)
        if len(n) < min_len or n in pdf_set:
            continue
        longer = next(
            (p for p in pdf_norm if len(p) > len(n) + min_gap and p.startswith(n)),
            None,
        )
        if longer:
            hits.append({"line": line_no, "md": raw.strip()[:160],
                         "pdf": longer[:160], "missing_chars": len(longer) - len(n)})
    return hits


def extract_pdf_text_lines(pdf_path: Path) -> list[str]:
    """PDF 文本层按行切分；pymupdf 不可用时抛 OcrSourceCheckUnavailable。"""
    try:
        import pymupdf  # type: ignore
    except Exception as exc:  # noqa: BLE001
        raise OcrSourceCheckUnavailable(f"pymupdf unavailable: {type(exc).__name__}: {exc}")
    lines: list[str] = []
    doc = pymupdf.open(str(pdf_path))
    try:
        for page in doc:
            lines.extend(page.get_text("text").split("\n"))
    finally:
        doc.close()
    return lines


def check_ocr_truncation(md_lines: list[str], pdf_path: Path) -> dict:
    """返回 {checked, hits}；PDF 无文本层（扫描件）时 checked=False 并记录原因。"""
    pdf_lines = extract_pdf_text_lines(pdf_path)
    if not any(x.strip() for x in pdf_lines):
        return {"checked": False, "reason": "pdf text layer empty (scanned?)", "hits": []}
    hits = find_truncated_lines(md_lines, pdf_lines)
    return {"checked": True, "hits": hits}


class OcrSourceCheckUnavailable(RuntimeError):
    """截断门无法执行（缺依赖/读不了 PDF）。调用方决定 fail-closed 还是记录。"""


def build_context(p: PaperInput, run_id: str) -> tuple[MappingContext, dict]:
    """构造单卷 MappingContext；哈希/字节现算。annotated 缺省时沿既有驱动惯例回退。

    Manifest↔源文绑定（fail-closed，对齐 run_phase_c 输入校验语义）：
    - manifest 带 ``source_content_sha256`` 时必须等于 source_md 现算 sha；
    - manifest 带 ``source_file`` 时必须指向同一 MD（basename 一致）；
    - manifest 带 ``original_sha256`` 时必须等于 source_pdf 现算 sha。
    任一不匹配 → InputContractError（该卷 paper_input_failed，不落库）。
    """
    manifest = json.loads(p.manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest.get("units"), list):
        raise InputContractError(f"manifest has no units[]: {p.manifest_path}")
    lines = load_source_lines(str(p.source_md_path))
    image_by_line = {a["line_no"]: a for a in manifest.get("image_assets", [])}

    md_sha = sha256_file(p.source_md_path)
    pdf_sha = sha256_file(p.source_pdf_path)
    binding = {}
    declared_md_sha = manifest.get("source_content_sha256")
    if declared_md_sha:
        binding["source_content_sha256_match"] = declared_md_sha == md_sha
        if not binding["source_content_sha256_match"]:
            raise InputContractError(
                f"manifest source_content_sha256 mismatch for {p.source_md_path.name}: "
                f"manifest={declared_md_sha} actual={md_sha}"
            )
    else:
        binding["source_content_sha256_match"] = "field_absent_skipped"
    declared_src = manifest.get("source_file")
    if declared_src:
        binding["source_file_basename_match"] = (
            Path(str(declared_src)).name == p.source_md_path.name
        )
        if not binding["source_file_basename_match"]:
            raise InputContractError(
                f"manifest source_file points to {Path(str(declared_src)).name!r} "
                f"but input MD is {p.source_md_path.name!r}"
            )
    else:
        binding["source_file_basename_match"] = "field_absent_skipped"
    declared_pdf_sha = manifest.get("original_sha256")
    if declared_pdf_sha:
        binding["original_sha256_match"] = declared_pdf_sha == pdf_sha
        if not binding["original_sha256_match"]:
            raise InputContractError(
                f"manifest original_sha256 mismatch for {p.source_pdf_path.name}: "
                f"manifest={declared_pdf_sha} actual={pdf_sha}"
            )
    else:
        binding["original_sha256_match"] = "field_absent_skipped"

    ann = p.annotated_md_path
    ann_note = "explicit"
    if ann is None:
        derived = p.manifest_path.parent / p.manifest_path.name.replace(
            ".manifest.json", ".annotated.md"
        )
        if derived.is_file():
            ann = derived
            ann_note = "derived_same_stem"
        else:
            ann = p.manifest_path
            ann_note = "fallback_manifest_itself"
    ctx = MappingContext(
        lines=lines,
        manifest=manifest,
        manifest_path=str(p.manifest_path),
        manifest_name=p.manifest_path.name,
        source_md_path=str(p.source_md_path),
        source_md_name=p.source_md_path.name,
        source_pdf_name=p.source_pdf_path.name,
        annotated_md_name=ann.name,
        manifest_sha=sha256_file(p.manifest_path),
        source_md_sha=md_sha,
        source_pdf_sha=pdf_sha,
        annotated_md_sha=sha256_file(ann),
        manifest_bytes=p.manifest_path.stat().st_size,
        source_md_bytes=p.source_md_path.stat().st_size,
        source_pdf_bytes=p.source_pdf_path.stat().st_size,
        annotated_md_bytes=ann.stat().st_size,
        image_by_line=image_by_line,
        paper_id=p.paper_id,
        subject=p.subject,
        run_id=run_id,
        # D9 C2: pass the logical paper segment through (empty -> paper_id).
        paper_segment_id=p.paper_segment_id,
        # Layer 2：布局证据/跨单元归属需要原始 PDF 文本层坐标（只读）。
        source_pdf_path=str(p.source_pdf_path),
    )
    meta = {
        "annotated_md_resolution": ann_note,
        "annotated_md_path": str(ann),
        "manifest_units": len(manifest["units"]),
        "manifest_image_assets": len(image_by_line),
        "manifest_source_binding": binding,
    }
    return ctx, meta


# ---------------------------------------------------------------------------
# 数据库目标确认（写前 fail-closed）
# ---------------------------------------------------------------------------


def validate_target_db_name(
    target_db: str,
    forbidden: frozenset[str] = DEFAULT_FORBIDDEN_DBS,
    forbidden_prefixes: tuple[str, ...] = FORBIDDEN_DB_PREFIXES,
) -> dict:
    name = (target_db or "").strip()
    checks = {
        "target_db": name,
        "name_pattern_ok": bool(DB_NAME_RE.match(name)),
        "not_exact_forbidden": name not in forbidden,
        "not_prefix_forbidden": not any(name.startswith(p) for p in forbidden_prefixes),
    }
    checks["pass"] = all(checks[k] for k in ("name_pattern_ok", "not_exact_forbidden", "not_prefix_forbidden"))
    return checks


def apply_target_db_url(target_db: str) -> dict:
    """把 QCORE_DATABASE_URL 显式指向 target-db（保留凭据，记录覆盖事实）。"""
    ambient = os.environ.get("QCORE_DATABASE_URL", "").strip()
    if not ambient:
        raise DatabaseTargetError("QCORE_DATABASE_URL is not set; cannot construct target URL")
    norm = ambient.replace("postgresql+psycopg2://", "postgresql://").replace(
        "postgresql+psycopg://", "postgresql://"
    )
    prefix = norm.rpartition("/")[0]
    if not prefix.startswith(("postgresql://", "postgres://")):
        raise DatabaseTargetError("unrecognized DATABASE_URL scheme")
    new_url = prefix + "/" + target_db
    record = {
        "preexisting_dbname": norm.rsplit("/", 1)[-1] or None,
        "preexisting_url_redacted": re.sub(
            r"://([^:]+):([^@]+)@", r"://\1:***@", norm
        ),
        "applied_target_dbname": target_db,
    }
    os.environ["QCORE_DATABASE_URL"] = new_url.replace(
        "postgresql://", "postgresql+psycopg2://", 1
    )
    return record


def assert_connected_target(target_db: str) -> dict:
    """连接层复核：current_database/current_user（写前第二断言）。"""
    import psycopg2

    norm = os.environ.get("QCORE_DATABASE_URL", "").replace(
        "postgresql+psycopg2://", "postgresql://"
    ).replace("postgresql+psycopg://", "postgresql://")
    conn = psycopg2.connect(norm)
    try:
        with conn.cursor() as cur:
            cur.execute("select current_database(), current_user")
            db, user = cur.fetchone()
    finally:
        conn.close()
    return {"current_database": db, "current_user": user, "pass": db == target_db}


# ---------------------------------------------------------------------------
# 执行编排
# ---------------------------------------------------------------------------


def _force_incomplete(mapping, reason: dict):
    """Temporarily withhold a question from students (Owner 2026-11-22 §11.3).

    Content is unchanged and fully preserved; only completeness/state is forced to
    ``incomplete`` so Admission produces a ``not_ready`` revision. No SQL, no
    publication bypass.
    """
    from question_core.contracts.v1 import Completeness

    core = mapping.candidate.core
    data = core.model_dump()
    data["completeness"] = Completeness.INCOMPLETE
    new_core = type(core).model_validate(data)
    source = mapping.candidate.source
    src_data = source.model_dump()
    if isinstance(src_data.get("answer_declaration"), dict):
        src_data["answer_declaration"]["completeness"] = Completeness.INCOMPLETE
    new_source = type(source).model_validate(src_data)
    cand = type(mapping.candidate)(core=new_core, source=new_source)
    log = dict(mapping.log or {})
    log["suspended_due_to"] = reason
    return replace(mapping, candidate=cand, completeness="incomplete", state_plan="hold_not_ready", log=log)


def load_suspensions(path: str | Path | None) -> list[dict]:
    if not path:
        return []
    p = Path(path)
    if not p.is_file():
        raise InputContractError(f"suspensions file not found: {p}")
    data = json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise InputContractError("suspensions file must be a JSON array")
    for e in data:
        if not e.get("reason_code"):
            raise InputContractError("each suspension needs reason_code")
    return data


def _match_suspension(suspensions, paper_id: str, unit: dict) -> dict | None:
    if not suspensions:
        return None
    printed = str(unit.get("printed_number"))
    uid = str(unit.get("unit_id"))
    for e in suspensions:
        if e.get("paper_id") not in (None, paper_id):
            continue
        if str(e.get("printed_number")) == printed or str(e.get("unit_id")) == uid:
            return e
    return None


def _match_exclusion(exclusions, paper_id: str, unit: dict) -> dict | None:
    """Match a declared exclusion by (paper_id, printed_number | unit_id)."""
    if not exclusions:
        return None
    printed = str(unit.get("printed_number"))
    uid = str(unit.get("unit_id"))
    for e in exclusions:
        if e.get("paper_id") not in (None, paper_id):
            continue
        if str(e.get("printed_number")) == printed or str(e.get("unit_id")) == uid:
            return e
    return None


def load_exclusions(path: str | Path | None) -> list[dict]:
    if not path:
        return []
    p = Path(path)
    if not p.is_file():
        raise InputContractError(f"exclusions file not found: {p}")
    data = json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise InputContractError("exclusions file must be a JSON array")
    for e in data:
        if not e.get("reason_code"):
            raise InputContractError("each exclusion needs reason_code")
    return data


def run_papers(
    papers: list[PaperInput],
    target_db: str,
    out_dir: Path,
    run_id: str,
    dry_run: bool = False,
    forbidden: frozenset[str] = DEFAULT_FORBIDDEN_DBS,
    forbidden_prefixes: tuple[str, ...] = FORBIDDEN_DB_PREFIXES,
    exclusions: list[dict] | None = None,
    suspensions: list[dict] | None = None,
    ocr_source_check: bool = True,
) -> dict:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    summary: dict = {
        "entry": "strict_adapter.generic_executor",
        "adapter_version": ADAPTER_VERSION,
        "run_id": run_id,
        "started_at": now(),
        "target_db": target_db,
        "dry_run": dry_run,
        "papers": [],
        "totals": {},
    }

    # --- DB 目标断言（dry-run 也做名称级校验；写断言仅持久化前） ---
    name_checks = validate_target_db_name(target_db, forbidden, forbidden_prefixes)
    summary["db_name_checks"] = name_checks
    if not name_checks["pass"]:
        raise DatabaseTargetError(f"target db name rejected: {name_checks}")

    url_record = None
    connect_check = None
    if not dry_run:
        url_record = apply_target_db_url(target_db)
        summary["db_url_override"] = url_record
        connect_check = assert_connected_target(target_db)
        summary["db_connect_check"] = connect_check
        if not connect_check["pass"]:
            raise DatabaseTargetError(f"connected db mismatch: {connect_check}")

    # --- 逐卷映射（卷间隔离） ---
    mapped_all = []  # (paper, ctx, [(ordinal, mapping)])
    for p in papers:
        prec: dict = {"paper_id": p.paper_id, "subject": p.subject, "units": []}
        try:
            ctx, meta = build_context(p, run_id)
            prec.update(meta)
        except Exception as exc:  # noqa: BLE001
            prec["status"] = "paper_input_failed"
            prec["error"] = f"{type(exc).__name__}: {exc}"
            prec["traceback"] = traceback.format_exc()
            summary["papers"].append(prec)
            continue
        # --- OCR↔PDF 截断门（新导入专用；已发布数据不回溯）---
        if ocr_source_check:
            try:
                chk = check_ocr_truncation(list(ctx.lines), p.source_pdf_path)
            except OcrSourceCheckUnavailable as exc:
                chk = {"checked": False, "reason": str(exc), "hits": []}
            prec["ocr_source_check"] = chk
            if chk.get("hits"):
                prec["status"] = "ocr_source_defect"
                prec["error"] = (
                    "ocr truncation vs PDF text layer (OCR_SOURCE_ERROR): "
                    + json.dumps(chk["hits"], ensure_ascii=False)
                )
                summary["papers"].append(prec)
                continue
        pairs = []
        for idx, unit in enumerate(ctx.manifest["units"], start=1):
            urec = {
                "unit_id": unit.get("unit_id"),
                "ordinal": idx,
                "unit_type": unit.get("unit_type"),
                "printed_number": unit.get("printed_number"),
            }
            exclusion = _match_exclusion(exclusions, p.paper_id, unit)
            if exclusion is not None:
                # Owner 2026-11-22：源文缺少该题必需的媒体（如无音频听力）时，
                # 该 unit 不进入 Question Core；证据（PDF/OCR/Manifest）保留。
                urec["status"] = "excluded"
                urec["exclusion"] = exclusion
                prec["units"].append(urec)
                continue
            try:
                m = map_unit(unit, ctx)
                _susp = _match_suspension(suspensions, p.paper_id, unit)
                if _susp is not None:
                    m = _force_incomplete(m, _susp)
                    urec["suspended"] = _susp.get("reason_code")
                urec["status"] = "mapped"
                urec["completeness"] = m.completeness
                # D9 C1/C2: make the source anchor visible in run evidence so a
                # reviewer can verify segment propagation without a DB.
                urec["identity_key"] = m.candidate.core.ingestion.candidate_idempotency_key
                urec["identity_anchor"] = m.identity_anchor
                pairs.append((idx, m))
            except Exception as exc:  # noqa: BLE001
                urec["status"] = "map_failed"
                urec["error"] = f"{type(exc).__name__}: {exc}"
            prec["units"].append(urec)
        prec["status"] = "ok" if pairs else "no_units_mapped"
        prec["mapped_count"] = len(pairs)
        summary["papers"].append(prec)
        mapped_all.append((p, ctx, pairs))

    # --- 逐 unit 准入 ---
    admitted_all = []  # (paper, ctx, ordinal, mapping, admit_result)
    for p, ctx, pairs in mapped_all:
        prec = next(x for x in summary["papers"] if x["paper_id"] == p.paper_id)
        for ordinal, m in pairs:
            urec = next(u for u in prec["units"] if u["ordinal"] == ordinal)
            try:
                res = admit(m, ctx, ordinal=ordinal)
            except Exception as exc:  # noqa: BLE001
                urec["status"] = "admit_failed"
                urec["error"] = f"{type(exc).__name__}: {exc}"
                continue
            urec.update(
                {
                    "validated": res.validated,
                    "admitted": res.admitted,
                    "admission_reason": res.admission_reason,
                    "review_state": res.review_state,
                    "publication_state": res.publication_state,
                    "question_id": str(res.question_id) if res.question_id else None,
                    "revision_id": str(res.revision_id) if res.revision_id else None,
                    "instance_id": str(res.instance_id) if res.instance_id else None,
                    "content_hash": res.content_hash,
                }
            )
            urec["status"] = "admitted" if res.admitted else "not_admitted"
            if res.admitted:
                admitted_all.append((p, ctx, ordinal, m, res))

    # --- 持久化（逐 unit 事务 + 幂等；dry-run 跳过） ---
    if dry_run:
        for p, ctx, ordinal, m, res in admitted_all:
            prec = next(x for x in summary["papers"] if x["paper_id"] == p.paper_id)
            urec = next(u for u in prec["units"] if u["ordinal"] == ordinal)
            urec["persist"] = "dry_run_skipped"
    else:
        from question_core.persistence import (
            DatabaseSettings,
            QuestionCoreRepository,
            create_db_engine,
            session_scope,
        )
        from question_core.persistence.exceptions import NotFoundError
        from .ingest import persist_mapping

        settings = DatabaseSettings.from_env()
        if settings.dbname != target_db:
            raise DatabaseTargetError(
                f"settings.dbname={settings.dbname!r} != target {target_db!r}"
            )
        engine = create_db_engine(settings)
        for p, ctx, ordinal, m, res in admitted_all:
            prec = next(x for x in summary["papers"] if x["paper_id"] == p.paper_id)
            urec = next(u for u in prec["units"] if u["ordinal"] == ordinal)
            cand = m.candidate
            try:
                with session_scope(engine) as session:
                    repo = QuestionCoreRepository(session)
                    record = persist_mapping(repo, m, res, paper_id=p.paper_id)
                    urec["persist"] = record["persist"]
                    urec["identity_key"] = record["identity_key"]
                    urec["identity_anchor"] = record["identity_anchor"]
                    urec["matched_by"] = record["matched_by"]
                    if record.get("question_id"):
                        urec["question_id"] = record["question_id"]
                    if record.get("candidate_id"):
                        urec["candidate_id"] = record["candidate_id"]
            except Exception as exc:  # noqa: BLE001
                urec["persist"] = "rolled_back"
                urec["error"] = f"{type(exc).__name__}: {exc}"

        # --- 断开重连回读 ---
        engine.dispose()
        from question_core.persistence import DatabaseSettings as _DS  # noqa: F401

        rb_engine = create_db_engine(DatabaseSettings.from_env())
        readback = {"units": []}
        with session_scope(rb_engine) as session:
            repo = QuestionCoreRepository(session)
            for p, ctx, ordinal, m, res in admitted_all:
                prec = next(x for x in summary["papers"] if x["paper_id"] == p.paper_id)
                urec = next(u for u in prec["units"] if u["ordinal"] == ordinal)
                if urec.get("persist") not in (
                    "committed_new",
                    "revision_added",
                    "skipped_duplicate",
                ):
                    continue
                qid_text = urec.get("question_id") or str(res.question_id)
                agg = repo.get_question_aggregate(UUID(qid_text))
                readback["units"].append(
                    {
                        "unit_id": res.unit_id,
                        "question_id": qid_text,
                        "revision_count": len(agg.revisions),
                        "instance_count": len(agg.instances),
                        "instance_source_document_id": [
                            str(i.source_document_id) for i in agg.instances
                        ],
                        "ok": bool(agg.revisions) and bool(agg.instances),
                    }
                )
        rb_engine.dispose()
        summary["readback"] = readback

    # --- 汇总 ---
    flat = [u for pr in summary["papers"] for u in pr.get("units", [])]
    summary["totals"] = {
        "papers": len(papers),
        "units_in": len(flat),
        "excluded": sum(1 for u in flat if u.get("status") == "excluded"),
        "mapped": sum(1 for u in flat if u.get("status") not in ("map_failed", "excluded") and u.get("status") != "paper_input_failed"),
        "map_failed": sum(1 for u in flat if u.get("status") == "map_failed"),
        "admitted": sum(1 for u in flat if u.get("admitted") is True),
        "not_admitted": sum(1 for u in flat if u.get("status") == "not_admitted"),
        "persist_committed": sum(1 for u in flat if u.get("persist") == "committed"),
        "persist_skipped_duplicate": sum(1 for u in flat if u.get("persist") == "skipped_duplicate"),
        "persist_rolled_back": sum(1 for u in flat if u.get("persist") == "rolled_back"),
        "paper_input_failed": sum(1 for pr in summary["papers"] if pr.get("status") == "paper_input_failed"),
        "ocr_source_defect": sum(1 for pr in summary["papers"] if pr.get("status") == "ocr_source_defect"),
    }
    summary["finished_at"] = now()
    (out_dir / "run_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    _write_per_paper_outputs(out_dir, summary)
    return summary


def _safe_dirname(paper_id: str) -> str:
    return re.sub(r"[^0-9A-Za-z一-鿿_-]+", "_", paper_id)[:120]


def _write_per_paper_outputs(out_dir: Path, summary: dict) -> None:
    """逐卷输出（DESIGN §6 承诺）：mapping / admission / persistence / readback。"""
    readback_by_qid = {
        u["question_id"]: u for u in summary.get("readback", {}).get("units", [])
    }
    for prec in summary.get("papers", []):
        pd = out_dir / "papers" / _safe_dirname(prec["paper_id"])
        pd.mkdir(parents=True, exist_ok=True)
        units = prec.get("units", [])
        head = {
            "paper_id": prec.get("paper_id"),
            "subject": prec.get("subject"),
            "run_id": summary.get("run_id"),
            "adapter_version": summary.get("adapter_version"),
            "target_db": summary.get("target_db"),
            "status": prec.get("status"),
            "manifest_source_binding": prec.get("manifest_source_binding"),
            "annotated_md_resolution": prec.get("annotated_md_resolution"),
        }
        (pd / "mapping.json").write_text(
            json.dumps(
                {
                    **head,
                    "manifest_units": prec.get("manifest_units"),
                    "mapped_count": prec.get("mapped_count"),
                    "units": [
                        {k: u.get(k) for k in ("unit_id", "ordinal", "unit_type", "status", "completeness", "identity_key", "identity_anchor", "error") if k in u}
                        for u in units
                    ],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        (pd / "admission.json").write_text(
            json.dumps(
                {
                    **head,
                    "units": [
                        {
                            k: u.get(k)
                            for k in (
                                "unit_id", "ordinal", "status", "validated", "admitted",
                                "admission_reason", "review_state", "publication_state",
                                "question_id", "revision_id", "instance_id", "content_hash", "error",
                            )
                            if k in u
                        }
                        for u in units
                    ],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        (pd / "persistence.json").write_text(
            json.dumps(
                {
                    **head,
                    "units": [
                        {
                            k: u.get(k)
                            for k in (
                                "unit_id", "ordinal", "persist", "candidate_id",
                                "existing_candidate_id", "error",
                            )
                            if k in u
                        }
                        for u in units
                    ],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        rb_units = []
        for u in units:
            qid = u.get("question_id")
            rb = readback_by_qid.get(qid) if qid else None
            if rb is not None:
                rb_units.append(rb)
        (pd / "readback.json").write_text(
            json.dumps({**head, "units": rb_units}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="python -m strict_adapter.generic_executor",
        description="Generic exam-paper processing execution entry (map_unit/admit/persist).",
    )
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--paper", type=str, help="single paper descriptor JSON")
    g.add_argument("--papers-file", type=str, help="JSON array of paper descriptors")
    ap.add_argument("--target-db", type=str, required=True, help="target database name (required, asserted)")
    ap.add_argument("--out-dir", type=str, required=True, help="execution log directory")
    ap.add_argument("--run-id", type=str, default=None)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument(
        "--forbidden-db",
        action="append",
        default=[],
        help="additional forbidden db name (repeatable)",
    )
    ap.add_argument(
        "--exclusions",
        type=str,
        default=None,
        help="JSON array of units excluded from Question Core (e.g. listening without audio); "
        "each item needs reason_code",
    )
    ap.add_argument(
        "--suspend",
        type=str,
        default=None,
        help="JSON array of units temporarily withheld from students (content kept, "
        "completeness forced incomplete); each item needs reason_code",
    )
    ap.add_argument(
        "--no-ocr-source-check",
        action="store_true",
        help="skip the OCR-vs-PDF truncation gate (not recommended; the gate only "
        "applies to newly imported papers)",
    )
    args = ap.parse_args(argv)

    run_id = args.run_id or f"generic-exec-{now().replace(':', '').replace('-', '')[:15]}"
    forbidden = DEFAULT_FORBIDDEN_DBS | frozenset(args.forbidden_db)

    if args.paper:
        papers = load_paper_descriptors(Path(args.paper))
    else:
        papers = load_paper_descriptors(Path(args.papers_file))

    summary = run_papers(
        papers,
        target_db=args.target_db,
        out_dir=Path(args.out_dir),
        run_id=run_id,
        dry_run=args.dry_run,
        forbidden=forbidden,
        exclusions=load_exclusions(args.exclusions),
        suspensions=load_suspensions(args.suspend),
        ocr_source_check=not args.no_ocr_source_check,
    )
    print(
        json.dumps(
            {"run_id": run_id, "totals": summary["totals"], "adapter_version": ADAPTER_VERSION},
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
