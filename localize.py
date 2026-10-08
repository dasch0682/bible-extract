"""Short texts (speaker names, event labels) written in the target language by a model.

The model only translates a short label that comes from a dataset; it is never a source.
The answer is accepted only as a short, single-line text, and cached per kind, language,
prompt version and model. The caller injects `call(system, user) -> str | None`, so this
module holds no model identifier and makes no network call of its own.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import unicodedata
from pathlib import Path

MAX_WORDS = 12


def slug(s: str) -> str:
    s = "".join(ch for ch in unicodedata.normalize("NFD", s or "") if unicodedata.category(ch) != "Mn")
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:40]


def write_atomic(path: Path, text: str) -> None:
    """Write a cache file so that a concurrent reader sees the old file or the whole new one, never half of it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def clean_text(raw, max_words: int = MAX_WORDS):
    """A model answer is accepted only as a short, single-line text without markup; otherwise None."""
    if not isinstance(raw, str):
        return None
    text = raw.strip().strip('"«»“”\'').strip()
    if not text or "\n" in text or len(text.split()) > max_words or any(c in text for c in "{}[]<>"):
        return None
    return text


def _cache_path(cache_dir, kind: str, text: str, lang: str, prompt_version: str, model: str, extra: str) -> Path:
    digest = hashlib.sha1(f"{text}\x00{extra}".encode("utf-8")).hexdigest()[:8]
    return Path(cache_dir) / kind / lang / f"{slug(text)}-{digest}.{prompt_version}.{slug(model)}.json"


def localize(kind: str, text: str, what: str, lang: str, lang_cfg: dict, context_lines: list,
             call, model: str, cache_dir, prompt_version: str, extra: str = "") -> str | None:
    """`text` (English, from a dataset) written in the target language, or None if no valid answer.

    kind          cache folder and namespace, e.g. 'speaker-name' or 'event-label'
    what          what the text is, for the instruction, e.g. 'name of a biblical speaker'
    context_lines verses of the target-language corpus shown to the model, to follow their wording
    """
    cf = _cache_path(cache_dir, kind, text, lang, prompt_version, model, extra)
    if cf.exists():
        return clean_text(json.loads(cf.read_text(encoding="utf-8")).get("text"))
    system = (
        f"You write a {what} in {lang_cfg['prompt_lang']}, following the wording of the "
        f"{lang_cfg['translation']} where it uses one. The source text is a short English dataset label. "
        f"Answer with the {lang_cfg['prompt_lang']} text only: no quotes, no explanation, one line, "
        f"at most {MAX_WORDS} words. Never add information that is not in the label. {extra}"
    ).strip()
    user = f"Label: {text}\nVerses ({lang_cfg['translation']}):\n" + "\n".join(context_lines)
    out = clean_text(call(system, user))
    if out is not None:
        write_atomic(cf, json.dumps({"label": text, "text": out, "model": model, "prompt_version": prompt_version},
                                    ensure_ascii=False))
    return out


def localize_multi(kind: str, text: str, what: str, langs: dict, context_by_lang: dict,
                   call, model: str, cache_dir, prompt_version: str, extra: str = "") -> dict:
    """text written in each language, with at most one call for all uncached languages.

    langs: {lang: lang_cfg}, context_by_lang: {lang: [verse_lines]}.
    Writes to the same per-lang cache files as localize(), so the two paths share a cache.
    Returns {lang: str | None} for all langs.
    When only one language is uncached, delegates to localize() to keep the same prompt format.
    """
    result, missing = {}, {}
    for lang, lang_cfg in langs.items():
        cf = _cache_path(cache_dir, kind, text, lang, prompt_version, model, extra)
        if cf.exists():
            result[lang] = clean_text(json.loads(cf.read_text(encoding="utf-8")).get("text"))
        else:
            missing[lang] = lang_cfg

    if not missing:
        return result

    if len(missing) == 1:
        lang, lang_cfg = next(iter(missing.items()))
        result[lang] = localize(kind, text, what, lang, lang_cfg,
                                context_by_lang.get(lang, []), call, model, cache_dir, prompt_version, extra)
        return result

    langs_block = "\n\n".join(
        f"{lang} ({lang_cfg['translation']}):\n" + "\n".join(context_by_lang.get(lang, []))
        for lang, lang_cfg in missing.items()
    )
    system = (
        f"You write a {what} in multiple languages, following the wording of each translation "
        f"where it uses one. Answer with a JSON object: one key per language code, value is the {what} "
        f"in that language (one line, at most {MAX_WORDS} words, no markup, no quotes). "
        f"Never add information absent from the label. {extra}"
    ).strip()
    user = f"Label: {text}\n\nLanguages:\n{langs_block}"
    raw = call(system, user)
    parsed = {}
    if raw:
        try:
            parsed = json.loads(raw)
            if not isinstance(parsed, dict):
                parsed = {}
        except (json.JSONDecodeError, ValueError):
            pass

    for lang, lang_cfg in missing.items():
        val = clean_text(parsed.get(lang)) if parsed else None
        result[lang] = val
        if val is not None:
            write_atomic(_cache_path(cache_dir, kind, text, lang, prompt_version, model, extra),
                         json.dumps({"label": text, "text": val, "model": model,
                                     "prompt_version": prompt_version}, ensure_ascii=False))
    return result
