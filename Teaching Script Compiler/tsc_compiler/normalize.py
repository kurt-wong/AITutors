"""Text, math-span and token utilities.

Everything here is deterministic and side-effect free; the compiler and the
validator share it so a script can be re-derived and audited later.
"""

from __future__ import annotations

import html
import re
import unicodedata

_MATH_DELIM = re.compile(r"\${1,2}")
_SENTENCE_SPLIT = re.compile(r"(?<=[。！？；;])")
_NUMBER = re.compile(r"\d+(?:\.\d+)?")
_LATEX_CMD = re.compile(r"\\[A-Za-z]+")
_CJK = re.compile(r"[\u4e00-\u9fff]")

_HTML_ENTITY = re.compile(r"&(?:gt|lt|amp|quot|nbsp);")


def decode_entities(text: str) -> str:
    """Decode only the entities OCR actually emits (&amp; last)."""
    text = text.replace("&gt;", ">").replace("&lt;", "<")
    text = text.replace("&quot;", '"').replace("&nbsp;", " ")
    return text.replace("&amp;", "&")


def clean_source_text(text: str) -> str:
    """Normalize whitespace but never change wording."""
    text = decode_entities(str(text or ""))
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [ln.strip() for ln in text.split("\n")]
    lines = [ln for ln in lines if ln and not re.fullmatch(r"-{3,}", ln)]
    return "\n".join(lines).strip()


def split_math_spans(text: str) -> list[dict[str, str]]:
    """Split a source string into ordered text / math spans.

    ``math`` spans keep the raw LaTeX (without the ``$`` delimiters). An
    unbalanced ``$`` is treated as literal text — the caller's validator will
    then see the same characters the student sees.
    """
    text = str(text or "")
    out: list[dict[str, str]] = []
    buf: list[str] = []

    def flush() -> None:
        if buf:
            merged = "".join(buf)
            if merged:
                out.append({"kind": "text", "text": merged})
            buf.clear()

    i = 0
    n = len(text)
    while i < n:
        if text.startswith("$$", i):
            j = text.find("$$", i + 2)
            if j != -1:
                body = text[i + 2 : j].strip()
                if body:
                    flush()
                    out.append({"kind": "math", "latex": body})
                    i = j + 2
                    continue
        if text[i] == "$":
            j = text.find("$", i + 1)
            if j != -1:
                body = text[i + 1 : j]
                if body.strip() and "\n" not in body:
                    flush()
                    out.append({"kind": "math", "latex": body.strip()})
                    i = j + 1
                    continue
        buf.append(text[i])
        i += 1
    flush()
    return out


def plain_text(text: str) -> str:
    """Source text with math delimiters removed (LaTeX retained)."""
    return "".join(
        span.get("text", "") if span["kind"] == "text" else span["latex"]
        for span in split_math_spans(text)
    )


_MATH_SYMBOLS = {
    r"\in": "∈",
    r"\notin": "∉",
    r"\ni": "∋",
    r"\cap": "∩",
    r"\cup": "∪",
    r"\complement": "∁",
    r"\subseteq": "⊆",
    r"\subset": "⊂",
    r"\supseteq": "⊇",
    r"\geq": "≥",
    r"\ge": "≥",
    r"\leq": "≤",
    r"\le": "≤",
    r"\neq": "≠",
    r"\ne": "≠",
    r"\times": "×",
    r"\cdot": "·",
    r"\pm": "±",
    r"\infty": "∞",
    r"\pi": "π",
    r"\alpha": "α",
    r"\beta": "β",
    r"\theta": "θ",
    r"\angle": "∠",
    r"\triangle": "△",
    r"\parallel": "∥",
    r"\perp": "⊥",
    r"\Rightarrow": "⇒",
    r"\rightarrow": "→",
    r"\to": "→",
    r"\because": "∵",
    r"\therefore": "∴",
    r"\quad": " ",
    r"\qquad": "  ",
    r"\,": " ",
    r"\;": " ",
    r"\!": "",
    r"\ ": " ",
    r"\left": "",
    r"\right": "",
}


def _read_group(text: str, start: int) -> tuple[str, int]:
    """Read a balanced ``{...}`` group starting at ``start`` (the brace)."""
    if start >= len(text) or text[start] != "{":
        return "", start
    depth = 0
    for index in range(start, len(text)):
        if text[index] == "{":
            depth += 1
        elif text[index] == "}":
            depth -= 1
            if depth == 0:
                return text[start + 1 : index], index + 1
    return text[start + 1 :], len(text)


def _expand_fractions(latex: str) -> str:
    """Rewrite ``\\frac{a}{b}`` / ``\\sqrt[n]{x}`` with balanced parsing."""
    out: list[str] = []
    i = 0
    while i < len(latex):
        match = re.match(r"\\([dt]?frac|sqrt)\s*", latex[i:])
        if not match:
            out.append(latex[i])
            i += 1
            continue
        command = match.group(1)
        j = i + match.end()
        if command.endswith("frac"):
            if j >= len(latex) or latex[j] != "{":
                out.append(latex[i])
                i += 1
                continue
            numerator, j = _read_group(latex, j)
            while j < len(latex) and latex[j].isspace():
                j += 1
            if j >= len(latex) or latex[j] != "{":
                out.append(latex[i])
                i += 1
                continue
            denominator, j = _read_group(latex, j)
            out.append(
                "("
                + _expand_fractions(numerator)
                + ")/("
                + _expand_fractions(denominator)
                + ")"
            )
            i = j
            continue
        # sqrt
        index_text = ""
        if j < len(latex) and latex[j] == "[":
            close = latex.find("]", j)
            if close != -1:
                index_text = latex[j + 1 : close]
                j = close + 1
        if j < len(latex) and latex[j] == "{":
            body, j = _read_group(latex, j)
            rendered = _expand_fractions(body)
            out.append(
                f"({index_text})次根号({rendered})" if index_text else f"√({rendered})"
            )
            i = j
            continue
        out.append(latex[i])
        i += 1
    return "".join(out)


_SYMBOL_PATTERNS = [
    (re.compile(re.escape(src) + r"(?![A-Za-z])"), dst)
    for src, dst in _MATH_SYMBOLS.items()
    if src not in (r"\left", r"\right")
]


def math_to_speech(latex: str) -> str:
    """Render LaTeX as readable plain text for subtitles.

    Purely presentational: digits and values are unchanged, so the fact check
    still compares the same number tokens as the source. Braces are kept so a
    command never fuses with its argument (``\\bar{z}`` must not become
    ``\\barz``, which would look like a different LaTeX command).
    """
    out = str(latex or "")
    out = re.sub(r"\\(left|right)(?![A-Za-z])", "", out)
    out = _expand_fractions(out)
    for pattern, dst in _SYMBOL_PATTERNS:
        out = pattern.sub(dst, out)
    out = out.replace(r"\{", "{").replace(r"\}", "}").replace(r"\_", "_")
    out = out.replace(r"\%", "%").replace("\\\\", " ").replace("$", "")
    out = re.sub(r"[ \t]+", " ", out)
    return out.strip()


def speechify(text: str) -> str:
    """Source text → subtitle / speech string (math rendered readably)."""
    parts: list[str] = []
    for span in split_math_spans(text):
        if span["kind"] == "text":
            parts.append(span["text"])
        else:
            parts.append(" " + math_to_speech(span["latex"]) + " ")
    out = "".join(parts)
    out = re.sub(r"[ \t]+", " ", out)
    out = re.sub(r"\s*\n\s*", " ", out)
    return out.strip()


def numeric_tokens(text: str) -> set[str]:
    return set(_NUMBER.findall(str(text or "")))


def latex_commands(text: str) -> set[str]:
    return set(_LATEX_CMD.findall(str(text or "")))


def cjk_length(text: str) -> int:
    return len(_CJK.findall(str(text or "")))


def split_sentences(text: str) -> list[str]:
    """Split at Chinese sentence punctuation *outside* math spans."""
    parts: list[str] = []
    buf: list[str] = []
    depth = 0
    i = 0
    while i < len(text):
        ch = text[i]
        if text.startswith("$$", i):
            depth = 1 - depth
            buf.append("$$")
            i += 2
            continue
        if ch == "$":
            depth = 1 - depth
            buf.append(ch)
            i += 1
            continue
        buf.append(ch)
        if depth == 0 and ch in "。！？；;":
            parts.append("".join(buf))
            buf = []
        i += 1
    if buf:
        parts.append("".join(buf))
    return [p.strip() for p in parts if p.strip()]


def chunk_paragraph(text: str, max_chars: int = 220) -> list[str]:
    """Split one paragraph into teaching-sized chunks without breaking math."""
    text = text.strip()
    if not text:
        return []
    if len(text) <= max_chars:
        return [text]
    sentences = split_sentences(text)
    chunks: list[str] = []
    current = ""
    for sentence in sentences:
        if current and len(current) + len(sentence) > max_chars:
            chunks.append(current)
            current = sentence
        else:
            current += sentence
    if current.strip():
        chunks.append(current.strip())
    # A single monster sentence: hard-split at safe boundaries.
    out: list[str] = []
    for chunk in chunks:
        while len(chunk) > max_chars * 1.6:
            out.append(chunk[: max_chars * 1.6])
            chunk = chunk[max_chars * 1.6 :]
        if chunk:
            out.append(chunk)
    return out


def estimate_duration_ms(text: str) -> int:
    """No TTS in this round: estimate a stable reading timeline."""
    length = len(speechify(text))
    ms = 1200 + length * 190
    return max(4000, min(18000, int(ms)))


def normalize_answer(value: str) -> str:
    """Conservative equivalence key for answer comparison.

    Only typographic differences are removed; mathematical structure is kept
    so ``A`` never equals ``B`` and ``\\frac{1}{2}`` never equals ``2``.
    """
    text = unicodedata.normalize("NFKC", str(value or ""))
    text = text.strip()
    text = re.sub(r"^[\s$]+|[\s$]+$", "", text)
    text = text.replace(r"\left", "").replace(r"\right", "")
    text = re.sub(r"\\[dt]frac", r"\\frac", text)
    text = re.sub(r"\\ge(?![a-zA-Z])", r"\\geq", text)
    text = re.sub(r"\\le(?![a-zA-Z])", r"\\leq", text)
    text = re.sub(r"\\ne(?![a-zA-Z])", r"\\neq", text)
    for junk in (r"\,", r"\;", r"\!", r"\ ", "~"):
        text = text.replace(junk, "")
    text = re.sub(r"\s+", "", text)
    text = text.rstrip("。．.；;，,")
    return text.lower()


def truncate_title(text: str, limit: int = 42) -> str:
    clean = re.sub(r"\s+", " ", plain_text(text)).strip()
    clean = re.sub(r"^\d+[.、．]\s*", "", clean)
    return clean[:limit] + ("…" if len(clean) > limit else "")


def normalize_for_search(text: str) -> str:
    """Loose normalization used by the retrieval index (not by the validator)."""
    text = unicodedata.normalize("NFKC", str(text or ""))
    text = text.lower()
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()
