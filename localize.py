"""Short texts (speaker names, event labels) written in the target language by a model.

The model only translates a short label that comes from a dataset; it is never a source.
The answer is accepted only as a short, single-line text, and cached per kind, language,
prompt version and model. The caller injects `call(system, user) -> str | None`, so this
module holds no model identifier and makes no network call of its own.
"""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from pathlib import Path

MAX_WORDS = 12


def slug(s: str) -> str:
    s = "".join(ch for ch in unicodedata.normalize("NFD", s or "") if unicodedata.category(ch) != "Mn")
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:40]


def clean_text(raw, max_words: int = MAX_WORDS):
    """A model answer is accepted only as a short, single-line text without markup; otherwise None."""
    if not isinstance(raw, str):
        return None
    text = raw.strip().strip('"«»“”\'').strip()
    if not text or "\n" in text or len(text.split()) > max_words or any(c in text for c in "{}[]<>"):
        return None
    return text


def localize(kind: str, text: str, what: str, lang: str, lang_cfg: dict, context_lines: list,
             call, model: str, cache_dir, prompt_version: str, extra: str = "") -> str | None:
    """`text` (English, from a dataset) written in the target language, or None if no valid answer.

    kind          cache folder and namespace, e.g. 'speaker-name' or 'event-label'
    what          what the text is, for the instruction, e.g. 'name of a biblical speaker'
    context_lines verses of the target-language corpus shown to the model, to follow their wording
    """
    digest = hashlib.sha1(f"{text}\x00{extra}".encode("utf-8")).hexdigest()[:8]
    cf = Path(cache_dir) / kind / lang / f"{slug(text)}-{digest}.{prompt_version}.{slug(model)}.json"
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
        cf.parent.mkdir(parents=True, exist_ok=True)
        cf.write_text(json.dumps({"label": text, "text": out, "model": model, "prompt_version": prompt_version},
                                 ensure_ascii=False), encoding="utf-8")
    return out
