# bible-extract

Extraction thématique de versets (Segond 1910) vers JSON, vérifiée par code.
Le cahier des charges fait foi ; `CLAUDE.md` en résume les règles.

1. Ajouter `data/lsg1910.json` (voir `data/README.md`).
2. Créer `topics/<sujet>.yml` (modèle : `topics/verite.yml`).
3. Test sans API : `python extract.py --topic verite --dry-run` (découverte et bornes d'extrait, aucun appel au modèle).
   Les jeux de données se récupèrent avec `python scripts/fetch_sources.py --fetch`.
   Mode de découverte : `--mode rules` (le code décide, défaut) ou `--mode model` (le modèle juge la pertinence).
4. Contrôle des prix : `python check_prices.py` (sans clé d'API). Il compare `models.yml` aux prix publiés
   par OpenRouter et s'arrête si un prix a augmenté, si un modèle a disparu ou si les prix sont illisibles.
5. Lancer : onglet Actions > extract-topic > Run workflow (secret `OPENROUTER_API_KEY` requis).
   Le contrôle des prix est la première étape du workflow et de `extract.py`.
6. Résultats : `out/<sujet>.<langue>.json` et `out/<sujet>.report.md`.

Tous les modèles se choisissent dans `models.yml` (voir son commentaire d'en-tête), nulle part ailleurs.

Garde-fous (`validate.py`, schéma 2) : extrait = concaténation exacte de versets entiers contigus du même
livre (pas de limite de mots), paraphrase jamais plus longue que l'extrait, sources citées présentes avec
leur licence, `null` toujours accompagné d'une raison, niveaux de confiance valides, contrôle croisé entre
langues.
