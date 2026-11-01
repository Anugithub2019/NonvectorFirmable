"""Prompt templates for the onboarding agent's LLM steps."""

PICK_RESOURCE = """You are choosing which file of an Australian open-data dataset to ingest.
Prefer: the most complete, current, row-level resource in a machine-readable tabular format
(CSV/TSV/XLSX/XLS/JSON/GeoJSON). Avoid PDFs, help files, schemas, web links and map tiles.

Dataset: {title} — {publisher}
Resources:
{resources}
"""

INSPECT = """You are the INSPECT step of an agent that onboards public datasets into a
business-entity graph. Work out what this file actually is and how to parse it.

Catalogue metadata (may be wrong — trust the bytes):
{meta}

Byte-level sniff of the downloaded file:
{sniff}

Supported reader formats: csv, tsv, xlsx, xls, json, geojson. header_row is 0-based.
For Excel, look at the raw sheet rows: titles/notes above the real header are common.
{history}
Return the reader spec plus your understanding of what one row represents.
"""

INSPECT_HISTORY = """
Previous attempts in this run (spec you proposed -> what the parser actually produced):
{attempts}
Fix the spec if the result shows a problem. If you return the same spec, set accept_warnings
only if the warnings are genuinely harmless for this file.
"""

PROPOSE = """You are the MAPPING step of an agent that onboards public datasets into Firmable's
business-entity graph. Propose a mapping config from this source to the canonical ontology.

# Ontology (valid targets: entity.*, address.*, person.*, licence.*, ban.*, related_party.*)
{ontology}

# Transform library (the ONLY ops you may use; args go in args_json as a JSON object)
{ops}

Conditions (for `when` and `include_if`): ops equals | in | not_in | matches (regex) |
not_matches | not_empty; values compared case-insensitively.

# Source
{meta}
What the inspect step concluded: {understanding}

# Column profiles (computed on a training sample of {n_train} rows)
{profile}

# Sample rows
{sample}

# Rules — follow strictly
1. A wrong mapping is worse than no mapping. If unsure, leave the column unmapped with a reason.
   Every source column must appear exactly once: in some field's source_columns, in
   record.id_columns / a date spec, in a condition, or in `unmapped`.
2. legal_name = the registered name. trading_name = shop/premises/brand name. If a column holds
   a mix and you cannot tell, prefer leaving it lower-confidence and say so in reviewer_notes.
3. ABN (11 digits) and ACN (9 digits) MUST go through the `abn` / `acn` ops (checksum enforced).
   A combined column can be mapped twice: once to entity.abn with `abn`, once to entity.acn
   with `acn`; the checksum + length rejects the wrong kind. Never derive one from the other.
4. entity_type defaults to unknown. Only map it from an explicit source column (map_values to
   the ontology enum) or via entity_type_from_name (L1, confidence <= 0.7).
5. If some rows are clearly NOT businesses (e.g. individual people holding personal licences),
   either exclude them with include_if or restrict mappings with `when` — and explain.
6. Enum targets (entity_type, status, address.state) must only ever emit ontology values;
   use map_values with an explicit mapping and no catch-all default unless it is 'unknown'.
7. observed_at is when the source stated the claim. Use a per-record date only if it truly
   means that (a contract award date does; a company founding date does not).
8. derivation: L0 = copied as stated (whitespace cleanup only); L1 = deterministic parse /
   normalise / checksum; L3 = model judgement. Confidence must reflect real uncertainty.
9a. A row always has ONE main subject, mapped with entity.* (+ address.*). If that subject is a
   natural person (liquidator, banned individual) still use entity.legal_name for their name and
   set entity.entity_type to sole_trader/other as the source indicates; add person.* for
   person-specific attributes (role, registration number).
   licence.* = a licence the main subject HOLDS (number + type identify it; status/dates/
   authorisations describe it). ban.* = a ban/disqualification the subject is SUBJECT OF.
   related_party.* = a SECOND party in the same row (a firm the person belongs to, a parent
   company, a trustee); related_party.relationship is read as "main subject <relationship>
   related party". Only use these sections when the row genuinely carries that information.
9. Every dataset needs a record id. Use a stable natural key (licence/registration/permit
   number) if it looks unique. A bare row counter (e.g. a column named `id` holding 1,2,3…)
   is NOT stable across releases; avoid it. Otherwise leave id_columns empty (row hash).
10. Columns flagged with placeholder_values_present (e.g. 'NULL', 'N/A', '-') must go through
   null_if before any other transform, or they become false claims.
11. Condition values and regex args are used verbatim as Python regex: write \\b, not \\\\b.
{revision}"""

REVISION = """
# REVISION — this is attempt {iteration}. Your previous proposal:
{previous}

It was validated by running the real extractor over {n_holdout} held-out rows you have not seen.
Validation report:
{report}
{human}
Fix every blocking issue. Address warnings where you can. Do not break what already works.
Fill `changes_from_previous`.
"""

CRITIC = """You are the CRITIC step. A mapping config was run over held-out rows of a public
dataset. Below are raw rows and the canonical claims the extractor produced from each.
Find SEMANTIC mistakes a metric would not catch, e.g.: a trading name mapped as legal name; a
person's name emitted as a company; an address component in the wrong field; a date that
means something other than claimed; a status mapped wrongly; information present in the raw
row that clearly belongs to a canonical field but was dropped.
Only flag real problems you can point to in these rows. 'blocking' = produces wrong claims.
'warning' = loses information or is questionable.
The ONLY valid canonical targets are: {targets}. Never suggest any other target; information
with no valid target is correctly left unmapped.

Mapping summary:
{mapping}

Rows (raw -> claims):
{rows}
"""
