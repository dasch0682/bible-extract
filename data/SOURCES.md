# Data sources

Every corpus used in this project must be listed here before use.
Verify the license of each source independently — never assume.

Machine-readable twin: `data/sources.yml` (ids, licenses, attribution strings); pinned commits of the
fetched datasets: `data/sources.lock.json`. `python scripts/fetch_sources.py --check` re-reads each
license file and fails if a marker string disappeared. Coverage measured on 20 passages: `data/COVERAGE.md`.

---

## 1. KJV — King James Version (1769)

| Field | Value |
|---|---|
| **Usage** | English language output (`data/en.json`); pivot language for Strong's verse references |
| **Repository** | https://github.com/scrollmapper/bible_databases |
| **File** | `formats/json/KJV.json` |
| **License** | MIT (repo) — KJV text itself: **Public Domain** (US; Crown copyright in UK) |
| **Verified** | 2026-10-04 — `gh api repos/scrollmapper/bible_databases --jq .license` → MIT |
| **Format** | JSON array: `[{book_name, chapter, verse, text}]` |
| **Download** | `curl -L https://raw.githubusercontent.com/scrollmapper/bible_databases/master/formats/json/KJV.json -o data/en.json` |
| **Notes** | Plain text only — Strong's numbers are **not** in this file (see source 3 for Strong's). |

---

## 2. LSG 1910 — Louis Segond 1910

| Field | Value |
|---|---|
| **Usage** | French language output (`data/fr.json`) |
| **Repository** | https://github.com/BibleAquifer/LouisSegond1910 |
| **Files** | `fra/json/01.content.json` … `fra/json/66.content.json` (one per canonical book) |
| **License** | **CC0 1.0 Universal (Public Domain)** — confirmed in repository README |
| **Verified** | 2026-10-04 — README states "licensed under the Public Domain CC0" |
| **Format** | Per-book JSON array; each entry has fields `title` ("Matthieu 1.1"), `content` (HTML `<p>` with `<sup>` verse number), `language: "fra"`. Requires HTML stripping and conversion to `{book: {chap: {verse: text}}}`. |
| **Download** | `git clone --depth 1 https://github.com/BibleAquifer/LouisSegond1910 tmp/lsg1910 && python scripts/build_corpus.py lsg1910` (script to be written) |
| **Sample check** | Jean 14,6 → "Jésus lui dit: Je suis le chemin, la vérité, et la vie." Verify verbatim against a reference (e.g. CCEL or Gallica scan) before committing corpus. |

---

## 3. Byzantine Greek NT with Strong's numbers

| Field | Value |
|---|---|
| **Usage** | Strong's concordance pivot for NT (G-numbers → verse references) |
| **Repository** | https://github.com/byztxt/byzantine-majority-text |
| **Files** | `csv-unicode/strongs/with-parsing/<BOOK>.csv` (27 NT books) |
| **License** | **Unlicense (Public Domain)** — confirmed in GitHub metadata and LICENSE.txt |
| **Verified** | 2026-10-04 — `gh api repos/byztxt/byzantine-majority-text --jq .license.key` → "unlicense" |
| **Format** | 3-column CSV: `chapter,verse,text` — text is space-separated tokens `word strongsnum {MORPHOLOGY}` (e.g. `αληθειαν 225 {N-ASF}`). Strong's number is a bare integer; prefix `G` to match topic YAML (G225). |
| **Text base** | Robinson-Pierpont 2018 Byzantine Majority Text — covers all 27 NT books. |
| **Download** | `git clone --depth 1 https://github.com/byztxt/byzantine-majority-text tmp/byztxt` |
| **Notes** | OT (H-numbers) is not covered here; see source 4 for OT Hebrew. |

---

## 4. STEPBible Translators Amalgamated Hebrew OT

| Field | Value |
|---|---|
| **Usage** | Strong's concordance pivot for OT (H-numbers → verse references) — needed when scope includes OT |
| **Repository** | https://github.com/STEPBible/STEPBible-Data |
| **Files** | `Translators Amalgamated OT+NT/TAHOT *.txt` (4 files covering Gen–Mal) |
| **License** | **CC BY 4.0** — stated in repository README and file headers |
| **Verified** | 2026-10-04 — README header: "STEPBible Data Repository CC BY 4.0" |
| **Attribution required** | "TAHOT — Translators Amalgamated Hebrew OT, STEPBible.org (https://github.com/STEPBible/STEPBible-Data), CC BY 4.0" |
| **Format** | Tab-delimited text; each word row includes Strong's number and verse reference. See file header for column spec. |
| **Download** | `git clone --depth 1 https://github.com/STEPBible/STEPBible-Data tmp/stepbible` |
| **Notes** | OT only. Not needed for NT-scoped topics. Strong's numbers are extended (e.g. H1234a) but backward-compatible with original Strong's H-numbers. |

---

## 5. Versification map — English standard

| Field | Value |
|---|---|
| **Usage** | Maps verse references across different versification traditions (e.g. Psalm numbering differences); used during build, not distributed in output |
| **Repository** | https://github.com/Copenhagen-Alliance/versification-specification |
| **File** | `versification-mappings/standard-mappings/eng.json` |
| **License** | Data: **CC BY-SA 4.0** — Code: Apache 2.0 — confirmed in LICENSE.md |
| **Verified** | 2026-10-04 — LICENSE.md states data is CC BY-SA 4.0 |
| **Attribution required** | "Versification data from the Copenhagen Alliance for Open Biblical Language Resources (https://github.com/Copenhagen-Alliance/versification-specification), CC BY-SA 4.0" |
| **ShareAlike note** | This file is used only as a processing tool during corpus build. It is **not** embedded in or distributed with the JSON outputs. No ShareAlike obligation on outputs. |
| **Format** | JSON: `{maxVerses: {BOOK: [versesInChap1, ...]}, mappedVerses: {...}, excludedVerses: [...]}` — represents English (KJV-based) versification. |
| **Download** | `curl -L https://raw.githubusercontent.com/Copenhagen-Alliance/versification-specification/master/versification-mappings/standard-mappings/eng.json -o data/versification_eng.json` |
| **Notes** | LSG 1910 follows Protestant/Hebrew versification (same as KJV for Psalms). Verify specific edge cases (Malachi 3/4 split, 3 John) before finalising the map. |

---

## 6. Strong's Greek lexicon (optional — definitions only)

| Field | Value |
|---|---|
| **Usage** | Human-readable gloss for each G-number (for documentation and review); NOT used in output JSON |
| **Repository** | https://github.com/openscriptures/strongs |
| **Files** | `greek/StrongsGreekDictionaryXML_1.4/` (XML) |
| **License** | **CC BY-SA** (digital edition) — no LICENSE file in repo; license stated in crizin/bible-db NOTICE which cites this source |
| **Verified** | 2026-10-04 — license derived from downstream attribution (direct repo has no LICENSE file; treat as CC BY-SA to be safe) |
| **Attribution** | "Strong's Greek Dictionary, digital edition by openscriptures (https://github.com/openscriptures/strongs)" |
| **ShareAlike note** | Used only as a lookup reference during topic-file authoring. Gloss strings do **not** appear in output JSON. |
| **Notes** | Original Strong's Concordance (1890, James Strong) is public domain. The openscriptures digital XML edition added corrections and markup, hence CC BY-SA on the derived work. |

---

## 7. Theographic Bible Metadata (`theographic`)

| Field | Value |
|---|---|
| **Usage** | Event dates (year only, BCE negative), places and people per verse |
| **Repository** | https://github.com/robertrouse/theographic-bible-metadata |
| **Pinned commit** | `cfb1c485d4da6fb63a69cb3b7f5b0752792f46bc` |
| **License** | **CC BY-SA 4.0** (file `LICENSE`, "Attribution-ShareAlike 4.0 International"). The specification said "CC BY": that was wrong. |
| **Verified** | 2026-10-07, from the license file of the clone |
| **Attribution** | "Theographic Bible Metadata (github.com/robertrouse/theographic-bible-metadata), CC BY-SA 4.0" |
| **Read by** | `datasets.load_theographic` (`json/events.json`, `verses.json`, `places.json`) |
| **Notes** | Some events carry a day (e.g. Pentecost 0030-05-02). Only the year is kept: days come from a calendar computation, never from a dataset. |

## 8. OpenBible.info Bible Geocoding Data (`openbible`)

| Field | Value |
|---|---|
| **Usage** | Ancient places per verse, identification score, Wikidata id |
| **Repository** | https://github.com/openbibleinfo/bible-geocoding-data |
| **Pinned commit** | `7eb18a5ee62f27b9b93bd6689ea272d76dd23b8f` |
| **License** | **CC BY 4.0** (file `license.txt`) |
| **Verified** | 2026-10-07 |
| **Attribution** | "OpenBible.info Bible Geocoding Data (github.com/openbibleinfo/bible-geocoding-data), CC BY 4.0" |
| **Read by** | `datasets.load_openbible` (`data/ancient.jsonl`), `places.py` (rules in `data/place_rules.yml`) |
| **Score used** | The `vote_total` of the best identification. README: "an overall total of 500 or higher represents high confidence". `vote_average` is not used for the level: it equals 500 for any place with a single identification, but is a mean vote (at most about 30) otherwise |
| **Notes** | Geometry is NOT used: part of it comes from OpenStreetMap (ODbL), which has its own obligations. Places whose best identification is `not_a_place` or `not_a_proper_name` are left out. |

## 9. TVTMS, Translators Versification Traditions (`tvtms`)

| Field | Value |
|---|---|
| **Usage** | Verse-number differences between traditions (e.g. Hebrew Psa.3:1 is Psa.3:Title in the KJV numbering) |
| **Repository** | https://github.com/STEPBible/STEPBible-Data (same repository as TAHOT) |
| **Pinned commit** | `1f3423d42400f59f1f30fe08f74e38fcd3bbf7bc` |
| **License** | **CC BY 4.0** (README and file header) |
| **Verified** | 2026-10-07 |
| **Attribution** | "Data created by www.STEPBible.org based on work at Tyndale House Cambridge, CC BY 4.0" |
| **Read by** | `datasets.load_tvtms` (section "Expanded"), `datasets.tvtms_standard_refs` |
| **Notes** | It gives mappings, not the number of verses per chapter. It does not replace the Copenhagen file (source 5) for bounds; no equivalence comparison was run. |

## 10. MACULA Quotation and Speaker Data (`speaker-quotations`)

| Field | Value |
|---|---|
| **Usage** | Speaker of each quotation, by verse range |
| **Repository** | https://github.com/Clear-Bible/speaker-quotations |
| **Pinned commit** | `b09e308a3a1aafdb7d6c75baf0fe2a31d61601da` |
| **License** | **CC BY 4.0**, plus **MIT** for the Glyssen / Faith Comes By Hearing character data (file `LICENSE.md`) |
| **Verified** | 2026-10-07 |
| **Attribution** | "MACULA Quotation and Speaker Data, © 2023 by Clear Bible, Inc" |
| **Read by** | `datasets.load_speakers` (`tsv/Clear-Aligned-Projections.tsv`), `datasets.speakers_at`, `speaker.py` |
| **Notes** | The dataset does not document its quote types (`Implicit`, `Quotation`...): they are recorded but never change a confidence level, except `Hypothetical` |

## 11. ACAI Biblical Entity Data (`acai`)

| Field | Value |
|---|---|
| **Usage** | People and places per verse (id and English label only). People: cross-check of the speaker (`speaker.py`, ids only). Places: measured for coverage, not used in outputs (no identification confidence) |
| **Repository** | https://github.com/BibleAquifer/ACAI |
| **Pinned commit** | `7e6a2d6674910aedb0888493ebbe6684d374ae5c` |
| **License** | **CC BY-SA 4.0** (file `LICENSE.md`) |
| **Verified** | 2026-10-07 |
| **Attribution** | "ACAI Biblical Entity Data, © BiblioNexus / Mission Mutual, CC BY-SA 4.0" |
| **Read by** | `datasets.load_acai` |

## 12. Wikidata (`wikidata`)

| Field | Value |
|---|---|
| **Usage** | Names of places and people in other languages. Not integrated yet; only the `Q` ids from OpenBible are kept |
| **License** | CC0 1.0 |
| **Verified** | Not verified in this task (not used yet). Check before the first use |

## 13. Dated anchors (`anchors`) and the primary texts behind them

| Field | Value |
|---|---|
| **Usage** | `data/anchors.yml`: second, independent source for dates. Each anchor cites its work, location, edition, URL and a verbatim `check_quote` (at most 40 words) |
| **Content** | 3 anchors: Tacitus, Annals 15.44; Josephus, Antiquities 18 (Gratus and Caiaphas; Pilate's ten years). All read in the Perseus files, none recalled from memory |
| **Texts** | Perseus Digital Library, `PerseusDL/canonical-latinLit` (commit `5493c006cc4c6f4651b6ea7f5f063aa88649efe5`, translation by Church and Brodribb) and `PerseusDL/canonical-greekLit` (commit `01b725d835e6e733062ffd79e0efdbae1ba06e5c`, translation by Whiston). Sparse clones in `tmp/`, read once |
| **License** | **CC BY-SA 4.0** (`license.md` of both repositories and the `<licence>` element of both files) |
| **Verified** | 2026-10-07 |
| **Attribution** | "Perseus Digital Library (Tufts University), CC BY-SA 4.0" |
| **Notes** | No numeric `date_range` yet: the texts give reigns and durations, not years. A numeric range will be added only with a source read for it. Luke 3:1 is not an anchor (it is the passage under study). |

---

## 14. Meeus, Astronomical Algorithms (`meeus-astronomical-algorithms`)

| Field | Value |
|---|---|
| **Usage** | Julian day (chapter 7) and new-moon times (chapter 49) in `calendar_calc.py`, for the day-level date candidates |
| **Reference** | Jean Meeus, *Astronomical Algorithms*, 2nd edition, Willmann-Bell, 1998 |
| **License** | Published formulas of a book. No text or table of the book is copied; the code implements the formulas |
| **Checks done** | Worked example 49.a of the book (new moon of February 1977, k = -283: JDE 2443192.65118, reproduced to 1e-5 day) and the new moon of 6 January 2000 (18:14 UT). Julian-calendar conversions and weekdays are tested on known dates |
| **Not yet checked** | The Delta T polynomial (Espenak and Meeus, NASA Five Millennium Canon of Solar Eclipses, valid -500 to +500) and the new-moon times of the first century against a published table (NASA Five Millennium Catalog of Moon Phases). Until then, candidates rely on formulas that are right for modern dates only by test |
| **Notes** | Nothing here is a source for a Bible fact. It only turns explicit hypotheses into dates |

---

## 15. Calendar rules (`calendar-rules`)

| Field | Value |
|---|---|
| **File** | `data/calendar_rules.yml` (project file) |
| **Content** | Hypotheses, not facts: where the month starts (moon age at sunset, two variants), the spring equinox taken at 21 March (Julian), Nisan 14 or 15 as the day of death, two readings of Leviticus 23:15-16 for Pentecost, the kept Passion years (30 and 33) and the years set aside (27 and 34, single source to check) |
| **License** | Project file |
| **Notes** | Every candidate lists the hypotheses it relies on. No candidate is presented as a fact |

---

## License compatibility summary

| Source | License | In repo? | Used in outputs? |
|---|---|---|---|
| KJV (scrollmapper) | MIT / PD | No (downloaded) | Text, no attribution |
| LSG 1910 (BibleAquifer) | CC0 | No (downloaded) | Text, no attribution |
| Byzantine Greek NT (byztxt) | Unlicense / PD | No | Numbers only |
| TAHOT (STEPBible) | CC BY 4.0 | No | Numbers only |
| Versification (Copenhagen) | CC BY-SA 4.0 | No (build tool) | No |
| Strong's lexicon (openscriptures) | CC BY-SA | No | Not used |
| TVTMS (STEPBible) | CC BY 4.0 | No | Reference mapping |
| Theographic | CC BY-SA 4.0 | No | Years, place names |
| OpenBible.info | CC BY 4.0 | No | Place names, scores, Wikidata ids |
| speaker-quotations | CC BY 4.0 + MIT | No | Speaker names |
| ACAI | CC BY-SA 4.0 | No | Entity ids, as a cross-check of the speaker |
| Perseus (anchors) | CC BY-SA 4.0 | Short quotes in `anchors.yml` | Reference only |
| Meeus (algorithms) | published formulas | No | Computed dates only |
| Calendar rules | project file | `data/calendar_rules.yml` | Hypotheses behind the day candidates |

**Decision of 2026-10-07:** datasets are integrated whatever their license, because nothing is shared for now.
**The license of the outputs is decided at publication.** Before any sharing, the ShareAlike sources
(Theographic, ACAI, Perseus) and the attribution strings of `data/sources.yml` must be reviewed: data derived
from them (years, place names) may carry a ShareAlike obligation.
