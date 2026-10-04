# bible-extract

Extraction thématique de versets (Segond 1910) vers JSON, vérifiée par code.

1. Ajouter `data/lsg1910.json` (voir `data/README.md`).
2. Créer `topics/<sujet>.yml` (modèle : `topics/verite.yml`).
3. Test sans API : `python extract.py --topic verite --dry-run`
4. Lancer : onglet Actions > extract-topic > Run workflow (secret `ANTHROPIC_API_KEY` requis).
5. Résultats : `out/<sujet>.json` et `out/<sujet>.report.md`.

Garde-fous (`validate.py`) : extrait = sous-chaîne exacte du verset, 14 mots max, paraphrase
obligatoire si extrait tronqué, auteur requis, compteurs calculés par le script.
