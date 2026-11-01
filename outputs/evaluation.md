# Evaluation

Generated 2026-11-01T11:10:43+00:00. **All labels are model labels** (Gemini 3.1 Pro + Jev, blind); see `labels/README.md`.

## Link precision (labelled sample)

88 links labelled from a population of 444995 non-singleton links ({'exact_abn': 345605, 'exact_acn': 43109, 'exact_lei': 3655, 'bridge_abr_acn': 14034, 'name_exact_norm': 8936, 'name_semantic': 729, 'name_exact_norm_same_source': 28927}).

Columns: `precision (decided)` = correct / (correct + incorrect) where both labellers agreed — a **sample proportion**, not a population figure; `Wilson 95% lower` = a real 95% lower confidence bound on that proportion (small groups get wide intervals: 3/3 → 0.44); `share correct of all labelled` treats every unresolved label as wrong; `Pro-only` = Gemini Pro's verdicts alone, the labeller that is independent of the matcher (Jev scored the semantic links itself).

### By match type

| group | labelled | correct | incorrect | unresolved | precision (decided) | Wilson 95% lower | share correct of all labelled | Pro-only |
|---|---|---|---|---|---|---|---|---|
| bridge_abr_acn | 25 | 25 | 0 | 0 | 1.0 | 0.867 | 1.0 | 1.0 |
| exact_abn | 21 | 21 | 0 | 0 | 1.0 | 0.845 | 1.0 | 1.0 |
| exact_acn | 7 | 7 | 0 | 0 | 1.0 | 0.646 | 1.0 | 1.0 |
| exact_lei | 6 | 6 | 0 | 0 | 1.0 | 0.61 | 1.0 | 1.0 |
| name_exact_norm | 8 | 4 | 0 | 4 | 1.0 | 0.51 | 0.5 | 1.0 |
| name_exact_norm_same_source | 13 | 12 | 0 | 1 | 1.0 | 0.757 | 0.923 | 1.0 |
| name_semantic | 8 | 7 | 0 | 1 | 1.0 | 0.646 | 0.875 | 0.875 |

### By tier pair

| group | labelled | correct | incorrect | unresolved | precision (decided) | Wilson 95% lower | share correct of all labelled | Pro-only |
|---|---|---|---|---|---|---|---|---|
| tier1 → tier1 | 12 | 12 | 0 | 0 | 1.0 | 0.757 | 1.0 | 1.0 |
| tier1 → tier2 | 1 | 1 | 0 | 0 | 1.0 | 0.207 | 1.0 | 1.0 |
| tier2 → tier1 | 21 | 21 | 0 | 0 | 1.0 | 0.845 | 1.0 | 1.0 |
| tier2 → tier2 | 10 | 10 | 0 | 0 | 1.0 | 0.722 | 1.0 | 1.0 |
| tier3 → tier1 | 10 | 10 | 0 | 0 | 1.0 | 0.722 | 1.0 | 1.0 |
| tier3 → tier2 | 7 | 3 | 0 | 4 | 1.0 | 0.438 | 0.429 | 0.857 |
| tier3 → tier3 | 27 | 25 | 0 | 2 | 1.0 | 0.867 | 0.926 | 1.0 |

### By source pair

| group | labelled | correct | incorrect | unresolved | precision (decided) | Wilson 95% lower | share correct of all labelled | Pro-only |
|---|---|---|---|---|---|---|---|---|
| data.gov.au:asic-afs-licensee ↔ local:asic-companies-slice | 10 | 10 | 0 | 0 | 1.0 | 0.722 | 1.0 | 1.0 |
| data.gov.au:asic-banned-disqualified-org ↔ local:abr-slice | 5 | 5 | 0 | 0 | 1.0 | 0.566 | 1.0 | 1.0 |
| data.gov.au:asic-banned-disqualified-org ↔ local:asic-companies-slice | 1 | 1 | 0 | 0 | 1.0 | 0.207 | 1.0 | 1.0 |
| data.gov.au:asic-credit-licensee ↔ local:asic-companies-slice | 3 | 3 | 0 | 0 | 1.0 | 0.438 | 1.0 | 1.0 |
| local:abr-slice ↔ local:asic-companies-slice | 5 | 5 | 0 | 0 | 1.0 | 0.566 | 1.0 | 1.0 |
| local:asic-companies-slice ↔ data.gov.au:asic-afs-licensee | 1 | 1 | 0 | 0 | 1.0 | 0.207 | 1.0 | 1.0 |
| local:asic-companies-slice ↔ local:abr-slice | 2 | 2 | 0 | 0 | 1.0 | 0.342 | 1.0 | 1.0 |
| local:asic-companies-slice ↔ local:asic-companies-slice | 5 | 5 | 0 | 0 | 1.0 | 0.566 | 1.0 | 1.0 |
| local:gleif-lei-au ↔ local:abr-slice | 4 | 4 | 0 | 0 | 1.0 | 0.51 | 1.0 | 1.0 |
| local:gleif-lei-au ↔ local:asic-companies-slice | 1 | 1 | 0 | 0 | 1.0 | 0.207 | 1.0 | 1.0 |
| local:gleif-lei-au ↔ local:gleif-relationships | 3 | 3 | 0 | 0 | 1.0 | 0.438 | 1.0 | 1.0 |
| local:gleif-relationships ↔ local:gleif-lei-au | 3 | 3 | 0 | 0 | 1.0 | 0.438 | 1.0 | 1.0 |
| local:gleif-relationships ↔ local:gleif-relationships | 4 | 4 | 0 | 0 | 1.0 | 0.51 | 1.0 | 1.0 |
| nsw:liquor-licence-premises-list-as-at-8-feb-2021 ↔ data.gov.au:acnc-register | 2 | 2 | 0 | 0 | 1.0 | 0.342 | 1.0 | 1.0 |
| nsw:liquor-licence-premises-list-as-at-8-feb-2021 ↔ local:gleif-lei-au | 3 | 0 | 0 | 3 | None | None | 0.0 | 0.667 |
| nsw:liquor-licence-premises-list-as-at-8-feb-2021 ↔ nsw:liquor-licence-premises-list-as-at-8-feb-2021 | 3 | 2 | 0 | 1 | 1.0 | 0.342 | 0.667 | 1.0 |
| qld:ehp-suitable-operator-register-sor-for-environmentally-relevant-activities-eras ↔ local:asic-companies-slice | 1 | 1 | 0 | 0 | 1.0 | 0.207 | 1.0 | 1.0 |
| qld:ehp-suitable-operator-register-sor-for-environmentally-relevant-activities-eras ↔ local:gleif-lei-au | 2 | 1 | 0 | 1 | 1.0 | 0.207 | 0.5 | 1.0 |
| qld:ehp-suitable-operator-register-sor-for-environmentally-relevant-activities-eras ↔ qld:qbcc-licensed-contractors-register | 3 | 2 | 0 | 1 | 1.0 | 0.342 | 0.667 | 1.0 |
| qld:qbcc-licensed-contractors-register ↔ local:asic-companies-slice | 4 | 4 | 0 | 0 | 1.0 | 0.51 | 1.0 | 1.0 |
| qld:qbcc-licensed-contractors-register ↔ qld:qbcc-licensed-contractors-register | 10 | 10 | 0 | 0 | 1.0 | 0.722 | 1.0 | 1.0 |
| qld:queensland-government-contracts-directory-awarded-contracts ↔ local:abr-slice | 1 | 1 | 0 | 0 | 1.0 | 0.207 | 1.0 | 1.0 |
| qld:queensland-government-contracts-directory-awarded-contracts ↔ local:asic-companies-slice | 1 | 1 | 0 | 0 | 1.0 | 0.207 | 1.0 | 1.0 |
| qld:queensland-government-contracts-directory-awarded-contracts ↔ local:gleif-lei-au | 2 | 2 | 0 | 0 | 1.0 | 0.342 | 1.0 | 1.0 |
| qld:queensland-government-contracts-directory-awarded-contracts ↔ qld:ehp-suitable-operator-register-sor-for-environmentally-relevant-activities-eras | 1 | 1 | 0 | 0 | 1.0 | 0.207 | 1.0 | 1.0 |
| qld:queensland-government-contracts-directory-awarded-contracts ↔ qld:qbcc-licensed-contractors-register | 2 | 2 | 0 | 0 | 1.0 | 0.342 | 1.0 | 1.0 |
| qld:queensland-government-contracts-directory-awarded-contracts ↔ qld:queensland-government-contracts-directory-awarded-contracts | 6 | 6 | 0 | 0 | 1.0 | 0.61 | 1.0 | 1.0 |

## Thresholds

- semantic path, default sources: link if Jev P(same) ≥ **0.85**
- sensitive sources (ASIC bans): ≥ **0.95**
- persons: never linked by name alone
- exact identifier path: 0.99 regardless (checksum-valid ABN/ACN/LEI)
- arbitration: a conflicting identifier of the same kind beats any name similarity → abstain

## Recall of the semantic path (hidden-identifier test, full index)

150 records that were linked by an exact identifier had the identifier hidden and were re-resolved by name against **every other record** (555,547 records, 347,295 blocking keys) — the production index, not a sampled background.

| stage | value |
|---|---|
| candidate recall (true party among the candidates after blocking + similarity floor) | **0.913** |
| ranking accuracy (true party ranked first, given it was a candidate) | **0.985** |
| acceptance recall (ranked first AND ≥ threshold 0.85: the link would be made) | **0.887** |
| false-accept rate (a different party ranked first AND ≥ threshold: a wrong link) | **0.0** |

Where the misses happen: {'ok': 133, 'not_in_candidates': 13, 'below_threshold': 2, 'ranked_below_other': 2}. (`blocking_keys`: distinctive name tokens ≥3 chars, first-token+state, postcode+first-token; generic tokens excluded.)

## Identifier coverage per source

| source | tier | records | with ABN/ACN/LEI | % | abn | acn | lei |
|---|---|---|---|---|---|---|---|
| data.gov.au:acnc-register | 3 | 66341 | 65905 | 99.3 | 65905 | 0 | 0 |
| data.gov.au:asic-afs-licensee | 2 | 6541 | 6540 | 100.0 | 6344 | 196 | 0 |
| data.gov.au:asic-banned-disqualified-org | 2 | 15 | 15 | 100.0 | 0 | 15 | 0 |
| data.gov.au:asic-credit-licensee | 3 | 4308 | 4239 | 98.4 | 3846 | 393 | 0 |
| data.gov.au:asic-liquidator | 2 | 662 | 0 | 0.0 | 0 | 0 | 0 |
| local:abr-slice | 1 | 64484 | 64484 | 100.0 | 64484 | 60858 | 0 |
| local:asic-companies-slice | 1 | 80188 | 80188 | 100.0 | 78600 | 80188 | 0 |
| local:gleif-lei-au | 2 | 53604 | 53604 | 100.0 | 14125 | 36787 | 53604 |
| local:gleif-relationships | 2 | 6489 | 6489 | 100.0 | 0 | 0 | 6489 |
| nsw:liquor-licence-premises-list-as-at-8-feb-2021 | 3 | 18747 | 0 | 0.0 | 0 | 0 | 0 |
| qld:ehp-suitable-operator-register-sor-for-environmentally-relevant-activities-eras | 3 | 15128 | 8222 | 54.3 | 300 | 7922 | 0 |
| qld:qbcc-licensed-contractors-register | 3 | 205535 | 116718 | 56.8 | 112001 | 48237 | 0 |
| qld:queensland-government-contracts-directory-awarded-contracts | 3 | 45752 | 0 | 0.0 | 0 | 0 | 0 |

## Confusion cases

- **Commonwealth Bank of Australia** → `resolved`; top: COMMONWEALTH BANK OF AUSTRALIA (name_exact_norm, score 0.95, Jev None/None)
- **Commonwealth Superannuation Corporation** → `resolved`; top: COMMONWEALTH SUPERANNUATION CORPORATION (name_exact_norm, score 0.95, Jev None/None)
- **commonwealth bank** → `resolved`; top: COMMONWEALTH BANK OF AUSTRALIA (name_exact_norm, score 0.95, Jev None/None)
- **CBA** → `abstained`; top: COMMONWEALTH BANK OF AUSTRALIA (name_semantic, score 0.72, Jev 0.72/same); CBA A320 AIRCRAFT NO1 PTY LTD (name_semantic, score 0.32, Jev 0.32/related); CBA BUILDING SOLUTIONS PTY LTD (name_semantic, score 0.31, Jev 0.31/same)
- **Commonwealth Super Corp** → `abstained`; top: COMMONWEALTH SUPERANNUATION CORPORATION (name_semantic, score 0.5, Jev 0.5/same); Commonwealth Bank Group Super (name_semantic, score 0.19, Jev 0.19/related); COMMONWEALTH PRIVATE LIMITED (name_semantic, score 0.14, Jev 0.14/unrelated)

## resolve() benchmark (200 dirty references, `labels/dirty_references.jsonl`)

Outcomes are kept apart; 'asked the user' is not counted as 'resolved'.

- **resolved accuracy: 0.91** = 171/188 present references resolved to the expected key; **0 resolved to a wrong key**
- clarification: 2 references were ambiguous; the expected entity was among the offered candidates in 2 (success 1.0)
- abstained although present: 15
- absent references (12): abstained 12, wrongly resolved/offered 0
- acceptable outcome (resolved correctly, or asked with the right option, or abstained on an absent reference): 185/200
- failure stage over present references: {'below_threshold': 14, 'not_in_candidates': 1, 'ambiguous_gap': 1, 'not_top': 1} (retrieval → ranking → acceptance)
- p50 6.3 ms, p95 1551.1 ms

| perturbation | n | resolved ✓ | resolved ✗ | asked (✓ offered) | asked (✗) | abstained (present) | abstained (absent) | false resolve | failure stages |
|---|---|---|---|---|---|---|---|---|---|
| exact | 21 | 21 | 0 | 0 | 0 | 0 | 0 | 0 |  |
| lower | 21 | 20 | 0 | 1 | 0 | 0 | 0 | 0 | {'not_top': 1} |
| no_legal_form | 21 | 21 | 0 | 0 | 0 | 0 | 0 | 0 |  |
| typo | 21 | 7 | 0 | 0 | 0 | 14 | 0 | 0 | {'below_threshold': 13, 'not_in_candidates': 1} |
| abn_spaced | 21 | 21 | 0 | 0 | 0 | 0 | 0 | 0 |  |
| acn_only | 21 | 21 | 0 | 0 | 0 | 0 | 0 | 0 |  |
| abbrev | 21 | 21 | 0 | 0 | 0 | 0 | 0 | 0 |  |
| extra_words | 21 | 19 | 0 | 1 | 0 | 1 | 0 | 0 | {'below_threshold': 1, 'ambiguous_gap': 1} |
| trading_or_former | 20 | 20 | 0 | 0 | 0 | 0 | 0 | 0 |  |
| absent | 12 | 0 | 0 | 0 | 0 | 0 | 12 | 0 |  |

## Resolution run

```json
{
 "records": 555547,
 "links": 555546,
 "abstentions": 139479,
 "parties": 352368,
 "jev_calls": 25,
 "secs_exact": 5.8,
 "secs_semantic": 9.2,
 "secs_singletons": 0.4,
 "secs_persist": 5.6,
 "blocking": {
  "pending": 149143,
  "indexed": 406404,
  "blocks": 296396,
  "largest_block": 8122,
  "records_with_candidates": 44088,
  "skipped_oversize_blocks": 38520
 },
 "scorer_down": false,
 "cached_pairs_used": 58749,
 "match_types": {
  "exact_abn": 345605,
  "singleton": 110551,
  "exact_acn": 43109,
  "name_exact_norm_same_source": 28927,
  "bridge_abr_acn": 14034,
  "name_exact_norm": 8936,
  "exact_lei": 3655,
  "name_semantic": 729
 },
 "abstain_reasons": {
  "person_name_only": 96068,
  "below_threshold": 34423,
  "no_candidate_in_block": 8964,
  "no_usable_name": 23,
  "identifier_conflict": 1
 },
 "secs_total": 21.2
}
```