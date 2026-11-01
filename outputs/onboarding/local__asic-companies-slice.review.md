# Review: local:asic-companies-slice

ASIC Company Dataset (sliced) — Australian Securities and Investments Commission (ASIC)
resource: asic_companies_slice.csv [CSV]  rows: 80188  licence: Creative Commons Attribution 3.0 Australia
what it is: This dataset contains a sliced snapshot of the Australian Securities and Investments Commission (ASIC) company register, providing corporate registration details such as ACN, ABN, company status, type, class, and name history (current vs former names).
one row = one company name record (either current name or a former name) associated with an Australian Company Number (ACN)
entity concerns: Multiple rows can represent the same business entity (ACN) over time across its name history; all entities listed are corporate entities registered with ASIC.
reader: {"format": "csv", "encoding": "utf-8-sig", "delimiter": ",", "sheet": "", "header_row": 0, "skip_rows_after_header": 0, "records_path": ""}  (inspect attempts: 1)
record id: ['ACN', 'Company Name'] — Combination of ACN and Company Name uniquely identifies each company name record (current or former name entry).
observed_at: {"fixed": null, "note": "Not available in raw records; populated at ingest time from dataset snapshot metadata."}

| target | source | transforms | when | conf | lvl | applied | fail% |
|---|---|---|---|---|---|---|---|
| entity.legal_name | Company Name |  | Current Name Indicator equals ['Y'] | 0.92 | L1 | 1000 | 0% |
| entity.legal_name | Current Name |  | Current Name Indicator not_in ['Y']; Current Name not_empty [] | 0.89 | L1 | 1000 | 0% |
| entity.former_name | Company Name |  | Current Name Indicator not_in ['Y'] | 0.41 | L1 | 222 | 0% |
| entity.acn | ACN | acn |  | 0.97 | L1 | 1000 | 0% |
| entity.abn | ABN | null_if({"values": ["0"]}), abn |  | 0.81 | L1 | 983 | 2% |
| entity.entity_type | Type | map_values({"mapping": {"APTY": "company", "APUB": "company"}, "default) |  | 0.79 | L1 | 1000 | 0% |
| entity.status | Status | map_values({"mapping": {"REGD": "active", "DRGD": "deregistered", "SOFF) |  | 0.87 | L1 | 1000 | 0% |
| entity.date_registered | Date of Registration | parse_date({"formats": ["%d/%m/%Y"]}) |  | 0.98 | L1 | 1000 | 0% |

Unmapped (deliberately not guessed):
  - Class: ASIC internal legal class (e.g. LMSH = Limited by Shares); no direct field in ontology.
  - Sub Class: ASIC internal sub-class classification (e.g. PROP = Proprietary, ULST = Unlisted); no direct field in ontology.
  - Previous State of Registration: Historical pre-1991 state of registration; no direct field in ontology.
  - State Registration number: Historical state-level registration number superseded by ACN; no direct field in ontology.
  - Modified since last report: Internal ASIC diff indicator; entirely blank in data.
  - Current Name Start Date: Date when current name became effective for former name rows; no entity attribute for name start date in schema.

source_reliability: {'score': 0.98, 'reason': 'Official statutory corporate registry published by ASIC.'}

Validation: PASSED
  warning  [jev] entity.former_name: P(mapping correct) = 0.41 - reviewer should look
critic: No semantic issues found in the mapping configuration or extracted claims.

history: [{"iteration": 0, "passed": true, "n_blocking": 0, "n_warnings": 1}]
  it0 propose: initial proposal
  NOTE FOR REVIEWER: Rows with blank 'Current Name Indicator' represent historical/former names for an ACN.
  NOTE FOR REVIEWER: The dataset uses 'Company Name' as current legal name when 'Current Name Indicator' is 'Y', and as former name when blank.

Examples (unseen rows):
  RAW    {"Company Name": "WAKATAPU PTY LTD", "ACN": "102860604", "Type": "APTY", "Class": "LMSH", "Sub Class": "PROP", "Status": "REGD", "Date of Registration": "18/11/2002", "Current Name Indicator": "Y", "ABN": "45102860604"}
  CLAIMS [('entity.legal_name', 'WAKATAPU PTY LTD'), ('entity.acn', '102860604'), ('entity.abn', '45102860604'), ('entity.entity_type', 'company'), ('entity.status', 'active'), ('entity.date_registered', '2002-11-18')]
  RAW    {"Company Name": "SMR (QLD) PTY LTD", "ACN": "102887472", "Type": "APTY", "Class": "LMSH", "Sub Class": "PROP", "Status": "REGD", "Date of Registration": "20/11/2002", "Current Name Indicator": "Y", "ABN": "59102887472"}
  CLAIMS [('entity.legal_name', 'SMR (QLD) PTY LTD'), ('entity.acn', '102887472'), ('entity.abn', '59102887472'), ('entity.entity_type', 'company'), ('entity.status', 'active'), ('entity.date_registered', '2002-11-20')]
  RAW    {"Company Name": "COLLECT SUCCESS PTY LTD", "ACN": "103450791", "Type": "APTY", "Class": "LMSH", "Sub Class": "PROP", "Status": "REGD", "Date of Registration": "21/01/2003", "Current Name Indicator": "Y", "ABN": "63103450791"}
  CLAIMS [('entity.legal_name', 'COLLECT SUCCESS PTY LTD'), ('entity.acn', '103450791'), ('entity.abn', '63103450791'), ('entity.entity_type', 'company'), ('entity.status', 'active'), ('entity.date_registered', '2003-01-21')]

agent cost so far: $0.1071 over 7 steps; paused at: ('review',)