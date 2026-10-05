"""Garde-fous : rien n'entre dans le JSON final sans passer ici."""
import re, unicodedata
import requests

LINK = "https://lire.la-bible.net/bible/{ver}/{code}.{c}.{v}-{code}.{c}.{v}"

# Length-preserving map: typographic variants → ASCII equivalents.
# Length-preserving means positions in the softened string map 1-to-1 to the original,
# so we can recover the verbatim corpus substring after a soft match.
_SOFT_MAP = str.maketrans(
    "\u2018\u2019\u02BC`\u201C\u201D\u00AB\u00BB\u2013\u2014\u2212\u00A0",
    "''''\"\"\"\"--- ",
)

def _soft(s: str) -> str:
    """Lowercase + normalise typographic variants, length-preserving."""
    return s.lower().translate(_SOFT_MAP)

def norm(s):
    s = s.replace("\u2019", "'").replace("\u00a0", " ")
    s = unicodedata.normalize("NFD", s)
    s = "".join(ch for ch in s if unicodedata.category(ch) != "Mn")
    return re.sub(r"\s+", " ", s).strip().lower()

def _ws(s):
    return re.sub(r"\s+", " ", s.replace("\u00a0", " ")).strip()

def _find_verbatim(ext: str, verse_ws: str) -> str | None:
    """Find ext in verse_ws with progressively looser matching.

    Level 1 — soft: typographic variants (length-preserving, positions transfer 1-to-1).
    Level 2 — space-insensitive: handles corpus artifacts where spaces are missing
               (e.g. "ilne" instead of "il ne"). Positions recovered by non-space char count.

    Always returns the verbatim corpus substring on success, or None.
    """
    soft_verse = _soft(verse_ws)
    soft_ext = _soft(ext)

    # Level 1: soft (length-preserving)
    pos = soft_verse.find(soft_ext)
    if pos != -1:
        return verse_ws[pos: pos + len(ext)]

    # Level 2: space-insensitive
    ns_verse = re.sub(r"\s", "", soft_verse)
    ns_ext = re.sub(r"\s", "", soft_ext)
    if not ns_ext:
        return None
    pos_ns = ns_verse.find(ns_ext)
    if pos_ns == -1:
        return None
    # Map no-space position back to original by counting non-space chars
    count = 0
    start = None
    for i, ch in enumerate(soft_verse):
        if ch != " ":
            if count == pos_ns:
                start = i
                break
            count += 1
    if start is None:
        return None
    count = 0
    end = None
    for i in range(start, len(soft_verse)):
        if soft_verse[i] != " ":
            count += 1
            if count == len(ns_ext):
                end = i + 1
                break
    if end is None:
        return None
    return verse_ws[start:end]

def build_link(version, code, c, v):
    return LINK.format(ver=version, code=code, c=c, v=v)

def check_link(url, timeout=10):
    try:
        r = requests.head(url, allow_redirects=True, timeout=timeout)
        return r.status_code < 400
    except requests.RequestException:
        return False

def validate_entry(llm, verse_text, max_words):
    """Retourne (entree_partielle | None, raison_rejet | None)."""
    ext = _ws(llm.get("extrait") or "")
    if not ext:
        return None, "extrait vide"
    verse_ws = _ws(verse_text)
    # Strict match first; fall back to soft (typographic-variant-tolerant) match.
    if ext in verse_ws:
        verbatim_ext = ext
    else:
        verbatim_ext = _find_verbatim(ext, verse_ws)
        if verbatim_ext is None:
            return None, "extrait absent du verset (non exact)"
    n = len(verbatim_ext.split())
    para = (llm.get("paraphrase") or "").strip() or None
    if not (llm.get("auteur") or "").strip():
        return None, "auteur manquant"
    if n > max_words:
        # Extract too long: fall back to full verse as citation; paraphrase is mandatory.
        if para is None:
            return None, "extrait trop long et paraphrase manquante"
        return {
            "citation": verse_ws,
            "longueurExtrait": len(verse_ws),
            "nbMotExtrait": len(verse_ws.split()),
            "paraphrase": para,
            "auteur": llm["auteur"].strip(),
            "contexte": (llm.get("contexte") or "").strip(),
        }, None
    full = norm(re.sub(r"[^\w\s]", "", verbatim_ext)) == norm(re.sub(r"[^\w\s]", "", verse_ws))
    if full:
        para = None
    elif para is None:
        return None, "paraphrase manquante (extrait tronque)"
    return {
        "citation": verbatim_ext,
        "longueurExtrait": len(verbatim_ext),
        "nbMotExtrait": n,
        "paraphrase": para,
        "auteur": llm["auteur"].strip(),
        "contexte": (llm.get("contexte") or "").strip(),
    }, None
