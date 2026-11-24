"""Build real photo-style inputs from the sealed source PDFs (pilot harness).

The camera is simulated: a question region is cropped from the PDF page(s),
rendered at ~200 dpi, optionally rotated a little and re-encoded as JPEG. A
question that continues on the next page is stacked into one tall image, the
way a second shot of the same question would look. The pipeline treats the
result exactly like an uploaded phone photo — nothing about the QCore side
changes.
"""

from __future__ import annotations

import io
import re
from pathlib import Path

import fitz
from PIL import Image

_QUESTION_START = re.compile(r"^\s*(\d{1,2})\s*[.、．]")


def _clean_block_text(text: str) -> str:
    return re.sub(r"\s+", "", str(text or ""))


def stem_hint(stem_text: str, length: int = 10) -> str:
    """First CJK run of the stem, used to locate the question on the page."""
    plain = re.sub(r"\$[^$]*\$", "", stem_text or "")
    runs = re.findall(r"[\u4e00-\u9fff]{3,}", plain)
    if not runs:
        return ""
    return runs[0][:length]


def _blocks(page: fitz.Page) -> list[tuple[float, float, str]]:
    out = []
    for block in page.get_text("blocks"):
        out.append((block[1], block[3], _clean_block_text(block[4])))
    out.sort(key=lambda b: b[0])
    return out


def _next_question_y(page: fitz.Page, after_y: float, printed_number: str) -> float | None:
    for y0, _y1, text in _blocks(page):
        if y0 <= after_y:
            continue
        match = _QUESTION_START.match(text)
        if match and match.group(1) != str(printed_number):
            return y0 - 8
    return None


def locate_question(page: fitz.Page, printed_number: str, hint: str) -> fitz.Rect | None:
    blocks = _blocks(page)
    start_index = None
    for index, (y0, _y1, text) in enumerate(blocks):
        if not text:
            continue
        if text.startswith(str(printed_number)) and (not hint or hint in text[:40]):
            start_index = index
            break
    if start_index is None:
        return None
    y_start = max(0.0, blocks[start_index][0] - 14)
    y_end = _next_question_y(page, blocks[start_index][0], printed_number)
    if y_end is None:
        y_end = page.rect.height - 20
    return fitz.Rect(18, y_start, page.rect.width - 18, y_end)


def _render_region(page: fitz.Page, rect: fitz.Rect, dpi: int) -> Image.Image:
    pixmap = page.get_pixmap(clip=rect, dpi=dpi)
    return Image.open(io.BytesIO(pixmap.tobytes("png"))).convert("RGB")


def render_question_image(
    pdf_path: Path,
    *,
    printed_number: str,
    hint: str,
    out_path: Path,
    dpi: int = 200,
    rotate_degrees: float = 0.0,
    jpeg_quality: int = 88,
) -> dict:
    """Crop one question (possibly across two pages) and write a photo JPEG."""
    doc = fitz.open(str(pdf_path))
    try:
        start_page = None
        rect = None
        for page_index in range(doc.page_count):
            candidate = locate_question(doc[page_index], printed_number, hint)
            if candidate is not None:
                start_page, rect = page_index, candidate
                break
        if start_page is None:
            page = doc[0]
            rect = fitz.Rect(18, 18, page.rect.width - 18, page.rect.height - 18)
            segments = [(0, rect)]
            method = "full_page_fallback"
        else:
            segments = [(start_page, rect)]
            method = "question_block"
            if rect.y1 >= doc[start_page].rect.height - 25 and start_page + 1 < doc.page_count:
                next_page = doc[start_page + 1]
                y_end = _next_question_y(next_page, 0, printed_number)
                if y_end is None:
                    y_end = next_page.rect.height - 20
                segments.append(
                    (start_page + 1, fitz.Rect(18, 18, next_page.rect.width - 18, y_end))
                )
                method = "question_block_multi_page"
        images = [_render_region(doc[index], region, dpi) for index, region in segments]
        width = max(img.width for img in images)
        gap = 16
        height = sum(img.height for img in images) + gap * (len(images) - 1)
        canvas = Image.new("RGB", (width, height), (255, 255, 255))
        y = 0
        for image in images:
            canvas.paste(image, (0, y))
            y += image.height + gap
        if rotate_degrees:
            canvas = canvas.rotate(
                rotate_degrees,
                expand=True,
                resample=Image.BICUBIC,
                fillcolor=(255, 255, 255),
            )
        out_path.parent.mkdir(parents=True, exist_ok=True)
        canvas.save(out_path, format="JPEG", quality=jpeg_quality)
        return {
            "path": str(out_path),
            "method": method,
            "segments": [
                {
                    "page_index": index,
                    "rect": [round(v, 1) for v in (region.x0, region.y0, region.x1, region.y1)],
                }
                for index, region in segments
            ],
            "width": canvas.width,
            "height": canvas.height,
            "dpi": dpi,
            "rotate_degrees": rotate_degrees,
        }
    finally:
        doc.close()
