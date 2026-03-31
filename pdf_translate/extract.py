from __future__ import annotations

from dataclasses import dataclass

import fitz  # PyMuPDF


@dataclass(frozen=True)
class TextSpanItem:
    page_index: int
    rect: fitz.Rect
    text: str
    source_fontsize: float


@dataclass(frozen=True)
class TextLineItem:
    page_index: int
    rect: fitz.Rect
    text: str
    source_fontsize: float


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
                    size = span.get("size")
                    try:
                        fontsize = float(size) if size is not None else 12.0
                    except Exception:  # noqa: BLE001
                        fontsize = 12.0
                    items.append(TextSpanItem(page_index=page_index, rect=rect, text=text, source_fontsize=fontsize))
                    char_count += len(text)

        spans_by_page[page_index] = items
        page_char_counts[page_index] = char_count

    return spans_by_page, page_char_counts


def extract_text_lines_by_page(
    doc: fitz.Document,
    *,
    min_bbox_area: float = 4.0,
) -> tuple[dict[int, list[TextLineItem]], dict[int, int]]:
    lines_by_page: dict[int, list[TextLineItem]] = {}
    page_char_counts: dict[int, int] = {}

    for page_index in range(doc.page_count):
        page = doc.load_page(page_index)
        d = page.get_text("dict")
        items: list[TextLineItem] = []
        char_count = 0

        for block in d.get("blocks", []):
            for line in block.get("lines", []):
                spans = line.get("spans", []) or []
                parts: list[str] = []
                rect_union: fitz.Rect | None = None
                line_bbox = line.get("bbox")
                if line_bbox and isinstance(line_bbox, (list, tuple)) and len(line_bbox) == 4:
                    try:
                        rect_union = fitz.Rect(line_bbox)
                    except Exception:  # noqa: BLE001
                        rect_union = None
                for span in spans:
                    t = (span.get("text") or "").strip()
                    if not t:
                        continue
                    bbox = span.get("bbox")
                    if not bbox or len(bbox) != 4:
                        continue
                    r = fitz.Rect(bbox)
                    if _bbox_area(r) < min_bbox_area:
                        continue
                    rect_union = r if rect_union is None else (rect_union | r)
                    parts.append(t)
                if not parts or rect_union is None:
                    continue
                text = " ".join(parts).strip()
                if not text:
                    continue
                # Prefer the line's first span fontsize if available, else default.
                first_size = None
                for span in spans:
                    if (span.get("text") or "").strip():
                        first_size = span.get("size")
                        break
                try:
                    fontsize = float(first_size) if first_size is not None else 12.0
                except Exception:  # noqa: BLE001
                    fontsize = 12.0
                items.append(TextLineItem(page_index=page_index, rect=rect_union, text=text, source_fontsize=fontsize))
                char_count += len(text)

        lines_by_page[page_index] = items
        page_char_counts[page_index] = char_count

    return lines_by_page, page_char_counts


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

