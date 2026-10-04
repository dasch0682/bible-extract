"""Tests for validate.py guardrails."""
import pytest
from validate import norm, validate_entry, build_link

VERSE = "Jésus lui dit: Je suis le chemin, la vérité, et la vie."


# --- norm ---

def test_norm_strips_accents():
    assert norm("vérité") == "verite"

def test_norm_smart_quote():
    assert norm("l\u2019homme") == "l'homme"

def test_norm_nbsp():
    assert norm("a\u00a0b") == "a b"

def test_norm_lowercase():
    assert norm("Jésus") == "jesus"

def test_norm_collapses_spaces():
    assert norm("a  b   c") == "a b c"


# --- validate_entry: happy paths ---

def test_partial_extract_with_paraphrase():
    llm = {
        "extrait": "Je suis le chemin, la vérité, et la vie",
        "paraphrase": "Jésus se présente comme la seule voie vers Dieu.",
        "auteur": "Jésus",
        "contexte": "Réponse à la question de Thomas.",
    }
    entry, err = validate_entry(llm, VERSE, 14)
    assert err is None
    assert entry["citation"] == "Je suis le chemin, la vérité, et la vie"
    assert entry["paraphrase"] == "Jésus se présente comme la seule voie vers Dieu."
    assert entry["auteur"] == "Jésus"
    assert entry["nbMotExtrait"] == 9
    assert entry["longueurExtrait"] == len("Je suis le chemin, la vérité, et la vie")

def test_full_verse_extract_drops_paraphrase():
    verse = "La vérité vous affranchira."
    llm = {
        "extrait": "La vérité vous affranchira.",
        "paraphrase": "Paraphrase non nécessaire.",
        "auteur": "Jésus",
        "contexte": "...",
    }
    entry, err = validate_entry(llm, verse, 14)
    assert err is None
    assert entry["paraphrase"] is None

def test_whitespace_normalised_in_extract():
    llm = {
        "extrait": "Je suis le chemin,  la vérité",
        "paraphrase": "...",
        "auteur": "Jésus",
        "contexte": "",
    }
    # _ws() collapses double spaces before the substring check → accepted
    entry, err = validate_entry(llm, VERSE, 14)
    assert err is None
    assert entry["citation"] == "Je suis le chemin, la vérité"


# --- validate_entry: rejections ---

def test_reject_empty_extract():
    llm = {"extrait": "", "paraphrase": "x", "auteur": "Jean", "contexte": ""}
    _, err = validate_entry(llm, VERSE, 14)
    assert err == "extrait vide"

def test_reject_none_extract():
    llm = {"extrait": None, "paraphrase": "x", "auteur": "Jean", "contexte": ""}
    _, err = validate_entry(llm, VERSE, 14)
    assert err == "extrait vide"

def test_reject_extract_not_in_verse():
    llm = {
        "extrait": "Je suis la résurrection et la vie",
        "paraphrase": "...",
        "auteur": "Jésus",
        "contexte": "",
    }
    _, err = validate_entry(llm, VERSE, 14)
    assert err == "extrait absent du verset (non exact)"

def test_reject_extract_too_long():
    verse = "a b c d e f g h i j k l m n o p"
    extract = "a b c d e f g h i j k l m n o"  # 15 words
    llm = {"extrait": extract, "paraphrase": "...", "auteur": "X", "contexte": ""}
    _, err = validate_entry(llm, verse, 14)
    assert "trop long" in err

def test_reject_missing_paraphrase_on_partial():
    llm = {
        "extrait": "Je suis le chemin",
        "paraphrase": None,
        "auteur": "Jésus",
        "contexte": "",
    }
    _, err = validate_entry(llm, VERSE, 14)
    assert err == "paraphrase manquante (extrait tronque)"

def test_reject_missing_auteur():
    llm = {
        "extrait": "Je suis le chemin, la vérité, et la vie",
        "paraphrase": "...",
        "auteur": "",
        "contexte": "",
    }
    _, err = validate_entry(llm, VERSE, 14)
    assert err == "auteur manquant"


# --- counters are computed, never trusted from LLM ---

def test_counters_computed_from_extract():
    ext = "la vérité"
    llm = {"extrait": ext, "paraphrase": "...", "auteur": "Jean", "contexte": ""}
    entry, _ = validate_entry(llm, VERSE, 14)
    assert entry["nbMotExtrait"] == 2
    assert entry["longueurExtrait"] == len("la vérité")


# --- build_link ---

def test_build_link():
    url = build_link("lsg", "JHN", "14", "6")
    assert "JHN" in url
    assert "14" in url
    assert "6" in url
