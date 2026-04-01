from __future__ import annotations

import hashlib
import json
import re
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
    base_url: str | None = None


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
        base_url: str | None = None,
        max_chars_per_request: int = 6000,
    ) -> None:
        self.cfg = TranslationConfig(
            api_key=api_key,
            model=model,
            max_chars_per_request=max_chars_per_request,
            base_url=base_url,
        )
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
                translated = self._call_chat_list(batch)
                # If the model returns blanks for non-blank inputs, retry line-by-line for those.
                if len(translated) == len(batch):
                    for src, zh in zip(batch, translated, strict=False):
                        if src and not (zh or "").strip():
                            try:
                                retry = self._call_chat_list([src])
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
                        results.extend(self._call_chat_list([t]))
                    except Exception:  # noqa: BLE001
                        results.append("")
        # Ensure same length as input
        if len(results) != len(texts):
            # Pad/truncate defensively
            results = (results + [""] * len(texts))[: len(texts)]
        return results

    def _call_chat_list(self, texts: list[str]) -> list[str]:
        from openai import OpenAI  # type: ignore

        kwargs: dict = {"api_key": self.cfg.api_key}
        if self.cfg.base_url:
            kwargs["base_url"] = self.cfg.base_url
        client = OpenAI(**kwargs)

        system = (
            "Translate Russian text snippets to Simplified Chinese.\n"
            "Respond with a JSON object only: {\"translations\": [\"...\", ...]}.\n"
            "The translations array must have exactly the same length and order as the input texts."
        )
        user_content = json.dumps({"texts": texts}, ensure_ascii=False)

        def _parse_translations(content: str) -> list[str]:
            obj = _parse_json_object(content)
            data = obj.get("translations")
            if not isinstance(data, list):
                raise ValueError("Missing translations array")
            if len(data) != len(texts):
                raise ValueError("Translation response length mismatch")
            return [str(x) for x in data]

        try:
            resp = client.chat.completions.create(
                model=self.cfg.model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user_content},
                ],
                response_format={"type": "json_object"},
            )
        except Exception:
            resp = client.chat.completions.create(
                model=self.cfg.model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user_content},
                ],
            )

        raw = (resp.choices[0].message.content or "").strip()
        if not raw:
            raise ValueError("Empty model response")
        return _parse_translations(raw)


def _parse_json_object(text: str) -> dict:
    s = text.strip()
    if s.startswith("```"):
        m = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", s)
        if m:
            s = m.group(1).strip()
    data = json.loads(s)
    if not isinstance(data, dict):
        raise ValueError("Expected JSON object")
    return data

