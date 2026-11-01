"""Hand-check helpers. These build sheets for a HUMAN to fill in; they never fill verdicts.

shortlist_sheet(): random 20 of the 50 (fixed seed), with real column headers and sample rows
pulled from each dataset, so the reviewer judges the data rather than the title.
"""
from __future__ import annotations

import csv
import io
import json
import random
from pathlib import Path

import httpx
from typing import Literal

from pydantic import BaseModel, Field

from . import ckan
from ..paths import OUTPUTS

OUT = OUTPUTS / "handcheck"
SEED = 20261021


def _peek(portal: str, resources: list[dict], n: int = 3) -> tuple[list[str], list[list[str]], str]:
    """Return (columns, sample_rows, where_from) for the first readable resource."""
    for r in resources:
        if r.get("datastore"):
            try:
                res = ckan.call(portal, "datastore_search", resource_id=r["id"], limit=n)
                cols = [f["id"] for f in res["fields"] if f["id"] != "_id"]
                rows = [[str(rec.get(c, ""))[:40] for c in cols] for rec in res["records"]]
                return cols, rows, f"datastore:{r['id']}"
            except Exception:  # noqa: BLE001
                pass
    for r in resources:
        if r.get("format") in ("CSV", "TSV", "TXT") and r.get("url"):
            try:
                with httpx.stream("GET", r["url"], timeout=30, follow_redirects=True,
                                  headers=ckan.UA) as s:
                    buf = b""
                    for chunk in s.iter_bytes():
                        buf += chunk
                        if len(buf) > 65536:
                            break
                text = buf.decode("utf-8-sig", errors="replace")
                rows = list(csv.reader(io.StringIO(text)))[:n + 1]
                return rows[0], [[c[:40] for c in row] for row in rows[1:]], r["url"]
            except Exception:  # noqa: BLE001
                pass
    return [], [], "not previewable (open the dataset page manually)"


def shortlist_sheet(n: int = 20) -> Path:
    rows = [json.loads(line) for line in (OUT.parent / "shortlist.jsonl").read_text().splitlines()]
    sample = random.Random(SEED).sample(rows, n)
    OUT.mkdir(parents=True, exist_ok=True)
    md = ["# Shortlist hand-check (20 random of 50, seed %d)" % SEED, "",
          "Fill `verdict` in shortlist_handcheck.csv: Y = rows identify specific businesses, "
          "N = they do not, ? = cannot tell. Judge the columns/rows, not the title.", ""]
    for s in sample:
        pkg = ckan.package_show(s["portal"], s["dataset_id"])
        res = [{"id": r["id"], "format": (r.get("format") or "").upper(), "url": r.get("url"),
                "datastore": r.get("datastore_active")} for r in pkg.get("resources", [])]
        cols, sample_rows, src = _peek(s["portal"], res)
        md += [f"## #{s['rank']} {s['title']}", f"- portal/id: `{s['portal']}` / `{s['dataset_id']}`",
               f"- model said: {s['confidence']} — {s['reason']}", f"- preview from: {src}", ""]
        if cols:
            md.append("| " + " | ".join(cols[:10]) + " |")
            md.append("|" + "---|" * min(len(cols), 10))
            for r in sample_rows:
                md.append("| " + " | ".join((r + [""] * 10)[:min(len(cols), 10)]) + " |")
        md.append("")
        print(f"  #{s['rank']:>2} {len(cols):>3} cols  {s['title'][:60]}")
    (OUT / "shortlist_handcheck.md").write_text("\n".join(md))
    with (OUT / "shortlist_handcheck.csv").open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["rank", "portal", "dataset_id", "title", "model_confidence", "verdict", "note"])
        for s in sorted(sample, key=lambda s: s["rank"]):
            w.writerow([s["rank"], s["portal"], s["dataset_id"], s["title"], s["confidence"], "", ""])
    print(f"wrote {OUT}/shortlist_handcheck.md and .csv — fill in the verdict column")
    return OUT


# ---------- LLM judge (independent second opinion; NOT a substitute for the hand-check) ----

JUDGE_PROMPT = """You are auditing an automated dataset triage. Decide from the DATA ONLY whether
this Australian open dataset contains row-level records that each identify a specific, nameable
business or organisation (company, sole trader, partnership, trust, incorporated association,
licensee, contractor, supplier, venue operator, grant recipient business).

Answer N if rows are aggregates/statistics, spatial features without a business name, people
only (no business), program descriptions, or only government agencies. Answer ? only if the
evidence below is genuinely insufficient (e.g. no columns could be previewed).
Do not trust the title; weigh the columns and sample rows.

Title: {title}
Publisher: {publisher}
Preview source: {src}
Columns: {cols}
Sample rows:
{rows}
"""


class JudgeVerdict(BaseModel):
    verdict: Literal["Y", "N", "?"]
    entity_columns: list[str] = Field(description="columns that name/identify the business, if any")
    reason: str = Field(description="one sentence citing the evidence")


def judge_sheet() -> Path:
    """Re-preview the 20 sampled datasets (8 rows, all columns) and have a model from a
    DIFFERENT family than the triage model judge them blind (it never sees the triage
    confidence or reason). Writes llm_judge_* columns; the human `verdict` column is untouched."""
    from .. import llm
    path = OUT / "shortlist_handcheck.csv"
    rows = list(csv.DictReader(path.open()))
    for r in rows:
        pkg = ckan.package_show(r["portal"], r["dataset_id"])
        res = [{"id": x["id"], "format": (x.get("format") or "").upper(), "url": x.get("url"),
                "datastore": x.get("datastore_active")} for x in pkg.get("resources", [])]
        cols, sample, src = _peek(r["portal"], res, n=8)
        v = llm.openrouter_json(JUDGE_PROMPT.format(
            title=r["title"], publisher=(pkg.get("organization") or {}).get("title"), src=src,
            cols=cols or "(none could be previewed)",
            rows="\n".join(json.dumps(dict(zip(cols, s)), ensure_ascii=False) for s in sample)
            or "(none)"), JudgeVerdict, model=llm.JUDGE, tag="judge:shortlist")
        r["llm_judge_verdict"], r["llm_judge_reason"] = v.verdict, v.reason
        r["llm_judge_entity_columns"] = ";".join(v.entity_columns)
        print(f"  #{r['rank']:>2} {v.verdict}  {r['title'][:55]:<55} {v.reason[:70]}")
    fields = list(rows[0].keys())
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    ys = sum(r["llm_judge_verdict"] == "Y" for r in rows)
    qs = sum(r["llm_judge_verdict"] == "?" for r in rows)
    print(f"LLM judge ({llm.JUDGE}): {ys}/{len(rows)} Y, {qs} undecidable "
          f"-> judged precision {ys}/{len(rows) - qs} decidable")
    return path


JEV_QUESTIONS = {
    "is_business": {
        "type": "noul",
        "instructions": "Judging from the columns and sample rows (not the title), does each row of "
                        "this Australian open dataset identify a specific, nameable business or "
                        "organisation?",
        "criteria": {
            "true": "Rows name or uniquely identify a business/organisation: company, sole trader, "
                    "licensee, contractor, supplier, venue, charity, grant-recipient business.",
            "false": "Rows are aggregates or statistics, spatial features with no business name, "
                     "people with no business, template/header junk, anonymous codes, or only "
                     "government agencies.",
        },
    },
    "row_kind": {
        "type": "choice",
        "instructions": "What does one row of this dataset represent?",
        "criteria": {
            "business": "A specific named business or organisation (or its licence/contract/permit).",
            "aggregate": "A count, total or statistic, not an individual entity.",
            "person_only": "An individual person with no business identity.",
            "government_only": "Only government agencies or programs.",
            "anonymous": "An entity referred to only by an opaque code, with no name.",
            "unusable_preview": "The preview is empty, broken or template rows, so it cannot be judged.",
        },
    },
}


def jev_judge_sheet(yes: float = 0.7, no: float = 0.3) -> Path:
    """Same blind evidence as judge_sheet(), judged by TypeSafe Jev (decision model).
    Verdict: Y if P(business) >= `yes`, N if <= `no`, else '?'. Writes jev_* columns."""
    from .. import llm
    path = OUT / "shortlist_handcheck.csv"
    rows = list(csv.DictReader(path.open()))
    for r in rows:
        pkg = ckan.package_show(r["portal"], r["dataset_id"])
        res = [{"id": x["id"], "format": (x.get("format") or "").upper(), "url": x.get("url"),
                "datastore": x.get("datastore_active")} for x in pkg.get("resources", [])]
        cols, sample, src = _peek(r["portal"], res, n=8)
        state = {"title": r["title"],
                 "publisher": (pkg.get("organization") or {}).get("title"),
                 "preview_source": src, "columns": cols or "(none could be previewed)",
                 "sample_rows": [dict(zip(cols, s)) for s in sample] or "(none)"}
        a = llm.jev_decide(state, JEV_QUESTIONS, tag="judge:shortlist:jev")["answers"]
        p = a["is_business"]["noul"]
        kind = a["row_kind"]["choice"]
        verdict = "?" if not cols else "Y" if p >= yes else "N" if p <= no else "?"
        r.update({"jev_p_business": f"{p:.2f}", "jev_row_kind": kind,
                  "jev_row_kind_conf": f"{a['row_kind'].get('confidence', 0):.2f}",
                  "jev_verdict": verdict})
        print(f"  #{r['rank']:>2} {verdict} p={p:.2f} {kind:<16} {r['title'][:55]}")
    fields = list(dict.fromkeys(k for r in rows for k in r))
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    ys = sum(r["jev_verdict"] == "Y" for r in rows)
    qs = sum(r["jev_verdict"] == "?" for r in rows)
    print(f"Jev ({llm.JEV}, Y>={yes}, N<={no}): {ys}/{len(rows)} Y, {qs} undecided "
          f"-> judged precision {ys}/{len(rows) - qs} decidable")
    if "llm_judge_verdict" in rows[0]:
        agree = sum(r["jev_verdict"] == r["llm_judge_verdict"] for r in rows)
        print(f"agreement with Claude judge: {agree}/{len(rows)}; disagreements:")
        for r in rows:
            if r["jev_verdict"] != r["llm_judge_verdict"]:
                print(f"    #{r['rank']} {r['title'][:55]}: jev={r['jev_verdict']} "
                      f"(p={r['jev_p_business']}, {r['jev_row_kind']}) claude={r['llm_judge_verdict']}")
    return path
