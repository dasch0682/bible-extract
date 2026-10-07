"""Tests for bounds.py (task 8): rules-mode excerpt bounds and the merge of overlapping excerpts."""
import pytest

import bounds
import datasets as ds
import validate


def corpus(book="JHN", chapters=None):
    chapters = chapters or {"14": 10, "15": 6}
    return {book: {c: {str(v): f"verse {c}.{v}" for v in range(1, n + 1)} for c, n in chapters.items()}}


def quote(start, end, speaker="Jesus"):
    return {"start": ds.verse_key(start), "end": ds.verse_key(end), "speaker": speaker, "type": "Dialogue"}


def ids(result):
    return result["verses"]


# --- rules-mode bounds ---

def test_without_a_covering_quotation_the_excerpt_is_the_verse_alone():
    r = bounds.rules_bounds(("JHN", "14", "6"), corpus(), [], 2)
    assert ids(r) == ["JHN.14.6"] and r["quotation"] is None


def test_a_covering_quotation_extends_the_excerpt_up_to_the_window():
    r = bounds.rules_bounds(("JHN", "14", "6"), corpus(), [quote("JHN.14.1", "JHN.14.10")], 2)
    assert ids(r) == ["JHN.14.4", "JHN.14.5", "JHN.14.6", "JHN.14.7", "JHN.14.8"]
    assert r["quotation"] == ["JHN.14.1", "JHN.14.10"]


def test_the_quotation_limits_the_window():
    r = bounds.rules_bounds(("JHN", "14", "6"), corpus(), [quote("JHN.14.6", "JHN.14.7")], 2)
    assert ids(r) == ["JHN.14.6", "JHN.14.7"]


def test_the_innermost_quotation_wins():
    big, small = quote("JHN.14.1", "JHN.14.10"), quote("JHN.14.5", "JHN.14.6", "Thomas")
    assert ids(bounds.rules_bounds(("JHN", "14", "6"), corpus(), [big, small], 3)) == ["JHN.14.5", "JHN.14.6"]


def test_a_window_of_zero_keeps_the_verse_alone():
    assert ids(bounds.rules_bounds(("JHN", "14", "6"), corpus(), [quote("JHN.14.1", "JHN.14.10")], 0)) == ["JHN.14.6"]


def test_the_window_crosses_a_chapter_boundary_in_corpus_order():
    r = bounds.rules_bounds(("JHN", "14", "10"), corpus(), [quote("JHN.14.8", "JHN.15.3")], 2)
    assert ids(r) == ["JHN.14.8", "JHN.14.9", "JHN.14.10", "JHN.15.1", "JHN.15.2"]


def test_the_window_stops_at_the_start_and_end_of_the_book():
    c = corpus(chapters={"14": 3})
    assert ids(bounds.rules_bounds(("JHN", "14", "1"), c, [quote("JHN.14.1", "JHN.14.3")], 5)) == \
        ["JHN.14.1", "JHN.14.2", "JHN.14.3"]


def test_a_quotation_whose_ends_are_not_in_the_corpus_is_ignored():
    r = bounds.rules_bounds(("JHN", "14", "6"), corpus(), [quote("JHN.14.1", "JHN.16.3")], 2)
    assert ids(r) == ["JHN.14.6"] and r["quotation"] is None


def test_a_verse_missing_from_the_corpus_is_an_error():
    with pytest.raises(ValueError):
        bounds.rules_bounds(("JHN", "14", "99"), corpus(), [], 2)


def test_every_bound_is_a_valid_excerpt_for_validate_py():
    c = corpus()
    r = bounds.rules_bounds(("JHN", "14", "10"), c, [quote("JHN.14.8", "JHN.15.3")], 2)
    text = " ".join(c["JHN"][i.split(".")[1]][i.split(".")[2]] for i in r["verses"])
    assert validate.check_excerpt({"text": text, "verses": r["verses"]}, c) == []


# --- merging ---

def item(first, last, ref, c=None):
    c = c or corpus()
    order = bounds.verse_order(c, "JHN")
    return {"verses": order[order.index(first): order.index(last) + 1], "candidates": [ref]}


def test_overlapping_excerpts_become_one_with_both_candidates():
    c = corpus()
    a, b = item("JHN.14.4", "JHN.14.8", ("JHN", "14", "6")), item("JHN.14.5", "JHN.14.9", ("JHN", "14", "7"))
    (m,) = bounds.merge_ranges([a, b], c)
    assert m["verses"][0] == "JHN.14.4" and m["verses"][-1] == "JHN.14.9" and len(m["verses"]) == 6
    assert m["candidates"] == [("JHN", "14", "6"), ("JHN", "14", "7")] and m["merged_from"] == 2


def test_identical_excerpts_merge_and_a_chain_merges_through_its_links():
    c = corpus()
    items = [item("JHN.14.1", "JHN.14.3", ("JHN", "14", "2")), item("JHN.14.3", "JHN.14.5", ("JHN", "14", "4")),
             item("JHN.14.5", "JHN.14.5", ("JHN", "14", "5"))]
    (m,) = bounds.merge_ranges(items, c)
    assert m["verses"] == bounds.verse_order(c, "JHN")[0:5] and m["merged_from"] == 3
    assert len(bounds.merge_ranges([items[0], dict(items[0])], c)) == 1


def test_neighbours_that_only_touch_stay_apart():
    c = corpus()
    out = bounds.merge_ranges([item("JHN.14.1", "JHN.14.3", ("JHN", "14", "2")),
                               item("JHN.14.4", "JHN.14.6", ("JHN", "14", "5"))], c)
    assert [(m["verses"][0], m["verses"][-1]) for m in out] == [("JHN.14.1", "JHN.14.3"), ("JHN.14.4", "JHN.14.6")]
    assert all(m["merged_from"] == 1 for m in out)


def test_merged_excerpts_come_out_in_canonical_order_across_books():
    c = {**corpus("MAT", {"5": 5}), **corpus()}
    mat = {"verses": [f"MAT.5.{v}" for v in (2, 3)], "candidates": [("MAT", "5", "3")]}
    jhn = item("JHN.14.6", "JHN.14.6", ("JHN", "14", "6"), c)
    out = bounds.merge_ranges([jhn, mat], c)
    assert [m["verses"][0] for m in out] == ["MAT.5.2", "JHN.14.6"]
