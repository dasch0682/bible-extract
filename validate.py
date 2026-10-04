"""Garde-fous : rien n'entre dans le JSON final sans passer ici."""
import re, unicodedata
import requests

LINK = "https://lire.la-bible.net/bible/{ver}/{code}.{c}.{v}-{code}.{c}.{v}"

def norm(s):
    s = s.replace("\u2019", "'").replace("\u00a0", " ")
    s = unicodedata.normalize("NFD", s)
    s = "".join(ch for ch in s if unicodedata.category(ch) != "Mn")
    return re.sub(r"\s+", " ", s).strip().lower()

def _ws(s):
    return re.sub(r"\s+", " ", s.replace("\u00a0", " ")).strip()

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
    if ext not in _ws(verse_text):
        return None, "extrait absent du verset (non exact)"
    n = len(ext.split())
    if n > max_words:
        return None, f"extrait trop long ({n} mots)"
    full = norm(re.sub(r"[^\w\s]", "", ext)) == norm(re.sub(r"[^\w\s]", "", verse_text))
    para = (llm.get("paraphrase") or "").strip() or None
    if full:
        para = None
    elif para is None:
        return None, "paraphrase manquante (extrait tronque)"
    if not (llm.get("auteur") or "").strip():
        return None, "auteur manquant"
    return {
        "citation": ext,
        "longueurExtrait": len(ext),
        "nbMotExtrait": n,
        "paraphrase": para,
        "auteur": llm["auteur"].strip(),
        "contexte": (llm.get("contexte") or "").strip(),
    }, None
