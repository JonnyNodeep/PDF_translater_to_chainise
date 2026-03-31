from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

import fitz  # PyMuPDF

from pdf_translate.config import PdfTranslateConfig, load_config
from pdf_translate.extract import extract_text_spans_by_page, decide_page_modes
from pdf_translate.ocr import ocr_items_for_page
from pdf_translate.render import RenderOptions, overlay_and_insert, redact_and_insert
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

    if not cfg.openai_api_key:
        log.error("Missing OPENAI_API_KEY in environment / .env")
        return 2

    if cfg.font_path is None:
        log.warning("PDF_FONT_PATH is not set; Chinese glyphs may show as squares in some viewers.")
    else:
        fp = Path(cfg.font_path)
        if not fp.exists():
            log.warning("PDF_FONT_PATH does not exist: %s", fp)

    doc = fitz.open(str(in_path))
    log.info("Pages: %d", doc.page_count)

    spans_by_page, page_char_counts = extract_text_spans_by_page(doc, min_bbox_area=cfg.min_span_bbox_area)
    modes = decide_page_modes(
        doc_page_count=doc.page_count,
        page_char_counts=page_char_counts,
        min_chars_per_page=cfg.min_text_chars_per_page,
        force_ocr=args.force_ocr,
    )

    total_spans = sum(len(v) for v in spans_by_page.values())
    log.info("Extracted text spans: %d", total_spans)

    translator = Translator(
        api_key=cfg.openai_api_key,
        model=cfg.translate_model,
        cache_path=cfg.cache_path,
        max_chars_per_request=cfg.max_chars_per_request,
    )

    render_opts = RenderOptions(font_path=cfg.font_path)

    for page_index in range(doc.page_count):
        mode = modes[page_index]
        log.info("Page %d/%d mode=%s", page_index + 1, doc.page_count, mode)
        page = doc.load_page(page_index)
        try:
            if mode == "text":
                items = spans_by_page.get(page_index, [])
                if not items:
                    continue
                src_texts = [it.text for it in items]
                translations = translator.translate_texts(src_texts)
                for it, zh in zip(items, translations, strict=False):
                    if not zh.strip():
                        continue
                    redact_and_insert(page, it.rect, zh, render_opts)
            else:
                ocr_items = ocr_items_for_page(
                    page=page,
                    dpi=cfg.ocr_dpi,
                    langs=cfg.ocr_langs,
                    min_score=cfg.ocr_min_score,
                )
                if not ocr_items:
                    continue
                src_texts = [it.text for it in ocr_items]
                translations = translator.translate_texts(src_texts)
                for it, zh in zip(ocr_items, translations, strict=False):
                    if not zh.strip():
                        continue
                    overlay_and_insert(page, it.rect, zh, render_opts)
        except Exception as e:  # noqa: BLE001
            log.exception("Failed processing page %d: %s", page_index + 1, e)
            # Best-effort: continue other pages.
            continue

    if args.dry_run:
        log.info("Dry-run enabled: not saving output.")
        return 0

    out_path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(out_path))
    log.info("Saved: %s", out_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

