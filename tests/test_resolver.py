"""Resolver behaviour on a small synthetic register (no model calls: use_jev=False)."""
import duckdb
import pytest

from firmable.resolve import normalise as N
from firmable.resolve.resolver import Resolver


def _db(rows):
    con = duckdb.connect()
    con.execute("""CREATE TABLE record_parties (record_key VARCHAR, source_id VARCHAR, source_record_id VARCHAR,
        name VARCHAR, entity_type VARCHAR, status VARCHAR, abn VARCHAR, acn VARCHAR, lei VARCHAR, state VARCHAR,
        postcode VARCHAR, locality VARCHAR, trading_names VARCHAR[], person_role VARCHAR)""")
    for r in rows:
        con.execute("INSERT INTO record_parties VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", [
            r["key"], r["src"], r["key"].split(":")[-1], r.get("name"), r.get("type"), None, r.get("abn"),
            r.get("acn"), r.get("lei"), r.get("state"), r.get("postcode"), None, r.get("trading"), r.get("role")])
    return con


ABN_A = "51824753556"      # valid checksum
ACN_A = "090444714"        # valid checksum


def run(rows, **kw):
    con = _db(rows)
    R = Resolver(con, use_jev=False)
    R.persist = lambda: None  # keep the test in memory
    rep = R.run()
    return R, rep


def test_exact_abn_links_two_sources():
    R, rep = run([{"key": "a:1", "src": "a", "name": "ACME PTY LTD", "abn": ABN_A},
                  {"key": "b:1", "src": "b", "name": "Acme Pty. Ltd.", "abn": ABN_A, "state": "QLD"}])
    assert R.key_of["a:1"] == R.key_of["b:1"] == f"abn:{ABN_A}"
    assert {l["match_type"] for l in R.links} == {"exact_abn"}


def test_abr_bridges_abn_and_acn():
    R, _ = run([{"key": "abr:1", "src": "abr", "name": "ACME PTY LTD", "abn": ABN_A, "acn": ACN_A},
                {"key": "asic:1", "src": "asic", "name": "ACME PTY LTD", "acn": ACN_A},
                {"key": "afs:1", "src": "afs", "name": "ACME PTY LTD", "abn": ABN_A}])
    assert len({R.key_of[k] for k in ("abr:1", "asic:1", "afs:1")}) == 1
    mt = {l["left_record_key"]: l["match_type"] for l in R.links}
    assert mt["asic:1"] == "bridge_abr_acn" and mt["afs:1"] == "exact_abn"


def test_acn_under_two_abns_is_not_merged():
    other_abn = "53004085616"  # valid: Telstra-style ABN example
    R, _ = run([{"key": "abr:1", "src": "abr", "name": "ONE PTY LTD", "abn": ABN_A, "acn": ACN_A},
                {"key": "abr:2", "src": "abr", "name": "TWO PTY LTD", "abn": other_abn, "acn": ACN_A},
                {"key": "ban:1", "src": "ban", "name": "ONE PTY LTD", "acn": ACN_A}])
    assert R.key_of["abr:1"] != R.key_of["abr:2"]
    abst = {a["record_key"]: a["reason"] for a in R.abstentions}
    assert abst.get("ban:1") == "identifier_conflict"


def test_exact_normalised_same_place_links_without_model():
    R, _ = run([{"key": "abr:1", "src": "abr", "name": "OVER THE TOP ROOF RESTORATIONS PTY LTD", "abn": ABN_A, "state": "QLD", "postcode": "4575"},
                {"key": "con:1", "src": "contracts", "name": '"Over The Top" Roof Restorations Pty. Ltd', "state": "QLD", "postcode": "4575"}])
    assert R.key_of["con:1"] == f"abn:{ABN_A}"
    link = next(l for l in R.links if l["left_record_key"] == "con:1")
    assert link["match_type"] == "name_exact_norm" and link["confidence"] >= 0.85


def test_similar_name_different_place_is_abstained():
    R, _ = run([{"key": "abr:1", "src": "abr", "name": "SMITH PLUMBING PTY LTD", "abn": ABN_A, "state": "QLD", "postcode": "4000"},
                {"key": "con:1", "src": "contracts", "name": "Smith Plumbing Services", "state": "VIC", "postcode": "3000"}])
    assert "con:1" not in [l["left_record_key"] for l in R.links if l["match_type"] != "singleton"]
    a = next(a for a in R.abstentions if a["record_key"] == "con:1")
    assert a["reason"] == "below_threshold" and a["best_candidate"] == f"abn:{ABN_A}"


def test_person_never_linked_by_name():
    R, _ = run([{"key": "liq:1", "src": "liq", "name": "JANE CITIZEN", "role": "liquidator", "state": "QLD"},
                {"key": "qbcc:1", "src": "qbcc", "name": "JANE CITIZEN", "type": "sole_trader", "state": "QLD", "abn": ABN_A}])
    assert next(a for a in R.abstentions if a["record_key"] == "liq:1")["reason"] == "person_name_only"
    assert R.key_of["liq:1"].startswith("src:")


def test_singleton_keeps_own_identifier():
    R, _ = run([{"key": "afs:1", "src": "afs", "name": "LONELY LTD", "abn": ABN_A}])
    assert R.key_of["afs:1"] == f"abn:{ABN_A}"
    assert R.links[0]["match_type"] in ("singleton", "exact_abn")


def test_normalise_and_blocking():
    assert N.normalise('"Over The Top" Roof Restorations Pty. Ltd') == "OVER TOP ROOF RESTORATIONS"
    assert N.legal_form("Acme Proprietary Limited") == "PTY LTD"
    keys = N.blocking_keys("SMITH PLUMBING HOLDINGS", "QLD", "4000")
    assert "t:SMITH" in keys and "t:PLUMBING" in keys and "t:HOLDINGS" not in keys
    assert "f:SMI:QLD" in keys and "p:4000:SMI" in keys
