"""Guardrails that the review of the shipped repo found bypassable. Each test pins the fix:
the Cypher write guard knows INSERT and the other mutating forms; name-based lookups cannot bypass
resolution via case-folding, inline maps, IN lists, WITH aliases or the full-text index; `within_days`
is bounded on both sides by the pinned as_of; graph-filtered exports evaluate the graph predicate at the
saved date; a mapping the reviewer still rejects on the final round fails instead of being approved."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from firmable.retrieval import agent as A
from firmable.retrieval import graph_api as G


# ----------------------------------------------------------------------------- write guard
@pytest.mark.parametrize("q", [
    "INSERT (n:Party {key: 'x'})",
    "insert (n:Party {key: 'x'}) return n",
    "MATCH (p:Party) FOREACH (x IN [1] | SET p.status = 'gone')",
    "CREATE (n:Party)",
    "MATCH (n) DETACH DELETE n",
    "CALL db.clearQueryCaches()",
    "ALTER DATABASE neo4j SET ACCESS READ WRITE",
    "LOAD CSV FROM 'file:///x.csv' AS row RETURN row",
])
def test_write_guard_refuses_every_mutating_form(q):
    assert G._FORBIDDEN.search(q), q


def test_write_guard_lets_reads_through():
    q = "MATCH (p:Party {key: $k})-[:HOLDS]->(l:Licence) RETURN l.licence_type, l.status ORDER BY l.start_date"
    assert not G._FORBIDDEN.search(q)


# ----------------------------------------------------------------------------- name gate
@pytest.mark.parametrize("q", [
    "MATCH (p:Party) WHERE p.display_name CONTAINS 'ACME' RETURN p.key",
    "MATCH (p:Party) WHERE toLower(p.display_name) CONTAINS 'acme' RETURN p.key",
    "MATCH (p:Party {display_name: 'ACME PTY LTD'}) RETURN p.key",
    "MATCH (p:Party) WHERE p.display_name IN ['ACME PTY LTD', 'ACME HOLDINGS'] RETURN p.key",
    "MATCH (p:Party)-[:KNOWN_AS]->(n:Name) WITH p, n.text AS t WHERE t STARTS WITH 'ACME' RETURN p.key",
    "MATCH (n:Name) WHERE n.normalised = 'ACME PTY LTD' MATCH (p)-[:KNOWN_AS]->(n) RETURN p.key",
    "CALL db.index.fulltext.queryNodes('name_text', 'acme') YIELD node MATCH (p)-[:KNOWN_AS]->(node) RETURN p.key",
    "MATCH (p:Party) WHERE p.display_name =~ '(?i)acme.*' RETURN p.key",
    "MATCH (p:Party) WHERE toUpper(p.display_name) = 'ACME' RETURN p.key",
])
def test_name_lookups_are_refused_in_every_spelling(q):
    assert A._name_filtered(q), q


@pytest.mark.parametrize("q", [
    "MATCH (p:Party {key: $k})-[:KNOWN_AS]->(n:Name) RETURN p.display_name, n.text ORDER BY n.text",
    "MATCH (p:Party {key: 'abn:1'})-[:OWNS]->(c:Party) RETURN c.key, c.display_name",
    "MATCH (p:Party) WHERE p.status = 'active' AND p.state = 'QLD' RETURN count(p)",
])
def test_names_may_be_returned_but_not_filtered(q):
    assert not A._name_filtered(q), q


def test_name_gate_applies_after_a_resolve_too(monkeypatch):
    """Resolving one entity does not license name-matching for others in the same turn."""
    from google.genai import types
    from test_agent import FakeAPI, _fc, _text, _script  # tests/ is on sys.path under pytest's prepend import mode
    api = FakeAPI({"ACME": "resolved"})
    _script(monkeypatch, [_fc("resolve", reference="ACME"),
                          _fc("read_cypher", query="MATCH (p:Party) WHERE toLower(p.display_name) CONTAINS 'globex' RETURN p.key"),
                          _text("done")])
    res = A.Agent(api).intelligent("acme and globex", [])
    assert res["trace"][1]["gated"] == "name_filter_in_cypher"
    assert ("read_cypher", "MATCH (p:Party) WHERE toLower(p.display_name) CONTAINS 'globex' RETURN p.key") not in api.calls


# ----------------------------------------------------------------------------- dates
def test_within_days_excludes_dates_after_as_of():
    where, params = G._filter_clauses([{"column": "end_date", "op": "within_days", "value": 90}], "2026-11-02")
    assert len(where) == 1
    assert ">=" in where[0] and "<=" in where[0], where[0]
    assert params == ["2026-11-02", 90, "2026-11-02"]


def test_within_days_is_really_two_sided_in_duckdb():
    import duckdb
    con = duckdb.connect()
    con.execute("CREATE TABLE t(end_date VARCHAR)")
    con.execute("INSERT INTO t VALUES ('2026-10-01'), ('2026-11-02'), ('2026-12-25'), ('2025-01-01'), (NULL)")
    where, params = G._filter_clauses([{"column": "end_date", "op": "within_days", "value": 90}], "2026-11-02")
    rows = con.execute(f"SELECT end_date FROM t WHERE {where[0]} ORDER BY 1", params).fetchall()
    assert rows == [("2026-10-01",), ("2026-11-02",)]   # the future date and the old one are out


def test_graph_filter_is_evaluated_at_the_saved_as_of():
    seen = {}

    def within_hops(hops, of_key=None, limit=100, current_only=True, as_of=None):
        seen["within_hops"] = as_of
        return {"results": [{"key": "abn:1"}]}

    def _run(q, **params):
        seen["run"] = (q, params)
        return [{"key": "abn:2"}]

    fake = SimpleNamespace(within_hops=within_hops, _run=_run)
    assert G.GraphAPI._graph_keys(fake, {"kind": "within_hops_of_ban", "hops": 2}, "2024-06-30") == ["abn:1"]
    assert seen["within_hops"] == "2024-06-30"
    assert G.GraphAPI._graph_keys(fake, {"kind": "has_owner"}, "2024-06-30") == ["abn:2"]
    q, params = seen["run"]
    assert "valid_to" in q and params == {"as_of": "2024-06-30"}


# ----------------------------------------------------------------------------- review rounds
def _review_state(n_rejections: int) -> dict:
    return {"slug": "test-src", "auto_review": True, "human_feedback": ["fix a", "fix b"][:n_rejections]}


def _patch_reviewer(monkeypatch, action: str):
    from firmable.ingest.onboarding import nodes, review
    monkeypatch.setattr(review, "render", lambda slug, state=None, quiet=False: "REVIEW SCREEN")
    monkeypatch.setattr(nodes.llm, "structured", lambda *a, **k: nodes.ReviewDecision(action=action, note="still maps a trading name to legal_name"))
    monkeypatch.setattr(nodes.llm, "usage_since", lambda *a, **k: {"calls": 1, "in": 1, "out": 1, "usd": 0.0})
    return nodes


def test_final_round_rejection_fails_the_run_instead_of_approving(monkeypatch):
    nodes = _patch_reviewer(monkeypatch, "reject")
    upd = nodes.model_review(_review_state(2))
    assert upd["status"].startswith("failed"), upd["status"]
    assert upd["decision"]["action"] == "reject"
    assert "approved" not in upd["status"]


def test_earlier_round_rejection_reopens_the_agent(monkeypatch):
    nodes = _patch_reviewer(monkeypatch, "reject")
    upd = nodes.model_review(_review_state(1))
    assert upd["status"] == "revising_after_review"
    assert len(upd["human_feedback"]) == 2


def test_final_round_can_still_approve_a_right_mapping(monkeypatch):
    nodes = _patch_reviewer(monkeypatch, "approve")
    assert nodes.model_review(_review_state(2))["status"] == "approved"


def test_failed_review_ends_the_graph_without_emit():
    from firmable.ingest.onboarding import graph
    from langgraph.graph import END
    assert graph._after_review({"status": "failed_review_rejected_after_max_revisions"}) == END
    assert graph._after_review({"status": "approved"}) == "emit"
