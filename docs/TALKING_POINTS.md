# Talking points — explaining this system in a conversation

Short answers to the questions an interviewer is likely to ask, in the order they usually come.
Each points at the file that proves it.

## "Walk me through it in one minute"

Public registers (ABR, ASIC, GLEIF, state registers) come in through an **onboarding agent** that
works out each file's shape, proposes a mapping to our ontology, tests the mapping on rows it has
not seen, fixes its own mistakes, and submits it for approval. One generic extractor then turns
every source into **observations**: claims with provenance, never overwritten. A **resolver**
joins records into parties: by checksum-valid identifiers where it can, by names + a calibrated
decision model where it must, and it refuses when unsure. The result is loaded into **Neo4j**
(the graph you traverse) and **DuckDB** (the raw rows, links and flat tables). On top sits an
**agent with two modes**: answer a question with evidence, or build a stable table you can take
away. Nothing is embedded; every answer carries the query that produced it.

## "Why is this agentic and not just scripts?"

Because adding a seventh source needs no new code. `python -m firmable onboard <portal> <id>`
makes the agent inspect, map, validate, revise and submit. The mapping configs in `configs/` were
written by the agent, and each one records who approved it. The deterministic parts — the
extractor, checksums, slicing, the transform library — are deliberately *not* agentic: they are
what the agent composes from. (`README.md` → "What is agentic here".)

## "Why Neo4j *and* DuckDB?"

They are good at different things. Neo4j answers "who is within two hops of a banned party" and
"who ultimately owns this" — traversals. DuckDB holds millions of raw rows, does the blocking
joins and writes flat exports — columnar work. The graph is derived from DuckDB and rebuilt
idempotently, so they cannot disagree about a party's attributes (`party_attrs` is computed once,
in SQL, and written to both). The cost: two systems, and a stale window between resolve and load.
(`WRITEUP.md` §1.)

## "Why no vector database?"

Nothing in the five questions the graph must answer needs semantic similarity over text. Entity
lookup is identifiers → exact normalised names → a full-text index over every name variant → a
decision model on the top few. Embedding a subgraph and hoping similarity finds the neighbourhood
is the approach the brief itself warns stops working at scale. (`docs/CONCEPTS.md` §3.)

## "How do you avoid wrong links?"

Three rules. Identifiers beat names: a checksum-valid ABN or ACN match is the only 0.99 link.
Names need a calibrated probability from the decision model above a threshold — higher for
sources where a wrong link is an accusation (bans), never for people. And an identifier conflict
beats any name similarity: two different valid ABNs means never merge, whatever the names say.
Everything below threshold goes to the **abstention queue** with its best candidate and the
reason — that queue is a product, not a log. (`src/firmable/resolve/resolver.py`,
`outputs/abstentions.jsonl`, the demo's Abstentions page.)

## "What is Jev and why use it?"

A decision model: you give it a typed question (yes/no, choose one, score) and structured context,
and it returns a **calibrated probability**, not prose. Generative models are bad at this — ask
one for its confidence and it says 0.9 regardless. We use Jev wherever the *number* is the
product: dataset triage confidence, per-field mapping confidence, P(same party) for links, and
routing the user's request. Gemini still writes the text: mappings, review notes, answers,
Cypher. (`docs/ARCHITECTURE.md` §5 table; every Jev call is in `outputs/usage.jsonl`.)

## "How do you measure it, and who labelled?"

No human labelled anything, and the write-up says so. Two models that did not make the links —
Gemini 3.1 Pro and Jev — label a stratified sample **blind** (they see the two records'
attributes, not the system's decision; identifiers hidden for name-path links). Agreement is
reported; disagreements are never counted as correct. Gemini Pro is the independent one — Jev also
scored the semantic links, so Pro-only numbers are shown too — and the precision figures are
sample proportions with Wilson 95% lower bounds, not population claims. Recall is measured without
labels at all: hide a record's identifier and see whether the name path finds the same party,
against the *full* index, reported per stage (candidates → ranking → acceptance, plus false
accepts). The 200-reference benchmark has 12 references that are not in the graph; abstaining on
those is the correct output, and "asked the user" is reported separately from "resolved".
(`outputs/evaluation.md`, `labels/README.md`.)

## "What happens when the matcher improves in six months?"

Nothing is re-run by default. Every link carries its matcher version, threshold, score and the
evidence (which candidate, what similarity, what probability). Recalibrating a threshold is a
`WHERE confidence BETWEEN old AND new` query over `links` — those are the only edges that flip.
A new scoring model is run over the candidate pairs that were ever scored, not the corpus, and
written as a new matcher version alongside the old one. Source records are never deleted, so any
merge can be undone. (`WRITEUP.md` §4.)

## "Two modes — what is the difference, and how does the agent guide the user?"

*Intelligent agent* answers one question: it must resolve the name first, and if the graph offers
two plausible entities — or none above threshold — the **code** stops the tool loop and asks; the
model does not get to pick. The typed tools only accept keys that were resolved, chosen by the
user, or returned by an earlier tool, so an invented or ambiguous key is refused. The answer cites
keys, source records and match types, and ends with what it could not determine. *Data retriever*
produces a dataset: natural language becomes a typed spec validated against real columns — an
invalid column or filter is rejected, never silently dropped — the user sees how many rows match,
how many the export will hold, a preview, and a restatement generated *from the validated spec*;
only on "yes" is a CSV + Parquet + spec file written, with the `as_of` date and data generation
pinned so a re-run on the same generation gives the same bytes. Guidance is the same mechanism in
both: Jev estimates whether the request is specific enough; if not, one question with concrete
options from the graph. Which of these are enforced by code and which are prompt behaviour is
tabled in `docs/ARCHITECTURE.md` §5, each with the test that proves it.

## "What did you leave out, and why?"

ACCC infringement notices (a web page that blocks automated access — we did not work around it),
TGA ARTG (export-only, licence unconfirmed), annualreports.com (not open). The tier-1 slice is
Brisbane inner-city active companies plus the backbone record for every tier-2 identifier —
small enough to iterate on, large enough that blocking is real; the write-up names what breaks
first at 15M. (`README.md` → Sources, `WRITEUP.md` §6.)

## "What would you do with three more weeks?"

Human labels and a calibration curve first — the thresholds are chosen numbers today, they
should be measured operating points. Then incremental loads through an outbox (no stale window),
a degree-aware traversal for hub companies, and the ACCC page as the first prose-only source
through the onboarding agent. (`WRITEUP.md` §8.)

## Numbers to have in your head

Fill these from `outputs/` before the conversation:

| | value | from |
|---|---|---|
| sources onboarded by the agent | 13 configs (11 CKAN/local registers + 2 GLEIF) | `configs/` |
| tier-1 slice | 64,484 ABR + 80,188 ASIC rows (Brisbane 4000–4039 active companies + every tier-2 identifier) | `data/raw/_tier/slice_report.json` |
| source records / observations | 567,794 / 5.3M | DuckDB |
| parties / links / abstentions | 352k parties; 556k resolved records (416k by identifier or cross-source name, 29k same-source collapse, 111k singletons); 139k abstentions (96k persons never linked by name, 34k below threshold, 9k no candidate) | `outputs/resolution_report.json` |
| link types | exact ABN 345,605 · exact ACN 43,109 · ABR bridge 14,034 · LEI 3,655 · exact-normalised name 8,936 · semantic (Jev) 730 | `outputs/links.jsonl` |
| Neo4j | 353k Party (223k org incl. 1k stubs, 130k person), 369k Name, 568k SourceRecord, 126k Licence, 15 Ban; 556k RESOLVED_TO, 512k KNOWN_AS, 163k HOLDS, 3.8k OWNS, 2.6k RELATED_TO, 503 AFFILIATED_WITH. The first reconciling load removed 28k stale parties from earlier loads | `outputs/load_report.csv`, `neo4j_load_report.json` |
| link precision (model-labelled, blind) | 0 incorrect of 78 decided (88 labelled); Pro-only 1.0 everywhere; Wilson 95% lower: 0.85 ABN · 0.87 bridge · 0.65 semantic · 0.51 exact-name (small n) | `outputs/evaluation.md` |
| semantic recall (hidden-id, n=150, full index) | candidates 0.913 · ranking 0.985 · accepted at 0.85: 0.887 · false accepts 0.0 (the old 0.96 was against a 2k background; withdrawn) | `outputs/evaluation.md` |
| resolve benchmark | resolved accuracy 0.91 (171/188), 0 wrong; 2 asked (both offered the right one); 12/12 absent abstained; typos 7/21 — 13 of 14 misses are below-threshold, not retrieval | `outputs/resolve_results.jsonl` |
| resolve latency | p50 6 ms (exact paths) · p95 1.6 s (semantic path, Jev) | `outputs/performance.md` |
| cost per 1,000 resolutions | ≈ $0.02 (estimated: Jev calls × share reaching the semantic path) | `outputs/performance.md` |
| total API spend | $11.01 across both case studies, ≈ $6.9 for this one (see README) | `outputs/usage.jsonl` |
