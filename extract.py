#!/usr/bin/env python3
"""Usage: python extract.py --topic verite [--lang fr,en] [--dry-run] [--limit N]
                            [--check-links] [--strongs-dir DIR]"""
from __future__ import annotations
import argparse, json, os, re, sys, time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import yaml
from books import scope_codes, NAMES, NAMES_BY_LANG
from validate import norm, validate_entry, check_link

ROOT = Path(__file__).parent
PROMPT_VERSION = "3"
PROMPT_VERSION_EXTRACT = "3e"  # extract-only prompt (no pertinence field)


def _model_slug(model: str) -> str:
    return re.sub(r"[^\w.-]", "_", model)


def make_client(provider: str, base_url: str | None = None):
    if provider == "anthropic":
        from anthropic import Anthropic
        return Anthropic()
    elif provider == "openai_compat":
        api_key = os.getenv("OPENROUTER_API_KEY") or os.getenv("OPENAI_API_KEY")
        return {"base_url": (base_url or "https://openrouter.ai/api/v1").rstrip("/"),
                "api_key": api_key}
    else:
        sys.exit(f"Unknown PROVIDER '{provider}' — supported: anthropic, openai_compat")


def _call_llm(provider: str, client, model: str, system: str, user: str) -> str | None:
    if provider == "anthropic":
        try:
            r = client.messages.create(
                model=model, max_tokens=700, system=system,
                messages=[{"role": "user", "content": user}],
            )
            return r.content[0].text
        except Exception as e:
            print(f"[warn] LLM call failed: {e}", file=sys.stderr)
            return None

    # openai_compat (OpenRouter) — HTTP via requests, retry on 429 with progressive backoff
    import requests as _req
    msgs = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    headers = {"Authorization": f"Bearer {client['api_key']}", "Content-Type": "application/json"}
    url = f"{client['base_url']}/chat/completions"

    def _do_call(use_json_fmt: bool):
        body = {"model": model, "max_tokens": 700, "messages": msgs,
                "reasoning": {"effort": "none"}}
        if use_json_fmt:
            body["response_format"] = {"type": "json_object"}
        return _req.post(url, headers=headers, json=body, timeout=60)

    for attempt in range(4):
        try:
            resp = _do_call(use_json_fmt=True)
            if resp.status_code in (400, 422):
                resp = _do_call(use_json_fmt=False)
            if resp.status_code == 429:
                wait = (2 ** attempt) * 5
                print(f"[warn] 429 rate-limit, attente {wait}s (tentative {attempt + 1}/4)",
                      file=sys.stderr)
                time.sleep(wait)
                continue
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"]
        except Exception as e:
            print(f"[warn] LLM call failed: {e}", file=sys.stderr)
            return None
    return None

SYSTEM_PIVOT_TEMPLATE = """\
Analyze a Bible verse ({translation}) for a thematic anthology.
Write all string values in {prompt_lang}.
Reply ONLY with a JSON object, no surrounding text, with these keys:
- "pertinent" (bool): the verse genuinely addresses the given theme (not a trivial use of the keyword).
- "auteur" (str): who speaks (e.g. "Jésus", "Paul"); for narration give the book author (e.g. "Jean (narrateur)").
- "contexte" (str): one sentence on the situation from the neighboring verses provided.
- "extrait" (str): a CONTIGUOUS passage copied VERBATIM from the verse (preserving accents, punctuation), \
at most {max_words} words, containing the key term.
- "paraphrase" (str|null): summary of the full verse in your words; required if the extract does not cover the whole verse.
Never quote text not present in the verse.{extra_instructions}"""

SYSTEM_EXTRACT_TEMPLATE = """\
Extract a passage from a Bible verse ({translation}) for a thematic anthology.
This verse has already been selected as thematically relevant.
Write all string values in {prompt_lang}.
Reply ONLY with a JSON object, no surrounding text, with these keys:
- "auteur" (str): who speaks (e.g. "Jesus", "Paul"); for narration give the book author (e.g. "John (narrator)").
- "contexte" (str): one sentence on the situation from the neighboring verses provided.
- "extrait" (str): a CONTIGUOUS passage copied VERBATIM from the verse (preserving accents, punctuation), \
at most {max_words} words, containing the key term.
- "paraphrase" (str|null): summary of the full verse in your words; required if the extract does not cover the whole verse.
Never quote text not present in the verse.{extra_instructions}"""


def load_languages() -> dict:
    p = ROOT / "languages.yml"
    if not p.exists():
        sys.exit("languages.yml not found")
    return yaml.safe_load(p.read_text(encoding="utf-8"))


def load_corpus(path: str) -> dict | None:
    p = Path(path)
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


def make_link(lang_cfg: dict, code: str, c: str, v: str) -> str:
    from books import EN_NAMES
    book_names = EN_NAMES if lang_cfg.get("prompt_lang") == "English" else NAMES
    return lang_cfg["link_template"].format(
        ver=lang_cfg["version"], code=code, c=c, v=v,
        book_name=book_names.get(code, code),
    )


def find_hits_patterns(
    corpus: dict, codes: list, patterns: list, exclude_phrases: list | None = None
) -> tuple[set, set]:
    """Return (hits, excluded_by_phrase).

    exclude_phrases are stripped from the normalised text before pattern matching.
    A ref lands in `excluded_by_phrase` when it would have matched on the raw text
    but no longer matches after stripping — i.e. the only keyword occurrence was
    inside an excluded formula.
    """
    rx = [re.compile(p) for p in patterns]
    rx_excl = [re.compile(p) for p in (exclude_phrases or [])]
    hits: set = set()
    excluded: set = set()
    for code in codes:
        for c in sorted(corpus.get(code, {}), key=int):
            for v in sorted(corpus[code][c], key=int):
                t = norm(corpus[code][c][v])
                t_filtered = t
                for rx_e in rx_excl:
                    t_filtered = rx_e.sub("", t_filtered)
                if any(r.search(t_filtered) for r in rx):
                    hits.add((code, c, v))
                elif any(r.search(t) for r in rx):
                    excluded.add((code, c, v))
    return hits, excluded


def _find_hits_strongs(strong_labels: list, codes: list, byztxt_dir: Path) -> set:
    from strongs import find_hits_strongs
    try:
        return find_hits_strongs(strong_labels, codes, byztxt_dir)
    except Exception as e:
        print(f"[warn] Strong's discovery: {e}", file=sys.stderr)
        return set()


def neighbours(corpus: dict, code: str, c: str, v: str, span: int = 2) -> list:
    chap = corpus[code][c]
    vs = sorted(chap, key=int)
    i = vs.index(v)
    return [(x, chap[x]) for x in vs[max(0, i - span): i + span + 1]]


def ask(provider: str, client, model: str, lang_cfg: dict, topic_label: str,
        ctx_lines: list, code: str, c: str, v: str, text: str, max_words: int,
        extra_instructions: str = "", include_relevance: bool = True) -> dict | None:
    template = SYSTEM_PIVOT_TEMPLATE if include_relevance else SYSTEM_EXTRACT_TEMPLATE
    system = template.format(
        translation=lang_cfg["translation"],
        prompt_lang=lang_cfg["prompt_lang"],
        max_words=max_words,
        extra_instructions=("\n" + extra_instructions) if extra_instructions else "",
    )
    user = (
        f"Theme: {topic_label}\nReference: {code} {c}:{v}\nVerse: {text}\n\n"
        "Neighboring verses:\n" + "\n".join(f"{x}: {t}" for x, t in ctx_lines)
    )
    for _ in range(2):
        raw = _call_llm(provider, client, model, system, user)
        if raw is None:
            return None
        m = re.search(r"\{.*\}", raw, re.S)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                pass
    return None


def judge_relevance(
    refs: list, pivot_lang: str, pivot_cfg: dict, pivot_corpus: dict,
    topic: dict, provider: str, client, model: str,
) -> tuple[list, int]:
    """Phase 1: judge relevance once on the pivot language.

    Returns (relevant_refs, skipped_count). Caches under the pivot lang's cache
    dir so run_language for that lang reads from cache without extra LLM calls.
    """
    topic_id = topic["_id"]
    max_words = topic.get("max_words", 14)
    extra_instructions = topic.get("extra_instructions", "")
    cache_dir = ROOT / "cache" / topic_id / pivot_lang
    cache_dir.mkdir(parents=True, exist_ok=True)

    def work(h: tuple) -> tuple:
        code, c, v = h
        verse_text = pivot_corpus.get(code, {}).get(c, {}).get(v)
        if verse_text is None:
            return h, None
        cf = cache_dir / f"{code}.{c}.{v}.{PROMPT_VERSION}.{_model_slug(model)}.json"
        if cf.exists():
            llm = json.loads(cf.read_text(encoding="utf-8"))
        else:
            llm = ask(provider, client, model, pivot_cfg, topic["label"],
                      neighbours(pivot_corpus, code, c, v), code, c, v, verse_text, max_words,
                      extra_instructions=extra_instructions, include_relevance=True)
            if llm is not None:
                cf.write_text(json.dumps(llm, ensure_ascii=False), encoding="utf-8")
        return h, llm

    with ThreadPoolExecutor(max_workers=topic.get("workers", 4)) as ex:
        results = list(ex.map(work, refs))

    relevant, skipped = [], 0
    for ref, llm in results:
        if llm is not None and llm.get("pertinent"):
            relevant.append(ref)
        else:
            skipped += 1
    return relevant, skipped


def run_language(
    lang: str, lang_cfg: dict, topic: dict, refs: list,
    provider: str, client, model: str, check_links: bool,
    is_pivot: bool = False,
) -> tuple[dict, list, dict]:
    """Phase 2: annotate relevant refs for one language.

    Returns (kept_dict, rejected_list, rejected_keys).
      kept_dict:     {(code,c,v): entry}
      rejected_list: [(ref_str, why)]
      rejected_keys: {(code,c,v): why}

    On validation failure the cache is deleted and the LLM is retried up to
    topic["retries"] times before the verse is considered rejected.
    """
    corpus = load_corpus(lang_cfg["corpus"])
    if corpus is None:
        print(f"[{lang}] corpus not found: {lang_cfg['corpus']} — skipping")
        return {}, [], {}

    max_words = topic.get("max_words", 14)
    topic_id = topic["_id"]
    max_retries = topic.get("retries", 2)
    pv = PROMPT_VERSION if is_pivot else PROMPT_VERSION_EXTRACT

    cache_dir = ROOT / "cache" / topic_id / lang
    cache_dir.mkdir(parents=True, exist_ok=True)

    def work(h: tuple) -> tuple:
        code, c, v = h
        verse_text = corpus.get(code, {}).get(c, {}).get(v)
        if verse_text is None:
            return h, None, "verse absent from corpus"
        cf = cache_dir / f"{code}.{c}.{v}.{pv}.{_model_slug(model)}.json"
        last_why = "LLM response unreadable"
        for attempt in range(max_retries + 1):
            if cf.exists() and attempt == 0:
                llm = json.loads(cf.read_text(encoding="utf-8"))
            else:
                if cf.exists():
                    cf.unlink()
                llm = ask(provider, client, model, lang_cfg, topic["label"],
                          neighbours(corpus, code, c, v), code, c, v, verse_text, max_words,
                          extra_instructions=topic.get("extra_instructions", ""),
                          include_relevance=is_pivot)
                if llm is None:
                    continue
                cf.write_text(json.dumps(llm, ensure_ascii=False), encoding="utf-8")
            if llm is None:
                continue
            entry, why = validate_entry(llm, verse_text, max_words)
            if entry is not None:
                return h, entry, None
            last_why = why
        return h, None, last_why

    with ThreadPoolExecutor(max_workers=topic.get("workers", 4)) as ex:
        results = list(ex.map(work, refs))

    book_names = NAMES_BY_LANG.get(lang, NAMES)
    ref_sep = lang_cfg.get("ref_sep", ":")
    kept_dict: dict = {}
    rejected: list = []
    rejected_keys: dict = {}

    for (code, c, v), entry, why in results:
        ref_str = f"{book_names.get(code, code)} {c}{ref_sep}{v}"
        if entry is None:
            rejected.append((ref_str, why))
            rejected_keys[(code, c, v)] = why
        else:
            entry["reference"] = ref_str
            entry["lien"] = make_link(lang_cfg, code, c, v)
            entry["version"] = lang_cfg["version_label"]
            entry["modele"] = model
            if check_links and not check_link(entry["lien"]):
                rejected.append((ref_str, "dead link"))
                rejected_keys[(code, c, v)] = "dead link"
            else:
                kept_dict[(code, c, v)] = entry

    return kept_dict, rejected, rejected_keys


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--topic", required=True)
    ap.add_argument("--lang", help="comma-separated language codes (default: all)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--check-links", action="store_true")
    ap.add_argument("--strongs-dir", default=os.getenv("STRONGS_DIR", "tmp/byztxt"))
    ap.add_argument("--provider", default=os.getenv("PROVIDER", "openai_compat"))
    ap.add_argument("--base-url", default=os.getenv("BASE_URL", "https://openrouter.ai/api/v1"))
    ap.add_argument("--model", default=os.getenv("MODEL", "deepseek/deepseek-v4.1-flash"))
    ap.add_argument("--workers", type=int, default=int(os.getenv("WORKERS", "4")))
    ap.add_argument("--retries", type=int, default=int(os.getenv("RETRIES", "2")))
    a = ap.parse_args()

    topic = yaml.safe_load((ROOT / "topics" / f"{a.topic}.yml").read_text(encoding="utf-8"))
    topic["_id"] = a.topic

    languages = load_languages()
    if a.lang:
        langs = {k: languages[k] for k in a.lang.split(",") if k in languages}
        if not langs:
            sys.exit(f"Unknown language(s): {a.lang}")
    else:
        langs = languages

    topic["workers"] = a.workers
    topic["retries"] = a.retries
    codes = scope_codes(topic.get("scope", "NT"))
    strongs = topic.get("strongs", [])
    patterns = topic.get("patterns", [])
    byztxt_dir = ROOT / a.strongs_dir

    # --- Pivot corpus for pattern cross-check (prefer fr) ---
    pivot_lang = next((l for l in ("fr", "en") if l in langs), next(iter(langs)))
    pivot_corpus = load_corpus(langs[pivot_lang]["corpus"])

    # --- Discovery ---
    refs_strongs: set = set()
    refs_patterns: set = set()
    refs_excluded_patterns: set = set()

    if strongs:
        if byztxt_dir.exists():
            refs_strongs = _find_hits_strongs(strongs, codes, byztxt_dir)
            print(f"Strong's discovery: {len(refs_strongs)} refs")
        else:
            print(f"[warn] --strongs-dir {byztxt_dir} not found; skipping Strong's discovery",
                  file=sys.stderr)

    if patterns:
        if pivot_corpus is not None:
            refs_patterns, refs_excluded_patterns = find_hits_patterns(
                pivot_corpus, codes, patterns, topic.get("exclude_phrases"))
            msg = f"Pattern discovery ({pivot_lang}): {len(refs_patterns)} refs"
            if refs_excluded_patterns:
                msg += f", {len(refs_excluded_patterns)} excluded by phrase filter"
            print(msg)
        else:
            print(f"[warn] no corpus for {pivot_lang}; skipping pattern cross-check",
                  file=sys.stderr)

    if not refs_strongs and not refs_patterns:
        sys.exit("No refs found: provide byztxt data (--strongs-dir) or a corpus for pattern matching")

    all_refs_set = refs_strongs | refs_patterns
    only_strongs = refs_strongs - refs_patterns
    only_patterns = refs_patterns - refs_strongs
    in_both = refs_strongs & refs_patterns

    code_order = {c: i for i, c in enumerate(codes)}
    all_refs = sorted(
        all_refs_set,
        key=lambda r: (code_order.get(r[0], 999), int(r[1]), int(r[2])),
    )
    if a.limit:
        all_refs = all_refs[: a.limit]

    print(f"Total: {len(all_refs)} refs "
          f"({len(in_both)} in both, {len(only_strongs)} Strong's-only, {len(only_patterns)} patterns-only)")

    if a.dry_run:
        for code, c, v in all_refs:
            tag = (" [Strong's-only]" if (code, c, v) in only_strongs
                   else " [patterns-only]" if (code, c, v) in only_patterns else "")
            print(f"  {code} {c}:{v}{tag}")
        return

    client = make_client(a.provider, a.base_url)

    out_dir = ROOT / "out"
    out_dir.mkdir(exist_ok=True)

    # --- Phase 1: relevance judgment on pivot language ---
    if pivot_corpus is None:
        sys.exit(f"Pivot corpus not found for '{pivot_lang}'; cannot judge relevance")
    print(f"\n=== Phase 1: relevance ({pivot_lang}) ===")
    relevant_refs, skipped_relevance = judge_relevance(
        all_refs, pivot_lang, langs[pivot_lang], pivot_corpus,
        topic, a.provider, client, a.model,
    )
    print(f"Relevant: {len(relevant_refs)}/{len(all_refs)}, not relevant: {skipped_relevance}")

    report = [
        f"# Report: {topic['label']}",
        "",
        "## Discovery cross-check",
        f"- Strong's numbers: {strongs}",
        f"- Patterns: {patterns}",
        f"- Excluded phrases (pattern filter): {topic.get('exclude_phrases', [])}",
        f"- Refs by Strong's: {len(refs_strongs)}",
        f"- Refs by patterns ({pivot_lang}): {len(refs_patterns)}",
        f"- Excluded by phrase filter: {len(refs_excluded_patterns)}",
        f"- In both: {len(in_both)}",
        f"- Strong's-only: {len(only_strongs)}",
        f"- Patterns-only: {len(only_patterns)}",
        "",
        "## Relevance judgment",
        f"- Pivot language: {pivot_lang}",
        f"- Candidates evaluated: {len(all_refs)}",
        f"- Relevant: {len(relevant_refs)}",
        f"- Not relevant: {skipped_relevance}",
        "",
    ]
    if refs_excluded_patterns:
        report.append("### Excluded by phrase filter")
        report += [f"  - {c} {ch}:{v}" for c, ch, v in
                   sorted(refs_excluded_patterns, key=lambda r: (code_order.get(r[0], 999), int(r[1]), int(r[2])))]
        report.append("")
    if only_strongs:
        report.append("### Strong's-only")
        report += [f"  - {c} {ch}:{v}" for c, ch, v in
                   sorted(only_strongs, key=lambda r: (code_order.get(r[0], 999), int(r[1]), int(r[2])))]
        report.append("")
    if only_patterns:
        report.append("### Patterns-only")
        report += [f"  - {c} {ch}:{v}" for c, ch, v in
                   sorted(only_patterns, key=lambda r: (code_order.get(r[0], 999), int(r[1]), int(r[2])))]
        report.append("")

    # --- Phase 2: per-language annotation ---
    kept_by_lang: dict = {}
    rejected_by_lang: dict = {}
    rejected_keys_by_lang: dict = {}

    for lang, lang_cfg in langs.items():
        print(f"\n=== {lang} ({lang_cfg['translation']}) ===")
        kept_dict, rejected, rejected_keys = run_language(
            lang, lang_cfg, topic, relevant_refs, a.provider, client, a.model, a.check_links,
            is_pivot=(lang == pivot_lang),
        )
        kept_by_lang[lang] = kept_dict
        rejected_by_lang[lang] = rejected
        rejected_keys_by_lang[lang] = rejected_keys
        print(f"  validated: {len(kept_dict)}, rejected: {len(rejected)}")

    # --- Intersection: keep only refs that passed in ALL languages ---
    common_refs_set = set(relevant_refs)
    for kept in kept_by_lang.values():
        common_refs_set &= set(kept.keys())
    common_refs = sorted(
        common_refs_set, key=lambda r: (code_order.get(r[0], 999), int(r[1]), int(r[2]))
    )
    print(f"\nIntersection: {len(common_refs)} refs kept in all languages "
          f"(dropped {len(relevant_refs) - len(common_refs)})")

    for lang in langs:
        kept_ordered = [kept_by_lang[lang][ref] for ref in common_refs]
        (out_dir / f"{a.topic}.{lang}.json").write_text(
            json.dumps(kept_ordered, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    # --- Report ---
    for lang, lang_cfg in langs.items():
        report += [
            f"## {lang}: {lang_cfg['translation']}",
            f"- relevant refs: {len(relevant_refs)}",
            f"- kept after validation+retries: {len(kept_by_lang[lang])}",
            f"- rejected: {len(rejected_by_lang[lang])}",
            "",
        ]
        if rejected_by_lang[lang]:
            report += [f"  - {r}: {w}" for r, w in rejected_by_lang[lang]]
            report.append("")

    dropped = [r for r in relevant_refs if r not in common_refs_set]
    report += [
        "## Intersection",
        f"- kept in all languages: {len(common_refs)}",
        f"- dropped (failed in ≥1 language): {len(dropped)}",
        "",
    ]
    if dropped:
        for code, c, v in sorted(dropped, key=lambda r: (code_order.get(r[0], 999), int(r[1]), int(r[2]))):
            reasons = [f"{lg}: {rejected_keys_by_lang[lg][(code,c,v)]}"
                       for lg in langs if (code, c, v) in rejected_keys_by_lang[lg]]
            report.append(f"  - {code} {c}:{v} — {', '.join(reasons)}")
        report.append("")

    (out_dir / f"{a.topic}.report.md").write_text("\n".join(report), encoding="utf-8")
    print("\n".join(report))


if __name__ == "__main__":
    main()
