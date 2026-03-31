from __future__ import annotations

from dataclasses import dataclass

import fitz  # PyMuPDF


@dataclass(frozen=True)
class RenderOptions:
    font_path: str | None
    font_name: str = "cjk"
    start_fontsize: float = 12.0
    min_fontsize: float = 2.0
    step: float = 0.25
    line_height_mult: float = 1.05
    # Always pass fontfile for custom CJK fonts; redactions can drop embedded font resources.
    use_fontfile_in_insert: bool = True


def _get_font(opts: RenderOptions) -> fitz.Font:
    if opts.font_path:
        return fitz.Font(fontfile=opts.font_path)
    return fitz.Font(fontname="helv")


def _measure_text_width(font: fitz.Font, text: str, fontsize: float) -> float:
    # PyMuPDF font.text_length handles unicode, including CJK.
    return float(font.text_length(text, fontsize))


def _wrap_text(text: str, *, font: fitz.Font, fontsize: float, max_width: float) -> list[str]:
    s = (text or "").strip()
    if not s:
        return [""]

    # Prefer word wrap when spaces exist; otherwise wrap by characters (good for CJK).
    tokens = s.split(" ")
    if len(tokens) > 1:
        parts: list[str] = []
        for t in tokens:
            if t == "":
                continue
            parts.append(t)
        lines: list[str] = []
        cur = ""
        for w in parts:
            candidate = w if not cur else f"{cur} {w}"
            if _measure_text_width(font, candidate, fontsize) <= max_width:
                cur = candidate
            else:
                if cur:
                    lines.append(cur)
                # If a single word is too long, fall back to char wrapping.
                if _measure_text_width(font, w, fontsize) <= max_width:
                    cur = w
                else:
                    lines.extend(_wrap_text(w, font=font, fontsize=fontsize, max_width=max_width))
                    cur = ""
        if cur:
            lines.append(cur)
        return lines or [s]

    # Char wrap (CJK-safe)
    lines = []
    cur = ""
    for ch in s:
        if ch == "\n":
            lines.append(cur)
            cur = ""
            continue
        candidate = cur + ch
        if _measure_text_width(font, candidate, fontsize) <= max_width:
            cur = candidate
        else:
            if cur:
                lines.append(cur)
            cur = ch
    if cur or not lines:
        lines.append(cur)
    return lines


def _fit_text_to_rect(text: str, rect: fitz.Rect, opts: RenderOptions) -> tuple[float, str] | None:
    font = _get_font(opts)
    max_width = max(0.0, rect.width)
    max_height = max(0.0, rect.height)
    if max_width <= 0 or max_height <= 0:
        return None

    fontsize = float(opts.start_fontsize)
    while fontsize >= float(opts.min_fontsize) - 1e-9:
        lines = _wrap_text(text, font=font, fontsize=fontsize, max_width=max_width)
        line_h = fontsize * float(opts.line_height_mult)
        if (len(lines) * line_h) <= max_height + 1e-6:
            return fontsize, "\n".join(lines)
        fontsize -= float(opts.step)
    return None


def _insert_textbox(
    page: fitz.Page,
    rect: fitz.Rect,
    text_wrapped: str,
    fontsize: float,
    opts: RenderOptions,
    color: tuple[float, float, float] = (0, 0, 0),
) -> bool:
    ff = opts.font_path if opts.use_fontfile_in_insert else None
    rc = page.insert_textbox(
        rect,
        text_wrapped,
        fontsize=fontsize,
        fontname=opts.font_name,
        fontfile=ff,
        color=color,
        align=fitz.TEXT_ALIGN_LEFT,
    )
    return rc >= 0


def _insert_text_fallback_point(
    page: fitz.Page,
    rect: fitz.Rect,
    text: str,
    opts: RenderOptions,
) -> bool:
    """Last resort: single-line text at top-left of rect, tiny font."""
    s = (text or "").strip()
    if not s:
        return False
    fontsize = float(opts.min_fontsize)
    p = fitz.Point(rect.x0 + 1, rect.y0 + fontsize)
    ff = opts.font_path if opts.use_fontfile_in_insert else None
    try:
        page.insert_text(
            p,
            s[:2000],
            fontsize=fontsize,
            fontname=opts.font_name,
            fontfile=ff,
            color=(0, 0, 0),
        )
        return True
    except Exception:  # noqa: BLE001
        return False


def _find_fontsize_with_scratch_page(
    *,
    page: fitz.Page,
    rect: fitz.Rect,
    text: str,
    opts: RenderOptions,
) -> float | None:
    # Use MuPDF's own layouting on a scratch page to see whether text can fit.
    # This avoids "redact then fail => blank hole".
    scratch_doc = fitz.open()
    scratch_page = scratch_doc.new_page(width=page.rect.width, height=page.rect.height)
    if opts.font_path and not opts.use_fontfile_in_insert:
        try:
            scratch_page.insert_font(fontname=opts.font_name, fontfile=opts.font_path)
        except Exception:  # noqa: BLE001
            pass
    ff = opts.font_path if opts.use_fontfile_in_insert else None
    fontsize = float(opts.start_fontsize)
    while fontsize >= float(opts.min_fontsize) - 1e-9:
        rc = scratch_page.insert_textbox(
            rect,
            text,
            fontsize=fontsize,
            fontname=opts.font_name,
            fontfile=ff,
            color=(0, 0, 0),
            align=fitz.TEXT_ALIGN_LEFT,
        )
        if rc >= 0:
            return fontsize
        fontsize -= float(opts.step)
    return None


def _expanded_rect(page: fitz.Page, rect: fitz.Rect) -> fitz.Rect:
    # Heuristic: PDF span bboxes are often tight to glyphs; translated text needs extra vertical room.
    # Expand mostly downward, with small padding around. Clamp to page bounds.
    pad_x = 1.0
    pad_y_top = 0.5
    extra_down = max(6.0, rect.height * 1.8)
    r = fitz.Rect(rect.x0 - pad_x, rect.y0 - pad_y_top, rect.x1 + pad_x, rect.y1 + extra_down)
    return r & page.rect


def _expanded_rect_wide(page: fitz.Page, rect: fitz.Rect) -> fitz.Rect:
    # Aggressive fallback: allow wrapping across the remaining page width
    # and more vertical space. Used only when normal fitting fails.
    extra_h = min(400.0, max(120.0, page.rect.height - rect.y0 - 4.0))
    r = fitz.Rect(rect.x0, rect.y0, page.rect.x1 - 2.0, min(page.rect.y1 - 2.0, rect.y1 + extra_h))
    return r & page.rect


def redact_and_insert(page: fitz.Page, rect: fitz.Rect, text: str, opts: RenderOptions) -> bool:
    # IMPORTANT: never create a blank hole. We only redact if we know the translation will fit.
    fit = _fit_text_to_rect(text, rect, opts)
    if fit is not None:
        fontsize, wrapped = fit
        page.add_redact_annot(rect, fill=(1, 1, 1))
        page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE)
        ok = _insert_textbox(page, rect, wrapped, fontsize, opts)
        return ok if ok else _insert_text_fallback_point(page, rect, text, opts)

    # Try again with an expanded rect (but redact only original rect).
    rect2 = _expanded_rect(page, rect)
    fit2 = _fit_text_to_rect(text, rect2, opts)
    if fit2 is not None:
        fontsize, wrapped = fit2
        page.add_redact_annot(rect, fill=(1, 1, 1))
        page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE)
        ok = _insert_textbox(page, rect2, wrapped, fontsize, opts)
        return ok if ok else _insert_text_fallback_point(page, rect, text, opts)

    # Last resort: use a wide box to preserve content (may wrap more but avoids missing translations).
    rect3 = _expanded_rect_wide(page, rect)
    fit3 = _fit_text_to_rect(text, rect3, opts)
    if fit3 is not None:
        fontsize, wrapped = fit3
        page.add_redact_annot(rect, fill=(1, 1, 1))
        page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE)
        ok = _insert_textbox(page, rect3, wrapped, fontsize, opts)
        return ok if ok else _insert_text_fallback_point(page, rect, text, opts)
    fontsize3 = _find_fontsize_with_scratch_page(page=page, rect=rect3, text=text, opts=opts)
    if fontsize3 is not None:
        page.add_redact_annot(rect, fill=(1, 1, 1))
        page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE)
        # Let MuPDF wrap text inside the box.
        ok = _insert_textbox(page, rect3, text, fontsize3, opts)
        if ok:
            return True
        return _insert_text_fallback_point(page, rect, text, opts)

    # Fallback: try MuPDF's textbox fitting on a scratch page. If it fits there,
    # we render via overlay (safe) to guarantee visibility.
    fontsize = _find_fontsize_with_scratch_page(page=page, rect=rect, text=text, opts=opts)
    if fontsize is None:
        page.draw_rect(rect, color=None, fill=(1, 1, 1))
        return _insert_text_fallback_point(page, rect, text, opts)
    page.draw_rect(rect, color=None, fill=(1, 1, 1))
    ok = _insert_textbox(page, rect, text, fontsize, opts)
    if ok:
        return True
    return _insert_text_fallback_point(page, rect, text, opts)


def overlay_and_insert(page: fitz.Page, rect: fitz.Rect, text: str, opts: RenderOptions) -> bool:
    # Never draw overlay if translation won't fit.
    fit = _fit_text_to_rect(text, rect, opts)
    if fit is None:
        rect2 = _expanded_rect(page, rect)
        fit = _fit_text_to_rect(text, rect2, opts)
        if fit is None:
            rect3 = _expanded_rect_wide(page, rect)
            fit = _fit_text_to_rect(text, rect3, opts)
            if fit is None:
                fontsize3 = _find_fontsize_with_scratch_page(page=page, rect=rect3, text=text, opts=opts)
                if fontsize3 is None:
                    return False
                page.draw_rect(rect, color=None, fill=(1, 1, 1))
                return _insert_textbox(page, rect3, text, fontsize3, opts)
            fontsize, wrapped = fit
            page.draw_rect(rect, color=None, fill=(1, 1, 1))
            return _insert_textbox(page, rect3, wrapped, fontsize, opts)
        fontsize, wrapped = fit
        page.draw_rect(rect, color=None, fill=(1, 1, 1))
        return _insert_textbox(page, rect2, wrapped, fontsize, opts)
    fontsize, wrapped = fit
    page.draw_rect(rect, color=None, fill=(1, 1, 1))
    return _insert_textbox(page, rect, wrapped, fontsize, opts)

