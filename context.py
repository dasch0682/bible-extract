"""Assembles the speaker and the `context` block (literary, temporal, places) of one entry, in one language.

Everything computed by the code comes from the datasets and the rule files (data/*.yml); the models
only write short texts and the literary context (roles `speaker` and `context` of models.yml).
The caller injects the model calls, so this module names no model and makes no network call:

    calls = {"speaker": (call, model_id), "context": (call, model_id)}      # call(system, user) -> str | None

The result is not an entry: the excerpt, the paraphrase, the discovery steps and the review
status are added by the pipeline (tasks 7 and 8). Flags tell the pipeline what a human must look at.
"""
from __future__ import annotations

import datasets as ds
import dating
import day_candidates
import literary
import localize
import narrative
import pericope
import places
import speaker
from provenance import merge_sources

EVENT_LABEL_PROMPT_VERSION = "event-label-1"
PLACE_NAME_PROMPT_VERSION = "place-name-1"

# Flags that force the entry through the review page (the others are information for the reviewer).
REVIEW_REQUIRED = ("speaker_ambiguous", "literary_failed")


def load_data(tmp=ds.TMP) -> dict:
    """The datasets read by this module, loaded once per batch (see scripts/fetch_sources.py)."""
    tmp = ds.Path(tmp)
    return {"theographic": ds.load_theographic(tmp / "theographic"),
            "openbible": ds.load_openbible(tmp / "openbible-geocoding" / "data" / "ancient.jsonl"),
            "speakers": ds.load_speakers(tmp / "speaker-quotations" / "tsv" / "Clear-Aligned-Projections.tsv"),
            "acai": ds.load_acai(tmp / "acai"),
            "anchors": ds.load_anchors()}


def load_rules() -> dict:
    """The rule files, checked: dates, calendar (day candidates), places, pericope and narrative."""
    return {"dates": dating.load_rules(), "calendar": day_candidates.load_rules(),
            "places": places.load_rules(), "pericope": pericope.load_rules(),
            "narrative": narrative.load_rules()}


def review_required(flags: list) -> bool:
    return any(f.split(":")[0] in REVIEW_REQUIRED for f in flags)


def build_context(verse_ids: list, corpus: dict, lang: str, lang_cfg: dict, data: dict, rules: dict,
                  registry: dict, calls: dict, cache_dir) -> dict:
    """{'speaker', 'context', 'sources', 'flags', 'speaker_candidates', 'review_required'} for an excerpt.

    `verse_ids` are the excerpt's verses ('JHN.14.6'), `corpus` is the language corpus.
    """
    book, chapter, _ = verse_ids[0].split(".")
    lines = [f"{v}: {corpus[book][chapter][v.split('.')[2]]}" for v in verse_ids]
    s_call, s_model = calls["speaker"]
    c_call, c_model = calls["context"]

    ident = speaker.identify(verse_ids, data["speakers"], data["acai"])
    name = speaker.render_name(ident["label"], book, lang, lang_cfg, lines, s_call, s_model, cache_dir) \
        if ident["label"] else None
    spk = speaker.build_speaker(ident, name, lang_cfg, registry)

    def label(text):
        return localize.localize("event-label", text, "label of a historical event", lang, lang_cfg, lines,
                                 c_call, c_model, cache_dir, EVENT_LABEL_PROMPT_VERSION)

    def place_name(text):
        return localize.localize("place-name", text, "name of a place of the Bible", lang, lang_cfg, lines,
                                 c_call, c_model, cache_dir, PLACE_NAME_PROMPT_VERSION)

    temporal = dating.build_temporal(verse_ids, data["theographic"], data["anchors"], rules["dates"], registry,
                                     localize_label=label, day_rules=rules["calendar"], lang=lang)
    plc = places.build_places(verse_ids, data["openbible"], rules["places"], registry, localize_name=place_name)
    lit = literary.literary_context(verse_ids, corpus, lang, lang_cfg, c_call, c_model, cache_dir, registry)
    peri = pericope.build_pericope(verse_ids, corpus, lang, lang_cfg, c_call, c_model, cache_dir,
                                   rules["pericope"])
    narr = narrative.build_narrative(verse_ids, corpus, lang, lang_cfg, c_call, c_model, cache_dir, registry,
                                     rules["narrative"], pericope_summary=peri)

    flags = spk["flags"] + temporal["flags"] + plc["flags"] + lit["flags"] + narr["flags"]
    return {
        "speaker": spk["speaker"],
        "context": {"narrative": narr["narrative"], "literary": lit["literary"],
                    "temporal": temporal["temporal"], "places": plc["places"]},
        "sources": merge_sources(spk["sources"], temporal["sources"], plc["sources"],
                                 lit["sources"], narr["sources"]),
        "flags": flags,
        "speaker_candidates": spk["candidates"],
        "review_required": review_required(flags),
    }


def prefill_localize(verse_ids: list, langs: dict, corpora: dict, data: dict, rules: dict,
                     registry: dict, calls: dict, cache_dir) -> None:
    """Pre-fill localize caches for all languages with one call per unique label (--mutualize-langs).

    Runs code-only discovery of labels (places, events, speaker) via collecting callbacks, then
    calls localize_multi for each unique label. Subsequent build_context() calls hit cache for all
    localize calls, reducing total model calls from N_labels × N_langs to N_labels.
    """
    c_call, c_model = calls["context"]
    s_call, s_model = calls["speaker"]
    book, chapter, _ = verse_ids[0].split(".")
    context_by_lang = {
        lang: [f"{v}: {corpora[lang][book][chapter][v.split('.')[2]]}" for v in verse_ids]
        for lang in langs
    }
    place_labels, event_labels = [], []
    places.build_places(verse_ids, data["openbible"], rules["places"], registry,
                        localize_name=lambda t: place_labels.append(t) or None)
    dating.build_temporal(verse_ids, data["theographic"], data["anchors"], rules["dates"], registry,
                          localize_label=lambda t: event_labels.append(t) or None)
    ident = speaker.identify(verse_ids, data["speakers"], data["acai"])
    for label in dict.fromkeys(place_labels):
        localize.localize_multi("place-name", label, "name of a place of the Bible",
                                langs, context_by_lang, c_call, c_model, cache_dir, PLACE_NAME_PROMPT_VERSION)
    for label in dict.fromkeys(event_labels):
        localize.localize_multi("event-label", label, "label of a historical event",
                                langs, context_by_lang, c_call, c_model, cache_dir, EVENT_LABEL_PROMPT_VERSION)
    if ident["label"]:
        book_code = verse_ids[0].split(".")[0]
        extra = (f"A label such as narrator-XXX means 'the narrator' of the book {book_code}: "
                 "answer with the usual word for it.")
        localize.localize_multi("speaker-name", ident["label"], "name of a biblical speaker",
                                langs, context_by_lang, s_call, s_model, cache_dir,
                                speaker.NAME_PROMPT_VERSION, extra=extra)


def prefill_localize_all(ranges: list, langs: dict, corpora: dict, data: dict, rules: dict,
                         registry: dict, calls: dict, cache_dir, workers: int = 4) -> None:
    """Run prefill_localize for all ranges concurrently (--mutualize-langs)."""
    import sys
    from concurrent.futures import ThreadPoolExecutor

    def work(rng):
        try:
            prefill_localize(rng["verses"], langs, corpora, data, rules, registry, calls, cache_dir)
        except Exception as e:  # noqa: BLE001
            print(f"[warn] prefill_localize failed for {rng['verses'][0]}: {type(e).__name__}: {e}",
                  file=sys.stderr)

    with ThreadPoolExecutor(max_workers=workers) as ex:
        list(ex.map(work, ranges))
