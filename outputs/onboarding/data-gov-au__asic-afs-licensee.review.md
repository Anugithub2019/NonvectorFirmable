# Review: data.gov.au:asic-afs-licensee

ASIC - Australian Financial Services Licensee Dataset — Australian Securities and Investments Commission (ASIC)
resource: AFS Licensee Dataset - Current [CSV]  rows: 6541  licence: Creative Commons Attribution 3.0 Australia
what it is: This dataset contains current Australian Financial Services (AFS) licensees published by the Australian Securities and Investments Commission (ASIC). It includes details such as licensee name, ASIC licence number, Australian Business Number (ABN) or Australian Company Number (ACN), licence start date, registered address, and specific licence conditions and authorisations.
one row = one Australian Financial Services (AFS) licence held by an entity
entity concerns: While the majority of licensees are corporate entities (e.g. Proprietary Limited companies with ABN/ACN), some entries may represent individual sole traders or partnerships.
reader: {"format": "csv", "encoding": "utf-8-sig", "delimiter": ",", "sheet": "", "header_row": 0, "skip_rows_after_header": 0, "records_path": ""}  (inspect attempts: 1)
record id: ['AFS_LIC_NUM'] — AFS_LIC_NUM uniquely identifies each AFS licence issued by ASIC.
observed_at: {"fixed": null, "note": "Not available per record; metadata shows dataset last modified date."}

| target | source | transforms | when | conf | lvl | applied | fail% |
|---|---|---|---|---|---|---|---|
| entity.legal_name | AFS_LIC_NAME | collapse_whitespace |  | 0.91 | L0 | 1000 | 0% |
| entity.entity_type | AFS_LIC_NAME | entity_type_from_name |  | 0.7 | L1 | 984 | 0% |
| entity.abn | AFS_LIC_ABN_ACN | abn | AFS_LIC_ABN_ACN matches ['^[0-9]{11}$'] | 0.74 | L1 | 972 | 0% |
| entity.acn | AFS_LIC_ABN_ACN | acn | AFS_LIC_ABN_ACN matches ['^[0-9]{9}$'] | 0.88 | L1 | 28 | 0% |
| address.locality | AFS_LIC_ADD_LOCAL | collapse_whitespace, title_case |  | 0.97 | L1 | 991 | 0% |
| address.state | AFS_LIC_ADD_STATE | au_state |  | 0.96 | L1 | 991 | 0% |
| address.postcode | AFS_LIC_ADD_PCODE | au_postcode |  | 0.96 | L1 | 991 | 0% |
| address.country | AFS_LIC_ADD_COUNTRY | map_values({"mapping": {"australia": "AU", "international": "OTHER"}, ") |  | 0.9 | L1 | 1000 | 0% |
| licence.licence_number | AFS_LIC_NUM | collapse_whitespace |  | 0.95 | L0 | 1000 | 0% |
| licence.licence_type | AFS_LIC_NUM | constant({"value": "afs"}) |  | 0.71 | L1 | 1000 | 0% |
| licence.start_date | AFS_LIC_START_DT | parse_date({"formats": ["%d/%m/%Y"]}) |  | 0.93 | L1 | 1000 | 0% |
| licence.authorisations | AFS_LIC_CONDITION | collapse_whitespace |  | 0.46 | L0 | 1000 | 0% |

Unmapped (deliberately not guessed):
  - REGISTER_NAME: Redundant static string ('AFS Licence') across all records.
  - AFS_LIC_PRE_FSR: Legacy pre-Financial Services Reform registration codes/references.

source_reliability: {'score': 0.98, 'reason': 'Official dataset published by the Australian Securities and Investments Commission (ASIC).'}

Validation: PASSED
  warning  [jev] licence.authorisations: P(mapping correct) = 0.46 - reviewer should look
critic: No semantic issues detected. All extracted fields accurately align with the source raw data and conform to the canonical target schema.

history: [{"iteration": 0, "passed": false, "n_blocking": 1, "n_warnings": 3}, {"iteration": 1, "passed": true, "n_blocking": 0, "n_warnings": 1}, {"iteration": 2, "passed": true, "n_blocking": 0, "n_warnings": 1}]
  it0 propose: initial proposal
  it1 revise: Added 'when' regex conditions on AFS_LIC_ABN_ACN for both entity.abn (matching 11 digits) and entity.acn (matching 9 digits). Previously entity.acn attempted to parse 11-digit ABNs as ACNs, causing 97% transform failures. Updated all transforms to use args_json formatting compliant with schema.
  it2 revise: Updated mapping target for AFS_LIC_CONDITION from licence.conditions to licence.authorisations based on reviewer feedback, as the column content details authorisation scope rather than licence restrictions/conditions.
  NOTE FOR REVIEWER: Changed target for AFS_LIC_CONDITION from licence.conditions to licence.authorisations per feedback.

Examples (unseen rows):
  RAW    {"REGISTER_NAME": "AFS Licence", "AFS_LIC_NUM": "218600", "AFS_LIC_NAME": "IPIB PTY LTD", "AFS_LIC_ABN_ACN": "85007186003", "AFS_LIC_START_DT": "02/05/2002", "AFS_LIC_PRE_FSR": "\"General insurance broker\",\"000030366\"", "AFS_LIC_ADD_LOCAL": "SOUTHBANK", "AFS_LIC_ADD_STATE": "VIC", "AFS_LIC_ADD_PCODE": "3006", "AFS_LIC_ADD_COUNTRY": "Australia", "AFS_LIC_CONDITION": "\"This licence authorises the licensee to carry on "}
  CLAIMS [('entity.legal_name', 'IPIB PTY LTD'), ('entity.entity_type', 'company'), ('entity.abn', '85007186003'), ('address.locality', 'Southbank'), ('address.state', 'VIC'), ('address.postcode', '3006'), ('address.country', 'AU'), ('licence.licence_number', '218600'), ('licence.licence_type', 'afs'), ('licence.start_date', '2002-05-02'), ('licence.authorisations', '"This licence authorises the licensee to carry on a financial services business to:"~"(a) provide financial product advice for the following classes of financial products:"~"(i) general insurance products; and"~"(b) deal in a financial product by:"~"(i) applying for, acquiring, varying or disposing of a financial product on behalf of another person in respect of the following classes of products:"~"(A) general insurance products;"~"to retail and wholesale clients."')]
  RAW    {"REGISTER_NAME": "AFS Licence", "AFS_LIC_NUM": "219723", "AFS_LIC_NAME": "PRIME SUPER PTY LTD", "AFS_LIC_ABN_ACN": "81067241016", "AFS_LIC_START_DT": "21/06/2002", "AFS_LIC_PRE_FSR": "\"Securities dealer\",\"000197897\"", "AFS_LIC_ADD_LOCAL": "MELBOURNE", "AFS_LIC_ADD_STATE": "VIC", "AFS_LIC_ADD_PCODE": "3000", "AFS_LIC_ADD_COUNTRY": "Australia", "AFS_LIC_CONDITION": "\"This licence authorises the licensee to carry on "}
  CLAIMS [('entity.legal_name', 'PRIME SUPER PTY LTD'), ('entity.entity_type', 'company'), ('entity.abn', '81067241016'), ('address.locality', 'Melbourne'), ('address.state', 'VIC'), ('address.postcode', '3000'), ('address.country', 'AU'), ('licence.licence_number', '219723'), ('licence.licence_type', 'afs'), ('licence.start_date', '2002-06-21'), ('licence.authorisations', '"This licence authorises the licensee to carry on a financial services business to:"~"(a) provide general financial product advice for the following classes of financial products:"~"(i) superannuation limited to:"~"(A) the "Prime Super"; and"~"(b) deal in a financial product by:"~"(i) issuing, applying for, acquiring, varying or disposing of a financial product in respect of the following classes of financial products:"~"(A) superannuation limited to:"~"(1) the "Prime Super"; and"~"(c) provide a superannuation trustee service"~"to retail clients."')]
  RAW    {"REGISTER_NAME": "AFS Licence", "AFS_LIC_NUM": "221794", "AFS_LIC_NAME": "COOPER INVESTORS PTY LIMITED", "AFS_LIC_ABN_ACN": "26100409890", "AFS_LIC_START_DT": "24/09/2002", "AFS_LIC_ADD_LOCAL": "MELBOURNE", "AFS_LIC_ADD_STATE": "VIC", "AFS_LIC_ADD_PCODE": "3000", "AFS_LIC_ADD_COUNTRY": "Australia", "AFS_LIC_CONDITION": "\"This licence authorises the licensee to carry on "}
  CLAIMS [('entity.legal_name', 'COOPER INVESTORS PTY LIMITED'), ('entity.entity_type', 'company'), ('entity.abn', '26100409890'), ('address.locality', 'Melbourne'), ('address.state', 'VIC'), ('address.postcode', '3000'), ('address.country', 'AU'), ('licence.licence_number', '221794'), ('licence.licence_type', 'afs'), ('licence.start_date', '2002-09-24'), ('licence.authorisations', '"This licence authorises the licensee to carry on a financial services business to:"~"(a) provide financial product advice for the following classes of financial products:"~"(i) deposit and payment products including:"~"(A) basic deposit products;"~"(B) deposit products other than basic deposit products; and"~"(C) non-cash payment products;"~"(ii) derivatives;"~"(iii) foreign exchange contracts;"~"(iv) debentures, stocks or bonds issued or proposed to be issued by a government;"~"(v) interests in managed investment schemes excluding investor directed portfolio services; and"~"(vi) securities;"~"(b) deal in a financial product by:"~"(i) issuing, applying for, acquiring, varying or disposing of a financial product in respect of the following classes of financial products:"~"(A) derivatives;"~"(B) foreign exchange contracts;"~"(C) interests in managed investment schemes excluding investor directed portfolio services; and"~"(D) securities;"~"(ii) applying for, acquiring, varying or disposing of a financial product on behalf of another person in respect of the following classes of products:"~"(A) deposit and payment products including:"~"(1) basic deposit products;"~"(2) deposit products other than basic deposit products; and"~"(3) non-cash payment products;"~"(B) derivatives;"~"(C) foreign exchange contracts;"~"(D) debentures, stocks or bonds issued or proposed to be issued by a government;"~"(E) interests in managed investment schemes excluding investor directed portfolio services; and"~"(F) securities; and"~"(iii) underwriting:"~"(A) interests in managed investment schemes; and"~"(B) an issue of securities; and"~"(c) provide the following custodial or depository services:"~"(i) operate custodial or depository services other than investor directed portfolio services;"~"to wholesale clients."')]

agent cost so far: $0.2819 over 12 steps; paused at: ('review',)