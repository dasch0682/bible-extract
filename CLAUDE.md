# bible-extract: project rules

Thematic verse extraction (e.g. "truth") from public-domain Bibles into JSON,
one file per language. Run from mobile via GitHub Actions.

## Non-negotiable rules
- Biblical text comes ONLY from data/<lang>.json, never from LLM memory.
- An extract is an exact substring of the verse in that language's corpus,
  14 words maximum, checked per language.
- Counters (longueurExtrait, nbMotExtrait) are computed by code, never by the LLM.
- Do not modify the guardrails in validate.py without explicit approval.
- Public-domain texts only. Never add copyrighted translations
  (NBS, ISV, NIV...) to the repo or to prompts as source text.

## Finding references (default: Strong's numbers)
- Default discovery uses Strong's numbers (Greek/Hebrew lemmas), listed per topic
  in topics/<topic>.yml (e.g. strongs: [G225, G227, G228, G230]).
- Pivot: Strong's-tagged King James Version gives the verse references;
  they are mapped to every other language by verse reference
  (with a versification map for numbering differences, notably Psalms).
- Word-level `patterns` in the topic file are an optional cross-check.
  Any verse found by one method but not the other is listed in
  out/<topic>.report.md, never silently dropped.
- `exclude_phrases` (optional list of regexes in a topic YML) are stripped from
  the normalised text before pattern matching. A verse that matched only because
  of an excluded formula is counted in the report under "Excluded by phrase filter".
  Strong's discovery is never affected by `exclude_phrases`.
- `extra_instructions` (optional string in a topic YML) is appended to the LLM
  system prompt for that topic only, to convey topic-specific relevance rules.
- Record each data source and its license in data/SOURCES.md.
  Verify the license before use; never assume it.

## Languages
- Initial languages: fr (Louis Segond 1910), en (King James Version).
- One output file per language: out/<topic>.<lang>.json, same references,
  same order in every file.
- languages.yml defines per language: code, translation name, version label,
  link template, corpus path. Adding a language = new corpus + one entry
  there, no code change.
- Fields auteur, contexte, paraphrase are written by the LLM in the target
  language, from that language's verse text. The extract is always verbatim
  from that language's corpus.

## Output schema (per entry)
citation, longueurExtrait, nbMotExtrait, paraphrase (null if the extract
is the whole verse), auteur (who speaks in the text), contexte, reference,
lien, version.

## Conventions
- The LLM is used only for: relevance judgement, speaker, context, choice
  of extract, paraphrase. Cache results per verse + language + prompt version.
- Run pytest before every commit. Tests cover validate.py.
- API key only via environment variable or GitHub secret, never in the repo.
- Code, comments and docs in English. Talk with the user in the language
  they write in (French or English).
