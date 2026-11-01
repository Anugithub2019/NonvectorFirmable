#!/bin/zsh
# Gzip the large JSONL outputs for shipping in git (DuckDB reads .jsonl.gz transparently; the
# `graph store` step falls back to .gz when the plain file is absent).
cd "$(dirname "$0")/.."
for f in outputs/observations/*.jsonl outputs/links.jsonl outputs/abstentions.jsonl outputs/resolve_results.jsonl; do
  [ -f "$f" ] && gzip -kf "$f"
done
du -sh outputs/observations outputs/*.gz 2>/dev/null | sort -h | tail -5
