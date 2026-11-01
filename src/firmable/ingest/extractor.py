"""The one generic extractor: (mapping config, raw file) -> canonical observations.

Deterministic, no model calls. The onboarding agent's validate step runs this exact code
over held-out records, so a config is tested by the engine that will execute it.

Output is one JSON line per CLAIM (record x field x value), carrying the ontology's
observation envelope. A raw record with two trading names yields two trading_name claims.
Nothing is reconciled here.
"""
from __future__ import annotations

import hashlib
import json
import random
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

import yaml

from . import readers, transforms
from ..ontology import enum_values, targets
from ..paths import OUTPUTS, ROOT

ENGINE_VERSION = "0.1.2"  # 0.1.1: entity_type_from_name recognises "P/L"; 0.1.2: zfill op
OBS_DIR = OUTPUTS / "observations"


# ---------- config helpers ----------------------------------------------------------------

def load_config(path: Path) -> dict:
    return yaml.safe_load(path.read_text())


def config_hash(cfg: dict) -> str:
    """Hash of the parts that change output (reader/record/filters/fields), not provenance."""
    core = {k: cfg.get(k) for k in ("reader", "record", "include_if", "fields")}
    return hashlib.sha1(json.dumps(core, sort_keys=True).encode()).hexdigest()[:10]


def extractor_version(cfg: dict) -> str:
    return (f"engine={ENGINE_VERSION};config={cfg['source_id']}@v{cfg.get('config_version', 0)}"
            f";sha={config_hash(cfg)}")


def static_check(cfg: dict, columns: list[str]) -> list[str]:
    """Problems detectable without running: unknown targets/ops/columns, bad args."""
    problems = []
    cols = set(columns)
    tgt = targets()
    for f in cfg.get("fields", []):
        t = f.get("target")
        if t not in tgt:
            problems.append(f"{t}: not a canonical field (valid: {sorted(tgt)})")
        for c in f.get("source_columns", []):
            if c not in cols:
                problems.append(f"{t}: source column {c!r} does not exist")
        for w in f.get("when", []) or []:
            if w.get("column") not in cols:
                problems.append(f"{t}: condition column {w.get('column')!r} does not exist")
        problems += _check_steps(t, f.get("transforms", []))
        allowed = enum_values(t) if t in tgt else None
        if allowed:
            for st in f.get("transforms", []):
                out_vals = []
                if st.get("op") == "constant":
                    out_vals = [str((st.get("args") or {}).get("value"))]
                elif st.get("op") == "map_values":
                    a = st.get("args") or {}
                    out_vals = [str(v) for v in (a.get("mapping") or {}).values()]
                    if a.get("default") is not None:
                        out_vals.append(str(a["default"]))
                bad = sorted({v for v in out_vals if v not in allowed})
                if bad:
                    problems.append(f"{t}: transform emits values outside the ontology enum {bad}; "
                                    f"allowed: {allowed}")
    rec = cfg.get("record", {})
    for c in rec.get("id_columns", []):
        if c not in cols:
            problems.append(f"record.id_columns: {c!r} does not exist")
    for k in ("observed_at", "valid_from", "valid_to"):
        spec = rec.get(k) or {}
        if spec.get("column") and spec["column"] not in cols:
            problems.append(f"record.{k}: column {spec['column']!r} does not exist")
        problems += _check_steps(f"record.{k}", spec.get("transforms", []))
    for w in cfg.get("include_if", []) or []:
        if w.get("column") not in cols:
            problems.append(f"include_if: column {w.get('column')!r} does not exist")
    return problems


def _check_steps(where: str, steps: list[dict]) -> list[str]:
    out = []
    for s in steps:
        if s.get("op") not in transforms.OPS:
            out.append(f"{where}: unknown transform op {s.get('op')!r}")
            continue
        try:  # dry-run with a dummy value to catch bad/missing args
            transforms.apply([s], "x")
        except TypeError as e:
            out.append(f"{where}: bad args for {s['op']}: {e}")
        except Exception:  # noqa: BLE001 - value-dependent errors are fine here
            pass
    return out


# ---------- record evaluation -------------------------------------------------------------

def _cond(row: dict, c: dict) -> bool:
    v = (row.get(c["column"]) or "").strip()
    vals = [x.strip().lower() for x in c.get("values", [])]
    op = c.get("op", "equals")
    if op == "equals":
        return v.lower() == (vals[0] if vals else "")
    if op == "in":
        return v.lower() in vals
    if op == "not_in":
        return v.lower() not in vals
    if op == "matches":
        return bool(re.search(c["values"][0], v, re.I))
    if op == "not_matches":
        return not re.search(c["values"][0], v, re.I)
    if op == "not_empty":
        return v != ""
    raise ValueError(f"unknown condition op {op!r}")


def _raw(row: dict, cols: list[str], join_with: str) -> str | None:
    parts = [(row.get(c) or "").strip() for c in cols]
    parts = [p for p in parts if p]
    return join_with.join(parts) if parts else None


def _record_id(cfg: dict, row: dict) -> str:
    cols = cfg["record"].get("id_columns") or []
    vals = [(row.get(c) or "").strip() for c in cols]
    if cols and all(vals):
        return "|".join(vals)
    # Deterministic fallback: hash of the full raw row (sorted keys). Documented in README.
    return "rowhash:" + hashlib.sha1(json.dumps(row, sort_keys=True).encode()).hexdigest()[:16]


def _date_spec(row: dict, spec: dict | None) -> str | None:
    if not spec:
        return None
    if spec.get("column"):
        return transforms.apply(spec.get("transforms", []), _raw(row, [spec["column"]], " "))
    return spec.get("fixed")


class Evaluator:
    """Applies a config to rows; accumulates the per-field metrics the validator needs."""

    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.version = extractor_version(cfg)
        self.ingested_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        self.seen_ids: Counter = Counter()
        self.stats = {"records": 0, "filtered": 0, "duplicate_ids": 0,
                      "observed_at_fallback": 0, "records_without_entity_claims": 0}
        self.field = defaultdict(lambda: {"applicable": 0, "produced": 0, "failed": 0,
                                          "enum_violations": 0, "fail_examples": [],
                                          "value_examples": [], "raw_examples": []})
        rel = cfg.get("source_reliability") or {}
        self.reliability = rel.get("score") if isinstance(rel, dict) else rel

    def record(self, row_num: int, row: dict) -> list[dict]:
        cfg = self.cfg
        if not all(_cond(row, c) for c in cfg.get("include_if", []) or []):
            self.stats["filtered"] += 1
            return []
        self.stats["records"] += 1
        rid = _record_id(cfg, row)
        self.seen_ids[rid] += 1
        if self.seen_ids[rid] > 1:
            self.stats["duplicate_ids"] += 1
            rid = f"{rid}#{self.seen_ids[rid]}"
        rec = cfg["record"]
        observed = _date_spec(row, rec.get("observed_at"))
        basis = "record"
        if not observed:
            observed = (cfg.get("dataset") or {}).get("resource_last_modified")
            basis = "dataset_modified"
            self.stats["observed_at_fallback"] += 1
        envelope = {
            "source_id": cfg["source_id"], "source_record_id": rid, "source_row": row_num,
            "observed_at": observed, "observed_at_basis": basis, "ingested_at": self.ingested_at,
            "valid_from": _date_spec(row, rec.get("valid_from")),
            "valid_to": _date_spec(row, rec.get("valid_to")),
            "licence": (cfg.get("dataset") or {}).get("licence") or "unknown",
            "extractor_version": self.version,
        }
        out = []
        for f in cfg.get("fields", []):
            t = f["target"]
            if not all(_cond(row, c) for c in f.get("when", []) or []):
                continue
            raw = _raw(row, f["source_columns"], f.get("join_with", " "))
            is_const = any(s["op"] == "constant" for s in f.get("transforms", []))
            if raw is None and not is_const:
                continue
            m = self.field[t]
            m["applicable"] += 1
            val = transforms.apply(f.get("transforms", []), raw)
            if val is None and any(s["op"] in transforms.ABSTAINING
                                   for s in f.get("transforms", [])):
                m["applicable"] -= 1  # op declined by design (e.g. a person's name has no legal form)
                m["abstained"] = m.get("abstained", 0) + 1
                continue
            if val is None:
                m["failed"] += 1
                if len(m["fail_examples"]) < 6:
                    m["fail_examples"].append(raw)
                continue
            m["produced"] += 1
            allowed = enum_values(t)
            for v in (val if isinstance(val, list) else [val]):
                if allowed and v not in allowed:
                    m["enum_violations"] += 1
                    if len(m["fail_examples"]) < 6:
                        m["fail_examples"].append(f"{raw} -> {v} (not in enum)")
                    continue
                if len(m["value_examples"]) < 4 and v not in m["value_examples"]:
                    m["value_examples"].append(v)
                    m["raw_examples"].append(raw)
                claim = {
                    **envelope, "field": t, "value": v, "raw_value": raw,
                    "source_columns": f["source_columns"],
                    "transforms": [s["op"] for s in f.get("transforms", [])],
                    "derivation_level": f.get("derivation", "L1"),
                    "confidence": {"source_reliability": self.reliability,
                                   "field_confidence": f.get("confidence")},
                }
                claim["observation_id"] = hashlib.sha1(
                    f"{rid}|{t}|{v}|{self.version}".encode()).hexdigest()[:16]
                out.append(claim)
        if not any(o["field"] in ("entity.legal_name", "entity.trading_name", "entity.abn",
                                  "entity.acn") for o in out):
            self.stats["records_without_entity_claims"] += 1
        return out

    def report(self) -> dict:
        fields = {}
        for t, m in self.field.items():
            app = m["applicable"] or 1
            fields[t] = {**m, "fail_rate": round(m["failed"] / app, 3),
                         "enum_violation_rate": round(m["enum_violations"] / app, 3)}
        n = self.stats["records"] or 1
        return {"stats": self.stats, "fields": fields,
                "duplicate_id_rate": round(self.stats["duplicate_ids"] / n, 3),
                "observed_at_fallback_rate": round(self.stats["observed_at_fallback"] / n, 3)}


# ---------- CLI entry ----------------------------------------------------------------------

def run(config_path: Path, input_path: Path | None = None, limit: int = 1000,
        sample: str = "random", seed: int = 7) -> dict:
    cfg = load_config(config_path)
    path = input_path or ROOT / cfg["dataset"]["local_file"]
    df = readers.read_frame(path, cfg["reader"])
    idx = list(range(len(df)))
    if limit and len(idx) > limit:
        idx = sorted(random.Random(seed).sample(idx, limit)) if sample == "random" else idx[:limit]
    ev = Evaluator(cfg)
    OBS_DIR.mkdir(parents=True, exist_ok=True)
    slug = config_path.stem
    n_obs = 0
    # Two outputs: claims (observations) and the raw rows they came from. Raw rows are kept
    # verbatim so any later merge can be undone and any claim re-derived.
    with (OBS_DIR / f"{slug}.jsonl").open("w") as f, \
            (OBS_DIR / f"{slug}.records.jsonl").open("w") as fr:
        for i in idx:
            row = df.iloc[i].to_dict()
            obs = ev.record(i, row)
            if obs:
                fr.write(json.dumps({"record_key": f"{cfg['source_id']}:{obs[0]['source_record_id']}",
                                     "source_id": cfg["source_id"],
                                     "source_record_id": obs[0]["source_record_id"],
                                     "source_row": i, "observed_at": obs[0]["observed_at"],
                                     "ingested_at": obs[0]["ingested_at"], "licence": obs[0]["licence"],
                                     "extractor_version": ev.version,
                                     "content_hash": hashlib.sha1(json.dumps(row, sort_keys=True).encode()).hexdigest()[:16],
                                     "raw": row}, ensure_ascii=False) + "\n")
            for o in obs:
                f.write(json.dumps(o, ensure_ascii=False) + "\n")
                n_obs += 1
    rep = {"source_id": cfg["source_id"], "extractor_version": ev.version,
           "input_rows": len(df), "sampled_rows": len(idx), "sample": sample, "seed": seed,
           "observations": n_obs, **ev.report()}
    (OBS_DIR / f"{slug}.stats.json").write_text(json.dumps(rep, indent=2, default=str))
    return rep
