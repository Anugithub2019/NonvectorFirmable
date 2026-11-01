# Review: nsw:liquor-licence-premises-list-as-at-8-feb-2021

Liquor licence premises list as at 8 Feb 2021 — Department of Customer Service
resource: Premises list (as at 8 February 2021) [CSV]  rows: 18747  licence: Creative Commons Attribution
what it is: This file contains a list of active liquor licensed premises in New South Wales as of February 2021, published by the Department of Customer Service / Liquor & Gaming NSW. It includes licence numbers, premises names, trading statuses, addresses, geographic coordinates, licensee names, business types, and gaming/trading authorizations.
one row = One row represents a single liquor licence assigned to a specific premises and licensee.
entity concerns: Licensee entities include both corporate entities (e.g. Ltd companies, incorporated clubs) and individual natural persons.
reader: {"format": "csv", "encoding": "cp1252", "delimiter": ",", "sheet": "", "header_row": 0, "skip_rows_after_header": 0, "records_path": ""}  (inspect attempts: 1)
record id: ['Licence number'] — Licence number is a stable, unique primary identifier for liquor licence records issued by NSW Liquor & Gaming.
observed_at: {"fixed": null, "note": "Observed at publication date of dataset (2021-02-08)."}

| target | source | transforms | when | conf | lvl | applied | fail% |
|---|---|---|---|---|---|---|---|
| entity.legal_name | Licensee | collapse_whitespace | Licensee matches ['(?i)\\b(PTY/LTD/LIMITED/INC/INCORPORATED/CO-?OP/CO-?OPERATIVE/CO OPERATIVE/ASSOCIATION/CLUB/TRUST)\\b'] | 0.95 | L0 | 350 | 0% |
| entity.trading_name | Licence name | collapse_whitespace |  | 0.9 | L0 | 1000 | 0% |
| entity.entity_type | Licensee | entity_type_from_name |  | 0.7 | L1 | 346 | 0% |
| entity.status | Status | map_values({"mapping": {"Current": "active"}, "default": "unknown"}) |  | 0.95 | L1 | 1000 | 0% |
| address.full | Address | null_if({"values": ["NULL"]}), collapse_whitespace |  | 0.95 | L0 | 989 | 1% |
| address.locality | Suburb | null_if({"values": ["NULL"]}), collapse_whitespace, title_case |  | 0.95 | L1 | 989 | 1% |
| address.postcode | Postcode | null_if({"values": ["NULL"]}), digits_only |  | 0.95 | L1 | 989 | 1% |
| address.state | Suburb | constant({"value": "NSW"}) |  | 0.99 | L1 | 1000 | 0% |
| address.country | Suburb | constant({"value": "AU"}) |  | 0.99 | L1 | 1000 | 0% |

Unmapped (deliberately not guessed):
  - Licence type: Specific liquor licence category, not in canonical ontology.
  - Trading Status: Premises trading operational status; entity status is mapped from Status.
  - Latitude: Geographic coordinate, not part of canonical address schema.
  - Longitude: Geographic coordinate, not part of canonical address schema.
  - LGA: Local Government Area boundary name.
  - Precinct: Regulatory liquor precinct designation.
  - Business type: Venue business classification string.
  - Authorisation restriction name: Regulatory licence condition text.
  - Extended trading: Licence permission flag.
  - Reduced trading: Licence permission flag.
  - Primary service: Licence permission flag.
  - Right to keep gaming: Gaming authorisation flag.
  - Unrestricted: Licence permission flag.
  - After12am: Trading hours authorisation flag.
  - After3am: Trading hours authorisation flag.
  - After5am: Trading hours authorisation flag.
  - SA2: Statistical region name.
  - Band: Gaming Machine regulatory band classification.
  - GMEs: Gaming machine count metric.
  - PMPs: Poker machine permit count metric.
  - Auth limit: Authorised gaming count limit.
  - Unfulfilled Quota: Gaming quota metric.
  - GMT: Gaming machine threshold count.
  - EGMs: Electronic gaming machine count metric.

source_reliability: {'score': 0.9, 'reason': 'Official NSW government licensing registry published by the Department of Customer Service.'}

Validation: PASSED
  warning  [critic] entity.trading_name: In row 2, 'Licence name' ('Orange City Rugby Club Incorporated') contains a legal entity suffix ('Incorporated'), but is mapped as 'entity.trading_name' while 'entity.legal_name' is left unmapped because the 'Licensee' field contains an individual's name ('Laurie Dunn'). -> Consider evaluating 'Licence name' for legal corporate suffixes (e.g. Incorporated, Ltd) to populate 'entity.legal_name' and 'entity.entity_type' when 'Licensee' is an individual person.
critic: The mapping configuration performs well overall, accurately extracting legal names, trading names, entity types, statuses, and standardizing address fields. One warning was identified where an incorporated entity name was categorized as a trading name because the licensee field listed an individual officer.

history: [{"iteration": 0, "passed": true, "n_blocking": 0, "n_warnings": 2}, {"iteration": 1, "passed": false, "n_blocking": 1, "n_warnings": 1}, {"iteration": 2, "passed": true, "n_blocking": 0, "n_warnings": 1}]
  it0 propose: initial proposal
  it1 revise: 1. Added mapping from Start date to entity.date_registered. 2. Added condition to entity.legal_name mapping so Licensee is only mapped when containing legal-form words (e.g. LTD, CLUB, INC). 3. Corrected transform args to JSON string args_json per schema.
  it2 revise: Removed entity.date_registered mapping from 'Start date' to resolve blocking validation failure. Kept legal form filter on entity.legal_name per human reviewer feedback.
  NOTE FOR REVIEWER: Removed entity.date_registered mapping from Start date as licence start date is not corporate incorporation date.
  NOTE FOR REVIEWER: Retained legal-form word matching on Licensee column for entity.legal_name to prevent natural person licensees from being incorrectly ingested as corporate legal names.

Examples (unseen rows):
  RAW    {"Licence number": "LIQC300200124", "Licence type": "Liquor - club licence", "Status": "Current", "Start date": "08/04/1982", "Trading Status": "Trading", "Licence name": "Clarence Town Bowling, Sport and Recreation Club L", "Address": "Prince & Durham Sts", "Suburb": "CLARENCE TOWN", "Postcode": "2321", "Latitude": "-32.5860530000", "Longitude": "151.7822040000", "LGA": "Dungog Shire Council", "Licensee": "CLARENCETOWN BOWLING CLUB LTD", "Authorisation restriction name": "Club functions authorisation,Non-restricted area a", "Extended trading": "No", "Reduced trading": "No", "Primary service":
  CLAIMS [('entity.legal_name', 'CLARENCETOWN BOWLING CLUB LTD'), ('entity.trading_name', 'Clarence Town Bowling, Sport and Recreation Club Limited'), ('entity.entity_type', 'company'), ('entity.status', 'active'), ('address.full', 'Prince & Durham Sts'), ('address.locality', 'Clarence Town'), ('address.postcode', '2321'), ('address.state', 'NSW'), ('address.country', 'AU')]
  RAW    {"Licence number": "LIQC300200485", "Licence type": "Liquor - club licence", "Status": "Current", "Start date": "03/02/1984", "Trading Status": "Trading", "Licence name": "Slovene Association Sydney", "Address": "2-10 Elizabeth St", "Suburb": "WETHERILL PARK", "Postcode": "2164", "Latitude": "-33.8508090000", "Longitude": "150.8993010000", "LGA": "Fairfield City Council", "Licensee": "SLOVENE ASSOCIATION SYDNEY", "Authorisation restriction name": "Club functions authorisation,Non-restricted area a", "Extended trading": "No", "Reduced trading": "No", "Primary service": "No", "Right to keep gami
  CLAIMS [('entity.legal_name', 'SLOVENE ASSOCIATION SYDNEY'), ('entity.trading_name', 'Slovene Association Sydney'), ('entity.status', 'active'), ('address.full', '2-10 Elizabeth St'), ('address.locality', 'Wetherill Park'), ('address.postcode', '2164'), ('address.state', 'NSW'), ('address.country', 'AU')]
  RAW    {"Licence number": "LIQC300225577", "Licence type": "Liquor - club licence", "Status": "Current", "Start date": "09/05/1955", "Trading Status": "Trading", "Licence name": "Bankstown RSL Club Ltd", "Address": "1 Meredith St", "Suburb": "BANKSTOWN", "Postcode": "2200", "Latitude": "-33.9165060000", "Longitude": "151.0317700000", "LGA": "Canterbury-Bankstown Council", "Licensee": "Bankstown RSL Club Limited", "Authorisation restriction name": "Club functions authorisation,Non-restricted area a", "Extended trading": "No", "Reduced trading": "No", "Primary service": "No", "Right to keep gaming": "Y
  CLAIMS [('entity.legal_name', 'Bankstown RSL Club Limited'), ('entity.trading_name', 'Bankstown RSL Club Ltd'), ('entity.entity_type', 'company'), ('entity.status', 'active'), ('address.full', '1 Meredith St'), ('address.locality', 'Bankstown'), ('address.postcode', '2200'), ('address.state', 'NSW'), ('address.country', 'AU')]

agent cost so far: $0.3341 over 12 steps; paused at: ('review',)