"""Configuration for the Teaching Script Compiler.

Secrets never live in the repository. ``.env.local`` is gitignored and is the
only place a database URL / API key may be written for local runs; the process
environment always wins.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = ROOT.parent

DEFAULT_QCORE_ROOT = REPO_ROOT / "Question Core"
DEFAULT_ASSET_ALLOWLIST = (
    REPO_ROOT
    / "runs"
    / "qcore_six_subject_accept_01"
    / "execution"
    / "asset_allowlist_175.json"
)


def _load_env_local(path: Path) -> dict[str, str]:
    """Minimal KEY=VALUE loader (no quoting machinery, no exports)."""
    out: dict[str, str] = {}
    if not path.is_file():
        return out
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if value[:1] in {"'", '"'} and value[-1:] == value[:1]:
            value = value[1:-1]
        if key:
            out[key] = value
    return out


def _env(name: str, default: str = "") -> str:
    value = os.environ.get(name)
    if value is None or value == "":
        value = _LOCAL.get(name, default)
    return value


_LOCAL = _load_env_local(ROOT / ".env.local")


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    qcore_root: Path
    qcore_database_url: str = ""
    asset_allowlist: Path = DEFAULT_ASSET_ALLOWLIST
    asset_base: str = "http://127.0.0.1:8812"
    languages: tuple[str, ...] = ("zh-CN",)
    llm_base_url: str = "https://api.deepseek.com"
    llm_model: str = "deepseek-flash"
    llm_api_key: str = ""
    llm_rerank: bool = True
    ocr_token: str = ""
    ocr_job_url: str = "https://paddleocr.aistudio-app.com/api/v2/ocr/jobs"
    ocr_model: str = "PaddleOCR-VL-1.6"
    ocr_proxy: str = "http://127.0.0.1:58182"
    cors_origins: tuple[str, ...] = (
        "http://127.0.0.1:3000",
        "http://localhost:3000",
        "http://127.0.0.1:8821",
        "http://localhost:8821",
    )
    extra: dict[str, str] = field(default_factory=dict)


def _bool(value: str, default: bool) -> bool:
    if not value:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def load_settings() -> Settings:
    data_dir = Path(_env("TSC_DATA_DIR", str(ROOT / "data"))).resolve()
    qcore_root = Path(_env("TSC_QCORE_ROOT", str(DEFAULT_QCORE_ROOT))).resolve()
    allowlist = Path(_env("TSC_ASSET_ALLOWLIST", str(DEFAULT_ASSET_ALLOWLIST)))
    return Settings(
        data_dir=data_dir,
        qcore_root=qcore_root,
        qcore_database_url=_env("QCORE_DATABASE_URL"),
        asset_allowlist=allowlist,
        asset_base=_env("TSC_ASSET_BASE", "http://127.0.0.1:8812").rstrip("/"),
        llm_base_url=_env("TSC_LLM_BASE_URL", "https://api.deepseek.com").rstrip("/"),
        llm_model=_env("TSC_LLM_MODEL", "deepseek-flash"),
        llm_api_key=_env("TSC_LLM_API_KEY"),
        llm_rerank=_bool(_env("TSC_LLM_RERANK", "on"), True),
        ocr_token=_env("OCR_API_TOKEN"),
        ocr_job_url=_env(
            "TSC_OCR_JOB_URL", "https://paddleocr.aistudio-app.com/api/v2/ocr/jobs"
        ),
        ocr_model=_env("TSC_OCR_MODEL", "PaddleOCR-VL-1.6"),
        ocr_proxy=_env("TSC_OCR_PROXY", "http://127.0.0.1:58182"),
    )


def ensure_dirs(settings: Settings) -> None:
    for sub in ("qcore", "qcore/bundles", "scripts", "photo", "logs"):
        (settings.data_dir / sub).mkdir(parents=True, exist_ok=True)
