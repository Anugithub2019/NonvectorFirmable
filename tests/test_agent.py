"""Agent control flow with the model and the graph mocked out. These tests prove the guarantees the
docs claim are *enforced*: an ambiguous/abstained resolve halts the turn; typed tools refuse keys that
were not resolved or chosen; a user's choice unlocks exactly that key; the budget counts real calls;
invalid projection specs are rejected rather than narrowed; the restatement comes from the spec."""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from google.genai import types

from firmable.retrieval import agent as A


# ----------------------------------------------------------------------------- fakes
def _cand(key, name, score, mt="name_semantic"):
    return {"key": key, "name": name, "state": "QLD", "postcode": "4000", "entity_type": "company", "status": "active",
            "sources": ["asic"], "score": score, "match_type": mt, "evidence": {}, "path": "q"}


class FakeAPI:
    PROJECTION_BASES = {"organisation": "", "party": "", "licence": "", "ban": ""}
    COLS = {"organisation": ["party_key", "display_name", "state", "status"], "party": ["party_key", "display_name"],
            "licence": ["party_key", "licence_type", "licence_status", "end_date"], "ban": ["party_key", "ban_type"]}

    def __init__(self, decisions: dict[str, str]):
        self.decisions, self.calls = decisions, []

    def resolve(self, ref):
        self.calls.append(("resolve", ref))
        d = self.decisions.get(ref, "abstained")
        cands = {"resolved": [_cand("abn:1", "ACME PTY LTD", 0.97), _cand("abn:2", "ACME HOLDINGS", 0.40)],
                 "ambiguous": [_cand("abn:1", "ACME PTY LTD", 0.90), _cand("abn:2", "ACME HOLDINGS", 0.88)],
                 "abstained": [_cand("abn:9", "ACMEE LTD", 0.61)]}[d]
        return {"reference": ref, "normalised": ref.upper(), "decision": d, "candidates": cands, "paths": [], "threshold": 0.85, "latency_ms": 1}

    def entity(self, key):
        self.calls.append(("entity", key))
        return {"party": {"key": key, "display_name": "X"}, "owners": {"items": [{"key": "lei:P", "name": "PARENT"}], "total": 1, "dropped": 0},
                "bans": {"items": [], "total": 0, "dropped": 0}}

    def ultimate_parent(self, key):
        self.calls.append(("ultimate_parent", key))
        return {"start": key, "chain": [], "ultimate_parent": None, "terminated_by": "root", "depth": 0}

    def within_hops(self, hops, of_key=None, limit=100):
        self.calls.append(("within_hops", of_key))
        return {"results": [], "count": 0}

    def read_cypher(self, q):
        self.calls.append(("read_cypher", q))
        return {"rows": [{"key": "abn:777"}], "count": 1}

    def schema_summary(self):
        return {}

    def projection_columns(self, base):
        return self.COLS[base]

    # the real validator, bound to the fake columns
    def validate_projection(self, spec):
        from firmable.retrieval.graph_api import GraphAPI
        return GraphAPI.validate_projection(self, spec)

    FILTER_OPS = ("=", "!=", ">", "<", ">=", "<=", "contains", "in", "is_null", "not_null", "within_days")


def _fc(name, **args):
    return types.Content(role="model", parts=[types.Part.from_function_call(name=name, args=args)])


def _text(t):
    return types.Content(role="model", parts=[types.Part(text=t)])


def _script(monkeypatch, steps):
    """Replace llm.generate with a scripted sequence of model turns."""
    it = iter(steps)

    def fake_generate(contents, cfg, tag="", **kw):
        return SimpleNamespace(candidates=[SimpleNamespace(content=next(it))])
    monkeypatch.setattr(A.llm, "generate", fake_generate)


# ----------------------------------------------------------------------------- tests
def test_ambiguous_resolve_halts_before_the_model_can_continue(monkeypatch):
    api = FakeAPI({"ACME": "ambiguous"})
    # the scripted model WOULD call entity on candidate 1 next; it must never get the chance
    _script(monkeypatch, [_fc("resolve", reference="ACME"), _fc("entity", key="abn:1"), _text("ACME is owned by PARENT")])
    res = A.Agent(api).intelligent("who owns ACME?", [])
    assert res["halt"]["kind"] == "ambiguous"
    assert [c[0] for c in api.calls] == ["resolve"]
    assert "will not pick" in res["answer"] and "abn:1" in res["answer"] and "abn:2" in res["answer"]
    assert "PARENT" not in res["answer"]


def test_abstained_resolve_halts_and_marks_candidates_not_matched(monkeypatch):
    api = FakeAPI({"ACMEE": "abstained"})
    _script(monkeypatch, [_fc("resolve", reference="ACMEE"), _text("should not be reached")])
    res = A.Agent(api).intelligent("is ACMEE banned?", [])
    assert res["halt"]["kind"] == "abstained"
    assert "not matched" in res["answer"] and "0.61" in res["answer"]
    assert api.calls == [("resolve", "ACMEE")]


def test_typed_tools_refuse_keys_that_were_not_resolved(monkeypatch):
    api = FakeAPI({})
    _script(monkeypatch, [_fc("entity", key="abn:1"), _text("done")])
    res = A.Agent(api).intelligent("tell me about abn:1", [])
    assert res["trace"][0]["gated"] == "unresolved_key"
    assert not any(c[0] == "entity" for c in api.calls)


def test_resolved_key_and_keys_it_exposes_are_allowed_but_cypher_keys_are_not(monkeypatch):
    api = FakeAPI({"ACME": "resolved"})
    _script(monkeypatch, [_fc("resolve", reference="ACME"), _fc("entity", key="abn:1"),
                          _fc("ultimate_parent", key="lei:P"),           # owner key came from entity(): allowed
                          _fc("read_cypher", query="MATCH (p:Party) RETURN p.key AS key LIMIT 1"),
                          _fc("entity", key="abn:777"),                  # key came from Cypher rows: refused
                          _text("answer")])
    res = A.Agent(api).intelligent("who ultimately owns ACME?", [])
    kinds = [(t["tool"], t["gated"]) for t in res["trace"]]
    assert kinds == [("resolve", None), ("entity", None), ("ultimate_parent", None), ("read_cypher", None), ("entity", "unresolved_key")]
    assert res["allowed_keys"] == ["abn:1", "lei:P"]


def test_cypher_name_lookup_is_refused_before_resolution(monkeypatch):
    api = FakeAPI({})
    _script(monkeypatch, [_fc("read_cypher", query="MATCH (p:Party) WHERE p.display_name CONTAINS 'ACME' RETURN p.key"), _text("x")])
    res = A.Agent(api).intelligent("find acme", [])
    assert res["trace"][0]["gated"] == "name_predicate_before_resolve"
    assert api.calls == []


def test_user_choice_unlocks_exactly_that_key(monkeypatch):
    api = FakeAPI({"ACME": "ambiguous"})
    agent = A.Agent(api)
    monkeypatch.setattr(A.llm, "jev_decide", lambda *a, **k: {"answers": {"intent": {"choice": "answer", "probabilities": {}}, "specific": {"noul": 0.9}}})
    _script(monkeypatch, [_fc("resolve", reference="ACME")])
    t1 = agent.turn("who owns ACME?", "intelligent", [], None)
    assert t1["pending"]["kind"] == "clarification" and t1["pending"]["candidates"] == ["abn:1", "abn:2"]
    _script(monkeypatch, [_fc("entity", key="abn:2"), _fc("entity", key="abn:1"), _text("ACME HOLDINGS has owner PARENT")])
    t2 = agent.turn("2", "intelligent", [], t1["pending"])
    assert t2["pending"] is None
    assert t2["trace"][0]["tool"] == "user_selected" and t2["trace"][0]["args"]["key"] == "abn:2"
    assert [(t["tool"], t["gated"]) for t in t2["trace"][1:]] == [("entity", None), ("entity", "unresolved_key")]


def test_select_candidate_accepts_index_key_or_close_name():
    pend = {"candidates": ["abn:1", "abn:2"], "candidate_names": ["ACME PTY LTD", "ACME HOLDINGS"]}
    assert A.select_candidate("2", pend)["key"] == "abn:2"
    assert A.select_candidate("use abn:1 please", pend)["key"] == "abn:1"
    assert A.select_candidate("acme holdings", pend)["key"] == "abn:2"
    assert A.select_candidate("actually, who owns Bunnings?", pend) is None


def test_budget_counts_real_calls_not_iterations(monkeypatch):
    api = FakeAPI({"ACME": "resolved"})
    many = [types.Content(role="model", parts=[types.Part.from_function_call(name="entity", args={"key": "abn:1"}) for _ in range(6)])]
    _script(monkeypatch, [_fc("resolve", reference="ACME"), many[0], many[0], _text("final")])
    res = A.Agent(api).intelligent("ACME", [])
    assert res["budget"]["calls"] == A.MAX_TOOL_CALLS and res["budget"]["exhausted"] == "calls"
    assert sum(1 for c in api.calls if c[0] == "entity") == A.MAX_TOOL_CALLS - 1
    assert any("exhausted" in str(t["result"]) for t in res["trace"])


def test_invalid_spec_is_rejected_not_narrowed(monkeypatch):
    api = FakeAPI({})
    bad = A.ProjectionSpec(name="x", base="organisation", columns=["party_key"], filters=[A.ProjectionFilter(column="turnover", op=">", value=5)],
                           restatement="orgs with turnover > 5")
    monkeypatch.setattr(A.llm, "structured", lambda *a, **k: bad)
    spec, problems = A.Agent(api).retriever_spec("orgs with turnover over 5", [], None)
    assert problems and "turnover" in problems[0]
    assert spec.filters and spec.filters[0].column == "turnover"   # nothing was dropped


def test_restatement_is_generated_from_the_validated_spec(monkeypatch):
    api = FakeAPI({})
    good = A.ProjectionSpec(name="x", base="licence", columns=["party_key", "licence_type"], as_of="2026-11-01",
                            filters=[A.ProjectionFilter(column="licence_status", op="in", value=["cancelled"]),
                                     A.ProjectionFilter(column="end_date", op="within_days", value=90)],
                            restatement="SOMETHING THE MODEL SAID", limit=500)
    monkeypatch.setattr(A.llm, "structured", lambda *a, **k: good)
    spec, problems = A.Agent(api).retriever_spec("cancelled licences last 90 days", [], None)
    assert not problems
    assert "SOMETHING THE MODEL SAID" not in spec.restatement
    assert "licence_status is one of ['cancelled']" in spec.restatement and "90 days before 2026-11-01" in spec.restatement
    assert "At most 500 rows" in spec.restatement


def test_shrink_caps_lists_instead_of_cutting_json():
    big = {"party": {"key": "abn:1"}, "records": {"items": [{"record_key": f"r{i}"} for i in range(500)], "total": 500}}
    s = A._shrink(big, limit=800)
    assert s["party"]["key"] == "abn:1" and s["records"]["total"] == 500
    assert s["records"]["items"][-1].get("_dropped") and "truncated_json" not in s
