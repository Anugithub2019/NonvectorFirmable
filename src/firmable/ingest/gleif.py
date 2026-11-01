"""GLEIF (Global LEI Foundation) reader: Level 1 (who is who) + Level 2 (who owns whom).

Level 1 comes from the public JSON:API, filtered to Australian legal addresses (~54k records).
For Australian entities GLEIF's `registeredAs` carries the ASIC/ABR identifier (ACN or ABN),
which is what makes an exact join to tier 1 possible.
Level 2 relationships are fetched per entity only for those that report a parent, and only
within the slice (see --leis), to keep API calls bounded.

Output: data/raw/gleif/lei_au.jsonl (one flattened record per LEI) and relationships.jsonl.
Licence: CC0 (GLEIF data is public domain).
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import httpx

from ..paths import RAW

API = "https://api.gleif.org/api/v1"
OUT = RAW / "gleif"
HEADERS = {"Accept": "application/vnd.api+json", "User-Agent": "firmable-case-study/0.1"}


def _get(url: str, params: dict | None = None, retries: int = 5) -> dict:
    for attempt in range(retries):
        try:
            r = httpx.get(url, params=params, headers=HEADERS, timeout=60)
            if r.status_code == 429:
                time.sleep(10 * (attempt + 1))
                continue
            r.raise_for_status()
            return r.json()
        except (httpx.HTTPError, ValueError) as e:  # noqa: PERF203
            if attempt == retries - 1:
                raise
            time.sleep(3 * (attempt + 1))
    raise RuntimeError("unreachable")


def flatten(rec: dict) -> dict:
    a = rec["attributes"]
    e = a["entity"]
    reg = a.get("registration", {})
    addr = e.get("legalAddress") or {}
    other = [n.get("name") for n in (e.get("otherNames") or []) if n.get("name")]
    rels = rec.get("relationships") or {}
    return {
        "lei": a["lei"],
        "legal_name": (e.get("legalName") or {}).get("name"),
        "other_names": " | ".join(other),
        "status": e.get("status"),
        "legal_form": ((e.get("legalForm") or {}).get("id")),
        "category": e.get("category"),
        "registered_as": e.get("registeredAs"),
        "registered_at": ((e.get("registeredAt") or {}).get("id")),
        "jurisdiction": e.get("jurisdiction"),
        "address": ", ".join(x for x in (addr.get("addressLines") or []) if x),
        "city": addr.get("city"),
        "region": addr.get("region"),
        "postcode": addr.get("postalCode"),
        "country": addr.get("country"),
        "creation_date": e.get("creationDate"),
        "registration_status": reg.get("status"),
        "initial_registration": reg.get("initialRegistrationDate"),
        "last_update": reg.get("lastUpdateDate"),
        "next_renewal": reg.get("nextRenewalDate"),
        "has_direct_parent": "direct-parent" in rels and bool((rels.get("direct-parent") or {}).get("links", {}).get("relationship-record")),
        "has_ultimate_parent": bool((rels.get("ultimate-parent") or {}).get("links", {}).get("relationship-record")),
        "successor": " | ".join(s.get("lei") or s.get("name", "") for s in (e.get("successorEntities") or [])),
    }


def fetch_level1(country: str = "AU", page_size: int = 200, limit_pages: int | None = None) -> Path:
    OUT.mkdir(parents=True, exist_ok=True)
    out = OUT / f"lei_{country.lower()}.jsonl"
    # Offset pagination stops at 10,000 results; the API offers cursor pagination instead.
    page, n = 1, 0
    url: str | None = f"{API}/lei-records"
    params: dict | None = {"filter[entity.legalAddress.country]": country,
                           "page[size]": page_size, "page[cursor]": "*"}
    with out.open("w") as f:
        while url:
            body = _get(url, params)
            for rec in body["data"]:
                f.write(json.dumps(flatten(rec)) + "\n")
                n += 1
            total = body.get("meta", {}).get("pagination", {}).get("total", "?")
            print(f"  gleif page {page} ({n}/{total} records)", file=sys.stderr, flush=True)
            url, params = body.get("links", {}).get("next"), None
            page += 1
            if limit_pages and page > limit_pages:
                break
            time.sleep(0.2)
    return out


def fetch_relationships(leis: list[str]) -> Path:
    """Level 2: direct + ultimate parent for the given LEIs (one call each)."""
    OUT.mkdir(parents=True, exist_ok=True)
    out = OUT / "relationships.jsonl"
    with out.open("w") as f:
        for i, lei in enumerate(leis, 1):
            for kind in ("direct-parent-relationship", "ultimate-parent-relationship"):
                try:
                    body = _get(f"{API}/lei-records/{lei}/{kind}")
                except httpx.HTTPStatusError as e:
                    if e.response.status_code == 404:
                        continue
                    raise
                d = body.get("data")
                if not d:
                    continue
                a = d["attributes"]["relationship"]
                periods = {p.get("type"): p for p in d["attributes"].get("relationship", {}).get("periods", [])}
                f.write(json.dumps({
                    "child_lei": a["startNode"]["id"], "parent_lei": a["endNode"]["id"],
                    "relationship_type": a["type"], "status": a.get("status"),
                    "percent": (a.get("quantifiers") or [{}])[0].get("quantifierAmount"),
                    "valid_from": (periods.get("RELATIONSHIP_PERIOD") or {}).get("startDate"),
                    "valid_to": (periods.get("RELATIONSHIP_PERIOD") or {}).get("endDate"),
                    "registration_status": d["attributes"].get("registration", {}).get("status"),
                }) + "\n")
            if i % 100 == 0:
                print(f"  gleif relationships {i}/{len(leis)}", file=sys.stderr, flush=True)
            time.sleep(0.2)
    return out


if __name__ == "__main__":
    fetch_level1()


def relationships_from_golden_copy(zip_path: Path, au_leis: set[str]) -> Path:
    """Level 2 from the GLEIF 'golden copy' bulk RR file (one 25 MB download, ~500k rows
    worldwide) instead of two API calls per entity: the API path above is rate-limited to a
    crawl. Same output shape as fetch_relationships()."""
    import csv as _csv
    import zipfile
    out = OUT / "relationships.jsonl"
    n = 0
    with zipfile.ZipFile(zip_path) as z, out.open("w") as f:
        member = next(m for m in z.namelist() if m.endswith(".csv"))
        with z.open(member) as fh:
            rdr = _csv.DictReader((line.decode("utf-8") for line in fh))
            for r in rdr:
                child, parent = r["Relationship.StartNode.NodeID"], r["Relationship.EndNode.NodeID"]
                if child not in au_leis and parent not in au_leis:
                    continue
                periods = {r[f"Relationship.Period.{i}.periodType"]: (r[f"Relationship.Period.{i}.startDate"], r[f"Relationship.Period.{i}.endDate"])
                           for i in range(1, 6) if r.get(f"Relationship.Period.{i}.periodType")}
                rel = periods.get("RELATIONSHIP_PERIOD", ("", ""))
                f.write(json.dumps({
                    "child_lei": child, "parent_lei": parent,
                    "relationship_type": r["Relationship.RelationshipType"],
                    "status": r["Relationship.RelationshipStatus"],
                    "percent": r.get("Relationship.Quantifiers.1.QuantifierAmount") or None,
                    "valid_from": rel[0][:10] or None, "valid_to": rel[1][:10] or None,
                    "registration_status": r.get("Registration.RegistrationStatus"),
                }) + "\n")
                n += 1
    print(f"  gleif golden-copy relationships touching AU: {n}", file=sys.stderr)
    return out
