"""Part 1 — discovery and triage.

Pipeline (cheap first, model last):
  1. discover   : many package_search queries across 5 CKAN portals -> pool (>= 200, usually ~1,500)
  2. rule score : free keyword/format heuristics over title, description, tags, org
  3. schema peek: for the top N by rule score, pull DataStore column names (still free)
  4. LLM rank   : flash-lite judges only the survivors, in batches, returning confidence + reason
  5. shortlist  : top 50 by LLM confidence, ties broken by rule score

Why rules first: ~90% of the catalogue (boundaries, statistics, imagery) is obviously not
entity-level data and costs nothing to reject. The model is spent where judgement is needed.
"""
from __future__ import annotations

import csv
import json
import re
from pathlib import Path

from pydantic import BaseModel, Field

from . import ckan
from .. import llm
from ..paths import OUTPUTS

OUT = OUTPUTS

QUERIES = [
    "business names", "register", "licence holders", "licensed", "licensee", "contractors",
    "registered businesses", "ABN", "company", "suppliers", "contracts awarded", "procurement",
    "grants recipients", "food premises", "liquor licences", "building approvals", "builders",
    "accredited providers", "approved providers", "operators", "permits issued", "penalty notices",
    "prosecutions", "enforcement", "childcare services", "training organisations",
    "charities", "pharmacies", "tenders", "funded organisations", "employers", "manufacturers",
    "mining tenements", "petroleum titles", "waste licences", "environment protection licence",
    "gaming venues", "motor dealers", "security licences", "real estate agents",
]
ROWS_PER_QUERY = 50

POS = {  # term -> weight; matched as whole words in title (x2) / notes / tags
    "register": 3, "registered": 2, "licence": 3, "license": 3, "licensed": 3, "licensee": 4,
    "licences": 3, "business": 3, "businesses": 3, "company": 3, "companies": 3, "abn": 5,
    "acn": 5, "contractor": 3, "contractors": 3, "supplier": 3, "suppliers": 3, "contracts": 3,
    "contract": 2, "awarded": 2, "operator": 2, "operators": 2, "provider": 2, "providers": 2,
    "approved": 2, "accredited": 2, "holders": 3, "holder": 2, "premises": 2, "trading": 3,
    "vendor": 2, "vendors": 2, "recipients": 2, "grant": 1, "grants": 1, "employer": 2,
    "employers": 2, "organisations": 1, "permit": 1, "permits": 1, "tenements": 2, "titles": 1,
    "prosecutions": 2, "penalty": 1, "notices": 1, "list": 1, "directory": 2, "charities": 3,
}
NEG = {
    "boundary": -4, "boundaries": -4, "statistics": -2, "census": -4, "imagery": -5,
    "aerial": -5, "rainfall": -5, "elevation": -5, "lidar": -6, "vegetation": -4, "survey": -1,
    "aggregate": -3, "aggregated": -3, "summary": -2, "budget": -2, "species": -5,
    "population": -3, "estimates": -2, "forecast": -3, "index": -2, "monthly": -1,
    "geology": -4, "contours": -5, "cadastre": -3, "zones": -2, "zoning": -2, "transport": -1,
    "water": -1, "flood": -3, "tree": -3, "trees": -3, "crime": -2, "health": -1,
}
TABULAR = {"CSV", "XLSX", "XLS", "JSON", "GEOJSON", "ZIP", "XML", "TSV", "TXT"}
SCHEMA_HINTS = re.compile(
    r"\b(abn|acn|business|company|trading|licensee|licence_holder|holder|operator|entity|"
    r"supplier|contractor|vendor|organisation|organization|provider|employer|owner|applicant)\b",
    re.I)


def _fmt(r: dict) -> str:
    f = (r.get("format") or "").upper().strip(". ")
    if not f:
        f = Path((r.get("url") or "").split("?")[0]).suffix.upper().strip(".")
    return {"EXCEL (.XLSX)": "XLSX", "EXCEL": "XLSX"}.get(f, f)


def discover() -> list[dict]:
    pool: dict[str, dict] = {}
    for portal in ckan.PORTALS:
        for q in QUERIES:
            try:
                res = ckan.call(portal, "package_search", q=q, rows=ROWS_PER_QUERY)
            except Exception as e:  # noqa: BLE001 - one portal failing shouldn't stop discovery
                print(f"  ! {portal} '{q}': {e}")
                continue
            for p in res["results"]:
                key = f"{portal}:{p['name']}"
                if key in pool:
                    pool[key]["hits"].append(q)
                    continue
                pool[key] = {
                    "key": key, "portal": portal, "dataset_id": p["name"], "uuid": p["id"],
                    "title": p.get("title") or "", "notes": (p.get("notes") or "")[:1500],
                    "organisation": (p.get("organization") or {}).get("title") or "",
                    "tags": [t["name"] for t in p.get("tags", [])],
                    "licence": p.get("license_title") or p.get("license_id") or "unknown",
                    "formats": sorted({_fmt(r) for r in p.get("resources", []) if _fmt(r)}),
                    "resources": [{"id": r["id"], "format": _fmt(r), "name": r.get("name"),
                                   "url": r.get("url"), "datastore": r.get("datastore_active")}
                                  for r in p.get("resources", [])],
                    "hits": [q],
                }
    return list(pool.values())


def _words(s: str) -> list[str]:
    return re.findall(r"[a-z]+", s.lower())


def rule_score(d: dict) -> tuple[float, list[str]]:
    why, s = [], 0.0
    title, rest = _words(d["title"]), _words(d["notes"] + " " + " ".join(d["tags"]))
    for w in set(title):
        if w in POS: s += 2 * POS[w]; why.append(f"title:{w}")
        if w in NEG: s += 2 * NEG[w]; why.append(f"title:-{w}")
    for w in set(rest):
        s += POS.get(w, 0) * 0.5 + NEG.get(w, 0) * 0.5
    if TABULAR & set(d["formats"]):
        s += 3
    else:
        s -= 6; why.append("no tabular format")
    s += min(len(d["hits"]), 4)  # matched several business-ish queries
    return s, why


def schema_peek(d: dict) -> list[str]:
    for r in d["resources"]:
        if r.get("datastore"):
            cols = ckan.datastore_fields(d["portal"], r["id"])
            if cols:
                return cols
    return []


class Judgement(BaseModel):
    key: str
    confidence: float = Field(description="0-1: probability the dataset has row-level records "
                                          "that each identify a specific business/organisation")
    entity_kind: str = Field(description="what one row is, e.g. 'licensed liquor venue', or 'n/a'")
    reason: str = Field(description="one line, <= 20 words")


class Batch(BaseModel):
    items: list[Judgement]


PROMPT = """You triage Australian government open-data catalogue entries.
For each dataset decide: does it contain ROW-LEVEL records where each row identifies a specific,
nameable business or organisation (company, sole trader, licensee, contractor, supplier, provider,
venue operator)? Aggregated statistics, spatial layers, people-only data, and documents
describing a program are NOT. Government agencies as the only entity -> low.
Be calibrated: 0.9 only if the metadata or column names make it near certain.

Datasets:
{items}
"""


def llm_rank(cands: list[dict], batch: int = 20) -> dict[str, Judgement]:
    out: dict[str, Judgement] = {}
    for i in range(0, len(cands), batch):
        chunk = cands[i:i + batch]
        items = "\n".join(json.dumps({
            "key": d["key"], "title": d["title"], "organisation": d["organisation"],
            "formats": d["formats"], "description": d["notes"][:400],
            "columns": d.get("columns", [])[:40]}) for d in chunk)
        res = llm.structured(PROMPT.format(items=items), Batch, model=llm.CHEAP, tag="triage")
        for j in res.items:
            out[j.key] = j
        print(f"  llm ranked {min(i + batch, len(cands))}/{len(cands)}")
    return out


JEV_QUESTIONS = {
    "is_business": {
        "type": "noul",
        "instructions": "From this Australian open-data catalogue entry, does the dataset contain "
                        "ROW-LEVEL records that each identify a specific, nameable business or "
                        "organisation?",
        "criteria": {
            "true": "Rows are businesses/organisations or their licences, contracts, permits, "
                    "grants or registrations (company, sole trader, licensee, contractor, "
                    "supplier, venue, charity). Column names like ABN, licensee, supplier, "
                    "trading name are strong evidence.",
            "false": "Aggregated statistics, spatial layers, imagery, people-only data, program "
                     "descriptions, or only government agencies.",
        },
    },
    "row_kind": {
        "type": "choice",
        "instructions": "What is one row of this dataset most likely to be?",
        "criteria": {
            "business": "A specific named business/organisation or its licence/contract/permit.",
            "aggregate": "A count, total or statistic.",
            "person_only": "An individual person with no business identity.",
            "government_only": "Only government agencies or programs.",
            "spatial_or_other": "A map feature, document, or something else.",
        },
    },
}


def jev_confidence(cands: list[dict], workers: int = 8) -> dict[str, dict]:
    """Calibrated confidence from TypeSafe Jev: P(rows identify businesses) as a probability,
    instead of a number the generative model writes as text (which clusters at 0.9-0.99)."""
    from concurrent.futures import ThreadPoolExecutor

    def one(d: dict) -> tuple[str, dict]:
        state = {"title": d["title"], "publisher": d["organisation"], "formats": d["formats"],
                 "description": d["notes"][:600], "column_names": d.get("columns", [])[:60]
                 or "(not available from the catalogue)"}
        try:
            a = llm.jev_decide(state, JEV_QUESTIONS, tag="triage:jev")["answers"]
            return d["key"], {"p": a["is_business"]["noul"], "kind": a["row_kind"]["choice"]}
        except Exception as e:  # noqa: BLE001 - one failed call must not sink the ranking
            print(f"  ! jev failed for {d['key']}: {e}")
            return d["key"], {}

    with ThreadPoolExecutor(workers) as ex:
        return dict(ex.map(one, cands))


def run(pool_out: int = 50, llm_pool: int = 220) -> list[dict]:
    print("1/4 discover")
    pool = discover()
    print(f"  pool = {len(pool)} datasets")
    print("2/4 rule score")
    for d in pool:
        d["rule_score"], d["rule_why"] = rule_score(d)
    pool.sort(key=lambda d: d["rule_score"], reverse=True)
    print("3/4 schema peek (top by rule score)")
    top = pool[:llm_pool]
    for d in top:
        d["columns"] = schema_peek(d)
        if any(SCHEMA_HINTS.search(c.replace("_", " ")) for c in d["columns"]):
            d["rule_score"] += 6
            d["rule_why"].append("entity-like columns")
    print(f"4/4 model pass over {len(top)}: Gemini writes the reason, Jev gives the confidence")
    judged = llm_rank(top)
    jev = jev_confidence(top)
    for d in top:
        j = judged.get(d["key"])
        d["gemini_confidence"] = round(j.confidence, 2) if j else None
        d["entity_kind"] = j.entity_kind if j else ""
        d["reason"] = j.reason if j else "not judged"
        jv = jev.get(d["key"]) or {}
        if "p" in jv:
            d["confidence"], d["confidence_source"] = round(jv["p"], 3), llm.JEV
            d["jev_row_kind"] = jv["kind"]
        else:  # Jev unavailable for this one: fall back, and say so in the output
            d["confidence"], d["confidence_source"] = d["gemini_confidence"] or 0.0, llm.CHEAP
            d["jev_row_kind"] = ""
    top.sort(key=lambda d: (d["confidence"], d["rule_score"]), reverse=True)
    shortlist = dedupe(top, pool_out)

    OUT.mkdir(exist_ok=True)
    (OUT / "catalogue_pool.jsonl").write_text(
        "\n".join(json.dumps({k: d[k] for k in ("key", "title", "organisation", "formats",
                                                "rule_score")}) for d in pool))
    with (OUT / "shortlist.jsonl").open("w") as f:
        for rank, d in enumerate(shortlist, 1):
            f.write(json.dumps(_row(rank, d)) + "\n")
    with (OUT / "shortlist.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(_row(1, shortlist[0]).keys()))
        w.writeheader()
        for rank, d in enumerate(shortlist, 1):
            w.writerow({k: (";".join(v) if isinstance(v, list) else v)
                        for k, v in _row(rank, d).items()})
    print(f"wrote output/shortlist.csv ({len(shortlist)}) from pool of {len(pool)}")
    return shortlist


def _family(title: str) -> str:
    """Title minus dates, quarters, rounds and agency acronyms: groups a dataset series
    ("DESBT - 2021 Small Business Grants" ~ "CDSB - 2025 Small Business Grants")."""
    title = re.split(r"\bas (?:at|of)\b", title, flags=re.I)[0]
    months = {"jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"}
    keep = []
    for tok in re.findall(r"[A-Za-z]+", title):
        if tok.isupper() and len(tok) > 1:  # agency acronyms
            continue
        low = tok.lower()
        if low[:3] in months or re.fullmatch(r"q[1-4]|round", low):
            continue
        keep.append(low)
    return " ".join(keep)


def dedupe(ranked: list[dict], n: int, per_family: int = 2) -> list[dict]:
    """data.gov.au harvests state portals, so the same dataset appears twice; series
    (yearly grants, quarterly reports) would otherwise crowd the list. Keep the first
    (highest-ranked) copy of each exact title and at most `per_family` of a series."""
    seen_titles: set[str] = set()
    fam_count: dict[str, int] = {}
    out = []
    for d in ranked:
        t = re.sub(r"[^a-z0-9]+", " ", d["title"].lower()).strip()
        f = _family(d["title"])
        if t in seen_titles or fam_count.get(f, 0) >= per_family:
            continue
        seen_titles.add(t)
        fam_count[f] = fam_count.get(f, 0) + 1
        out.append(d)
        if len(out) == n:
            break
    return out


def _row(rank: int, d: dict) -> dict:
    return {"rank": rank, "portal": d["portal"], "dataset_id": d["dataset_id"],
            "title": d["title"], "organisation": d["organisation"], "formats": d["formats"],
            "licence": d["licence"], "confidence": d["confidence"],
            "confidence_source": d["confidence_source"], "jev_row_kind": d["jev_row_kind"],
            "gemini_confidence": d["gemini_confidence"],
            "entity_kind": d["entity_kind"], "reason": d["reason"],
            "rule_score": round(d["rule_score"], 1)}
