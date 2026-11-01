"""Minimal CKAN Action API client for the AU government portals."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import httpx

from ..paths import CACHE as _CACHE

PORTALS = {
    "data.gov.au": "https://data.gov.au/data/api/3/action/",
    "nsw": "https://data.nsw.gov.au/data/api/3/action/",
    "sa": "https://data.sa.gov.au/data/api/3/action/",
    "qld": "https://www.data.qld.gov.au/api/3/action/",
    "vic": "https://discover.data.vic.gov.au/api/3/action/",
}

CACHE = _CACHE
UA = {"User-Agent": "firmable-case-study/0.1 (research; contact via repo)"}


def call(portal: str, action: str, **params) -> dict:
    """Call a CKAN action, caching the JSON response on disk (re-runs are free and reproducible)."""
    key = hashlib.sha1(json.dumps([portal, action, params], sort_keys=True).encode()).hexdigest()
    path = CACHE / f"{key}.json"
    if path.exists():
        return json.loads(path.read_text())
    r = httpx.get(PORTALS[portal] + action, params=params, headers=UA, timeout=60,
                  follow_redirects=True)
    r.raise_for_status()
    body = r.json()
    if not body.get("success"):
        raise RuntimeError(f"CKAN {portal}/{action} failed: {body.get('error')}")
    CACHE.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(body["result"]))
    return body["result"]


def package_show(portal: str, dataset_id: str) -> dict:
    return call(portal, "package_show", id=dataset_id)


def datastore_fields(portal: str, resource_id: str) -> list[str]:
    """Column names from the CKAN DataStore, if the resource is loaded there. Cheap schema signal."""
    try:
        res = call(portal, "datastore_search", resource_id=resource_id, limit=0)
        return [f["id"] for f in res.get("fields", []) if f["id"] != "_id"]
    except Exception:  # noqa: BLE001 - not every resource is in the datastore
        return []
