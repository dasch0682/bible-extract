# Report: la vérité

## Price check
- Checked at: 2026-10-08T14:49:00Z (source: https://openrouter.ai/api/v1/models)
- Result: OK

| Model | Ref in | Ref out | Now in | Now out | Status |
|---|---|---|---|---|---|
| deepseek/deepseek-v4.1-flash | 0.3 | 1.2 | 0.3 | 1.2 | ok |
| mistralai/mistral-large-4-0 | 0.68 | 2.09 | 0.68 | 2.09 | ok |

Prices in USD per 1M tokens.

## Discovery
- Mode: model
- Labels: fr="la vérité", en="truth"
- Strong's numbers: ['G225', 'G227', 'G228', 'G230']
- Refs by Strong's: 162
- Refs by patterns (fr, rules ['verit', 'vrai']): 162
- Excluded formulas (fr): ['amen_formula']; verses whose only match was inside one: 79
- Refs by patterns (en, rules ['truth', 'true_word']): 173
- Candidates: 198 (kept for the run: 50)
- Found by both routes: 38
- Strong's only: 2
- Patterns only: 10

### Strong's only
  - MAT.26.73
  - MRK.14.70

### Patterns only
  - MAT.9.37
  - MAT.15.27
  - MAT.17.11
  - MAT.20.23
  - MRK.10.39
  - MRK.14.38
  - LUK.10.2
  - LUK.11.48
  - LUK.22.22
  - LUK.24.22

### Excluded by phrase filter (fr)
  - MAT.5.18
  - MAT.5.26
  - MAT.6.2
  - MAT.6.5
  - MAT.6.16
  - MAT.8.10
  - MAT.10.15
  - MAT.10.23
  - MAT.10.42
  - MAT.11.11
  - MAT.13.17
  - MAT.16.28
  - MAT.17.20
  - MAT.18.3
  - MAT.18.13
  - MAT.18.18
  - MAT.19.23
  - MAT.19.28
  - MAT.21.21
  - MAT.21.31
  - MAT.23.36
  - MAT.24.2
  - MAT.24.34
  - MAT.24.47
  - MAT.25.12
  - MAT.25.40
  - MAT.25.45
  - MAT.26.13
  - MAT.26.21
  - MAT.26.34
  - MRK.3.28
  - MRK.8.12
  - MRK.9.1
  - MRK.9.41
  - MRK.10.15
  - MRK.10.29
  - MRK.11.23
  - MRK.12.43
  - MRK.13.30
  - MRK.14.9
  - MRK.14.18
  - MRK.14.25
  - MRK.14.30
  - LUK.4.24
  - LUK.4.25
  - LUK.9.27
  - LUK.12.37
  - LUK.12.44
  - LUK.18.17
  - LUK.18.29
  - LUK.21.3
  - LUK.21.32
  - LUK.23.43
  - JHN.1.51
  - JHN.3.3
  - JHN.3.5
  - JHN.3.11
  - JHN.4.24
  - JHN.5.19
  - JHN.5.24
  - JHN.5.25
  - JHN.6.26
  - JHN.6.47
  - JHN.6.53
  - JHN.8.34
  - JHN.8.51
  - JHN.8.58
  - JHN.10.1
  - JHN.10.7
  - JHN.12.24
  - JHN.13.16
  - JHN.13.20
  - JHN.13.21
  - JHN.13.38
  - JHN.14.12
  - JHN.16.20
  - JHN.16.23
  - JHN.21.18
  - ACT.10.34

## Versification
- TVTMS has a rule for 1 candidate verse(s); nothing is remapped.
  - JHN.6.55: [{'traditions': ['Eng-KJV', 'Greek'], 'standard_ref': 'Jhn.6:55', 'action': 'Keep verse'}, {'traditions': ['Latin'], 'standard_ref': 'Jhn.6:54', 'action': 'Renumber verse'}]

## Relevance judgement (pivot language: fr)
- Candidates judged: 50
- Relevant: 25
- Not relevant: 25
- No valid verdict (not kept): 0

### Not relevant
  - MAT.9.37
  - MAT.15.27
  - MAT.17.11
  - MAT.20.23
  - MAT.26.73
  - MAT.27.54
  - MRK.10.39
  - MRK.14.38
  - MRK.14.70
  - MRK.15.39
  - LUK.4.25
  - LUK.9.27
  - LUK.10.2
  - LUK.11.48
  - LUK.12.44
  - LUK.16.11
  - LUK.21.3
  - LUK.22.22
  - LUK.22.59
  - LUK.24.22
  - JHN.1.47
  - JHN.6.14
  - JHN.6.55
  - JHN.7.26
  - JHN.7.40

## Excerpts
- Excerpts: 20 (window of rules mode: 2)
- Merged because they overlapped: 3
  - JHN.1.14 to JHN.1.18: 2 candidates
  - JHN.5.31 to JHN.5.33: 3 candidates
  - JHN.8.13 to JHN.8.18: 3 candidates

## fr: Louis Segond 1910
- excerpts: 20
- valid: 20
- rejected: 0

## en: King James Version (1769)
- excerpts: 20
- valid: 20
- rejected: 0

## Intersection
- kept in all languages: 20
- dropped (invalid in at least one language): 0

## Review
- entries that must go through the review page: 7

  - MAT.14.33 to MAT.14.33 (review required): genre_conflict:speaker:narrative
  - MAT.22.16 to MAT.22.16 (review required): genre_conflict:speaker:narrative
  - MRK.5.33 to MRK.5.33: speaker_not_identified
  - MRK.12.29 to MRK.12.34 (review required): paraphrase_failed, speaker_ambiguous
  - JHN.1.9 to JHN.1.9: speaker_not_identified
  - JHN.1.14 to JHN.1.18 (review required): genre_conflict:speaker:narrative, speaker_partial_coverage
  - JHN.5.31 to JHN.5.33 (review required): paraphrase_failed
  - JHN.6.32 to JHN.6.33 (review required): paraphrase_failed
  - JHN.8.13 to JHN.8.18 (review required): speaker_ambiguous

## Cross-language check
- neutral fields identical in every language file
