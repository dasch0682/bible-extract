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

_NT_INDEX: dict[str, dict[int, set[tuple[str, str, str]]]] = {}   # one index per byztxt folder


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
    key = str(Path(byztxt_dir).resolve())
    if key not in _NT_INDEX:
        _NT_INDEX[key] = _build_nt_index(Path(byztxt_dir))
    return _NT_INDEX[key]


def find_strongs_matches(
    strong_labels: list[str],
    scope: list[str],
    byztxt_dir: str | Path,
) -> dict[tuple[str, str, str], list[str]]:
    """{(USFM_book, chap, verse): [labels found there]} for the given Strong's numbers.

    Labels are upper-case ('G225'), listed in numeric order. Only G-numbers (NT) are supported
    for now; H-numbers require STEPBible TAHOT data.
    """
    index = load_nt_index(byztxt_dir)
    scope_set = set(scope)
    found: dict[tuple[str, str, str], set[int]] = {}
    for label in strong_labels:
        label = label.upper()
        if label.startswith("G") and label[1:].isdigit():
            for ref in index.get(int(label[1:]), set()):
                if ref[0] in scope_set:
                    found.setdefault(ref, set()).add(int(label[1:]))
        elif label.startswith("H"):
            pass  # OT H-numbers: needs STEPBible TAHOT — not yet implemented
    return {ref: [f"G{n}" for n in sorted(nums)] for ref, nums in found.items()}


def find_hits_strongs(
    strong_labels: list[str],
    scope: list[str],
    byztxt_dir: str | Path,
) -> set[tuple[str, str, str]]:
    """Return (USFM_book, chap, verse) tuples where any given Strong's number occurs."""
    return set(find_strongs_matches(strong_labels, scope, byztxt_dir))
