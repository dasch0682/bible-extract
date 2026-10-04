#!/usr/bin/env python3
"""Usage : python extract.py --topic verite [--dry-run] [--limit N] [--check-links]"""
import argparse, json, os, re, sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import yaml
from books import scope_codes, NAMES
from validate import norm, validate_entry, build_link, check_link

ROOT = Path(__file__).parent
PROMPT_VERSION = "1"

SYSTEM = """Tu analyses un verset biblique (Segond 1910) pour un recueil thematique.
Reponds UNIQUEMENT par un objet JSON, sans texte autour, avec ces cles :
- "pertinent" (bool) : le verset traite vraiment du sujet donne (pas un emploi banal du mot).
- "auteur" (str) : qui parle dans ce verset (ex. "Jésus", "Pilate", "Paul"). S'il s'agit de narration, indique l'auteur du livre (ex. "Jean (narrateur)").
- "contexte" (str) : une phrase sur la situation, d'apres les versets voisins fournis.
- "extrait" (str) : passage CONTIGU copie A L'IDENTIQUE du verset (accents, ponctuation), de {max_words} mots maximum, contenant le terme cle.
- "paraphrase" (str|null) : resume du verset entier avec tes mots, obligatoire si l'extrait ne couvre pas tout le verset.
Ne cite jamais de texte qui n'est pas dans le verset."""

def load_corpus():
    p = ROOT / "data" / "lsg1910.json"
    if not p.exists():
        sys.exit("data/lsg1910.json introuvable (voir data/README.md)")
    return json.loads(p.read_text(encoding="utf-8"))

def find_hits(corpus, codes, patterns):
    rx = [re.compile(p) for p in patterns]
    for code in codes:
        for c in sorted(corpus.get(code, {}), key=int):
            for v in sorted(corpus[code][c], key=int):
                t = norm(corpus[code][c][v])
                if any(r.search(t) for r in rx):
                    yield code, c, v

def neighbours(corpus, code, c, v, span=2):
    chap = corpus[code][c]
    vs = sorted(chap, key=int)
    i = vs.index(v)
    return [(x, chap[x]) for x in vs[max(0, i - span): i + span + 1]]

def ask(client, model, topic, ctx_lines, code, c, v, text, max_words):
    user = (f"Sujet : {topic['label']}\nVerset : {NAMES[code]} {c},{v}\nTexte : {text}\n\n"
            "Versets voisins :\n" + "\n".join(f"{x}. {t}" for x, t in ctx_lines))
    for _ in range(2):
        r = client.messages.create(model=model, max_tokens=700,
                                   system=SYSTEM.format(max_words=max_words),
                                   messages=[{"role": "user", "content": user}])
        m = re.search(r"\{.*\}", r.content[0].text, re.S)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                pass
    return None

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--topic", required=True)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--check-links", action="store_true")
    ap.add_argument("--model", default=os.getenv("MODEL", "claude-sonnet-4-6"))
    a = ap.parse_args()

    topic = yaml.safe_load((ROOT / "topics" / f"{a.topic}.yml").read_text(encoding="utf-8"))
    max_words = topic.get("max_words", 14)
    version = topic.get("version", "LSG")
    corpus = load_corpus()
    hits = list(find_hits(corpus, scope_codes(topic.get("scope", "NT")), topic["patterns"]))
    if a.limit:
        hits = hits[: a.limit]
    print(f"{len(hits)} versets candidats")
    if a.dry_run:
        for code, c, v in hits:
            print(f"{NAMES[code]} {c},{v}")
        return

    from anthropic import Anthropic
    client = Anthropic()
    cache_dir = ROOT / "cache" / a.topic
    cache_dir.mkdir(parents=True, exist_ok=True)

    def work(h):
        code, c, v = h
        ref = f"{code}.{c}.{v}"
        cf = cache_dir / f"{ref}.{PROMPT_VERSION}.json"
        if cf.exists():
            llm = json.loads(cf.read_text(encoding="utf-8"))
        else:
            llm = ask(client, a.model, topic, neighbours(corpus, code, c, v),
                      code, c, v, corpus[code][c][v], max_words)
            if llm is not None:
                cf.write_text(json.dumps(llm, ensure_ascii=False), encoding="utf-8")
        return h, llm

    with ThreadPoolExecutor(max_workers=6) as ex:
        results = list(ex.map(work, hits))

    kept, rejected, skipped = [], [], 0
    for (code, c, v), llm in results:
        ref = f"{NAMES[code]} {c},{v}"
        if llm is None:
            rejected.append((ref, "reponse LLM illisible")); continue
        if not llm.get("pertinent"):
            skipped += 1; continue
        entry, why = validate_entry(llm, corpus[code][c][v], max_words)
        if entry is None:
            rejected.append((ref, why)); continue
        entry["reference"] = ref
        entry["lien"] = build_link(version, code, c, v)
        entry["version"] = topic.get("version_label", "LSG 1910")
        if a.check_links and not check_link(entry["lien"]):
            rejected.append((ref, "lien mort")); continue
        kept.append(entry)

    out = ROOT / "out"; out.mkdir(exist_ok=True)
    (out / f"{a.topic}.json").write_text(json.dumps(kept, ensure_ascii=False, indent=2), encoding="utf-8")
    rep = [f"# Rapport : {topic['label']}", "",
           f"- candidats : {len(hits)}", f"- retenus : {len(kept)}",
           f"- jugés non pertinents : {skipped}", f"- rejetés par validation : {len(rejected)}", ""]
    rep += [f"  - {r} : {w}" for r, w in rejected]
    (out / f"{a.topic}.report.md").write_text("\n".join(rep), encoding="utf-8")
    print("\n".join(rep))

if __name__ == "__main__":
    main()
