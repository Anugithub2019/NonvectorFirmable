#!/bin/zsh
# Orchestrates everything after the onboarding chain: GLEIF prep (if needed), GLEIF onboarding,
# extraction, DuckDB store, resolution, Neo4j load. Markers are written to outputs/pipeline.log.
cd "$(dirname "$0")/.."
until grep -q CHAIN_DONE outputs/onboarding/run_chain.log; do sleep 15; done
if [ ! -s data/raw/gleif/relationships.csv ]; then
  echo "== gleif relationships"
  uv run python -u - <<'PY'
import json, csv
from firmable.ingest import gleif
rows=[json.loads(l) for l in open("data/raw/gleif/lei_au.jsonl")]
with open("data/raw/gleif/lei_au.csv","w",newline="") as f:
    w=csv.DictWriter(f, fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)
leis=[r["lei"] for r in rows if r["has_direct_parent"] or r["has_ultimate_parent"]]
print("level1 rows", len(rows), "| with parents", len(leis), flush=True)
out = gleif.fetch_relationships(leis)
rel=[json.loads(l) for l in open(out)]
with open("data/raw/gleif/relationships.csv","w",newline="") as f:
    w=csv.DictWriter(f, fieldnames=list(rel[0].keys()) if rel else ["child_lei"]); w.writeheader(); w.writerows(rel)
print("relationships", len(rel), flush=True)
PY
fi
for ds in gleif-lei-au gleif-relationships; do
  echo "== onboard local $ds"
  uv run python -u -m firmable onboard local "$ds" --fresh --auto-review 2>&1 | grep -vE "^\s+\[.*\] (jev|try_read|profile|download|resolve) "
done
echo "== extract all";   uv run python -u -m firmable extract --limit 0
echo "== graph store";   uv run python -u -m firmable graph store
echo "== graph resolve"; uv run python -u -m firmable graph resolve
echo "== graph load";    uv run python -u -m firmable graph load
echo REST_FINISHED
