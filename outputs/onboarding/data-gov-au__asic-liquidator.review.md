# Review: data.gov.au:asic-liquidator

ASIC - Liquidator Dataset — Australian Securities and Investments Commission (ASIC)
resource: Liquidator Dataset - Current [CSV]  rows: 662  licence: Creative Commons Attribution 3.0 Australia
what it is: This dataset contains the register of current registered liquidators maintained by the Australian Securities and Investments Commission (ASIC). It includes details such as liquidator registration numbers, liquidator names, registration start dates, status, location address details, and associated firm names.
one row = One registered liquidator individual
entity concerns: Records represent individual practitioners (registered liquidators) rather than business entities, although employer/firm names are listed as text attributes.
reader: {"format": "csv", "encoding": "utf-8-sig", "delimiter": ",", "sheet": "", "header_row": 0, "skip_rows_after_header": 0, "records_path": ""}  (inspect attempts: 1)
record id: ['LIQ_NUM'] — LIQ_NUM is the unique liquidator registration number assigned by ASIC.
observed_at: {"fixed": null, "note": "Not available from record."}

| target | source | transforms | when | conf | lvl | applied | fail% |
|---|---|---|---|---|---|---|---|
| person.full_name | LIQ_NAME | collapse_whitespace |  | 0.9 | L0 | 362 | 0% |
| person.registration_number | LIQ_NUM | collapse_whitespace |  | 0.93 | L1 | 362 | 0% |
| person.role | REGISTER_NAME | map_values({"mapping": {"Liquidator": "liquidator"}, "default": "unknow) |  | 0.19 | L1 | 362 | 0% |
| licence.licence_number | LIQ_NUM | collapse_whitespace |  | 0.94 | L1 | 362 | 0% |
| licence.licence_type | REGISTER_NAME | map_values({"mapping": {"Liquidator": "other"}, "default": "other"}) |  | 0.56 | L1 | 362 | 0% |
| licence.status | LIQ_STATUS | map_values({"mapping": {"APPR": "current"}, "default": "unknown"}) |  | 0.56 | L1 | 362 | 0% |
| licence.start_date | LIQ_START_DT | parse_date({"formats": ["%d/%m/%Y"]}) |  | 0.96 | L1 | 362 | 0% |
| address.locality | LIQ_ADD_LOCAL | title_case |  | 0.97 | L1 | 361 | 0% |
| address.state | LIQ_ADD_STATE | au_state |  | 0.96 | L1 | 361 | 0% |
| address.postcode | LIQ_ADD_PCODE | au_postcode |  | 0.96 | L1 | 361 | 0% |
| address.country | LIQ_ADD_COUNTRY | map_values({"mapping": {"Australia": "AU", "International": "OTHER"}, ") |  | 0.86 | L1 | 362 | 0% |
| related_party.name | LIQ_FIRM | collapse_whitespace | LIQ_FIRM not_empty [] | 0.79 | L0 | 279 | 0% |
| related_party.relationship | LIQ_FIRM | constant({"value": "employs"}) | LIQ_FIRM not_empty [] | 0.38 | L1 | 279 | 0% |

Unmapped (deliberately not guessed):
  - OFF_LIQ_NUM: Official liquidator registration number present for a minority of rows; no distinct official liquidator registration field in canonical ontology.
  - OFF_LIQ_START_DT: Start date for official liquidator designation; no distinct canonical field available.
  - LIQ_SUSP_DT: Suspension date column contains no values (0% fill rate).

source_reliability: {'score': 0.95, 'reason': "ASIC is Australia's corporate regulator and official registrar for liquidators."}

Validation: PASSED
  warning  362 of 362 kept records produced no identifying claim
  warning  [critic] licence.licence_type: The REGISTER_NAME value 'Liquidator' is mapped to 'other', which loses the specific licence type information. -> Map 'Liquidator' to 'liquidator' instead of 'other'.
  warning  [critic] person.full_name: Person names are emitted in raw inverted uppercase format ('SURNAME, GIVEN NAMES', e.g., 'ELKERTON, ANTHONY WAYNE') rather than standard name order and casing. -> Reorder name components to 'FIRST LAST' format and apply title casing.
  warning  [critic] related_party.relationship: The relationship is mapped to the verb 'employs' for the firm, whereas 'employer' correctly describes the firm's relationship to the registered individual. -> Change the constant relationship value from 'employs' to 'employer'.
  warning  [jev] person.role: P(mapping correct) = 0.19 - reviewer should look
  warning  [jev] licence.licence_type: P(mapping correct) = 0.56 - reviewer should look
  warning  [jev] licence.status: P(mapping correct) = 0.56 - reviewer should look
  warning  [jev] related_party.relationship: P(mapping correct) = 0.38 - reviewer should look
critic: The mapping successfully captures core liquidator details, but maps licence.licence_type to a generic 'other' category, leaves person full names in raw inverted uppercase format, and uses 'employs' instead of 'employer' for the firm relationship.

history: [{"iteration": 0, "passed": false, "n_blocking": 5, "n_warnings": 7}, {"iteration": 1, "passed": false, "n_blocking": 1, "n_warnings": 0}, {"iteration": 2, "passed": false, "n_blocking": 1, "n_warnings": 7}, {"iteration": 3, "passed": false, "n_blocking": 1, "n_warnings": 5}, {"iteration": 4, "passed": false, "n_blocking": 1, "n_warnings": 5}, {"iteration": 5, "passed": true, "n_blocking": 0, "n_warnings": 8}]
  it0 propose: initial proposal
  it1 revise: Added explicit map_values and au_state transforms across entity.status, person.role, licence.licence_type, licence.status, address.country, and related_party.relationship to convert raw source codes to valid canonical ontology enum values.
  it2 revise: Replaced invalid map_values usage on related_party.relationship with the constant transform specifying value 'member_of'.
  it3 revise: Removed mappings to entity.legal_name and entity.status to avoid misclassifying individual practitioners as corporate entities. Added 'not_empty' condition on LIQ_FIRM for related_party fields so incomplete relationship claims are not emitted for independent practitioners.
  it4 revise: 1. Applied constant transform 'member_of' to related_party.relationship to ensure outputs match the canonical enum rather than passing raw text firm names. 2. Added mapping for entity.legal_name from LIQ_NAME in compliance with Rule 9a, resolving the warning regarding records producing no identifyin
  it5 revise: Removed entity.legal_name mapping per human reviewer request. Configured constant transform with 'employs' for related_party.relationship.
  NOTE FOR REVIEWER: Removed mapping to entity.legal_name as requested by human reviewer feedback, as these records represent natural persons.
  NOTE FOR REVIEWER: Fixed related_party.relationship transform to properly use constant 'employs' with args_json.

Examples (unseen rows):
  RAW    {"REGISTER_NAME": "Liquidator", "LIQ_NUM": "423914", "LIQ_NAME": "ABEYRATNE, JEREMY ROBERT", "LIQ_START_DT": "14/08/2012", "LIQ_STATUS": "APPR", "LIQ_ADD_LOCAL": "SOUTH MELBOURNE", "LIQ_ADD_STATE": "VIC", "LIQ_ADD_PCODE": "3205", "LIQ_ADD_COUNTRY": "Australia"}
  CLAIMS [('person.full_name', 'ABEYRATNE, JEREMY ROBERT'), ('person.registration_number', '423914'), ('person.role', 'liquidator'), ('licence.licence_number', '423914'), ('licence.licence_type', 'other'), ('licence.status', 'current'), ('licence.start_date', '2012-08-14'), ('address.locality', 'South Melbourne'), ('address.state', 'VIC'), ('address.postcode', '3205'), ('address.country', 'AU')]
  RAW    {"REGISTER_NAME": "Liquidator", "LIQ_NUM": "548548", "LIQ_NAME": "AGOSTINO, ANNA", "LIQ_START_DT": "30/06/2023", "LIQ_STATUS": "APPR", "LIQ_ADD_LOCAL": "ADELAIDE", "LIQ_ADD_STATE": "SA", "LIQ_ADD_PCODE": "5000", "LIQ_ADD_COUNTRY": "Australia", "LIQ_FIRM": "CH ADVISORY PTY LTD"}
  CLAIMS [('person.full_name', 'AGOSTINO, ANNA'), ('person.registration_number', '548548'), ('person.role', 'liquidator'), ('licence.licence_number', '548548'), ('licence.licence_type', 'other'), ('licence.status', 'current'), ('licence.start_date', '2023-06-30'), ('address.locality', 'Adelaide'), ('address.state', 'SA'), ('address.postcode', '5000'), ('address.country', 'AU'), ('related_party.name', 'CH ADVISORY PTY LTD'), ('related_party.relationship', 'employs')]
  RAW    {"REGISTER_NAME": "Liquidator", "LIQ_NUM": "190669", "LIQ_NAME": "ALBARRAN, RICHARD", "LIQ_START_DT": "19/08/1999", "LIQ_STATUS": "APPR", "LIQ_ADD_LOCAL": "SYDNEY", "LIQ_ADD_STATE": "NSW", "LIQ_ADD_PCODE": "2000", "LIQ_ADD_COUNTRY": "Australia", "LIQ_FIRM": "HALL CHADWICK"}
  CLAIMS [('person.full_name', 'ALBARRAN, RICHARD'), ('person.registration_number', '190669'), ('person.role', 'liquidator'), ('licence.licence_number', '190669'), ('licence.licence_type', 'other'), ('licence.status', 'current'), ('licence.start_date', '1999-08-19'), ('address.locality', 'Sydney'), ('address.state', 'NSW'), ('address.postcode', '2000'), ('address.country', 'AU'), ('related_party.name', 'HALL CHADWICK'), ('related_party.relationship', 'employs')]

agent cost so far: $0.4857 over 19 steps; paused at: ('review',)