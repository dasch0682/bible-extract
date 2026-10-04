"""Versification helpers: validate and remap verse references across numbering systems.

Standard mapping source: Copenhagen Alliance (CC BY-SA 4.0).
File: data/versification_eng.json  (eng.json = English/KJV standard).

For the initial NT scope, KJV and LSG 1910 share the same verse numbering.
OT Psalm numbering (Hebrew vs. LXX) will be handled here when OT topics are added.
"""
from __future__ import annotations
import json
from pathlib import Path

_VERS: dict | None = None


def load_versification(path: str | Path) -> dict:
    global _VERS
    if _VERS is None:
        p = Path(path)
        _VERS = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    return _VERS


def verse_in_bounds(book: str, chap: str, verse: str, vers_data: dict) -> bool:
    """Return True if (book, chap, verse) is within the English versification bounds."""
    max_verses = vers_data.get("maxVerses", {})
    book_data = max_verses.get(book)
    if book_data is None:
        return True  # unknown book — pass through
    chap_idx = int(chap) - 1
    if chap_idx < 0 or chap_idx >= len(book_data):
        return False
    return int(verse) <= book_data[chap_idx]
