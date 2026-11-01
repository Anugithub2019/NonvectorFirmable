# Ontology notes

Machine-readable model: `schema.yaml` (graph layer) and `firmable_ontology.yaml` (observation
layer, v0.2). Constraints as Neo4j DDL: `graph.cypher`. This note is the reasoning.

## The five questions the model was derived from

| # | Question | What it forced |
|---|---|---|
| Q1 | *Who is this?* — a messy name / ABN / LEI → ranked candidates with evidence | every name variant is searchable with its provenance → `Name` nodes + `KNOWN_AS {kind, source, valid_from, valid_to}`; identifiers are unique, checksummed properties; a full-text index over names |
| Q2 | *Who ultimately owns X?* — follow the chain, terminate safely | `OWNS` is a directed edge parent→child with `kind` (direct / ultimate), `percent`, validity; traversal is one hop at a time with a visited set and a depth cap, so a cycle is reported, not looped |
| Q3 | *Which organisations are within 2 hops of a banned party?* | `Ban` is a node (a party can carry several; each keeps its own source record); a ban attaches to a **person or an organisation**, so both are `Party` and traversals use the super-label; traversal edges exclude `KNOWN_AS` (sharing a name is not a relationship) |
| Q4 | *Which licensees had a licence cancelled in the last N months?* | `Licence` is reified: status, start/end dates, authorisations are its own properties; `HOLDS` carries validity; an index on `(status, end_date)` |
| Q5 | *Give me a stable flat table of a subset* | everything in the graph is also in DuckDB; `party_attrs` is computed once (SQL, by source precedence) and written to both; projections are specs (JSON) with a content hash, so they re-run identically |

Q3 and Q1 are the two that most shaped the schema; Q5 shaped the storage split.

## Node, property, or reified edge

| Candidate | Decision | Why |
|---|---|---|
| Licence | **node** | has number, status, dates, authorisations (list), conditions; several per holder; questions are asked *of the licence* |
| Ban / disqualification | **node** | has type and duration; the wrong-link cost is highest here, so the ban must be cut from a party without touching either |
| Ownership | **edge with properties** | one source (GLEIF) asserts it; `percent`, `kind`, validity fit on the edge. Promote to an `Ownership` node when a second source asserts ownership (then provenance per assertion needs its own identity) |
| Name | **node** | validity time (former names) and provenance per assertion; the resolver's exact-normalised path is a lookup on `Name.normalised` |
| Source record | **node; versions never lost** | one per raw row; resolution adds one `RESOLVED_TO` edge; raw payload in DuckDB, where a re-ingested version supersedes the old one into `source_records_history` rather than deleting it. See *What happens to a source record* |
| State, postcode, locality, industry code, entity type, licence type, ban type | **properties** | as nodes they are hubs: `QLD` would carry ~400k edges at full ABR scale, ~5M at 15M companies; nothing traverses *through* a state |
| Address | property (`address_full` + parts) | no question asks "who else is at this address" yet; when one does, Address becomes a node keyed on a normalised string — an extension point, not a rebuild |

## One party type or two

Two labels, one super-label: `(:Party:Organisation)` and `(:Party:Person)`.

- Liquidators are people (with a registration number and a firm); a sole trader is a person with
  an ABN; a disqualification can attach to either. One label would make "within 2 hops of a
  disqualified *person*" need a property filter on every hop.
- The consequence in resolution: **persons are never linked by name alone across sources**
  (`abstentions.reason = person_name_only`). A person is only merged on an identifier (ABN or a
  register number). This loses recall on people deliberately; 130M people with far more name
  collisions than companies is the scale argument.
- A record is a `Person` when its `entity_type` is `sole_trader` without an ABN or it carries a
  `person.role` (liquidator). Everything else is an `Organisation`.

## What happens to a source record after resolution

It stays. Three places:

1. `SourceRecord` node in Neo4j with `(source_id, record_id, content_hash, observed_at)`.
2. `source_records` row in DuckDB with the full raw payload (JSON) — the only place the raw row
   lives in full, because 100M raw rows do not belong in a graph page cache.
3. `links.jsonl` / `abstentions.jsonl`: the decision about it, with matcher version and threshold.

Why that is safe: resolution is a function from source records to edges. Deleting every
`RESOLVED_TO` edge and re-running reproduces the graph; deleting a wrong edge un-merges without
losing anything. The thing that *would* be unsafe — overwriting a party's attributes in place —
never happens: `party_attrs` is recomputed from member records by precedence on every load.

## Uniqueness constraints and invariants (and what happens on violation)

| Constraint | On violation |
|---|---|
| `Party.key` unique | cannot occur: keys are derived (`abn:` > `acn:` > `lei:` > `src:`) |
| `Organisation.abn`, `.acn`, `.lei` unique where present | the resolver forms parties by identifier equality, so two parties cannot share one. **One ACN under two different ABNs** (seen in the data via ABR rows that disagree): the ACN is removed from the union-find bridge, the ABN-keyed parties stay separate, and every ACN-only record pointing at it is **abstained** with `identifier_conflict`, listing the ABNs claiming it |
| ABN / ACN checksum | a failing identifier is treated as absent at ingest (the `abn`/`acn` transform ops return nothing); the record can still link by name. Counted in `load_report.records_rejected` when the record has no other usable field |
| `Licence.licence_id = type:number` unique | two sources describing one licence MERGE onto one node; properties set by the later load (last-writer); `source_id` on `HOLDS` keeps both assertions |
| `Name.normalised` unique | by construction (MERGE) |
| `SourceRecord -RESOLVED_TO-> Party` is exactly 1 | enforced by the resolver: linked records point at the merged party; abstained records point at their own singleton party (`src:`) or the same-source same-name party, and the refusal is recorded in `abstentions`. A lone identifier-bearing record is a one-member component and carries `exact_<id>` as its match type (it is keyed by its own identifier) |
| one ACN under two legal names | both names become `Name` nodes with `kind: legal` and their source; `display_name` follows precedence (ASIC > ABR > GLEIF > …); `name_conflict = true` on the party and the case is listed in `graph_queries.md` |

## Degree distribution at 15M companies

- **Avoided:** categorical hubs (state, industry, type) are properties.
- **Expected, legitimate:** large corporates (hundreds of licences / subsidiaries), prolific
  liquidators (hundreds of appointments), big law/insolvency firms. Handled by capping every
  neighbourhood read at 25 per section (`retrieval.caps`), most-recent first, with the dropped
  count returned.
- **Watched:** `Name` nodes. Keyed on exact normalised text, so degree is the number of parties
  sharing the *exact* string. The loader logs every Name with degree > 50
  (`neo4j_load_report.json → hot_names_over_50`); generic strings ("THE TRUSTEE FOR THE FAMILY
  TRUST") are the ones that appear, and those tokens are excluded from blocking keys so they
  never drive a semantic match.
- **Would hurt first:** `SourceRecord` count (one per raw row across all sources, ~5× the party
  count). At 15M companies that is the label to shard or to keep as DuckDB rows only, with
  `RESOLVED_TO` becoming a property list on the party. Second: `Name`, at ~1.5 names per party.

## Extension points

| Arrives next month | What changes | What is reprocessed |
|---|---|---|
| a new relationship type (e.g. "audited by") | one enum value in `related_party.relationship`, one line in `loader_rules` / `REL_EDGE`; the edge carries the standard provenance slots | only the new source's observations |
| a new entity type (e.g. "Property") | one section in `firmable_ontology.yaml` (as `licence` was added), one class in `schema.yaml`, one loader rule | nothing existing |
| ownership from a second source | `OWNS` edge → `Ownership` node with `ASSERTED_BY → SourceRecord` | ownership edges only |
| people at scale | `Person` only from sources with a register number / ABN; name-only persons stay singleton `SourceRecord`s | nothing |

## What was taken, and rejected, from existing vocabularies

- **schema.org** `Organization` / `Person` / `legalName` / `alternateName` / `taxID` /
  `parentOrganization`: taken as naming guidance (two party types; `legal` vs `trading` name
  kinds). Rejected its address-as-node default (`PostalAddress`) for the degree reason above.
- **W3C Org ontology** (`org:Organization`, `org:memberOf`, `org:ChangeEvent`): `AFFILIATED_WITH
  {role}` is `org:Membership` collapsed to an edge (reify when memberships need their own
  attributes); `org:ChangeEvent` is the model for `SUCCESSOR_OF` and for former names with
  validity. Rejected `org:OrganizationalUnit` — no source distinguishes units.
- **GLEIF CDF / RR**: the `OWNS` edge is the Level-2 relationship record (direct vs ultimate
  parent, percent, validity period, registration status); `registeredAs` is the bridge to
  ACN/ABN. Rejected carrying GLEIF's full relationship-period taxonomy; one `valid_from/to` pair
  suffices until a question needs more.
- **FIBO** (`LegalEntity`, `hasLegalName`, `isControlledBy`): consulted for the
  control/ownership distinction; rejected as a whole because its depth is not earned by these
  sources.

## Match-type vocabulary (`links.jsonl`)

`exact_abn`, `exact_acn`, `exact_lei`, `exact_registered_as`, `bridge_abr_acn` — deterministic.
`name_exact_norm`, `name_semantic` — the semantic path (cross-source). `name_exact_norm_same_source` —
identical normalised name within ONE source, collapsed to one party (a contracts register listing the
same supplier on every contract); never applied across sources or to persons. `singleton` — no link;
own party. A deterministic join and a fuzzy match never share a label, by construction.
