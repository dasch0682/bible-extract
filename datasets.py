"""Readers for the external datasets (dates, places, speakers, versification, anchors).

The datasets are fetched into tmp/ by scripts/fetch_sources.py. Every reader
returns an index keyed by an 8-digit verse key BBCCCVVV (book number in
books.BOOKS, chapter, verse): John 14:6 -> "43014006".

Only identifiers, names, years and scores are read. Dictionary text, geometry
and OpenStreetMap-derived data are never copied.
"""
from __future__ import annotations

import csv
import datetime as dt
import json
import re
from pathlib import Path

import yaml

from books import BOOKS

TMP = Path(__file__).parent / "tmp"
_KEY = re.compile(r"^\d{8}$")
_USFM_REF = re.compile(r"^([1-3A-Z][A-Z0-9]{2}) (\d+):(\d+)$")
_THEO_DATE = re.compile(r"^(-?)(\d{1,4})(?:-(\d{2})-(\d{2}))?$")
_QID = re.compile(r"^Q\d+$")


# --- verse keys ---

def make_key(book: str, chapter, verse) -> str:
    return f"{BOOKS.index(book) + 1:02d}{int(chapter):03d}{int(verse):03d}"


def verse_key(vid: str) -> str:
    """'JHN.14.6' -> '43014006' (raises ValueError when malformed or unknown book)."""
    parts = vid.split(".") if isinstance(vid, str) else []
    if len(parts) != 3 or parts[0] not in BOOKS or not parts[1].isdigit() or not parts[2].isdigit():
        raise ValueError(f"bad verse id: {vid!r}")
    return make_key(*parts)


def key_to_id(key: str) -> str:
    """'43014006' -> 'JHN.14.6'."""
    return f"{BOOKS[int(key[:2]) - 1]}.{int(key[2:5])}.{int(key[5:])}"


def parse_usfm_ref(ref: str):
    """'JHN 14:6' -> '43014006', or None for other books or formats."""
    m = _USFM_REF.match((ref or "").strip())
    if not m or m.group(1) not in BOOKS:
        return None
    return make_key(m.group(1), m.group(2), m.group(3))


# --- Theographic (dates by event, places) ---

def parse_theographic_date(raw):
    """'-4003' or '0030-05-02' -> {'year': int, 'precision': 'year'|'day', 'raw': str}.

    The year is in ISO 8601 astronomical numbering, as the dataset documents it
    (docs/api-documentation.md): 0 is 1 BCE, -1 is 2 BCE, -4003 is 4004 BCE.

    Only the year is kept downstream: days come from a calendar computation, not a dataset.
    """
    m = _THEO_DATE.match(str(raw or "").strip())
    if not m:
        return None
    year = int(m.group(2)) * (-1 if m.group(1) else 1)
    return {"year": year, "precision": "day" if m.group(3) else "year", "raw": str(raw).strip()}


def load_theographic(base=TMP / "theographic") -> dict:
    """{'events': {key: [event]}, 'places': {key: [place]}} from json/*.json."""
    j = Path(base) / "json"
    load = lambda name: json.loads((j / name).read_text(encoding="utf-8"))  # noqa: E731
    rec_to_key = {v["id"]: v["fields"]["verseID"] for v in load("verses.json")
                  if _KEY.match(str(v["fields"].get("verseID", "")))}
    place_records = load("places.json")
    place_name = {p["id"]: p["fields"].get("displayTitle") or p["fields"].get("kjvName") for p in place_records}
    events, places = {}, {}
    for e in load("events.json"):
        f = e["fields"]
        date = parse_theographic_date(f.get("startDate"))
        if date is None:
            continue
        item = {"id": str(f.get("eventID") or e["id"]), "title": f.get("title"), "duration": f.get("duration"), **date,
                "places": [place_name[r] for r in f.get("locations", []) if place_name.get(r)]}
        for rid in f.get("verses", []):
            if rid in rec_to_key:
                events.setdefault(rec_to_key[rid], []).append(item)
    for p in place_records:
        f = p["fields"]
        item = {"name": place_name[p["id"]], "id": f.get("placeID") or p["id"]}
        for rid in f.get("verses", []):
            if rid in rec_to_key:
                places.setdefault(rec_to_key[rid], []).append(item)
    return {"events": events, "places": places}


# --- OpenBible.info geocoding (places, identification scores) ---

def load_openbible(path=TMP / "openbible-geocoding" / "data" / "ancient.jsonl") -> dict:
    """{key: [place]} with name, Wikidata id and the published scores. No geometry.

    `score` is the best `vote_average`. `total`, `count` and `special` describe the identification with the
    highest `vote_total` (README: a total of 500 or higher represents high confidence). `special` is
    multiple_locations, nonspecific_place or not_a_place when the place has no single location.
    """
    index = {}
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        idents = r.get("identifications", [])
        scored = [i for i in idents if isinstance(i.get("score"), dict)]
        scores = [i["score"]["vote_average"] for i in scored if "vote_average" in i["score"]]
        totals = [i for i in scored if "vote_total" in i["score"]]
        best = max(totals, key=lambda i: i["score"]["vote_total"], default=None)
        wikidata = next((v["id"] for v in (r.get("linked_data") or {}).values()
                         if isinstance(v, dict) and _QID.match(str(v.get("id", "")))), None)
        item = {"id": r["id"], "name": r.get("friendly_id"), "wikidata": wikidata,
                "score": max(scores) if scores else None, "identifications": len(idents),
                "total": best["score"]["vote_total"] if best else None,
                "count": best["score"].get("vote_count") if best else None,
                "special": best.get("special") if best else None}
        for v in r.get("verses", []):
            if _KEY.match(str(v.get("sort", ""))):
                index.setdefault(v["sort"], []).append(item)
    return index


# --- speaker-quotations (Clear Bible) ---

def load_speakers(path=TMP / "speaker-quotations" / "tsv" / "Clear-Aligned-Projections.tsv") -> list:
    """Quotation ranges: [{'start': key, 'end': key, 'speaker': str, 'type': str}] sorted by start."""
    with open(path, encoding="utf-8", newline="") as fh:
        rows = list(csv.reader(fh, delimiter="\t", quoting=csv.QUOTE_NONE))
    header = rows[0]
    col = {name: header.index(name) for name in ("START VS", "END VS", "SPEAKER (FCBH)", "QUOTE TYPE")}
    out = []
    for r in rows[1:]:
        if len(r) <= max(col.values()):
            continue
        start, end = parse_usfm_ref(r[col["START VS"]]), parse_usfm_ref(r[col["END VS"]])
        if start and end and r[col["SPEAKER (FCBH)"]].strip():
            out.append({"start": start, "end": end, "speaker": r[col["SPEAKER (FCBH)"]].strip(),
                        "type": r[col["QUOTE TYPE"]].strip()})
    return sorted(out, key=lambda x: (x["start"], x["end"]))


def speakers_at(ranges: list, key: str) -> list:
    """Distinct speakers of the quotations whose range covers the verse."""
    seen = []
    for r in ranges:
        if r["start"] <= key <= r["end"] and r["speaker"] not in seen:
            seen.append(r["speaker"])
    return seen


# --- ACAI (people and places per verse) ---

def load_acai(base=TMP / "acai") -> dict:
    """{'people': {key: [entity]}, 'places': {key: [entity]}}: id and English label only."""
    out = {}
    for kind in ("people", "places"):
        index = {}
        for f in sorted((Path(base) / kind / "json").glob("*.json")):
            d = json.loads(f.read_text(encoding="utf-8"))
            label = ((d.get("localizations") or {}).get("eng") or {}).get("preferred_label") or d.get("id")
            item = {"id": d.get("id"), "label": label}
            for ref in d.get("references", []):
                if _KEY.match(str(ref)):
                    index.setdefault(str(ref), []).append(item)
        out[kind] = index
    return out


# --- TVTMS (versification differences, STEPBible) ---

def load_tvtms(path) -> list:
    """Rows of the 'Expanded' section: [{'traditions': [...], 'source_ref', 'standard_ref', 'action'}].

    Each row says how a verse of a tradition (SourceType, e.g. 'Hebrew' or
    'Eng-KJV+Hebrew') is numbered in the standard (KJV) numbering. References are
    kept as written in the file ('Psa.3:1' -> 'Psa.3:0'). Comment and test lines
    ('#', "'") are skipped.
    """
    lines = Path(path).read_text(encoding="utf-8-sig").splitlines()
    start = next((i for i, line in enumerate(lines) if line.startswith("#DataStart(Expanded)")), None)
    if start is None:
        raise ValueError("TVTMS: '#DataStart(Expanded)' not found")
    header, rows = None, []
    for line in lines[start + 1:]:
        if line.startswith("#DataEnd(Expanded)"):
            break
        cells = [c.strip() for c in line.split("\t")]
        if not any(cells) or cells[0].startswith(("#", "'", "$")):
            continue
        if header is None:
            header = [c.lower() for c in cells]
            need = ("sourcetype", "sourceref", "standardref", "action")
            if any(n not in header for n in need):
                raise ValueError("TVTMS: unexpected columns in the Expanded section")
            col = {n: header.index(n) for n in need}
            continue
        if len(cells) <= max(col.values()) or not cells[col["sourceref"]]:
            continue
        rows.append({"traditions": cells[col["sourcetype"]].split("+"),
                     "source_ref": cells[col["sourceref"]],
                     "standard_ref": cells[col["standardref"]],
                     "action": cells[col["action"]]})
    return rows


def tvtms_standard_refs(rows: list, tradition: str, source_ref: str) -> list:
    """Standard (KJV) references a verse of the tradition maps to; [] when the file has no rule."""
    return [r["standard_ref"] for r in rows if tradition in r["traditions"] and r["source_ref"] == source_ref]


# --- anchors (data/anchors.yml) ---

ANCHOR_KINDS = {"ancient_author", "inscription", "archaeology", "calendar"}


def check_anchors(data) -> list:
    """Problems in an anchors file (empty list = valid). Every anchor cites its primary text."""
    errs = []
    anchors = (data or {}).get("anchors") if isinstance(data, dict) else None
    if not isinstance(anchors, list):
        return ["anchors: must be a list"]
    seen = set()
    for i, a in enumerate(anchors):
        p = f"anchors[{i}]"
        if not isinstance(a, dict):
            errs.append(f"{p}: malformed")
            continue
        for key in ("id", "claim"):
            if not isinstance(a.get(key), str) or not a[key].strip():
                errs.append(f"{p}.{key}: missing")
        if a.get("id") in seen:
            errs.append(f"{p}.id: duplicate")
        seen.add(a.get("id"))
        if a.get("kind") not in ANCHOR_KINDS:
            errs.append(f"{p}.kind: unknown")
        ref = a.get("reference")
        if not isinstance(ref, dict) or not all(isinstance(ref.get(k), str) and ref[k].strip()
                                                for k in ("work", "location", "edition", "url")):
            errs.append(f"{p}.reference: needs work, location (book and paragraph), edition and url")
        q = a.get("check_quote")
        if not isinstance(q, str) or not q.strip() or len(q.split()) > 40:
            errs.append(f"{p}.check_quote: required, at most 40 words")
        try:
            dt.date.fromisoformat(str(a.get("verified_on")))
        except ValueError:
            errs.append(f"{p}.verified_on: must be YYYY-MM-DD")
        dr = a.get("date_range")
        if dr is None:
            if not a.get("reason"):
                errs.append(f"{p}: date_range null needs a reason")
        elif not (isinstance(dr, dict) and all(isinstance(dr.get(k), int) for k in ("from", "to"))
                  and dr["from"] <= dr["to"] and dr.get("era") in ("CE", "BCE")
                  and isinstance(dr.get("basis"), str) and dr["basis"].strip()):
            errs.append(f"{p}.date_range: needs from <= to (years), era CE or BCE, and a basis")
    return errs


def load_anchors(path=Path(__file__).parent / "data" / "anchors.yml") -> list:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    errs = check_anchors(data)
    if errs:
        raise ValueError("; ".join(errs))
    return data["anchors"]
