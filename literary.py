"""Literary context of an excerpt (schema 2 `context.literary`): who speaks to whom, in which situation.

The model writes the text and judges its own confidence (high, medium or low) in the same call;
this is allowed because a model may write and judge, it is just never a source. The code limits
what it can do:
- it only sees the excerpt and a window of neighbouring verses of the same chapter (from the corpus);
- every verse it cites must be one of the verses shown to it, and at least one must be cited;
- the answer must be the expected JSON, with a valid level and a short text; otherwise one retry
  with the reason, then the field is null with reason `no_source` and the entry is flagged for review;
- the entry records who judged the confidence (`confidence_by`), the model and the prompt version.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import localize
import validate
from provenance import merge_sources, verse_source

PROMPT_VERSION = "literary-1"
WINDOW = 3                  # neighbouring verses shown before and after the excerpt, inside the chapter
MAX_WORDS = 60
_JSON = re.compile(r"\{.*\}", re.S)


def window_verses(verse_ids: list, corpus: dict, window: int = WINDOW) -> list:
    """[(verse id, text)] of the excerpt plus `window` verses before and after, inside the same chapter."""
    book, chapter, _ = validate.parse_verse_id(verse_ids[0])
    numbers = sorted(corpus[book][chapter], key=int)
    first = min(numbers.index(validate.parse_verse_id(v)[2]) for v in verse_ids)
    last = max(numbers.index(validate.parse_verse_id(v)[2]) for v in verse_ids)
    chosen = numbers[max(0, first - window): last + window + 1]
    return [(f"{book}.{chapter}.{n}", corpus[book][chapter][n]) for n in chosen]


def _prompt(verse_ids: list, shown: list, lang_cfg: dict, retry_hint: str = "") -> tuple:
    lang = lang_cfg["prompt_lang"]
    system = (
        f"You describe the literary context of a Bible excerpt in {lang}: who speaks to whom and in which "
        f"situation, as the neighbouring verses show it. Use ONLY the verses given below "
        f"({lang_cfg['translation']}); add nothing from memory. Answer with one JSON object: "
        '{"text": string or null, "cited_verses": [verse ids], "confidence": "high" | "medium" | "low"}. '
        f"text: one or two sentences in {lang}, at most {MAX_WORDS} words. "
        "cited_verses: at least one verse id taken exactly from the list, the verses that support the text. "
        "confidence: high if the verses state the situation explicitly, medium if it is partly stated and partly "
        "inferred, low if it is mostly inferred. If the verses do not show the context, answer "
        '{"text": null, "cited_verses": [], "confidence": null}.'
    )
    user = ("Excerpt: " + ", ".join(verse_ids) + "\n\nVerses:\n" + "\n".join(f"{v}: {t}" for v, t in shown))
    if retry_hint:
        user += f"\n\nIMPORTANT (previous answer rejected): {retry_hint}"
    return system, user


def check_answer(raw, shown_ids: set):
    """(answer, problem): the parsed answer when it passes the code's checks, else None and the reason."""
    m = _JSON.search(raw) if isinstance(raw, str) else None
    if not m:
        return None, "the answer is not a JSON object"
    try:
        a = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None, "the answer is not valid JSON"
    if not isinstance(a, dict) or set(a) != {"text", "cited_verses", "confidence"}:
        return None, "the object must have exactly text, cited_verses and confidence"
    if a["text"] is None:
        return ({"text": None, "cited_verses": [], "confidence": None}, None) \
            if not a["cited_verses"] and a["confidence"] is None else (None, "a null text has no citations or level")
    text = a["text"]
    if not isinstance(text, str) or not text.strip() or "\n" in text.strip():
        return None, "text must be one short paragraph"
    if validate.word_count(text) > MAX_WORDS:
        return None, f"text is longer than {MAX_WORDS} words"
    cited = a["cited_verses"]
    if not isinstance(cited, list) or not cited or not all(isinstance(c, str) for c in cited):
        return None, "cited_verses must list at least one verse id"
    if any(c not in shown_ids for c in cited):
        return None, "cited_verses must be verse ids taken from the list shown"
    if a["confidence"] not in validate.LITERARY_CONFIDENCE:
        return None, "confidence must be high, medium or low"
    return {"text": text.strip(), "cited_verses": list(dict.fromkeys(cited)), "confidence": a["confidence"]}, None


def literary_context(verse_ids: list, corpus: dict, lang: str, lang_cfg: dict, call, model: str, cache_dir,
                     registry: dict, window: int = WINDOW) -> dict:
    """{'literary': field, 'sources': [...], 'flags': [...]} for an entry.

    `call(system, user)` returns the raw model text or None. The valid answer is cached per excerpt,
    language, prompt version and model.
    """
    shown = window_verses(verse_ids, corpus, window)
    shown_ids = {v for v, _ in shown}
    key = hashlib.sha1("|".join(verse_ids + [str(window)]).encode("utf-8")).hexdigest()[:10]
    cf = Path(cache_dir) / "literary" / lang / f"{verse_ids[0]}-{key}.{PROMPT_VERSION}.{localize.slug(model)}.json"
    answer = None
    if cf.exists():
        answer, _ = check_answer(cf.read_text(encoding="utf-8"), shown_ids)
    if answer is None:
        hint = ""
        for _attempt in range(2):
            answer, problem = check_answer(call(*_prompt(verse_ids, shown, lang_cfg, hint)), shown_ids)
            if answer is not None:
                break
            hint = problem
        if answer is not None:
            cf.parent.mkdir(parents=True, exist_ok=True)
            cf.write_text(json.dumps(answer, ensure_ascii=False), encoding="utf-8")
    if answer is None:
        return {"literary": {"text": None, "reason": "no_source"}, "sources": [], "flags": ["literary_failed"]}
    if answer["text"] is None:
        return {"literary": {"text": None, "reason": "no_source"}, "sources": [], "flags": []}
    sources = merge_sources([verse_source(v, lang_cfg["dataset"], registry) for v in answer["cited_verses"]])
    field = {"text": answer["text"], "confidence": answer["confidence"], "sources": [s["id"] for s in sources],
             "confidence_by": "model", "model": model, "prompt_version": PROMPT_VERSION}
    return {"literary": field, "sources": sources, "flags": []}
