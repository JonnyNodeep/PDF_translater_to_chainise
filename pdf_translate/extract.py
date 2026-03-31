from __future__ import annotations

from dataclasses import dataclass

import fitz  # PyMuPDF


@dataclass(frozen=True)
class TextSpanItem:
    page_index: int
    rect: fitz.Rect
    text: str


def _bbox_area(rect: fitz.Rect) -> float:
    return max(0.0, (rect.x1 - rect.x0)) * max(0.0, (rect.y1 - rect.y0))


def extract_text_spans_by_page(
    doc: fitz.Document,
    *,
    min_bbox_area: float = 4.0,
) -> tuple[dict[int, list[TextSpanItem]], dict[int, int]]:
    spans_by_page: dict[int, list[TextSpanItem]] = {}
    page_char_counts: dict[int, int] = {}

    for page_index in range(doc.page_count):
        page = doc.load_page(page_index)
        d = page.get_text("dict")
        items: list[TextSpanItem] = []
        char_count = 0

        for block in d.get("blocks", []):
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    text = (span.get("text") or "").strip()
                    if not text:
                        continue
                    bbox = span.get("bbox")
                    if not bbox or len(bbox) != 4:
                        continue
                    rect = fitz.Rect(bbox)
                    if _bbox_area(rect) < min_bbox_area:
                        continue
                    items.append(TextSpanItem(page_index=page_index, rect=rect, text=text))
                    char_count += len(text)

        spans_by_page[page_index] = items
        page_char_counts[page_index] = char_count

    return spans_by_page, page_char_counts


PageMode = str  # "text" | "ocr"


def decide_page_modes(
    *,
    doc_page_count: int,
    page_char_counts: dict[int, int],
    min_chars_per_page: int,
    force_ocr: bool,
) -> list[PageMode]:
    modes: list[PageMode] = []
    for page_index in range(doc_page_count):
        if force_ocr:
            modes.append("ocr")
            continue
        chars = page_char_counts.get(page_index, 0)
        modes.append("text" if chars >= min_chars_per_page else "ocr")
    return modes

