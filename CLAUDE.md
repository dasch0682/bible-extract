# bible-extract: project rules

Thematic verse extraction (e.g. "truth") from public-domain Bibles into JSON,
one file per language. Run from mobile via GitHub Actions.

The specification ("Cahier des charges Bible extract") is the source of truth.
This file summarises its rules for Claude Code; if they differ, the
specification wins.

## Non-negotiable rules
- Biblical text and every piece of information come from sources the code
  retrieved, never from LLM memory. Biblical text comes ONLY from
  data/<lang>.json.
- An extract is the exact text of one or more whole, contiguous verses of the
  same book, copied from that language's corpus. There is no word limit
  (the 14-word rule was dropped on 2026-10-06). An extract never cuts a verse.
  The LLM proposes the bounds, the code checks them.
- Every piece of information cites at least one source, and the code checks
  that each cited source exists.
- An LLM writes and judges, it is never a source.
- A field without a source is null, with a reason (no_source, not_identified,
  disputed_no_consensus).
- Every uncertain value carries a confidence level. Confidence levels are
  computed by the code, never by an LLM.
- Counters and measurements are computed by the code, never by the LLM.
- Do not modify validate.py without explicit approval.
- Public-domain texts only. Never add copyrighted translations
  (NBS, ISV, NIV...) to the repo or to prompts as source text.
- Verify the license of every dataset before use and record it in
  data/SOURCES.md. Never assume a license.

## Finding references (default: Strong's numbers)
- Default discovery uses Strong's numbers (Greek/Hebrew lemmas), listed per topic
  in topics/<topic>.yml (e.g. strongs: [G225, G227, G228, G230]).
- Strong's: numbers only. Never copy the dictionary definitions (GPL).
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
- `extra_instructions_<lang>` (e.g. `extra_instructions_fr`, `extra_instructions_en`) are
  appended to the LLM system prompt for that language only. Always provide one per active
  language when instructions reference language-specific formulas.
- Discovery has two modes: `rules` (the code decides, the LLM only writes) and
  `model` (the LLM judges relevance and cites the verses that justify it).
  Mode, model, prompt version and every step are recorded in the entry's
  `discovery` field.

## Paraphrase
- Keeps the original genre (discourse, narrative, letter, prayer, parable),
  is written in the present tense, and is never longer than the extract
  (word count compared by the code). It adds no information absent from the extract.
- Three candidates (`close`, `condensed`, `free`) are generated in ONE call.
  The code runs its checks (not longer than the extract, target language,
  non-empty), then ONE verification call by a model from a different family
  than the generator, candidates shuffled and unlabelled. The code arbitrates.
- If no candidate passes: paraphrase is null with reason `no_faithful_version`,
  and the entry goes to review.
- The full history (candidates, checks, scores, arbitration) is kept in the entry,
  with `prompt_version`.

## Context, dates and speaker
- Context has `literary`, `temporal` and `places` parts, each sourced and
  given a confidence level.
- Dates: one entry per source, never an average or a merge. Keep only the year
  of a dataset date and turn it into a range; the margin lives in a rules file,
  not in code. Confidence levels (certain, probable, approximate, disputed) are
  computed by the code from the range width and source agreement.
- For events where the day matters (the Passion, Pentecost), `temporal` lists
  day-level candidates with method, explicit assumptions and sources. Never
  present one as a fact. The code recomputes the day at every batch.
- Speaker: `role` is speaker or narrator, confidence is high, medium or low,
  and an unidentified speaker is null with reason `not_identified`.
  Ambiguous cases must go through review.

## Models and costs
- Everything about models lives in models.yml, nowhere else. The code contains
  no hard-coded model identifier.
- Each model carries reference prices (price_ref, price_ref_date), changed only
  by a deliberate edit of the file.
- A pre-run check compares models.yml with the prices OpenRouter publishes.
  The batch stops before any call if a price rose, a model is gone, or prices
  cannot be read. There is no option to bypass it silently.

## Languages
- Initial languages: fr (Louis Segond 1910), en (King James Version).
- One output file per language: out/<topic>.<lang>.json, same references,
  same order in every file.
- languages.yml defines per language: code, translation name, version label,
  link template, corpus path. Adding a language = new corpus + one entry
  there, no code change.
- Each topic YAML must have `label_<lang>` for every active language (e.g. `label_fr`,
  `label_en`). The generic `label` field is the canonical identifier used in report
  titles and filenames. A warning is printed at runtime if a language-specific label
  is missing.
- The JSON structure is in English for all languages. Neutral fields (references,
  verses, speaker role, discovery steps, date ranges, place ids, source ids) are
  identical across files; a cross-check verifies this. Text fields are written
  by the LLM in the target language, from that language's verse text. The
  extract is always verbatim from that language's corpus.

## Output schema
Defined by the "Schéma JSON" section of the specification (schema 2). Do not
reintroduce the old French keys (citation, longueurExtrait, nbMotExtrait,
auteur, contexte, reference, lien, version).

## Status of this file
validate.py and its tests still enforce the old 14-word rule until task 2 of
the specification is done. Do not change validate.py before that task is agreed.

## Conventions
- The LLM is used only for: relevance judgement (model mode), speaker, context,
  choice of extract bounds, paraphrase. Cache results per verse + language + prompt version.
- Ask for a plan before coding. Run pytest before every commit. Tests cover validate.py.
- API key only via environment variable or GitHub secret, never in the repo.
- Code, comments and docs in English. Talk with the user in the language
  they write in (French or English).
