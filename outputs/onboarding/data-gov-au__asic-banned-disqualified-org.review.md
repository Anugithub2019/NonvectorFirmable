# Review: data.gov.au:asic-banned-disqualified-org

ASIC - Banned and Disqualified Organisations Dataset — Australian Securities and Investments Commission (ASIC)
resource: Banned and Disqualified Organisations - Current [CSV]  rows: 15  licence: Creative Commons Attribution 3.0 Australia
what it is: This dataset is a point-in-time snapshot from ASIC's Banned and Disqualified Registers listing organisations that have been banned or disqualified from engaging in credit activities, financial services, or other regulated business operations in Australia.
one row = One banning or disqualification order applied to an organisation identified by its ACN.
reader: {"format": "tsv", "encoding": "utf-8-sig", "delimiter": "\t", "sheet": "", "header_row": 0, "skip_rows_after_header": 0, "records_path": ""}  (inspect attempts: 1)
record id: ['BD_ORG_ACN', 'BD_ORG_START_DT', 'BD_ORG_TYPE'] — Combination of organisation ACN, banning start date, and banning type uniquely identifies each disqualification order.
observed_at: {"fixed": null, "note": "Extracted from resource last modified metadata date: 2026-10-26T21:03:26.297860"}

| target | source | transforms | when | conf | lvl | applied | fail% |
|---|---|---|---|---|---|---|---|
| entity.legal_name | BD_ORG_NAME | collapse_whitespace |  | 0.95 | L0 | - | 0% |
| entity.acn | BD_ORG_ACN | acn |  | 1.0 | L1 | - | 0% |
| entity.entity_type | BD_ORG_NAME | entity_type_from_name |  | 0.7 | L1 | - | 0% |
| ban.ban_type | BD_ORG_TYPE | collapse_whitespace |  | 0.95 | L0 | - | 0% |
| ban.start_date | BD_ORG_START_DT | parse_date({"formats": ["%d/%m/%Y"]}) |  | 0.95 | L1 | - | 0% |
| ban.end_date | BD_ORG_END_DT | null_if({"values": ["Permanent banning"]}), parse_date({"formats": ["%d/%m/%Y"]}) |  | 0.95 | L1 | - | 0% |
| ban.issuing_authority | REGISTER_NAME | constant({"value": "Australian Securities and Investments Commission") |  | 1.0 | L1 | - | 0% |
| ban.reference | BD_ORG_URL | null_if({"values": ["Not available"]}), strip |  | 0.9 | L0 | - | 0% |

Unmapped (deliberately not guessed):
  - BD_ORG_COMMENT: Contains free-text comments and reasons regarding the order (e.g., 'Fail to comply...'), which does not fit standard canonical ban attributes.

source_reliability: {'score': 0.98, 'reason': 'ASIC is the statutory national corporate and financial services regulator in Australia.'}

Validation: PASSED

history: [{"iteration": 0, "passed": true, "n_blocking": 0, "n_warnings": 0}]
  it0 propose: initial proposal
  NOTE FOR REVIEWER: BD_ORG_END_DT uses string 'Permanent banning' for indefinite bans; this is converted to null for ISO date parsing compliance.
  NOTE FOR REVIEWER: BD_ORG_COMMENT contains grounds for banning but remains unmapped as ban entity currently lacks a dedicated comments field.

Examples (unseen rows):

agent cost so far: $0.0580 over 7 steps; paused at: ('review',)