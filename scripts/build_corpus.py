#!/usr/bin/env python3
"""Prepare corpus files from upstream sources into data/<lang>.json.

Expected format: {USFM_code: {chapter_str: {verse_str: text}}}
  e.g.  {"JHN": {"3": {"16": "Car Dieu a tant aimé le monde..."}}}

Run:
  python scripts/build_corpus.py fr    # builds data/fr.json from tmp/lsg1910/
  python scripts/build_corpus.py en    # builds data/en.json from tmp/kjv.json

Download instructions are in data/SOURCES.md.
"""
import html, json, re, sys
from pathlib import Path

ROOT = Path(__file__).parent.parent

# USFM book codes in canonical order (66 books, same order as BibleAquifer filenames)
_BOOK_ORDER = [
    "GEN","EXO","LEV","NUM","DEU","JOS","JDG","RUT","1SA","2SA","1KI","2KI","1CH","2CH",
    "EZR","NEH","EST","JOB","PSA","PRO","ECC","SNG","ISA","JER","LAM","EZK","DAN","HOS",
    "JOL","AMO","OBA","JON","MIC","NAM","HAB","ZEP","HAG","ZEC","MAL",
    "MAT","MRK","LUK","JHN","ACT","ROM","1CO","2CO","GAL","EPH","PHP","COL","1TH","2TH",
    "1TI","2TI","TIT","PHM","HEB","JAS","1PE","2PE","1JN","2JN","3JN","JUD","REV",
]

# scrollmapper KJV uses full English book names; map to USFM
_KJV_BOOK_NAME_TO_USFM = {
    "Genesis":"GEN","Exodus":"EXO","Leviticus":"LEV","Numbers":"NUM","Deuteronomy":"DEU",
    "Joshua":"JOS","Judges":"JDG","Ruth":"RUT","1 Samuel":"1SA","2 Samuel":"2SA",
    "1 Kings":"1KI","2 Kings":"2KI","1 Chronicles":"1CH","2 Chronicles":"2CH",
    "Ezra":"EZR","Nehemiah":"NEH","Esther":"EST","Job":"JOB","Psalms":"PSA",
    "Proverbs":"PRO","Ecclesiastes":"ECC","Song of Solomon":"SNG","Isaiah":"ISA",
    "Jeremiah":"JER","Lamentations":"LAM","Ezekiel":"EZK","Daniel":"DAN",
    "Hosea":"HOS","Joel":"JOL","Amos":"AMO","Obadiah":"OBA","Jonah":"JON",
    "Micah":"MIC","Nahum":"NAM","Habakkuk":"HAB","Zephaniah":"ZEP","Haggai":"HAG",
    "Zechariah":"ZEC","Malachi":"MAL","Matthew":"MAT","Mark":"MRK","Luke":"LUK",
    "John":"JHN","Acts":"ACT","Romans":"ROM","1 Corinthians":"1CO","2 Corinthians":"2CO",
    "Galatians":"GAL","Ephesians":"EPH","Philippians":"PHP","Colossians":"COL",
    "1 Thessalonians":"1TH","2 Thessalonians":"2TH","1 Timothy":"1TI","2 Timothy":"2TI",
    "Titus":"TIT","Philemon":"PHM","Hebrews":"HEB","James":"JAS","1 Peter":"1PE",
    "2 Peter":"2PE","1 John":"1JN","2 John":"2JN","3 John":"3JN","Jude":"JUD",
    "Revelation":"REV",
}


def _strip_html(s: str) -> str:
    s = html.unescape(s)
    s = re.sub(r"<[^>]+>", "", s)
    return re.sub(r"\s+", " ", s).strip()


def build_fr(lsg_dir: Path, out_path: Path) -> None:
    """Build data/fr.json from BibleAquifer/LouisSegond1910 fra/json/ directory."""
    json_dir = lsg_dir / "fra" / "json"
    if not json_dir.exists():
        sys.exit(f"LSG1910 json dir not found: {json_dir}")

    # BibleAquifer uses numeric filenames (01..66) matching canonical book order
    files = sorted(json_dir.glob("*.content.json"))
    if len(files) != 66:
        print(f"[warn] expected 66 book files, found {len(files)}")

    corpus: dict = {}
    for book_file, usfm in zip(files, _BOOK_ORDER):
        entries = json.loads(book_file.read_text(encoding="utf-8"))
        for entry in entries:
            title = entry.get("title", "")          # e.g. "Matthieu 1.1"
            content = entry.get("content", "")
            m = re.match(r".+\s+(\d+)\.(\d+)$", title)
            if not m:
                continue
            c, v = m.group(1), m.group(2)
            # content is HTML like <p><sup>1</sup>Texte du verset.</p>
            text = _strip_html(re.sub(r"<sup>[^<]*</sup>", "", content))
            if text:
                corpus.setdefault(usfm, {}).setdefault(c, {})[v] = text

    out_path.write_text(json.dumps(corpus, ensure_ascii=False, indent=None), encoding="utf-8")
    print(f"Wrote {out_path} ({sum(len(vv) for bk in corpus.values() for vv in bk.values())} verses)")


def build_en(kjv_json: Path, out_path: Path) -> None:
    """Build data/en.json from scrollmapper KJV.json (array of {book_name,chapter,verse,text})."""
    if not kjv_json.exists():
        sys.exit(f"KJV json not found: {kjv_json}")

    raw = json.loads(kjv_json.read_text(encoding="utf-8"))
    # scrollmapper format: {"resultset": {"row": [{"field": [book_name, chap, verse, text]}...]}}
    # OR flat array of objects with keys book_name / chapter / verse / text
    # Detect format:
    corpus: dict = {}
    if isinstance(raw, dict) and "resultset" in raw:
        rows = raw["resultset"]["row"]
        for r in rows:
            f = r["field"]
            book_name, chap, verse, text = str(f[0]), str(f[1]), str(f[2]), f[3]
            usfm = _KJV_BOOK_NAME_TO_USFM.get(book_name)
            if usfm:
                corpus.setdefault(usfm, {}).setdefault(chap, {})[verse] = text
    elif isinstance(raw, list):
        for item in raw:
            book_name = item.get("book_name", item.get("b", ""))
            chap = str(item.get("chapter", item.get("c", "")))
            verse = str(item.get("verse", item.get("v", "")))
            text = item.get("text", item.get("t", ""))
            usfm = _KJV_BOOK_NAME_TO_USFM.get(book_name)
            if usfm:
                corpus.setdefault(usfm, {}).setdefault(chap, {})[verse] = text
    elif isinstance(raw, dict) and "books" in raw:
        # scrollmapper format: {books: [{name, chapters: [{chapter, verses: [{verse, text}]}]}]}
        for book in raw["books"]:
            usfm = _KJV_BOOK_NAME_TO_USFM.get(book["name"])
            if not usfm:
                continue
            for chap_obj in book["chapters"]:
                chap = str(chap_obj["chapter"])
                for v_obj in chap_obj["verses"]:
                    corpus.setdefault(usfm, {}).setdefault(chap, {})[str(v_obj["verse"])] = v_obj["text"]
    else:
        sys.exit(f"Unrecognised KJV JSON format in {kjv_json}")

    out_path.write_text(json.dumps(corpus, ensure_ascii=False, indent=None), encoding="utf-8")
    print(f"Wrote {out_path} ({sum(len(vv) for bk in corpus.values() for vv in bk.values())} verses)")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    lang = sys.argv[1].lower()
    data_dir = ROOT / "data"
    data_dir.mkdir(exist_ok=True)
    if lang == "fr":
        build_fr(ROOT / "tmp" / "lsg1910", data_dir / "fr.json")
    elif lang == "en":
        build_en(ROOT / "tmp" / "kjv.json", data_dir / "en.json")
    else:
        sys.exit(f"Unknown language '{lang}' — supported: fr, en")
