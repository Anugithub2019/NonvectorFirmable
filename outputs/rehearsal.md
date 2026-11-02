# Live rehearsal of the agent flow

Run through `Agent.turn` (the same entry point the Streamlit demo and the terminal chat use) against the loaded Neo4j and DuckDB, on 2026-11-02 03:01 UTC. Steps: clear match → ambiguous match → evidence-backed answer → dataset export, then a repeat export to show the same spec yields the same file. Transcript is verbatim; the checks are the assertions the script made.


## 1. Clear match → evidence-backed answer (intelligent mode)

**Question.** What licences does AIA Australia Limited hold, and who owns it?

**Tool calls.** `[('resolve', None), ('entity', None), ('ultimate_parent', None), ('read_cypher', None), ('read_cypher', None)]`

**Resolve decision.** `resolved` → `abn:79004837861` (AIA AUSTRALIA LIMITED, match_type `name_exact_norm`, score 0.95)

**Answer (17.6 s).**

### Entity Resolved
* **Name**: AIA AUSTRALIA LIMITED
* **Entity Key**: `abn:79004837861`
* **Identifiers**: ABN `79004837861` | ACN `004837861` | LEI `549300N73ROJAVEE4I54`
* **Match Type**: `name_exact_norm` (Score: 0.95)

---

### Licences Held
AIA Australia Limited holds two licences:

1. **Australian Financial Services (AFS) Licence**
   * **Licence ID**: `afs:230043`
   * **Type**: `afs`
   * **Start Date**: 2003-07-01
   * **Authorisations**: 1 listed authorisation
   * **Source**: `data.gov.au:asic-afs-licensee`

2. **Australian Credit Licence**
   * **Licence ID**: `credit:230043`
   * **Type**: `credit`
   * **Status**: `current`
   * **Start Date**: 2011-01-10
   * **Source**: `data.gov.au:asic-credit-licensee`

---

### Ownership Structure
According to GLEIF relationship datasets (`local:gleif-relationships`):

* **Direct Parent (`owned_by`)**: `lei:RU6VTXUC5TNXNI3V7Y80` (Directly consolidated by)
* **Ultimate Parent (`ultimately_owned_by`)**: `lei:ZP5ILWVSYE4LJGMMVD57` (Ultimately consolidated by)

---

### Limitations & Unverified Details
* **Parent Legal Names**: The graph records the parent entities by LEI (`lei:RU6VTXUC5TNXNI3V7Y80` and `lei:ZP5ILWVSYE4LJGMMVD57`), but their text legal names are not populated in this slice of the graph.
* **Ownership Percentages**: Ownership percentages are unspecified (`null`) in the available dataset.
* **Bans**: No bans were found in this slice of sources (`data.gov.au:asic-afs-licensee`, `data.gov.au:asic-credit-licensee`, `local:abr-slice`, `local:asic-companies-slice`, `local:gleif-lei-au`, `local:gleif-relationships`).

---

### Suggested Follow-up Questions
1. *Are there any entities or individuals within 1 or 2 hops of AIA Australia Limited that have active ASIC bans?*
2. *What trading names or former legal names has AIA Australia Limited operated under?*

**Check.** decision=resolved; `entity` called on the resolved key; keys cited in the answer: `['abn:79004837861', 'lei:RU6VTXUC5TNXNI3V7Y80', 'lei:ZP5ILWVSYE4LJGMMVD57']`.

## 2. Ambiguous match → clarification → user picks → answer

**Question.** Which licences does the trustee for the anderson family trust hold?

**Tool calls.** `[('resolve', None)]`

**Resolve decision.** `ambiguous`

**Reply written by code (the model did not get to continue):**

'the trustee for the anderson family trust' matches more than one entity above the threshold (0.85), and I will not pick one for you. Which did you mean?

1. **ANDERSON FAMILY TRUST** · `lei:254900ZKA4P4BM0DZ432` · QLD 4730 · trust · name_exact_norm 0.95
2. **The Trustee for The Anderson Family Trust** · `abn:26547845596` · NSW 2750 · trust · name_exact_norm 0.95

Reply with a number, or give an ABN/ACN.

**User replies `1`.**

**Tool calls.** `[('user_selected', None), ('entity', None), ('read_cypher', None)]`

**Answer.**

Based on the graph data for **ANDERSON FAMILY TRUST** (`key: lei:254900ZKA4P4BM0DZ432`):

### Licence Details
* **Licences Held:** None recorded.

---

### Entity Summary & Evidence
* **Entity Key:** `lei:254900ZKA4P4BM0DZ432`
* **Display Name:** ANDERSON FAMILY TRUST
* **Legal Name:** The Trustee for The Anderson Family Trust (`source: local:gleif-lei-au`)
* **LEI:** `254900ZKA4P4BM0DZ432`
* **Entity Type:** Trust (`active`)
* **Location:** Longreach, QLD 4730
* **Data Sources Checked:** `local:gleif-lei-au` (GLEIF LEI Register)

---

### Limitations & What Could Not Be Determined
* Having no licence recorded in this graph slice means no licence was found within the indexed sources (`local:gleif-lei-au`). It does not guarantee that the entity does not hold licences in unindexed registers or under a separate ABN entity.

---

### Suggested Follow-Up Questions
1. Does the other trust entity (**The Trustee for The Anderson Family Trust**, `abn:26547845596`) hold any licences?
2. Are there any ultimate parents or ownership relationships recorded for `lei:254900ZKA4P4BM0DZ432`?
3. Are there any banned individuals or organisations within 1-2 hops of `lei:254900ZKA4P4BM0DZ432`?

**Check.** the turn halted on the ambiguous decision with a pending clarification listing the candidates; the user's choice unlocked exactly that key (`user_selected` is first in the trace) and no re-resolve happened.

## 3. Dataset export (retriever mode): preview → confirm → export → repeat

**Request.** Give me a table of all AFS licensees in Queensland with their ABN, status and postcode

**Restatement and preview (generated from the validated spec):**

**Proposed dataset: afs_licensees_qld** - All licence holdings (one row per licence record) where licence_type = 'afs' AND state = 'QLD'. Columns: party_key, licence_id, display_name, abn, licence_status, state, postcode. Ordered by display_name (ties broken by key). At most 10000 rows.

Assumptions: Used 'QLD' as the state code for Queensland.; Filtered licence_type = 'afs'.; Did not filter on licence_status as AFS registers publish current holders and licence_status may be NULL.; Ordered by display_name and limited to 10,000 records by default.

**894 rows match**; export limit 10000, so the file will hold **894 rows**. Columns: party_key, licence_id, display_name, abn, licence_status, state, postcode. Preview shows the first 20.

Reply **yes** to export (CSV + Parquet + re-runnable spec), or tell me what to change.

**User replies `yes`.**

Exported **894 rows** to `outputs/projections/afs-licensees-qld-20261102T030217Z.csv` (and Parquet). All 894 matching rows are included. Spec saved to `outputs/projections/afs-licensees-qld-20261102T030217Z.spec.json` (data generation `43389d875af0`, as_of 2026-11-02, content hash `ae5660834394`) - re-run it on this generation for the same table.

**Files.** CSV `outputs/projections/afs-licensees-qld-20261102T030217Z.csv` · spec `outputs/projections/afs-licensees-qld-20261102T030217Z.spec.json` · content sha1 `ae5660834394` · as_of `2026-11-02` · generation `43389d875af0`

**Repeat export from the saved spec file.** content sha1 `ae5660834394` → identical; rows 894 vs 894.

First lines of the CSV:

```
party_key,licence_id,display_name,abn,licence_status,state,postcode
abn:36141812222,afs:491024,20:20 INSURANCE SERVICES PTY LTD,36141812222,,QLD,4000
abn:93680522936,afs:563434,2DM CAPITAL PTY LTD,93680522936,,QLD,4218
abn:33010805222,afs:247843,786 INTERNATIONAL (AUST) PTY. LTD.,33010805222,,QLD,4109
```

## Result

All checks passed. The calls this rehearsal made are in `outputs/usage.jsonl` (tags `agent:*`, `route:*`).
