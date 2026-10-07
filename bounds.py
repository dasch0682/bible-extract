"""Excerpt bounds and merging (task 8).

An excerpt is whole, contiguous verses of one book (validate.check_excerpt checks it against the corpus).
In `rules` mode the code chooses the bounds: the verse that was found, extended by at most `window` verses
on each side, never beyond the speaker-quotations range that covers it (the innermost one when several do),
and the verse alone when no quotation covers it. In `model` mode the bounds come from the model's answer
(relevance.py), already checked. Excerpts that overlap are merged into one, so a verse is never written twice.
"""
from __future__ import annotations

import datasets as ds
from books import BOOKS


def verse_order(corpus: dict, book: str) -> list:
    """Verse ids of a book in corpus order (chapters, then verses, numerically)."""
    return [f"{book}.{c}.{v}"
            for c in sorted(corpus.get(book, {}), key=int)
            for v in sorted(corpus[book][c], key=int)]


def rules_bounds(ref: tuple, corpus: dict, quotations: list, window: int) -> dict:
    """{'verses': [ids], 'quotation': [start id, end id] | None} for a found verse (rules mode).

    Raises ValueError when the verse is not in the corpus (the caller filters those out first).
    """
    order = verse_order(corpus, ref[0])
    pos = {vid: i for i, vid in enumerate(order)}
    vid = ".".join(ref)
    if vid not in pos:
        raise ValueError(f"verse not in corpus: {vid}")
    i = pos[vid]
    lo = hi = i                                   # the verse alone, unless a quotation covers it
    key = ds.verse_key(vid)
    best = None                                   # innermost covering quotation: (span, start id, end id)
    for q in quotations:
        if q["start"] <= key <= q["end"]:
            s, e = ds.key_to_id(q["start"]), ds.key_to_id(q["end"])
            if s in pos and e in pos and (best is None or pos[e] - pos[s] < best[0]):
                best = (pos[e] - pos[s], s, e)
    quotation = None
    if best:
        _, s, e = best
        lo, hi, quotation = max(i - window, pos[s]), min(i + window, pos[e]), [s, e]
    return {"verses": order[lo:hi + 1], "quotation": quotation}


def merge_ranges(items: list, corpus: dict) -> list:
    """Merge the excerpts that share a verse; neighbours that only touch stay apart.

    items: [{'verses': [ids], 'candidates': [refs]}]. Returns the same shape plus 'merged_from' (how many
    items were joined), sorted in canonical order of book, chapter and verse.
    """
    by_book: dict = {}
    for it in items:
        by_book.setdefault(it["verses"][0].split(".")[0], []).append(it)
    out = []
    for book in sorted(by_book, key=lambda b: BOOKS.index(b) if b in BOOKS else len(BOOKS)):
        order = verse_order(corpus, book)
        pos = {vid: i for i, vid in enumerate(order)}
        spans = sorted(((pos[it["verses"][0]], pos[it["verses"][-1]], it) for it in by_book[book]),
                       key=lambda s: (s[0], s[1]))
        cur = None
        for start, end, it in spans:
            if cur and start <= cur["end"]:
                cur["end"] = max(cur["end"], end)
                cur["candidates"] += [c for c in it["candidates"] if c not in cur["candidates"]]
                cur["merged_from"] += 1
            else:
                if cur:
                    out.append(cur)
                cur = {"start": start, "end": end, "candidates": list(it["candidates"]), "merged_from": 1}
            cur["order"] = order
        if cur:
            out.append(cur)
    return [{"verses": r["order"][r["start"]:r["end"] + 1], "candidates": r["candidates"],
             "merged_from": r["merged_from"]} for r in out]
