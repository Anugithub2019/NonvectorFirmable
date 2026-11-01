"""What a human sees when asked to approve a mapping (terminal + a markdown copy on disk)."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from rich.console import Console
from rich.prompt import Prompt
from rich.table import Table

from ...paths import ROOT
from .. import readers
from ..extractor import Evaluator
from . import graph, nodes



def render(slug: str, console: Console | None = None, state: dict | None = None,
           quiet: bool = False) -> str:
    """Print the review screen and return it as markdown (also saved next to the report).
    `state` lets a node render its own in-flight state; `quiet` skips the terminal output."""
    if state is not None:
        s, nxt = state, ("review",)
    else:
        s, nxt = graph.get_state(slug)
    console = console or Console(quiet=quiet)
    if not s:
        console.print(f"[red]no run found for {slug}[/]")
        return ""
    cfg, v, d = s.get("config", {}), s.get("validation", {}), s.get("dataset", {})
    md = [f"# Review: {s['source_id']}", ""]

    def line(txt: str, style: str = "") -> None:
        console.print(f"[{style}]{txt}[/]" if style else txt)
        md.append(txt)

    line(f"{d.get('title')} — {d.get('publisher')}", "bold")
    line(f"resource: {d.get('resource_name')} [{d.get('resource_format')}]  "
         f"rows: {s.get('total_rows')}  licence: {d.get('licence')}"
         + (f"  ⚠ {d['licence_flag']}" if d.get("licence_flag") else ""))
    u = s.get("understanding", {})
    line(f"what it is: {u.get('what_it_is')}")
    line(f"one row = {u.get('record_grain')}")
    if u.get("entity_concerns"):
        line(f"entity concerns: {u['entity_concerns']}", "yellow")
    line(f"reader: {json.dumps(s.get('reader'))}  (inspect attempts: "
         f"{len(s.get('reader_attempts', []))})")
    if s.get("reader_warnings_unresolved"):
        line(f"unresolved reader warnings: {s['reader_warnings_unresolved']}", "yellow")
    rec = cfg.get("record", {})
    line(f"record id: {rec.get('id_columns') or 'row hash'} — {rec.get('id_note')}")
    line(f"observed_at: {json.dumps(rec.get('observed_at'))}")
    if cfg.get("include_if"):
        line(f"include_if: {json.dumps(cfg['include_if'])} — {cfg.get('include_if_reason')}",
             "yellow")

    fm = v.get("metrics", {}).get("fields", {})
    t = Table(title=f"Proposed mapping (validated on {len(s.get('holdout_idx', []))} unseen rows)")
    for col in ("target", "source", "transforms", "when", "conf", "lvl", "applied", "fail%"):
        t.add_column(col, overflow="fold")
    md += ["", "| target | source | transforms | when | conf | lvl | applied | fail% |",
           "|---|---|---|---|---|---|---|---|"]
    for f in cfg.get("fields", []):
        m = fm.get(f["target"], {})
        ops = ", ".join(st["op"] + (f"({json.dumps(st.get('args'))[:60]})" if st.get("args") else "")
                        for st in f["transforms"])
        when = "; ".join(f"{c['column']} {c['op']} {c['values']}" for c in f.get("when", []))
        row = [f["target"], ", ".join(f["source_columns"]), ops, when, str(f["confidence"]),
               f["derivation"], str(m.get("produced", "-")), f"{m.get('fail_rate', 0):.0%}"]
        t.add_row(*row)
        md.append("| " + " | ".join(x.replace("|", "/") for x in row) + " |")
    console.print(t)

    line("\nUnmapped (deliberately not guessed):", "bold")
    for x in cfg.get("unmapped", []):
        line(f"  - {x['column']}: {x['reason']}")
    line(f"\nsource_reliability: {cfg.get('source_reliability')}")
    line("\nValidation: " + ("PASSED" if v.get("passed") else "NOT PASSED"),
         "green" if v.get("passed") else "red")
    for b in v.get("blocking", []):
        line(f"  BLOCKING {b}", "red")
    for w in v.get("warnings", []):
        line(f"  warning  {w}", "yellow")
    if v.get("critic"):
        line(f"critic: {v['critic']['summary']}")
    line(f"\nhistory: {json.dumps(s.get('validation_history'))}")
    for c in s.get("changes_log", []):
        line(f"  it{c['iteration']} {c['node']}: {c['changes'][:300]}")
    for n in cfg.get("reviewer_notes", []):
        line(f"  NOTE FOR REVIEWER: {n}", "cyan")

    # a few concrete examples: raw row -> claims
    try:
        df = readers.read_frame(ROOT / s["local_file"], s["reader"], nrows=None)
        ev = Evaluator(cfg)
        line("\nExamples (unseen rows):", "bold")
        for i in s["holdout_idx"][:3]:
            row = df.iloc[i].to_dict()
            claims = [(o["field"], o["value"]) for o in ev.record(i, row)]
            line(f"  RAW    {json.dumps({k: str(x)[:50] for k, x in row.items() if x}, ensure_ascii=False)[:600]}")
            line(f"  CLAIMS {claims}")
    except Exception as e:  # noqa: BLE001
        line(f"(could not render examples: {e})")

    cost = sum(x.get("usd", 0) for x in s.get("steps", []))
    line(f"\nagent cost so far: ${cost:.4f} over {len(s.get('steps', []))} steps; "
         f"paused at: {nxt}")
    text = "\n".join(md)
    out = nodes.REPORTS / f"{slug}.review.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text)
    return text


def decide(slug: str, action: str | None, note: str, reviewer: str) -> dict:
    """Interactive if action is None; otherwise non-interactive approve/reject/abandon.
    Works on a run paused at review AND on a finished run (re-review)."""
    render(slug)
    if action is None:
        action = Prompt.ask("decision", choices=["approve", "reject", "abandon"])
        if action == "reject" and not note:
            note = Prompt.ask("what should the agent fix?")
    decision = {"action": action, "note": note, "reviewer": reviewer,
                "at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    _, nxt = graph.get_state(slug)
    if not nxt:  # finished run: re-review
        return _re_review(slug, decision)
    res = graph.resume_review(slug, decision)
    print(f"-> status={res['values'].get('status')} next={res['next']}")
    return res


def _re_review(slug: str, decision: dict) -> dict:
    """Re-review an already-emitted config.
    approve -> append to provenance.approvals and make this reviewer the approver of record
               (mapping unchanged, so existing observations stay valid: the config hash in
               extractor_version covers reader/record/fields only, not provenance).
    reject  -> reopen the run at `revise` with the note as human feedback; it then
               validates and pauses at review again."""
    import yaml
    s, _ = graph.get_state(slug)
    if decision["action"] == "approve":
        path = ROOT / s["config_path"]
        text = path.read_text()
        header = "".join(l + "\n" for l in text.splitlines() if l.startswith("#"))
        cfg = yaml.safe_load(text)
        prov = cfg.setdefault("provenance", {})
        history = prov.get("approvals") or [{k: prov.get(k) for k in
                                              ("approved_by", "approved_at", "review_note")}]
        history.append({"approved_by": decision["reviewer"], "approved_at": decision["at"],
                        "review_note": decision["note"]})
        prov.update({"approvals": history, "approved_by": decision["reviewer"],
                     "approved_at": decision["at"], "review_note": decision["note"]})
        path.write_text(header + yaml.safe_dump(cfg, sort_keys=False, allow_unicode=True,
                                                width=100))
        print(f"-> re-approved by {decision['reviewer']}; {len(history)} approvals on record "
              f"({path.name})")
        return {"slug": slug, "next": (), "values": s}
    if decision["action"] == "reject":
        g = graph.build(graph._saver())
        cfg = {"configurable": {"thread_id": slug}, "recursion_limit": 60}
        g.update_state(cfg, {"human_feedback": s.get("human_feedback", []) + [decision["note"]],
                             "status": "revising_after_review", "decision": decision},
                       as_node="review")
        g.invoke(None, cfg)
        st = g.get_state(cfg)
        nodes.write_report(st.values)
        print(f"-> reopened: status={st.values.get('status')} next={st.next}")
        return {"slug": slug, "next": st.next, "values": st.values}
    print("-> nothing to do for a finished run")
    return {"slug": slug, "next": (), "values": s}
