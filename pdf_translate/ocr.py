from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO

import fitz  # PyMuPDF
from PIL import Image


@dataclass(frozen=True)
class OcrItem:
    page_index: int
    rect: fitz.Rect
    text: str
    score: float


def _get_ocr_engine(langs: str):
    # Lazy import: PaddleOCR is heavy and optional until OCR is needed.
    from paddleocr import PaddleOCR  # type: ignore

    lang = "en"  # PaddleOCR uses a single `lang` setting; we keep `langs` for config symmetry.
    # Basic heuristic: if ru present, use multilingual model if available.
    if "ru" in {x.strip().lower() for x in langs.split(",") if x.strip()}:
        lang = "en"  # Many installs use en; users can change by setting PDF_OCR_LANGS and code can be extended.
    return PaddleOCR(use_angle_cls=True, lang=lang)


def _pixmap_to_pil(pix: fitz.Pixmap) -> Image.Image:
    if pix.alpha:
        pix = fitz.Pixmap(pix, 0)  # drop alpha
    img_bytes = pix.tobytes("png")
    return Image.open(BytesIO(img_bytes)).convert("RGB")


def _poly_to_rect(poly) -> tuple[float, float, float, float] | None:
    # poly is expected like [[x,y],[x,y],[x,y],[x,y]]
    try:
        xs = [p[0] for p in poly]
        ys = [p[1] for p in poly]
        return (min(xs), min(ys), max(xs), max(ys))
    except Exception:  # noqa: BLE001
        return None


def ocr_items_for_page(
    *,
    page: fitz.Page,
    dpi: int,
    langs: str,
    min_score: float = 0.5,
) -> list[OcrItem]:
    pix = page.get_pixmap(dpi=dpi)
    img = _pixmap_to_pil(pix)

    engine = _get_ocr_engine(langs)
    # PaddleOCR returns: [ [ [poly], (text, score) ], ... ]
    result = engine.ocr(img, cls=True)
    if not result:
        return []

    page_rect = page.rect
    sx = page_rect.width / float(img.width)
    sy = page_rect.height / float(img.height)

    items: list[OcrItem] = []
    seen: set[tuple[int, int, int, int, str]] = set()

    for entry in result[0] if isinstance(result, list) and result and isinstance(result[0], list) else result:
        try:
            poly, payload = entry
            text, score = payload
        except Exception:  # noqa: BLE001
            continue

        text = (text or "").strip()
        if not text:
            continue
        try:
            score_f = float(score)
        except Exception:  # noqa: BLE001
            score_f = 0.0
        if score_f < min_score:
            continue

        rect_px = _poly_to_rect(poly)
        if rect_px is None:
            continue
        x0, y0, x1, y1 = rect_px

        # Map px->pt and flip y from image-top origin to PDF-top origin by using page_rect.
        pdf_x0 = page_rect.x0 + x0 * sx
        pdf_x1 = page_rect.x0 + x1 * sx
        pdf_y0 = page_rect.y0 + y0 * sy
        pdf_y1 = page_rect.y0 + y1 * sy
        rect = fitz.Rect(pdf_x0, pdf_y0, pdf_x1, pdf_y1)

        key = (round(rect.x0), round(rect.y0), round(rect.x1), round(rect.y1), text)
        if key in seen:
            continue
        seen.add(key)

        items.append(OcrItem(page_index=page.number, rect=rect, text=text, score=score_f))

    return items

