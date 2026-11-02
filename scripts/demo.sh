#!/usr/bin/env bash
# One command from a clean checkout to the running demo at http://localhost:8501.
# Prerequisites: Docker Desktop running, uv installed, .env with GOOGLE_API_KEY and OPENROUTER_API_KEY.
# Re-runs are cheap: the DuckDB build (store + resolve) is skipped once it has completed, the Neo4j load
# if the graph already has parties. Pass --rebuild to redo both. Only one copy may run at a time: the
# DuckDB file allows a single writer, so a second copy exits with a message instead of a lock error.
set -euo pipefail
cd "$(dirname "$0")/.."

if [ ! -f .env ]; then
  echo "No .env: run  cp .env.example .env  and fill GOOGLE_API_KEY and OPENROUTER_API_KEY" >&2
  exit 1
fi
REBUILD=0; [ "${1:-}" = "--rebuild" ] && REBUILD=1

mkdir -p data
LOCK=data/.demo.lock
if [ -f "$LOCK" ] && kill -0 "$(cat "$LOCK" 2>/dev/null)" 2>/dev/null; then
  echo "Another ./scripts/demo.sh is already running (PID $(cat "$LOCK")). Wait for it, or stop it first." >&2
  exit 1
fi
echo $$ > "$LOCK"
trap 'rm -f "$LOCK"' EXIT

echo "== python env";  uv sync
echo "== neo4j";       docker compose up -d --wait neo4j

BUILT=data/.resolved        # written only after store + resolve both succeeded
LOADED=data/.loaded         # written only after a load completed; an interrupted load leaves a partial graph
if [ "$REBUILD" = 1 ] || [ ! -f data/firmable.duckdb ] || [ ! -f "$BUILT" ]; then
  # invalidate first: a build that fails part-way must leave NO marker, so the next run redoes it
  # rather than skipping it. The graph marker goes too, since a rebuilt store needs a fresh load.
  rm -f "$BUILT" "$LOADED"
  echo "== duckdb store";  uv run python -m firmable graph store
  echo "== resolve";       uv run python -m firmable graph resolve    # seconds to a few minutes with the shipped Jev cache
  date -u +%Y-%m-%dT%H:%M:%SZ > "$BUILT"
else
  echo "== duckdb store already built, skipping (use --rebuild to redo)"
fi

PARTIES=$(docker compose exec -T neo4j cypher-shell -u neo4j -p firmable-graph --format plain \
          "MATCH (p:Party) RETURN count(p)" 2>/dev/null | tail -1 || echo 0)
if [ "$REBUILD" = 1 ] || [ ! -f "$LOADED" ] || [ "${PARTIES:-0}" = "0" ]; then
  rm -f "$LOADED"
  echo "== neo4j load";  uv run python -m firmable graph load         # ~1.5 min
  date -u +%Y-%m-%dT%H:%M:%SZ > "$LOADED"
else
  echo "== neo4j already has $PARTIES parties, skipping load (use --rebuild to redo)"
fi

echo "== demo (Ctrl-C stops it; 'docker compose --profile demo down' removes the containers)"
docker compose --profile demo up --build
