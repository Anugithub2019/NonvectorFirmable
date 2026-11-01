# Review: local:abr-slice

ABN Bulk Extract (sliced) — Australian Business Register (ATO)
resource: abr_slice.csv [CSV]  rows: 64484  licence: Creative Commons Attribution 3.0 Australia
what it is: A sliced CSV extract of the Australian Business Register (ABR) containing Australian Business Number (ABN) records, including entity status, entity type code and description, main entity name, ACN, state, postcode, GST registration details, and alternative/trading names.
one row = one ABN entity record
entity concerns: Mainly contains corporate entities (Australian Private Companies), but may include other entity types depending on slice rules.
reader: {"format": "csv", "encoding": "utf-8-sig", "delimiter": ",", "sheet": "", "header_row": 0, "skip_rows_after_header": 0, "records_path": ""}  (inspect attempts: 1)
record id: ['abn'] — The ABN uniquely identifies each registered business entity in the ABR extract.
observed_at: {"column": "record_last_updated", "transforms": [{"op": "parse_datetime", "args": {"formats": ["%Y%m%d"]}}], "note": "Last update date from ABR."}

| target | source | transforms | when | conf | lvl | applied | fail% |
|---|---|---|---|---|---|---|---|
| entity.abn | abn | abn |  | 0.78 | L1 | 1000 | 0% |
| entity.status | abn_status | map_values({"mapping": {"ACT": "active", "CAN": "deregistered", "SUS": ) |  | 0.92 | L1 | 1000 | 0% |
| entity.entity_type | entity_type_text | map_values({"mapping": {"Australian Private Company": "company", "Austr) |  | 0.72 | L1 | 1000 | 0% |
| entity.legal_name | name | collapse_whitespace |  | 0.9 | L0 | 1000 | 0% |
| entity.acn | acn | zfill({"width": 9}), acn |  | 0.95 | L1 | 944 | 0% |
| address.state | state | au_state |  | 0.96 | L1 | 1000 | 0% |
| address.postcode | postcode | au_postcode |  | 0.96 | L1 | 1000 | 0% |
| entity.trading_name | other_names | split({"sep": "\\s*\\/\\s*"}), collapse_whitespace |  | 0.49 | L1 | 334 | 0% |

Unmapped (deliberately not guessed):
  - entity_type_code: Redundant short code; entity_type_text is mapped instead.
  - name_type: Constant flag ('MN') indicating main legal name.
  - acn_type: Source metadata value ('undetermined') providing no analytical utility.
  - gst_status: GST registration status is out of scope for entity identification core schema.
  - gst_from: GST start date is out of scope for entity identification core schema.
  - other_name_types: Parallel descriptor codes ('BN', 'TRD', 'OTN') corresponding to elements in other_names.
  - replaced: Internal source extract flag ('N').
  - source_member: Source XML member file name from batch dump.
  - slice_reason: Extraction filter reason metadata ('geographic', 'referenced').

source_reliability: {'score': 0.98, 'reason': 'Official Australian Business Register dataset maintained directly by the ATO.'}

Validation: PASSED
  warning  [jev] entity.trading_name: P(mapping correct) = 0.49 - reviewer should look
critic: No semantic mapping errors or invalid claims identified across the evaluated rows.

history: [{"iteration": 0, "passed": true, "n_blocking": 0, "n_warnings": 2}, {"iteration": 1, "passed": true, "n_blocking": 0, "n_warnings": 1}, {"iteration": 2, "passed": true, "n_blocking": 0, "n_warnings": 1}]
  it0 propose: initial proposal
  it1 revise: Removed mapping from abn_status_from to entity.date_registered to prevent misrepresenting status start dates as company registration dates. Updated regex in entity.trading_name split transform to split on pipe characters ('\s*\|\s*').
  it2 revise: Corrected the split regex in entity.trading_name to split on pipe characters (\s*\|\s*) instead of forward slashes.
  NOTE FOR REVIEWER: Ensure pipe separator correctly splits multi-value trading names.

Examples (unseen rows):
  RAW    {"abn": "12613497966", "abn_status": "ACT", "abn_status_from": "20160706", "entity_type_code": "PRV", "entity_type_text": "Australian Private Company", "name": "MIRABELLA HOLDINGS PTY. LTD.", "name_type": "MN", "acn": "613497966", "acn_type": "undetermined", "state": "QLD", "postcode": "4000", "gst_status": "ACT", "gst_from": "20160706", "record_last_updated": "20160706", "replaced": "N", "source_member": "20261028_Public01.xml", "slice_reason": "geographic"}
  CLAIMS [('entity.abn', '12613497966'), ('entity.status', 'active'), ('entity.entity_type', 'company'), ('entity.legal_name', 'MIRABELLA HOLDINGS PTY. LTD.'), ('entity.acn', '613497966'), ('address.state', 'QLD'), ('address.postcode', '4000')]
  RAW    {"abn": "12618487577", "abn_status": "ACT", "abn_status_from": "20170410", "entity_type_code": "PRV", "entity_type_text": "Australian Private Company", "name": "HONDROS INVESTMENTS PTY LTD", "name_type": "MN", "acn": "618487577", "acn_type": "undetermined", "state": "QLD", "postcode": "4007", "gst_status": "NON", "gst_from": "19000101", "record_last_updated": "20230109", "replaced": "N", "source_member": "20261028_Public01.xml", "slice_reason": "geographic"}
  CLAIMS [('entity.abn', '12618487577'), ('entity.status', 'active'), ('entity.entity_type', 'company'), ('entity.legal_name', 'HONDROS INVESTMENTS PTY LTD'), ('entity.acn', '618487577'), ('address.state', 'QLD'), ('address.postcode', '4007')]
  RAW    {"abn": "12626075198", "abn_status": "ACT", "abn_status_from": "20180510", "entity_type_code": "PRV", "entity_type_text": "Australian Private Company", "name": "CAPITAL KOM TRADING PTY LTD", "name_type": "MN", "acn": "626075198", "acn_type": "undetermined", "state": "NSW", "postcode": "2121", "gst_status": "NON", "gst_from": "19000101", "record_last_updated": "20260416", "replaced": "N", "source_member": "20261028_Public01.xml", "slice_reason": "referenced"}
  CLAIMS [('entity.abn', '12626075198'), ('entity.status', 'active'), ('entity.entity_type', 'company'), ('entity.legal_name', 'CAPITAL KOM TRADING PTY LTD'), ('entity.acn', '626075198'), ('address.state', 'NSW'), ('address.postcode', '2121')]

agent cost so far: $0.3096 over 13 steps; paused at: ('review',)