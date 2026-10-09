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
- Every uncertain value carries a confidence level. Date, place and speaker levels are
  computed by the code from the rule files (`data/date_rules.yml`, `data/place_rules.yml`,
  `speaker.rate`), never by an LLM. The only level a model judges is the literary context,
  in the same call that writes it; the code limits the call (citations must come from the verses
  shown, valid level, short text) and records `confidence_by: model`, the model and the prompt version.
- Counters and measurements are computed by the code, never by the LLM.
- Do not modify validate.py without explicit approval.
- Public-domain texts only. Never add copyrighted translations
  (NBS, ISV, NIV...) to the repo or to prompts as source text.
- Verify the license of every dataset before use and record it in
  data/SOURCES.md. Never assume a license.

## Finding references (default: Strong's numbers)
- Default discovery uses Strong's numbers (Greek lemmas), listed per topic in topics/<topic>.yml
  (e.g. strongs: [G225, G227, G228, G230]).
- Strong's: numbers only. Never copy the dictionary definitions (GPL).
- Pivot: the Strong's-tagged Byzantine Greek NT (byztxt, public domain) gives the verse references; they are
  used as they are in every language (NT numbering is shared by the LSG and the KJV). TVTMS is only a check:
  the candidates it has a rule for are listed in the report, nothing is remapped (to revisit with OT topics).
- Word patterns are a cross-check on each language's own corpus: `patterns_<lang>` in the topic file is a mapping
  rule name -> regex, run on the normalised text (no accents, lowercase). Rule names are never bare YAML booleans
  (`true`, `no`, `on`...). The union of the Strong's route and the patterns of every language gives the candidates.
  A verse found by one family of routes only stays a candidate, is listed in out/<topic>.report.md and carries
  `single_route: true` in its `union` step, never silently dropped.
- `exclude_phrases_<lang>` (mapping name -> regex in a topic YML) are stripped from the normalised text before
  pattern matching (e.g. `amen_formula`: "en vérité"). A verse that matched only because of an excluded formula is
  listed in the report under "Excluded by phrase filter" and recorded in its `exclusion_check` step
  (`excluded: true`). Strong's discovery is never affected.
- `extra_instructions_<lang>` are appended to the relevance prompt (model mode) of the pivot language.
- Discovery has two modes (`--mode rules|model`, default rules). `rules`: the code decides (Strong's, patterns,
  exclusions) and every candidate is kept; the excerpt is the verse extended by at most `excerpt.window` verses
  (data/discovery_rules.yml, 2 at first) inside the speaker-quotations range that covers it, the verse alone when
  none covers it. `model`: `relevance.judge` (role `relevance`) judges each candidate once, on the pivot language,
  cites verses and proposes bounds among the verses shown (`model.window`); the code checks them, and the bounds
  apply to every language file. Excerpts that overlap are merged. Candidates not kept (not relevant, or no valid
  verdict) are listed in the report. Mode, model, prompt version and every step are recorded in the entry's
  `discovery` field (steps: `union`, `strongs`, `pattern`, `exclusion_check`, `llm_relevance`).

## Paraphrase
- Keeps the original genre (discourse, narrative, letter, prayer, parable),
  and is never longer than the extract (word count compared by the code).
  It adds no information absent from the extract.
- Three candidates (`close`, `condensed`, `free`) are generated in ONE call.
  The code runs its checks (not longer than the extract, target language,
  non-empty), then ONE verification call by a model from a different family
  than the generator, candidates shuffled and unlabelled. The code arbitrates.
- If no candidate passes: paraphrase is null with reason `no_faithful_version`,
  and the entry goes to review.
- The full history (candidates, checks, scores, arbitration) is kept in the entry,
  with `prompt_version`.

## Context, dates and speaker
- Context has `narrative`, `literary`, `temporal` and `places` parts, each sourced and
  given a confidence level. `narrative` (optional) has three fields: `situation` (what
  is happening around the excerpt), `place` (scene location), `arc_position` (position
  in the book's arc). It is produced by `narrative.py`, which uses a chapter-level
  pericope summary (`pericope.py`, cached once per chapter) as background context.
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
- Code map (task 6): `context.build_context` assembles `speaker` and `context` from
  `speaker.py` (speaker-quotations + ACAI cross-check), `dating.py` (one entry per source, levels from
  `data/date_rules.yml`), `day_candidates.py` + `calendar_calc.py` (Passion and Pentecost candidates from
  `data/calendar_rules.yml`, explicit hypotheses), `places.py` (OpenBible, `data/place_rules.yml`),
  `literary.py` (model within code limits), `pericope.py` (chapter-level summary, cached, from
  `data/narrative_rules.yml`) and `narrative.py` (per-excerpt situation/place/arc_position, uses
  pericope summary). `provenance.py` builds the `sources` records from `data/sources.yml`. Short texts
  (names, labels) are written by a model through `localize.py` and cached.
- Code map (task 7): `paraphrase.build_paraphrase` writes the `paraphrase` field from the excerpt text, with injected calls
  `calls = {"paraphrase_generation": (call, model_id), "paraphrase_verification": (call, model_id)}` and the rules in
  `data/paraphrase_rules.yml` (`min_fidelity`, language markers). It returns the field and flags; `paraphrase.review_required`
  tells when a human must look (`paraphrase_failed`, `genre_conflict`). The genre is proposed by the model in the generation call;
  a genre that contradicts the speaker role is flagged.
- Theographic years are ISO 8601 astronomical (0 = 1 BCE, -3 = 4 BCE); `dating.to_schema` converts them.
  validate.py wants `from <= to` as numbers, so for BCE `from` is the later bound.

- Code map (task 8): `discovery.py` (routes, union, recorded steps, TVTMS check; no model), `bounds.py` (rules-mode
  bounds, merge of overlapping excerpts), `relevance.py` (model-mode verdict within the code's limits) and
  `extract.py`, which wires everything: price check, `context.build_context`, `paraphrase.build_paraphrase`,
  `validate.validate_entry`, `validate.check_cross_language`, report. Each entry carries
  `review: {status, note, flags, required}`: `flags` and `required` come from the modules (`speaker_ambiguous`,
  `literary_failed`, `paraphrase_failed`, `genre_conflict`...) and tell the review page what a human must look at.
  A range is written only when its entry validates in every language; the others are listed in the report.

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
validate.py enforces schema 2 (task 2 is done). extract.py is migrated to schema 2 (task 8): discovery, context,
paraphrase and validation run end to end, tested with fake models. Still to do: the review page for schema 2 (task 9)
and a trial on a varied sample before any full batch (task 10). Do not change validate.py without explicit approval.

## Conventions
- The LLM is used only for: relevance judgement (model mode), speaker, context,
  choice of extract bounds, paraphrase. Cache results per verse + language + prompt version.
- Ask for a plan before coding. Run pytest before every commit. Tests cover validate.py.
- API key only via environment variable or GitHub secret, never in the repo.
- Code, comments and docs in English. Talk with the user in the language
  they write in (French or English).
