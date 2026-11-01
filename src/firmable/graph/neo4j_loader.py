"""Load the resolved graph from DuckDB into Neo4j so that the graph equals the DuckDB state.

Idempotent AND reconciling: every node and edge is MERGEd on its identifier (ontology/schema.yaml
`constraints.unique`) and stamped with this run's `load_id`; at the end, every derived node or
edge that was NOT stamped is deleted (mark-and-sweep). So a record that re-resolved from party A
to party B ends with exactly one RESOLVED_TO (to B); a name a source dropped loses its KNOWN_AS;
a party that merged away disappears. Re-running on unchanged data changes nothing.

Pipeline per run:
  1. apply ontology/graph.cypher (constraints + indexes)
  2. Party nodes      from parties x record_parties (display_name by source precedence)
  3. Name nodes       from every legal/trading name (KNOWN_AS with kind, source, validity)
  4. SourceRecord     from source_records + RESOLVED_TO from links
  5. Licence / Ban    from record_licences / record_bans, edges from the record's party
  6. Relationships    from record_related (related_party.*): OWNS / AFFILIATED_WITH / ...
  7. reconcile        delete nodes/edges not stamped by this run
  8. load_report.csv  records_in, nodes_out, edges_out, rejected per source
"""
from __future__ import annotations

import csv
import json
import re
import os
import time
import uuid
from collections import defaultdict
from datetime import datetime, timezone

import duckdb
from neo4j import GraphDatabase

from ..paths import ONTOLOGY_DIR, OUTPUTS
from ..resolve import normalise as N
from .store import PRECEDENCE  # noqa: F401 - single definition of source precedence

URI = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
AUTH = (os.environ.get("NEO4J_USER", "neo4j"), os.environ.get("NEO4J_PASSWORD", "firmable-graph"))
BATCH = 2000
DERIVED_EDGES = "RESOLVED_TO|KNOWN_AS|HOLDS|SUBJECT_OF|OWNS|AFFILIATED_WITH|RELATED_TO"
DERIVED_LABELS = ("Party", "Name", "Licence", "Ban", "SourceRecord")
REL_EDGE = {"owned_by": ("OWNS", "parent->child"), "owns": ("OWNS", "child->parent"),
            "ultimately_owned_by": ("OWNS", "parent->child"), "member_of": ("AFFILIATED_WITH", "self->related"),
            "employs": ("AFFILIATED_WITH", "related->self"), "successor_of": ("SUCCESSOR_OF", "self->related"),
            "trustee_for": ("TRUSTEE_FOR", "self->related"), "trading_as": ("KNOWN_AS", "name"),
            "other": ("RELATED_TO", "self->related")}


class Loader:
    def __init__(self, con: duckdb.DuckDBPyConnection, uri: str = URI, auth: tuple[str, str] = AUTH):
        self.con = con
        self.driver = GraphDatabase.driver(uri, auth=auth)
        self.load_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:6]
        self.report_path = OUTPUTS / "load_report.csv"
        self.report: dict[str, dict] = defaultdict(lambda: {"records_in": 0, "nodes_out": 0, "edges_out": 0,
                                                            "records_rejected": 0, "rejection_reasons": defaultdict(int)})
        self.timing: dict[str, float] = {}

    def close(self):
        self.driver.close()

    def run_cypher(self, q: str, rows: list[dict] | None = None) -> dict:
        with self.driver.session() as s:
            if rows is None:
                return s.run(q).consume().counters.__dict__
            counters = defaultdict(int)
            for i in range(0, len(rows), BATCH):
                c = s.run(q, rows=rows[i:i + BATCH], load_id=self.load_id).consume().counters
                counters["nodes_created"] += c.nodes_created
                counters["relationships_created"] += c.relationships_created
                counters["properties_set"] += c.properties_set
            return dict(counters)

    # ---------------------------------------------------------------------------------
    def schema(self) -> None:
        for stmt in (ONTOLOGY_DIR / "graph.cypher").read_text().split(";"):
            stmt = "\n".join(l for l in stmt.splitlines() if not l.strip().startswith("//")).strip()
            if stmt:
                self.run_cypher(stmt)

    def parties(self) -> dict:
        """One Party node per canonical key, attributes from DuckDB party_attrs (source precedence
        is applied there, in SQL, so the graph and the flat views cannot disagree)."""
        cur = self.con.execute("""SELECT party_key AS key, party_type, abn, acn, lei, n_sources, sources, display_name,
            entity_type, status, state, postcode, locality, address_full, website, industry_code, date_registered,
            person_role, person_registration, name_conflict, identifier_conflicts FROM party_attrs""")
        cols = [d[0] for d in cur.description]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]
        q = """UNWIND $rows AS r
            MERGE (p:Party {key: r.key})
            SET p.display_name = r.display_name, p.abn = r.abn, p.acn = r.acn, p.lei = r.lei,
                p.entity_type = r.entity_type, p.status = r.status, p.state = r.state, p.postcode = r.postcode,
                p.locality = r.locality, p.address_full = r.address_full, p.website = r.website,
                p.industry_code = r.industry_code, p.date_registered = r.date_registered,
                p.person_role = r.person_role, p.person_registration = r.person_registration,
                p.n_sources = r.n_sources, p.sources = r.sources, p.name_conflict = r.name_conflict,
                p.identifier_conflicts = r.identifier_conflicts,
                p.matcher_version = 'resolver-0.1.0', p.loaded_at = datetime(), p.load_id = $load_id, p.stub = null
            WITH p, r
            CALL { WITH p, r WITH p, r WHERE r.party_type = 'person' SET p:Person RETURN 1 AS x
                   UNION WITH p, r WITH p, r WHERE r.party_type <> 'person' SET p:Organisation RETURN 1 AS x }
            RETURN count(*)"""
        return self.run_cypher(q, rows)

    def names(self) -> dict:
        cur = self.con.execute("""
            SELECT rc.canonical_key, o.source_id, o.field, o.value, o.valid_from, o.valid_to
            FROM observations o JOIN record_cluster rc ON rc.record_key = o.record_key
            WHERE o.field IN ('entity.legal_name', 'entity.trading_name', 'entity.former_name', 'person.full_name') AND o.value IS NOT NULL""")
        rows = []
        for key, src, field, value, vf, vt in cur.fetchall():
            if re.fullmatch(r"[A-Z0-9]{20}|\d{9,11}", value.strip()):
                continue  # an identifier carried in a name field is not a name
            norm = N.normalise(value)
            if not norm:
                continue
            rows.append({"key": key, "normalised": norm, "text": value, "source_id": src,
                         "kind": {"entity.legal_name": "legal", "person.full_name": "legal",
                                  "entity.trading_name": "trading", "entity.former_name": "former"}[field],
                         "valid_from": vf, "valid_to": vt})
        q = """UNWIND $rows AS r
            MATCH (p:Party {key: r.key})
            MERGE (n:Name {normalised: r.normalised}) ON CREATE SET n.text = r.text
            SET n.load_id = $load_id
            MERGE (p)-[k:KNOWN_AS {kind: r.kind, source_id: r.source_id}]->(n)
            SET k.valid_from = r.valid_from, k.valid_to = r.valid_to, k.load_id = $load_id"""
        res = self.run_cypher(q, rows)
        with self.driver.session() as sess:  # degree watch from the ontology: generic names
            hot = [dict(r) for r in sess.run("MATCH (n:Name)<-[k:KNOWN_AS]-() WITH n, count(k) AS d "
                                             "WHERE d > 50 RETURN n.normalised AS name, d ORDER BY d DESC LIMIT 10")]
        res["hot_names_over_50"] = hot
        return res

    def source_records(self) -> dict:
        cur = self.con.execute("""
            SELECT s.record_key, s.source_id, s.source_record_id, s.content_hash, s.observed_at, s.ingested_at,
                   s.licence, s.extractor_version, l.canonical_key, l.match_type, l.confidence, l.threshold,
                   l.evidence, l.matcher_version
            FROM source_records s LEFT JOIN links l ON l.left_record_key = s.record_key""")
        cols = [d[0] for d in cur.description]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]
        for r in rows:
            r["evidence"] = r["evidence"] if isinstance(r["evidence"], str) else json.dumps(r["evidence"])
        q = """UNWIND $rows AS r
            MERGE (s:SourceRecord {record_key: r.record_key})
            SET s.source_id = r.source_id, s.source_record_id = r.source_record_id, s.content_hash = r.content_hash,
                s.observed_at = r.observed_at, s.ingested_at = r.ingested_at, s.licence = r.licence,
                s.extractor_version = r.extractor_version, s.load_id = $load_id
            WITH s, r WHERE r.canonical_key IS NOT NULL
            MATCH (p:Party {key: r.canonical_key})
            MERGE (s)-[e:RESOLVED_TO]->(p)
            SET e.match_type = r.match_type, e.confidence = r.confidence, e.threshold = r.threshold,
                e.evidence = r.evidence, e.matcher_version = r.matcher_version, e.load_id = $load_id"""
        return self.run_cypher(q, rows)

    def licences(self) -> dict:
        cur = self.con.execute("""
            SELECT l.record_key, l.source_id, rc.canonical_key, l.licence_number, l.licence_type, l.status,
                   l.start_date, l.end_date, l.authorisations, l.conditions
            FROM record_licences l JOIN record_cluster rc ON rc.record_key = l.record_key
            WHERE l.licence_number IS NOT NULL""")
        cols = [d[0] for d in cur.description]
        rows = []
        for r in cur.fetchall():
            d = dict(zip(cols, r))
            d["licence_id"] = f"{d['licence_type'] or 'other'}:{d['licence_number']}"
            d["authorisations"] = [a for a in (d["authorisations"] or []) if a]
            rows.append(d)
        q = """UNWIND $rows AS r
            MATCH (p:Party {key: r.canonical_key})
            MERGE (l:Licence {licence_id: r.licence_id})
            SET l.licence_type = r.licence_type, l.licence_number = r.licence_number, l.status = r.status,
                l.start_date = r.start_date, l.end_date = r.end_date, l.authorisations = r.authorisations,
                l.conditions = r.conditions, l.source_id = r.source_id, l.record_key = r.record_key, l.load_id = $load_id
            MERGE (p)-[h:HOLDS {source_id: r.source_id}]->(l)
            SET h.valid_from = r.start_date, h.valid_to = r.end_date, h.load_id = $load_id"""
        return self.run_cypher(q, rows)

    def bans(self) -> dict:
        cur = self.con.execute("""
            SELECT b.record_key, b.source_id, rc.canonical_key, b.ban_type, b.start_date, b.end_date,
                   b.issuing_authority, b.reference, l.match_type, l.confidence
            FROM record_bans b JOIN record_cluster rc ON rc.record_key = b.record_key
            LEFT JOIN links l ON l.left_record_key = b.record_key""")
        cols = [d[0] for d in cur.description]
        rows = [dict(zip(cols, r)) | {"ban_id": r[0]} for r in cur.fetchall()]
        q = """UNWIND $rows AS r
            MATCH (p:Party {key: r.canonical_key})
            MERGE (b:Ban {ban_id: r.ban_id})
            SET b.ban_type = r.ban_type, b.start_date = r.start_date, b.end_date = r.end_date,
                b.issuing_authority = r.issuing_authority, b.reference = r.reference, b.source_id = r.source_id, b.load_id = $load_id
            MERGE (p)-[s:SUBJECT_OF {source_id: r.source_id}]->(b)
            SET s.match_type = r.match_type, s.confidence = r.confidence, s.valid_from = r.start_date, s.valid_to = r.end_date,
                s.load_id = $load_id"""
        return self.run_cypher(q, rows)

    def related(self) -> dict:
        """related_party.* -> second Party (by identifier if it has one, else a name-keyed
        singleton) + typed edge. Direction per REL_EDGE."""
        cur = self.con.execute("""
            SELECT r.record_key, r.source_id, rc.canonical_key, r.name, r.abn, r.acn, r.lei, r.relationship,
                   r.percent, r.valid_from, r.valid_to, r.role
            FROM record_related r JOIN record_cluster rc ON rc.record_key = r.record_key
            WHERE r.relationship IS NOT NULL AND (r.name IS NOT NULL OR r.abn IS NOT NULL OR r.acn IS NOT NULL OR r.lei IS NOT NULL)""")
        cols = [d[0] for d in cur.description]
        fetched = cur.fetchall()  # fetch BEFORE other statements: a new execute() invalidates this cursor
        by_abn = dict(self.con.execute("SELECT abn, key FROM parties WHERE abn IS NOT NULL").fetchall())
        by_acn = dict(self.con.execute("SELECT acn, key FROM parties WHERE acn IS NOT NULL").fetchall())
        by_lei = dict(self.con.execute("SELECT lei, key FROM parties WHERE lei IS NOT NULL").fetchall())
        rows, unresolved = [], 0
        for r in fetched:
            d = dict(zip(cols, r))
            abn, acn, lei = N.digits(d["abn"]) or None, N.digits(d["acn"]) or None, d["lei"]
            other = (by_abn.get(abn) if abn else None) or (by_acn.get(acn) if acn else None) or (by_lei.get(lei) if lei else None)
            if other is None:
                # no party has this identifier (e.g. a foreign GLEIF parent): an identifier-keyed stub,
                # so chains can terminate at it; a name-only related party becomes a name-keyed stub
                # (never merged by name with anything else).
                ident = N.canonical_key(abn, acn, lei)
                if ident:
                    other = ident
                    d["stub_name"] = d["name"] or f"({ident})"
                elif d["name"]:
                    other = f"stub:{N.normalise(d['name'])[:80]}"
                    d["stub_name"] = d["name"]
                else:
                    unresolved += 1
                    continue
            edge, direction = REL_EDGE.get(d["relationship"], ("RELATED_TO", "self->related"))
            d.update({"other_key": other, "edge": edge, "direction": direction, "other_abn": abn, "other_acn": acn, "other_lei": lei})
            rows.append(d)
        q = """UNWIND $rows AS r
            MATCH (a:Party {key: r.canonical_key})
            MERGE (b:Party {key: r.other_key})
            ON CREATE SET b:Organisation, b.display_name = coalesce(r.stub_name, r.other_key), b.abn = r.other_abn,
                          b.acn = r.other_acn, b.lei = r.other_lei, b.stub = true, b.sources = [r.source_id]
            SET b.load_id = $load_id
            WITH a, b, r
            CALL {
              WITH a, b, r WITH a, b, r WHERE r.edge = 'OWNS' AND r.direction = 'parent->child'
                MERGE (b)-[e:OWNS {source_id: r.source_id, kind: coalesce(r.role, r.relationship)}]->(a)
                SET e.percent = r.percent, e.valid_from = r.valid_from, e.valid_to = r.valid_to, e.load_id = $load_id RETURN 1 AS x
              UNION WITH a, b, r WITH a, b, r WHERE r.edge = 'OWNS' AND r.direction = 'child->parent'
                MERGE (a)-[e:OWNS {source_id: r.source_id, kind: coalesce(r.role, r.relationship)}]->(b)
                SET e.percent = r.percent, e.valid_from = r.valid_from, e.valid_to = r.valid_to, e.load_id = $load_id RETURN 1 AS x
              UNION WITH a, b, r WITH a, b, r WHERE r.edge = 'AFFILIATED_WITH' AND (a:Person OR NOT b:Person)
                MERGE (a)-[e:AFFILIATED_WITH {source_id: r.source_id}]->(b)
                SET e.role = coalesce(r.role, r.relationship), e.valid_from = r.valid_from, e.valid_to = r.valid_to, e.load_id = $load_id RETURN 1 AS x
              UNION WITH a, b, r WITH a, b, r WHERE r.edge = 'AFFILIATED_WITH' AND NOT a:Person AND b:Person
                MERGE (b)-[e:AFFILIATED_WITH {source_id: r.source_id}]->(a)
                SET e.role = coalesce(r.role, r.relationship), e.valid_from = r.valid_from, e.valid_to = r.valid_to, e.load_id = $load_id RETURN 1 AS x
              UNION WITH a, b, r WITH a, b, r WHERE r.edge IN ['SUCCESSOR_OF', 'TRUSTEE_FOR', 'RELATED_TO']
                MERGE (a)-[e:RELATED_TO {source_id: r.source_id, kind: r.relationship}]->(b)
                SET e.role = r.role, e.valid_from = r.valid_from, e.valid_to = r.valid_to, e.load_id = $load_id RETURN 1 AS x
            }
            RETURN count(*)"""
        res = self.run_cypher(q, rows)
        res["unresolved_related_parties"] = unresolved
        return res

    def reconcile(self) -> dict:
        """Sweep: delete every derived edge and node this run did not stamp. After this the graph
        asserts exactly what DuckDB asserts; stale RESOLVED_TO / KNOWN_AS / HOLDS edges from a
        record that re-resolved, and parties that merged away, are gone."""
        out = {}
        with self.driver.session() as s:
            r = s.run(f"MATCH ()-[e:{DERIVED_EDGES}]->() WHERE e.load_id IS NULL OR e.load_id <> $load_id "
                      "CALL { WITH e DELETE e } IN TRANSACTIONS OF 10000 ROWS RETURN count(*) AS n",
                      load_id=self.load_id).single()
            out["edges_deleted"] = r["n"]
            labels = " OR ".join(f"n:{l}" for l in DERIVED_LABELS)
            r = s.run(f"MATCH (n) WHERE ({labels}) AND (n.load_id IS NULL OR n.load_id <> $load_id) "
                      "CALL { WITH n DETACH DELETE n } IN TRANSACTIONS OF 10000 ROWS RETURN count(*) AS n",
                      load_id=self.load_id).single()
            out["nodes_deleted"] = r["n"]
            # a Name node nobody is KNOWN_AS any more has no reason to exist
            r = s.run("MATCH (n:Name) WHERE NOT ()-[:KNOWN_AS]->(n) "
                      "CALL { WITH n DELETE n } IN TRANSACTIONS OF 10000 ROWS RETURN count(*) AS n").single()
            out["orphan_names_deleted"] = r["n"]
        out["load_id"] = self.load_id
        return out

    # ---------------------------------------------------------------------------------
    def load_report(self) -> None:
        """records_in / nodes_out / edges_out per source, from the graph itself."""
        per_source = self.con.execute("""
            SELECT s.source_id, count(*) AS records_in,
                   count(*) FILTER (l.canonical_key IS NOT NULL) AS linked,
                   count(*) FILTER (a.record_key IS NOT NULL) AS abstained
            FROM source_records s LEFT JOIN links l ON l.left_record_key = s.record_key
            LEFT JOIN abstentions a ON a.record_key = s.record_key GROUP BY 1 ORDER BY 1""").fetchall()
        with self.driver.session() as sess:
            nodes = {r["src"]: r["n"] for r in sess.run(
                "MATCH (p:Party) UNWIND p.sources AS src RETURN src, count(DISTINCT p) AS n")}
            edges = {r["src"]: r["n"] for r in sess.run(
                "MATCH ()-[e]->() WHERE e.source_id IS NOT NULL RETURN e.source_id AS src, count(e) AS n")}
            resolved_edges = {r["src"]: r["n"] for r in sess.run(
                "MATCH (s:SourceRecord)-[e:RESOLVED_TO]->() RETURN s.source_id AS src, count(e) AS n")}
            rej = {r["src"]: (r["n"], r["reason"]) for r in sess.run(
                "MATCH (s:SourceRecord) WHERE NOT (s)-[:RESOLVED_TO]->() RETURN s.source_id AS src, count(s) AS n, 'abstained' AS reason")}
        top_reason = {r[0]: r[1] for r in self.con.execute(
            "SELECT source, arg_max(reason, c) FROM (SELECT source, reason, count(*) c FROM abstentions GROUP BY 1,2) GROUP BY 1").fetchall()}
        self.report_path.parent.mkdir(parents=True, exist_ok=True)
        with self.report_path.open("w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["source", "records_in", "nodes_out", "edges_out", "records_rejected", "top_rejection_reason"])
            for src, n_in, linked, abstained in per_source:
                w.writerow([src, n_in, nodes.get(src, 0) + n_in,   # party nodes touched + its SourceRecord nodes
                            edges.get(src, 0) + resolved_edges.get(src, 0), abstained,
                            top_reason.get(src, "") if abstained else ""])

    def run(self) -> dict:
        out = {}
        for step in ("schema", "parties", "names", "source_records", "licences", "bans", "related", "reconcile"):
            t0 = time.time()
            out[step] = getattr(self, step)()
            self.timing[step] = round(time.time() - t0, 1)
            print(f"  neo4j {step:<15} {self.timing[step]:6.1f}s {out[step]}")
        self.load_report()
        out["timing"] = self.timing
        return out
