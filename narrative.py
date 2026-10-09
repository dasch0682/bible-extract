"""Narrative context of an excerpt (schema 2 `context.narrative`).

Complements `context.literary` (genre/tone) with three situational fields:
- situation:    what is happening around the excerpt in the narrative flow
- place:        where the scene takes place (specific location, region or route)
- arc_position: where this excerpt sits in the book's narrative arc

The model sees the excerpt plus a window of neighbouring verses (narrative_rules.yml: narrative_window).
When a pericope summary is available (from pericope.build_pericope), it is injected as background
context in the prompt. The model must cite only verses from the window shown, and at least one.
The code checks format, word counts and citation validity; one retry on failure.

The caller injects the model call and, optionally, the pericope summary:
    call(system, user) -> str | None
    pericope_summary = {"narrative_arc": ..., "scene_location": ..., "book_position": ...} | None
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import yaml

import literary
import localize
import validate
from provenance import merge_sources, verse_source

PROMPT_VERSION = "narrative-1"
RULES_PATH = Path(__file__).parent / "data" / "narrative_rules.yml"
FIELDS = ("situation", "place", "arc_position")
ANSWER_KEYS = set(FIELDS) | {"cited_verses", "confidence"}
_JSON = re.compile(r"\{.*\}", re.S)


class RulesError(ValueError):
    pass


def load_rules(path=RULES_PATH) -> dict:
    """Read and validate per-excerpt limits and window from data/narrative_rules.yml."""
    rules = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    out = {}
    for field in FIELDS:
        key = f"max_words_{field}"
        v = rules.get(key)
        if v is None or isinstance(v, bool) or not isinstance(v, int) or v < 1:
            raise RulesError(f"narrative_rules.yml: {key} must be a positive integer")
        out[key] = v
    win = rules.get("narrative_window")
    if win is None or isinstance(win, bool) or not isinstance(win, int) or win < 1:
        raise RulesError("narrative_rules.yml: narrative_window must be a positive integer")
    out["window"] = win
    return out


def _pericope_block(summary: dict | None) -> str:
    """One-line background string injected into the user prompt, or empty string."""
    if not summary:
        return ""
    return (f"\n[Chapter background: {summary['narrative_arc']} "
            f"— {summary['scene_location']} "
            f"— {summary['book_position']}]\n")


def _prompt(verse_ids: list, shown: list, lang_cfg: dict, pericope_summary: dict | None,
            rules: dict, retry_hint: str = "") -> tuple:
    lang = lang_cfg["prompt_lang"]
    lim = {f: rules[f"max_words_{f}"] for f in FIELDS}
    system = (
        f"You describe the narrative context of a Bible excerpt ({lang_cfg['translation']}) in {lang}: "
        "the situation in the narrative flow, the geographic setting, and the position in the book's arc, "
        "as the neighbouring verses show it. "
        "Use ONLY the verses given below — add nothing from memory. "
        '{"situation": string, "place": string, "arc_position": string, '
        '"cited_verses": [verse ids], "confidence": "high" | "medium" | "low"}. '
        f"situation: what is happening around the excerpt — who is involved and what occurs, "
        f"at most {lim['situation']} words. "
        f"place: where the scene takes place — specific location and, if stated, broader region or route, "
        f"at most {lim['place']} words. "
        f"arc_position: where this excerpt sits in the book's narrative arc — what it follows and precedes, "
        f"at most {lim['arc_position']} words. "
        "cited_verses: at least one verse id from the list below that supports the answer. "
        "confidence: high if the verses state the context explicitly, medium if partly inferred, "
        f"low if mostly inferred. Answer with one JSON object. Every text field in {lang}."
    )
    user = "Excerpt: " + ", ".join(verse_ids)
    block = _pericope_block(pericope_summary)
    if block:
        user += block
    user += "\n\nVerses:\n" + "\n".join(f"{v}: {t}" for v, t in shown)
    if retry_hint:
        user += f"\n\nIMPORTANT (previous answer rejected): {retry_hint}"
    return system, user


def check_answer(raw: str, shown_ids: set, rules: dict) -> tuple:
    """(answer dict, problem string) — validated answer or (None, reason)."""
    m = _JSON.search(raw) if isinstance(raw, str) else None
    if not m:
        return None, "the answer is not a JSON object"
    try:
        a = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None, "the answer is not valid JSON"
    if not isinstance(a, dict) or set(a) != ANSWER_KEYS:
        return None, f"the object must have exactly {', '.join(sorted(ANSWER_KEYS))}"
    for field in FIELDS:
        v = a[field]
        if not isinstance(v, str) or not v.strip():
            return None, f"{field} must be a non-empty string"
        limit = rules[f"max_words_{field}"]
        if validate.word_count(v) > limit:
            return None, f"{field} exceeds {limit} words"
    cited = a["cited_verses"]
    if not isinstance(cited, list) or not cited or not all(isinstance(c, str) for c in cited):
        return None, "cited_verses must list at least one verse id"
    if any(c not in shown_ids for c in cited):
        return None, "cited_verses must be verse ids taken from the list shown"
    if a["confidence"] not in validate.LITERARY_CONFIDENCE:
        return None, "confidence must be high, medium or low"
    return ({f: a[f].strip() for f in FIELDS}
            | {"cited_verses": list(dict.fromkeys(cited)), "confidence": a["confidence"]}), None


def _cache_path(verse_ids: list, lang: str, window: int, pericope_summary: dict | None,
                model: str, cache_dir) -> Path:
    key = hashlib.sha1("|".join(verse_ids + [str(window)]).encode("utf-8")).hexdigest()[:10]
    pc_hash = hashlib.sha1(
        json.dumps({k: pericope_summary[k] for k in ("narrative_arc", "scene_location", "book_position")}
                   if pericope_summary else {}, sort_keys=True).encode("utf-8")
    ).hexdigest()[:6]
    return (Path(cache_dir) / "narrative" / lang
            / f"{verse_ids[0]}-{key}.pc{pc_hash}.{PROMPT_VERSION}.{localize.slug(model)}.json")


def build_narrative(verse_ids: list, corpus: dict, lang: str, lang_cfg: dict, call, model: str,
                    cache_dir, registry: dict, rules: dict,
                    pericope_summary: dict | None = None) -> dict:
    """{'narrative': field, 'sources': [...], 'flags': [...]} for one excerpt.

    `pericope_summary` is the output of pericope.build_pericope() for the same chapter, or None.
    When None, the model runs with the window only (no chapter background), still producing the field.
    """
    shown = literary.window_verses(verse_ids, corpus, rules["window"])
    shown_ids = {v for v, _ in shown}
    cf = _cache_path(verse_ids, lang, rules["window"], pericope_summary, model, cache_dir)

    if cf.exists():
        answer, _ = check_answer(cf.read_text(encoding="utf-8"), shown_ids, rules)
        if answer is not None:
            return _to_result(answer, lang_cfg, model, registry)

    hint = ""
    for _attempt in range(2):
        raw = call(*_prompt(verse_ids, shown, lang_cfg, pericope_summary, rules, hint))
        answer, problem = check_answer(raw if isinstance(raw, str) else "", shown_ids, rules)
        if answer is not None:
            cf.parent.mkdir(parents=True, exist_ok=True)
            cf.write_text(json.dumps(answer, ensure_ascii=False), encoding="utf-8")
            return _to_result(answer, lang_cfg, model, registry)
        hint = problem
    return {"narrative": {"text": None, "reason": "no_source"}, "sources": [], "flags": ["narrative_failed"]}


def _to_result(answer: dict, lang_cfg: dict, model: str, registry: dict) -> dict:
    sources = merge_sources([verse_source(v, lang_cfg["dataset"], registry)
                             for v in answer["cited_verses"]])
    field = {
        "situation": answer["situation"],
        "place": answer["place"],
        "arc_position": answer["arc_position"],
        "sources": [s["id"] for s in sources],
        "confidence": answer["confidence"],
        "confidence_by": "model",
        "model": model,
        "prompt_version": PROMPT_VERSION,
    }
    return {"narrative": field, "sources": sources, "flags": []}
