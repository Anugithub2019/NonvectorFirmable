# Review: qld:queensland-government-contracts-directory-awarded-contracts

Queensland Government contracts directory—awarded contracts — Legacy datasets (not updated)
resource: Queensland Contracts Directory – awarded contracts [CSV]  rows: 45752  licence: Creative Commons Attribution 4.0
what it is: This dataset contains awarded Queensland Government contracts over $10,000, detailing the procurement agency, contract description, award date, value, and supplier details including name and address.
one row = one awarded government contract
entity concerns: Most suppliers are companies or trading entities, but some records represent individual sole traders or contractors.
reader: {"format": "csv", "encoding": "latin-1", "delimiter": ",", "sheet": "", "header_row": 0, "skip_rows_after_header": 0, "records_path": ""}  (inspect attempts: 2)
record id: row hash — No unique contract identifier exists in dataset; generating a deterministic row hash across all columns.
observed_at: {"column": "Date", "transforms": [{"op": "parse_datetime", "args": {"formats": ["%d/%m/%Y", "%d.%m.%Y"]}}], "note": "Contract award date used as observation timestamp."}

| target | source | transforms | when | conf | lvl | applied | fail% |
|---|---|---|---|---|---|---|---|
| entity.legal_name | Supplier Name | regex_replace({"pattern": "(?i)\\s*\\bt/a\\b.*$", "repl": ""}), collapse_whitespace, strip |  | 0.7 | L0 | 1000 | 0% |
| entity.trading_name | Supplier Name | regex_extract({"pattern": "(?i)\\bt/a\\s+(.*)", "group": 1}), collapse_whitespace, strip | Supplier Name matches ['(?i)\\bt/a\\b'] | 0.65 | L0 | 8 | 68% |
| entity.entity_type | Supplier Name | entity_type_from_name |  | 0.65 | L1 | 639 | 0% |
| address.full | Supplier Address | collapse_whitespace, strip |  | 0.85 | L0 | 996 | 0% |
| address.postcode | Supplier Address, unnamed_7, unnamed_8, unnamed_9, unnamed_10 | null_if({"values": ["n/a", "N/A"]}), au_postcode |  | 0.75 | L1 | 876 | 12% |
| address.state | Supplier Address, unnamed_7, unnamed_8, unnamed_9, unnamed_10 | null_if({"values": ["n/a", "N/A"]}), au_state |  | 0.75 | L1 | 294 | 70% |
| address.country | Supplier Address, unnamed_7, unnamed_8, unnamed_9, unnamed_10 | null_if({"values": ["n/a", "N/A"]}), constant({"value": "AU"}) | Supplier Address matches ['(?i)\\b(NSW/VIC/QLD/WA/SA/TAS/ACT/NT/New South Wales/Victoria/Queensland/Western Australia/South Australia/Tasmania/Australian Capital Territory/Northern Territory/Australia)\\b'] | 0.8 | L1 | 277 | 0% |

Unmapped (deliberately not guessed):
  - Agency Name: Represents the purchasing government agency, not the target supplier entity.
  - Agency Address: Represents purchasing agency address, not supplier address.
  - Description: Contract item description; outside entity and address ontology scope.
  - Value: Contract monetary value; outside entity and address ontology scope.

source_reliability: {'score': 0.85, 'reason': 'Official Queensland Government procurement dataset, though legacy and unmaintained.'}

Validation: NOT PASSED
  BLOCKING address.postcode: 12% of non-empty source values failed to transform, e.g. ['Unit No 703-706 7th Floor International Trade Tower Nehru Place New Delhi  110019 India', 'Consultants Pvt Limited 131-4 Horana Rd  Panadura  12500 Sri Lanka Limited Offer Process', 'Head Office 25B, 2nd Floor, AB Block Saidarjung Enclave  New Delhi  29 India Limited Offer Process']
  BLOCKING address.state: 70% of non-empty source values failed to transform, e.g. ['1700 North Moore Street Ste 2000  Arlington VA 22209 United States', 'Unit No 703-706 7th Floor International Trade Tower Nehru Place New Delhi  110019 India', 'Consultants Pvt Limited 131-4 Horana Rd  Panadura  12500 Sri Lanka Limited Offer Process']
  BLOCKING entity.trading_name: 68% of non-empty source values failed to transform, e.g. ['ELDERMONT PTY LTD  T/A', 'GAINSLEET PTY LTD T/A', 'ARBOR OPERATIONS QLD P/L T/A']

history: [{"iteration": 0, "passed": false, "n_blocking": 2, "n_warnings": 0}, {"iteration": 1, "passed": false, "n_blocking": 2, "n_warnings": 0}, {"iteration": 2, "passed": false, "n_blocking": 1, "n_warnings": 1}, {"iteration": 3, "passed": false, "n_blocking": 1, "n_warnings": 1}, {"iteration": 4, "passed": true, "n_blocking": 0, "n_warnings": 3}, {"iteration": 5, "passed": false, "n_blocking": 4, "n_warnings": 0}, {"iteration": 6, "passed": false, "n_blocking": 3, "n_warnings": 0}]
  it0 propose: initial proposal
  it1 revise: Included CSV overflow columns unnamed_7, unnamed_8, unnamed_9, and unnamed_10 in source_columns for address.full, address.state, and address.postcode, as unquoted commas in CSV rows caused city, state, and postcode values to break across these extra columns. Added null_if to strip placeholder values
  it2 revise: Added 'when' matching conditions to address.postcode and address.state to restrict extraction to records containing valid Australian postcodes and state identifiers respectively. This resolves the 12% postcode and 70% state transform failures caused by international addresses.
  it3 revise: Fixed address.full by adding regex_replace transform to remove procurement process terms (e.g. 'Limited Offer Process', 'Selective') originating from unnamed_7 column before collapsing whitespace. Fixed entity.legal_name warning by adding regex_replace and strip transforms to clean trailing hyphens 
  it4 revise: 1) Rebuilt address.full using only 'Supplier Address' to fix text duplication blocking issue. 2) Restricted address.country emission with a condition requiring an Australian state or postcode match, ensuring overseas suppliers are not wrongly mapped as AU. 3) Added mapping for entity.trading_name wh
  it5 revise: 1. Added regex_extract to entity.trading_name to extract only the trading name after 't/a'. 2. Added condition on address.full to prevent emitting full addresses when Supplier Address contains only a 4-digit postcode. 3. Formatted all transform parameters into strict JSON strings in args_json.
  it6 revise: 1. Corrected regex escaping in entity.trading_name when condition to (?i)\bt/a\b so it correctly matches 't/a' rows.
2. Removed over-restrictive when conditions on address.postcode and address.state, allowing au_postcode and au_state transforms to run cleanly across address columns.
3. Updated addre
  NOTE FOR REVIEWER: Supplier Name strings are truncated at 40 characters in this CSV source, which may impact exact legal name matching for longer corporate names.
  NOTE FOR REVIEWER: Some suppliers are based overseas (e.g. Germany, India, China). address.country is mapped to AU only when Australian address tokens are matched.
  NOTE FOR REVIEWER: address.full uses Supplier Address exclusively to prevent duplicate text concatenation from unlabelled trailing CSV columns.

Examples (unseen rows):
  RAW    {"Agency Name": "Arts Queensland", "Agency Address": "Level 1, State Library of Queensland, Stanley Plac", "Description": " CI606 SLQ Replace sign above Level 5", "Date": "25/01/2019", "Value": "12039.75", "Supplier Name": "HONEYWELL LIMITED", "Supplier Address": "19 Corporate Dr, Cannon Hill    QLD   4170"}
  CLAIMS [('entity.legal_name', 'HONEYWELL LIMITED'), ('entity.entity_type', 'company'), ('address.full', '19 Corporate Dr, Cannon Hill QLD 4170'), ('address.postcode', '4170'), ('address.state', 'QLD'), ('address.country', 'AU')]
  RAW    {"Agency Name": "Arts Queensland", "Agency Address": "Level 1, State Library of Queensland, Stanley Plac", "Description": "CB301 QCC Fire Suppression DOCS", "Date": "26/02/2019", "Value": "39930", "Supplier Name": "GHD PTY LTD", "Supplier Address": "GPO BOX 668, BRISBANE    QLD   4001"}
  CLAIMS [('entity.legal_name', 'GHD PTY LTD'), ('entity.entity_type', 'company'), ('address.full', 'GPO BOX 668, BRISBANE QLD 4001'), ('address.postcode', '4001'), ('address.state', 'QLD'), ('address.country', 'AU')]
  RAW    {"Agency Name": "Central Queensland University", "Agency Address": "Bruce Highway, Rockhampton North,  QLD, 4701", "Description": "Bachelor of Nursing - Clinical Placement", "Date": "07/01/2019", "Value": "30030", "Supplier Name": "CENTRAL QUEENSLAND HOSPITAL & HEALTH SER", "Supplier Address": "District Finance - Central  QLD H&HS Reference 301"}
  CLAIMS [('entity.legal_name', 'CENTRAL QUEENSLAND HOSPITAL & HEALTH SER'), ('address.full', 'District Finance - Central QLD H&HS Reference 3010 Central QLD Health Service District PO Box 871 Rockhampton QLD 4700 Australia'), ('address.postcode', '4700'), ('address.state', 'QLD'), ('address.country', 'AU')]

agent cost so far: $0.6756 over 24 steps; paused at: ('review',)