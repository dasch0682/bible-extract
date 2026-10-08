"""Paraphrase of an excerpt (schema 2 `paraphrase`): three candidates, one verification, arbitration by the code.

Specification, section "Paraphrase":
1. generation, ONE call: the model returns exactly three candidates, `close`, `condensed` and `free`
   (plus the genre of the passage); any other format is refused and the call is retried once;
2. code checks on every candidate: not longer than the excerpt, in the target language, non-empty;
3. verification, ONE call, by a model of another family than the generator: it sees the excerpt and the
   candidates in a shuffled order under neutral letters, and scores each from 1 to 5 on fidelity (nothing
   added) and completeness (the central idea is kept), and reports problems (addition, genre changed,
   tense other than present);
4. arbitration by the code: it drops the candidates that fail a check, have a reported problem or a fidelity
   below `min_fidelity` (data/paraphrase_rules.yml), keeps the best sum of the two scores, then the shortest,
   then the order close, condensed, free;
5. no valid candidate: the paraphrase is null with reason `no_faithful_version`, and the entry goes to review.

The whole history (candidates, checks, scores, arbitration) is kept in the entry. A model writes and judges,
it is never a source. The caller injects the model calls, so this module names no model and makes no
network call of its own:

    calls = {"paraphrase_generation": (call, model_id), "paraphrase_verification": (call, model_id)}
    # call(system, user) -> str | None

The result is not an entry: the pipeline (tasks 7 and 8) adds it as `entry["paraphrase"]`.
"""
from __future__ import annotations

import hashlib
import json
import random
import re
from pathlib import Path

import yaml

import localize
import validate
from models import family

GENERATION_VERSION = "paraphrase-gen-5"
VERIFICATION_VERSION = "paraphrase-verify-4"
TRIM_VERSION = "paraphrase-trim-1"
RULES_PATH = Path(__file__).parent / "data" / "paraphrase_rules.yml"

STYLES = ("close", "condensed", "free")          # also the tie-break order
ISSUES = ("addition", "genre_changed", "tense_not_present", "other")
SCORE_RANGE = range(1, 6)
LABELS = "ABC"
# Flags that force the entry through the review page (the others are information for the reviewer).
REVIEW_REQUIRED = ("paraphrase_failed", "genre_conflict")

_JSON = re.compile(r"\{.*\}", re.S)
_WORD = re.compile(r"[^\W\d_]+")
_STYLE_RULES = {
    "close": "stay close to the text: follow the order and structure of the excerpt, only simplify the vocabulary",
    "condensed": "keep only the central idea, in one sentence",
    "free": "reformulate freely: change the syntax and the order of the ideas, with common words",
}


class RulesError(ValueError):
    pass


def load_rules(path=RULES_PATH) -> dict:
    """Read and check data/paraphrase_rules.yml. Words shared by several languages are dropped from the markers."""
    rules = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    mf = rules.get("min_fidelity")
    if isinstance(mf, bool) or mf not in SCORE_RANGE:
        raise RulesError("min_fidelity: an integer from 1 to 5 is required")
    raw = rules.get("language_markers")
    if not isinstance(raw, dict) or not all(isinstance(v, list) and v and all(isinstance(w, str) for w in v)
                                            for v in raw.values()):
        raise RulesError("language_markers: a dict of non-empty word lists is required")
    sets = {lang: {w.lower() for w in words} for lang, words in raw.items()}
    shared = {w for lang, s in sets.items() for other, o in sets.items() if other != lang for w in s & o}
    return {"min_fidelity": mf, "markers": {lang: s - shared for lang, s in sets.items()}}


def review_required(flags: list) -> bool:
    return any(f.split(":")[0] in REVIEW_REQUIRED for f in flags)


# --- generation ---

def _generation_prompt(excerpt_text: str, max_words: int, lang_cfg: dict, retry_hint: str = "") -> tuple:
    lang = lang_cfg["prompt_lang"]
    styles = "; ".join(f"{s}: {_STYLE_RULES[s]}" for s in STYLES)
    prompt_max = max(int(max_words * 0.85), 5)
    system = (
        f"You paraphrase a Bible excerpt ({lang_cfg['translation']}) in {lang}. Rules shared by every candidate: "
        "keep the original genre (a speech stays a speech, for example 'Jesus declares that...'; a narrative stays "
        "a narrative; a letter, a prayer or a parable stays one); "
        "write every verb in the present tense (historic present); avoid passé simple and imparfait; "
        "passé composé is allowed only when the excerpt itself uses a completed past action (e.g. 'il est venu', "
        "'ils ne l'ont pas reconnu') — in those cases keep the passé composé; "
        "add NO information that is not in the excerpt — this applies to every style including free: never add "
        "a character name, detail, interpretation, implied context or consequence absent from the excerpt text; "
        "in particular, do NOT name a character who is not named in the excerpt itself (if the excerpt uses a "
        "pronoun such as 'il', 'she', 'they', keep a pronoun or a generic phrase, never substitute the person's "
        "name); converting direct speech to indirect speech (tu→il, je→il) is not an addition; "
        f"use at most {prompt_max} words (strict limit — count carefully). "
        f"Write three candidates that differ only in style, never in content, and do not reuse in one candidate the "
        f"wording of another. Styles - {styles}. "
        f"Also give the genre of the excerpt, one of: {', '.join(sorted(validate.GENRES))}. "
        'Answer with one JSON object: {"genre": string, "candidates": {"close": string, "condensed": string, '
        f'"free": string}}}}. Every text is in {lang}.'
    )
    user = f"Excerpt:\n{excerpt_text}"
    if retry_hint:
        user += f"\n\nIMPORTANT (previous answer rejected): {retry_hint}"
    return system, user


def check_generation(raw):
    """(answer, problem): {'genre', 'candidates': {style: text}} when the format is exact, else None and the reason."""
    m = _JSON.search(raw) if isinstance(raw, str) else None
    if not m:
        return None, "the answer is not a JSON object"
    try:
        a = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None, "the answer is not valid JSON"
    if not isinstance(a, dict) or set(a) != {"genre", "candidates"}:
        return None, "the object must have exactly genre and candidates"
    if a["genre"] not in validate.GENRES:
        return None, f"genre must be one of {', '.join(sorted(validate.GENRES))}"
    c = a["candidates"]
    if not isinstance(c, dict) or set(c) != set(STYLES) or not all(isinstance(c[s], str) for s in STYLES):
        return None, "candidates must have exactly close, condensed and free, as strings"
    return {"genre": a["genre"], "candidates": {s: c[s].strip() for s in STYLES}}, None


# --- code checks ---

def _words(text: str) -> list:
    return _WORD.findall((text or "").lower())


def language_check(text: str, lang: str, markers: dict):
    """True / False, or None when the language has no marker list. False when another language clearly outnumbers it."""
    if lang not in markers:
        return None
    words = _words(text)
    mine = sum(w in markers[lang] for w in words)
    other = max((sum(w in m for w in words) for k, m in markers.items() if k != lang), default=0)
    return other <= mine


def code_checks(text: str, excerpt_text: str, lang: str, rules: dict) -> dict:
    """The three checks of the specification; a check is True (passes), False, or None (not checked)."""
    return {
        "non_empty": bool(validate._ws(text)),
        "not_longer_than_excerpt": validate.word_count(text) <= validate.word_count(excerpt_text) + 2,
        "target_language": language_check(text, lang, rules["markers"]),
    }


def checks_pass(checks: dict) -> bool:
    return all(v is not False for v in checks.values())


# --- verification ---

def _verification_prompt(excerpt_text: str, shown: list, lang_cfg: dict, retry_hint: str = "") -> tuple:
    lang = lang_cfg["prompt_lang"]
    labels = [lab for lab, _ in shown]
    system = (
        f"You check paraphrases of a Bible excerpt ({lang_cfg['translation']}, {lang}). You receive the excerpt and "
        f"candidate paraphrases under the letters {', '.join(labels)}. Score each candidate from 1 to 5 on "
        "fidelity (5 = adds nothing that is not in the excerpt) and on completeness (5 = the central idea of the "
        "excerpt is fully kept). Report its problems with these codes: addition (information absent from the "
        "excerpt — note that: using a pronoun where the excerpt uses a name, or vice-versa, is NOT an addition; "
        "converting direct speech to indirect speech and adjusting pronouns is NOT an addition), genre_changed (a speech is no longer a speech, a narrative no longer a narrative, and so on), "
        "tense_not_present (ONLY flag when you see unambiguous passé simple such as 'il vint', 'ils vinrent', "
        "'il fit', 'ils firent', 'il prit', 'ils prirent', 'il fut', 'ils furent', 'il alla', 'ils allèrent', "
        "'il envoya', 'ils envoyèrent'; or imparfait ending in -ait/-aient/-ions/-iez. "
        "Passé composé (avoir or être + past participle, e.g. 'il a dit', 'il est venu', 'ils ont entendu', "
        "'elle est venue', 'ils ne l'ont pas reconnu', 'tu as dit', 'nous l'avons entendu') is ALWAYS "
        "acceptable — NEVER flag it as tense_not_present. "
        "Examples of what NOT to flag: 'il dit' = present indicative ✓; 'il vient' ✓; 'elle sait' ✓; "
        "'ils disent' ✓; 'il est venu' ✓; 'ils ont entendu' ✓; 'tu as dit' ✓; 'nous l'avons entendu' ✓. "
        "Examples of what TO flag: 'il vint' ✗; 'il vit' (voir, passé simple) ✗; 'ils dirent' ✗; "
        "'il était' ✗; 'ils parlaient' ✗), "
        "other. Use an empty list when there is no "
        'problem. Answer with one JSON object keyed by the letters, for example {"A": {"fidelity": 5, '
        '"completeness": 4, "issues": []}}. Judge every candidate on its own.'
    )
    user = f"Excerpt:\n{excerpt_text}\n\nCandidates:\n" + "\n".join(f"{lab}: {t}" for lab, t in shown)
    if retry_hint:
        user += f"\n\nIMPORTANT (previous answer rejected): {retry_hint}"
    return system, user


# --- trim (targeted retry for too-long candidates) ---

def _trim_prompt(text: str, current_wc: int, max_words: int, style: str, lang_cfg: dict) -> tuple:
    lang = lang_cfg["prompt_lang"]
    system = (
        f"You shorten a Bible paraphrase ({lang_cfg['translation']}, {lang}). "
        "Return ONLY the shortened text — no label, no explanation, no quotes."
    )
    user = (
        f"This '{style}' paraphrase is {current_wc} words but must be at most {max_words} words.\n\n"
        f"Text: {text}\n\n"
        "Shorten it by removing or condensing one phrase. Keep the same tense (historic present), "
        "genre and content. Return only the shortened text."
    )
    return system, user


def _check_trim(raw, max_words: int):
    if not raw or not raw.strip():
        return None, "empty response"
    t = raw.strip()
    if validate.word_count(t) > max_words:
        return None, f"still {validate.word_count(t)} words, limit is {max_words}"
    return t, None


def _trim_candidate(text: str, max_words: int, style: str, lang_cfg: dict,
                    call, model: str, verse_ids: list, key: str, base: Path) -> str | None:
    trim_key = hashlib.sha1(text.encode("utf-8")).hexdigest()[:10]
    cf = base / f"{verse_ids[0]}-{key}.trim-{trim_key}.{TRIM_VERSION}.{localize.slug(model)}.json"
    wc = validate.word_count(text)
    return _ask(call, lambda _hint: _trim_prompt(text, wc, max_words, style, lang_cfg),
                lambda raw: _check_trim(raw, max_words), (), cf)


def check_verification(raw, labels: list):
    """(scores, problem): {label: {'fidelity', 'completeness', 'issues'}} when the format is exact, else None and why."""
    m = _JSON.search(raw) if isinstance(raw, str) else None
    if not m:
        return None, "the answer is not a JSON object"
    try:
        a = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None, "the answer is not valid JSON"
    if not isinstance(a, dict) or set(a) != set(labels):
        return None, f"the object must have exactly the keys {', '.join(labels)}"
    out = {}
    for lab in labels:
        s = a[lab]
        if not isinstance(s, dict) or set(s) != {"fidelity", "completeness", "issues"}:
            return None, f"{lab} must have exactly fidelity, completeness and issues"
        for k in ("fidelity", "completeness"):
            if isinstance(s[k], bool) or s[k] not in SCORE_RANGE:
                return None, f"{lab}.{k} must be an integer from 1 to 5"
        if not isinstance(s["issues"], list) or any(i not in ISSUES for i in s["issues"]):
            return None, f"{lab}.issues must be a list of: {', '.join(ISSUES)}"
        out[lab] = {"fidelity": s["fidelity"], "completeness": s["completeness"],
                    "issues": list(dict.fromkeys(s["issues"]))}
    return out, None


def shuffle_seed(verse_ids: list, lang: str, texts: list) -> int:
    """A reproducible seed (same excerpt, language and candidates give the same order), recorded in the entry."""
    return int(hashlib.sha1("|".join(verse_ids + [lang] + texts).encode("utf-8")).hexdigest()[:8], 16)


def shuffled_labels(styles: list, seed: int) -> list:
    """[(label, style)] in random order: the verifier sees only the neutral letters."""
    order = list(styles)
    random.Random(seed).shuffle(order)
    return [(LABELS[i], s) for i, s in enumerate(order)]


# --- arbitration ---

def arbitrate(history: list, min_fidelity: int):
    """(selected attempt number | None, reason). Pure function of the history, no model."""
    eligible, dropped = [], []
    for h in history:
        v = h["verification"]
        why = None
        if not checks_pass(h["code_checks"]):
            why = "failed a code check"
        elif v["verdict"] == "not_verified":
            why = "not verified"
        elif v["issues"]:
            why = "problem reported: " + ", ".join(v["issues"])
        elif v["fidelity"] < min_fidelity:
            why = f"fidelity {v['fidelity']} below {min_fidelity}"
        (dropped if why else eligible).append((h, why))
    if not eligible:
        detail = "; ".join(f"{h['style']}: {why}" for h, why in dropped) or "no candidate"
        return None, f"no candidate passes ({detail})"
    best = min((h for h, _ in eligible),
               key=lambda h: (-(h["verification"]["fidelity"] + h["verification"]["completeness"]),
                              validate.word_count(h["text"]), STYLES.index(h["style"])))
    v = best["verification"]
    return best["attempt"], (f"{best['style']} selected: fidelity {v['fidelity']} + completeness "
                             f"{v['completeness']}, {validate.word_count(best['text'])} words; "
                             f"{len(history) - 1} other candidate(s) not selected")


# --- orchestration ---

def _cached(cache_file: Path, check, *args):
    if cache_file.exists():
        value, _ = check(cache_file.read_text(encoding="utf-8"), *args)
        return value
    return None


def _ask(call, make_prompt, check, args: tuple, cache_file: Path):
    """The valid answer (from the cache, or from the model with one retry), or None. Valid answers are cached."""
    answer = _cached(cache_file, check, *args)
    if answer is not None:
        return answer
    hint = ""
    for _attempt in range(2):
        raw = call(*make_prompt(hint))
        answer, problem = check(raw, *args)
        if answer is not None:
            cache_file.parent.mkdir(parents=True, exist_ok=True)
            cache_file.write_text(raw if isinstance(raw, str) else "", encoding="utf-8")
            return answer
        hint = problem
    return None


def build_paraphrase(excerpt_text: str, verse_ids: list, lang: str, lang_cfg: dict, calls: dict, cache_dir,
                     rules: dict, speaker_role: str | None = None) -> dict:
    """{'paraphrase': field, 'flags': [...]} for an excerpt of one language.

    `excerpt_text` is the exact text of the excerpt (from the corpus). The field is valid for
    validate.check_paraphrase: a selected candidate with its history, or a null text with reason
    `no_faithful_version` (the history is kept for the review page). `speaker_role` (speaker or narrator)
    only serves to flag a genre that contradicts the role.
    """
    gen_call, gen_model = calls["paraphrase_generation"]
    ver_call, ver_model = calls["paraphrase_verification"]
    if family(gen_model) == family(ver_model):
        raise ValueError("the verification model must come from another family than the generator")
    max_words = validate.word_count(excerpt_text)
    key = hashlib.sha1("|".join(verse_ids).encode("utf-8")).hexdigest()[:10]
    base = Path(cache_dir) / "paraphrase" / lang

    gen = _ask(gen_call, lambda hint: _generation_prompt(excerpt_text, max_words, lang_cfg, hint),
               check_generation, (), base / f"{verse_ids[0]}-{key}.gen.{GENERATION_VERSION}.{localize.slug(gen_model)}.json")
    if gen is None:
        return {"paraphrase": {"text": None, "reason": "no_faithful_version", "history": [],
                               "arbitration": {"selected_attempt": None, "reason": "generation failed after one retry"}},
                "flags": ["paraphrase_failed", "generation_failed"]}

    flags = []
    history = []
    for n, style in enumerate(STYLES, start=1):
        text = gen["candidates"][style]
        history.append({"attempt": n, "style": style, "text": text, "model": gen_model,
                        "prompt_version": GENERATION_VERSION,
                        "code_checks": code_checks(text, excerpt_text, lang, rules),
                        "verification": {"model": ver_model, "verdict": "not_verified", "fidelity": None,
                                         "completeness": None, "issues": []}})
    if any(h["code_checks"]["target_language"] is None for h in history):
        flags.append("language_unchecked")

    # Trim too-long candidates before verification
    for h in history:
        if h["code_checks"].get("not_longer_than_excerpt") is False:
            trimmed = _trim_candidate(h["text"], max_words, h["style"], lang_cfg,
                                      gen_call, gen_model, verse_ids, key, base)
            if trimmed:
                h["text"] = trimmed
                h["trimmed"] = True
                h["code_checks"] = code_checks(trimmed, excerpt_text, lang, rules)

    sendable = [h for h in history if h["code_checks"]["non_empty"]]
    seed = None
    if sendable:
        seed = shuffle_seed(verse_ids, lang, [h["text"] for h in sendable])
        shown = [(lab, next(h["text"] for h in sendable if h["style"] == style))
                 for lab, style in shuffled_labels([h["style"] for h in sendable], seed)]
        labels = [lab for lab, _ in shown]
        vkey = hashlib.sha1("|".join(f"{lab}:{t}" for lab, t in shown).encode("utf-8")).hexdigest()[:10]
        scores = _ask(ver_call, lambda hint: _verification_prompt(excerpt_text, shown, lang_cfg, hint),
                      check_verification, (labels,),
                      base / f"{verse_ids[0]}-{key}.verify-{vkey}.{VERIFICATION_VERSION}.{localize.slug(ver_model)}.json")
        if scores is None:
            flags.append("verification_failed")
        else:
            by_style = {style: scores[lab] for lab, style in shuffled_labels([h["style"] for h in sendable], seed)}
            for h in sendable:
                s = by_style[h["style"]]
                h["verification"] = {"model": ver_model, "verdict": "fail" if s["issues"] else "pass",
                                     "fidelity": s["fidelity"], "completeness": s["completeness"],
                                     "issues": s["issues"], "prompt_version": VERIFICATION_VERSION}

    selected, reason = arbitrate(history, rules["min_fidelity"])
    arbitration = {"selected_attempt": selected, "reason": reason}
    if seed is not None:
        arbitration["shuffle_seed"] = seed
    if selected is None:
        flags.append("paraphrase_failed")
        return {"paraphrase": {"text": None, "reason": "no_faithful_version", "genre": gen["genre"],
                               "history": history, "arbitration": arbitration}, "flags": flags}
    if (speaker_role == "narrator" and gen["genre"] == "discourse") or \
            (speaker_role == "speaker" and gen["genre"] == "narrative"):
        flags.append(f"genre_conflict:{speaker_role}:{gen['genre']}")
    chosen = history[selected - 1]
    return {"paraphrase": {"text": chosen["text"], "genre": gen["genre"], "genre_by": "model",
                           "history": history, "arbitration": arbitration}, "flags": flags}


def apply_genre_conflict(para: dict, speaker_role: str | None) -> None:
    """Append genre_conflict flag when genre contradicts speaker_role.

    Call this after build_paraphrase(speaker_role=None) when the role was not yet known at call time
    (e.g. context and paraphrase ran concurrently).
    """
    if not speaker_role or para["paraphrase"] is None:
        return
    genre = para["paraphrase"].get("genre")
    if (speaker_role == "narrator" and genre == "discourse") or \
            (speaker_role == "speaker" and genre == "narrative"):
        para["flags"].append(f"genre_conflict:{speaker_role}:{genre}")
