# Data sources

Every corpus used in this project must be listed here before use.
Verify the license of each source independently — never assume.

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

## License compatibility summary

| Source | License | Corpus in repo? | Attribution in output? |
|---|---|---|---|
| KJV (scrollmapper) | MIT / PD | No (downloaded) | No (PD text) |
| LSG 1910 (BibleAquifer) | CC0 | No (downloaded) | No (PD) |
| Byzantine Greek NT (byztxt) | Unlicense/PD | No | No |
| TAHOT (STEPBible) | CC BY 4.0 | No | In SOURCES.md only |
| Versification (Copenhagen) | CC BY-SA 4.0 | No (build tool) | In SOURCES.md only |
| Strong's lexicon (openscriptures) | CC BY-SA | No (optional) | In SOURCES.md only |

**Output JSON files** (`out/*.json`) contain only verse text from PD sources (KJV, LSG 1910) and LLM-generated fields — no CC BY-SA data is embedded. No ShareAlike obligation applies to the outputs.
