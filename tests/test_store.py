"""DuckDB store: a re-ingested record with a different content hash supersedes the old version
rather than deleting it; unchanged records are no-ops; history is append-only."""
from __future__ import annotations

import json

from firmable.graph import store


def _write(dirpath, slug, records):
    rec_lines, obs_lines = [], []
    for rk, h, name in records:
        src, rid = rk.split(":", 1)
        rec_lines.append(json.dumps({"record_key": rk, "source_id": src, "source_record_id": rid, "source_row": 1,
                                     "observed_at": "2026-01-01", "ingested_at": "2026-01-01", "licence": "cc-by",
                                     "extractor_version": "t", "content_hash": h, "raw": {"name": name}}))
        obs_lines.append(json.dumps({"observation_id": f"{rk}:n", "source_id": src, "source_record_id": rid, "source_row": 1,
                                     "observed_at": "2026-01-01", "observed_at_basis": "x", "ingested_at": "2026-01-01",
                                     "valid_from": None, "valid_to": None, "licence": "cc-by", "extractor_version": "t",
                                     "field": "entity.legal_name", "value": name, "raw_value": name, "source_columns": [],
                                     "transforms": [], "derivation_level": "direct",
                                     "confidence": {"field_confidence": 0.9, "source_reliability": 0.9}}))
    (dirpath / f"{slug}.records.jsonl").write_text("\n".join(rec_lines))
    (dirpath / f"{slug}.jsonl").write_text("\n".join(obs_lines))


def test_reingest_supersedes_into_history_instead_of_deleting(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "OBS_DIR", tmp_path)
    con = store.connect(tmp_path / "t.duckdb")
    _write(tmp_path, "s", [("s:1", "h1", "ACME PTY LTD"), ("s:2", "h2", "BETA LTD")])
    r1 = store.load_observations(con, "s")
    assert r1["records_loaded"] == 2 and r1["superseded_to_history"] == 0

    # record 1 changes name (new content hash); record 2 unchanged
    _write(tmp_path, "s", [("s:1", "h1b", "ACME GROUP PTY LTD"), ("s:2", "h2", "BETA LTD")])
    r2 = store.load_observations(con, "s")
    assert r2["records_loaded"] == 1 and r2["skipped_unchanged"] == 1 and r2["superseded_to_history"] == 1
    assert con.execute("SELECT value FROM observations WHERE record_key = 's:1'").fetchone()[0] == "ACME GROUP PTY LTD"
    assert con.execute("SELECT count(*) FROM source_records").fetchone()[0] == 2
    hist = con.execute("SELECT record_key, content_hash, superseded_by_hash FROM source_records_history").fetchall()
    assert hist == [("s:1", "h1", "h1b")]
    assert con.execute("SELECT value, superseded_content_hash FROM observations_history").fetchall() == [("ACME PTY LTD", "h1")]

    # a third, identical load: nothing moves, nothing changes
    r3 = store.load_observations(con, "s")
    assert r3["records_loaded"] == 0 and r3["superseded_to_history"] == 0
    assert con.execute("SELECT count(*) FROM source_records_history").fetchone()[0] == 1
    con.close()
