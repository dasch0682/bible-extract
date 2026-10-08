"""Tests for localize.localize_multi: one call for multiple uncached languages."""
import json
from pathlib import Path

import localize

LANGS = {
    "fr": {"prompt_lang": "French", "translation": "Louis Segond 1910"},
    "en": {"prompt_lang": "English", "translation": "King James Version"},
}
CTX = {
    "fr": ["JHN.14.6: Jésus lui dit: Je suis le chemin"],
    "en": ["JHN.14.6: Jesus saith unto him, I am the way"],
}
TEXT = "John the Baptist"
KIND = "speaker-name"
VER = "speaker-name-1"
MODEL = "m/speaker"


def _write_cache(tmp_path, lang, val):
    cf = localize._cache_path(tmp_path, KIND, TEXT, lang, VER, MODEL, "")
    cf.parent.mkdir(parents=True, exist_ok=True)
    cf.write_text(json.dumps({"label": TEXT, "text": val, "model": MODEL, "prompt_version": VER}))


# --- core behaviours ---

def test_all_cached_no_call(tmp_path):
    _write_cache(tmp_path, "fr", "Jean-Baptiste")
    _write_cache(tmp_path, "en", "John the Baptist")
    calls = []
    result = localize.localize_multi(KIND, TEXT, "name", LANGS, CTX,
                                     lambda s, u: calls.append(1) or None, MODEL, tmp_path, VER)
    assert calls == []
    assert result == {"fr": "Jean-Baptiste", "en": "John the Baptist"}


def test_all_missing_two_langs_one_call(tmp_path):
    calls = []

    def model(s, u):
        calls.append(s)
        return json.dumps({"fr": "Jean-Baptiste", "en": "John the Baptist"})

    result = localize.localize_multi(KIND, TEXT, "name", LANGS, CTX, model, MODEL, tmp_path, VER)
    assert len(calls) == 1
    assert "multiple languages" in calls[0]
    assert result == {"fr": "Jean-Baptiste", "en": "John the Baptist"}

    # Second call: both now cached, zero further calls
    calls.clear()
    result2 = localize.localize_multi(KIND, TEXT, "name", LANGS, CTX, model, MODEL, tmp_path, VER)
    assert calls == []
    assert result2 == {"fr": "Jean-Baptiste", "en": "John the Baptist"}


def test_one_missing_uses_single_lang_prompt(tmp_path):
    _write_cache(tmp_path, "fr", "Jean-Baptiste")
    calls = []

    def model(s, u):
        calls.append(s)
        return "John the Baptist"

    result = localize.localize_multi(KIND, TEXT, "name", LANGS, CTX, model, MODEL, tmp_path, VER)
    assert len(calls) == 1
    assert "multiple languages" not in calls[0]    # single-lang prompt
    assert "English" in calls[0]
    assert result == {"fr": "Jean-Baptiste", "en": "John the Baptist"}


def test_invalid_json_returns_none_no_cache(tmp_path):
    result = localize.localize_multi(KIND, TEXT, "name", LANGS, CTX,
                                     lambda s, u: "not json at all", MODEL, tmp_path, VER)
    assert result == {"fr": None, "en": None}
    # Nothing written: a retry will call the model again
    for lang in ("fr", "en"):
        assert not localize._cache_path(tmp_path, KIND, TEXT, lang, VER, MODEL, "").exists()


def test_partial_json_caches_present_lang_only(tmp_path):
    def model(s, u):
        return json.dumps({"fr": "Jean-Baptiste"})   # "en" is absent

    result = localize.localize_multi(KIND, TEXT, "name", LANGS, CTX, model, MODEL, tmp_path, VER)
    assert result["fr"] == "Jean-Baptiste"
    assert result["en"] is None
    assert localize._cache_path(tmp_path, KIND, TEXT, "fr", VER, MODEL, "").exists()
    assert not localize._cache_path(tmp_path, KIND, TEXT, "en", VER, MODEL, "").exists()


def test_single_lang_cache_written_by_localize_is_found_by_localize_multi(tmp_path):
    """Cache files from localize() and localize_multi() are interchangeable."""
    localize.localize(KIND, TEXT, "name", "fr", LANGS["fr"], CTX["fr"],
                      lambda s, u: "Jean-Baptiste", MODEL, tmp_path, VER)
    calls = []

    def model(s, u):
        calls.append(s)
        return "John the Baptist"   # single-lang path: plain text, not JSON

    result = localize.localize_multi(KIND, TEXT, "name", LANGS, CTX, model, MODEL, tmp_path, VER)
    # fr is cached; only en is missing → single-lang call (not "multiple languages")
    assert len(calls) == 1 and "multiple languages" not in calls[0]
    assert "English" in calls[0]
    assert result == {"fr": "Jean-Baptiste", "en": "John the Baptist"}
