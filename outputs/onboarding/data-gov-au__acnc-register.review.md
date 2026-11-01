# Review: data.gov.au:acnc-register

ACNC Registered Charities — Australian Charities and Not-for-profits Commission (ACNC)
resource: ACNC Register of Australian charities CSV [CSV]  rows: 66514  licence: Creative Commons Attribution 3.0 Australia
what it is: This dataset contains the Australian Charities and Not-for-profits Commission (ACNC) register of Australian charities, including their Australian Business Number (ABN), legal name, address details, registration date, financial size, operating jurisdictions, and charitable purposes/beneficiary categories.
one row = one registered charity entity
entity concerns: Entities are legal organisations registered in Australia with ABNs, including incorporated associations, trusts, corporations, and public benevolent institutions.
reader: {"format": "csv", "encoding": "utf-8-sig", "delimiter": ",", "sheet": "", "header_row": 0, "skip_rows_after_header": 0, "records_path": ""}  (inspect attempts: 2)
record id: ['ABN'] — ABN uniquely identifies each registered Australian charity in the ACNC register.
observed_at: {"fixed": null, "note": "Sourced from dataset resource last modified metadata timestamp (2026-10-18T17:58:51.946320)."}

| target | source | transforms | when | conf | lvl | applied | fail% |
|---|---|---|---|---|---|---|---|
| entity.abn | ABN | abn |  | 1.0 | L1 | 997 | 0% |
| entity.legal_name | Charity_Legal_Name | collapse_whitespace |  | 0.98 | L0 | 998 | 0% |
| entity.trading_name | Other_Organisation_Names | split({"sep": "[,;]"}), regex_replace({"pattern": "(?i)(previously known as/former name/abn\\s*\\d), collapse_whitespace |  | 0.85 | L1 | 110 | 3% |
| entity.entity_type | Charity_Legal_Name | entity_type_from_name |  | 0.7 | L1 | 709 | 0% |
| entity.website | Charity_Website | null_if({"values": ["na", "n/a", "none"]}), url |  | 0.9 | L1 | 678 | 0% |
| entity.date_registered | Registration_Date | parse_date({"formats": ["%d/%m/%Y"]}) |  | 0.95 | L1 | 998 | 0% |
| address.full | Address_Line_1, Address_Line_2, Address_Line_3 | collapse_whitespace |  | 0.85 | L1 | 899 | 0% |
| address.locality | Town_City | title_case, collapse_whitespace |  | 0.95 | L1 | 899 | 0% |
| address.state | State | au_state |  | 0.95 | L1 | 898 | 0% |
| address.postcode | Postcode | au_postcode |  | 0.95 | L1 | 900 | 0% |
| address.country | Country | collapse_whitespace, map_values({"mapping": {"Australia": "AU", "AUSTRALIA": "AU"}, "default) |  | 0.95 | L1 | 884 | 0% |

Unmapped (deliberately not guessed):
  - Address_Type: Address classification label ('Business'); redundant for address parsing.
  - Date_Organisation_Established: Entity establishment date; entity.date_registered prioritises official registration date.
  - Charity_Size: Financial tier indicator (Small/Medium/Large), outside canonical entity schema.
  - Number_of_Responsible_Persons: Board/governance size count, outside canonical entity schema.
  - Financial_Year_End: Accounting period indicator, outside canonical entity schema.
  - Operates_in_ACT: State operational jurisdiction flag, outside canonical entity schema.
  - Operates_in_NSW: State operational jurisdiction flag, outside canonical entity schema.
  - Operates_in_NT: State operational jurisdiction flag, outside canonical entity schema.
  - Operates_in_QLD: State operational jurisdiction flag, outside canonical entity schema.
  - Operates_in_SA: State operational jurisdiction flag, outside canonical entity schema.
  - Operates_in_TAS: State operational jurisdiction flag, outside canonical entity schema.
  - Operates_in_VIC: State operational jurisdiction flag, outside canonical entity schema.
  - Operates_in_WA: State operational jurisdiction flag, outside canonical entity schema.
  - Operating_Countries: International operational jurisdiction codes, outside canonical entity schema.
  - PBI: Public Benevolent Institution tax endorsement flag, outside canonical entity schema.
  - HPC: Health Promotion Charity tax endorsement flag, outside canonical entity schema.
  - Preventing_or_relieving_suffering_of_animals: Charitable subtype purpose flag, outside canonical entity schema.
  - Advancing_Culture: Charitable subtype purpose flag, outside canonical entity schema.
  - Advancing_Education: Charitable subtype purpose flag, outside canonical entity schema.
  - Advancing_Health: Charitable subtype purpose flag, outside canonical entity schema.
  - Promote_or_oppose_a_change_to_law__government_poll_or_prac: Charitable subtype purpose flag, outside canonical entity schema.
  - Advancing_natual_environment: Charitable subtype purpose flag, outside canonical entity schema.
  - Promoting_or_protecting_human_rights: Charitable subtype purpose flag, outside canonical entity schema.
  - Purposes_beneficial_to_ther_general_public_and_other_analogous: Charitable subtype purpose flag, outside canonical entity schema.
  - Promoting_reconciliation__mutual_respect_and_tolerance: Charitable subtype purpose flag, outside canonical entity schema.
  - Advancing_Religion: Charitable subtype purpose flag, outside canonical entity schema.
  - Advancing_social_or_public_welfare: Charitable subtype purpose flag, outside canonical entity schema.
  - Advancing_security_or_safety_of_Australia_or_Australian_public: Charitable subtype purpose flag, outside canonical entity schema.
  - Aboriginal_or_TSI: Beneficiary group classification flag, outside canonical entity schema.
  - Adults: Beneficiary group classification flag, outside canonical entity schema.
  - Aged_Persons: Beneficiary group classification flag, outside canonical entity schema.
  - Children: Beneficiary group classification flag, outside canonical entity schema.
  - Communities_Overseas: Beneficiary group classification flag, outside canonical entity schema.
  - Early_Childhood: Beneficiary group classification flag, outside canonical entity schema.
  - Ethnic_Groups: Beneficiary group classification flag, outside canonical entity schema.
  - Families: Beneficiary group classification flag, outside canonical entity schema.
  - Females: Beneficiary group classification flag, outside canonical entity schema.
  - Financially_Disadvantaged: Beneficiary group classification flag, outside canonical entity schema.
  - LGBTIQA+: Beneficiary group classification flag, outside canonical entity schema.
  - General_Community_in_Australia: Beneficiary group classification flag, outside canonical entity schema.
  - Males: Beneficiary group classification flag, outside canonical entity schema.
  - Migrants_Refugees_or_Asylum_Seekers: Beneficiary group classification flag, outside canonical entity schema.
  - Other_Beneficiaries: Beneficiary group classification flag, outside canonical entity schema.
  - Other_Charities: Beneficiary group classification flag, outside canonical entity schema.
  - People_at_risk_of_homelessness: Beneficiary group classification flag, outside canonical entity schema.
  - People_with_Chronic_Illness: Beneficiary group classification flag, outside canonical entity schema.
  - People_with_Disabilities: Beneficiary group classification flag, outside canonical entity schema.
  - Pre_Post_Release_Offenders: Beneficiary group classification flag, outside canonical entity schema.
  - Rural_Regional_Remote_Communities: Beneficiary group classification flag, outside canonical entity schema.
  - Unemployed_Person: Beneficiary group classification flag, outside canonical entity schema.
  - Veterans_or_their_families: Beneficiary group classification flag, outside canonical entity schema.
  - Victims_of_crime: Beneficiary group classification flag, outside canonical entity schema.
  - Victims_of_Disasters: Beneficiary group classification flag, outside canonical entity schema.
  - Youth: Beneficiary group classification flag, outside canonical entity schema.
  - animals: Beneficiary group classification flag, outside canonical entity schema.
  - environment: Beneficiary group classification flag, outside canonical entity schema.
  - other_gender_identities: Beneficiary group classification flag, outside canonical entity schema.

source_reliability: {'score': 0.98, 'reason': 'Official statutory regulator (ACNC) maintaining national register of Australian charities.'}

Validation: PASSED
  warning  entity.trading_name: 3% transform failures, e.g. ['Previously known as ABN 89497784003', 'Previously known as ABN 91566009857', 'Previously known as ABN 19366795521']
  warning  [critic] entity.entity_type: 'Kullilli Bulloo River Aboriginal Corporation RNTBC' was mapped to 'company' based on the word 'Corporation', but it is an Aboriginal and Torres Strait Islander Corporation / RNTBC rather than a standard commercial company. -> Refine the entity_type_from_name transform to handle Indigenous corporations properly or avoid mapping them as generic companies.
  warning  [critic] address.full: Concatenating Address_Line_1, Address_Line_2, and Address_Line_3 creates redundant text when source rows repeat address components across multiple lines (e.g., 'Level 1Unit 5/20 King Street, Unit 5/20 King Street, 20 King Street'). -> Add a deduplication transform when merging multi-line address fields into address.full.
critic: Mapping accurately captures most fields, but entity type inference misclassifies Aboriginal corporations as generic companies, and merging multi-line address fields produces duplicate address fragments.

history: [{"iteration": 0, "passed": true, "n_blocking": 0, "n_warnings": 1}, {"iteration": 1, "passed": true, "n_blocking": 0, "n_warnings": 1}, {"iteration": 2, "passed": true, "n_blocking": 0, "n_warnings": 3}]
  it0 propose: initial proposal
  it1 revise: Updated record envelope properties (observed_at, valid_from, valid_to) to comply with JSON schema requirements. Updated entity.trading_name mapping to split delimited values on commas/semicolons and strip administrative notes like 'Previously known as' and ABN references using regex_replace.
  it2 revise: 1. Corrected `entity.trading_name` regex pattern to remove notes like 'Previously known as', 'former name', and ABN fragments without matching rest-of-string (.*), preserving valid former names. 2. Updated `address.country` map_values transform with explicit default null to prevent non-Australian co
  NOTE FOR REVIEWER: Verify that entity.trading_name correctly emits individual names when multiple comma/semicolon separated values exist.
  NOTE FOR REVIEWER: Verify non-Australian address records emit null for address.country rather than defaulting to AU.

Examples (unseen rows):
  RAW    {"ABN": "37381250705", "Charity_Legal_Name": "The Trustee for The Lightening Foundation", "Address_Type": "Business", "Address_Line_1": "5 Cullen Dr", "Town_City": "Kiama Downs", "State": "NSW", "Postcode": "2533", "Country": "Australia", "Charity_Website": "www.lighteningfoundation.wix.com/info", "Registration_Date": "19/05/2021", "Date_Organisation_Established": "19/05/2021", "Charity_Size": "Small", "Number_of_Responsible_Persons": "4", "Financial_Year_End": "30-Jun", "Advancing_Religion": "Y", "Adults": "Y"}
  CLAIMS [('entity.abn', '37381250705'), ('entity.legal_name', 'The Trustee for The Lightening Foundation'), ('entity.entity_type', 'trust'), ('entity.website', 'www.lighteningfoundation.wix.com/info'), ('entity.date_registered', '2021-05-19'), ('address.full', '5 Cullen Dr'), ('address.locality', 'Kiama Downs'), ('address.state', 'NSW'), ('address.postcode', '2533'), ('address.country', 'AU')]
  RAW    {"ABN": "53470910212", "Charity_Legal_Name": "The Trustee for the Louis Koala Foundation", "Address_Type": "Business", "Address_Line_1": "Suite 14.06, Level 6", "Address_Line_2": "109 Pitt Street", "Town_City": "Sydney", "State": "NSW", "Postcode": "2000", "Registration_Date": "23/03/2021", "Date_Organisation_Established": "16/03/2021", "Charity_Size": "Small", "Number_of_Responsible_Persons": "5", "Financial_Year_End": "30-Jun", "Operates_in_NSW": "Y", "Operating_Countries": "AUS", "Preventing_or_relieving_suffering_of_animals": "Y", "Advancing_natual_environment": "Y", "animals": "Y"}
  CLAIMS [('entity.abn', '53470910212'), ('entity.legal_name', 'The Trustee for the Louis Koala Foundation'), ('entity.entity_type', 'trust'), ('entity.date_registered', '2021-03-23'), ('address.full', 'Suite 14.06, Level 6, 109 Pitt Street'), ('address.locality', 'Sydney'), ('address.state', 'NSW'), ('address.postcode', '2000')]
  RAW    {"ABN": "37650268385", "Charity_Legal_Name": "WHAT ABILITY FOUNDATION LIMITED", "Address_Type": "Business", "Address_Line_1": "Suite 1.03", "Address_Line_2": "7 Eden Park Drive", "Town_City": "Macquarie Park", "State": "NSW", "Postcode": "2047", "Country": "Australia", "Charity_Website": "www.whatabilityfoundation.org.au", "Registration_Date": "17/05/2021", "Date_Organisation_Established": "17/05/2021", "Charity_Size": "Small", "Number_of_Responsible_Persons": "4", "Financial_Year_End": "30-Jun", "Operates_in_ACT": "Y", "Operates_in_NSW": "Y", "Operates_in_NT": "Y", "Operates_in_QLD": "Y", "Op
  CLAIMS [('entity.abn', '37650268385'), ('entity.legal_name', 'WHAT ABILITY FOUNDATION LIMITED'), ('entity.entity_type', 'company'), ('entity.website', 'www.whatabilityfoundation.org.au'), ('entity.date_registered', '2021-05-17'), ('address.full', 'Suite 1.03, 7 Eden Park Drive'), ('address.locality', 'Macquarie Park'), ('address.state', 'NSW'), ('address.postcode', '2047'), ('address.country', 'AU')]

agent cost so far: $0.5078 over 15 steps; paused at: ('review',)