# pdf_translate (RU → ZH)

Отдельный модуль для перевода PDF с русского на китайский (упрощённый) с попыткой сохранить разметку (позиции текста по bbox).

## Установка

В корне проекта:

```bash
python -m pip install -e .
```

## Конфигурация (.env)

В корне репозитория файл `.env`:

- `DEEPSEEK_API_KEY` (рекомендуется; перевод через [DeepSeek](https://api.deepseek.com), модель по умолчанию `deepseek-chat`)
- либо `OPENAI_API_KEY` для OpenAI (модель по умолчанию `gpt-4.1-mini`)
- опционально `PDF_TRANSLATE_BASE_URL` (если задан хост DeepSeek, модель по умолчанию `deepseek-chat` даже при ключе в `OPENAI_API_KEY`)
- `PDF_TRANSLATE_MODEL` (переопределение модели)
- `PDF_FONT_PATH` (путь к `.ttf` с поддержкой CJK, напр. Noto Sans SC)
- `PDF_START_FONTSIZE` (стартовый размер шрифта для вставки; например `14` или `16`)
- `PDF_MAX_FONTSIZE` (верхний лимит для OCR/общий; например `18` или `24`)
- `PDF_LINE_HEIGHT_MULT` (межстрочный множитель; например `1.0` для более крупного текста в том же bbox)

Если `PDF_FONT_PATH` не задан, некоторые просмотрщики могут показывать китайский как “квадратики”.

## Запуск

```bash
python -m pdf_translate.cli --in "input.pdf" --out "output_zh.pdf"
```

Опции:
- `--force-ocr`: OCR для всех страниц
- `--dry-run`: не сохранять PDF (прогон пайплайна)

## Тестовые файлы

Рекомендуется держать 3 файла для ручной проверки (в git не обязательно):
- text PDF (1–2 страницы)
- scan PDF (1–2 страницы)
- mixed PDF (3–5 страниц)

