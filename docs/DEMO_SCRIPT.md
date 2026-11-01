# Demo script (≈ 2 minutes)

Record with the demo running (`uv run streamlit run demo/app.py`, Neo4j up). Say what each
screen *proves*, not what it shows. Replace the example names with ones from your own graph if
these do not resolve.

| t | Page (sidebar) | Do | Say |
|---|---|---|---|
| 0:00 | Resolve | type `over the top roof restorations` | "A messy name. The exact-normalised path finds the party; evidence shows which name variant matched and the Cypher that ran." |
| 0:15 | Resolve | type `51 824 753 556` (or any ABN from the graph) | "An identifier goes through the checksum, then an exact lookup: 0.99, no model involved." |
| 0:25 | Resolve | type `Commonwealth Bank of Australia`, then `Commonwealth Superannuation Corporation` | "The two named confusion cases. Each has its own exact-normalised name, so neither needs a model to resolve; the decision model only matters for a messy reference like `CBA` or `Commonwealth Super Corp`, where anything under threshold is *abstained*, not guessed." |
| 0:45 | Entity | click **open** on a result | "Identifiers, every source record behind the entity with its match type and confidence, licences, bans, owners. Sections are capped at 25 with the dropped count shown." |
| 1:00 | Traversals | ultimate parent for a GLEIF-owned company (e.g. `ELECTRO OPTIC SYSTEMS PTY. LIMITED`'s key); within 2 hops of a ban | "Two things only a graph answers. The chain is walked one hop at a time with a visited set, so a cycle is reported, not looped." |
| 1:20 | Abstentions | filter `below_threshold` | "Records we believed were businesses and refused to link, each with its best candidate and score. This queue is a product." |
| 1:35 | Chat (intelligent) | ask: *"Does OVER THE TOP ROOF RESTORATIONS hold a building licence, and who else is in its ownership chain?"* (or click an example in the sidebar) | "The agent resolves first, then calls typed tools, and cites keys and match types. If the name were ambiguous it would stop and show numbered candidates; a **use N** button or a reply with the number continues with that entity only." |
| 1:50 | Chat (retriever) | ask: *"Give me QLD companies with a current building licence and more than one source, with ABN, name, postcode"* → **yes** | "Data-retriever mode: a typed spec, a preview with the row count and every assumption, then CSV + Parquet + a re-runnable spec with a content hash. Stable tables, not screenshots." |
| 2:10 | Datasets | show the exported file | "Same spec, same data, same rows — that is what 'stable' means here." |

Closing line: "Everything here is measured in `outputs/`: link precision per match type, recall of
the name path, p50/p95 latency, cost per thousand lookups. Labels are model labels and the
write-up says so."
