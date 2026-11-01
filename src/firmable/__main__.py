"""CLI: python -m firmable <command> ..."""
from __future__ import annotations

import argparse
import getpass
import json
from pathlib import Path

from .paths import OUTPUTS, ROOT, SOURCES, CONFIGS


def main() -> None:
    p = argparse.ArgumentParser(prog="firmable")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("triage", help="Part 1: build the ranked shortlist of 50")
    sub.add_parser("handcheck-sheet", help="Part 1: sample 20 shortlist rows for hand-checking")
    j = sub.add_parser("judge-shortlist", help="Part 1: independent judge over the 20 "
                                               "hand-check rows (needs OPENROUTER_API_KEY)")
    j.add_argument("--judge", choices=["jev", "claude"], default="jev",
                   help="jev = TypeSafe Jev decision model (default); claude = Claude Sonnet")

    o = sub.add_parser("onboard", help="Part 2: run the onboarding agent on a dataset "
                                       "(pauses for human review)")
    o.add_argument("portal", nargs="?", help="data.gov.au | nsw | sa | qld | vic")
    o.add_argument("dataset_id", nargs="?")
    o.add_argument("--resource", help="force a specific resource id")
    o.add_argument("--all", action="store_true", help="onboard every source in sources.yaml")
    o.add_argument("--fresh", action="store_true", help="discard any saved run state first")
    o.add_argument("--auto-review", action="store_true",
                   help="approval step performed by the PRO model instead of a person")

    r = sub.add_parser("review", help="Part 2: show a paused mapping and approve/reject it")
    r.add_argument("slug")
    g = r.add_mutually_exclusive_group()
    g.add_argument("--approve", action="store_true")
    g.add_argument("--reject", action="store_true")
    g.add_argument("--abandon", action="store_true")
    g.add_argument("--show", action="store_true", help="only print the review screen")
    r.add_argument("--note", default="", help="feedback for the agent (required with --reject)")
    r.add_argument("--reviewer", default=getpass.getuser())

    sub.add_parser("status", help="Part 2: status of every onboarding run")

    e = sub.add_parser("extract", help="run the generic extractor on approved configs")
    e.add_argument("configs", nargs="*", help="config paths (default: all in configs/)")
    e.add_argument("--limit", type=int, default=1000, help="0 = every record")
    e.add_argument("--sample", choices=["random", "head"], default="random")

    sub.add_parser("slice", help="graph: build the tier-1 slice CSVs from ABR + ASIC companies")
    sub.add_parser("abr-parse", help="graph: stream the ABR XML zips into data/raw/abr/abr_all.parquet")
    g = sub.add_parser("graph", help="graph: build the store, resolve entities, load Neo4j")
    g.add_argument("step", choices=["store", "resolve", "load", "all"])
    g.add_argument("--no-jev", action="store_true", help="semantic path without the decision model")
    ev = sub.add_parser("evaluate", help="label a link sample (Pro + Jev, blind), recall test, resolve benchmark, reports")
    ev.add_argument("--no-jev", action="store_true")
    c = sub.add_parser("chat", help="talk to the retrieval agent in the terminal")
    c.add_argument("--mode", choices=["auto", "intelligent", "retriever"], default="auto")
    a = p.parse_args()

    if a.cmd == "triage":
        from .ingest.triage import run
        run()
    elif a.cmd == "handcheck-sheet":
        from .ingest.handcheck import shortlist_sheet
        shortlist_sheet()
    elif a.cmd == "judge-shortlist":
        from .ingest.handcheck import jev_judge_sheet, judge_sheet
        jev_judge_sheet() if a.judge == "jev" else judge_sheet()
    elif a.cmd == "onboard":
        from .ingest.onboarding.graph import onboard
        import yaml
        registry = yaml.safe_load(SOURCES.read_text())["sources"]
        if a.all:
            jobs = registry
        else:  # single run: pick up resource pin / local metadata from the registry if present
            match = next((j for j in registry if j["portal"] == a.portal and j["dataset_id"] == a.dataset_id), {})
            jobs = [{**match, "portal": a.portal, "dataset_id": a.dataset_id,
                     "resource": a.resource or match.get("resource")}]
        for j in jobs:
            print(f"\n== onboarding {j['portal']}:{j['dataset_id']}")
            res = onboard(j["portal"], j["dataset_id"], j.get("resource"), fresh=a.fresh,
                          auto_review=a.auto_review, local_meta=j.get("local"))
            nxt = res["next"]
            st = res["values"].get("status") or ("awaiting review" if nxt and "review" in nxt
                                                 else f"paused before {nxt}" if nxt else "?")
            print(f"-> {res['slug']}: {st} {res['values'].get('error') or ''}")
            if res["next"] and "review" in res["next"]:
                print(f"   review with: python -m firmable review {res['slug']}")
    elif a.cmd == "review":
        from .ingest.onboarding import review
        if a.show:
            review.render(a.slug)
            return
        action = "approve" if a.approve else "reject" if a.reject else \
            "abandon" if a.abandon else None
        if action == "reject" and not a.note:
            p.error("--reject needs --note explaining what to fix")
        review.decide(a.slug, action, a.note, a.reviewer)
    elif a.cmd == "status":
        from .ingest.onboarding.graph import get_state, slug_for
        import yaml
        rows = ["| source | status | steps | LLM calls | tokens in/out | USD | agent secs | "
                "inspect tries | revisions |", "|---|---|---|---|---|---|---|---|---|"]
        for j in yaml.safe_load(SOURCES.read_text())["sources"]:
            slug = slug_for(j["portal"], j["dataset_id"])
            v, nxt = get_state(slug)
            st = v.get("status") or ("awaiting review" if nxt and "review" in nxt else
                                     f"paused at {nxt}" if nxt else "not started")
            steps = v.get("steps", [])
            usd = sum(s.get("usd", 0) for s in steps)
            secs = sum(s["secs"] for s in steps if s["node"] != "review")
            print(f"{slug[:60]:<60} {st:<18} {len(steps):>3} steps ${usd:.4f} {secs:6.1f}s "
                  f"{v.get('error') or ''}")
            rows.append(f"| {v.get('source_id', slug)} | {st} | {len(steps)} | "
                        f"{sum(s.get('calls', 0) for s in steps)} | "
                        f"{sum(s.get('in', 0) for s in steps)}/{sum(s.get('out', 0) for s in steps)}"
                        f" | {usd:.4f} | {secs:.1f} | {len(v.get('reader_attempts', []))} | "
                        f"{v.get('iteration', 0)} |")
        out = OUTPUTS / "onboarding" / "SUMMARY.md"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text("# Onboarding runs\n\n" + "\n".join(rows) + "\n")
        print(f"wrote {out.relative_to(ROOT)}")
    elif a.cmd == "slice":
        from .ingest.slices import run
        run()
    elif a.cmd == "abr-parse":
        from .ingest.abr import parse_all
        parse_all()
    elif a.cmd == "graph":
        from .graph.pipeline import run_step
        run_step(a.step, use_jev=not a.no_jev)
    elif a.cmd == "evaluate":
        from .evaluate.evaluation import run_all
        run_all(use_jev=not a.no_jev)
    elif a.cmd == "chat":
        from .retrieval.cli import repl
        repl(a.mode)
    elif a.cmd == "extract":
        from .ingest.extractor import run
        paths = [Path(c) for c in a.configs] or sorted(CONFIGS.glob("*.yaml"))
        for path in paths:
            rep = run(path, limit=a.limit, sample=a.sample)
            print(f"{path.stem}: {rep['sampled_rows']} rows -> {rep['observations']} observations"
                  f" | filtered {rep['stats']['filtered']} | no-entity "
                  f"{rep['stats']['records_without_entity_claims']}")
            print("   " + json.dumps({t: f"{m['produced']}/{m['applicable']}"
                                      for t, m in rep["fields"].items()}))


if __name__ == "__main__":
    main()
