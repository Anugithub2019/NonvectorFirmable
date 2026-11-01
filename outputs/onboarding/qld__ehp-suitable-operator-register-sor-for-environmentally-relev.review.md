# Review: qld:ehp-suitable-operator-register-sor-for-environmentally-relevant-activities-eras

Suitable Operator Register (SOR) for Environmentally Relevant Activities (ERAs) — Environment, Tourism, Science and Innovation
resource: Suitable Operator Register (SOR) for Environmentally Relevant Activities (ERAs) [XLSX]  rows: 15128  licence: Creative Commons Attribution 4.0
what it is: This file contains the Suitable Operator Register (SOR) for Environmentally Relevant Activities (ERAs) from Queensland's Department of Environment, Tourism, Science and Innovation. It lists registered entities authorised to perform environmentally relevant activities under the Environmental Protection Act 1994, along with entity details, ACN/business numbers, registration dates, RSO numbers, status, and locations.
one row = One registered suitable operator record in Queensland.
entity concerns: Includes corporations with ACNs alongside potential non-corporate entities or individuals depending on the Entity Type field.
reader: {"format": "xlsx", "encoding": "utf-8-sig", "delimiter": ",", "sheet": "Registered Suitable Operators", "header_row": 0, "skip_rows_after_header": 0, "records_path": ""}  (inspect attempts: 1)
record id: ['RSO Number'] — RSO Number is the unique registration identifier assigned to each suitable operator in the Queensland register.
observed_at: {"fixed": null, "note": "Observation date not available per record; dataset last modified 2026-10-16."}

| target | source | transforms | when | conf | lvl | applied | fail% |
|---|---|---|---|---|---|---|---|
| entity.legal_name | Customer Name | collapse_whitespace, strip |  | 0.95 | L1 | 1000 | 0% |
| entity.entity_type | Entity Type | map_values({"mapping": {"Corporation (Company)": "company", "An individ) |  | 0.95 | L1 | 1000 | 0% |
| entity.acn | Business Number | acn | Business Number matches ['(?i)ACN'] | 0.95 | L1 | 532 | 2% |
| entity.abn | Business Number | abn | Business Number matches ['(?i)ABN'] | 0.95 | L1 | 25 | 0% |
| entity.status | Registration Status | map_values({"mapping": {"Registered": "active"}, "default": "unknown"}) |  | 0.95 | L1 | 1000 | 0% |
| entity.date_registered | Registration Date | parse_date({"formats": ["%Y-%m-%d %H:%M:%S"]}) |  | 0.95 | L1 | 1000 | 0% |
| address.full | Location | collapse_whitespace, strip |  | 0.9 | L0 | 1000 | 0% |
| address.locality | Location | pick_part({"sep": ",", "index": 0}), title_case, strip |  | 0.9 | L1 | 1000 | 0% |
| address.state | Location | au_state |  | 0.95 | L1 | 998 | 0% |
| address.postcode | Location | au_postcode |  | 0.95 | L1 | 1000 | 0% |
| address.country |  | constant({"value": "AU"}) |  | 1.0 | L0 | 1000 | 0% |

Unmapped (deliberately not guessed):

source_reliability: {'score': 0.95, 'reason': 'Official Queensland Government Department of Environment, Tourism, Science and Innovation statutory register.'}

Validation: PASSED
  warning  [critic] entity.abn: In row 8, 'Business Number' contains 'ACN 14631562957', which is an 11-digit Australian Business Number (ABN) incorrectly prefixed with 'ACN'. Because the condition strictly checks for the presence of 'ACN', it routes to entity.acn and gets dropped during transform validation, losing the business identifier. -> Update the condition or transform logic for ABN/ACN extraction to fall back to digit length (11 digits for ABN vs 9 digits for ACN) rather than relying solely on the text prefix.
critic: Mappings accurately extract entity legal names, entity types, registration statuses, dates, and full address components across most rows. However, relying strictly on the string 'ACN' vs 'ABN' in the Business Number column causes 11-digit ABNs mislabeled as ACNs to fail validation and be dropped entirely.

history: [{"iteration": 0, "passed": false, "n_blocking": 1, "n_warnings": 1}, {"iteration": 1, "passed": true, "n_blocking": 0, "n_warnings": 1}, {"iteration": 2, "passed": false, "n_blocking": 1, "n_warnings": 1}, {"iteration": 3, "passed": true, "n_blocking": 0, "n_warnings": 1}]
  it0 propose: initial proposal
  it1 revise: Added 'when' conditions to entity.abn and entity.acn field mappings so that Business Number is only evaluated against 'ABN' or 'ACN' respectively. This eliminates the 95% transform failure rate on entity.abn and resolves warnings on entity.acn. Formatted all transform parameters using args_json.
  it2 revise: Mapped all 11 values of Entity Type (adding Local/State/Federal Government, Government Owned Corporation to government; Australian Registered Foreign Body to company; Co-operative, Body Corporate, Indigenous Corporation to other) per reviewer feedback. Removed 'when' clause on ABN and ACN transforms
  it3 revise: Added 'when' condition on entity.abn (matches (?i)ABN) and entity.acn (matches (?i)ACN) for Business Number column to eliminate false transform failures when a row contains the other number type.
  NOTE FOR REVIEWER: Added when condition to entity.abn and entity.acn to evaluate only rows matching ABN/ACN keywords, resolving the 95% transform failure rate.

Examples (unseen rows):
  RAW    {"Entity Type": "Corporation (Company)", "Customer Name": "1873 CO PTY LTD", "Business Number": "ACN 601079949", "Registration Date": "2014-08-20 00:00:00", "RSO Number": "729864", "Registration Status": "Registered", "Location": "BROMELTON, QLD, 4285"}
  CLAIMS [('entity.legal_name', '1873 CO PTY LTD'), ('entity.entity_type', 'company'), ('entity.acn', '601079949'), ('entity.status', 'active'), ('entity.date_registered', '2014-08-20'), ('address.full', 'BROMELTON, QLD, 4285'), ('address.locality', 'Bromelton'), ('address.state', 'QLD'), ('address.postcode', '4285'), ('address.country', 'AU')]
  RAW    {"Entity Type": "Corporation (Company)", "Customer Name": "A ONE GROUP AUSTRALIA PTY LTD", "Business Number": "ACN 134535210", "Registration Date": "2014-08-22 00:00:00", "RSO Number": "729966", "Registration Status": "Registered", "Location": "FORESTDALE, QLD, 4118"}
  CLAIMS [('entity.legal_name', 'A ONE GROUP AUSTRALIA PTY LTD'), ('entity.entity_type', 'company'), ('entity.acn', '134535210'), ('entity.status', 'active'), ('entity.date_registered', '2014-08-22'), ('address.full', 'FORESTDALE, QLD, 4118'), ('address.locality', 'Forestdale'), ('address.state', 'QLD'), ('address.postcode', '4118'), ('address.country', 'AU')]
  RAW    {"Entity Type": "An individual or Sole trader", "Customer Name": "A Sheahan", "Registration Date": "2013-03-26 00:00:00", "RSO Number": "703148", "Registration Status": "Registered", "Location": "WOODSTOCK, QLD, 4816"}
  CLAIMS [('entity.legal_name', 'A Sheahan'), ('entity.entity_type', 'sole_trader'), ('entity.status', 'active'), ('entity.date_registered', '2013-03-26'), ('address.full', 'WOODSTOCK, QLD, 4816'), ('address.locality', 'Woodstock'), ('address.state', 'QLD'), ('address.postcode', '4816'), ('address.country', 'AU')]

agent cost so far: $0.3543 over 14 steps; paused at: ('review',)