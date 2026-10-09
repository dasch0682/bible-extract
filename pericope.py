"""Pericope summary of a Bible chapter (background context for narrative.py, not in output JSON).

Generated once per chapter per language and cached; all excerpts of the same chapter reuse it.
The model sees the full chapter text and produces three compact fields:
- narrative_arc:   main narrative thread (who is involved, what happens)
- scene_location:  geographic setting (immediate place and broader region/route)
- book_position:   where in the book's arc this chapter sits (inferred from textual cues only)

Failure is non-blocking: returns None, and narrative.py falls back to a narrower window.

The caller injects the model call:
    call(system, user) -> str | None
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import yaml

import localize
import validate

PROMPT_VERSION = "pericope-1"
RULES_PATH = Path(__file__).parent / "data" / "narrative_rules.yml"
FIELDS = ("narrative_arc", "scene_location", "book_position")
_JSON = re.compile(r"\{.*\}", re.S)


class RulesError(ValueError):
    pass


def load_rules(path=RULES_PATH) -> dict:
    """Read and validate word-limit entries from data/narrative_rules.yml."""
    rules = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    out = {}
    for field in FIELDS:
        key = f"max_words_{field}"
        v = rules.get(key)
        if v is None or isinstance(v, bool) or not isinstance(v, int) or v < 1:
            raise RulesError(f"narrative_rules.yml: {key} must be a positive integer")
        out[key] = v
    return out


def chapter_verses(book: str, chapter: str, corpus: dict) -> list:
    """[(verse_id, text)] for the chapter, in verse number order."""
    numbers = sorted(corpus[book][chapter], key=int)
    return [(f"{book}.{chapter}.{n}", corpus[book][chapter][n]) for n in numbers]


def _cache_path(chapter_id: str, lang: str, verse_ids: list, model: str, cache_dir) -> Path:
    digest = hashlib.sha1("|".join(verse_ids).encode("utf-8")).hexdigest()[:10]
    return (Path(cache_dir) / "pericope" / lang
            / f"{chapter_id}-{digest}.{PROMPT_VERSION}.{localize.slug(model)}.json")


def _prompt(chapter_id: str, verses: list, lang_cfg: dict, chapter_info: str, rules: dict,
            retry_hint: str = "") -> tuple:
    lang = lang_cfg["prompt_lang"]
    lim = {f: rules[f"max_words_{f}"] for f in FIELDS}
    system = (
        f"You summarize the narrative context of a Bible chapter ({lang_cfg['translation']}) in {lang}. "
        "Use ONLY what the verses below state explicitly — add nothing from memory. "
        'Answer with one JSON object: {"narrative_arc": string, "scene_location": string, "book_position": string}. '
        f"narrative_arc: the main narrative thread — who is involved and what happens, "
        f"at most {lim['narrative_arc']} words. "
        f"scene_location: the geographic setting — the immediate place of the scene and, if the verses state it, "
        f"the broader region or route, at most {lim['scene_location']} words. "
        f"book_position: where this chapter fits in the book's narrative arc — what major events it follows "
        f"and precedes, inferred solely from textual cues in the verses shown, "
        f"at most {lim['book_position']} words. "
        f"All three fields must be non-empty strings in {lang}."
    )
    user = f"Chapter: {chapter_info}\n\nVerses:\n" + "\n".join(f"{v}: {t}" for v, t in verses)
    if retry_hint:
        user += f"\n\nIMPORTANT (previous answer rejected): {retry_hint}"
    return system, user


def check_answer(raw: str, rules: dict) -> tuple:
    """(answer dict, problem string) — validated answer or (None, reason)."""
    m = _JSON.search(raw) if isinstance(raw, str) else None
    if not m:
        return None, "the answer is not a JSON object"
    try:
        a = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None, "the answer is not valid JSON"
    if not isinstance(a, dict) or set(a) != set(FIELDS):
        return None, f"the object must have exactly {', '.join(FIELDS)}"
    for field in FIELDS:
        v = a[field]
        if not isinstance(v, str) or not v.strip():
            return None, f"{field} must be a non-empty string"
        limit = rules[f"max_words_{field}"]
        if validate.word_count(v) > limit:
            return None, f"{field} exceeds {limit} words"
    return {f: a[f].strip() for f in FIELDS}, None


def build_pericope(verse_ids: list, corpus: dict, lang: str, lang_cfg: dict, call, model: str,
                   cache_dir, rules: dict) -> dict | None:
    """Pericope summary for the chapter containing verse_ids, or None on failure.

    Returns {"narrative_arc", "scene_location", "book_position", "chapter_id"}, or None.
    A None result is non-blocking: the caller falls back gracefully.
    """
    book, chapter, _ = validate.parse_verse_id(verse_ids[0])
    chapter_id = f"{book}.{chapter}"
    verses = chapter_verses(book, chapter, corpus)
    all_ids = [v for v, _ in verses]
    cf = _cache_path(chapter_id, lang, all_ids, model, cache_dir)

    if cf.exists():
        answer, _ = check_answer(cf.read_text(encoding="utf-8"), rules)
        if answer is not None:
            return {**answer, "chapter_id": chapter_id}

    total_chapters = len(corpus[book])
    chapter_info = f"{book} chapter {int(chapter)} (of {total_chapters})"
    hint = ""
    for _attempt in range(2):
        raw = call(*_prompt(chapter_id, verses, lang_cfg, chapter_info, rules, hint))
        answer, problem = check_answer(raw if isinstance(raw, str) else "", rules)
        if answer is not None:
            cf.parent.mkdir(parents=True, exist_ok=True)
            cf.write_text(json.dumps(answer, ensure_ascii=False), encoding="utf-8")
            return {**answer, "chapter_id": chapter_id}
        hint = problem
    return None
