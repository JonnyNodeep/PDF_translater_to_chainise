from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _parse_dotenv(path: Path) -> dict[str, str]:
    if not path.exists() or not path.is_file():
        return {}
    data: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("\"'")  # very small .env parser (MVP)
        if key:
            data[key] = value
    return data


def _env_get(key: str, dotenv: dict[str, str]) -> str | None:
    v = os.getenv(key)
    if v is not None and v != "":
        return v
    v = dotenv.get(key)
    if v is not None and v != "":
        return v
    return None


def _env_get_int(key: str, dotenv: dict[str, str], default: int) -> int:
    v = _env_get(key, dotenv)
    if v is None:
        return default
    try:
        return int(v)
    except ValueError:
        return default


def _env_get_float(key: str, dotenv: dict[str, str], default: float) -> float:
    v = _env_get(key, dotenv)
    if v is None:
        return default
    try:
        return float(v)
    except ValueError:
        return default


@dataclass(frozen=True)
class PdfTranslateConfig:
    openai_api_key: str | None
    translate_model: str
    font_path: str | None
    min_fontsize: float
    font_step: float
    text_unit: str
    min_text_chars_per_page: int
    max_chars_per_request: int
    ocr_langs: str
    ocr_dpi: int
    render_dpi: int
    ocr_min_score: float
    min_span_bbox_area: float
    cache_path: Path


def load_config(project_root: Path | None = None) -> PdfTranslateConfig:
    root = project_root or Path.cwd()
    dotenv_path = root / ".env"
    dotenv = _parse_dotenv(dotenv_path)

    openai_api_key = _env_get("OPENAI_API_KEY", dotenv)
    translate_model = _env_get("PDF_TRANSLATE_MODEL", dotenv) or "gpt-4.1-mini"
    font_path = _env_get("PDF_FONT_PATH", dotenv)
    min_fontsize = _env_get_float("PDF_MIN_FONTSIZE", dotenv, default=3.0)
    font_step = _env_get_float("PDF_FONT_STEP", dotenv, default=0.5)
    text_unit = (_env_get("PDF_TEXT_UNIT", dotenv) or "span").strip().lower()
    if text_unit not in {"line", "span"}:
        text_unit = "span"
    min_text_chars_per_page = _env_get_int("PDF_MIN_TEXT_CHARS_PER_PAGE", dotenv, default=40)
    max_chars_per_request = _env_get_int("PDF_MAX_CHARS_PER_REQUEST", dotenv, default=6000)
    ocr_langs = _env_get("PDF_OCR_LANGS", dotenv) or "en,ru"
    ocr_dpi = _env_get_int("PDF_OCR_DPI", dotenv, default=200)
    render_dpi = _env_get_int("PDF_RENDER_DPI", dotenv, default=180)
    ocr_min_score = _env_get_float("PDF_OCR_MIN_SCORE", dotenv, default=0.5)
    min_span_bbox_area = _env_get_float("PDF_MIN_SPAN_BBOX_AREA", dotenv, default=4.0)

    cache_path_str = _env_get("PDF_TRANSLATE_CACHE_PATH", dotenv)
    cache_path = Path(cache_path_str) if cache_path_str else (root / "pdf_translate" / "cache" / "ru_zh_cache.json")

    return PdfTranslateConfig(
        openai_api_key=openai_api_key,
        translate_model=translate_model,
        font_path=font_path,
        min_fontsize=min_fontsize,
        font_step=font_step,
        text_unit=text_unit,
        min_text_chars_per_page=min_text_chars_per_page,
        max_chars_per_request=max_chars_per_request,
        ocr_langs=ocr_langs,
        ocr_dpi=ocr_dpi,
        render_dpi=render_dpi,
        ocr_min_score=ocr_min_score,
        min_span_bbox_area=min_span_bbox_area,
        cache_path=cache_path,
    )

