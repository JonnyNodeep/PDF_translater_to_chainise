from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path


def _normalize_text(s: str) -> str:
    return " ".join((s or "").strip().split())


def _sha256(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class TranslationConfig:
    api_key: str
    model: str
    max_chars_per_request: int = 6000


class TranslationCache:
    def __init__(self, path: Path):
        self.path = path
        self._data: dict[str, str] = {}
        self._loaded = False

    def _load(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        if not self.path.exists():
            self._data = {}
            return
        try:
            self._data = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(self._data, dict):
                self._data = {}
        except Exception:  # noqa: BLE001
            self._data = {}

    def get(self, key: str) -> str | None:
        self._load()
        return self._data.get(key)

    def set(self, key: str, value: str) -> None:
        self._load()
        self._data[key] = value

    def save(self) -> None:
        self._load()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self._data, ensure_ascii=False, indent=2), encoding="utf-8")


class Translator:
    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        cache_path: Path,
        max_chars_per_request: int = 6000,
    ) -> None:
        self.cfg = TranslationConfig(api_key=api_key, model=model, max_chars_per_request=max_chars_per_request)
        self.cache = TranslationCache(cache_path)

    def translate_texts(self, texts: list[str]) -> list[str]:
        # Preserve length contract.
        normalized = [_normalize_text(t) for t in texts]
        keys = [_sha256(t) for t in normalized]

        out: list[str | None] = [None] * len(texts)
        missing: list[tuple[int, str]] = []
        for i, k in enumerate(keys):
            cached = self.cache.get(k)
            if cached is not None and not (normalized[i] and cached.strip() == ""):
                out[i] = cached
            else:
                missing.append((i, normalized[i]))

        if missing:
            translated_missing = self._translate_missing([t for _, t in missing])
            for (i, src), zh in zip(missing, translated_missing, strict=False):
                out[i] = zh
                # Do not cache empty translations for non-empty source (prevents permanent blanks).
                if src and not (zh or "").strip():
                    continue
                self.cache.set(keys[i], zh)
            self.cache.save()

        return [x or "" for x in out]

    def _translate_missing(self, texts: list[str]) -> list[str]:
        # Batch by char length.
        batches: list[list[str]] = []
        cur: list[str] = []
        cur_len = 0
        for t in texts:
            if not t:
                batches.append([""])
                continue
            if cur and cur_len + len(t) > self.cfg.max_chars_per_request:
                batches.append(cur)
                cur = []
                cur_len = 0
            cur.append(t)
            cur_len += len(t)
        if cur:
            batches.append(cur)

        results: list[str] = []
        for batch in batches:
            if batch == [""]:
                results.append("")
                continue
            try:
                translated = self._call_openai_list(batch)
                # If the model returns blanks for non-blank inputs, retry line-by-line for those.
                if len(translated) == len(batch):
                    for src, zh in zip(batch, translated, strict=False):
                        if src and not (zh or "").strip():
                            try:
                                retry = self._call_openai_list([src])
                                results.append(retry[0] if retry else "")
                            except Exception:  # noqa: BLE001
                                results.append("")
                        else:
                            results.append(zh)
                else:
                    results.extend(translated)
            except Exception:  # noqa: BLE001
                # Fallback: translate line-by-line for this batch.
                for t in batch:
                    try:
                        results.extend(self._call_openai_list([t]))
                    except Exception:  # noqa: BLE001
                        results.append("")
        # Ensure same length as input
        if len(results) != len(texts):
            # Pad/truncate defensively
            results = (results + [""] * len(texts))[: len(texts)]
        return results

    def _call_openai_list(self, texts: list[str]) -> list[str]:
        from openai import OpenAI  # type: ignore
        from pydantic import BaseModel

        class _Out(BaseModel):
            translations: list[str]

        client = OpenAI(api_key=self.cfg.api_key)
        instructions = (
            "Translate Russian text snippets to Simplified Chinese.\n"
            "Return results preserving the same order and length.\n"
            "Do not add any extra commentary."
        )
        payload = {"texts": texts}

        # Use structured parsing to avoid JSON formatting issues.
        resp = client.responses.parse(
            model=self.cfg.model,
            instructions=instructions,
            input=json.dumps(payload, ensure_ascii=False),
            text={"format": _Out},
        )
        parsed = resp.output_parsed
        if parsed is None:
            raise ValueError("No parsed output from model")
        data = parsed.translations
        if len(data) != len(texts):
            raise ValueError("Translation response length mismatch")
        return data

