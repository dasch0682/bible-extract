"""Strong's concordance: G/H number → set of (USFM_book, chap_str, verse_str).

Data source: byztxt/byzantine-majority-text (Unlicense / Public Domain).
CSV format per book: chapter,verse,word1 strongsnum1 {MORPH1} word2 strongsnum2 ...
"""
from __future__ import annotations
from pathlib import Path

# byztxt CSV stem → USFM code (differences only; identical codes omitted)
_BYZTXT_TO_USFM = {
    "MAR": "MRK", "JOH": "JHN", "JAM": "JAS",
    "1JO": "1JN", "2JO": "2JN", "3JO": "3JN",
}

_NT_INDEX: dict[int, set[tuple[str, str, str]]] | None = None


def _build_nt_index(byztxt_dir: Path) -> dict[int, set[tuple[str, str, str]]]:
    csv_root = byztxt_dir / "csv-unicode" / "strongs" / "with-parsing"
    if not csv_root.exists():
        raise FileNotFoundError(f"byztxt strongs dir not found: {csv_root}")
    index: dict[int, set] = {}
    for path in sorted(csv_root.glob("*.csv")):
        usfm = _BYZTXT_TO_USFM.get(path.stem, path.stem)
        with open(path, encoding="utf-8") as f:
            for line in f:
                parts = line.strip().split(",", 2)
                if len(parts) < 3:
                    continue
                chap, verse, text_field = parts
                for token in text_field.split():
                    if token.isdigit():
                        index.setdefault(int(token), set()).add((usfm, chap, verse))
    return index


def load_nt_index(byztxt_dir: str | Path) -> dict[int, set[tuple[str, str, str]]]:
    global _NT_INDEX
    if _NT_INDEX is None:
        _NT_INDEX = _build_nt_index(Path(byztxt_dir))
    return _NT_INDEX


def find_hits_strongs(
    strong_labels: list[str],
    scope: list[str],
    byztxt_dir: str | Path,
) -> set[tuple[str, str, str]]:
    """Return (USFM_book, chap, verse) tuples where any given Strong's number occurs.

    Only G-numbers (NT) are supported for now; H-numbers require STEPBible TAHOT data.
    """
    index = load_nt_index(byztxt_dir)
    scope_set = set(scope)
    hits: set[tuple[str, str, str]] = set()
    for label in strong_labels:
        label = label.upper()
        if label.startswith("G") and label[1:].isdigit():
            for ref in index.get(int(label[1:]), set()):
                if ref[0] in scope_set:
                    hits.add(ref)
        elif label.startswith("H"):
            pass  # OT H-numbers: needs STEPBible TAHOT — not yet implemented
    return hits
