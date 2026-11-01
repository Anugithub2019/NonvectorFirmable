# Write-up

Two pages. Numbers marked **[measured]** come from `outputs/`; **[estimated]** is a guess with its basis.

## 1. What lives where, and what that cost

- **Neo4j** holds the resolved graph: `Party` (Organisation/Person), `Name`, `Licence`, `Ban`,
  `SourceRecord`, and the edges between them. It answers traversals: ultimate parent, within-N-hops,
  the `resolve` name index.
- **DuckDB** holds the raw rows (verbatim; a re-ingested version supersedes the old one into
  `source_records_history` / `observations_history`, so nothing a source ever said is lost), every
  observation, links, abstentions, and the flat views (`v_party`, `v_licence`, `v_ban`) that
  Data-retriever projections read. It does the blocking and the bulk joins.
- **No vector store.** Candidates come from identifiers, exact normalised names and a Lucene
  full-text index; the decision model scores the top few. Embedding-similarity retrieval was
  rejected on purpose (case study 2's own warning), and nothing in the five questions needs it.
- **Consistency: solved by direction, deferred by time.** Neo4j is a derived artefact of DuckDB:
  each load `MERGE`s on unique keys, stamps what it touched with a `load_id`, and sweeps every
  derived node or edge it did not touch, so the graph equals the DuckDB state after a re-resolution
  (a record that moved from party A to B has one `RESOLVED_TO`; a merged-away party is gone —
  `tests/test_loader.py`). `party_attrs` is computed once in SQL and written to both, so the table
  a user exports and the node they click cannot disagree. What is deferred:
  the two stores are not updated transactionally — between `graph resolve` and `graph load` the
  graph is stale. For a weekly batch that is acceptable; for streaming updates it is not, and the
  fix is an outbox table in DuckDB that the loader drains.
- **Cost of the split:** two query languages, two deployables, and the projection layer cannot use
  graph predicates directly — it fetches a key set from Neo4j and filters in DuckDB
  (`graph_filter` in `ProjectionSpec`). That is the price of flat, stable, hashed exports.

## 2. The threshold

- Exact identifier path: 0.99, no threshold to set. Semantic path: link when Jev's P(same party)
  ≥ **0.85**; sensitive sources (ASIC bans) ≥ **0.95**; persons never by name.
- Measured at 0.85 **[measured, `outputs/evaluation.md`]**: 88 links labelled blind by two models;
  **0 incorrect** among the 78 both labellers agreed on; Gemini Pro alone — the labeller that had
  no part in matching (Jev scored the semantic links, so it is not independent for them) — says
  "same" on every decided link. These are sample proportions, not population guarantees: the
  Wilson 95% lower bounds are 0.85 for exact ABN (n=21), 0.87 for the ABR bridge (n=25), 0.65 for
  semantic (7/7 decided, 1 unresolved) and 0.51 for exact-normalised name (4/4 decided, 4 unresolved
  — contract suppliers whose record carries only a name). Small groups, wide intervals; that is
  what the numbers can and cannot say.
- Recall of the semantic path, measured **against the full index** (every other record, 555k;
  hidden-identifier test, n = 150): candidate recall **0.913**, ranking accuracy given a candidate
  **0.985**, acceptance at 0.85 **0.887**, false accepts **0.0**. So blocking costs ~9% of
  recoverable matches, ranking ~1%, the threshold ~1% — and nothing wrong would have been linked.
  An earlier version of this test used a 2,000-record background and reported 0.96; that number
  flattered blocking and is withdrawn.
- `resolve` benchmark (200 messy references, 12 absent), outcomes kept apart: **resolved accuracy
  0.91** (171/188 present references), **0 resolved to a wrong key**; 2 ambiguous, and both times
  the right entity was among the options; 15 abstained although present; all 12 absent references
  abstained. Identifiers with spaces, lower case, dropped legal forms, abbreviations, trading/former
  names: 21/21 each. **Single-character typos: 7/21** — of the 14 misses, 13 reach the candidate set
  and rank first but Jev's P(same) sits at 0.6–0.8, under the threshold; 1 never reaches the
  candidates. That is the weak spot, and a deliberate one: lowering the threshold to catch typos
  would also admit "ACME 1 PTY LTD" vs "ACME 2 PTY LTD" (string similarity 0.98).
- What a customer sees at each error type: a **false link** shows a licence, ban or owner on the
  wrong company's page — for a ban that is a published accusation, which is why bans get 0.95 and
  a name-only ban never links. A **missed link** shows an entity with fewer sources than it should
  have, and the record sits in the abstention queue with its best candidate, visible in the demo.
  The second is recoverable by a reviewer; the first is a correction after the fact.
- The two named cases: *Commonwealth Bank of Australia* and *Commonwealth Superannuation
  Corporation* each resolve to their own entity (exact normalised name, 0.95). `CBA` resolves to the
  bank via the semantic path (Jev 0.86; runner-up "CBA BUILDING SOLUTIONS" 0.32). `Commonwealth
  Super Corp` **abstains** (best candidate the Corporation at 0.56): the system would rather not
  guess an abbreviation. Neither case leaks into the other.

## 3. Extension

- **New relationship type** ("audited by"): add one enum value to `related_party.relationship`
  in `firmable_ontology.yaml` and one entry in `REL_EDGE` in `neo4j_loader.py`. The onboarding
  agent can then map a source to it; the edge carries the standard provenance slots. Reprocess:
  only that source's observations.
- **New entity type** ("Property"): one section in the observation ontology (as `licence` was
  added for this task), one class in `schema.yaml`, one loader rule. Nothing existing is touched.
- The component you touch is always the ontology file first; the loader rule second; never the
  resolver or the agent — they read the ontology.

## 4. Reprocess economics (the question you care most about)

Six months on, the matcher improves. Millions of links were made by the old one. What we do:

1. **Nothing is re-run over the corpus by default.** Every link carries `matcher_version`,
   `threshold`, `confidence` and the `evidence` object (string similarity, Jev probability, which
   fields agreed). Recalibrating a threshold is a query: `SELECT … FROM links WHERE
   matcher_version = 'resolver-0.1.0' AND confidence BETWEEN old AND new` — those are the only
   links whose decision flips, and the `RESOLVED_TO` edges to cut or add.
2. **A new scoring model** is run only on the *candidate pairs* that were ever scored (they are in
   the evidence: `candidate_record`), not on the blocking universe. New scores are written as a new
   `matcher_version`; the old ones stay. Promotion is a swap of which version the graph's
   `RESOLVED_TO` edges point at.
3. **Blocking changes** are the expensive case: a new blocking key can surface pairs never scored.
   Then the re-run is bounded to records whose key set changed, which the normalisation version
   stamped on each record identifies.

What had to be recorded in advance for this to work: the source records (never deleted), the
evidence per link (not just the score), the matcher and threshold per link, and the abstentions
with their best candidate — an abstained record is a future link under a better matcher, and
without its best candidate you would have to block it again.

## 5. Time

- Already modelled: `valid_from` / `valid_to` on `HOLDS`, `SUBJECT_OF`, `OWNS`, `KNOWN_AS`; status and
  end dates on `Licence` and `Ban`; `observed_at` on every claim. "Was X banned on date D" and
  "what was X called in 2019" are filters.
- Not modelled: point-in-time backbone attributes (an ABN's status on a date; an address on a
  date). The ABR extract is a weekly snapshot; to answer "what was true on D" for those, keep each
  weekly extract as a version (the parquet is 300 MB; 52 versions is 16 GB, cheap) and give
  `SourceRecord` a `valid_from = extract_date`, superseded by the next extract's row for the same
  ABN. The loader already keys on `(record_key, content_hash)`, so unchanged rows cost nothing.
- Merges, splits, renames: `SUCCESSOR_OF` and former names with validity cover renames and
  successions where a source states them (ASIC former names, GLEIF successor); splits need a
  `SPLIT_INTO` edge type — an extension, not a rebuild.

## 6. Scale

What breaks first between this slice and 15M companies with a billion edges:

1. **The blocking index** — an in-process dict (`resolver.py`). At 15M it becomes a DuckDB table
   keyed by blocking key with a `count` to skip hubs, and the semantic pass becomes a join.
2. **`SourceRecord` nodes** — ~5 per party. At 15M companies that label alone is 75M+ nodes; keep
   them in DuckDB and put `RESOLVED_TO` provenance as a property list on the party, or shard.
3. **`within_hops` over hub parties** — a bank with thousands of subsidiaries makes `*1..2` fan out;
   the cap on returned rows does not cap the work. Needs a degree-aware traversal (skip hubs
   above a degree, or precompute 2-hop ban neighbourhoods nightly).
4. Jev cost is linear in scored pairs, not in corpus size — blocking keeps it bounded.

## 7. Licence

- Usable commercially (CC-BY / CC0): ABR bulk extract, ASIC company register, AFS, credit,
  banned-organisations, liquidator datasets (data.gov.au, CC-BY 3.0 AU), GLEIF (CC0), ACNC
  (CC-BY), QBCC / SOR / QLD contracts (CC-BY 4.0), NSW liquor (CC-BY).
- Checked how: the CKAN `license_id` on every dataset is copied into each config
  (`dataset.licence`) and onto every observation and `SourceRecord`; a missing licence is a
  flagged finding, not a blocker. GLEIF's terms are on its site.
- Skipped: ACCC infringement notices (web page; automated access is blocked and the site's terms
  were not reviewed) and TGA ARTG (export-only, licence not confirmed). annualreports.com is not an
  open licence and was not used. The Victorian Building Practitioner Register appeared in triage
  with `other-closed` and was excluded for that reason.

## 8. Next (three weeks)

First: **human labels and a calibration curve.** The precision numbers here are model-labelled.
Three weeks buys a few hundred human labels per match type, which turns the threshold from a
chosen number into a measured operating point, and lets Jev's probabilities be checked for
calibration on this data. Then: an outbox-driven incremental load (no stale window), the
degree-aware traversal, and the ACCC page as the first prose-only source through the onboarding
agent.

## Cost

$11.01 of API spend in total across both case studies (`outputs/usage.jsonl`), ≈ $6.9 for this
task (the second evaluation run, against the full index, cost $0.3). Onboarding a source with the agent costs $0.20–0.70 depending on how many revision and review
rounds it takes; resolution scored ~59k candidate pairs with Jev for $1.9 (cached, never repeated);
the model reviewer and the blind labels cost $0.81 on Gemini Pro. Extraction, resolution of
identifier matches and every graph query cost nothing in model calls.

## How the parts were built

The ingestion layer (triage, onboarding agent, extractor) was built against case study 1 first,
then extended (ontology v0.2: licences, bans, related parties, LEI) for this task. The graph,
resolution, lookup and the two-mode agent were built for this task. Total API spend across both:
see `outputs/usage.jsonl` and README.
