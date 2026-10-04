"""Tests for discovery functions: patterns, Strong's, neighbours."""
import pytest
from extract import find_hits_patterns, neighbours
from strongs import find_hits_strongs
from books import scope_codes


# --- find_hits_patterns ---

CORPUS = {
    "JHN": {
        "14": {
            "6": "Je suis le chemin, la vérité, et la vie.",
            "7": "Si vous me connaissiez, vous connaîtriez aussi mon Père.",
        },
        "1": {
            "1": "Au commencement était la Parole.",
        },
    },
    "ROM": {
        "1": {
            "18": "La colère de Dieu se révèle du ciel.",
        },
    },
}

def test_patterns_finds_match():
    hits = find_hits_patterns(CORPUS, ["JHN", "ROM"], [r"v.rit."])
    assert ("JHN", "14", "6") in hits

def test_patterns_no_match():
    hits = find_hits_patterns(CORPUS, ["JHN"], [r"grâce"])
    assert len(hits) == 0

def test_patterns_scope_filters_books():
    hits = find_hits_patterns(CORPUS, ["ROM"], [r"v.rit."])
    assert ("JHN", "14", "6") not in hits

def test_patterns_multiple_patterns():
    hits = find_hits_patterns(CORPUS, ["JHN"], [r"grâce", r"v.rit."])
    assert ("JHN", "14", "6") in hits

def test_patterns_empty_patterns():
    hits = find_hits_patterns(CORPUS, ["JHN"], [])
    assert len(hits) == 0


# --- neighbours ---

def test_neighbours_middle_verse():
    ctx = neighbours(CORPUS, "JHN", "14", "7")
    verses = [v for v, _ in ctx]
    assert "6" in verses
    assert "7" in verses

def test_neighbours_first_verse_no_underflow():
    ctx = neighbours(CORPUS, "JHN", "1", "1")
    verses = [v for v, _ in ctx]
    assert "1" in verses
    assert all(int(v) >= 1 for v in verses)

def test_neighbours_span():
    corpus = {"MAT": {"5": {str(i): f"verse {i}" for i in range(1, 12)}}}
    ctx = neighbours(corpus, "MAT", "5", "6")
    verses = [v for v, _ in ctx]
    assert "4" in verses
    assert "5" in verses
    assert "6" in verses
    assert "7" in verses
    assert "8" in verses
    assert len(verses) == 5


# --- find_hits_strongs ---

@pytest.fixture
def byztxt_dir(tmp_path):
    csv_dir = tmp_path / "csv-unicode" / "strongs" / "with-parsing"
    csv_dir.mkdir(parents=True)
    # JHN 3:16 has Strong's 25 (ἀγαπάω) and 3:17 has 225 (ἀλήθεια)
    (csv_dir / "JHN.csv").write_text(
        "3,16,ηγαπησεν 25 {V-AAI-3S} ο 3588 {T-NSM}\n"
        "3,17,αληθειαν 225 {N-ASF} εχει 2192 {V-PAI-3S}\n"
        "1,1,λογος 3056 {N-NSM}\n",
        encoding="utf-8",
    )
    (csv_dir / "ROM.csv").write_text(
        "1,18,αληθειαν 225 {N-ASF}\n",
        encoding="utf-8",
    )
    return tmp_path


def test_strongs_finds_gnum(byztxt_dir):
    hits = find_hits_strongs(["G225"], ["JHN", "ROM"], byztxt_dir)
    assert ("JHN", "3", "17") in hits
    assert ("ROM", "1", "18") in hits

def test_strongs_scope_filters(byztxt_dir):
    hits = find_hits_strongs(["G225"], ["JHN"], byztxt_dir)
    assert ("ROM", "1", "18") not in hits

def test_strongs_multiple_labels(byztxt_dir):
    hits = find_hits_strongs(["G25", "G3056"], ["JHN"], byztxt_dir)
    assert ("JHN", "3", "16") in hits
    assert ("JHN", "1", "1") in hits

def test_strongs_h_number_ignored(byztxt_dir):
    # H-numbers silently skipped (OT not yet implemented)
    hits = find_hits_strongs(["H225"], ["JHN"], byztxt_dir)
    assert len(hits) == 0

def test_strongs_byztxt_stem_mapping(byztxt_dir):
    # JOH.csv → JHN via _BYZTXT_TO_USFM
    csv_dir = byztxt_dir / "csv-unicode" / "strongs" / "with-parsing"
    (csv_dir / "JOH.csv").write_text("1,1,αληθειαν 225 {N-ASF}\n", encoding="utf-8")
    from strongs import _build_nt_index
    idx = _build_nt_index(byztxt_dir)
    refs = idx.get(225, set())
    books = {r[0] for r in refs}
    assert "JHN" in books  # JOH remapped to JHN


# --- scope_codes ---

def test_scope_nt():
    codes = scope_codes("NT")
    assert "MAT" in codes
    assert "GEN" not in codes

def test_scope_ot():
    codes = scope_codes("OT")
    assert "GEN" in codes
    assert "MAT" not in codes

def test_scope_all():
    codes = scope_codes("ALL")
    assert "GEN" in codes
    assert "REV" in codes

def test_scope_list():
    codes = scope_codes(["JHN", "ROM", "FAKE"])
    assert codes == ["JHN", "ROM"]
