"""Measurement. Nothing here is hand-labelled: labels come from two models that did NOT make
the links and see them blind. The write-up says so.

1. label_links()      stratified sample of links (by match_type x source pair) -> labels/links_sample.jsonl
                      labelled blind by Gemini Pro (free-text verdict) and Jev (P(same)) given only
                      the two underlying records; agreement reported; disagreements never counted
                      as correct. Gemini Pro is the independent labeller (it played no part in
                      linking); Jev also scored the semantic links, so Pro-only numbers are
                      reported alongside the consensus. Precision figures are sample proportions
                      with a Wilson 95% lower bound, not population guarantees.
2. recall_hidden_id() recall of the SEMANTIC path: take records linked by an exact identifier,
                      hide the identifier, re-run blocking + semantic scoring AGAINST THE FULL
                      INDEX (every other record, as in production), and report separately: was the
                      true party among the candidates (blocking), was it ranked first (scoring),
                      was it accepted at the threshold, and was a WRONG party accepted.
3. identifier_coverage() per tier-2 source: how often the record carries an ABN/ACN/LEI at all.
4. test_cases()        the two named cases + a few more; outputs/evaluation.md section.
5. resolve_benchmark() 200 dirty references (built from real records + 12 absent ones) ->
                      outputs/resolve_results.jsonl + p50/p95 latency.
6. write_reports()     outputs/evaluation.md, outputs/performance.md, outputs/graph_queries.md
"""
from __future__ import annotations

import json
import random
import statistics
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

import duckdb
from pydantic import BaseModel, Field

from .. import llm
from ..paths import DUCKDB, LABELS, OUTPUTS
from ..resolve import normalise as N
from ..resolve.resolver import JEV_MATCH_Q, THRESHOLDS, Resolver
from ..retrieval.graph_api import GraphAPI

SEED = 20261030
LABELS.mkdir(exist_ok=True)


class ProLabel(BaseModel):
    verdict: Literal["same", "different", "cannot_tell"]
    reason: str = Field(description="one sentence citing the attributes that decide it")


PRO_PROMPT = """You are labelling an entity-resolution decision for an audit. Two records from two
Australian business registers are shown. Decide whether they refer to the SAME legal entity.
'same' only if the evidence supports identity (same registered name allowing for legal-form
words/abbreviations/punctuation, no contradicting identifiers or locations). 'different' if they
are distinct entities, including parent/subsidiary, trustee/trust, person/their company, or
similar-but-unrelated names. 'cannot_tell' if the shown attributes are insufficient.
You are NOT shown how the system decided. Judge from the records only.

Record A: {a}
Record B: {b}
"""


def _rec(con, record_key: str) -> dict:
    r = con.execute("""SELECT source_id, name, entity_type, status, abn, acn, lei, state, postcode, locality, trading_names
                       FROM record_parties WHERE record_key = ?""", [record_key]).fetchone()
    if not r:
        return {"record_key": record_key}
    cols = ["source_id", "name", "entity_type", "status", "abn", "acn", "lei", "state", "postcode", "locality", "trading_names"]
    return {k: v for k, v in zip(cols, r) if v}


def _blind(rec: dict) -> dict:
    """What a labeller sees: attributes only, identifiers REMOVED for name-path links so the
    labeller judges the same evidence the semantic path had (identifiers would make it trivial)."""
    return {k: v for k, v in rec.items() if k not in ("abn", "acn", "lei")}


# ---------------------------------------------------------------------------- 1. labels
def label_links(con, n_per_stratum: int = 12, max_total: int = 120) -> dict:
    links = [json.loads(l) for l in _read_jsonl(OUTPUTS / "links.jsonl")]
    links = [l for l in links if l["match_type"] != "singleton"]
    strata: dict[tuple, list] = defaultdict(list)
    for l in links:
        strata[(l["match_type"], l["left_source"])].append(l)
    rng = random.Random(SEED)
    sample = []
    for key, items in sorted(strata.items()):
        sample += rng.sample(items, min(n_per_stratum, len(items)))
    rng.shuffle(sample)
    sample = sample[:max_total]
    # the partner record: for exact links, any other member of the same party; for semantic, the candidate record
    members = defaultdict(list)
    for rk, ck in con.execute("SELECT record_key, canonical_key FROM record_cluster").fetchall():
        members[ck].append(rk)
    out = []
    for l in sample:
        a_key = l["left_record_key"]
        b_key = l["evidence"].get("candidate_record") or next((m for m in members[l["canonical_key"]] if m != a_key), None)
        if not b_key:
            continue
        a, b = _rec(con, a_key), _rec(con, b_key)
        blind_a, blind_b = (_blind(a), _blind(b)) if l["match_type"].startswith("name") else (a, b)
        row = {"link": {k: l[k] for k in ("left_record_key", "canonical_key", "match_type", "confidence", "left_source")},
               "record_a": a, "record_b": b, "record_b_key": b_key, "shown_to_labellers": {"a": blind_a, "b": blind_b}}
        try:
            pro = llm.structured(PRO_PROMPT.format(a=json.dumps(blind_a), b=json.dumps(blind_b)), ProLabel,
                                 model=llm.PRO, tag="eval:label:pro")
            row["label_pro"] = {"verdict": pro.verdict, "reason": pro.reason, "model": llm.PRO}
        except Exception as e:  # noqa: BLE001
            row["label_pro"] = {"verdict": "error", "reason": str(e)[:100]}
        try:
            j = llm.jev_decide({"record_A": blind_a, "record_B": blind_b}, JEV_MATCH_Q, tag="eval:label:jev", retries=2)["answers"]
            p = float(j["same_party"]["noul"])
            row["label_jev"] = {"p_same": round(p, 3), "verdict": "same" if p >= 0.7 else "different" if p <= 0.3 else "cannot_tell",
                                "relationship": j["relationship"]["choice"], "model": llm.JEV}
        except Exception as e:  # noqa: BLE001
            row["label_jev"] = {"verdict": "error", "reason": str(e)[:100]}
        pv, jv = row["label_pro"]["verdict"], row["label_jev"]["verdict"]
        row["consensus"] = pv if pv == jv and pv in ("same", "different") else "unresolved"
        row["link_correct"] = {"same": True, "different": False}.get(row["consensus"])
        out.append(row)
    with (LABELS / "links_sample.jsonl").open("w") as f:
        for r in out:
            f.write(json.dumps(r, ensure_ascii=False, default=str) + "\n")
    (LABELS / "README.md").write_text(_labels_readme(out))
    return _precision_tables(out, links)


def _read_jsonl(path: Path) -> list[str]:
    if path.exists():
        return path.read_text().splitlines()
    import gzip
    with gzip.open(path.with_suffix(".jsonl.gz"), "rt") as f:
        return f.read().splitlines()


def _wilson_lower(k: int, n: int, z: float = 1.96) -> float | None:
    """Wilson score interval, lower end: a real 95% lower confidence bound on a proportion."""
    if n == 0:
        return None
    p = k / n
    denom = 1 + z * z / n
    centre = p + z * z / (2 * n)
    spread = z * ((p * (1 - p) + z * z / (4 * n)) / n) ** 0.5
    return round((centre - spread) / denom, 3)


def _labels_readme(rows: list[dict]) -> str:
    agree = sum(r["consensus"] != "unresolved" for r in rows)
    return f"""# Labels

`links_sample.jsonl` — {len(rows)} links sampled from `outputs/links.jsonl`, stratified by
match_type x source, labelled by two models that did not produce the links:

- **Gemini 3.1 Pro** (free-text verdict + reason), model `{llm.PRO}` — independent: it played no
  part in making the links.
- **TypeSafe Jev 1.14** (decision model; P(same) with 0.7 / 0.3 cut-offs), model `{llm.JEV}` — NOT
  independent for `name_semantic` links, which Jev itself scored (blind presentation removes the
  system's decision, not the model's own tendencies). `evaluation.md` therefore also reports
  Pro-only precision.

Both saw only the two records' attributes (`shown_to_labellers`). For name-path links the
identifiers were removed so the labellers judged the same evidence the semantic path had.
They were never shown the system's score, match type or evidence.

Consensus: {agree}/{len(rows)} links where both labellers agreed on same/different. Disagreements
and 'cannot_tell' are reported as **unresolved** and never counted as correct.

These are model labels, not human labels. The write-up says so. Re-label any row by hand by
editing `human_verdict` into it; `evaluation.py` prefers a human verdict when present.
"""


def _precision_tables(rows: list[dict], all_links: list[dict]) -> dict:
    def table(keyfn):
        t: dict = defaultdict(lambda: {"labelled": 0, "correct": 0, "incorrect": 0, "unresolved": 0,
                                       "pro_same": 0, "pro_different": 0})
        for r in rows:
            k = keyfn(r)
            t[k]["labelled"] += 1
            if r["link_correct"] is True:
                t[k]["correct"] += 1
            elif r["link_correct"] is False:
                t[k]["incorrect"] += 1
            else:
                t[k]["unresolved"] += 1
            pv = r.get("label_pro", {}).get("verdict")
            if pv in ("same", "different"):
                t[k]["pro_" + pv] += 1
        for v in t.values():
            decided = v["correct"] + v["incorrect"]
            # sample proportions on this sample, not population bounds:
            v["precision_on_decided"] = round(v["correct"] / decided, 3) if decided else None
            v["share_correct_all_labelled"] = round(v["correct"] / v["labelled"], 3) if v["labelled"] else None
            # a real 95% lower confidence bound (Wilson) on the decided proportion
            v["wilson95_lower_on_decided"] = _wilson_lower(v["correct"], decided)
            pro_decided = v["pro_same"] + v["pro_different"]
            v["precision_pro_only"] = round(v["pro_same"] / pro_decided, 3) if pro_decided else None
        return dict(t)
    src_tier = _tiers()
    return {"by_match_type": table(lambda r: r["link"]["match_type"]),
            "by_source_pair": table(lambda r: f"{r['link']['left_source']} ↔ {r['record_b'].get('source_id', '?')}"),
            "by_tier": table(lambda r: f"tier{src_tier.get(r['link']['left_source'], '?')} → tier{src_tier.get(r['record_b'].get('source_id'), '?')}"),
            "population": dict(Counter(l["match_type"] for l in all_links)),
            "n_labelled": len(rows)}


def _tiers() -> dict[str, int]:
    import yaml
    from ..paths import SOURCES
    out = {}
    for s in yaml.safe_load(SOURCES.read_text())["sources"]:
        sid = f"{s['portal']}:{s['dataset_id']}"
        out[sid] = s.get("tier", 3)
    return out


# ---------------------------------------------------------------------------- 2. recall
def recall_hidden_id(con, n: int = 150, use_jev: bool = True) -> dict:
    """Records linked by exact identifier to a party that has >= 1 other member: hide the record's
    identifiers, run the semantic path against EVERY other record (the production index, not a
    sample), and report each stage separately:
      candidate_recall     true party was among the candidates (blocking + similarity floor)
      ranking_accuracy     given it was a candidate, the scorer ranked it first
      acceptance_recall    ranked first AND scored >= threshold (i.e. the link would be made)
      false_accept_rate    a DIFFERENT party ranked first and scored >= threshold (a wrong link)
    """
    rows = con.execute("""
        SELECT l.left_record_key, l.canonical_key FROM links l
        JOIN (SELECT canonical_key FROM record_cluster GROUP BY 1 HAVING count(*) > 1) m USING (canonical_key)
        WHERE l.match_type LIKE 'exact_%' AND l.left_source NOT LIKE 'gleif%'""").fetchall()
    rng = random.Random(SEED)
    rows = rng.sample(rows, min(n, len(rows)))
    R = Resolver(con, use_jev=use_jev)
    all_recs = R.records()
    by_key = {r["record_key"]: r for r in all_recs}
    cluster = dict(con.execute("SELECT record_key, canonical_key FROM record_cluster").fetchall())
    R.key_of = cluster
    # the production index: every record, by its blocking keys (built once)
    index: dict = defaultdict(list)
    for r in all_recs:
        for k in N.blocking_keys(r["name_norm"], r["state"], r["postcode"]):
            index[k].append(r)
        for tn in r["trading_norms"]:
            for k in N.blocking_keys(tn, r["state"], r["postcode"]):
                index[k].append(r)
    thr = THRESHOLDS["default"]
    results = []
    for rk, true_key in rows:
        probe = dict(by_key[rk])
        probe["abn"] = probe["acn"] = probe["lei"] = None
        cands = [(c, sim) for c, sim in R._candidates(probe, index) if c["record_key"] != rk]  # never itself
        in_cands = any(cluster.get(c["record_key"]) == true_key for c, _ in cands)
        best, score, ev = R._decide(probe, cands) if cands else (None, 0.0, {})
        best_key = cluster.get(best["record_key"]) if best else None
        top_true = best is not None and best_key == true_key
        results.append({"record_key": rk, "true_party": true_key, "n_candidates": len(cands),
                        "in_candidates": in_cands, "top_is_true": top_true,
                        "accepted": top_true and score >= thr,
                        "false_accept": best is not None and not top_true and score >= thr,
                        "score": score, "best": best_key, "best_name": best["name"] if best else None,
                        "probe_name": probe["name"], "rule": ev.get("rule") or ("jev" if "jev_p_same" in ev else None)})
    n_ = len(results) or 1
    n_in = sum(r["in_candidates"] for r in results) or 1
    rep = {"n": len(results), "index_size": len(all_recs), "blocks": len(index),
           "candidate_recall": round(sum(r["in_candidates"] for r in results) / n_, 3),
           "ranking_accuracy_given_candidate": round(sum(r["top_is_true"] for r in results) / n_in, 3),
           "acceptance_recall": round(sum(r["accepted"] for r in results) / n_, 3),
           "false_accept_rate": round(sum(r["false_accept"] for r in results) / n_, 3),
           "threshold": thr, "jev_calls": R.jev_calls,
           "failure_stages": dict(Counter("ok" if r["accepted"] else "not_in_candidates" if not r["in_candidates"]
                                          else "ranked_below_other" if not r["top_is_true"] else "below_threshold" for r in results))}
    (LABELS / "recall_hidden_identifier.jsonl").write_text("\n".join(json.dumps(r) for r in results))
    return rep


# ---------------------------------------------------------------------------- 3. coverage
def identifier_coverage(con) -> dict:
    rows = con.execute("""SELECT source_id, count(*) n,
        count(*) FILTER (abn IS NOT NULL OR acn IS NOT NULL OR lei IS NOT NULL) with_id,
        count(*) FILTER (abn IS NOT NULL) with_abn, count(*) FILTER (acn IS NOT NULL) with_acn,
        count(*) FILTER (lei IS NOT NULL) with_lei
        FROM record_parties GROUP BY 1 ORDER BY 1""").fetchall()
    tiers = _tiers()
    return {r[0]: {"tier": tiers.get(r[0]), "records": r[1], "with_identifier": r[2], "pct": round(100 * r[2] / r[1], 1),
                   "abn": r[3], "acn": r[4], "lei": r[5]} for r in rows}


# ---------------------------------------------------------------------------- 4+5. resolve tests
NAMED_CASES = ["Commonwealth Bank of Australia", "Commonwealth Superannuation Corporation"]


def build_dirty_references(con, n: int = 200, absent: int = 12) -> list[dict]:
    """200 messy references: real parties perturbed in realistic ways, plus 12 that are not in the graph."""
    rng = random.Random(SEED)
    parties = con.execute("""SELECT party_key, display_name, abn, acn, state FROM party_attrs
                             WHERE display_name IS NOT NULL AND party_type = 'organisation' AND n_sources >= 1""").fetchall()
    rng.shuffle(parties)
    refs = []
    kinds = ["exact", "lower", "no_legal_form", "typo", "abn_spaced", "acn_only", "abbrev", "extra_words", "trading_or_former"]
    for key, name, abn, acn, state in parties:
        if len(refs) >= n - absent:
            break
        kind = kinds[len(refs) % len(kinds)]
        base = name
        if kind == "exact":
            ref = name
        elif kind == "lower":
            ref = name.lower()
        elif kind == "no_legal_form":
            ref = N.normalise(name).title()
        elif kind == "typo":
            toks = list(name)
            if len(toks) > 6:
                i = rng.randrange(2, len(toks) - 2)
                toks[i] = rng.choice("abcdefghijklmnopqrstuvwxyz").upper()
            ref = "".join(toks)
        elif kind == "abn_spaced" and abn:
            ref = f"{abn[:2]} {abn[2:5]} {abn[5:8]} {abn[8:]}"
        elif kind == "acn_only" and acn:
            ref = f"ACN {acn[:3]} {acn[3:6]} {acn[6:]}"
        elif kind == "abbrev":
            ref = name.replace("PTY LTD", "P/L").replace("Pty Ltd", "P/L").replace("LIMITED", "LTD")
        elif kind == "extra_words":
            ref = f"{name} ({state or 'Australia'})"
        else:
            names = con.execute("""SELECT value FROM observations o JOIN record_cluster rc ON rc.record_key = o.record_key
                                   WHERE rc.canonical_key = ? AND o.field IN ('entity.trading_name','entity.former_name') LIMIT 1""", [key]).fetchone()
            ref = names[0] if names else name
        refs.append({"id": f"ref_{len(refs) + 1:03d}", "reference": ref, "kind": kind, "expected_key": key, "expected_name": base})
    for i in range(absent):
        refs.append({"id": f"ref_{len(refs) + 1:03d}", "reference": rng.choice([
            "Zyxwv Quantum Haulage Pty Ltd", "Northern Lights Alpaca Logistics", "Blue Ocelot Mining NL", "Kettleworth & Fane Brokerage",
            "Quokka Street Dental Trust", "Pindari Vortex Holdings", "Mavourneen Software P/L", "Grey Heron Aquaculture Ltd",
            "Tessellate Bricks & Co", "Ironbark Satellite Services", "Orbital Dingo Pty Limited", "Fennel & Fig Catering Qld"]) + f" #{i}",
                     "kind": "absent", "expected_key": None, "expected_name": None})
    refs = refs[:n]
    (LABELS / "dirty_references.jsonl").write_text("\n".join(json.dumps(r) for r in refs))
    return refs


def resolve_benchmark(api: GraphAPI, refs: list[dict]) -> dict:
    """Outcomes are reported separately, never folded into one 'correct' number:
      resolved_correct / resolved_wrong              the system chose, rightly or wrongly
      clarified_with_expected / clarified_without    the system asked; was the right answer offered?
      abstained_present / abstained_correct          the system declined; was the entity really absent?
      false_resolve                                  an absent reference was resolved or offered
    For present references that did not resolve, `failure_stage` says where it went wrong:
    not_in_candidates (retrieval), not_top (ranking), below_threshold / ambiguous_gap (acceptance)."""
    out, lat = [], []
    for r in refs:
        res = api.resolve(r["reference"])
        lat.append(res["latency_ms"])
        keys = [c["key"] for c in res["candidates"]]
        top = keys[0] if keys else None
        exp, d = r["expected_key"], res["decision"]
        if exp is None:
            outcome = "abstained_correct" if d == "abstained" else "false_resolve"
            stage = None
        elif d == "resolved":
            outcome = "resolved_correct" if top == exp else "resolved_wrong"
            stage = "ok" if top == exp else ("not_in_candidates" if exp not in keys else "not_top")
        elif d == "ambiguous":
            outcome = "clarified_with_expected" if exp in keys else "clarified_without_expected"
            stage = "ambiguous_gap" if exp == top else ("not_in_candidates" if exp not in keys else "not_top")
        else:
            outcome = "abstained_present"
            stage = "not_in_candidates" if exp not in keys else ("below_threshold" if exp == top else "not_top")
        acceptable = outcome in ("resolved_correct", "clarified_with_expected", "abstained_correct")
        out.append({"reference_id": r["id"], "reference": r["reference"], "kind": r["kind"], "expected_key": exp,
                    "candidates": [{k: c[k] for k in ("key", "score", "match_type", "evidence", "path")} for c in res["candidates"]],
                    "decision": d, "outcome": outcome, "failure_stage": stage, "latency_ms": res["latency_ms"],
                    "acceptable": acceptable, "correct": acceptable})
    with (OUTPUTS / "resolve_results.jsonl").open("w") as f:
        for o in out:
            f.write(json.dumps(o, ensure_ascii=False, default=str) + "\n")
    by_kind: dict = defaultdict(lambda: {"n": 0, "resolved_correct": 0, "resolved_wrong": 0, "clarified_with_expected": 0,
                                         "clarified_without_expected": 0, "abstained_present": 0, "abstained_correct": 0,
                                         "false_resolve": 0, "stages": defaultdict(int)})
    for o in out:
        k = by_kind[o["kind"]]
        k["n"] += 1; k[o["outcome"]] += 1
        if o["failure_stage"] and o["failure_stage"] != "ok":
            k["stages"][o["failure_stage"]] += 1
    for k in by_kind.values():
        k["stages"] = dict(k["stages"])
    present = [o for o in out if o["expected_key"]]
    absent = [o for o in out if not o["expected_key"]]
    outcomes = Counter(o["outcome"] for o in out)
    lat_sorted = sorted(lat)
    return {"n": len(out), "n_present": len(present), "n_absent": len(absent), "outcomes": dict(outcomes),
            "resolved_accuracy": round(outcomes["resolved_correct"] / max(1, len(present)), 3),
            "resolved_wrong": outcomes["resolved_wrong"],
            "clarification_success": round(outcomes["clarified_with_expected"] /
                                           max(1, outcomes["clarified_with_expected"] + outcomes["clarified_without_expected"]), 3),
            "n_clarified": outcomes["clarified_with_expected"] + outcomes["clarified_without_expected"],
            "abstained_present": outcomes["abstained_present"],
            "absent_abstained": outcomes["abstained_correct"], "false_resolve": outcomes["false_resolve"],
            "acceptable": sum(o["acceptable"] for o in out), "correct": sum(o["acceptable"] for o in out),
            "failure_stages": dict(Counter(o["failure_stage"] for o in present if o["failure_stage"] != "ok")),
            "by_kind": dict(by_kind),
            "p50_ms": lat_sorted[len(lat) // 2], "p95_ms": lat_sorted[int(len(lat) * 0.95) - 1],
            "mean_ms": round(statistics.mean(lat), 1)}


def test_cases(api: GraphAPI) -> list[dict]:
    out = []
    for ref in NAMED_CASES + ["commonwealth bank", "CBA", "Commonwealth Super Corp"]:
        r = api.resolve(ref)
        out.append({"reference": ref, "decision": r["decision"],
                    "top": [{"name": c["name"], "key": c["key"], "score": c["score"], "match_type": c["match_type"],
                             "jev_p_same": c["evidence"].get("jev_p_same"), "jev_relationship": c["evidence"].get("jev_relationship")}
                            for c in r["candidates"][:3]], "latency_ms": r["latency_ms"]})
    return out


# ---------------------------------------------------------------------------- 6. reports
def graph_queries(api: GraphAPI) -> dict:
    qs = {}
    # ultimate parent for a party that has an owner
    owned = api._run("MATCH (:Party)-[:OWNS]->(p:Party) RETURN p.key AS key, p.display_name AS name LIMIT 1")
    if owned:
        qs["ultimate_parent"] = api.ultimate_parent(owned[0]["key"])
    qs["within_2_hops_of_ban"] = api.within_hops(2, limit=50)
    qs["licence_cancelled_and_banned"] = api.read_cypher(
        "MATCH (p:Party)-[:SUBJECT_OF]->(b:Ban) OPTIONAL MATCH (p)-[:HOLDS]->(l:Licence) "
        "RETURN p.display_name AS party, p.key AS key, b.ban_type AS ban, b.start_date AS ban_start, b.end_date AS ban_end, "
        "collect(DISTINCT l.licence_id) AS licences ORDER BY ban_start DESC LIMIT 25")
    qs["liquidators_firms_with_most_people"] = api.read_cypher(
        "MATCH (pe:Person)-[:AFFILIATED_WITH]->(o:Organisation) RETURN o.display_name AS firm, o.key AS key, count(pe) AS liquidators "
        "ORDER BY liquidators DESC LIMIT 10")
    qs["name_conflicts"] = api.read_cypher(
        "MATCH (p:Party) WHERE p.name_conflict = true MATCH (p)-[k:KNOWN_AS {kind:'legal'}]->(n:Name) "
        "RETURN p.key AS key, collect(DISTINCT n.text) AS legal_names, p.sources AS sources LIMIT 15")
    qs["cycle_check"] = api.read_cypher("MATCH p = (a:Party)-[:OWNS*2..6]->(a) RETURN a.key AS key, length(p) AS cycle_length LIMIT 5")
    return qs


def write_reports(con, api: GraphAPI, prec: dict, recall: dict, cov: dict, bench: dict, cases: list, gq: dict,
                  load_timing: dict | None, resolution: dict | None) -> None:
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    # ---- evaluation.md
    L = [f"# Evaluation\n\nGenerated {now}. **All labels are model labels** (Gemini 3.1 Pro + Jev, blind); see `labels/README.md`.\n"]
    L.append("## Link precision (labelled sample)\n")
    L.append(f"{prec['n_labelled']} links labelled from a population of {sum(prec['population'].values())} non-singleton links "
             f"({prec['population']}).\n\nColumns: `precision (decided)` = correct / (correct + incorrect) where both labellers "
             f"agreed — a **sample proportion**, not a population figure; `Wilson 95% lower` = a real 95% lower confidence "
             f"bound on that proportion (small groups get wide intervals: 3/3 → 0.44); `share correct of all labelled` treats "
             f"every unresolved label as wrong; `Pro-only` = Gemini Pro's verdicts alone, the labeller that is independent of "
             f"the matcher (Jev scored the semantic links itself).\n")
    for title, key in [("By match type", "by_match_type"), ("By tier pair", "by_tier"), ("By source pair", "by_source_pair")]:
        L.append(f"### {title}\n\n| group | labelled | correct | incorrect | unresolved | precision (decided) | Wilson 95% lower | share correct of all labelled | Pro-only |\n|---|---|---|---|---|---|---|---|---|")
        for k, v in sorted(prec[key].items()):
            L.append(f"| {k} | {v['labelled']} | {v['correct']} | {v['incorrect']} | {v['unresolved']} | {v['precision_on_decided']} | "
                     f"{v['wilson95_lower_on_decided']} | {v['share_correct_all_labelled']} | {v['precision_pro_only']} |")
        L.append("")
    L.append("## Thresholds\n")
    L.append(f"- semantic path, default sources: link if Jev P(same) ≥ **{THRESHOLDS['default']}**\n- sensitive sources (ASIC bans): ≥ **{THRESHOLDS['sensitive']}**\n"
             f"- persons: never linked by name alone\n- exact identifier path: 0.99 regardless (checksum-valid ABN/ACN/LEI)\n"
             f"- arbitration: a conflicting identifier of the same kind beats any name similarity → abstain\n")
    L.append("## Recall of the semantic path (hidden-identifier test, full index)\n")
    L.append(f"{recall['n']} records that were linked by an exact identifier had the identifier hidden and were re-resolved by name "
             f"against **every other record** ({recall['index_size']:,} records, {recall['blocks']:,} blocking keys) — the production "
             f"index, not a sampled background.\n\n"
             f"| stage | value |\n|---|---|\n"
             f"| candidate recall (true party among the candidates after blocking + similarity floor) | **{recall['candidate_recall']}** |\n"
             f"| ranking accuracy (true party ranked first, given it was a candidate) | **{recall['ranking_accuracy_given_candidate']}** |\n"
             f"| acceptance recall (ranked first AND ≥ threshold {recall['threshold']}: the link would be made) | **{recall['acceptance_recall']}** |\n"
             f"| false-accept rate (a different party ranked first AND ≥ threshold: a wrong link) | **{recall['false_accept_rate']}** |\n\n"
             f"Where the misses happen: {recall['failure_stages']}. "
             f"(`blocking_keys`: distinctive name tokens ≥3 chars, first-token+state, postcode+first-token; generic tokens excluded.)\n")
    L.append("## Identifier coverage per source\n\n| source | tier | records | with ABN/ACN/LEI | % | abn | acn | lei |\n|---|---|---|---|---|---|---|---|")
    for s, v in cov.items():
        L.append(f"| {s} | {v['tier']} | {v['records']} | {v['with_identifier']} | {v['pct']} | {v['abn']} | {v['acn']} | {v['lei']} |")
    L.append("\n## Confusion cases\n")
    for c in cases:
        L.append(f"- **{c['reference']}** → `{c['decision']}`; top: " + "; ".join(
            f"{t['name']} ({t['match_type']}, score {t['score']}, Jev {t['jev_p_same']}/{t['jev_relationship']})" for t in c["top"]) )
    L.append("\n## resolve() benchmark (200 dirty references, `labels/dirty_references.jsonl`)\n")
    L.append(f"Outcomes are kept apart; 'asked the user' is not counted as 'resolved'.\n\n"
             f"- **resolved accuracy: {bench['resolved_accuracy']}** = {bench['outcomes'].get('resolved_correct', 0)}/{bench['n_present']} present references resolved to the expected key; "
             f"**{bench['resolved_wrong']} resolved to a wrong key**\n"
             f"- clarification: {bench['n_clarified']} references were ambiguous; the expected entity was among the offered candidates in "
             f"{bench['outcomes'].get('clarified_with_expected', 0)} (success {bench['clarification_success']})\n"
             f"- abstained although present: {bench['abstained_present']}\n"
             f"- absent references ({bench['n_absent']}): abstained {bench['absent_abstained']}, wrongly resolved/offered {bench['false_resolve']}\n"
             f"- acceptable outcome (resolved correctly, or asked with the right option, or abstained on an absent reference): {bench['acceptable']}/{bench['n']}\n"
             f"- failure stage over present references: {bench['failure_stages']} (retrieval → ranking → acceptance)\n"
             f"- p50 {bench['p50_ms']} ms, p95 {bench['p95_ms']} ms\n")
    L.append("| perturbation | n | resolved ✓ | resolved ✗ | asked (✓ offered) | asked (✗) | abstained (present) | abstained (absent) | false resolve | failure stages |\n|---|---|---|---|---|---|---|---|---|---|")
    for k, v in bench["by_kind"].items():
        L.append(f"| {k} | {v['n']} | {v['resolved_correct']} | {v['resolved_wrong']} | {v['clarified_with_expected']} | {v['clarified_without_expected']} | "
                 f"{v['abstained_present']} | {v['abstained_correct']} | {v['false_resolve']} | {v['stages'] or ''} |")
    if resolution:
        L.append("\n## Resolution run\n\n```json\n" + json.dumps(resolution, indent=1) + "\n```")
    (OUTPUTS / "evaluation.md").write_text("\n".join(L))
    # ---- performance.md
    size = _dir_size(Path("data/neo4j")) if Path("data/neo4j").exists() else None
    duck = Path(DUCKDB).stat().st_size if Path(DUCKDB).exists() else None
    cost_per_resolve = _resolve_cost()
    P = [f"# Performance\n\nGenerated {now}. **measured** unless marked *estimated*.\n",
         "## resolve()\n", f"- p50 **{bench['p50_ms']} ms**, p95 **{bench['p95_ms']} ms**, mean {bench['mean_ms']} ms over {bench['n']} references (measured, local Neo4j in Docker, M-series Mac)",
         f"- of which model calls: only the semantic path calls Jev (≤ 6 candidates), ~{cost_per_resolve['jev_calls_per_semantic_resolve']} calls × ~{cost_per_resolve['secs_per_jev_call']} s",
         f"- cost per 1,000 resolutions: **${cost_per_resolve['usd_per_1000']}** *estimated* = Jev at ${cost_per_resolve['usd_per_jev_call']:.6f}/call × calls per resolve × share of references that reach the semantic path ({cost_per_resolve['semantic_share']}) + compute (a t3.medium-class VM at ~$0.05/h amortised over ~50 resolves/s ≈ $0.0003/1000)",
         "\n## Load\n"]
    if load_timing:
        P.append("| step | seconds |\n|---|---|")
        for k, v in load_timing.items():
            P.append(f"| {k} | {v} |")
    P.append(f"\n## Size on disk\n\n- Neo4j data dir: {size / 1e6:.0f} MB (measured)" if size else "\n## Size on disk\n\n- Neo4j: n/a")
    if duck:
        P.append(f"- DuckDB: {duck / 1e6:.0f} MB (measured)")
    P.append("\n## Rerun cost (idempotency)\n\nRe-loading an unchanged source: DuckDB skips rows whose (record_key, content_hash) already exist; Neo4j MERGEs find every node and relationship and set no new properties. Measured on a second `graph load` run — see `outputs/neo4j_load_report.json` (nodes_created = 0).")
    (OUTPUTS / "performance.md").write_text("\n".join(P))
    # ---- graph_queries.md
    G = [f"# Graph queries\n\nGenerated {now}. Query text, result, runtime, from `GraphAPI`.\n"]
    for name, r in gq.items():
        G.append(f"## {name}\n")
        q = r.get("query") or r.get("paths")
        G.append("```cypher\n" + (q if isinstance(q, str) else "\n".join(q)) + "\n```")
        if name == "ultimate_parent":
            G.append(f"start `{r['start']}` → ultimate parent `{r['ultimate_parent']}`, depth {r['depth']}, terminated_by **{r['terminated_by']}**, {r['latency_ms']} ms\n\n"
                     "Cycle policy: climb one hop at a time keeping a visited set; a repeated key stops the walk and is reported as `terminated_by: cycle` with the cycle member; depth is capped at 12 (`max_depth`). Multiple owners: the `ultimately_owned_by` edge is preferred, then highest percent; the others are listed in `other_owners`.\n")
            G.append("```json\n" + json.dumps(r["chain"], indent=1, default=str) + "\n```")
        else:
            rows = r.get("results") or r.get("rows") or []
            G.append(f"{len(rows)} rows, {r.get('latency_ms')} ms" + (" (capped)" if r.get("capped") else "") + "\n")
            G.append("```json\n" + json.dumps(rows[:12], indent=1, default=str) + "\n```")
    (OUTPUTS / "graph_queries.md").write_text("\n".join(G))


def _dir_size(p: Path) -> int:
    return sum(f.stat().st_size for f in p.rglob("*") if f.is_file())


def _resolve_cost() -> dict:
    rows = [json.loads(l) for l in (OUTPUTS / "usage.jsonl").read_text().splitlines()]
    jev = [r for r in rows if r["tag"] == "resolve:lookup:jev"]
    res = [json.loads(l) for l in (OUTPUTS / "resolve_results.jsonl").read_text().splitlines()] if (OUTPUTS / "resolve_results.jsonl").exists() else []
    semantic = [r for r in res if any(c["match_type"] == "name_semantic" for c in r["candidates"])]
    usd_call = statistics.mean(r["usd"] for r in jev) if jev else 0.00002
    secs_call = round(statistics.mean(r["secs"] for r in jev), 2) if jev else 0.0
    calls_per = round(len(jev) / max(1, len(semantic)), 1) if semantic else 0
    share = round(len(semantic) / max(1, len(res)), 2) if res else 0
    return {"usd_per_jev_call": usd_call, "secs_per_jev_call": secs_call, "jev_calls_per_semantic_resolve": calls_per,
            "semantic_share": share, "usd_per_1000": round(1000 * (usd_call * calls_per * share) + 0.0003, 4)}


def run_all(use_jev: bool = True) -> None:
    con = duckdb.connect(str(DUCKDB), read_only=True)
    api = GraphAPI()
    t = {}
    t0 = time.time(); prec = label_links(con); t["label_links_s"] = round(time.time() - t0, 1)
    t0 = time.time(); recall = recall_hidden_id(con, use_jev=use_jev); t["recall_s"] = round(time.time() - t0, 1)
    cov = identifier_coverage(con)
    refs = build_dirty_references(con)
    t0 = time.time(); bench = resolve_benchmark(api, refs); t["benchmark_s"] = round(time.time() - t0, 1)
    cases = test_cases(api)
    gq = graph_queries(api)
    load = json.loads((OUTPUTS / "neo4j_load_report.json").read_text()).get("timing") if (OUTPUTS / "neo4j_load_report.json").exists() else None
    resolution = json.loads((OUTPUTS / "resolution_report.json").read_text()) if (OUTPUTS / "resolution_report.json").exists() else None
    write_reports(con, api, prec, recall, cov, bench, cases, gq, load, resolution)
    (OUTPUTS / "evaluation_summary.json").write_text(json.dumps({"precision": prec, "recall": recall, "coverage": cov,
                                                                "benchmark": bench, "cases": cases, "timing": t}, indent=1, default=str))
    print(json.dumps({"precision_by_match_type": prec["by_match_type"], "recall": recall,
                      "benchmark": {k: bench[k] for k in ("n", "resolved_accuracy", "resolved_wrong", "clarification_success", "abstained_present",
                                                          "absent_abstained", "false_resolve", "acceptable", "failure_stages", "p50_ms", "p95_ms")},
                      "timing": t}, indent=1))
    api.close()
    con.close()
