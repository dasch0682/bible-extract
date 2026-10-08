#!/usr/bin/env python3
"""Usage: python extract.py --topic verite [--lang fr,en] [--mode rules|model] [--dry-run] [--limit N]
                            [--workers N] [--workers-inner N] [--strongs-dir DIR] [--data-dir DIR]

The whole pipeline of the specification, schema 2:
  discovery (Strong's + word patterns, then rules or model mode) -> excerpt bounds -> speaker and context
  -> paraphrase -> sources -> validate.py -> cross-language check -> out/<topic>.<lang>.json + report.

Every model call goes through a role of models.yml; this file names no model. The price check runs before the
first call. The modules receive their model calls by injection, so they can be tested without a network.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import yaml

import bounds
import context
import datasets as ds
import discovery
import paraphrase
import provenance
import relevance
import validate
from books import NAMES, NAMES_BY_LANG, scope_codes
from models import format_report, load_models, run_check

ROOT = Path(__file__).parent
MAX_TOKENS = 2000                      # room for three paraphrase candidates of a multi-verse excerpt
CALL_ROLES = ("speaker", "context", "paraphrase_generation", "paraphrase_verification", "relevance")


# --- inputs ---

def load_languages() -> dict:
    p = ROOT / "languages.yml"
    if not p.exists():
        sys.exit("languages.yml not found")
    return yaml.safe_load(p.read_text(encoding="utf-8"))


def load_corpus(path: str) -> dict | None:
    p = ROOT / path
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def load_topic(name: str) -> dict:
    p = ROOT / "topics" / f"{name}.yml"
    if not p.exists():
        sys.exit(f"topic not found: {p}")
    topic = yaml.safe_load(p.read_text(encoding="utf-8"))
    topic["_id"] = name
    return topic


def topic_label(topic: dict, lang: str) -> str:
    key = f"label_{lang}"
    if key not in topic:
        print(f"[warn] topic '{topic.get('_id', '?')}' missing '{key}' - falling back to 'label'", file=sys.stderr)
    return topic.get(key) or topic["label"]


# --- model calls (OpenRouter over requests, no SDK) ---

def make_call(api_key: str, base_url: str, model: str, max_tokens: int = MAX_TOKENS, post=None, sleep=time.sleep):
    """call(system, user) -> text | None for one model. Retries 429 with a progressive wait; any other failure is None."""
    if post is None:
        import requests
        post = requests.post
    url = f"{base_url.rstrip('/')}/chat/completions"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    def call(system: str, user: str):
        body = {"model": model, "max_tokens": max_tokens, "reasoning": {"effort": "none"},
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
        for attempt in range(4):
            try:
                resp = post(url, headers=headers, json=body, timeout=90)
                if resp.status_code == 429:
                    wait = (2 ** attempt) * 5
                    print(f"[warn] 429 rate limit, waiting {wait}s (attempt {attempt + 1}/4)", file=sys.stderr)
                    sleep(wait)
                    continue
                resp.raise_for_status()
                return resp.json()["choices"][0]["message"]["content"]
            except Exception as e:  # noqa: BLE001 - a failed call is a missing answer, the modules handle it
                print(f"[warn] model call failed: {type(e).__name__}", file=sys.stderr)
                return None
        return None

    return call


def build_calls(roles: dict, make) -> dict:
    """{role: (call, model id)} for the roles the modules use; `make(model_id)` builds one call."""
    return {role: (make(roles[role]), roles[role]) for role in CALL_ROLES}


# --- references ---

def ref_label(lang: str, lang_cfg: dict, ids: list) -> str:
    """'Jean 14,6' / 'Jean 14,6-8' / 'Jean 14,30-15,2' (separator from languages.yml)."""
    book = ids[0].split(".")[0]
    name = NAMES_BY_LANG.get(lang, NAMES).get(book, book)
    sep = lang_cfg.get("ref_sep", ":")
    (_, c1, v1), (_, c2, v2) = ids[0].split("."), ids[-1].split(".")
    if ids[0] == ids[-1]:
        tail = f"{c1}{sep}{v1}"
    elif c1 == c2:
        tail = f"{c1}{sep}{v1}-{v2}"
    else:
        tail = f"{c1}{sep}{v1}-{c2}{sep}{v2}"
    return f"{name} {tail}"


def in_every_corpus(corpora: dict, vid: str) -> bool:
    """True when the verse id exists in the corpus of every language."""
    p = validate.parse_verse_id(vid)
    return p is not None and all(c.get(p[0], {}).get(p[1], {}).get(p[2]) is not None for c in corpora.values())


def excerpt_text(corpus: dict, ids: list) -> str:
    return " ".join(corpus[b][c][v] for b, c, v in (i.split(".") for i in ids))


# --- selection and bounds ---

def plan_ranges(disc: dict, candidates: list, mode: str, pivot: str, langs: dict, corpora: dict, topic: dict,
                rules: dict, quotations: list, calls: dict | None, cache_dir, workers: int = 2) -> dict:
    """Decide which candidates are kept and which verses each excerpt covers.

    rules mode: every candidate is kept; the code gives the bounds (bounds.rules_bounds).
    model mode: the model judges each candidate once, on the pivot language (relevance.judge).
    Returns {'ranges', 'verdicts', 'not_relevant', 'no_verdict'}; nothing is dropped without being listed.
    """
    corpus = corpora[pivot]
    verdicts, not_relevant, no_verdict, items = {}, [], [], []
    if mode == "rules":
        for ref in candidates:
            b = bounds.rules_bounds(ref, corpus, quotations, rules["excerpt_window"])
            items.append({"verses": b["verses"], "candidates": [ref]})
    else:
        call, model = calls["relevance"]
        extra = topic.get(f"extra_instructions_{pivot}") or topic.get("extra_instructions", "")
        label = topic_label(topic, pivot)

        def work(ref):
            return relevance.judge(discovery.ref_id(ref), corpus, pivot, langs[pivot], label, extra,
                                   call, model, cache_dir, rules["model_window"])
        with ThreadPoolExecutor(max_workers=workers) as ex:
            results = list(ex.map(work, candidates))
        for ref, v in zip(candidates, results):
            if v is None:
                no_verdict.append(ref)
            elif not v["relevant"]:
                not_relevant.append(ref)
            else:
                verdicts[ref] = v
                items.append({"verses": v["verses"], "candidates": [ref]})
    return {"ranges": bounds.merge_ranges(items, corpus), "verdicts": verdicts,
            "not_relevant": not_relevant, "no_verdict": no_verdict}


# --- one entry ---

def range_steps(rng: dict, disc: dict, lang: str, mode: str, verdicts: dict, codes: list) -> list:
    steps = []
    for ref in sorted(rng["candidates"], key=discovery.ref_order(codes)):
        steps += discovery.steps_for(disc, ref, lang)
        if mode == "model":
            v = verdicts[ref]
            steps.append({"step": "llm_relevance", "verse": discovery.ref_id(ref), "model": v["model"],
                          "prompt_version": v["prompt_version"], "verdict": "relevant",
                          "cited_verses": list(v["cited_verses"])})
    return steps


def build_entry(verse_ids: list, steps: list, mode: str, lang: str, lang_cfg: dict, corpus: dict, shared: dict,
                calls: dict, cache_dir, workers_inner: int = 1) -> dict:
    """One schema-2 entry of language `lang` for an excerpt (the caller validates it).

    When workers_inner >= 2, context.build_context and paraphrase.build_paraphrase run concurrently
    (paraphrase is called without the speaker role; apply_genre_conflict is called after both complete).
    """
    registry = shared["registry"]
    text = excerpt_text(corpus, verse_ids)
    if workers_inner >= 2:
        with ThreadPoolExecutor(max_workers=2) as ex:
            fut_ctx = ex.submit(context.build_context, verse_ids, corpus, lang, lang_cfg,
                                shared["data"], shared["rules"], registry, calls, cache_dir)
            fut_para = ex.submit(paraphrase.build_paraphrase, text, verse_ids, lang, lang_cfg,
                                 calls, cache_dir, shared["paraphrase_rules"])
            built = fut_ctx.result()
            para = fut_para.result()
        spk = built["speaker"]
        role = spk.get("role") if spk.get("value") is not None else None
        paraphrase.apply_genre_conflict(para, role)
    else:
        built = context.build_context(verse_ids, corpus, lang, lang_cfg, shared["data"], shared["rules"], registry,
                                      calls, cache_dir)
        spk = built["speaker"]
        role = spk.get("role") if spk.get("value") is not None else None
        para = paraphrase.build_paraphrase(text, verse_ids, lang, lang_cfg, calls, cache_dir,
                                           shared["paraphrase_rules"], role)
    numbers = sorted({n for s in steps if s["step"] == "strongs" for n in s["numbers"]}, key=lambda n: int(n[1:]))
    sources = provenance.merge_sources(
        [provenance.verse_source(v, lang_cfg["dataset"], registry) for v in verse_ids],
        [provenance.dataset_source(n, "byztxt", "concordance", registry) for n in numbers],
        built["sources"])
    flags = list(built["flags"]) + list(para["flags"])
    required = bool(built["review_required"] or paraphrase.review_required(para["flags"]))
    book = verse_ids[0].split(".")[0]
    return {
        "schema_version": validate.SCHEMA_VERSION,
        "language": lang,
        "translation": lang_cfg["version_label"],
        "reference": {"book": book, "start": verse_ids[0].split(".", 1)[1], "end": verse_ids[-1].split(".", 1)[1],
                      "label": ref_label(lang, lang_cfg, verse_ids)},
        "excerpt": {"text": text, "verses": list(verse_ids)},
        "paraphrase": para["paraphrase"],
        "speaker": spk,
        "context": built["context"],
        "discovery": {"mode": mode, "steps": steps},
        "review": {"status": None, "note": None, "flags": flags, "required": required},
        "sources": sources,
    }


def produce(plan: dict, disc: dict, mode: str, langs: dict, corpora: dict, shared: dict, calls: dict, cache_dir,
            codes: list, workers: int = 4, workers_inner: int = 1) -> dict:
    """{lang: [(entry | None, [errors]) per range]}; an entry is valid when its error list is empty."""
    known = provenance.known_datasets(shared["registry"])
    jobs = [(i, lang) for i in range(len(plan["ranges"])) for lang in langs]

    def work(job):
        i, lang = job
        rng = plan["ranges"][i]
        try:
            entry = build_entry(rng["verses"], range_steps(rng, disc, lang, mode, plan["verdicts"], codes), mode,
                                lang, langs[lang], corpora[lang], shared, calls, cache_dir, workers_inner)
            return job, entry, validate.validate_entry(entry, corpora[lang], known)
        except Exception as e:  # noqa: BLE001 - one failed entry must not lose the batch (answers are cached)
            return job, None, [f"exception: {type(e).__name__}: {e}"]

    out = {lang: [None] * len(plan["ranges"]) for lang in langs}
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for (i, lang), entry, errs in ex.map(work, jobs):
            out[lang][i] = (entry, errs)
    return out


def intersect(plan: dict, built: dict) -> tuple:
    """(kept range indexes, {index: [reasons]}): a range is kept when its entry is valid in every language."""
    kept, dropped = [], {}
    for i in range(len(plan["ranges"])):
        reasons = [f"{lang}: {'; '.join(res[i][1])}" for lang, res in built.items() if res[i][1]]
        if reasons:
            dropped[i] = reasons
        else:
            kept.append(i)
    return kept, dropped


# --- report ---

def _refs(refs: list) -> list:
    return [f"  - {discovery.ref_id(r)}" for r in refs]


def build_report(info: dict) -> str:
    topic, disc, summary = info["topic"], info["disc"], info["summary"]
    labels = ", ".join(l + "=" + json.dumps(topic_label(topic, l), ensure_ascii=False) for l in info["langs"])
    lines = [f"# Report: {topic['label']}", "", *info["price_report"].splitlines(), "",
             "## Discovery",
             f"- Mode: {info['mode']}",
             f"- Labels: {labels}",
             f"- Strong's numbers: {topic.get('strongs', [])}"
             + ("" if info["strongs_used"] else " (route skipped: Greek data not found)"),
             f"- Refs by Strong's: {len(disc['strongs'])}"]
    for lang in info["langs"]:
        hits = sum(1 for v in disc["patterns"][lang].values() if v["matches"])
        lines.append(f"- Refs by patterns ({lang}, rules {disc['pattern_rules'][lang]}): {hits}")
        if disc["exclusions"][lang]:
            lines.append(f"- Excluded formulas ({lang}): {disc['exclusions'][lang]}; verses whose only match was "
                         f"inside one: {len(summary['lost_by_phrase'][lang])}")
    lines += [f"- Candidates: {len(disc['candidates'])} (kept for the run: {len(info['candidates'])})",
              f"- Found by both routes: {len(summary['both'])}",
              f"- Strong's only: {len(summary['only_strongs'])}",
              f"- Patterns only: {len(summary['only_patterns'])}", ""]
    for title, refs in (("Strong's only", summary["only_strongs"]), ("Patterns only", summary["only_patterns"])):
        if refs:
            lines += [f"### {title}", *_refs(refs), ""]
    for lang, refs in summary["lost_by_phrase"].items():
        if refs:
            lines += [f"### Excluded by phrase filter ({lang})", *_refs(refs), ""]
    if info["absent"]:
        lines += ["### Candidates absent from a language corpus (dropped)", *_refs(info["absent"]), ""]
    notes = info["versification"]
    if notes is None:
        lines += ["## Versification", "- TVTMS not found: numbering was not checked.", ""]
    else:
        lines += ["## Versification",
                  f"- TVTMS has a rule for {len(notes)} candidate verse(s); nothing is remapped."]
        lines += [f"  - {vid}: {n}" for vid, n in notes.items()]
        lines.append("")
    if info["mode"] == "model":
        lines += ["## Relevance judgement (pivot language: " + info["pivot"] + ")",
                  f"- Candidates judged: {len(info['candidates'])}",
                  f"- Relevant: {len(info['plan']['verdicts'])}",
                  f"- Not relevant: {len(info['plan']['not_relevant'])}",
                  f"- No valid verdict (not kept): {len(info['plan']['no_verdict'])}", ""]
        for title, refs in (("Not relevant", info["plan"]["not_relevant"]), ("No valid verdict", info["plan"]["no_verdict"])):
            if refs:
                lines += [f"### {title}", *_refs(refs), ""]
    ranges = info["plan"]["ranges"]
    merged = [r for r in ranges if r["merged_from"] > 1]
    lines += ["## Excerpts",
              f"- Excerpts: {len(ranges)} (window of rules mode: {info['rules']['excerpt_window']})",
              f"- Merged because they overlapped: {len(merged)}"]
    lines += [f"  - {r['verses'][0]} to {r['verses'][-1]}: {r['merged_from']} candidates" for r in merged]
    lines.append("")
    for lang in info["langs"]:
        res = info["built"][lang]
        lines += [f"## {lang}: {info['langs'][lang]['translation']}",
                  f"- excerpts: {len(res)}",
                  f"- valid: {sum(1 for _, errs in res if not errs)}",
                  f"- rejected: {sum(1 for _, errs in res if errs)}", ""]
    lines += ["## Intersection",
              f"- kept in all languages: {len(info['kept'])}",
              f"- dropped (invalid in at least one language): {len(info['dropped'])}", ""]
    for i, reasons in info["dropped"].items():
        v = ranges[i]["verses"]
        lines.append(f"  - {v[0]} to {v[-1]} - {' | '.join(reasons)}")
    if info["dropped"]:
        lines.append("")
    review = []
    for i in info["kept"]:
        entries = [info["built"][lang][i][0] for lang in info["langs"]]
        flags = sorted({f for e in entries for f in e["review"]["flags"]})
        review.append((i, flags, any(e["review"]["required"] for e in entries)))
    lines += ["## Review", f"- entries that must go through the review page: {sum(1 for _, _, req in review if req)}", ""]
    for i, flags, required in review:
        if flags or required:
            v = ranges[i]["verses"]
            lines.append(f"  - {v[0]} to {v[-1]}{' (review required)' if required else ''}: {', '.join(flags) or '-'}")
    lines.append("")
    if info["cross_errors"]:
        lines += ["## Cross-language check: FAILED", *[f"  - {e}" for e in info["cross_errors"]], ""]
    else:
        lines += ["## Cross-language check", "- neutral fields identical in every language file", ""]
    return "\n".join(lines)


# --- main ---

def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--topic", required=True)
    ap.add_argument("--lang", help="comma-separated language codes (default: all)")
    ap.add_argument("--mode", choices=["rules", "model"], default="rules",
                    help="discovery mode: the code decides (rules) or the language model judges relevance (model)")
    ap.add_argument("--dry-run", action="store_true", help="discovery and bounds only, no model call")
    ap.add_argument("--limit", type=int, help="keep only the first N candidates")
    ap.add_argument("--workers", type=int, default=int(os.getenv("WORKERS", "4")),
                    help="outer parallelism: how many (range × lang) entries build concurrently (default 4)")
    ap.add_argument("--workers-inner", type=int, default=int(os.getenv("WORKERS_INNER", "1")),
                    help="inner parallelism per entry: context and paraphrase run concurrently when >= 2 (default 1)")
    ap.add_argument("--mutualize-langs", action="store_true",
                    help="one localize call per label for all languages instead of one per language (default off)")
    ap.add_argument("--strongs-dir", default=os.getenv("STRONGS_DIR", "tmp/byztxt"))
    ap.add_argument("--data-dir", default=os.getenv("DATA_DIR", "tmp"))
    ap.add_argument("--base-url", default=os.getenv("BASE_URL", "https://openrouter.ai/api/v1"))
    a = ap.parse_args(argv)

    topic = load_topic(a.topic)
    languages = load_languages()
    if a.lang:
        langs = {k: languages[k] for k in a.lang.split(",") if k in languages}
        if not langs:
            sys.exit(f"Unknown language(s): {a.lang}")
    else:
        langs = languages
    corpora = {}
    for lang, cfg in langs.items():
        corpora[lang] = load_corpus(cfg["corpus"])
        if corpora[lang] is None:
            sys.exit(f"[{lang}] corpus not found: {cfg['corpus']} (see data/README.md)")
    pivot = next((l for l in ("fr", "en") if l in langs), next(iter(langs)))
    rules = discovery.load_rules()
    codes = scope_codes(topic.get("scope", "NT"))
    data_dir = ROOT / a.data_dir
    byztxt = ROOT / a.strongs_dir

    # --- discovery: the code alone ---
    strongs_used = bool(topic.get("strongs")) and byztxt.exists()
    if topic.get("strongs") and not strongs_used:
        print(f"[warn] --strongs-dir {byztxt} not found; skipping Strong's discovery", file=sys.stderr)
    try:
        disc = discovery.discover(topic, corpora, codes, byztxt if strongs_used else None)
    except discovery.TopicError as e:
        sys.exit(f"topic {a.topic}: {e}")
    if not disc["candidates"]:
        sys.exit("No refs found: provide byztxt data (--strongs-dir) or word patterns for the languages")
    absent = [r for r in disc["candidates"] if not in_every_corpus(corpora, discovery.ref_id(r))]
    candidates = [r for r in disc["candidates"] if r not in absent]
    if a.limit:
        candidates = candidates[: a.limit]
    summary = discovery.summarize(disc, candidates)
    print(f"Candidates: {len(candidates)} ({len(summary['both'])} by both routes, "
          f"{len(summary['only_strongs'])} Strong's only, {len(summary['only_patterns'])} patterns only)")

    try:
        tvtms_path = next((data_dir / "stepbible" / "Versification").glob("TVTMS*.txt"), None)
        notes = discovery.versification_notes(candidates, ds.load_tvtms(tvtms_path)) if tvtms_path else None
    except (OSError, ValueError):
        notes = None

    if a.dry_run:
        try:
            quotations = ds.load_speakers(data_dir / "speaker-quotations" / "tsv" / "Clear-Aligned-Projections.tsv")
        except OSError:
            quotations = []
            print("[warn] speaker-quotations not found: excerpts are single verses in this preview", file=sys.stderr)
        for ref in candidates:
            tag = "+".join(discovery.routes_of(disc, ref)) + (" [single route]" if discovery.single_route(disc, ref) else "")
            span = ""
            if a.mode == "rules":
                v = bounds.rules_bounds(ref, corpora[pivot], quotations, rules["excerpt_window"])["verses"]
                span = f"  excerpt {v[0]} to {v[-1]}"
            print(f"  {discovery.ref_id(ref)}  {tag}{span}")
        return 0

    # --- price check: first step of any batch that calls a model. In doubt, stop. ---
    price_check = run_check()
    print(format_report(price_check))
    if not price_check.ok:
        sys.exit("Price check failed: no model call was made. "
                 "Edit models.yml (new price_ref or another model) to continue.")
    api_key = os.getenv("OPENROUTER_API_KEY") or os.getenv("OPENAI_API_KEY")
    if not api_key:
        sys.exit("OPENROUTER_API_KEY is not set")
    try:
        data = context.load_data(data_dir)
    except (OSError, ValueError) as e:
        sys.exit(f"datasets not found in {data_dir} ({type(e).__name__}); run: python scripts/fetch_sources.py --fetch")
    shared = {"data": data, "rules": context.load_rules(), "paraphrase_rules": paraphrase.load_rules(),
              "registry": provenance.load_registry()}
    calls = build_calls(load_models().roles, lambda model: make_call(api_key, a.base_url, model))
    cache_dir = ROOT / "cache" / a.topic

    plan = plan_ranges(disc, candidates, a.mode, pivot, langs, corpora, topic, rules, data["speakers"], calls,
                       cache_dir, a.workers)
    plan["ranges"] = [r for r in plan["ranges"]            # a verse of the pivot corpus must exist in every language
                      if all(in_every_corpus(corpora, v) for v in r["verses"])]
    print(f"Excerpts: {len(plan['ranges'])} from {len(candidates)} candidates")

    if a.mutualize_langs:
        print(f"Pre-filling localize caches ({len(plan['ranges'])} ranges × {len(langs)} languages)...")
        context.prefill_localize_all(plan["ranges"], langs, corpora, shared["data"], shared["rules"],
                                     shared["registry"], calls, cache_dir, a.workers)
    built = produce(plan, disc, a.mode, langs, corpora, shared, calls, cache_dir, codes, a.workers, a.workers_inner)
    kept, dropped = intersect(plan, built)
    out_dir = ROOT / "out"
    out_dir.mkdir(exist_ok=True)
    files = {lang: [built[lang][i][0] for i in kept] for lang in langs}
    for lang, entries in files.items():
        (out_dir / f"{a.topic}.{lang}.json").write_text(json.dumps(entries, ensure_ascii=False, indent=2),
                                                        encoding="utf-8")
    cross_errors = validate.check_cross_language(files)
    report = build_report({
        "topic": topic, "mode": a.mode, "langs": langs, "pivot": pivot, "disc": disc, "summary": summary,
        "candidates": candidates, "absent": absent, "strongs_used": strongs_used, "versification": notes,
        "plan": plan, "rules": rules, "built": built, "kept": kept, "dropped": dropped,
        "cross_errors": cross_errors, "price_report": format_report(price_check)})
    (out_dir / f"{a.topic}.report.md").write_text(report, encoding="utf-8")
    print(report)
    return 1 if cross_errors else 0


if __name__ == "__main__":
    sys.exit(main())
