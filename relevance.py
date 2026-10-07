"""Relevance judgement of the `model` discovery mode (specification, section "Découverte et sélection").

The model judges whether a candidate verse addresses the topic, cites the verses that justify the answer, and
proposes the excerpt bounds. It is never a source, and the code limits the call:
- it only sees the candidate verse and a window of verses of the same chapter, taken from the corpus;
- it cannot add a verse: every cited verse and both bounds must be among the verses shown;
- the bounds must be contiguous, contain the candidate and every cited verse;
- the answer must be the expected JSON, otherwise one retry with the reason, then no verdict (the candidate is
  listed in the report as "no verdict", never dropped in silence).
The valid answer is cached per candidate, window, language, topic wording, prompt version and model.
The judgement runs once, on the pivot language; its bounds apply to every language file (neutral fields).
The caller injects `call(system, user) -> str | None`, so this module names no model and makes no network call.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import literary
import localize

PROMPT_VERSION = "relevance-1"
_JSON = re.compile(r"\{.*\}", re.S)
_KEYS = {"relevant", "cited_verses", "start", "end"}


def _prompt(candidate_id: str, shown: list, lang_cfg: dict, topic_label: str, extra: str, retry_hint: str = "") -> tuple:
    lang = lang_cfg["prompt_lang"]
    system = (
        f"You judge whether a Bible verse ({lang_cfg['translation']}) genuinely addresses a theme, for a thematic "
        f"anthology. Use ONLY the verses given below; add nothing from memory. Answer with one JSON object: "
        '{"relevant": true | false, "cited_verses": [verse ids], "start": verse id or null, "end": verse id or null}. '
        "relevant: true only when the verse genuinely addresses the theme, not a trivial use of the keyword. "
        "cited_verses: when relevant, at least one verse id taken exactly from the list, the verses that justify "
        "your answer. start and end: the first and last verse of the excerpt to keep, taken exactly from the list. "
        "The excerpt is whole, contiguous verses that form one complete statement; it must contain the verse to "
        "judge and every cited verse. When not relevant, answer "
        '{"relevant": false, "cited_verses": [], "start": null, "end": null}.'
    )
    if extra:
        system += "\n" + extra.strip()
    user = (f"Theme: {topic_label}\nVerse to judge: {candidate_id}\n\nVerses:\n"
            + "\n".join(f"{v}: {t}" for v, t in shown))
    if retry_hint:
        user += f"\n\nIMPORTANT (previous answer rejected): {retry_hint}"
    return system, user


def check_answer(raw, shown_ids: list, candidate_id: str):
    """(answer, problem): the parsed answer when it passes the code's checks, else None and the reason.

    `shown_ids` are the verse ids shown to the model, in corpus order.
    """
    m = _JSON.search(raw) if isinstance(raw, str) else None
    if not m:
        return None, "the answer is not a JSON object"
    try:
        a = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None, "the answer is not valid JSON"
    if not isinstance(a, dict) or set(a) != _KEYS:
        return None, "the object must have exactly relevant, cited_verses, start and end"
    if not isinstance(a["relevant"], bool):
        return None, "relevant must be true or false"
    if not a["relevant"]:
        if a["cited_verses"] or a["start"] is not None or a["end"] is not None:
            return None, "a verse that is not relevant has no citations and no bounds"
        return {"relevant": False, "cited_verses": [], "verses": []}, None
    cited = a["cited_verses"]
    if not isinstance(cited, list) or not cited or not all(isinstance(c, str) for c in cited):
        return None, "cited_verses must list at least one verse id"
    pos = {v: i for i, v in enumerate(shown_ids)}
    if any(c not in pos for c in cited):
        return None, "cited_verses must be verse ids taken from the list shown"
    if not (isinstance(a["start"], str) and isinstance(a["end"], str) and a["start"] in pos and a["end"] in pos):
        return None, "start and end must be verse ids taken from the list shown"
    lo, hi = pos[a["start"]], pos[a["end"]]
    if lo > hi:
        return None, "start must not come after end"
    if not lo <= pos[candidate_id] <= hi:
        return None, "the excerpt must contain the verse to judge"
    if any(not lo <= pos[c] <= hi for c in cited):
        return None, "the excerpt must contain every cited verse"
    return {"relevant": True, "cited_verses": list(dict.fromkeys(cited)), "verses": shown_ids[lo:hi + 1]}, None


def judge(candidate_id: str, corpus: dict, lang: str, lang_cfg: dict, topic_label: str, extra_instructions: str,
          call, model: str, cache_dir, window: int):
    """{'relevant', 'cited_verses', 'verses', 'model', 'prompt_version'} for a candidate, or None without verdict."""
    shown = literary.window_verses([candidate_id], corpus, window)
    shown_ids = [v for v, _ in shown]
    key = hashlib.sha1("|".join([candidate_id, str(window), topic_label, extra_instructions]).encode("utf-8")
                       ).hexdigest()[:10]
    cf = Path(cache_dir) / "relevance" / lang / f"{candidate_id}-{key}.{PROMPT_VERSION}.{localize.slug(model)}.json"
    answer = None
    if cf.exists():
        answer, _ = check_answer(cf.read_text(encoding="utf-8"), shown_ids, candidate_id)
    if answer is None:
        hint = ""
        for _attempt in range(2):
            raw = call(*_prompt(candidate_id, shown, lang_cfg, topic_label, extra_instructions, hint))
            answer, problem = check_answer(raw, shown_ids, candidate_id)
            if answer is not None:
                break
            hint = problem
        if answer is not None:
            cf.parent.mkdir(parents=True, exist_ok=True)
            cf.write_text(json.dumps({"relevant": answer["relevant"], "cited_verses": answer["cited_verses"],
                                      "start": answer["verses"][0] if answer["verses"] else None,
                                      "end": answer["verses"][-1] if answer["verses"] else None},
                                     ensure_ascii=False), encoding="utf-8")
    if answer is None:
        return None
    return dict(answer, model=model, prompt_version=PROMPT_VERSION)
