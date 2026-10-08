"""Guardrails: nothing enters the final JSON without passing here (schema 2).

Every check returns a list of error strings (empty list = valid). An error
reads "<path>: <code>" so that the review page and the tests can match it.
The code never trusts a model: the excerpt is compared to the corpus, counters
are computed here, and cited sources must exist.
"""
import re
import unicodedata

import requests

LINK = "https://lire.la-bible.net/bible/{ver}/{code}.{c}.{v}-{code}.{c}.{v}"

# --- enumerations (schema 2) ---
SCHEMA_VERSION = "2"
GENRES = {"discourse", "narrative", "letter", "prayer", "parable"}
SPEAKER_ROLES = {"speaker", "narrator"}
SPEAKER_CONFIDENCE = {"high", "medium", "low"}
LITERARY_CONFIDENCE = {"high", "medium", "low"}
DATE_CONFIDENCE = {"certain", "probable", "approximate", "disputed"}
PLACE_CONFIDENCE = DATE_CONFIDENCE
NULL_REASONS = {"no_source", "not_identified", "disputed_no_consensus", "no_faithful_version"}
DATE_NULL_REASONS = {"no_source", "disputed_no_consensus"}
TEMPORAL_KINDS = {"in_text", "scholarly_estimate"}
ERAS = {"CE", "BCE"}
DISCOVERY_MODES = {"rules", "model"}
DAY_METHODS = {"calendar_computation"}

_VERSE_ID = re.compile(r"^([A-Z0-9]{3})\.(\d+)\.(\d+)$")
_ISO_DATE = re.compile(r"^-?\d{4}-\d{2}-\d{2}$")


# --- text helpers ---

def norm(s):
    s = s.replace("’", "'").replace(" ", " ")
    s = unicodedata.normalize("NFD", s)
    s = "".join(ch for ch in s if unicodedata.category(ch) != "Mn")
    return re.sub(r"\s+", " ", s).strip().lower()


def _ws(s):
    """Collapse whitespace (and non-breaking spaces) to single spaces."""
    return re.sub(r"\s+", " ", (s or "").replace(" ", " ")).strip()


def word_count(s):
    return len(_ws(s).split())


def _filled(value):
    """True for a non-empty string that is not an unfilled <placeholder>."""
    return isinstance(value, str) and bool(value.strip()) and not value.strip().startswith("<")


# --- verse ids and corpus ---

def parse_verse_id(vid):
    """'JHN.14.6' -> ('JHN', '14', '6'), or None when malformed."""
    m = _VERSE_ID.match(vid) if isinstance(vid, str) else None
    return (m.group(1), str(int(m.group(2))), str(int(m.group(3)))) if m else None


def _verse_text(corpus, vid):
    p = parse_verse_id(vid)
    if p is None:
        return None
    book, c, v = p
    return corpus.get(book, {}).get(c, {}).get(v)


def _book_order(corpus, book):
    """Verse ids of a book in corpus order (chapters, then verses, numerically)."""
    chapters = corpus.get(book, {})
    return [
        f"{book}.{c}.{v}"
        for c in sorted(chapters, key=int)
        for v in sorted(chapters[c], key=int)
    ]


# --- links (kept for the review page) ---

def build_link(version, code, c, v):
    return LINK.format(ver=version, code=code, c=c, v=v)


def check_link(url, timeout=10):
    try:
        r = requests.head(url, allow_redirects=True, timeout=timeout)
        return r.status_code < 400
    except requests.RequestException:
        return False


# --- excerpt ---

def check_excerpt(excerpt, corpus):
    """Excerpt = exact concatenation of whole, contiguous verses of one book.

    The text must equal the verses joined by one space, after whitespace
    normalisation only. There is no word limit and no fuzzy matching.
    """
    errs = []
    if not isinstance(excerpt, dict):
        return ["excerpt: missing"]
    verses = excerpt.get("verses")
    if not isinstance(verses, list) or not verses:
        return ["excerpt.verses: empty"]
    parsed = [parse_verse_id(v) for v in verses]
    if any(p is None for p in parsed):
        return ["excerpt.verses: malformed_id"]
    if len({p[0] for p in parsed}) != 1:
        return ["excerpt.verses: not_same_book"]
    texts = [_verse_text(corpus, v) for v in verses]
    if any(t is None for t in texts):
        return ["excerpt.verses: not_in_corpus"]
    order = _book_order(corpus, parsed[0][0])
    idx = [order.index(f"{b}.{c}.{v}") for b, c, v in parsed]
    if any(b - a != 1 for a, b in zip(idx, idx[1:])):
        errs.append("excerpt.verses: not_contiguous")
    text = _ws(excerpt.get("text"))
    if not text:
        errs.append("excerpt.text: empty")
    elif text != " ".join(_ws(t) for t in texts):
        errs.append("excerpt.text: not_exact_concatenation")
    return errs


# --- paraphrase ---

def check_paraphrase(paraphrase, excerpt_text):
    """Never longer than the excerpt; genre known; history and arbitration present.

    A null paraphrase needs a reason from NULL_REASONS.
    """
    if not isinstance(paraphrase, dict):
        return ["paraphrase: missing"]
    text = paraphrase.get("text")
    if text is None:
        return [] if paraphrase.get("reason") in NULL_REASONS else ["paraphrase.reason: missing_or_unknown"]
    errs = []
    if not _ws(text):
        return ["paraphrase.text: empty"]
    if word_count(text) > word_count(excerpt_text) + 2:
        errs.append("paraphrase.text: longer_than_excerpt")
    if paraphrase.get("genre") not in GENRES:
        errs.append("paraphrase.genre: unknown")
    history = paraphrase.get("history")
    if not isinstance(history, list) or not history:
        errs.append("paraphrase.history: empty")
        return errs
    for i, h in enumerate(history):
        if not isinstance(h, dict) or not _filled(h.get("model")) or not _filled(h.get("prompt_version")) \
                or not isinstance(h.get("code_checks"), dict) or not isinstance(h.get("verification"), dict):
            errs.append(f"paraphrase.history[{i}]: incomplete")
    arb = paraphrase.get("arbitration")
    chosen = [h for h in history if isinstance(arb, dict) and isinstance(h, dict)
              and h.get("attempt") == arb.get("selected_attempt")]
    if not isinstance(arb, dict) or not _filled(arb.get("reason")):
        errs.append("paraphrase.arbitration: incomplete")
    elif len(chosen) != 1:
        errs.append("paraphrase.arbitration: selected_attempt_not_in_history")
    elif _ws(chosen[0].get("text")) != _ws(text):
        errs.append("paraphrase.arbitration: selected_text_differs")
    return errs


# --- sourced fields ---

def _sources_ok(obj):
    s = obj.get("sources")
    return isinstance(s, list) and bool(s) and all(_filled(x) for x in s)


def check_speaker(speaker):
    """Speaker is sourced and rated, or value null with reason not_identified."""
    if not isinstance(speaker, dict):
        return ["speaker: missing"]
    if speaker.get("value") is None:
        return [] if speaker.get("reason") == "not_identified" else ["speaker.reason: must_be_not_identified"]
    errs = []
    if not _filled(speaker.get("value")):
        errs.append("speaker.value: empty")
    if speaker.get("role") not in SPEAKER_ROLES:
        errs.append("speaker.role: unknown")
    if speaker.get("confidence") not in SPEAKER_CONFIDENCE:
        errs.append("speaker.confidence: invalid")
    if not _sources_ok(speaker):
        errs.append("speaker.sources: missing")
    return errs


def _check_literary(lit):
    if not isinstance(lit, dict):
        return ["context.literary: missing"]
    if lit.get("text") is None:
        return [] if lit.get("reason") in NULL_REASONS else ["context.literary.reason: missing_or_unknown"]
    errs = []
    if not _filled(lit.get("text")):
        errs.append("context.literary.text: empty")
    if lit.get("confidence") not in LITERARY_CONFIDENCE:
        errs.append("context.literary.confidence: invalid")
    if not _sources_ok(lit):
        errs.append("context.literary.sources: missing")
    return errs


def _check_temporal_item(i, t):
    p = f"context.temporal[{i}]"
    if not isinstance(t, dict):
        return [f"{p}: malformed"]
    errs = []
    if t.get("kind") not in TEMPORAL_KINDS:
        errs.append(f"{p}.kind: unknown")
    if t.get("confidence") not in DATE_CONFIDENCE:
        errs.append(f"{p}.confidence: invalid")
    if not _sources_ok(t):
        errs.append(f"{p}.sources: missing")
    dr = t.get("date_range")
    if not isinstance(dr, dict):
        errs.append(f"{p}.date_range: missing")
    else:
        lo, hi = dr.get("from"), dr.get("to")
        if lo is None and hi is None:
            if dr.get("reason") not in DATE_NULL_REASONS:
                errs.append(f"{p}.date_range.reason: missing_or_unknown")
        else:
            ok = all(isinstance(x, int) and not isinstance(x, bool) and x > 0 for x in (lo, hi))
            if not ok:
                errs.append(f"{p}.date_range: bounds_must_be_positive_years")
            elif lo > hi:
                errs.append(f"{p}.date_range: from_after_to")
            if dr.get("era") not in ERAS:
                errs.append(f"{p}.date_range.era: unknown")
    for j, d in enumerate(t.get("day_candidates") or []):
        q = f"{p}.day_candidates[{j}]"
        if not isinstance(d, dict) or not _ISO_DATE.match(str(d.get("date", ""))):
            errs.append(f"{q}.date: invalid")
            continue
        if d.get("method") not in DAY_METHODS:
            errs.append(f"{q}.method: unknown")
        a = d.get("assumptions")
        if not isinstance(a, list) or not a or not all(_filled(x) for x in a):
            errs.append(f"{q}.assumptions: missing")
        if not _sources_ok(d):
            errs.append(f"{q}.sources: missing")
    # A day candidate is never a single fact: with several sources in dispute
    # the level stays "disputed" (computed by the code upstream, not checked here).
    return errs


def check_context(context):
    if not isinstance(context, dict):
        return ["context: missing"]
    errs = _check_literary(context.get("literary"))
    temporal = context.get("temporal")
    if not isinstance(temporal, list):
        errs.append("context.temporal: must_be_list")
    else:
        for i, t in enumerate(temporal):
            errs += _check_temporal_item(i, t)
    places = context.get("places")
    if not isinstance(places, list):
        errs.append("context.places: must_be_list")
    else:
        for i, pl in enumerate(places):
            p = f"context.places[{i}]"
            if not isinstance(pl, dict) or not _filled(pl.get("name")) or not _filled(pl.get("place_id")):
                errs.append(f"{p}: incomplete")
                continue
            if pl.get("confidence") not in PLACE_CONFIDENCE:
                errs.append(f"{p}.confidence: invalid")
            if not _sources_ok(pl):
                errs.append(f"{p}.sources: missing")
    return errs


# --- discovery ---

def check_discovery(discovery):
    if not isinstance(discovery, dict):
        return ["discovery: missing"]
    errs = []
    mode = discovery.get("mode")
    if mode not in DISCOVERY_MODES:
        errs.append("discovery.mode: unknown")
    steps = discovery.get("steps")
    if not isinstance(steps, list) or not steps or not all(isinstance(s, dict) and s.get("step") for s in steps):
        errs.append("discovery.steps: empty_or_malformed")
    elif mode == "model" and not any(s["step"] == "llm_relevance" for s in steps):
        errs.append("discovery.steps: llm_relevance_missing_in_model_mode")
    return errs


# --- sources ---

def _cited_ids(entry):
    """Every source id cited by a field of the entry."""
    cited = list((entry.get("excerpt") or {}).get("verses") or [])
    sp = entry.get("speaker")
    ctx = entry.get("context") if isinstance(entry.get("context"), dict) else {}
    objs = [sp, ctx.get("literary")]
    for t in ctx.get("temporal") or []:
        objs.append(t)
        objs += (t.get("day_candidates") or []) if isinstance(t, dict) else []
    objs += ctx.get("places") or []
    for o in objs:
        if isinstance(o, dict) and isinstance(o.get("sources"), list):
            cited += o["sources"]
    return cited


def check_sources(entry, corpus, known_datasets=None):
    """Each cited source exists, has a license, and is in the corpus or a known dataset.

    known_datasets: set of dataset ids recorded in data/SOURCES.md. When None,
    the dataset membership check is skipped (the other checks still run).
    """
    sources = entry.get("sources")
    if not isinstance(sources, list) or not sources:
        return ["sources: empty"]
    errs, registry = [], set()
    for i, s in enumerate(sources):
        p = f"sources[{i}]"
        if not isinstance(s, dict) or not _filled(s.get("id")):
            errs.append(f"{p}: malformed")
            continue
        registry.add(s["id"])
        for key in ("type", "dataset", "license"):
            if not _filled(s.get(key)):
                errs.append(f"{p}.{key}: missing_or_placeholder")
        if s.get("type") == "bible_text":
            if _verse_text(corpus, s["id"]) is None:
                errs.append(f"{p}: verse_not_in_corpus")
        elif known_datasets is not None and s.get("dataset") not in known_datasets:
            errs.append(f"{p}.dataset: unknown_dataset")
    for cid in sorted(set(_cited_ids(entry)) - registry):
        errs.append(f"sources: cited_but_not_listed:{cid}")
    return errs


# --- whole entry ---

def validate_entry(entry, corpus, known_datasets=None):
    """Validate one schema-2 entry against the language corpus.

    Returns the list of errors; an empty list means the entry passes.
    """
    if not isinstance(entry, dict):
        return ["entry: not_an_object"]
    errs = []
    if entry.get("schema_version") != SCHEMA_VERSION:
        errs.append("schema_version: must_be_2")
    errs += check_excerpt(entry.get("excerpt"), corpus)
    excerpt_text = (entry.get("excerpt") or {}).get("text") or ""
    errs += check_paraphrase(entry.get("paraphrase"), excerpt_text)
    errs += check_speaker(entry.get("speaker"))
    errs += check_context(entry.get("context"))
    errs += check_discovery(entry.get("discovery"))
    errs += check_sources(entry, corpus, known_datasets)
    return errs


# --- cross-language check ---

def _neutral(entry):
    """Language-neutral fields that must be identical across language files."""
    ref = entry.get("reference") or {}
    sp = entry.get("speaker") or {}
    ctx = entry.get("context") or {}
    disc = entry.get("discovery") or {}
    return {
        "reference": (ref.get("book"), ref.get("start"), ref.get("end")),
        "verses": tuple((entry.get("excerpt") or {}).get("verses") or []),
        "speaker_role": sp.get("role"),
        "discovery_mode": disc.get("mode"),
        "strongs_steps": tuple(sorted(
            (s.get("verse"), tuple(s.get("numbers") or []))
            for s in disc.get("steps") or [] if s.get("step") == "strongs")),
        "date_ranges": tuple(
            (t.get("date_range", {}).get("from"), t.get("date_range", {}).get("to"),
             t.get("date_range", {}).get("era"), t.get("date_range", {}).get("reason"),
             tuple((d.get("date"), d.get("method")) for d in t.get("day_candidates") or []))
            for t in ctx.get("temporal") or []),
        "place_ids": tuple(p.get("place_id") for p in ctx.get("places") or []),
        "source_ids": tuple(sorted(
            s.get("id") for s in entry.get("sources") or []
            if s.get("type") != "bible_text"
        )),
    }


def check_cross_language(files):
    """files: {lang: [entry, ...]}. Same references in the same order, same neutral fields."""
    if len(files) < 2:
        return []
    errs = []
    (ref_lang, ref_entries), *others = files.items()
    for lang, entries in others:
        if len(entries) != len(ref_entries):
            errs.append(f"cross:{lang}: entry_count_differs_from_{ref_lang}")
            continue
        for i, (a, b) in enumerate(zip(ref_entries, entries)):
            na, nb = _neutral(a), _neutral(b)
            for key in na:
                if na[key] != nb[key]:
                    errs.append(f"cross:{lang}[{i}].{key}: differs_from_{ref_lang}")
    return errs
