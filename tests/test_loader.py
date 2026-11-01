"""Loader reconciliation against a scratch Neo4j (docker compose --profile test up -d neo4j-test).
Skipped when that container is not reachable. Proves the claim "the graph equals the DuckDB state":
a record that re-resolves from party A to B keeps exactly one RESOLVED_TO; a dropped name loses its
KNOWN_AS and its orphan Name node; a party that merged away disappears; an unchanged rerun deletes
nothing. The real graph on :7687 is never touched."""
from __future__ import annotations

import json

import pytest
from neo4j import GraphDatabase

from firmable.graph import store
from firmable.graph.neo4j_loader import Loader

TEST_URI, AUTH = "bolt://localhost:7688", ("neo4j", "firmable-graph")


def _driver():
    try:
        d = GraphDatabase.driver(TEST_URI, auth=AUTH)
        d.verify_connectivity()
        return d
    except Exception:  # noqa: BLE001
        return None


def _obs(con, rk, src, fields: dict):
    con.execute("INSERT OR REPLACE INTO source_records VALUES (?, ?, ?, 1, 'h', '2026-01-01', '2026-01-01', 'cc-by', 'x', '{}')",
                [rk, src, rk])
    con.execute("DELETE FROM observations WHERE record_key = ?", [rk])
    for f, v in fields.items():
        con.execute("INSERT INTO observations VALUES (?, ?, ?, ?, ?, ?, ?, 'direct', 0.9, 0.9, '2026-01-01', NULL, NULL, 'x')",
                    [f"{rk}:{f}", rk, src, rk, f, v, v])


def _resolution(con, cluster: dict[str, str], parties: dict[str, tuple]):
    """cluster: record_key -> canonical_key; parties: key -> (party_type, abn, acn, lei)."""
    con.execute("CREATE OR REPLACE TABLE links (left_source VARCHAR, left_record_id VARCHAR, left_record_key VARCHAR, "
                "canonical_key VARCHAR, match_type VARCHAR, confidence DOUBLE, threshold DOUBLE, evidence JSON, "
                "matcher_version VARCHAR, created_at VARCHAR)")
    con.execute("CREATE OR REPLACE TABLE abstentions (source VARCHAR, record_id VARCHAR, record_key VARCHAR, name VARCHAR, "
                "best_candidate VARCHAR, best_score DOUBLE, reason VARCHAR, evidence JSON, matcher_version VARCHAR, created_at VARCHAR)")
    con.execute("CREATE OR REPLACE TABLE parties (key VARCHAR PRIMARY KEY, party_type VARCHAR, abn VARCHAR, acn VARCHAR, "
                "lei VARCHAR, n_sources INTEGER, sources VARCHAR[], names VARCHAR[])")
    con.execute("CREATE OR REPLACE TABLE record_cluster (record_key VARCHAR PRIMARY KEY, canonical_key VARCHAR)")
    for rk, ck in cluster.items():
        src = con.execute("SELECT source_id FROM source_records WHERE record_key = ?", [rk]).fetchone()[0]
        con.execute("INSERT INTO links VALUES (?, ?, ?, ?, 'exact_abn', 0.99, 0.85, ?, 'resolver-test', '2026-01-01')",
                    [src, rk, rk, ck, json.dumps({})])
        con.execute("INSERT INTO record_cluster VALUES (?, ?)", [rk, ck])
    for key, (pt, abn, acn, lei) in parties.items():
        srcs = [r[0] for r in con.execute("SELECT DISTINCT source_id FROM source_records s JOIN record_cluster rc USING (record_key) WHERE rc.canonical_key = ?", [key]).fetchall()]
        con.execute("INSERT INTO parties VALUES (?, ?, ?, ?, ?, ?, ?, [])", [key, pt, abn, acn, lei, len(srcs), srcs])
    store.build_record_parties(con)
    store.build_views(con)


def _counts(d) -> dict:
    with d.session() as s:
        return {
            "resolved_to": s.run("MATCH ()-[e:RESOLVED_TO]->() RETURN count(e) AS n").single()["n"],
            "per_record_max": s.run("MATCH (s:SourceRecord) OPTIONAL MATCH (s)-[e:RESOLVED_TO]->() WITH s, count(e) AS c RETURN max(c) AS n").single()["n"],
            "parties": sorted(r["k"] for r in s.run("MATCH (p:Party) RETURN p.key AS k")),
            "r3_target": [r["k"] for r in s.run("MATCH (:SourceRecord {record_key: 'r3'})-[:RESOLVED_TO]->(p) RETURN p.key AS k")],
            "names_of_A": sorted(r["t"] for r in s.run("MATCH (:Party {key: 'abn:11'})-[:KNOWN_AS]->(n) RETURN DISTINCT n.normalised AS t")),
            "name_nodes": s.run("MATCH (n:Name) RETURN count(n) AS n").single()["n"],
            "owns": s.run("MATCH (a)-[:OWNS]->(b) RETURN count(*) AS n").single()["n"],
            "holds": s.run("MATCH ()-[:HOLDS]->() RETURN count(*) AS n").single()["n"],
            "bans": s.run("MATCH ()-[:SUBJECT_OF]->() RETURN count(*) AS n").single()["n"],
        }


@pytest.fixture
def scratch_graph():
    d = _driver()
    if d is None:
        pytest.skip("scratch Neo4j on :7688 not reachable (docker compose --profile test up -d neo4j-test)")
    with d.session() as s:
        s.run("MATCH (n) DETACH DELETE n")
    yield d
    with d.session() as s:
        s.run("MATCH (n) DETACH DELETE n")
    d.close()


def test_reload_after_re_resolution_leaves_no_stale_edges(tmp_path, scratch_graph):
    con = store.connect(tmp_path / "t.duckdb")
    _obs(con, "r1", "s1", {"entity.legal_name": "ACME PTY LTD", "entity.abn": "11", "entity.trading_name": "ACME TRADING CO",
                           "address.state": "QLD", "licence.licence_number": "100", "licence.licence_type": "afs",
                           "related_party.name": "PARENT CO", "related_party.lei": "PPPPPPPPPPPPPPPPPPPP",
                           "related_party.relationship": "owned_by"})
    _obs(con, "r2", "s2", {"entity.legal_name": "ACME PTY LTD", "entity.abn": "11", "ban.ban_type": "disqualified",
                           "ban.start_date": "2025-01-01"})
    _obs(con, "r3", "s2", {"entity.legal_name": "ACME HOLDINGS", "entity.acn": "22"})
    _obs(con, "r4", "s3", {"entity.legal_name": "BETA LTD", "entity.abn": "33"})
    # run 1: r3 wrongly sits under A; BETA is its own party C
    _resolution(con, {"r1": "abn:11", "r2": "abn:11", "r3": "abn:11", "r4": "abn:33"},
                {"abn:11": ("organisation", "11", None, None), "abn:33": ("organisation", "33", None, None)})
    L = Loader(con, uri=TEST_URI); L.report_path = tmp_path / "report.csv"
    rep1 = L.run()
    c1 = _counts(scratch_graph)
    assert c1["resolved_to"] == 4 and c1["per_record_max"] == 1 and c1["r3_target"] == ["abn:11"]
    assert c1["parties"] == ["abn:11", "abn:33", "lei:PPPPPPPPPPPPPPPPPPPP"]
    assert c1["names_of_A"] == ["ACME", "ACME HOLDINGS", "ACME TRADING CO"]   # normalised: legal form stripped
    assert c1["owns"] == 1 and c1["holds"] == 1 and c1["bans"] == 1
    assert rep1["reconcile"]["edges_deleted"] == 0 and rep1["reconcile"]["nodes_deleted"] == 0

    # run 2: the matcher improved. r3 moves to its own party B, BETA merges into A (party C disappears),
    # and source s1 no longer reports the trading name "ACME TRADING CO".
    _obs(con, "r1", "s1", {"entity.legal_name": "ACME PTY LTD", "entity.abn": "11", "address.state": "QLD",
                           "licence.licence_number": "100", "licence.licence_type": "afs",
                           "related_party.name": "PARENT CO", "related_party.lei": "PPPPPPPPPPPPPPPPPPPP",
                           "related_party.relationship": "owned_by"})
    _resolution(con, {"r1": "abn:11", "r2": "abn:11", "r3": "acn:22", "r4": "abn:11"},
                {"abn:11": ("organisation", "11", None, None), "acn:22": ("organisation", None, "22", None)})
    L2 = Loader(con, uri=TEST_URI); L2.report_path = tmp_path / "report.csv"
    rep2 = L2.run()
    c2 = _counts(scratch_graph)
    assert c2["resolved_to"] == 4 and c2["per_record_max"] == 1, "every record resolves to exactly one party"
    assert c2["r3_target"] == ["acn:22"], "the old RESOLVED_TO -> abn:11 was swept"
    assert c2["parties"] == ["abn:11", "acn:22", "lei:PPPPPPPPPPPPPPPPPPPP"], "party C merged away, stub parent kept"
    assert c2["names_of_A"] == ["ACME", "BETA"], "dropped trading name gone, merged name arrived"
    assert c2["name_nodes"] == 3, "orphan Name ACME TRADING CO removed; ACME, ACME HOLDINGS, BETA remain (stubs carry no Name node)"
    assert c2["owns"] == 1 and c2["holds"] == 1 and c2["bans"] == 1
    assert rep2["reconcile"]["edges_deleted"] >= 3 and rep2["reconcile"]["nodes_deleted"] == 2   # party C + stale Name node

    # run 3: nothing changed -> nothing deleted, nothing created
    L3 = Loader(con, uri=TEST_URI); L3.report_path = tmp_path / "report.csv"
    rep3 = L3.run()
    assert rep3["reconcile"]["edges_deleted"] == 0 and rep3["reconcile"]["nodes_deleted"] == 0
    assert rep3["parties"]["nodes_created"] == 0 and rep3["source_records"]["relationships_created"] == 0
    assert _counts(scratch_graph) == c2
    L.close(); L2.close(); L3.close(); con.close()
