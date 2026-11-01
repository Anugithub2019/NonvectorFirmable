"""Orchestrates: observations -> DuckDB store -> resolution -> Neo4j. Each step is re-runnable."""
from __future__ import annotations

import json
import time

from ..paths import CONFIGS, OUTPUTS
from . import store


def run_step(step: str, use_jev: bool = True) -> None:
    con = store.connect()
    if step in ("store", "all"):
        t0 = time.time()
        for cfg in sorted(CONFIGS.glob("*.yaml")):
            try:
                r = store.load_observations(con, cfg.stem)
                print(f"  store {cfg.stem[:50]:<50} loaded {r['records_loaded']:>7} unchanged {r['skipped_unchanged']:>7}")
            except FileNotFoundError:
                print(f"  store {cfg.stem[:50]:<50} no observations yet (run extract)")
        store.build_record_parties(con)
        print(f"  store built in {time.time() - t0:.1f}s: {store.table_counts(con)}")
    if step in ("resolve", "all"):
        from ..resolve.resolver import Resolver
        t0 = time.time()
        rep = Resolver(con, use_jev=use_jev).run()
        rep["secs_total"] = round(time.time() - t0, 1)
        (OUTPUTS / "resolution_report.json").write_text(json.dumps(rep, indent=2))
        print("  resolve:", json.dumps(rep))
        store.build_views(con)
        print("  views built:", {k: v for k, v in store.table_counts(con).items() if k.startswith(("party_attrs", "parties"))})
    if step in ("load", "all"):
        from .neo4j_loader import Loader
        con.close()
        con = store.connect()
        L = Loader(con)
        rep = L.run()
        (OUTPUTS / "neo4j_load_report.json").write_text(json.dumps(rep, indent=2, default=str))
        L.close()
    con.close()
