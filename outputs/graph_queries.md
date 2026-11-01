# Graph queries

Generated 2026-11-01T11:10:43+00:00. Query text, result, runtime, from `GraphAPI`.

## ultimate_parent

```cypher
MATCH (owner:Party)-[o:OWNS]->(c:Party {key: $key}) WHERE o.valid_to IS NULL RETURN owner.key AS key, owner.display_name AS name, o.kind AS kind, o.percent AS percent ORDER BY CASE o.kind WHEN 'ultimately_owned_by' THEN 0 ELSE 1 END, o.percent DESC
```
start `abn:25064998867` → ultimate parent `lei:5493000YQ5WVP65Z4249`, depth 1, terminated_by **root**, 73.7 ms

Cycle policy: climb one hop at a time keeping a visited set; a repeated key stops the walk and is reported as `terminated_by: cycle` with the cycle member; depth is capped at 12 (`max_depth`). Multiple owners: the `ultimately_owned_by` edge is preferred, then highest percent; the others are listed in `other_owners`.

```json
[
 {
  "key": "lei:5493000YQ5WVP65Z4249",
  "name": "(lei:5493000YQ5WVP65Z4249)",
  "kind": "owned_by",
  "percent": "100.00"
 }
]
```
## within_2_hops_of_ban

```cypher
MATCH (b:Ban)<-[:SUBJECT_OF]-(banned:Party) OPTIONAL MATCH path = (banned)-[:OWNS|AFFILIATED_WITH|RELATED_TO*1..2]-(p:Party) WITH banned, b, p, path WHERE p IS NOT NULL AND p.key <> banned.key RETURN DISTINCT p.key AS key, p.display_name AS name, p.entity_type AS entity_type, p.state AS state, banned.display_name AS via_banned_party, b.ban_type AS ban_type, b.end_date AS ban_end, length(path) AS hops ORDER BY hops LIMIT $limit
```
0 rows, 62.3 ms

```json
[]
```
## licence_cancelled_and_banned

```cypher
MATCH (p:Party)-[:SUBJECT_OF]->(b:Ban) OPTIONAL MATCH (p)-[:HOLDS]->(l:Licence) RETURN p.display_name AS party, p.key AS key, b.ban_type AS ban, b.start_date AS ban_start, b.end_date AS ban_end, collect(DISTINCT l.licence_id) AS licences ORDER BY ban_start DESC LIMIT 25
```
15 rows, 56.6 ms

```json
[
 {
  "party": "TRADING LIFE SERVICES PTY LTD",
  "key": "abn:36630664318",
  "ban": "Section 920A banning",
  "ban_start": "2022-10-05",
  "ban_end": "2027-10-04",
  "licences": []
 },
 {
  "party": "MONARCH FX GROUP PTY LTD",
  "key": "abn:49155691786",
  "ban": "Australian Financial Services banning",
  "ban_start": "2014-12-17",
  "ban_end": "2018-12-16",
  "licences": []
 },
 {
  "party": "M.A.I PACIFIC PTY LTD",
  "key": "abn:77095393007",
  "ban": "Credit Banning",
  "ban_start": "2013-12-03",
  "ban_end": null,
  "licences": []
 },
 {
  "party": "RAY RENTALS PTY. LTD.",
  "key": "abn:36156070290",
  "ban": "Credit banning",
  "ban_start": "2013-06-24",
  "ban_end": "2017-06-24",
  "licences": []
 },
 {
  "party": "First Home Shop Pty Ltd",
  "key": "abn:57118554046",
  "ban": "Credit banning by a State or Territory",
  "ban_start": "2009-06-04",
  "ban_end": null,
  "licences": []
 },
 {
  "party": "BRANNELLY FINANCIAL PTY LTD",
  "key": "abn:72011021640",
  "ban": "Australian Financial Services banning",
  "ban_start": "2009-02-09",
  "ban_end": "2015-02-08",
  "licences": []
 },
 {
  "party": "AUSTRALIAN BUSINESS INSURANCE ADVISERS (ABIA) PTY LTD",
  "key": "abn:11081402379",
  "ban": "Australian Financial Services banning",
  "ban_start": "2006-11-07",
  "ban_end": "2008-11-07",
  "licences": []
 },
 {
  "party": "CLAIREMAY PTY LTD",
  "key": "abn:74090251086",
  "ban": "Credit banning by a State or Territory",
  "ban_start": "2004-12-05",
  "ban_end": null,
  "licences": []
 },
 {
  "party": "CHARTER FINANCE AND INSURANCE PTY LTD",
  "key": "abn:68052177009",
  "ban": "Credit banning by a State or Territory",
  "ban_start": "2003-07-31",
  "ban_end": null,
  "licences": []
 },
 {
  "party": "GAMEL WARD PTY LTD",
  "key": "acn:008853914",
  "ban": "Credit banning by a State or Territory",
  "ban_start": "2002-07-24",
  "ban_end": null,
  "licences": []
 },
 {
  "party": "GERALDTON FINANCE COMPANY PTY LIMITED",
  "key": "abn:87008669645",
  "ban": "Credit banning by a State or Territory",
  "ban_start": "2002-03-04",
  "ban_end": null,
  "licences": []
 },
 {
  "party": "KNIGHTSBRIDGE FINANCE PTY LTD (Formerly CLIFTON PARTNERS FINANCE PTY LTD)",
  "key": "acn:008716872",
  "ban": "Credit banning by a State or Territory",
  "ban_start": "2001-11-21",
  "ban_end": null,
  "licences": []
 }
]
```
## liquidators_firms_with_most_people

```cypher
MATCH (pe:Person)-[:AFFILIATED_WITH]->(o:Organisation) RETURN o.display_name AS firm, o.key AS key, count(pe) AS liquidators ORDER BY liquidators DESC LIMIT 10
```
10 rows, 29.4 ms

```json
[
 {
  "firm": "KORDAMENTHA PTY LTD",
  "key": "stub:KORDAMENTHA",
  "liquidators": 20
 },
 {
  "firm": "MCGRATHNICOL",
  "key": "stub:MCGRATHNICOL",
  "liquidators": 19
 },
 {
  "firm": "FTI CONSULTING",
  "key": "stub:FTI CONSULTING",
  "liquidators": 15
 },
 {
  "firm": "RSM AUSTRALIA PARTNERS",
  "key": "stub:RSM PARTNERS",
  "liquidators": 15
 },
 {
  "firm": "TENEO",
  "key": "stub:TENEO",
  "liquidators": 14
 },
 {
  "firm": "SV PARTNERS",
  "key": "stub:SV PARTNERS",
  "liquidators": 14
 },
 {
  "firm": "GRANT THORNTON",
  "key": "stub:GRANT THORNTON",
  "liquidators": 13
 },
 {
  "firm": "RODGERS REIDY",
  "key": "stub:RODGERS REIDY",
  "liquidators": 12
 },
 {
  "firm": "WORRELLS",
  "key": "stub:WORRELLS",
  "liquidators": 11
 },
 {
  "firm": "MACKAY GOODWIN",
  "key": "stub:MACKAY GOODWIN",
  "liquidators": 11
 }
]
```
## name_conflicts

```cypher
MATCH (p:Party) WHERE p.name_conflict = true MATCH (p)-[k:KNOWN_AS {kind:'legal'}]->(n:Name) RETURN p.key AS key, collect(DISTINCT n.text) AS legal_names, p.sources AS sources LIMIT 15
```
15 rows, 244.3 ms

```json
[
 {
  "key": "src:qld:queensland-government-contracts-directory-awarded-contracts:rowhash:353f95e7a2a212cc",
  "legal_names": [
   "HAWKINS JENKINS ROSS PTY. LTD."
  ],
  "sources": [
   "qld:queensland-government-contracts-directory-awarded-contracts"
  ]
 },
 {
  "key": "acn:004379186",
  "legal_names": [
   "FELLOWES (AUSTRALIA) PTY. LIMITED"
  ],
  "sources": [
   "local:gleif-lei-au",
   "local:gleif-relationships"
  ]
 },
 {
  "key": "acn:146346929",
  "legal_names": [
   "PENGANA AUSTRALIAN EQUITIES FUND"
  ],
  "sources": [
   "local:gleif-lei-au",
   "local:gleif-relationships"
  ]
 },
 {
  "key": "acn:608349613",
  "legal_names": [
   "BAEV - LASALLE DOCKLANDS PTY LTD"
  ],
  "sources": [
   "local:gleif-lei-au",
   "local:gleif-relationships"
  ]
 },
 {
  "key": "acn:108258019",
  "legal_names": [
   "MIPEC Pty Ltd"
  ],
  "sources": [
   "qld:ehp-suitable-operator-register-sor-for-environmentally-relevant-activities-eras",
   "qld:queensland-government-contracts-directory-awarded-contracts"
  ]
 },
 {
  "key": "acn:640366301",
  "legal_names": [
   "CBRE GLOBAL REAL ASSETS FUND"
  ],
  "sources": [
   "local:gleif-lei-au",
   "local:gleif-relationships"
  ]
 },
 {
  "key": "acn:005190036",
  "legal_names": [
   "BALL & DOGGETT PTY LTD"
  ],
  "sources": [
   "local:gleif-lei-au",
   "local:gleif-relationships"
  ]
 },
 {
  "key": "acn:088051889",
  "legal_names": [
   "BLACKROCK TACTICAL GROWTH FUND"
  ],
  "sources": [
   "local:gleif-lei-au",
   "local:gleif-relationships"
  ]
 },
 {
  "key": "acn:127015472",
  "legal_names": [
   "VANGUARD INTERNATIONAL SMALL COMPANIES INDEX FUND"
  ],
  "sources": [
   "local:gleif-lei-au",
   "local:gleif-relationships"
  ]
 },
 {
  "key": "acn:166771875",
  "legal_names": [
   "ADVANCE DEFENSIVE YIELD MULTI-BLEND FUND"
  ],
  "sources": [
   "local:gleif-lei-au",
   "local:gleif-relationships"
  ]
 },
 {
  "key": "abn:77662944978",
  "legal_names": [
   "The Trustee for Westgate Finance Trust"
  ],
  "sources": [
   "local:gleif-lei-au",
   "local:gleif-relationships"
  ]
 },
 {
  "key": "abn:34127863159",
  "legal_names": [
   "Medical Deans Australia And New Zealand Incorporated"
  ],
  "sources": [
   "data.gov.au:acnc-register",
   "qld:queensland-government-contracts-directory-awarded-contracts"
  ]
 }
]
```
## cycle_check

```cypher
MATCH p = (a:Party)-[:OWNS*2..6]->(a) RETURN a.key AS key, length(p) AS cycle_length LIMIT 5
```
0 rows, 236.2 ms

```json
[]
```