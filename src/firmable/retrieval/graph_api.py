"""The lookup an agent calls. Every function returns plain dicts with the query that produced
them, so the agent (and the demo) can show WHY, not just WHAT.

resolve(reference)        messy text -> ranked candidates, each with match_type, score, evidence, path
entity(key)               identifiers, names, source records, licences, bans, owners, subsidiaries (capped)
ultimate_parent(key)      follow OWNS upwards; bounded; reports cycles
within_hops(...)          parties within N hops of a banned/disqualified party (or of a given key)
read_cypher(query)        read-only, time- and row-capped Cypher for questions only the graph answers
projection(spec)          flat table over DuckDB (+ optional graph predicate) -> CSV/Parquet + spec

No embeddings anywhere: candidates come from identifiers, exact normalised names and a Lucene
full-text index over every name variant; the Jev decision model scores the top few.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path

import duckdb
from rapidfuzz.distance import JaroWinkler
from neo4j import GraphDatabase, Query

from .. import llm
from ..ontology import abn_valid, acn_valid
from ..paths import DUCKDB, OUTPUTS
from ..resolve import normalise as N
from ..resolve.resolver import JEV_MATCH_Q

URI = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
AUTH = (os.environ.get("NEO4J_USER", "neo4j"), os.environ.get("NEO4J_PASSWORD", "firmable-graph"))
CAP = 25                       # neighbours returned per type; the rest is counted, not returned
RESOLVE_THRESHOLD = 0.85       # P(same) from Jev needed to call a reference resolved
AMBIGUITY_GAP = 0.10           # top two within this gap -> ambiguous: ask, do not guess
MAX_DEPTH = 12                 # ultimate-parent chain bound
TRAVERSAL_RELS = "OWNS|AFFILIATED_WITH|RELATED_TO"   # never KNOWN_AS (shared names are not relationships)
QUERY_TIMEOUT_S = 30           # server-side transaction timeout for typed queries
CYPHER_TIMEOUT_S = 15          # ... and for agent-written Cypher
EXPORT_MAX_ROWS = 100_000
_FORBIDDEN = re.compile(r"\b(CREATE|MERGE|DELETE|DETACH|SET|REMOVE|DROP|CALL\s+dbms|CALL\s+apoc\.(?!text)|LOAD\s+CSV)\b", re.I)


class GraphAPI:
    def __init__(self, duck_path: Path = DUCKDB, read_only: bool = True):
        self.driver = GraphDatabase.driver(URI, auth=AUTH, notifications_disabled_classifications=["DEPRECATION"])
        self.duck_path = Path(duck_path)
        self.con = duckdb.connect(str(duck_path), read_only=read_only)
        self._generation: str | None = None

    def close(self):
        self.driver.close()
        self.con.close()

    def _run(self, q: str, timeout_s: float = QUERY_TIMEOUT_S, **params) -> list[dict]:
        # neo4j.Query carries the transaction timeout; a bare `timeout=` kwarg on Session.run would be
        # treated as a query parameter, not a limit.
        with self.driver.session(default_access_mode="READ") as s:
            rows = [r.data() for r in s.run(Query(q, timeout=timeout_s), **params)]
        return json.loads(json.dumps(rows, default=str))  # neo4j DateTime etc. -> plain JSON values

    def generation(self) -> str:
        """Identity of the data this API answers from: changes whenever the DuckDB store is rebuilt.
        Cheap (no file hash): file size + mtime + party/link counts + resolver version."""
        if self._generation is None:
            st = self.duck_path.stat()
            n_parties = self.con.execute("SELECT count(*) FROM parties").fetchone()[0]
            n_links, ver = self.con.execute("SELECT count(*), max(matcher_version) FROM links").fetchone()
            raw = f"{st.st_size}:{int(st.st_mtime)}:{n_parties}:{n_links}:{ver}"
            self._generation = hashlib.sha1(raw.encode()).hexdigest()[:12]
        return self._generation

    # ---------------------------------------------------------------- resolve
    def resolve(self, reference: str, limit: int = 5, use_jev: bool = True) -> dict:
        t0 = time.time()
        ref = reference.strip()
        cands: list[dict] = []
        paths: list[str] = []
        d = N.digits(ref)
        # 1. identifier path
        if len(d) == 11 and abn_valid(d):
            q = "MATCH (p:Party {abn: $abn}) RETURN p.key AS key, p.display_name AS name, p.state AS state, p.postcode AS postcode, p.entity_type AS entity_type, p.status AS status, p.sources AS sources"
            paths.append(q)
            for r in self._run(q, abn=d):
                cands.append(_cand(r, 0.99, "exact_abn", {"abn": d, "checksum": "valid"}, q))
        elif len(d) == 9 and acn_valid(d):
            q = "MATCH (p:Party {acn: $acn}) RETURN p.key AS key, p.display_name AS name, p.state AS state, p.postcode AS postcode, p.entity_type AS entity_type, p.status AS status, p.sources AS sources"
            paths.append(q)
            for r in self._run(q, acn=d):
                cands.append(_cand(r, 0.99, "exact_acn", {"acn": d, "checksum": "valid"}, q))
        elif re.fullmatch(r"[A-Z0-9]{20}", ref.upper()):
            q = "MATCH (p:Party {lei: $lei}) RETURN p.key AS key, p.display_name AS name, p.state AS state, p.postcode AS postcode, p.entity_type AS entity_type, p.status AS status, p.sources AS sources"
            paths.append(q)
            for r in self._run(q, lei=ref.upper()):
                cands.append(_cand(r, 0.99, "exact_lei", {"lei": ref.upper()}, q))
        elif len(d) in (9, 11):
            paths.append(f"identifier {d} failed its checksum: identifier path skipped")
        # 2. exact normalised name path
        norm = N.normalise(re.sub(r"\(?\b(ABN|ACN)\b[\s:]*[\d ]+\)?", " ", ref, flags=re.I))
        if norm and not cands:
            q = ("MATCH (n:Name {normalised: $norm})<-[k:KNOWN_AS]-(p:Party) "
                 "RETURN DISTINCT p.key AS key, p.display_name AS name, p.state AS state, p.postcode AS postcode, "
                 "p.entity_type AS entity_type, p.status AS status, p.sources AS sources, collect(DISTINCT k.kind) AS kinds")
            paths.append(q)
            for r in self._run(q, norm=norm):
                cands.append(_cand(r, 0.95, "name_exact_norm", {"normalised": norm, "name_kinds": r["kinds"]}, q))
        # 3. semantic path: full-text (fuzzy) over every name variant, then Jev on the top few
        if norm and not cands:
            lucene = " ".join(f"{t}~1" if len(t) > 4 else t for t in N.tokens(norm)[:8])
            q = ("CALL db.index.fulltext.queryNodes('name_text', $lucene) YIELD node, score "
                 "MATCH (node)<-[k:KNOWN_AS]-(p:Party) "
                 "RETURN p.key AS key, p.display_name AS name, p.state AS state, p.postcode AS postcode, "
                 "p.entity_type AS entity_type, p.status AS status, p.sources AS sources, node.text AS matched_name, "
                 "max(score) AS ft ORDER BY ft DESC LIMIT 20")
            paths.append(q)
            seen = {}
            for r in self._run(q, lucene=lucene):
                sim = _jw(norm, N.normalise(r["matched_name"] or ""))
                if r["key"] not in seen or sim > seen[r["key"]]["evidence"]["string_similarity"]:
                    seen[r["key"]] = _cand(r, sim, "name_semantic", {"matched_name": r["matched_name"],
                                            "string_similarity": round(sim, 3), "fulltext_score": round(r["ft"], 2)}, q)
            ranked = sorted(seen.values(), key=lambda c: -c["score"])[:6]
            ask = [c for c in ranked if use_jev and c["evidence"]["string_similarity"] >= 0.75]
            from concurrent.futures import ThreadPoolExecutor
            with ThreadPoolExecutor(max(1, len(ask))) as ex:  # score candidates concurrently
                for c, (p, rel) in zip(ask, ex.map(lambda c: self._jev(ref, c), ask)):
                    c["evidence"]["jev_p_same"], c["evidence"]["jev_relationship"] = p, rel
                    c["score"] = round(p, 3)
            for c in ranked:
                if c not in ask:
                    c["score"] = round(c["evidence"]["string_similarity"] * 0.8, 3)  # sub-threshold by construction
            cands = sorted(ranked, key=lambda c: -c["score"])
        cands = cands[:limit]
        decision = "abstained"
        if cands:
            top = cands[0]["score"]
            second = cands[1]["score"] if len(cands) > 1 else 0.0
            if top >= RESOLVE_THRESHOLD and (top - second) >= AMBIGUITY_GAP:
                decision = "resolved"
            elif top >= RESOLVE_THRESHOLD:
                decision = "ambiguous"
        return {"reference": reference, "normalised": norm, "decision": decision, "candidates": cands,
                "paths": paths, "threshold": RESOLVE_THRESHOLD,
                "latency_ms": round((time.time() - t0) * 1000, 1)}

    def _jev(self, ref: str, c: dict) -> tuple[float, str]:
        # record_B carries the party's display name AND the name variant the index actually matched
        # (a trading/former name), so an alias hit is judged on the alias, not only the legal name
        b = {k: c[k] for k in ("name", "state", "postcode", "entity_type", "status") if c.get(k)}
        matched = (c.get("evidence") or {}).get("matched_name")
        if matched and N.normalise(matched) != N.normalise(c.get("name") or ""):
            b["also_known_as"] = matched
        state = {"record_A": {"name": ref}, "record_B": b}
        try:
            a = llm.jev_decide(state, JEV_MATCH_Q, tag="resolve:lookup:jev", retries=2)["answers"]
            return float(a["same_party"]["noul"]), a["relationship"]["choice"]
        except Exception as e:  # noqa: BLE001
            return 0.0, f"error:{str(e)[:40]}"

    # ---------------------------------------------------------------- entity
    def entity(self, key: str, cap: int = CAP) -> dict | None:
        q = """MATCH (p:Party {key: $key})
            OPTIONAL MATCH (p)-[k:KNOWN_AS]->(n:Name)
            WITH p, collect(DISTINCT {name: n.text, kind: k.kind, source: k.source_id, valid_from: k.valid_from, valid_to: k.valid_to}) AS names
            OPTIONAL MATCH (s:SourceRecord)-[r:RESOLVED_TO]->(p)
            WITH p, names, collect(DISTINCT {record_key: s.record_key, source: s.source_id, match_type: r.match_type, confidence: r.confidence, observed_at: s.observed_at, licence: s.licence}) AS records
            OPTIONAL MATCH (p)-[:HOLDS]->(l:Licence)
            WITH p, names, records, collect(DISTINCT {licence_id: l.licence_id, type: l.licence_type, status: l.status, start: l.start_date, end: l.end_date, n_authorisations: size(coalesce(l.authorisations, []))}) AS licences
            OPTIONAL MATCH (p)-[so:SUBJECT_OF]->(b:Ban)
            WITH p, names, records, licences, collect(DISTINCT {ban_id: b.ban_id, type: b.ban_type, start: b.start_date, end: b.end_date, match_type: so.match_type, confidence: so.confidence}) AS bans
            OPTIONAL MATCH (owner:Party)-[o:OWNS]->(p)
            WITH p, names, records, licences, bans, collect(DISTINCT {key: owner.key, name: owner.display_name, kind: o.kind, percent: o.percent, valid_to: o.valid_to}) AS owners
            OPTIONAL MATCH (p)-[o2:OWNS]->(sub:Party)
            WITH p, names, records, licences, bans, owners, collect(DISTINCT {key: sub.key, name: sub.display_name, kind: o2.kind, percent: o2.percent, valid_to: o2.valid_to}) AS subsidiaries
            OPTIONAL MATCH (p)-[a:AFFILIATED_WITH]-(other:Party)
            RETURN p {.*} AS party, names, records, licences, bans, owners, subsidiaries,
                   collect(DISTINCT {key: other.key, name: other.display_name, role: a.role, valid_to: a.valid_to}) AS affiliations"""
        rows = self._run(q, key=key)
        if not rows:
            return None
        r = rows[0]
        out = {"party": r["party"], "query": q}
        for section in ("names", "records", "licences", "bans", "owners", "subsidiaries", "affiliations"):
            items = [x for x in r[section] if any(v is not None for v in x.values())]
            items.sort(key=lambda x: str(x.get("valid_from") or x.get("start") or x.get("observed_at") or ""), reverse=True)
            out[section] = {"items": items[:cap], "total": len(items), "dropped": max(0, len(items) - cap),
                            "drop_rule": "most recent first" if len(items) > cap else None}
        return out

    # ---------------------------------------------------------------- traversals
    def ultimate_parent(self, key: str, max_depth: int = MAX_DEPTH, as_of: str | None = None) -> dict:
        """Climb OWNS edges one hop at a time (so cycles are detected by key, not by Cypher).
        Only relationships current at `as_of` (default today) are followed: valid_to null or later
        than as_of. Where a child has several current owners, ONE is followed, chosen by the stated
        rule (an asserted `ultimately_owned_by` edge first, then highest percent); the others are
        listed in `other_owners` so the choice is visible, not silent."""
        t0 = time.time()
        as_of = as_of or datetime.now(timezone.utc).date().isoformat()
        q = ("MATCH (owner:Party)-[o:OWNS]->(c:Party {key: $key}) "
             "WHERE o.valid_to IS NULL OR toString(o.valid_to) > $as_of "
             "RETURN owner.key AS key, owner.display_name AS name, o.kind AS kind, o.percent AS percent "
             "ORDER BY CASE o.kind WHEN 'ultimately_owned_by' THEN 0 ELSE 1 END, o.percent DESC")
        chain, seen, terminated_by, current = [], {key}, "root", key
        for _ in range(max_depth):
            owners = self._run(q, key=current, as_of=as_of)
            if not owners:
                terminated_by = "root"
                break
            nxt = owners[0]
            if nxt["key"] in seen:
                terminated_by = "cycle"
                chain.append({**nxt, "note": "cycle: already visited"})
                break
            chain.append(nxt)
            seen.add(nxt["key"])
            current = nxt["key"]
            if len(owners) > 1:
                chain[-1]["other_owners"] = [o["key"] for o in owners[1:]]
        else:
            terminated_by = "max_depth"
        return {"start": key, "chain": chain, "ultimate_parent": chain[-1]["key"] if chain and terminated_by == "root" else None,
                "terminated_by": terminated_by, "depth": len(chain), "query": q, "as_of": as_of,
                "selection_rule": "asserted ultimately_owned_by edge first, then highest percent; alternatives in other_owners",
                "chain_kind": "asserted_ultimate_parent" if any(c.get("kind") == "ultimately_owned_by" for c in chain) else "direct_parent_hops",
                "latency_ms": round((time.time() - t0) * 1000, 1)}

    def within_hops(self, hops: int = 2, of_key: str | None = None, limit: int = 100, current_only: bool = True,
                    as_of: str | None = None) -> dict:
        """Parties within `hops` of any Ban (or of a given party), over ownership/affiliation edges.
        `current_only` (default) walks only edges and bans still in force at `as_of`: an ownership
        that ended, or a ban whose end_date has passed, is not a current neighbourhood. Pass
        current_only=False for the historical view. The result says which view it is and whether
        the row cap cut it."""
        t0 = time.time()
        hops = max(1, min(hops, 4))
        as_of = as_of or datetime.now(timezone.utc).date().isoformat()
        edge_ok = "all(e IN relationships(path) WHERE e.valid_to IS NULL OR toString(e.valid_to) > $as_of)" if current_only else "true"
        if of_key:
            q = (f"MATCH path = (start:Party {{key: $key}})-[:{TRAVERSAL_RELS}*1..{hops}]-(p:Party) "
                 f"WHERE p.key <> start.key AND {edge_ok} "
                 "RETURN DISTINCT p.key AS key, p.display_name AS name, p.entity_type AS entity_type, "
                 "p.state AS state, min(length(path)) AS hops ORDER BY hops LIMIT $limit")
            rows = self._run(q, key=of_key, limit=limit, as_of=as_of)
        else:
            ban_ok = "(b.end_date IS NULL OR toString(b.end_date) >= $as_of)" if current_only else "true"
            q = (f"MATCH (b:Ban)<-[:SUBJECT_OF]-(banned:Party) WHERE {ban_ok} "
                 f"OPTIONAL MATCH path = (banned)-[:{TRAVERSAL_RELS}*1..{hops}]-(p:Party) "
                 f"WITH banned, b, p, path WHERE p IS NOT NULL AND p.key <> banned.key AND {edge_ok} "
                 "RETURN DISTINCT p.key AS key, p.display_name AS name, p.entity_type AS entity_type, p.state AS state, "
                 "banned.display_name AS via_banned_party, b.ban_type AS ban_type, b.end_date AS ban_end, length(path) AS hops "
                 "ORDER BY hops LIMIT $limit")
            rows = self._run(q, limit=limit, as_of=as_of)
        return {"hops": hops, "of_key": of_key, "results": rows, "count": len(rows), "capped": len(rows) >= limit,
                "view": "current" if current_only else "historical", "as_of": as_of, "query": q,
                "coverage_note": "neighbourhood over sources in this graph only; absence here is not absence in the world",
                "latency_ms": round((time.time() - t0) * 1000, 1)}

    def read_cypher(self, query: str, params: dict | None = None, row_cap: int = 200, timeout_s: int = CYPHER_TIMEOUT_S) -> dict:
        """Agent-written Cypher, read-only. Writes are refused by pattern AND by using a read transaction,
        and the query runs under a server-side transaction timeout. Neo4j Community has no per-user
        read-only role, so these are the boundary; a read replica would be the production one."""
        if _FORBIDDEN.search(query):
            return {"error": "refused: only read queries are allowed", "query": query}
        t0 = time.time()
        with self.driver.session(default_access_mode="READ") as s:
            try:
                res = s.run(Query(query, timeout=timeout_s), **(params or {}))
                rows = []
                for r in res:
                    rows.append(r.data())
                    if len(rows) >= row_cap:
                        break
                rows = json.loads(json.dumps(rows, default=str))
            except Exception as e:  # noqa: BLE001
                return {"error": f"{type(e).__name__}: {str(e)[:300]}", "query": query}
        return {"rows": rows, "count": len(rows), "capped": len(rows) >= row_cap, "query": query,
                "latency_ms": round((time.time() - t0) * 1000, 1)}

    def schema_summary(self) -> dict:
        counts = self._run("MATCH (n) UNWIND labels(n) AS l RETURN l AS label, count(*) AS n ORDER BY n DESC")
        rels = self._run("MATCH ()-[r]->() RETURN type(r) AS type, count(*) AS n ORDER BY n DESC")
        return {"node_labels": counts, "relationship_types": rels}

    # ---------------------------------------------------------------- projections
    PROJECTION_BASES = {
        "organisation": "SELECT * FROM v_party WHERE party_type = 'organisation'",
        "party": "SELECT * FROM v_party",
        "licence": "SELECT * FROM v_licence",
        "ban": "SELECT * FROM v_ban",
    }

    # unique ordering tail per base: makes ORDER BY total, so the same spec yields the same row order
    TIE_BREAK = {"organisation": ["party_key"], "party": ["party_key"],
                 "licence": ["party_key", "licence_id", "record_key"], "ban": ["party_key", "record_key"]}
    FILTER_OPS = ("=", "!=", ">", "<", ">=", "<=", "contains", "in", "is_null", "not_null", "within_days")

    def projection_columns(self, base: str) -> list[str]:
        return [d[0] for d in self.con.execute(f"SELECT * FROM ({self.PROJECTION_BASES[base]}) LIMIT 0").description]

    def validate_projection(self, spec: dict) -> list[str]:
        """Every reason a spec cannot run as written. Empty list = executable exactly as given.
        Nothing is dropped or repaired here: a spec that names a column that does not exist is rejected,
        not silently broadened."""
        problems = []
        base = spec.get("base", "organisation")
        if base not in self.PROJECTION_BASES:
            return [f"unknown base {base!r}; one of {list(self.PROJECTION_BASES)}"]
        available = self.projection_columns(base)
        bad = [c for c in (spec.get("columns") or []) if c not in available]
        if bad:
            problems.append(f"columns not on {base}: {bad}")
        if not (spec.get("columns") or []):
            problems.append("no columns requested")
        for f in spec.get("filters") or []:
            c, op, v = f.get("column"), (f.get("op") or "=").lower(), f.get("value")
            if c not in available:
                problems.append(f"filter column not on {base}: {c!r}")
            if op not in self.FILTER_OPS:
                problems.append(f"unknown filter op {op!r}")
            elif op == "within_days":
                try:
                    if int(v) <= 0:
                        problems.append(f"within_days needs a positive day count, got {v!r}")
                except (TypeError, ValueError):
                    problems.append(f"within_days needs an integer day count, got {v!r}")
            elif op == "in" and not isinstance(v, list):
                problems.append(f"'in' filter on {c!r} needs a list of values")
            elif op in ("is_null", "not_null") and v not in (None, ""):
                problems.append(f"{op} on {c!r} takes no value")
            elif op not in ("is_null", "not_null", "in") and v is None:
                problems.append(f"filter {c!r} {op} has no value")
        if spec.get("order_by") and spec["order_by"] not in available:
            problems.append(f"order_by column not on {base}: {spec['order_by']!r}")
        lim = spec.get("limit")
        if lim is not None and not (isinstance(lim, int) and 1 <= lim <= EXPORT_MAX_ROWS):
            problems.append(f"limit must be 1..{EXPORT_MAX_ROWS}, got {lim!r}")
        gf = spec.get("graph_filter")
        if gf:
            if gf.get("kind") not in ("within_hops_of_ban", "within_hops_of_key", "has_owner", "has_subsidiary"):
                problems.append(f"unknown graph_filter kind {gf.get('kind')!r}")
            if gf.get("kind") == "within_hops_of_key" and not gf.get("key"):
                problems.append("within_hops_of_key needs a key")
        return problems

    def projection(self, spec: dict, preview: bool = False, out_dir: Path = OUTPUTS / "projections") -> dict:
        """spec = {name, base, columns, filters:[{column, op, value}], graph_filter: {kind, hops, key}|null,
        order_by, limit, as_of}. Deterministic: same spec + same data generation => same rows, same order.
        Returns matched_count (rows satisfying the spec), exported_count (rows actually written or
        previewed) and truncated; the two differ whenever `limit` cuts the result."""
        t0 = time.time()
        problems = self.validate_projection(spec)
        if problems:
            return {"error": "; ".join(problems), "problems": problems}
        base = spec.get("base", "organisation")
        cols = list(spec["columns"])
        # relative-date filters are evaluated against a pinned date so a re-run reproduces the table
        spec = dict(spec)
        spec["as_of"] = spec.get("as_of") or datetime.now(timezone.utc).date().isoformat()
        where, params = [], []
        for f in spec.get("filters") or []:
            c, op, v = f.get("column"), (f.get("op") or "=").lower(), f.get("value")
            if op in ("=", "!=", ">", "<", ">=", "<="):
                where.append(f'"{c}" {op} ?'); params.append(v)
            elif op == "contains":
                where.append(f'upper(CAST("{c}" AS VARCHAR)) LIKE ?'); params.append(f"%{str(v).upper()}%")
            elif op == "in":
                where.append(f'"{c}" IN ({",".join("?" * len(v))})'); params += v
            elif op == "is_null":
                where.append(f'"{c}" IS NULL')
            elif op == "not_null":
                where.append(f'"{c}" IS NOT NULL')
            elif op == "within_days":  # date column within the N days before as_of
                where.append(f'TRY_CAST("{c}" AS DATE) >= CAST(? AS DATE) - INTERVAL (?) DAY')
                params += [spec["as_of"], int(v)]
        gf = spec.get("graph_filter")
        graph_note = None
        if gf:
            keys = self._graph_keys(gf)
            self.con.execute("CREATE OR REPLACE TEMP TABLE gf_keys AS SELECT * FROM (VALUES " +
                             (",".join("(?)" for _ in keys) if keys else "(NULL)") + ") t(key)", keys or [])
            where.append('"party_key" IN (SELECT key FROM gf_keys)')
            graph_note = f"{gf.get('kind')} -> {len(keys)} keys"
        sql = f'SELECT {", ".join(chr(34) + c + chr(34) for c in cols)} FROM ({self.PROJECTION_BASES[base]}) b'
        if where:
            sql += " WHERE " + " AND ".join(where)
        order = [spec.get("order_by") or cols[0]]
        order += [t for t in self.TIE_BREAK[base] if t not in order]
        sql += " ORDER BY " + ", ".join(f'"{o}"' for o in order)
        matched = self.con.execute(f"SELECT count(*) FROM ({sql})", params).fetchone()[0]
        export_limit = int(spec.get("limit") or 10000)
        lim = 20 if preview else export_limit
        rows = self.con.execute(sql + f" LIMIT {lim}", params).fetchall()
        exported = min(matched, lim)
        result = {"spec": spec, "sql": sql, "graph_filter": graph_note, "columns": cols,
                  "matched_count": matched, "exported_count": exported, "export_limit": export_limit,
                  "truncated": matched > (export_limit if not preview else lim),
                  "preview_rows": lim if preview else None,
                  "rows": [dict(zip(cols, r)) for r in rows] if preview else None,
                  "generation": self.generation(),
                  "latency_ms": round((time.time() - t0) * 1000, 1)}
        if not preview:
            out_dir.mkdir(parents=True, exist_ok=True)
            name = re.sub(r"[^a-z0-9]+", "-", (spec.get("name") or "projection").lower()).strip("-")
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            csv_path = out_dir / f"{name}-{stamp}.csv"
            pq_path = out_dir / f"{name}-{stamp}.parquet"
            self.con.execute(f"COPY ({sql} LIMIT {lim}) TO '{csv_path}' (HEADER)", params)
            self.con.execute(f"COPY ({sql} LIMIT {lim}) TO '{pq_path}' (FORMAT PARQUET)", params)
            spec_path = out_dir / f"{name}-{stamp}.spec.json"
            content_hash = hashlib.sha1(csv_path.read_bytes()).hexdigest()[:12]
            # Everything needed to say whether a re-run *should* produce the same file: the executable
            # spec (with as_of pinned), the SQL, the data generation and the matcher version.
            spec_path.write_text(json.dumps({"spec": spec, "sql": sql, "columns": cols,
                                             "matched_count": matched, "exported_count": exported,
                                             "truncated": matched > export_limit, "content_sha1": content_hash,
                                             "created_at": stamp, "generation": self.generation(),
                                             "spec_version": "projection-0.2", "matcher_version": "resolver-0.1.0"},
                                            indent=2, default=str))
            result.update({"csv": str(csv_path), "parquet": str(pq_path), "spec_file": str(spec_path),
                           "content_sha1": content_hash})
        return result

    def _graph_keys(self, gf: dict) -> list[str] | None:
        kind = gf.get("kind")
        if kind == "within_hops_of_ban":
            return [r["key"] for r in self.within_hops(int(gf.get("hops", 2)), limit=100000)["results"]]
        if kind == "within_hops_of_key":
            return [r["key"] for r in self.within_hops(int(gf.get("hops", 1)), of_key=gf.get("key"), limit=100000)["results"]]
        if kind == "has_owner":
            return [r["key"] for r in self._run("MATCH (:Party)-[:OWNS]->(p:Party) RETURN DISTINCT p.key AS key")]
        if kind == "has_subsidiary":
            return [r["key"] for r in self._run("MATCH (p:Party)-[:OWNS]->(:Party) RETURN DISTINCT p.key AS key")]
        return None


def _cand(r: dict, score: float, match_type: str, evidence: dict, path: str) -> dict:
    return {"key": r["key"], "name": r["name"], "state": r.get("state"), "postcode": r.get("postcode"),
            "entity_type": r.get("entity_type"), "status": r.get("status"), "sources": r.get("sources"),
            "score": round(score, 3), "match_type": match_type, "evidence": evidence, "path": path}


def _jw(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return JaroWinkler.similarity(a, b)
