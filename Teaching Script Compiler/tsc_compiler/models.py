"""Fixed constants shared by the compiler, the validator and the player contract."""

from __future__ import annotations

SCRIPT_SCHEMA_VERSION = "1.0.0"
PROMPT_VERSION = "deterministic-explanation-v4"
MODEL_ID = "deterministic"
RENDERER_VERSION = "interactive-lesson/1.0.0"
DEFAULT_LANGUAGE = "zh-CN"

BOARD_KINDS = (
    "heading",
    "text",
    "math",
    "image",
    "table",
    "callout",
    "choice",
    "blank",
)
EFFECT_TYPES = ("show", "highlight", "focus", "pulse")

#: Every TeachingScript carries exactly these cache-key inputs (spec §19).
CACHE_KEY_FIELDS = (
    "question_id",
    "revision_id",
    "language",
    "script_schema_version",
    "prompt_version",
    "model",
    "renderer_version",
)


def cache_key(
    *,
    question_id: str,
    revision_id: str,
    language: str,
    script_schema_version: str = SCRIPT_SCHEMA_VERSION,
    prompt_version: str = PROMPT_VERSION,
    model: str = MODEL_ID,
    renderer_version: str = RENDERER_VERSION,
) -> str:
    return "|".join(
        [
            question_id,
            revision_id,
            language,
            script_schema_version,
            prompt_version,
            model,
            renderer_version,
        ]
    )
