"""Discovery (task 8): which verses a topic touches, found by the code alone (no model).

Two routes run first, then their union, and every step is kept for the entry's `discovery.steps`:
- Strong's numbers (byztxt Greek NT) project the topic's lemmas onto verse references; the same
  reference is used in every language (NT numbering is shared by the LSG and the KJV);
- word patterns run on each language's own corpus, after the excluded formulas (e.g. "en vérité",
  which translates amen) are stripped from the normalised text.
A verse found by only one route stays a candidate and is listed in the report, never dropped in silence.
Versification (TVTMS) is only checked: the verses that the table mentions are reported, not remapped.

The verdict of the `model` mode (relevance.py) and the excerpt bounds (bounds.py) come after this module.
"""
from __future__ import annotations

import re
from pathlib import Path

import yaml

import strongs
from books import BOOKS
from validate import norm

RULES_PATH = Path(__file__).parent / "data" / "discovery_rules.yml"
_WORD = re.compile(r"[^\W_]+")

Ref = tuple  # (USFM book, chapter, verse) as strings, e.g. ("JHN", "14", "6")


class RulesError(ValueError):
    """data/discovery_rules.yml is missing or invalid."""


class TopicError(ValueError):
    """A topic file has an invalid pattern or exclusion."""


def load_rules(path=RULES_PATH) -> dict:
    """{'excerpt_window': int, 'model_window': int} from data/discovery_rules.yml, checked."""
    try:
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as e:
        raise RulesError(f"cannot read {Path(path).name}: {e}") from None
    try:
        out = {"excerpt_window": raw["excerpt"]["window"], "model_window": raw["model"]["window"]}
    except (KeyError, TypeError):
        raise RulesError("needs excerpt.window and model.window") from None
    for key, value in out.items():
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise RulesError(f"{key} must be a whole number, 0 or more")
    if out["model_window"] < 1:
        raise RulesError("model_window must be at least 1")
    return out


def ref_id(ref: Ref) -> str:
    """('JHN', '14', '6') -> 'JHN.14.6'."""
    return ".".join(ref)


def ref_order(codes: list):
    """Sort key of a reference in canonical order of the given book codes."""
    order = {c: i for i, c in enumerate(codes)}
    return lambda r: (order.get(r[0], len(order)), int(r[1]), int(r[2]))


def neighbours(corpus: dict, code: str, c: str, v: str, span: int = 2) -> list:
    chap = corpus[code][c]
    vs = sorted(chap, key=int)
    i = vs.index(v)
    return [(x, chap[x]) for x in vs[max(0, i - span): i + span + 1]]


# --- patterns ---

def _compile(rules, what: str) -> dict:
    """{name: compiled regex} from a {name: regex} mapping of a topic file."""
    if rules is None:
        return {}
    if not isinstance(rules, dict):
        raise TopicError(f"{what}: must be a mapping of rule name to regex")
    out = {}
    for name, rx in rules.items():
        if not isinstance(name, str) or not name.strip() or not isinstance(rx, str) or not rx:
            raise TopicError(f"{what}: each rule needs a name and a regex string")
        try:
            out[name] = re.compile(rx)
        except re.error as e:
            raise TopicError(f"{what}.{name}: invalid regex ({e})") from None
    return out


def topic_rules(topic: dict, kind: str, lang: str) -> dict:
    """The compiled `patterns_<lang>` or `exclude_phrases_<lang>` of a topic ({} when absent)."""
    key = f"{kind}_{lang}"
    return _compile(topic.get(key), key)


def _matched_word(text: str, rx) -> str | None:
    """The word of the original text (accents and case kept) on which the rule matches."""
    for token in _WORD.findall(text):
        if rx.search(norm(token)):
            return token
    m = rx.search(norm(text))
    return m.group(0) if m else None


def find_pattern_matches(corpus: dict, codes: list, patterns: dict, exclusions: dict | None = None) -> dict:
    """{ref: {'matches': [{'rule', 'matched'}], 'found': [formula names], 'lost': bool}}.

    A verse is recorded when a rule matches its normalised text once the excluded formulas are stripped
    (`matches` filled), or when the only matches were inside an excluded formula (`lost`: True, no matches).
    `matched` is a word of the corpus text. `found` lists the excluded formulas present in the verse.
    """
    patterns = {n: re.compile(p) if isinstance(p, str) else p for n, p in patterns.items()}
    exclusions = {n: re.compile(p) if isinstance(p, str) else p for n, p in (exclusions or {}).items()}
    out: dict = {}
    for code in codes:
        for c in sorted(corpus.get(code, {}), key=int):
            for v in sorted(corpus[code][c], key=int):
                text = corpus[code][c][v]
                t = norm(text)
                t_filtered = t
                for rx in exclusions.values():
                    t_filtered = rx.sub("", t_filtered)
                found = [n for n, rx in exclusions.items() if rx.search(t)]
                matches = [{"rule": n, "matched": _matched_word(text, rx)}
                           for n, rx in patterns.items() if rx.search(t_filtered)]
                if matches:
                    out[(code, c, v)] = {"matches": matches, "found": found, "lost": False}
                elif any(rx.search(t) for rx in patterns.values()):
                    out[(code, c, v)] = {"matches": [], "found": found, "lost": True}
    return out


def find_hits_patterns(corpus: dict, codes: list, patterns: list, exclude_phrases: list | None = None) -> tuple:
    """(hits, excluded_by_phrase): sets of refs, from lists of regexes.

    `excluded_by_phrase` holds the refs that would have matched on the raw text but no longer match
    once the excluded formulas are stripped, i.e. whose only keyword was inside an excluded formula.
    """
    found = find_pattern_matches(
        corpus, codes,
        {f"pattern_{i}": p for i, p in enumerate(patterns)},
        {f"exclusion_{i}": p for i, p in enumerate(exclude_phrases or [])})
    return ({r for r, v in found.items() if v["matches"]}, {r for r, v in found.items() if v["lost"]})


# --- the two routes and their union ---

def discover(topic: dict, corpora: dict, codes: list, byztxt_dir=None) -> dict:
    """Both routes over every language in `corpora` ({lang: corpus}), then their union.

    `byztxt_dir` None skips the Strong's route (the caller says so in the report).
    Returns {'strongs': {ref: [labels]}, 'patterns': {lang: {ref: record}}, 'pattern_rules': {lang: [names]},
    'exclusions': {lang: [names]}, 'candidates': [ref, ...]} with candidates in canonical order.
    """
    labels = [str(s).upper() for s in topic.get("strongs") or []]
    by_strongs = strongs.find_strongs_matches(labels, codes, byztxt_dir) if labels and byztxt_dir else {}
    patterns, pattern_rules, exclusions = {}, {}, {}
    for lang, corpus in corpora.items():
        pats = topic_rules(topic, "patterns", lang)
        excl = topic_rules(topic, "exclude_phrases", lang)
        pattern_rules[lang], exclusions[lang] = list(pats), list(excl)
        patterns[lang] = find_pattern_matches(corpus, codes, pats, excl) if pats else {}
    refs = set(by_strongs)
    for found in patterns.values():
        refs |= {r for r, v in found.items() if v["matches"]}
    return {"strongs": by_strongs, "patterns": patterns, "pattern_rules": pattern_rules,
            "exclusions": exclusions, "candidates": sorted(refs, key=ref_order(codes))}


def routes_of(disc: dict, ref: Ref) -> list:
    """The routes that found a candidate: 'strongs' and/or 'pattern:<lang>'."""
    out = ["strongs"] if ref in disc["strongs"] else []
    out += [f"pattern:{lang}" for lang, found in disc["patterns"].items() if found.get(ref, {}).get("matches")]
    return out


def single_route(disc: dict, ref: Ref) -> bool:
    """True when only one family of routes (Strong's, or patterns in any language) found the verse."""
    routes = routes_of(disc, ref)
    return len({r.split(":")[0] for r in routes}) == 1


def steps_for(disc: dict, ref: Ref, lang: str) -> list:
    """The discovery steps of one candidate verse, as written in the entry of language `lang`.

    `union` and `strongs` are neutral (the same in every language file). `pattern` and `exclusion_check`
    describe the text of `lang`.
    """
    vid = ref_id(ref)
    steps = [{"step": "union", "verse": vid, "routes": routes_of(disc, ref), "single_route": single_route(disc, ref)}]
    if ref in disc["strongs"]:
        steps.append({"step": "strongs", "numbers": list(disc["strongs"][ref]), "verse": vid})
    rec = disc["patterns"].get(lang, {}).get(ref)
    for m in (rec or {}).get("matches", []):
        steps.append({"step": "pattern", "rule": m["rule"], "matched": m["matched"], "verse": vid})
    if disc["exclusions"].get(lang):
        steps.append({"step": "exclusion_check", "verse": vid, "rules": list(disc["exclusions"][lang]),
                      "found": list((rec or {}).get("found", [])), "excluded": bool((rec or {}).get("lost"))})
    return steps


def summarize(disc: dict, candidates: list | None = None) -> dict:
    """Counts and lists for the report, computed from the routes (never by a model)."""
    cands = disc["candidates"] if candidates is None else candidates
    both = [r for r in cands if not single_route(disc, r)]
    only_strongs = [r for r in cands if single_route(disc, r) and ref_id_has(disc, r, "strongs")]
    only_patterns = [r for r in cands if single_route(disc, r) and not ref_id_has(disc, r, "strongs")]
    lost = {}
    cand_set = set(cands)
    for lang, found in disc["patterns"].items():
        lost[lang] = sorted((r for r, v in found.items() if v["lost"]),
                            key=lambda r: (BOOKS.index(r[0]) if r[0] in BOOKS else 999, int(r[1]), int(r[2])))
    return {"both": both, "only_strongs": only_strongs, "only_patterns": only_patterns,
            "lost_by_phrase": lost, "lost_not_candidate": {
                lang: [r for r in refs if r not in cand_set] for lang, refs in lost.items()}}


def ref_id_has(disc: dict, ref: Ref, route: str) -> bool:
    return any(r.split(":")[0] == route for r in routes_of(disc, ref))


# --- versification check (TVTMS) ---

def versification_notes(refs: list, rows: list) -> dict:
    """{verse id: [rules]} for the candidates that TVTMS has a rule for (matched on the book code).

    The table is only used to detect numbering differences; nothing is remapped. For the New Testament
    the LSG and the KJV share their numbering, so an empty result is expected.
    """
    index: dict = {}
    for r in rows:
        index.setdefault(r["source_ref"].lower(), []).append(r)
    notes = {}
    for ref in refs:
        hit = index.get(f"{ref[0].lower()}.{ref[1]}:{ref[2]}")
        if hit:
            notes[ref_id(ref)] = [{"traditions": r["traditions"], "standard_ref": r["standard_ref"],
                                   "action": r["action"]} for r in hit]
    return notes
