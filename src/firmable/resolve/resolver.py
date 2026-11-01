"""Entity resolution over DuckDB `record_parties`: two named paths, one arbitration rule.

EXACT path   checksum-valid identifier equality (ABN, ACN, LEI, GLEIF registeredAs) plus the
             ABR bridge (an ABR row carrying both ABN and ACN links the two identifier spaces).
             Deterministic, no model, confidence 0.99 (not 1.0: identifiers are mistyped in
             sources at a small measured rate).
SEMANTIC path blocking on normalised-name tokens (+ state/postcode) -> string similarity ->
             the Jev decision model gives P(same party) from the two records' attributes ->
             link above a per-sensitivity threshold, else abstain with the best candidate.
ARBITRATION  an identifier conflict (both records carry a valid identifier of the same kind
             and they differ) overrides any name similarity: abstain, reason identifier_conflict.
             Person-type records are never linked by name alone across sources.

Outputs: tables links, abstentions, parties, record_cluster in DuckDB; outputs/links.jsonl and
outputs/abstentions.jsonl. Every link carries matcher_version + threshold so a later
recalibration can select exactly the links a new threshold would flip (see WRITEUP Q4).
"""
from __future__ import annotations

import json
import time
from collections import defaultdict
from datetime import datetime, timezone

import duckdb
from rapidfuzz import process
from rapidfuzz.distance import JaroWinkler

from .. import llm
from ..ontology import abn_valid, acn_valid
from pathlib import Path

from ..paths import CACHE, OUTPUTS
from . import normalise as N

MATCHER_VERSION = "resolver-0.1.0"
# Thresholds on Jev's P(same party). Sensitive = sources whose wrong link publishes an accusation.
THRESHOLDS = {"default": 0.85, "sensitive": 0.95, "person": 1.01}  # person: never by name
SENSITIVE_SOURCES = {"data.gov.au:asic-banned-disqualified-org"}
MAX_CANDIDATES = 8          # per record, after string-similarity ranking
MAX_BLOCK = 500             # a token block larger than this is a hub ("CONSTRUCTIONS") and is skipped
MAX_SPECIFIC_BLOCK = 3000   # prefix+state / postcode+prefix blocks: broader, so a higher cap
MAX_SEEN = 300              # stop adding token blocks once this many candidates are in hand
JEV_TOP_K = 2               # Jev is asked only about the top-k candidates by string similarity
JEV_MIN_SIM = 0.85          # ... and only when similarity is at least this
JEV_WORKERS = 12
JEV_CIRCUIT_BREAKER = 25    # consecutive scorer failures before the run stops asking and marks the rest
MIN_SIMILARITY = 0.80       # jaro-winkler floor to be a candidate at all
EXACT_CONF = 0.99

JEV_MATCH_Q = {
    "same_party": {
        "type": "noul",
        "instructions": "Do these two records, from two different registers, refer to the SAME "
                        "legal entity (not merely similar names, not parent/subsidiary, not a "
                        "person vs their company)?",
        "criteria": {
            "true": "Names agree after allowing for legal-form words, abbreviations, punctuation "
                    "and typos, AND nothing contradicts identity (location, entity type, dates).",
            "false": "Different entities with similar names (e.g. 'Commonwealth Bank of Australia' "
                     "vs 'Commonwealth Superannuation Corporation'), a franchise or branch, a "
                     "parent vs subsidiary, a person vs a company, or contradictory identifiers.",
        },
    },
    "relationship": {
        "type": "choice",
        "instructions": "If not the same entity, what is the most likely relationship?",
        "criteria": {
            "same": "The same entity.",
            "related": "Parent/subsidiary, trustee/trust, person/their company, franchise.",
            "unrelated": "Coincidentally similar names.",
        },
    },
}


class PairCache:
    """Append-only JSONL cache of model pair scores (data/cache/jev_pairs.jsonl). Thread-safe."""

    def __init__(self, path: Path):
        import threading
        self.path, self.lock, self.mem = path, threading.Lock(), {}
        if path.exists():
            for line in path.read_text().splitlines():
                try:
                    r = json.loads(line)
                    self.mem[r["k"]] = (r["p"], r["rel"])
                except (ValueError, KeyError):
                    continue
        path.parent.mkdir(parents=True, exist_ok=True)

    def get(self, key: str):
        return self.mem.get(key)

    def put(self, key: str, value: tuple[float, str]) -> None:
        with self.lock:
            self.mem[key] = value
            with self.path.open("a") as f:
                f.write(json.dumps({"k": key, "p": value[0], "rel": value[1]}) + "\n")


PAIR_CACHE = PairCache(CACHE / "jev_pairs.jsonl")


class Resolver:
    def __init__(self, con: duckdb.DuckDBPyConnection, use_jev: bool = True):
        self.con = con
        self.use_jev = use_jev
        self.links: list[dict] = []
        self.abstentions: list[dict] = []
        self.key_of: dict[str, str] = {}          # record_key -> canonical key
        self.party: dict[str, dict] = {}          # canonical key -> merged attributes
        self.jev_calls = 0
        self.consecutive_errors = 0
        self.scorer_down = False
        self.skipped_blocks = 0

    # ---------- load ------------------------------------------------------------------
    def records(self) -> list[dict]:
        cur = self.con.execute("""SELECT record_key, source_id, source_record_id, name, entity_type,
            status, abn, acn, lei, state, postcode, locality, trading_names, person_role
            FROM record_parties WHERE name IS NOT NULL OR abn IS NOT NULL OR acn IS NOT NULL OR lei IS NOT NULL""")
        cols = [d[0] for d in cur.description]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]
        for r in rows:
            r["abn"] = r["abn"] if r["abn"] and abn_valid(r["abn"]) else None
            r["acn"] = r["acn"] if r["acn"] and acn_valid(r["acn"]) else None
            r["lei"] = r["lei"].strip().upper() if r["lei"] and len(r["lei"].strip()) == 20 else None
            r["name_norm"] = N.normalise(r["name"] or "")
            r["trading_norms"] = [N.normalise(t) for t in (r["trading_names"] or []) if t]
            r["legal_form"] = N.legal_form(r["name"] or "")
            r["is_person"] = (r["entity_type"] in ("sole_trader",) and not r["abn"]) or bool(r["person_role"])
        return rows

    # ---------- exact path --------------------------------------------------------------
    def exact(self, rows: list[dict]) -> None:
        """Union-find over identifier equality. ABR rows bridge ABN<->ACN."""
        parent: dict[str, str] = {}

        def find(x):
            while parent.setdefault(x, x) != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        def union(a, b):
            ra, rb = find(a), find(b)
            if ra != rb:
                parent[rb] = ra

        acn_abns: dict[str, set] = defaultdict(set)
        for r in rows:
            ids = [f"abn:{r['abn']}" if r["abn"] else None, f"acn:{r['acn']}" if r["acn"] else None,
                   f"lei:{r['lei']}" if r["lei"] else None]
            ids = [i for i in ids if i]
            if r["abn"] and r["acn"]:
                acn_abns[r["acn"]].add(r["abn"])
            for i in ids:
                union(r["record_key"], i)
        # invariant: one ACN under two different ABNs -> do not bridge through that ACN
        conflicted_acns = {acn for acn, abns in acn_abns.items() if len(abns) > 1}
        if conflicted_acns:
            parent.clear()
            for r in rows:
                ids = [f"abn:{r['abn']}" if r["abn"] else None, f"lei:{r['lei']}" if r["lei"] else None]
                if r["acn"] and r["acn"] not in conflicted_acns:
                    ids.append(f"acn:{r['acn']}")
                for i in ids:
                    if i:
                        union(r["record_key"], i)
        # canonical key per component: abn > acn > lei
        comp: dict[str, list] = defaultdict(list)
        for r in rows:
            comp[find(r["record_key"])].append(r)
        for root, members in comp.items():
            ids = {k for r in members for k in (
                f"abn:{r['abn']}" if r["abn"] else None, f"acn:{r['acn']}" if r["acn"] else None,
                f"lei:{r['lei']}" if r["lei"] else None) if k}
            key = next((k for pfx in ("abn:", "acn:", "lei:") for k in sorted(ids) if k.startswith(pfx)), None)
            if key is None:
                continue  # no identifier: left for the semantic path / singleton
            for r in members:
                self.key_of[r["record_key"]] = key
                own = {k for k in (f"abn:{r['abn']}" if r["abn"] else None, f"acn:{r['acn']}" if r["acn"] else None,
                                   f"lei:{r['lei']}" if r["lei"] else None) if k}
                if key in own:
                    mt = "exact_" + key.split(":")[0]
                else:
                    mt = "bridge_abr_acn"
                if r["acn"] and r["acn"] in conflicted_acns and not r["abn"]:
                    continue
                self.links.append(self._link(r, key, mt, EXACT_CONF, {
                    "identifiers": sorted(own), "component_identifiers": sorted(ids),
                    "checksum": "valid"}))
            self._merge(key, members)
        for r in rows:
            if r["acn"] and r["acn"] in conflicted_acns and not r["abn"]:
                self.abstentions.append(self._abstain(r, None, None, "identifier_conflict",
                    {"acn": r["acn"], "abns_claiming_it": sorted(acn_abns[r["acn"]])}))

    # ---------- semantic path -----------------------------------------------------------
    def semantic(self, rows: list[dict]) -> None:
        """Records still without a key: block, score, ask Jev, decide."""
        resolved = [r for r in rows if r["record_key"] in self.key_of]
        pending = [r for r in rows if r["record_key"] not in self.key_of
                   and all(a["record_key"] != r["record_key"] for a in self.abstentions)]
        index: dict[str, list] = defaultdict(list)
        for r in resolved:
            for k in N.blocking_keys(r["name_norm"], r["state"], r["postcode"]):
                index[k].append(r)
            for tn in r["trading_norms"]:
                for k in N.blocking_keys(tn, r["state"], r["postcode"]):
                    index[k].append(r)
        self.block_stats = {"pending": len(pending), "indexed": len(resolved),
                            "blocks": len(index), "largest_block": max((len(v) for v in index.values()), default=0)}
        from concurrent.futures import ThreadPoolExecutor
        work = []
        for r in pending:
            if r["is_person"]:
                self.abstentions.append(self._abstain(r, None, None, "person_name_only",
                    {"policy": "persons are never linked by name alone"}))
                continue
            if not r["name_norm"] or len(r["name_norm"]) < 3:
                self.abstentions.append(self._abstain(r, None, None, "no_usable_name", {}))
                continue
            cands = self._candidates(r, index)
            if not cands:
                self.abstentions.append(self._abstain(r, None, None, "no_candidate_in_block",
                    {"blocking_keys": sorted(N.blocking_keys(r["name_norm"], r["state"], r["postcode"]))[:6]}))
                continue
            work.append((r, cands))
        self.block_stats["records_with_candidates"] = len(work)
        self.block_stats["skipped_oversize_blocks"] = self.skipped_blocks

        def decide(item):
            r, cands = item
            return r, self._decide(r, cands)

        with ThreadPoolExecutor(JEV_WORKERS if self.use_jev else 1) as ex:
            decided = list(ex.map(decide, work))
        for r, (best, score, evidence) in decided:
            thr = self._threshold(r)
            if best and score >= thr:
                key = self.key_of[best["record_key"]]
                mt = "name_exact_norm" if evidence.get("exact_normalised") else "name_semantic"
                self.key_of[r["record_key"]] = key
                self.links.append(self._link(r, key, mt, score, evidence, thr))
                self._merge(key, [r])
            else:
                reason = "below_threshold" if best else "no_candidate"
                if evidence.get("identifier_conflict"):
                    reason = "identifier_conflict"
                elif str(evidence.get("jev_relationship", "")).startswith("error:"):
                    reason = "scorer_unavailable"  # not a judgement: re-run when the scorer is back
                self.abstentions.append(self._abstain(
                    r, self.key_of.get(best["record_key"]) if best else None, score, reason,
                    {**evidence, "threshold": thr}))

    def _candidates(self, r: dict, index: dict) -> list[tuple[dict, float]]:
        """Specific keys (postcode+prefix, prefix+state) first; token blocks only while the
        candidate set is small and the block itself is not a hub (> MAX_BLOCK)."""
        seen: dict[str, dict] = {}
        keys = N.blocking_keys(r["name_norm"], r["state"], r["postcode"])
        for k in sorted(keys, key=lambda k: 0 if k[0] in "pf" else 1):
            block = index.get(k, [])
            cap = MAX_SPECIFIC_BLOCK if k[0] in "pf" else MAX_BLOCK
            if len(block) > cap or (k.startswith("t:") and len(seen) > MAX_SEEN):
                self.skipped_blocks += 1
                continue
            for c in block:
                seen.setdefault(c["record_key"], c)
        if not seen:
            return []
        # batch similarity in C++ (rapidfuzz) over the candidate names and their trading names
        cands = list(seen.values())
        choices = [c["name_norm"] for c in cands]
        sims = process.cdist([r["name_norm"]], choices, scorer=JaroWinkler.similarity, workers=1)[0]
        scored = []
        for c, sim in zip(cands, sims):
            if c.get("trading_names"):
                sim = max(sim, max((_jw(r["name_norm"], tn) for tn in c["trading_norms"]), default=0.0))
            if sim >= MIN_SIMILARITY:
                scored.append((c, float(sim)))
        scored.sort(key=lambda x: -x[1])
        return scored[:MAX_CANDIDATES]

    def _decide(self, r: dict, cands: list[tuple[dict, float]]):
        best, best_p, best_ev = None, 0.0, {}
        for rank, (c, sim) in enumerate(cands):
            ev = {"candidate_record": c["record_key"], "candidate_name": c["name"],
                  "string_similarity": round(sim, 3),
                  "exact_normalised": r["name_norm"] == c["name_norm"],
                  "state_agree": (r["state"] == c["state"]) if r["state"] and c["state"] else None,
                  "postcode_agree": (r["postcode"] == c["postcode"]) if r["postcode"] and c["postcode"] else None,
                  "legal_form": [r["legal_form"], c["legal_form"]]}
            # arbitration: a conflicting identifier of the same kind beats any name evidence
            if (r["abn"] and c["abn"] and r["abn"] != c["abn"]) or (r["acn"] and c["acn"] and r["acn"] != c["acn"]):
                ev["identifier_conflict"] = True
                p = 0.0
            elif ev["exact_normalised"] and (ev["postcode_agree"] or ev["state_agree"]) and ev["state_agree"] is not False:
                p = 0.90  # deterministic: identical normalised name in the same place needs no model
                ev["rule"] = "exact_normalised_same_place"
            elif self.use_jev and sim >= JEV_MIN_SIM and (rank == 0 or (rank < JEV_TOP_K and cands[0][1] - sim <= 0.02)):
                # the best candidate always; the runner-up only when it is nearly tied
                p, rel = self._jev(r, c)
                ev["jev_p_same"] = p
                ev["jev_relationship"] = rel
            else:  # not asked: string similarity alone is never enough to link
                p = round(sim * 0.8, 3)
                ev["rule"] = "similarity_only_not_linkable"
            if p > best_p:
                best, best_p, best_ev = c, p, ev
        return best, round(best_p, 3), best_ev

    def _jev(self, a: dict, b: dict) -> tuple[float, str]:
        """P(same party) for a candidate pair. Scores are cached on disk by (record, candidate,
        model): a pair is never scored twice across runs, and a future recalibration or model
        swap can start from exactly the pairs that were ever compared (WRITEUP §4)."""
        key = f"{a['record_key']}|{b['record_key']}|{llm.JEV}"
        hit = PAIR_CACHE.get(key)
        if hit:
            return hit
        if self.scorer_down:
            return 0.0, "error:scorer_unavailable"
        state = {"record_A": _public(a), "record_B": _public(b)}
        try:
            ans = llm.jev_decide(state, JEV_MATCH_Q, tag="resolve:jev", retries=2)["answers"]
            self.jev_calls += 1
            self.consecutive_errors = 0
            res = (float(ans["same_party"]["noul"]), ans["relationship"]["choice"])
        except Exception as e:  # noqa: BLE001 - on failure, do not link; never cache an error
            self.consecutive_errors += 1
            if self.consecutive_errors >= JEV_CIRCUIT_BREAKER:
                self.scorer_down = True
            return 0.0, f"error:{str(e)[:60]}"
        PAIR_CACHE.put(key, res)
        return res

    def _threshold(self, r: dict) -> float:
        if r["source_id"] in SENSITIVE_SOURCES:
            return THRESHOLDS["sensitive"]
        return THRESHOLDS["default"]

    # ---------- bookkeeping -------------------------------------------------------------
    def _link(self, r, key, match_type, conf, evidence, thr=None) -> dict:
        return {"left_source": r["source_id"], "left_record_id": r["source_record_id"],
                "left_record_key": r["record_key"], "canonical_key": key, "match_type": match_type,
                "confidence": round(conf, 3), "threshold": thr, "evidence": evidence,
                "matcher_version": MATCHER_VERSION, "created_at": _now()}

    def _abstain(self, r, best_key, score, reason, evidence) -> dict:
        return {"source": r["source_id"], "record_id": r["source_record_id"], "record_key": r["record_key"],
                "name": r["name"], "best_candidate": best_key, "best_score": score, "reason": reason,
                "evidence": evidence, "matcher_version": MATCHER_VERSION, "created_at": _now()}

    def _merge(self, key: str, members: list[dict]) -> None:
        p = self.party.setdefault(key, {"key": key, "sources": [], "names": set(), "abn": None,
                                        "acn": None, "lei": None, "party_type": "organisation"})
        for r in members:
            p["sources"].append(r["source_id"])
            if r["name"]:
                p["names"].add(r["name"])
            for f in ("abn", "acn", "lei"):
                if r[f] and not p[f]:
                    p[f] = r[f]
            if r["is_person"]:
                p["party_type"] = "person"

    def singletons(self, rows: list[dict]) -> None:
        """Every record that is neither linked nor abstained becomes its own party.
        Within ONE source, name-only organisation records with the identical normalised name
        collapse into one party (a contracts register lists the same supplier on every contract):
        same publisher + same string is not the cross-source problem, and leaving them apart
        makes one Name node per supplier with thousands of edges. Persons never collapse."""
        linked = set(self.key_of)
        abst = {a["record_key"] for a in self.abstentions}
        same_source: dict[tuple, str] = {}
        for r in rows:
            if r["record_key"] in linked or r["record_key"] in abst:
                continue
            key = N.canonical_key(r["abn"], r["acn"], r["lei"])
            mt, ev = "singleton", {"note": "own identifier or no other record"}
            if key is None:
                grp = (r["source_id"], r["name_norm"]) if (r["name_norm"] and not r["is_person"]) else None
                if grp and grp in same_source:
                    key, mt = same_source[grp], "name_exact_norm_same_source"
                    ev = {"rule": "identical normalised name within one source", "first_record": key}
                else:
                    key = f"src:{r['record_key']}"
                    if grp:
                        same_source[grp] = key
            self.key_of[r["record_key"]] = key
            self.links.append(self._link(r, key, mt, 1.0 if mt == "singleton" else 0.9, ev))
            self._merge(key, [r])
        # abstained records still exist in the graph as parties (never merged ACROSS sources);
        # the same within-source collapse applies, so one unlinked supplier is one party
        by_key = {x["record_key"]: x for x in rows}
        for a in self.abstentions:
            r = by_key.get(a["record_key"])
            if r and r["record_key"] not in self.key_of:
                grp = (r["source_id"], r["name_norm"]) if (r["name_norm"] and not r["is_person"]) else None
                if grp and grp in same_source:
                    key, mt = same_source[grp], "name_exact_norm_same_source"
                else:
                    key, mt = f"src:{r['record_key']}", "singleton"
                    if grp:
                        same_source[grp] = key
                self.key_of[r["record_key"]] = key
                # the record still RESOLVES_TO its own (or its same-source) party, so the graph stays
                # navigable; the abstention row is the record of the refused CROSS-source link
                self.links.append(self._link(r, key, mt, 1.0 if mt == "singleton" else 0.9,
                                             {"note": "abstained from cross-source linking", "abstention_reason": a["reason"]}))
                self._merge(key, [r])

    # ---------- run ---------------------------------------------------------------------
    def run(self) -> dict:
        t0 = time.time()
        rows = self.records()
        self.exact(rows)
        t1 = time.time()
        self.semantic(rows)
        t2 = time.time()
        self.singletons(rows)
        t3 = time.time()
        self.persist()
        return {"records": len(rows), "links": len(self.links), "abstentions": len(self.abstentions),
                "parties": len(self.party), "jev_calls": self.jev_calls,
                "secs_exact": round(t1 - t0, 1), "secs_semantic": round(t2 - t1, 1),
                "secs_singletons": round(t3 - t2, 1), "secs_persist": round(time.time() - t3, 1),
                "blocking": getattr(self, "block_stats", {}), "scorer_down": self.scorer_down,
                "cached_pairs_used": len(PAIR_CACHE.mem),
                "match_types": _count(l["match_type"] for l in self.links),
                "abstain_reasons": _count(a["reason"] for a in self.abstentions)}

    def persist(self) -> None:
        con = self.con
        con.execute("CREATE OR REPLACE TABLE links AS SELECT * FROM (VALUES (NULL)) WHERE false")
        con.execute("""CREATE OR REPLACE TABLE links (left_source VARCHAR, left_record_id VARCHAR,
            left_record_key VARCHAR, canonical_key VARCHAR, match_type VARCHAR, confidence DOUBLE,
            threshold DOUBLE, evidence JSON, matcher_version VARCHAR, created_at VARCHAR)""")
        import pandas as pd
        links_df = pd.DataFrame([
            (l["left_source"], l["left_record_id"], l["left_record_key"], l["canonical_key"], l["match_type"],
             l["confidence"], l["threshold"], json.dumps(l["evidence"]), l["matcher_version"], l["created_at"])
            for l in self.links], columns=["left_source", "left_record_id", "left_record_key", "canonical_key",
                                          "match_type", "confidence", "threshold", "evidence", "matcher_version", "created_at"])
        con.register("links_df", links_df)
        con.execute("INSERT INTO links SELECT * FROM links_df")
        con.execute("""CREATE OR REPLACE TABLE abstentions (source VARCHAR, record_id VARCHAR, record_key VARCHAR,
            name VARCHAR, best_candidate VARCHAR, best_score DOUBLE, reason VARCHAR, evidence JSON,
            matcher_version VARCHAR, created_at VARCHAR)""")
        abst_df = pd.DataFrame([
            (a["source"], a["record_id"], a["record_key"], a["name"], a["best_candidate"], a["best_score"],
             a["reason"], json.dumps(a["evidence"]), a["matcher_version"], a["created_at"]) for a in self.abstentions],
            columns=["source", "record_id", "record_key", "name", "best_candidate", "best_score", "reason", "evidence",
                     "matcher_version", "created_at"])
        con.register("abst_df", abst_df)
        con.execute("INSERT INTO abstentions SELECT * FROM abst_df")
        con.execute("""CREATE OR REPLACE TABLE parties (key VARCHAR PRIMARY KEY, party_type VARCHAR,
            abn VARCHAR, acn VARCHAR, lei VARCHAR, n_sources INTEGER, sources VARCHAR[], names VARCHAR[])""")
        parties_df = pd.DataFrame([
            (p["key"], p["party_type"], p["abn"], p["acn"], p["lei"], len(set(p["sources"])),
             sorted(set(p["sources"])), sorted(p["names"])) for p in self.party.values()],
            columns=["key", "party_type", "abn", "acn", "lei", "n_sources", "sources", "names"])
        con.register("parties_df", parties_df)
        con.execute("INSERT INTO parties SELECT * FROM parties_df")
        con.execute("CREATE OR REPLACE TABLE record_cluster (record_key VARCHAR PRIMARY KEY, canonical_key VARCHAR)")
        cluster_df = pd.DataFrame(list(self.key_of.items()), columns=["record_key", "canonical_key"])
        con.register("cluster_df", cluster_df)
        con.execute("INSERT INTO record_cluster SELECT * FROM cluster_df")
        OUTPUTS.mkdir(exist_ok=True)
        with (OUTPUTS / "links.jsonl").open("w") as f:
            for l in self.links:
                f.write(json.dumps(l, ensure_ascii=False) + "\n")
        with (OUTPUTS / "abstentions.jsonl").open("w") as f:
            for a in self.abstentions:
                f.write(json.dumps(a, ensure_ascii=False) + "\n")


def _public(r: dict) -> dict:
    return {k: r.get(k) for k in ("source_id", "name", "entity_type", "status", "state", "postcode",
                                  "locality", "trading_names", "legal_form") if r.get(k)}


def _jw(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return JaroWinkler.similarity(a, b)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _count(it) -> dict:
    out: dict = defaultdict(int)
    for x in it:
        out[x] += 1
    return dict(sorted(out.items(), key=lambda kv: -kv[1]))
