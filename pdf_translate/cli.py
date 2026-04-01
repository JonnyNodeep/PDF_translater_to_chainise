from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

import fitz  # PyMuPDF

from pdf_translate.config import PdfTranslateConfig, load_config
from pdf_translate.background import pick_text_rgb, render_page_image, rgb255_to_float, sample_background_rgb
from pdf_translate.extract import decide_page_modes, extract_text_lines_by_page, extract_text_spans_by_page
from pdf_translate.ocr import ocr_items_for_page
from pdf_translate.render import RenderOptions, overlay_with_bg_and_insert
from pdf_translate.translate import Translator


log = logging.getLogger("pdf_translate")


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m pdf_translate.cli",
        description="Translate PDF from Russian to Simplified Chinese, preserving layout via bbox.",
    )
    p.add_argument("--in", dest="in_path", required=True, help="Input PDF path")
    p.add_argument("--out", dest="out_path", required=True, help="Output PDF path")
    p.add_argument(
        "--force-ocr",
        action="store_true",
        help="Force OCR for all pages (ignore text layer).",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Run extract/translate/render but do not save output PDF.",
    )
    return p


def _configure_logging() -> None:
    level = os.getenv("PDF_TRANSLATE_LOG_LEVEL", "INFO").upper()
    logging.basicConfig(level=getattr(logging, level, logging.INFO), format="%(levelname)s %(message)s")


def main(argv: list[str] | None = None) -> int:
    _configure_logging()
    args = _build_parser().parse_args(argv)

    in_path = Path(args.in_path)
    out_path = Path(args.out_path)

    if not in_path.exists() or not in_path.is_file():
        log.error("Input file does not exist: %s", in_path)
        return 2
    if in_path.suffix.lower() != ".pdf":
        log.error("Input file must be a .pdf: %s", in_path)
        return 2

    try:
        cfg: PdfTranslateConfig = load_config()
    except Exception as e:  # noqa: BLE001
        log.error("%s", e)
        return 2

    if not cfg.translate_api_key:
        log.error("Missing DEEPSEEK_API_KEY or OPENAI_API_KEY in environment / .env")
        return 2

    if cfg.font_path is None:
        log.warning("PDF_FONT_PATH is not set; Chinese glyphs may show as squares in some viewers.")
    else:
        fp = Path(cfg.font_path)
        if not fp.exists():
            log.warning("PDF_FONT_PATH does not exist: %s", fp)

    doc = fitz.open(str(in_path))
    log.info("Pages: %d", doc.page_count)

    if cfg.text_unit == "span":
        spans_by_page, page_char_counts = extract_text_spans_by_page(doc, min_bbox_area=cfg.min_span_bbox_area)
        text_items_by_page = spans_by_page
    else:
        lines_by_page, page_char_counts = extract_text_lines_by_page(doc, min_bbox_area=cfg.min_span_bbox_area)
        text_items_by_page = lines_by_page
    modes = decide_page_modes(
        doc_page_count=doc.page_count,
        page_char_counts=page_char_counts,
        min_chars_per_page=cfg.min_text_chars_per_page,
        force_ocr=args.force_ocr,
    )

    total_items = sum(len(v) for v in text_items_by_page.values())
    log.info("Extracted text items (%s): %d", cfg.text_unit, total_items)

    translator = Translator(
        api_key=cfg.translate_api_key,
        model=cfg.translate_model,
        base_url=cfg.translate_base_url,
        cache_path=cfg.cache_path,
        max_chars_per_request=cfg.max_chars_per_request,
    )

    render_opts = RenderOptions(
        font_path=cfg.font_path,
        start_fontsize=cfg.start_fontsize,
        max_fontsize=cfg.max_fontsize,
        min_fontsize=cfg.min_fontsize,
        step=cfg.font_step,
        line_height_mult=cfg.line_height_mult,
    )

    for page_index in range(doc.page_count):
        mode = modes[page_index]
        log.info("Page %d/%d mode=%s", page_index + 1, doc.page_count, mode)
        page = doc.load_page(page_index)
        # Note: do not rely on page.insert_font alone — apply_redactions() can drop embedded fonts;
        # insert_textbox must pass fontfile each time when using a custom CJK font.

        try:
            if mode == "text":
                page_img = render_page_image(page, dpi=cfg.render_dpi)
                items = text_items_by_page.get(page_index, [])
                if not items:
                    continue
                src_texts = [it.text for it in items]
                translations = translator.translate_texts(src_texts)
                render_fail = 0
                fail_samples: list[tuple[str, str]] = []
                for it, zh in zip(items, translations, strict=False):
                    if not zh.strip():
                        continue
                    bg = sample_background_rgb(page_img, it.rect)
                    fg = pick_text_rgb(bg)
                    ok = overlay_with_bg_and_insert(
                        page,
                        it.rect,
                        zh,
                        render_opts,
                        bg_fill=rgb255_to_float(bg),
                        text_color=rgb255_to_float(fg),
                        start_fontsize=getattr(it, "source_fontsize", None),
                    )
                    if not ok:
                        render_fail += 1
                        if len(fail_samples) < 5:
                            fail_samples.append((it.text, zh))
                if render_fail:
                    log.warning("Page %d: render failures (text)=%d", page_index + 1, render_fail)
                    for src, zh in fail_samples:
                        log.warning("  sample_fail src=%r zh=%r", src[:80], zh[:80])
            else:
                ocr_items = ocr_items_for_page(
                    page=page,
                    dpi=cfg.ocr_dpi,
                    langs=cfg.ocr_langs,
                    min_score=cfg.ocr_min_score,
                )
                if not ocr_items:
                    continue
                page_img = render_page_image(page, dpi=cfg.render_dpi)
                src_texts = [it.text for it in ocr_items]
                translations = translator.translate_texts(src_texts)
                render_fail = 0
                for it, zh in zip(ocr_items, translations, strict=False):
                    if not zh.strip():
                        continue
                    bg = sample_background_rgb(page_img, it.rect)
                    fg = pick_text_rgb(bg)
                    ok = overlay_with_bg_and_insert(
                        page,
                        it.rect,
                        zh,
                        render_opts,
                        bg_fill=rgb255_to_float(bg),
                        text_color=rgb255_to_float(fg),
                        start_fontsize=None,
                    )
                    if not ok:
                        render_fail += 1
                if render_fail:
                    log.warning("Page %d: render failures (ocr)=%d", page_index + 1, render_fail)
        except Exception as e:  # noqa: BLE001
            log.exception("Failed processing page %d: %s", page_index + 1, e)
            # Best-effort: continue other pages.
            continue

    if args.dry_run:
        log.info("Dry-run enabled: not saving output.")
        return 0

    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_out = out_path.with_suffix(out_path.suffix + ".tmp")
    if tmp_out.exists():
        try:
            tmp_out.unlink()
        except Exception:  # noqa: BLE001
            pass

    doc.save(str(tmp_out))
    try:
        tmp_out.replace(out_path)
        log.info("Saved: %s", out_path)
    except Exception as e:  # noqa: BLE001
        # Common on Windows: output is open in a viewer -> permission denied.
        alt_out = out_path.with_name(out_path.stem + "_new" + out_path.suffix)
        tmp_out.replace(alt_out)
        log.warning("Could not overwrite output (%s). Saved to: %s (%s)", out_path, alt_out, e)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

