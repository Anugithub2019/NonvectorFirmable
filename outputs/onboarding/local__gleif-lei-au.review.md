# Review: local:gleif-lei-au

GLEIF LEI records, Australia (Level 1) — Global Legal Entity Identifier Foundation
resource: lei_au.csv [CSV]  rows: 53604  licence: CC0 1.0 (GLEIF data is public domain)
what it is: This dataset contains Level 1 Legal Entity Identifier (LEI) records for entities with an Australian legal address sourced from the Global Legal Entity Identifier Foundation (GLEIF). It includes entity details such as LEI code, legal name, alternative names, legal form, registration identifiers (ACN/ABN), address, jurisdiction, registration status, and parent entity indicators.
one row = One LEI record representing a legal entity or fund registered or operating in Australia.
entity concerns: Contains both corporate entities and managed investment funds; includes inactive, lapsed, or retired records.
reader: {"format": "csv", "encoding": "utf-8-sig", "delimiter": ",", "sheet": "", "header_row": 0, "skip_rows_after_header": 0, "records_path": ""}  (inspect attempts: 1)
record id: ['lei'] — LEI (Legal Entity Identifier) is a unique global identifier for legal entities.
observed_at: {"column": "last_update", "transforms": [{"op": "parse_datetime", "args": {"formats": ["%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S.%fZ"]}}], "note": "Date and time when the LEI record was last updated in the GLEIF database."}

| target | source | transforms | when | conf | lvl | applied | fail% |
|---|---|---|---|---|---|---|---|
| entity.lei | lei | strip, upper |  | 0.97 | L0 | 1000 | 0% |
| entity.legal_name | legal_name | collapse_whitespace |  | 0.96 | L0 | 1000 | 0% |
| entity.status | status | null_if({"values": ["NULL"]}), map_values({"mapping": {"ACTIVE": "active", "INACTIVE": "unknown"}, "de) |  | 0.83 | L1 | 995 | 0% |
| entity.entity_type | legal_name | entity_type_from_name |  | 0.89 | L1 | 903 | 0% |
| entity.abn | registered_as | abn | registered_as matches ['^(\\D*\\d){11}\\D*$'] | 0.53 | L1 | 269 | 0% |
| entity.acn | registered_as | acn | registered_as matches ['^(\\D*\\d){9}\\D*$'] | 0.62 | L1 | 685 | 0% |
| entity.date_registered | creation_date | parse_datetime({"formats": ["%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S.%fZ"]}) |  | 0.73 | L1 | 822 | 0% |
| address.full | address | collapse_whitespace |  | 0.71 | L0 | 1000 | 0% |
| address.locality | city | collapse_whitespace |  | 0.97 | L0 | 1000 | 0% |
| address.state | region | au_state |  | 0.91 | L1 | 945 | 0% |
| address.postcode | postcode | au_postcode |  | 0.97 | L1 | 1000 | 0% |
| address.country | country | upper |  | 0.97 | L0 | 1000 | 0% |

Unmapped (deliberately not guessed):
  - other_names: Contains a heterogeneous mix of former legal names, trading names, and trustee entity descriptions without structured flags to accurately distinguish between them.
  - legal_form: Internal ELF standard codes (e.g. TXVC, 7TPC), requiring external taxonomy mapping.
  - category: High-level entity category (GENERAL, FUND, SOLE_PROPRIETOR); entity_type is derived from legal_name.
  - registered_at: Registration authority ID (e.g. RA000014), register metadata.
  - jurisdiction: Jurisdiction code (AU), redundant with address.country.
  - registration_status: LEI record lifecycle status (ISSUED, LAPSED, RETIRED) rather than entity operational status.
  - initial_registration: Timestamp when LEI identifier was first issued.
  - next_renewal: LEI annual renewal due date.
  - has_direct_parent: Boolean flag indicating direct parent existence without providing parent identifier.
  - has_ultimate_parent: Boolean flag indicating ultimate parent existence without providing parent identifier.
  - successor: Successor mapping removed as predecessor_of relationship is not supported in the graph schema.

source_reliability: {'score': 0.95, 'reason': 'GLEIF is the official Global Legal Entity Identifier Foundation public authority register for legal entity identifiers.'}

Validation: PASSED
  warning  [critic] other_names: The source column 'other_names' contains former or alternative entity names (e.g. 'LYNAS CORPORATION LIMITED' for Lynas Rare Earths Limited) but is not included in the mapping config, causing this information to be dropped. -> Add a mapping for source column 'other_names' targeting 'entity.former_name' or 'entity.trading_name' (with splitting transforms if multiple names are separated by pipes).
  warning  [jev] entity.abn: P(mapping correct) = 0.53 - reviewer should look
critic: The mapping configuration accurately extracts LEIs, legal names, entity types, ACNs, dates, and full address fields. The only notable omission is that the 'other_names' column is unmapped, dropping valid former and alternative entity names.

history: [{"iteration": 0, "passed": false, "n_blocking": 3, "n_warnings": 3}, {"iteration": 1, "passed": true, "n_blocking": 0, "n_warnings": 2}, {"iteration": 2, "passed": false, "n_blocking": 1, "n_warnings": 1}, {"iteration": 3, "passed": true, "n_blocking": 0, "n_warnings": 2}]
  it0 propose: initial proposal
  it1 revise: 1. Fixed entity.abn and entity.acn failure rates by adding 'when' regex conditions matching digit counts (11 digits for ABN, 9 digits for ACN). 2. Fixed related_party.relationship enum validation failure by applying a 'constant' transform set to 'successor_of'. 3. Updated field confidences according
  it2 revise: Removed related_party.lei and related_party.relationship mappings for successor; added successor to unmapped per human reviewer feedback. Added creation_date mapping to entity.date_registered.
  it3 revise: 1. Unmapped 'other_names' column as it contains mixed former legal names, trading names, and trustee designations that cannot be safely disambiguated. 2. Changed date parsing transform for creation_date to parse_datetime as requested.
  NOTE FOR REVIEWER: Unmapped other_names to prevent misclassifying former legal names or trustee entity titles as trading names.
  NOTE FOR REVIEWER: Updated creation_date parsing to parse_datetime for both record valid_from and entity.date_registered.

Examples (unseen rows):
  RAW    {"lei": "16V2XOPZ012Q2IA7OP37", "legal_name": "AQR WHOLESALE MANAGED FUTURES FUND", "status": "ACTIVE", "legal_form": "ADXG", "category": "FUND", "registered_as": "147 951 791", "registered_at": "RA000015", "jurisdiction": "AU", "address": "Level 18", "city": "Sydney", "region": "AU-NSW", "postcode": "2000", "country": "AU", "creation_date": "2010-12-23T00:00:00Z", "registration_status": "ISSUED", "initial_registration": "2012-10-15T11:02:00Z", "last_update": "2026-01-02T20:41:37Z", "next_renewal": "2027-01-15T15:08:15Z", "has_direct_parent": "False", "has_ultimate_parent": "False"}
  CLAIMS [('entity.lei', '16V2XOPZ012Q2IA7OP37'), ('entity.legal_name', 'AQR WHOLESALE MANAGED FUTURES FUND'), ('entity.status', 'active'), ('entity.acn', '147951791'), ('entity.date_registered', '2010-12-23T00:00:00'), ('address.full', 'Level 18'), ('address.locality', 'Sydney'), ('address.state', 'NSW'), ('address.postcode', '2000'), ('address.country', 'AU')]
  RAW    {"lei": "2138003VLB1D8AXCHW55", "legal_name": "THE TRUSTEE FOR DAVID HUSOY SUPERANNUATION FUND", "status": "ACTIVE", "legal_form": "8888", "category": "GENERAL", "registered_as": "55 156 037 192", "registered_at": "RA000013", "jurisdiction": "AU", "address": "23 WOLLONDILLY PLACE, SYLVANIA WATERS", "city": "SYDNEY", "region": "AU-NSW", "postcode": "2224", "country": "AU", "creation_date": "2008-10-18T00:00:00Z", "registration_status": "LAPSED", "initial_registration": "2019-10-03T00:00:00Z", "last_update": "2025-10-13T00:05:10Z", "next_renewal": "2025-10-12T00:00:00Z", "has_direct_parent": "Fa
  CLAIMS [('entity.lei', '2138003VLB1D8AXCHW55'), ('entity.legal_name', 'THE TRUSTEE FOR DAVID HUSOY SUPERANNUATION FUND'), ('entity.status', 'active'), ('entity.entity_type', 'trust'), ('entity.abn', '55156037192'), ('entity.date_registered', '2008-10-18T00:00:00'), ('address.full', '23 WOLLONDILLY PLACE, SYLVANIA WATERS'), ('address.locality', 'SYDNEY'), ('address.state', 'NSW'), ('address.postcode', '2224'), ('address.country', 'AU')]
  RAW    {"lei": "21380043S9L927RM9515", "legal_name": "CJ&M CONTRACTING PTY LTD", "status": "ACTIVE", "legal_form": "TXVC", "category": "GENERAL", "registered_as": "104 966 396", "registered_at": "RA000014", "jurisdiction": "AU", "address": "10 Bennett Grove", "city": "Bidwill", "region": "AU-NSW", "postcode": "2770", "country": "AU", "registration_status": "LAPSED", "initial_registration": "2018-11-26T00:00:00Z", "last_update": "2022-02-23T15:28:32Z", "next_renewal": "2020-11-25T00:00:00Z", "has_direct_parent": "False", "has_ultimate_parent": "False"}
  CLAIMS [('entity.lei', '21380043S9L927RM9515'), ('entity.legal_name', 'CJ&M CONTRACTING PTY LTD'), ('entity.status', 'active'), ('entity.entity_type', 'company'), ('entity.acn', '104966396'), ('address.full', '10 Bennett Grove'), ('address.locality', 'Bidwill'), ('address.state', 'NSW'), ('address.postcode', '2770'), ('address.country', 'AU')]

agent cost so far: $0.4941 over 14 steps; paused at: ('review',)