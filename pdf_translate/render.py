from __future__ import annotations

from dataclasses import dataclass

import fitz  # PyMuPDF


@dataclass(frozen=True)
class RenderOptions:
    font_path: str | None
    font_name: str = "cjk"
    start_fontsize: float = 12.0
    min_fontsize: float = 5.0
    step: float = 0.8


def _insert_textbox_fit(
    page: fitz.Page,
    rect: fitz.Rect,
    text: str,
    opts: RenderOptions,
    color: tuple[float, float, float] = (0, 0, 0),
) -> bool:
    fontsize = opts.start_fontsize
    while fontsize >= opts.min_fontsize:
        rc = page.insert_textbox(
            rect,
            text,
            fontsize=fontsize,
            fontname=opts.font_name,
            fontfile=opts.font_path,
            color=color,
            align=fitz.TEXT_ALIGN_LEFT,
        )
        if rc >= 0:
            return True
        fontsize -= opts.step
    return False


def redact_and_insert(page: fitz.Page, rect: fitz.Rect, text: str, opts: RenderOptions) -> bool:
    # Redact (white fill) then insert translation.
    page.add_redact_annot(rect, fill=(1, 1, 1))
    page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE)
    return _insert_textbox_fit(page, rect, text, opts)


def overlay_and_insert(page: fitz.Page, rect: fitz.Rect, text: str, opts: RenderOptions) -> bool:
    # Draw white rectangle overlay then insert.
    page.draw_rect(rect, color=None, fill=(1, 1, 1))
    return _insert_textbox_fit(page, rect, text, opts)

