# Performance

Generated 2026-11-01T11:10:43+00:00. **measured** unless marked *estimated*.

## resolve()

- p50 **6.3 ms**, p95 **1551.1 ms**, mean 287.6 ms over 200 references (measured, local Neo4j in Docker, M-series Mac)
- of which model calls: only the semantic path calls Jev (≤ 6 candidates), ~6.6 calls × ~0.91 s
- cost per 1,000 resolutions: **$0.0385** *estimated* = Jev at $0.000024/call × calls per resolve × share of references that reach the semantic path (0.24) + compute (a t3.medium-class VM at ~$0.05/h amortised over ~50 resolves/s ≈ $0.0003/1000)

## Load

| step | seconds |
|---|---|
| schema | 0.1 |
| parties | 27.3 |
| names | 22.0 |
| source_records | 26.3 |
| licences | 8.4 |
| bans | 0.1 |
| related | 0.8 |
| reconcile | 2.7 |

## Size on disk

- Neo4j: n/a
- DuckDB: 921 MB (measured)

## Rerun cost (idempotency)

Re-loading an unchanged source: DuckDB skips rows whose (record_key, content_hash) already exist; Neo4j MERGEs find every node and relationship and set no new properties. Measured on a second `graph load` run — see `outputs/neo4j_load_report.json` (nodes_created = 0).