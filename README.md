# Firmable market graph — agentic ingestion, entity resolution, two-mode retrieval agent

Public Australian business registers → an agent-built ingestion layer → a resolved entity graph
(Neo4j + DuckDB) → an agent that either **answers a question** or **hands you a stable table**.

- Start with [`docs/CONCEPTS.md`](docs/CONCEPTS.md) (the ideas) and
  [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) (diagrams).
- The model: [`ontology/schema.yaml`](ontology/schema.yaml) with reasoning in
  [`ontology/NOTES.md`](ontology/NOTES.md). The write-up: [`WRITEUP.md`](WRITEUP.md).
- Measurements: [`outputs/evaluation.md`](outputs/evaluation.md),
  [`outputs/performance.md`](outputs/performance.md), [`outputs/graph_queries.md`](outputs/graph_queries.md).

## Run it from a clean checkout (< 10 minutes to a working demo on the shipped outputs)

```bash
# 0. prerequisites: Docker Desktop running, uv (https://docs.astral.sh/uv/), a Gemini key, an OpenRouter key (for Jev)
cp .env.example .env            # then fill GOOGLE_API_KEY and OPENROUTER_API_KEY
uv sync                         # python 3.12 env with every dependency

# 1. the graph database
docker compose up -d            # Neo4j 5 community at http://localhost:7474 (neo4j / firmable-graph)

# 2. the data. EITHER load the shipped outputs (fast)…
uv run python -m firmable graph store     # observations -> DuckDB (data/firmable.duckdb)
uv run python -m firmable graph resolve   # links, abstentions, parties  (~minutes; uses Jev)
uv run python -m firmable graph load      # DuckDB -> Neo4j, reconciling load (stamps + sweeps stale nodes/edges)

# …OR rebuild everything from the public sources (≈ 1 h incl. 1 GB ABR download; see "Full rebuild")

# 3. use it
uv run python -m firmable chat                       # terminal chat, both modes
uv run streamlit run demo/app.py                     # the demo (http://localhost:8501)
uv run python -m firmable evaluate                   # labels, recall test, 200-reference benchmark, reports
uv run pytest -q                                     # tests: transforms, resolver, agent control flow, projections, store history (loader test needs `docker compose --profile test up -d neo4j-test`)
```

The demo pages (sidebar): **Chat** (mode toggle: auto / intelligent / retriever; example prompts; the input stays pinned at the bottom and the newest answer scrolls into view), **Resolve** (ranked candidates,
match type, score, evidence, the Cypher that found them), **Entity** (identifiers, source records,
licences, bans, owners, subsidiaries; click through), **Traversals** (ultimate parent, within-N-hops
of a ban), **Abstentions**, **Datasets** (exports from Data-retriever mode).

### Full rebuild from sources

```bash
uv run python -m firmable triage                         # (optional) discover + rank data.gov.au datasets
uv run python -m firmable abr-parse                      # stream the two ABR zips -> data/raw/abr/abr_all.parquet (20.6M rows)
uv run python -m firmable slice                          # tier-1 slice CSVs (ABR + ASIC companies)
uv run python -m firmable onboard --all --auto-review    # the agent maps every source in sources.yaml; Gemini Pro approves
uv run python -m firmable extract --limit 0              # configs + raw files -> outputs/observations/*.jsonl
uv run python -m firmable graph all                      # store, resolve, load
```

Downloads are done by the onboarding agent (CKAN resources) except the ABR zips and GLEIF
(`src/firmable/ingest/abr.py`, `gleif.py`), which are fetched by their own readers.

## What is agentic here, and what is deliberately not

| Agentic (a model decides at runtime) | Deterministic (code) |
|---|---|
| **Onboarding a source**: inspect the file (format, sheet, header row, encoding), profile columns, propose a mapping to the ontology, validate it by running the real extractor on 1,000 unseen rows, read the failures, revise (≤3), submit for review. A new source needs no code. | the extractor (config + file → observations); the transform library the agent composes from; checksums; slicing |
| **Approval**: a higher-tier model (Gemini 3.1 Pro) reads the same review screen a human would and approves or rejects with instructions (`provenance.approved_by`) | static checks on every proposal (unknown columns, enum violations, bad args) |
| **Per-field confidence**: Jev (decision model) gives P(mapping correct) per field, blind to the proposer | |
| **Semantic matching**: Jev gives P(same party) for the top candidates | exact identifier joins; blocking; arbitration rule |
| **Routing and guidance**: Jev decides what the user wants and whether it is specific enough; Gemini writes the clarifying question | |
| **Intelligent agent**: tool-calling over the graph API | the tools themselves, caps, read-only Cypher guard, **and the control flow**: an ambiguous/abstained resolve halts the turn in code; typed tools accept only resolved, user-chosen or previously shown keys; the budget counts real calls and seconds |
| **Data retriever**: natural language → typed projection spec | spec validation (invalid columns/filters rejected, never dropped), restatement generated from the validated spec, SQL with total ordering, pinned `as_of` + data generation, hashing, export |

Which guarantees are enforced by code (with the test that proves each) and which remain prompt
behaviour is tabled in `docs/ARCHITECTURE.md` §5.

## Sources

| source | tier | rows used | licence | how it got in |
|---|---|---|---|---|
| ABR bulk extract (ATO) | 1 | 64,484 of 20.6M (slice) | CC-BY 3.0 AU | own XML reader → slice → agent |
| ASIC company register | 1 | 80,188 rows incl. 18,231 former names (slice) | CC-BY 3.0 AU | slice → agent |
| ASIC AFS licensees | 2 | 6,541 | CC-BY 3.0 AU | agent |
| ASIC credit licensees | 2 | 4,308 | CC-BY 3.0 AU | agent |
| ASIC banned & disqualified organisations | 2 | 15 | CC-BY 3.0 AU | agent |
| ASIC registered liquidators (people + firms) | 2 | 662 | CC-BY 3.0 AU | agent |
| GLEIF Level 1 (AU) + Level 2 relationships | 2 | 53,604 + parents | CC0 | own API reader → agent |
| ACNC charities | extra | 66,514 | CC-BY | agent |
| QBCC licensed contractors (QLD) | extra | 205,535 | CC-BY 4.0 | agent |
| QLD Suitable Operator Register | extra | 15,128 | CC-BY 4.0 | agent |
| QLD Government contracts (name-only) | extra | 45,752 | CC-BY 4.0 | agent |
| NSW liquor licence premises | extra | 18,747 | CC-BY | agent |

**Skipped and why.** ACCC infringement notices: a web page, not a download; automated access is
refused (HTTP 403) and we chose not to work around it. TGA ARTG: search-tool CSV exports only,
licence not confirmed. annualreports.com: not open data. ABR individuals / sole traders outside
the slice: volume. Victorian Building Practitioner Register: `other-closed` licence.

**The tier-1 slice** (`src/firmable/ingest/slices.py`): ABR records that are *active*,
*companies* (PRV/PUB), in *QLD*, postcodes *4000–4039* (Brisbane CBD + inner: 50,101 rows) **plus**
every ABR record whose ABN/ACN is carried by a tier-2 source (14,383 rows), so keyed attachment is
testable end to end. ASIC rows whose ACN is in that set (80,188 incl. former names). The extra
state/charity registers attach only where they fall inside the slice; their other records become
singleton parties with their own identifiers. This is ~1/300 of the national backbone; the
write-up says what changes at full scale.

## Results

**Measured** on the shipped outputs (details and method in `outputs/evaluation.md`, `outputs/performance.md`).

| | |
|---|---|
| sources onboarded by the agent | 13 (`configs/`), each approved by the model reviewer with provenance |
| source records / observations | 567,794 / 5.3 M (`data/firmable.duckdb`) |
| parties | 352,368 (251,727 organisations, 130,147 persons incl. stubs in Neo4j) |
| links by path | exact ABN 345,605 · exact ACN 43,109 · ABR bridge 14,034 · exact LEI 3,655 · exact-normalised name (cross-source) 8,936 · semantic/Jev 729 · same-source same-name collapse 28,927 · singleton 110,551 |
| abstentions | 139,479: persons never linked by name 96,068 · below threshold 34,423 · no candidate in block 8,964 · identifier conflict 1 (+ 67 parties flagged `identifier_conflicts`) |
| graph | 567,794 SourceRecord · 353,413 Party (223,266 organisations incl. 1,045 identifier-keyed stubs, 130,147 persons) · 369,439 Name · 126,424 Licence · 15 Ban; 555,546 RESOLVED_TO · 511,590 KNOWN_AS · 163,347 HOLDS · 3,847 OWNS · 2,642 RELATED_TO · 503 AFFILIATED_WITH · 15 SUBJECT_OF |
| link precision (88 links, labelled blind by Gemini Pro + Jev) | **0 incorrect** among the 78 both labellers decided; Gemini Pro alone (the labeller independent of the matcher): 1.0 in every group. These are sample proportions: Wilson 95% lower bounds are 0.85 (exact ABN, n=21), 0.87 (ABR bridge, n=25), 0.65 (semantic, 7/7 decided), 0.51 (exact-normalised name, 4/4 decided, 4 unresolved) |
| semantic-path recall (hidden identifier, n = 150, **against the full 555k-record index**) | candidate recall 0.913 · ranking accuracy 0.985 · acceptance at 0.85: **0.887** · false accepts **0.0**. Misses: 13 lost at blocking, 2 at ranking, 2 at threshold |
| `resolve` benchmark (200 messy references incl. 12 absent) | resolved accuracy **0.91** (171/188 present), **0 wrong resolves**; 2 asked (right option offered both times); 15 abstained though present, 14 of them typos; 12/12 absent abstained. Typos: 7/21 resolved, 13 fall below threshold, 1 never reaches the candidate set |
| `resolve` latency | p50 **6 ms** · p95 **1.6 s** (semantic path, model calls) · ≈ $0.02 per 1,000 resolutions (estimated) |
| load | DuckDB store 3 s (incremental) · resolution 35 s with cached pair scores · Neo4j load ≈ 1.5 min incl. the reconcile sweep · rerun on unchanged data: 0 nodes created, 0 deleted |
| API spend | **$11.01** in total across both case studies, of which ≈ **$6.9** for this task (onboarding $7.8 incl. case study 1, resolution $1.9 for ~59k pair scores, evaluation $0.5, agent $0.4, review $0.2, triage $0.2); `outputs/usage.jsonl` has every call |

The first *reconciling* load (loader stamps every node/edge with a `load_id` and sweeps what the run did not touch) removed **28,461 stale Party nodes** and 7 edges that earlier `MERGE`-only loads had left behind from a previous resolution run — the earlier "382k Party" figure was that debris. `tests/test_loader.py` proves the sweep on a scratch Neo4j (record moves A→B, party merges away, name dropped).

Things the run surfaced that are findings, not bugs: one ACN sitting under two different ABNs (67 such parties, kept apart and flagged); an ACNC placeholder string "THIS CHARITY HAS A SUB ENTITY" used as a name by 56 charities; contract supplier names truncated at 40 characters in the QLD contracts register; no banned organisation in the slice has any recorded ownership or affiliation edge, so "within 2 hops of a ban" is an honest zero on this data (the demo says so and offers the GLEIF ownership neighbourhoods instead).

## Decisions and assumptions

- **Storage**: Neo4j for the resolved graph, DuckDB for raw rows, claims, links, abstentions and
  the flat views. No vector store. Reasoning in `WRITEUP.md` §1.
- **Two party types** (Organisation, Person) under one `Party` label; persons are never linked by
  name alone. `ontology/NOTES.md`.
- **Thresholds**: exact identifiers 0.99; semantic P(same) ≥ 0.85; bans ≥ 0.95. `WRITEUP.md` §2.
- **Labels are model labels** (Gemini Pro + Jev, blind, agreement reported, disagreements not
  counted as correct). No human labelled anything in this repo; `labels/README.md`.
- **Approval is model approval**: every config records `approved_by: model:gemini-3.1-pro-preview`.
  The review step is built for a human (`python -m firmable review <slug>`) and was exercised by a
  model to fit the time budget.
- **observed_at**: per-record where the source states it; otherwise the resource's last-modified
  date, flagged on the claim.
- **Record ids**: the source's natural key when the agent finds one and validation confirms
  uniqueness on held-out rows, else a deterministic hash of the raw row.

## Repository layout

```
README.md  WRITEUP.md  docker-compose.yml  sources.yaml  pyproject.toml
ontology/      schema.yaml (graph), firmable_ontology.yaml (observations, v0.2), graph.cypher (DDL), NOTES.md
src/firmable/
  ingest/      ckan, readers (csv/tsv/xlsx/xls/json/xml), transforms, extractor, triage, slices, abr, gleif
  ingest/onboarding/   the LangGraph onboarding agent: nodes, graph, prompts, schemas, review
  resolve/     normalise (names, blocking keys), resolver (exact + semantic paths, arbitration)
  graph/       store (DuckDB), neo4j_loader, pipeline
  retrieval/   graph_api (resolve/entity/traversals/cypher/projection), agent (two modes), cli
  evaluate/    labels, recall test, benchmark, report writers
configs/       agent-generated mapping configs (one per source), with provenance
demo/          Streamlit app + Dockerfile
outputs/       load_report.csv, links.jsonl.gz, abstentions.jsonl.gz, evaluation.md, resolve_results.jsonl.gz,
               graph_queries.md, performance.md, observations/*.jsonl.gz, onboarding/ (per-source run reports), usage.jsonl
               (the large JSONL files ship gzipped; `graph resolve` regenerates the plain ones)
labels/        links_sample.jsonl (model labels), dirty_references.jsonl, recall test rows
tests/         transforms, resolver, agent control flow (mocked), graph API (live), loader reconciliation (scratch Neo4j), store history
data/          (git-ignored) raw downloads, abr parquet, firmable.duckdb; Neo4j data lives in the docker volume neo4j_data
```

## Known issues

- Persons' names from the liquidator register stay in `SURNAME, GIVEN` form (the reviewer noted
  it; no transform reorders them yet).
- `resolve` recovers only 7/21 single-character typos. The benchmark's failure-stage split says
  where: 13 of the 14 misses reach the candidate set and rank first but Jev's P(same) sits under
  0.85; 1 never reaches the candidates. So it is an acceptance problem, not a retrieval one.
  Lowering the threshold would admit "ACME 1" vs "ACME 2"; the fix is a labelled calibration set.
- Within-2-hops-of-a-ban returns nothing on this slice (no banned organisation has ownership or
  affiliation edges); the traversal is exercised on GLEIF ownership neighbourhoods instead.
- `address.state` is empty where a source gives only a postcode; a `state_from_postcode`
  transform would recover it.
- The hosted demo needs a Neo4j that is reachable from the host; AuraDB Free (200k nodes) is too
  small for this graph. `docker compose --profile demo up` runs Neo4j + the app locally; a
  screen recording stands in for a URL.
- The ingestion agent occasionally over-escapes regexes; proposals are normalised before
  validation, and a mapping that matches zero held-out rows is a blocking error.
- The Jev pair-score cache (`data/cache/jev_pairs.jsonl`) is keyed by (record, candidate, model),
  not by record content hash, so a record whose attributes change on re-ingest would reuse the old
  score. The fix is a content hash in the key; it is not applied because it would void the shipped
  cache (~59k pairs, $1.9 to rebuild).
- The Streamlit demo shares one `GraphAPI` (one DuckDB connection, one `gf_keys` temp table) across
  sessions via `st.cache_resource`; concurrent users need a connection per session.
- Neo4j Community has no per-user read-only role: agent Cypher is bounded by read access mode, a
  pattern guard and a server-side transaction timeout, not by database permissions.
- Traversals default to the *current* view (`valid_to`/`end_date` after today); the historical
  view is a parameter. `ultimate_parent` follows one owner per hop by a stated rule and lists the
  others, and says whether the chain was asserted (`ultimately_owned_by`) or walked hop by hop.
