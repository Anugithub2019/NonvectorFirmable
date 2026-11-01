"""Integration smoke test against the live graph. Skipped when Neo4j or the DuckDB file is absent."""
import pytest

from firmable.paths import DUCKDB


def _api():
    from firmable.retrieval.graph_api import GraphAPI
    try:
        api = GraphAPI()
        api._run("RETURN 1")
        return api
    except Exception:  # noqa: BLE001
        return None


pytestmark = pytest.mark.skipif(not DUCKDB.exists(), reason="no DuckDB store built")


def test_resolve_identifier_path_and_abstention():
    api = _api()
    if api is None:
        pytest.skip("Neo4j not reachable")
    r = api.resolve("Zyxwv Quantum Haulage Pty Ltd")
    assert r["decision"] in ("abstained", "ambiguous")
    bad = api.resolve("ABN 51 824 753 557")  # checksum fails
    assert any("checksum" in p for p in bad["paths"])
    api.close()


def test_read_cypher_refuses_writes():
    api = _api()
    if api is None:
        pytest.skip("Neo4j not reachable")
    assert "error" in api.read_cypher("MATCH (n) DETACH DELETE n")
    assert "rows" in api.read_cypher("MATCH (p:Party) RETURN p.key LIMIT 1")
    api.close()


def test_projection_preview_is_deterministic():
    api = _api()
    if api is None:
        pytest.skip("Neo4j not reachable")
    spec = {"name": "t", "base": "organisation", "columns": ["party_key", "display_name", "state"],
            "filters": [{"column": "state", "op": "=", "value": "QLD"}], "order_by": "party_key", "limit": 50}
    a, b = api.projection(spec, preview=True), api.projection(spec, preview=True)
    assert a["rows"] == b["rows"] and a["matched_count"] == b["matched_count"]
    assert a["exported_count"] <= 20 and a["generation"] == b["generation"]
    assert 'ORDER BY "party_key"' in a["sql"]
    api.close()


def test_projection_rejects_unknown_filter_column_instead_of_dropping_it():
    api = _api()
    if api is None:
        pytest.skip("Neo4j not reachable")
    spec = {"name": "t", "base": "organisation", "columns": ["party_key"],
            "filters": [{"column": "not_a_column", "op": "=", "value": "x"}], "limit": 5}
    r = api.projection(spec, preview=True)
    assert "error" in r and "not_a_column" in r["error"]
    assert api.validate_projection({"base": "licence", "columns": ["party_key"],
                                    "filters": [{"column": "end_date", "op": "within_days", "value": "ninety"}]})
    api.close()


def test_export_reports_matched_and_exported_separately(tmp_path):
    api = _api()
    if api is None:
        pytest.skip("Neo4j not reachable")
    spec = {"name": "t", "base": "organisation", "columns": ["party_key", "display_name"], "limit": 3}
    r = api.projection(spec, preview=False, out_dir=tmp_path)
    assert r["exported_count"] == 3 and r["matched_count"] > 3 and r["truncated"]
    assert sum(1 for _ in open(r["csv"])) == 4  # header + 3 rows
    meta = __import__("json").loads(open(r["spec_file"]).read())
    assert meta["exported_count"] == 3 and meta["truncated"] and meta["spec"]["as_of"]
    api.close()


def test_cypher_timeout_is_a_transaction_timeout():
    api = _api()
    if api is None:
        pytest.skip("Neo4j not reachable")
    # a query that cannot finish in 1 s: a filtered cartesian product over parties (plain count(*)
    # over a cartesian product is short-circuited by the planner, so the filter is what forces work)
    r = api.read_cypher("MATCH (a:Party), (b:Party) WHERE a.display_name < b.display_name RETURN count(*)", timeout_s=1)
    assert "error" in r and "TransactionTimedOut" in r["error"]
    api.close()
