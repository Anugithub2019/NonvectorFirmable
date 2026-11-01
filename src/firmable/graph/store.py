"""DuckDB store: the columnar side of the system.

What lives here (and not in Neo4j):
  source_records   the CURRENT raw row per record_key, verbatim.
  source_records_history / observations_history
                   every superseded version (a re-ingest with a different content_hash moves the old
                   row and its claims here, stamped superseded_at / superseded_by_hash). Nothing a
                   source ever said is deleted; the active tables hold only the latest claim set so
                   resolution and the views stay simple.
  observations     every canonical claim (record x field x value) with its envelope, current version.
  record_parties   one row per source record: the main party it describes, pivoted from
                   observations (name, abn, acn, lei, type, state, postcode...). The input
                   to blocking and resolution.
  record_related   second parties named by a record (related_party.*), same shape.
  links            resolution decisions, one per linked record (audit table).
  abstentions      records we believed were parties and refused to link, with the reason.
  parties          the resolved parties (canonical key, display name, identifiers).
  load_report      per source: records in, nodes/edges out, rejected, reasons.

Idempotent: loads are keyed on record_key + content_hash; re-loading the same file is a no-op.
"""
from __future__ import annotations

import json
from pathlib import Path

import duckdb

from ..paths import DUCKDB, OUTPUTS

OBS_DIR = OUTPUTS / "observations"

DDL = """
CREATE TABLE IF NOT EXISTS source_records (
  record_key VARCHAR PRIMARY KEY, source_id VARCHAR, source_record_id VARCHAR, source_row INTEGER,
  content_hash VARCHAR, observed_at VARCHAR, ingested_at VARCHAR, licence VARCHAR,
  extractor_version VARCHAR, raw JSON);
CREATE TABLE IF NOT EXISTS observations (
  observation_id VARCHAR, record_key VARCHAR, source_id VARCHAR, source_record_id VARCHAR,
  field VARCHAR, value VARCHAR, raw_value VARCHAR, derivation_level VARCHAR,
  field_confidence DOUBLE, source_reliability DOUBLE, observed_at VARCHAR, valid_from VARCHAR,
  valid_to VARCHAR, extractor_version VARCHAR);
CREATE INDEX IF NOT EXISTS obs_record ON observations(record_key);
CREATE INDEX IF NOT EXISTS obs_field ON observations(field);
CREATE TABLE IF NOT EXISTS source_records_history (
  record_key VARCHAR, source_id VARCHAR, source_record_id VARCHAR, source_row INTEGER,
  content_hash VARCHAR, observed_at VARCHAR, ingested_at VARCHAR, licence VARCHAR,
  extractor_version VARCHAR, raw JSON, superseded_at TIMESTAMP, superseded_by_hash VARCHAR);
CREATE TABLE IF NOT EXISTS observations_history (
  observation_id VARCHAR, record_key VARCHAR, source_id VARCHAR, source_record_id VARCHAR,
  field VARCHAR, value VARCHAR, raw_value VARCHAR, derivation_level VARCHAR,
  field_confidence DOUBLE, source_reliability DOUBLE, observed_at VARCHAR, valid_from VARCHAR,
  valid_to VARCHAR, extractor_version VARCHAR, superseded_at TIMESTAMP, superseded_content_hash VARCHAR);
CREATE TABLE IF NOT EXISTS load_log (
  source_id VARCHAR, file VARCHAR, content_sha VARCHAR, loaded_at TIMESTAMP DEFAULT now(),
  records INTEGER, observations INTEGER, skipped_unchanged INTEGER);
"""

PIVOT_FIELDS = {
    # record_parties column -> observation field
    "name": "entity.legal_name", "entity_type": "entity.entity_type", "status": "entity.status",
    "abn": "entity.abn", "acn": "entity.acn", "nzbn": "entity.nzbn", "lei": "entity.lei", "website": "entity.website",
    "industry_code": "entity.industry_code", "date_registered": "entity.date_registered",
    "address_full": "address.full", "locality": "address.locality", "state": "address.state",
    "postcode": "address.postcode", "country": "address.country",
    "person_role": "person.role", "person_registration": "person.registration_number",
}
RELATED_FIELDS = {
    "name": "related_party.name", "abn": "related_party.abn", "acn": "related_party.acn",
    "lei": "related_party.lei", "relationship": "related_party.relationship",
    "percent": "related_party.percent", "valid_from": "related_party.valid_from",
    "valid_to": "related_party.valid_to", "role": "related_party.role",
}


def connect(path: Path = DUCKDB) -> duckdb.DuckDBPyConnection:
    path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(path))
    con.execute(DDL)
    return con


def load_observations(con: duckdb.DuckDBPyConnection, slug: str) -> dict:
    """Load <slug>.records.jsonl + <slug>.jsonl idempotently, in ONE transaction: a failure
    half-way (e.g. a malformed observations file) leaves nothing behind, so the next run does
    not mistake a partial load for an unchanged source. Returns counts."""
    con.execute("BEGIN TRANSACTION")
    try:
        out = _load_observations(con, slug)
        con.execute("COMMIT")
        return out
    except Exception:
        con.execute("ROLLBACK")
        raise


def _load_observations(con: duckdb.DuckDBPyConnection, slug: str) -> dict:
    rec_path, obs_path = OBS_DIR / f"{slug}.records.jsonl", OBS_DIR / f"{slug}.jsonl"
    if not rec_path.exists():  # shipped outputs are gzipped; DuckDB reads .gz transparently
        rec_path, obs_path = rec_path.with_suffix(".jsonl.gz"), obs_path.with_suffix(".jsonl.gz")
    if not rec_path.exists():
        raise FileNotFoundError(rec_path)
    con.execute("CREATE OR REPLACE TEMP TABLE new_records AS SELECT * FROM read_json_auto(?, "
                "format='newline_delimited', maximum_object_size=4000000, "
                "columns={record_key:'VARCHAR', source_id:'VARCHAR', source_record_id:'VARCHAR', "
                "source_row:'INTEGER', observed_at:'VARCHAR', ingested_at:'VARCHAR', licence:'VARCHAR', "
                "extractor_version:'VARCHAR', content_hash:'VARCHAR', raw:'JSON'})", [str(rec_path)])
    total = con.execute("SELECT count(*) FROM new_records").fetchone()[0]
    unchanged = con.execute("""SELECT count(*) FROM new_records n JOIN source_records s
                               ON s.record_key = n.record_key AND s.content_hash = n.content_hash""").fetchone()[0]
    # changed or new records: the previous version (if any) moves to history, then is replaced
    con.execute("""CREATE OR REPLACE TEMP TABLE changed AS
                   SELECT n.record_key FROM new_records n LEFT JOIN source_records s
                   ON s.record_key = n.record_key AND s.content_hash = n.content_hash
                   WHERE s.record_key IS NULL""")
    con.execute("""INSERT INTO source_records_history
                   SELECT s.*, now(), n.content_hash FROM source_records s
                   JOIN changed c ON c.record_key = s.record_key JOIN new_records n ON n.record_key = s.record_key""")
    superseded = con.execute("SELECT count(*) FROM source_records s JOIN changed c ON c.record_key = s.record_key").fetchone()[0]
    con.execute("""INSERT INTO observations_history
                   SELECT o.*, now(), s.content_hash FROM observations o
                   JOIN changed c ON c.record_key = o.record_key JOIN source_records s ON s.record_key = o.record_key""")
    con.execute("DELETE FROM observations WHERE record_key IN (SELECT record_key FROM changed)")
    con.execute("DELETE FROM source_records WHERE record_key IN (SELECT record_key FROM changed)")
    con.execute("""INSERT INTO source_records SELECT record_key, source_id, source_record_id, source_row,
                   content_hash, observed_at, ingested_at, licence, extractor_version, raw
                   FROM new_records WHERE record_key IN (SELECT record_key FROM changed)""")
    con.execute("CREATE OR REPLACE TEMP TABLE new_obs AS SELECT * FROM read_json(?, "
                "format='newline_delimited', maximum_object_size=4000000, "
                "columns={observation_id:'VARCHAR', source_id:'VARCHAR', source_record_id:'VARCHAR', "
                "source_row:'BIGINT', observed_at:'VARCHAR', observed_at_basis:'VARCHAR', ingested_at:'VARCHAR', "
                "valid_from:'VARCHAR', valid_to:'VARCHAR', licence:'VARCHAR', extractor_version:'VARCHAR', "
                "field:'VARCHAR', value:'VARCHAR', raw_value:'VARCHAR', source_columns:'JSON', transforms:'JSON', "
                "derivation_level:'VARCHAR', confidence:'JSON'})", [str(obs_path)])
    n_obs = con.execute("""INSERT INTO observations
        SELECT observation_id, source_id || ':' || source_record_id, source_id, source_record_id,
               field, value, raw_value, derivation_level,
               TRY_CAST(json_extract(confidence, '$.field_confidence') AS DOUBLE),
               TRY_CAST(json_extract(confidence, '$.source_reliability') AS DOUBLE),
               observed_at, valid_from, valid_to, extractor_version
        FROM new_obs WHERE source_id || ':' || source_record_id IN (SELECT record_key FROM changed)""").fetchone()
    inserted = con.execute("SELECT count(*) FROM changed").fetchone()[0]
    source_id = con.execute("SELECT any_value(source_id) FROM new_records").fetchone()[0]
    con.execute("INSERT INTO load_log (source_id, file, content_sha, records, observations, skipped_unchanged) "
                "VALUES (?, ?, ?, ?, ?, ?)", [source_id, str(rec_path.name), "", inserted,
                                              con.execute("SELECT count(*) FROM new_obs").fetchone()[0], unchanged])
    return {"source_id": source_id, "records_in_file": total, "records_loaded": inserted,
            "skipped_unchanged": unchanged, "superseded_to_history": superseded}


def build_record_parties(con: duckdb.DuckDBPyConnection) -> None:
    """Pivot observations into one row per record (main party) and per related party."""
    cols = ",\n  ".join(f"max(CASE WHEN field = '{f}' THEN value END) AS {c}" for c, f in PIVOT_FIELDS.items() if c != "name")
    con.execute(f"""CREATE OR REPLACE TABLE record_parties AS
        SELECT record_key, any_value(source_id) AS source_id, any_value(source_record_id) AS source_record_id,
          coalesce(max(CASE WHEN field = 'entity.legal_name' THEN value END),
                   max(CASE WHEN field = 'person.full_name' THEN value END)) AS name,
          {cols},
          list(DISTINCT CASE WHEN field = 'entity.trading_name' THEN value END) FILTER (field = 'entity.trading_name') AS trading_names,
          max(CASE WHEN field = 'entity.legal_name' THEN field_confidence END) AS name_confidence,
          any_value(source_reliability) AS source_reliability
        FROM observations GROUP BY record_key""")
    rcols = ",\n  ".join(f"max(CASE WHEN field = '{f}' THEN value END) AS {c}" for c, f in RELATED_FIELDS.items())
    con.execute(f"""CREATE OR REPLACE TABLE record_related AS
        SELECT record_key, any_value(source_id) AS source_id, {rcols}
        FROM observations WHERE field LIKE 'related_party.%' GROUP BY record_key""")
    con.execute("""CREATE OR REPLACE TABLE record_licences AS
        SELECT record_key, any_value(source_id) AS source_id,
          max(CASE WHEN field = 'licence.licence_number' THEN value END) AS licence_number,
          max(CASE WHEN field = 'licence.licence_type' THEN value END) AS licence_type,
          max(CASE WHEN field = 'licence.status' THEN value END) AS status,
          max(CASE WHEN field = 'licence.start_date' THEN value END) AS start_date,
          max(CASE WHEN field = 'licence.end_date' THEN value END) AS end_date,
          list(DISTINCT CASE WHEN field = 'licence.authorisations' THEN value END) FILTER (field = 'licence.authorisations') AS authorisations,
          max(CASE WHEN field = 'licence.conditions' THEN value END) AS conditions
        FROM observations WHERE field LIKE 'licence.%' GROUP BY record_key""")
    con.execute("""CREATE OR REPLACE TABLE record_bans AS
        SELECT record_key, any_value(source_id) AS source_id,
          max(CASE WHEN field = 'ban.ban_type' THEN value END) AS ban_type,
          max(CASE WHEN field = 'ban.start_date' THEN value END) AS start_date,
          max(CASE WHEN field = 'ban.end_date' THEN value END) AS end_date,
          max(CASE WHEN field = 'ban.issuing_authority' THEN value END) AS issuing_authority,
          max(CASE WHEN field = 'ban.reference' THEN value END) AS reference
        FROM observations WHERE field LIKE 'ban.%' GROUP BY record_key""")


def table_counts(con: duckdb.DuckDBPyConnection) -> dict[str, int]:
    names = [r[0] for r in con.execute("SELECT table_name FROM information_schema.tables WHERE table_schema='main'").fetchall()]
    return {n: con.execute(f"SELECT count(*) FROM {n}").fetchone()[0] for n in sorted(names)}


def dump_jsonl(con: duckdb.DuckDBPyConnection, sql: str, path: Path, params: list | None = None) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    cur = con.execute(sql, params or [])
    cols = [d[0] for d in cur.description]
    n = 0
    with path.open("w") as f:
        for row in cur.fetchall():
            f.write(json.dumps(dict(zip(cols, row)), ensure_ascii=False, default=str) + "\n")
            n += 1
    return n


# Which source's value wins for display fields when sources disagree (lower rank wins).
PRECEDENCE = ["local:asic-companies-slice", "local:abr-slice", "local:gleif-lei-au",
              "data.gov.au:asic-afs-licensee", "data.gov.au:asic-credit-licensee",
              "data.gov.au:acnc-register", "qld:qbcc-licensed-contractors-register",
              "qld:ehp-suitable-operator-register-sor-for-environmentally-relevant-activities-eras",
              "data.gov.au:asic-liquidator", "data.gov.au:asic-banned-disqualified-org",
              "nsw:liquor-licence-premises-list-as-at-8-feb-2021",
              "qld:queensland-government-contracts-directory-awarded-contracts", "local:gleif-relationships"]


def build_views(con: duckdb.DuckDBPyConnection) -> None:
    """party_attrs: one row per resolved party with attributes chosen by source precedence.
    v_party / v_licence / v_ban: the flat, stable tables Data-retriever projections read.
    The same party_attrs rows are what the Neo4j loader writes, so graph and table agree."""
    rank = "CASE rp.source_id " + " ".join(f"WHEN '{s}' THEN {i}" for i, s in enumerate(PRECEDENCE)) + " ELSE 99 END"
    attrs = ["name", "entity_type", "status", "state", "postcode", "locality", "address_full", "website",
             "industry_code", "date_registered", "person_role", "person_registration"]
    picks = ",\n  ".join(f"arg_min(rp.{a}, {rank}) FILTER (rp.{a} IS NOT NULL) AS {a if a != 'name' else 'display_name'}"
                         for a in attrs)
    con.execute(f"""CREATE OR REPLACE TABLE party_attrs AS
        SELECT rc.canonical_key AS party_key, any_value(p.party_type) AS party_type, any_value(p.abn) AS abn,
               any_value(p.acn) AS acn, any_value(p.lei) AS lei, any_value(p.n_sources) AS n_sources,
               any_value(p.sources) AS sources,
               {picks},
               count(DISTINCT CASE WHEN rp.name IS NOT NULL THEN upper(rp.name) END) > 1 AS name_conflict,
               list(DISTINCT rp.record_key) AS record_keys
        FROM record_cluster rc JOIN parties p ON p.key = rc.canonical_key
        JOIN record_parties rp ON rp.record_key = rc.record_key
        GROUP BY rc.canonical_key""")
    # Invariant (ontology/NOTES.md): an identifier shared by two parties is a conflict, not a key.
    # Remove it from both and record it, so uniqueness holds and the conflict stays visible.
    con.execute("ALTER TABLE party_attrs ADD COLUMN identifier_conflicts VARCHAR[] DEFAULT []")
    for col in ("abn", "acn", "lei"):
        con.execute(f"""UPDATE party_attrs SET identifier_conflicts = list_append(identifier_conflicts, '{col}:' || {col}),
                        {col} = NULL
                        WHERE {col} IN (SELECT {col} FROM party_attrs WHERE {col} IS NOT NULL GROUP BY {col} HAVING count(*) > 1)""")
    con.execute("""CREATE OR REPLACE VIEW v_licence AS
        SELECT rc.canonical_key AS party_key, pa.display_name, pa.abn, pa.acn, pa.state, pa.postcode, pa.locality,
               l.licence_type || ':' || l.licence_number AS licence_id, l.licence_type, l.licence_number,
               l.status AS licence_status, l.start_date, l.end_date, len(l.authorisations) AS n_authorisations,
               l.source_id, l.record_key
        FROM record_licences l JOIN record_cluster rc ON rc.record_key = l.record_key
        JOIN party_attrs pa ON pa.party_key = rc.canonical_key WHERE l.licence_number IS NOT NULL""")
    con.execute("""CREATE OR REPLACE VIEW v_ban AS
        SELECT rc.canonical_key AS party_key, pa.display_name, pa.abn, pa.acn, pa.state, pa.postcode, pa.locality,
               b.ban_type, b.start_date, b.end_date, b.issuing_authority, b.reference, b.source_id, b.record_key,
               lk.match_type AS link_match_type, lk.confidence AS link_confidence
        FROM record_bans b JOIN record_cluster rc ON rc.record_key = b.record_key
        JOIN party_attrs pa ON pa.party_key = rc.canonical_key
        LEFT JOIN links lk ON lk.left_record_key = b.record_key""")
    con.execute("""CREATE OR REPLACE VIEW v_party AS
        SELECT pa.party_key, pa.party_type, pa.display_name, pa.abn, pa.acn, pa.lei, pa.entity_type, pa.status,
               pa.state, pa.postcode, pa.locality, pa.website, pa.industry_code, pa.date_registered,
               pa.n_sources, pa.sources, pa.name_conflict,
               (SELECT count(*) FROM v_licence l WHERE l.party_key = pa.party_key) AS n_licences,
               (SELECT count(*) FROM v_licence l WHERE l.party_key = pa.party_key AND l.licence_status IN ('cancelled','suspended','ceased')) AS n_licences_ended,
               (SELECT max(end_date) FROM v_licence l WHERE l.party_key = pa.party_key) AS latest_licence_end,
               (SELECT count(*) FROM v_ban b WHERE b.party_key = pa.party_key) AS n_bans,
               (SELECT max(b.end_date) FROM v_ban b WHERE b.party_key = pa.party_key) AS latest_ban_end,
               (SELECT count(*) FROM record_related r JOIN record_cluster rc2 ON rc2.record_key = r.record_key
                 WHERE rc2.canonical_key = pa.party_key AND r.relationship IN ('owned_by','ultimately_owned_by')) AS n_owners_declared
        FROM party_attrs pa""")
