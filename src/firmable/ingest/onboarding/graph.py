"""LangGraph wiring for the onboarding agent.

  resolve -> download -> inspect <-> try_read -> profile -> propose -> validate
                                                               ^           |
                                                               |  fail &   | pass, or
                                                               +- revise <-+ revisions exhausted
                                                               ^           v
                                                    rejected   +------- review (human interrupt)
                                                                           | approved
                                                                           v
                                                                         emit

State is checkpointed to SQLite after every node (thread_id = source slug). A crash or a
failed API call loses only the node in flight: re-running `onboard` resumes from there.
"""
from __future__ import annotations

import operator
import re
import sqlite3
from pathlib import Path
from typing import Annotated, Any, TypedDict

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command

from ...paths import DATA
from . import nodes

DB = DATA / "checkpoints.sqlite"


class State(TypedDict, total=False):
    # inputs
    source_id: str
    slug: str
    portal: str
    dataset_id: str
    resource_hint: str | None
    auto_review: bool
    local_meta: dict | None
    # carried between steps
    dataset: dict
    local_file: str
    sha256: str
    sniff: dict
    understanding: dict
    reader: dict
    reader_attempts: list
    reader_ok: bool
    reader_warnings_unresolved: list
    columns: list
    total_rows: int
    train_idx: list
    holdout_idx: list
    profile: dict
    sample_rows: list
    config: dict
    config_issues: list
    changes_log: list
    iteration: int
    validation: dict
    validation_history: list
    human_feedback: list
    decision: dict
    config_path: str
    status: str
    error: str
    steps: Annotated[list, operator.add]


def slug_for(portal: str, dataset_id: str) -> str:
    return f"{portal.replace('.', '-')}__{re.sub(r'[^a-z0-9]+', '-', dataset_id.lower())[:60]}"


def _failed(state: dict) -> bool:
    return str(state.get("status", "")).startswith("failed")


def _next(after: str):
    return lambda s: END if _failed(s) else after


def _after_read(s: dict) -> str:
    if _failed(s):
        return END
    return "profile" if s.get("reader_ok") else "inspect"


def _after_validate(s: dict) -> str:
    if s["validation"]["passed"] or s.get("iteration", 0) >= nodes.MAX_REVISIONS + \
            len(s.get("human_feedback", [])):
        return "review"
    return "revise"


def _after_review(s: dict) -> str:
    return {"approved": "emit", "revising_after_review": "revise"}.get(s.get("status"), END)


def build(checkpointer=None):
    g = StateGraph(State)
    for name in ("resolve", "download", "inspect", "try_read", "profile", "propose", "revise",
                 "validate", "review", "emit"):
        g.add_node(name, getattr(nodes, name))
    g.add_edge(START, "resolve")
    g.add_conditional_edges("resolve", _next("download"))
    g.add_conditional_edges("download", _next("inspect"))
    g.add_conditional_edges("inspect", _next("try_read"))
    g.add_conditional_edges("try_read", _after_read)
    g.add_conditional_edges("profile", _next("propose"))
    g.add_conditional_edges("propose", _next("validate"))
    g.add_conditional_edges("revise", _next("validate"))
    g.add_conditional_edges("validate", _after_validate)
    g.add_conditional_edges("review", _after_review)
    g.add_edge("emit", END)
    return g.compile(checkpointer=checkpointer)


def _saver() -> SqliteSaver:
    DB.parent.mkdir(parents=True, exist_ok=True)
    return SqliteSaver(sqlite3.connect(DB, check_same_thread=False))


def onboard(portal: str, dataset_id: str, resource: str | None = None,
            fresh: bool = False, auto_review: bool = False, local_meta: dict | None = None) -> dict[str, Any]:
    """Run (or resume) onboarding until it finishes, fails, or pauses for human review."""
    slug = slug_for(portal, dataset_id)
    saver = _saver()
    graph = build(saver)
    cfg = {"configurable": {"thread_id": slug}, "recursion_limit": 60}
    if fresh:
        saver.delete_thread(slug)
    snap = graph.get_state(cfg)
    try:
        if snap.next and "review" not in snap.next:
            # an earlier run died mid-way: resume from the last completed node's checkpoint
            print(f"resuming {slug} at {snap.next}")
            graph.invoke(None, cfg)
        elif not snap.values:
            graph.invoke({"source_id": f"{portal}:{dataset_id}", "slug": slug, "portal": portal,
                          "dataset_id": dataset_id, "resource_hint": resource,
                          "auto_review": auto_review, "local_meta": local_meta, "steps": []}, cfg)
    except Exception as e:  # noqa: BLE001 - unexpected crash: state up to the last node is kept
        print(f"  ! run interrupted by {type(e).__name__}: {e}\n    re-run the same command to "
              "resume from the last checkpoint")
    state = graph.get_state(cfg)
    nodes.write_report(state.values)
    return {"slug": slug, "next": state.next, "values": state.values}


def resume_review(slug: str, decision: dict) -> dict[str, Any]:
    graph = build(_saver())
    cfg = {"configurable": {"thread_id": slug}, "recursion_limit": 60}
    graph.invoke(Command(resume=decision), cfg)
    state = graph.get_state(cfg)
    nodes.write_report(state.values)
    return {"slug": slug, "next": state.next, "values": state.values}


def get_state(slug: str) -> tuple[dict, tuple]:
    graph = build(_saver())
    snap = graph.get_state({"configurable": {"thread_id": slug}})
    return snap.values, snap.next
