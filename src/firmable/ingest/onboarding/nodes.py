"""Onboarding agent steps. Each node reads the shared state and returns an update.

Deterministic nodes (resolve, download, try_read, profile, validate-metrics, emit) are tools;
LLM nodes (pick resource, inspect, propose, revise, critic) make judgements. The model never
sees its own output graded by itself alone: every proposal is executed by the real extractor
on held-out rows before the critic or the human look at it.
"""
from __future__ import annotations

import functools
import hashlib
import json
import random
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

import httpx
import yaml
from pydantic import BaseModel, Field

from ... import llm, ontology
from ...paths import CONFIGS, OUTPUTS, RAW, ROOT
from .. import ckan, readers, transforms
from ..extractor import Evaluator, extractor_version, static_check
from . import prompts
from .schemas import (CriticResult, InspectResult, MappingProposal, ResourceChoice)

REPORTS = OUTPUTS / "onboarding"
AGENT_VERSION = "onboard-0.1.0"

MAX_DOWNLOAD = 300 * 1024 * 1024
N_TRAIN, N_HOLDOUT, SEED = 300, 1000, 13
MAX_INSPECT_ATTEMPTS, MAX_REVISIONS = 3, 3
MAX_REVIEW_REJECTIONS = 2   # reviewer rejections that reopen the agent; a rejection after that fails the run
TABULAR = {"CSV", "TSV", "XLSX", "XLS", "JSON", "GEOJSON"}


class StepFailed(Exception):
    """Expected, explainable failure: ends the run with a status instead of a crash."""


def step(name: str):
    """Record wall-clock time and LLM spend for each node into state['steps']."""
    def deco(fn):
        @functools.wraps(fn)
        def wrapper(state: dict) -> dict:
            t0 = time.time()
            try:
                update = fn(state) or {}
            except StepFailed as e:
                update = {"status": f"failed:{name}", "error": str(e)}
            u = llm.usage_since(t0, f"onboard:{state['slug']}:")
            update["steps"] = [{"node": name, "secs": round(time.time() - t0, 2), **u}]
            print(f"  [{state['slug'][:40]}] {name:<10} {time.time() - t0:6.1f}s "
                  f"${u['usd']:.4f}  {update.get('status', '')}")
            return update
        return wrapper
    return deco


def _tag(state: dict, node: str) -> str:
    return f"onboard:{state['slug']}:{node}"


def _steps_from_json(steps: list) -> list[dict]:
    out = []
    for s in steps:
        d = s.model_dump()
        d["args"] = json.loads(d.pop("args_json") or "{}")
        out.append(d)
    return out


# ---------- 1. resolve: catalogue metadata + choose the resource ---------------------------

@step("resolve")
def resolve(state: dict) -> dict:
    if state["portal"] == "local":
        m = state["local_meta"]
        return {"dataset": {
            "portal": "local", "dataset_id": state["dataset_id"], "title": m["title"],
            "publisher": m.get("publisher"), "licence": m.get("licence", "unknown"),
            "licence_flag": None if m.get("licence") else "no licence recorded",
            "description": m.get("description", ""), "resource_id": None, "resource_name": Path(m["file"]).name,
            "resource_url": None, "resource_format": Path(m["file"]).suffix.upper().strip("."),
            "resource_last_modified": m.get("last_modified"), "resource_choice_reason": "local file"}}
    pkg = ckan.package_show(state["portal"], state["dataset_id"])
    res = pkg.get("resources", [])
    fmt = lambda r: (r.get("format") or "").upper().strip(". ")  # noqa: E731
    if state.get("resource_hint"):
        chosen = next((r for r in res if r["id"] == state["resource_hint"]), None)
        if not chosen:
            raise StepFailed(f"resource {state['resource_hint']} not in dataset")
        why = "resource chosen by operator"
    else:
        cands = [r for r in res if fmt(r) in TABULAR] or res
        if len(cands) == 1:
            chosen, why = cands[0], "only tabular resource"
        else:
            listing = "\n".join(f"- id={r['id']} format={fmt(r)} name={r.get('name')!r} "
                                f"size={r.get('size')} modified={r.get('last_modified')}"
                                for r in res)
            pick = llm.structured(prompts.PICK_RESOURCE.format(
                title=pkg.get("title"), publisher=(pkg.get("organization") or {}).get("title"),
                resources=listing), ResourceChoice, model=llm.CHEAP, tag=_tag(state, "resolve"))
            chosen = next((r for r in res if r["id"] == pick.resource_id), cands[0])
            why = pick.reason
    licence = pkg.get("license_title") or pkg.get("license_id") or "unknown"
    return {"dataset": {
        "portal": state["portal"], "dataset_id": state["dataset_id"], "title": pkg.get("title"),
        "publisher": (pkg.get("organization") or {}).get("title"),
        "licence": licence, "licence_flag": None if pkg.get("license_id") not in (None, "", "notspecified")
        else "no clear licence in catalogue metadata",
        "description": (pkg.get("notes") or "")[:800],
        "resource_id": chosen["id"], "resource_name": chosen.get("name"),
        "resource_url": chosen.get("url"), "resource_format": fmt(chosen),
        "resource_last_modified": chosen.get("last_modified") or chosen.get("created")
        or pkg.get("metadata_modified"),
        "resource_choice_reason": why}}


# ---------- 2. download --------------------------------------------------------------------

@step("download")
def download(state: dict) -> dict:
    d = state["dataset"]
    if state["portal"] == "local":
        path = ROOT / state["local_meta"]["file"]
        if not path.exists():
            raise StepFailed(f"local file missing: {path} (run the slice step first)")
        return {"local_file": str(path.relative_to(ROOT)),
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    folder = RAW / state["slug"]
    folder.mkdir(parents=True, exist_ok=True)
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", Path(d["resource_url"].split("?")[0]).name) or "file"
    path = folder / name
    if not path.exists():
        tmp = path.with_suffix(path.suffix + ".part")
        with httpx.stream("GET", d["resource_url"], headers=ckan.UA, timeout=120,
                          follow_redirects=True) as r:
            if r.status_code >= 400:
                raise StepFailed(f"HTTP {r.status_code} from publisher ({d['resource_url']})")
            size = 0
            with tmp.open("wb") as f:
                for chunk in r.iter_bytes(1 << 20):
                    size += len(chunk)
                    if size > MAX_DOWNLOAD:
                        raise StepFailed(f"resource > {MAX_DOWNLOAD >> 20} MB; needs a streaming "
                                         "reader (not built)")
                    f.write(chunk)
        tmp.rename(path)
    head = path.read_bytes()[:4096]
    if readers._magic(head) == "html" and d["resource_format"] not in ("HTML",):
        path.unlink()
        raise StepFailed("publisher returned an HTML page instead of the file "
                         "(bot protection / login wall?) — cannot fetch programmatically")
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    return {"local_file": str(path.relative_to(ROOT)), "sha256": sha}


# ---------- 3. inspect (LLM) <-> try_read (tool) loop ----------------------------------------

@step("inspect")
def inspect(state: dict) -> dict:
    path = ROOT / state["local_file"]
    sniff = state.get("sniff") or readers.sniff(path)
    attempts = state.get("reader_attempts", [])
    history = ""
    if attempts:
        history = prompts.INSPECT_HISTORY.format(attempts=json.dumps(attempts[-2:], indent=1,
                                                                     default=str)[:6000])
    d = state["dataset"]
    meta = json.dumps({k: d[k] for k in ("title", "publisher", "resource_name",
                                         "resource_format", "description")}, indent=1)
    res = llm.structured(prompts.INSPECT.format(meta=meta, sniff=json.dumps(sniff, default=str)[:9000],
                                                history=history),
                         InspectResult, tag=_tag(state, "inspect"))
    return {"sniff": sniff, "understanding": res.model_dump(exclude={"reader"}),
            "reader": res.reader.model_dump()}


@step("try_read")
def try_read(state: dict) -> dict:
    spec = state["reader"]
    result = readers.try_read(ROOT / state["local_file"], spec)
    attempts = state.get("reader_attempts", []) + [{"spec": spec, "result": {
        k: v for k, v in result.items() if k != "first_rows"} | {
        "first_rows": result.get("first_rows", [])[:3]}}]
    accepted = state["understanding"].get("accept_warnings") and len(attempts) > 1 \
        and attempts[-2]["spec"] == spec
    ok = result.get("ok") and (not result.get("warnings") or accepted)
    upd = {"reader_attempts": attempts, "reader_ok": bool(ok)}
    if not ok and len(attempts) >= MAX_INSPECT_ATTEMPTS:
        if result.get("ok"):
            upd["reader_ok"] = True  # parses, warnings unresolved: surface them to the human
            upd["reader_warnings_unresolved"] = result["warnings"]
        else:
            raise StepFailed(f"could not find a working reader after {len(attempts)} attempts: "
                             f"{result.get('error')}")
    return upd


# ---------- 4. profile ---------------------------------------------------------------------

_DATE_FORMATS = ["%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%d/%m/%Y", "%d/%m/%y",
                 "%d-%m-%Y", "%m/%d/%Y", "%d %b %Y", "%d-%b-%Y", "%d-%b-%y", "%Y%m%d"]


_PLACEHOLDERS = {"NULL", "NONE", "N/A", "NA", "-", "--", "NIL", "UNKNOWN", "TBA", "TBC", "0",
                 "NOT APPLICABLE", "NOT PROVIDED", "#N/A", "."}


def _profile_column(vals: list[str]) -> dict:
    nonempty = [v for v in vals if v.strip()]
    n = len(nonempty) or 1
    rate = lambda pred: round(sum(1 for v in nonempty if pred(v)) / n, 2)  # noqa: E731
    digits = lambda v: re.sub(r"\D", "", v)  # noqa: E731
    p = {"fill_rate": round(len(nonempty) / (len(vals) or 1), 2),
         "distinct_ratio": round(len(set(nonempty)) / n, 2),
         "avg_len": round(sum(map(len, nonempty)) / n, 1),
         "examples": list(dict.fromkeys(nonempty))[:6]}
    signals = {
        "abn_checksum_ok": rate(lambda v: ontology.abn_valid(digits(v))),
        "acn_checksum_ok": rate(lambda v: ontology.acn_valid(digits(v))),
        "postcode_like": rate(lambda v: bool(re.search(r"(?<!\d)\d{4}(?!\d)", v))),
        "state_token": rate(lambda v: bool(re.search(r"\b(NSW|VIC|QLD|WA|SA|TAS|ACT|NT)\b", v.upper()))),
        "url_like": rate(lambda v: bool(re.search(r"(www\.|https?://|\.com|\.au\b)", v, re.I))),
        "email_like": rate(lambda v: "@" in v),
        "legal_form_word": rate(lambda v: bool(re.search(r"\b(PTY|LTD|LIMITED|INC|INCORPORATED|TRUST)\b", v.upper()))),
        "numeric": rate(lambda v: bool(re.fullmatch(r"-?[\d,]+(\.\d+)?", v.strip()))),
    }
    p["signals"] = {k: v for k, v in signals.items() if v >= 0.05}
    placeholders = sorted({v.strip() for v in nonempty
                           if v.strip().upper() in _PLACEHOLDERS})
    if placeholders:
        p["placeholder_values_present"] = placeholders
    for fmt in _DATE_FORMATS:
        ok = 0
        for v in nonempty[:200]:
            try:
                time.strptime(v.strip(), fmt)
                ok += 1
            except ValueError:
                pass
        if nonempty and ok / min(len(nonempty), 200) >= 0.8:
            p["date_format"] = fmt
            break
    return p


@step("profile")
def profile(state: dict) -> dict:
    df = readers.read_frame(ROOT / state["local_file"], state["reader"])
    idx = list(range(len(df)))
    random.Random(SEED).shuffle(idx)
    if len(idx) >= 2 * N_TRAIN:
        train, holdout = sorted(idx[:N_TRAIN]), sorted(idx[N_TRAIN:N_TRAIN + N_HOLDOUT])
    elif len(idx) >= 40:  # small source: half to propose on, half held out
        half = len(idx) // 2
        train, holdout = sorted(idx[:half]), sorted(idx[half:])
    else:  # tiny source: nothing can be held out; validation runs on the same rows (flagged)
        train = holdout = sorted(idx)
    tdf = df.iloc[train]
    prof = {c: _profile_column(tdf[c].tolist()) for c in df.columns}
    sample = tdf.head(15).map(lambda s: s[:80]).to_dict(orient="records")
    return {"columns": list(df.columns), "total_rows": len(df), "train_idx": train,
            "holdout_idx": holdout, "profile": prof, "sample_rows": sample}


# ---------- 5. propose / revise (LLM) ------------------------------------------------------

_OVERESCAPED = re.compile(r"\\\\([bBdDsSwW])")


def _unescape(v):
    """The model repeatedly writes regexes one escaping level too deep (\\\\b instead of \\b),
    which silently matches nothing. A literal backslash before a regex class letter never occurs
    in business names, so collapse it deterministically instead of hoping the prompt rule holds."""
    if isinstance(v, str):
        return _OVERESCAPED.sub(r"\\\1", v)
    if isinstance(v, list):
        return [_unescape(x) for x in v]
    if isinstance(v, dict):
        return {k: _unescape(x) for k, x in v.items()}
    return v


def _proposal_to_config(state: dict, p: MappingProposal) -> tuple[dict, list[str]]:
    """Convert the LLM's proposal into the config the engine runs. Bad args_json -> issue."""
    cfg, issues = _proposal_to_config_raw(state, p)
    for f in cfg["fields"]:
        f["when"] = _unescape(f["when"])
        f["transforms"] = _unescape(f["transforms"])
    cfg["include_if"] = _unescape(cfg["include_if"])
    return cfg, issues


def _proposal_to_config_raw(state: dict, p: MappingProposal) -> tuple[dict, list[str]]:
    issues = []

    def steps(ss, where):
        try:
            return _steps_from_json(ss)
        except json.JSONDecodeError as e:
            issues.append(f"{where}: args_json is not valid JSON ({e})")
            return []

    def date(ds, where):
        if not ds.column:
            return None
        return {"column": ds.column, "transforms": steps(ds.transforms, where), "note": ds.note}

    r = p.record
    d = state["dataset"]
    cfg = {
        "source_id": state["source_id"],
        "config_version": 1,
        "dataset": {**{k: d[k] for k in ("portal", "dataset_id", "title", "publisher", "licence",
                                          "licence_flag", "resource_id", "resource_url",
                                          "resource_format", "resource_last_modified")},
                    "local_file": state["local_file"], "sha256": state["sha256"]},
        "reader": state["reader"],
        "record": {"id_columns": r.id_columns, "id_note": r.id_note,
                   "observed_at": date(r.observed_at, "record.observed_at")
                   or {"fixed": None, "note": r.observed_at.note or
                       "no per-record statement date; dataset last-modified is used"},
                   "valid_from": date(r.valid_from, "record.valid_from"),
                   "valid_to": date(r.valid_to, "record.valid_to")},
        "include_if": [c.model_dump() for c in p.include_if],
        "include_if_reason": p.include_if_reason,
        "fields": [{"target": f.target, "source_columns": f.source_columns,
                    "join_with": f.join_with,
                    "transforms": steps(f.transforms, f.target),
                    "when": [c.model_dump() for c in f.when],
                    "confidence": round(f.confidence, 2), "derivation": f.derivation,
                    "rationale": f.rationale} for f in p.fields],
        "unmapped": [u.model_dump() for u in p.unmapped],
        "source_reliability": {"score": round(p.source_reliability, 2),
                               "reason": p.source_reliability_reason},
        "reviewer_notes": p.reviewer_notes,
    }
    return cfg, issues


def _profile_text(state: dict) -> str:
    return "\n".join(f"- {c!r}: {json.dumps(p, ensure_ascii=False)[:400]}"
                     for c, p in state["profile"].items())


def _propose(state: dict, revision: str, node: str) -> dict:
    d = state["dataset"]
    meta = json.dumps({k: d.get(k) for k in ("title", "publisher", "licence", "resource_name",
                                             "resource_format", "resource_last_modified",
                                             "description")}, indent=1)
    prompt = prompts.PROPOSE.format(
        ontology=ontology.raw_text(), ops=transforms.catalogue(), meta=meta,
        understanding=json.dumps(state["understanding"]), n_train=len(state["train_idx"]),
        profile=_profile_text(state), sample=readers.to_text_table(state["sample_rows"], 60),
        revision=revision)
    p = llm.structured(prompt, MappingProposal, tag=_tag(state, node))
    cfg, issues = _proposal_to_config(state, p)
    return {"config": cfg, "config_issues": issues,
            "changes_log": state.get("changes_log", []) + [
                {"iteration": state.get("iteration", 0) + (node == "revise"),
                 "node": node, "changes": p.changes_from_previous or "initial proposal"}]}


@step("propose")
def propose(state: dict) -> dict:
    return {**_propose(state, "", "propose"), "iteration": 0}


@step("revise")
def revise(state: dict) -> dict:
    v = state["validation"]
    report = json.dumps({"blocking": v["blocking"], "warnings": v["warnings"],
                         "field_metrics": {t: {k: m[k] for k in ("applicable", "produced", "failed",
                                                                 "fail_rate", "fail_examples")}
                                           for t, m in v["metrics"]["fields"].items()}},
                        indent=1, default=str)
    human = ""
    if state.get("human_feedback"):
        human = "\nHUMAN REVIEWER FEEDBACK (highest priority):\n- " + "\n- ".join(
            state["human_feedback"])
    previous = yaml.safe_dump({k: state["config"][k] for k in
                               ("record", "include_if", "fields", "unmapped")}, sort_keys=False)
    rev = prompts.REVISION.format(iteration=state.get("iteration", 0) + 1, previous=previous,
                                  n_holdout=len(state["holdout_idx"]), report=report, human=human)
    return {**_propose(state, rev, "revise"), "iteration": state.get("iteration", 0) + 1}


# ---------- 6. validate: run the real engine on unseen rows, then an LLM critic ------------

@step("validate")
def validate(state: dict) -> dict:
    cfg = state["config"]
    blocking = list(state.get("config_issues", []))
    warnings: list[str] = []
    blocking += static_check(cfg, state["columns"])

    df = readers.read_frame(ROOT / state["local_file"], state["reader"])
    ev = Evaluator(cfg)
    produced_by_row = []
    if not blocking:  # only execute configs that are structurally valid
        for i in state["holdout_idx"]:
            row = df.iloc[i].to_dict()
            produced_by_row.append((i, row, ev.record(i, row)))
    metrics = ev.report()

    # metric gates
    if produced_by_row:
        for f in cfg.get("fields", []):
            if f["target"] not in metrics["fields"]:
                # with a condition it is almost certainly a broken condition; without one the
                # column may just be rare, so only warn
                (blocking if f.get("when") else warnings).append(
                    f"{f['target']}: mapping applied to 0 of {len(produced_by_row)} held-out rows "
                    f"— its `when` condition never holds or its source columns are always empty "
                    f"(check regex escaping: values are used verbatim, write \\b not \\\\b)")
    for t, m in metrics["fields"].items():
        if m["applicable"] >= 5 and m["fail_rate"] > 0.10:
            blocking.append(f"{t}: {m['fail_rate']:.0%} of non-empty source values failed to "
                            f"transform, e.g. {m['fail_examples'][:3]}")
        elif m["applicable"] >= 5 and m["fail_rate"] > 0.02:
            warnings.append(f"{t}: {m['fail_rate']:.0%} transform failures, e.g. "
                            f"{m['fail_examples'][:3]}")
        if m["enum_violations"]:
            blocking.append(f"{t}: {m['enum_violations']} values outside the ontology enum, "
                            f"e.g. {m['fail_examples'][:3]}")
    if metrics["duplicate_id_rate"] > 0.01:
        blocking.append(f"record id not unique: {metrics['duplicate_id_rate']:.1%} duplicates "
                        f"in holdout with id_columns={cfg['record']['id_columns']}")
    identity = {"entity.legal_name", "entity.trading_name", "entity.abn", "entity.acn", "person.full_name"}
    if not identity & {f["target"] for f in cfg.get("fields", [])}:
        blocking.append("no identifying field mapped (legal_name/trading_name/abn/acn)")
    used = set(cfg["record"]["id_columns"])
    for f in cfg.get("fields", []):
        used |= set(f["source_columns"]) | {c["column"] for c in f.get("when", [])}
    for k in ("observed_at", "valid_from", "valid_to"):
        used |= {(cfg["record"].get(k) or {}).get("column")}
    used |= {c["column"] for c in cfg.get("include_if", [])}
    used |= {u["column"] for u in cfg.get("unmapped", [])}
    missing = [c for c in state["columns"] if c not in used]
    if missing:
        warnings.append(f"columns neither mapped nor listed as unmapped: {missing}")
    if metrics["stats"]["records"] and metrics["stats"]["records_without_entity_claims"] \
            / metrics["stats"]["records"] > 0.2:
        warnings.append(f"{metrics['stats']['records_without_entity_claims']} of "
                        f"{metrics['stats']['records']} kept records produced no identifying claim")

    # LLM critic on a few raw->claims pairs (semantic errors metrics cannot see)
    critic = None
    if not blocking and produced_by_row:
        pick = random.Random(SEED + state.get("iteration", 0)).sample(
            produced_by_row, min(8, len(produced_by_row)))
        rows = "\n\n".join(
            f"RAW: {json.dumps({k: v[:80] for k, v in row.items() if v}, ensure_ascii=False)}\n"
            f"CLAIMS: {json.dumps([(o['field'], o['value']) for o in obs], ensure_ascii=False)}"
            for _, row, obs in pick)
        mapping = yaml.safe_dump({"include_if": cfg["include_if"], "fields": [
            {k: f[k] for k in ("target", "source_columns", "transforms", "when")}
            for f in cfg["fields"]]}, sort_keys=False)[:6000]
        critic = llm.structured(prompts.CRITIC.format(mapping=mapping, rows=rows,
                                                      targets=", ".join(ontology.targets())),
                                CriticResult, tag=_tag(state, "critic")).model_dump()
        for i in critic["issues"]:
            msg = f"[critic] {i['field']}: {i['problem']} -> {i['suggestion']}"
            (blocking if i["severity"] == "blocking" else warnings).append(msg)

    # Calibrated per-field confidence from Jev (decision model), replacing the proposing
    # model's self-reported number. Blind: Jev sees the mapping and raw->value examples, not
    # the proposer's confidence or rationale.
    if produced_by_row:
        jev_field_confidence(cfg, metrics, state, warnings)

    passed = not blocking
    return {"validation": {"passed": passed, "blocking": blocking, "warnings": warnings,
                           "metrics": metrics, "critic": critic,
                           "iteration": state.get("iteration", 0)},
            "validation_history": state.get("validation_history", []) + [
                {"iteration": state.get("iteration", 0), "passed": passed,
                 "n_blocking": len(blocking), "n_warnings": len(warnings)}]}


JEV_FIELD_Q = {
    "mapping_correct": {
        "type": "noul",
        "instructions": "Is this source column -> canonical field mapping semantically right "
                        "AND parsed correctly, judging from the examples?",
        "criteria": {
            "true": "The canonical field's definition fits what the source column holds, and the "
                    "produced values are well-formed instances of it.",
            "false": "The column means something else (e.g. a person's name mapped as a legal "
                     "entity name, a contract date mapped as registration date), or the "
                     "transformed values are malformed, truncated or wrong-kind.",
        },
    },
}


def jev_field_confidence(cfg: dict, metrics: dict, state: dict, warnings: list[str]) -> None:
    from concurrent.futures import ThreadPoolExecutor
    spec = ontology.targets()
    fields = [f for f in cfg.get("fields", []) if metrics["fields"].get(f["target"])]

    def ask(f: dict):
        m = metrics["fields"][f["target"]]
        examples = list(zip(m.get("raw_examples", []), m.get("value_examples", [])))
        st = {"canonical_field": f["target"], "field_definition": spec.get(f["target"], {}),
              "source_columns": f["source_columns"], "transforms": [t["op"] for t in f["transforms"]],
              "condition": f.get("when") or None,
              "raw_to_value_examples": examples or m.get("value_examples", []),
              "transform_fail_rate": m.get("fail_rate"), "fail_examples": m.get("fail_examples", [])[:3]}
        try:
            a = llm.jev_decide(st, JEV_FIELD_Q, tag=_tag(state, "jev_field"), retries=2)["answers"]
            return f, round(a["mapping_correct"]["noul"], 3), None
        except Exception as e:  # noqa: BLE001 - keep the proposer's number, say so
            return f, None, str(e)[:80]

    with ThreadPoolExecutor(6) as ex:
        for f, p, err in ex.map(ask, fields):
            if p is None:
                warnings.append(f"{f['target']}: Jev confidence unavailable ({err})")
                continue
            f["confidence_proposer"] = f.get("confidence_proposer", f["confidence"])
            f["confidence"] = p
            f["confidence_source"] = llm.JEV
            if p < 0.6:
                warnings.append(f"[jev] {f['target']}: P(mapping correct) = {p:.2f} - reviewer should look")


# ---------- 7. review: human (interrupt) or model reviewer ---------------------------------

class ReviewDecision(BaseModel):
    action: Literal["approve", "reject"]
    note: str = Field(description="If reject: precise, actionable instructions for the agent. "
                                  "If approve: what you checked and any residual concerns.")
    concerns: list[str] = Field([], description="Specific problems seen, even when approving.")


REVIEW_PROMPT = """You are the REVIEWER of a mapping config generated by an onboarding agent, standing
in for a senior data engineer. You see exactly what the human reviewer would see. Decide
whether this mapping may go to production.

Approve only if every mapped field is semantically right (not just parseable): a person's
name is not an entity legal name unless the source says the party IS the entity; a trading
name is not a legal name; dates mean what the canonical field means; enum values are right;
rows that are not the entity type claimed are excluded; identifiers go through checksum ops;
placeholders ('NULL', '-') are nulled; nothing is guessed. Metric blocks that are correct
abstentions (e.g. overseas addresses yielding no AU state) may be approved WITH a note.
A field flagged "[jev] ... P(mapping correct) < 0.6" is an independent calibrated signal that
the mapping is wrong: reject with the fix (often: the column belongs to a different canonical
field, e.g. licence.conditions instead of licence.authorisations) unless you can state
precisely why the signal is mistaken.
Reject with concrete instructions when the agent can fix it. You may reject at most twice
per source. On the final round (two rejections already) a further rejection ENDS the run as
failed and nothing is emitted: approve only if the mapping is right, never because the rounds
ran out. A failed run is a correct outcome for a mapping that is still wrong.

Conventions you must respect (they are ontology rules, not the agent's choice):
- entity.legal_name ALWAYS carries the main subject's name, even when the subject is a natural
  person; person.full_name is additive. Never ask for entity.legal_name to be removed.
- related_party.relationship must be one of the enum values below, read as "main subject
  <relationship> related party" (a liquidator is member_of their firm).

Enum targets and their ONLY allowed values (never instruct the agent to emit anything else):
{enums}

Transform ops that exist (never instruct the agent to use any other op):
{ops}

Rejections so far: {n_rejections} of 2.

{review}
"""


def review(state: dict) -> dict:
    if state.get("auto_review"):
        return model_review(state)
    from langgraph.types import interrupt
    decision = interrupt({"slug": state["slug"], "message": "mapping awaits human review"})
    t0 = time.time()
    upd: dict = {"decision": decision}
    if decision.get("action") == "approve":
        upd["status"] = "approved"
    elif decision.get("action") == "reject":
        upd["human_feedback"] = state.get("human_feedback", []) + [decision.get("note", "")]
        upd["status"] = "revising_after_review"
    else:
        upd["status"] = "abandoned"
    upd["steps"] = [{"node": "review", "secs": round(time.time() - t0, 2), "calls": 0, "in": 0,
                     "out": 0, "usd": 0.0}]
    return upd


def model_review(state: dict) -> dict:
    """The approval step performed by a higher-tier model (PRO) instead of a person.
    Recorded as such in provenance; the review text is the same screen a human gets."""
    from .review import render
    t0 = time.time()
    screen = render(state["slug"], state=state, quiet=True)
    n_rej = len(state.get("human_feedback", []))
    enums = "\n".join(f"- {t}: {spec['values']}" for t, spec in ontology.targets().items() if spec.get("values"))
    d = llm.structured(REVIEW_PROMPT.format(n_rejections=n_rej, review=screen[:30000], enums=enums,
                                            ops=transforms.catalogue()),
                       ReviewDecision, model=llm.PRO, tag=_tag(state, "model_review"))
    action = d.action
    decision = {"action": action, "note": d.note, "concerns": d.concerns, "round": n_rej + 1,
                "reviewer": f"model:{llm.PRO}", "at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    upd: dict = {"decision": decision}
    if action == "approve":
        upd["status"] = "approved"
    elif n_rej >= MAX_REVIEW_REJECTIONS:
        # the rounds are a budget for the agent, not a path to approval: a mapping the reviewer still
        # rejects after the last revision fails the run, it is never approved by exhaustion
        upd["human_feedback"] = state.get("human_feedback", []) + [d.note]
        upd["status"] = "failed_review_rejected_after_max_revisions"
        upd["error"] = f"reviewer rejected the mapping on round {n_rej + 1}: {d.note[:300]}"
    else:
        upd["human_feedback"] = state.get("human_feedback", []) + [d.note]
        upd["status"] = "revising_after_review"
    u = llm.usage_since(t0, f"onboard:{state['slug']}:")
    upd["steps"] = [{"node": "review", "secs": round(time.time() - t0, 2), **u}]
    print(f"  [{state['slug'][:40]}] review({llm.PRO.split('-')[1]}) {action}: {d.note[:120]}")
    return upd


# ---------- 8. emit -------------------------------------------------------------------------

@step("emit")
def emit(state: dict) -> dict:
    cfg = dict(state["config"])
    dec = state.get("decision", {})
    cfg["provenance"] = {
        "generated_by": AGENT_VERSION, "model": llm.SMART, "run_thread": state["slug"],
        "iterations": state.get("iteration", 0) + 1,
        "validation": {k: state["validation"][k] for k in ("passed", "blocking", "warnings")},
        "holdout_rows": len(state["holdout_idx"]), "train_rows": len(state["train_idx"]),
        "approved_by": dec.get("reviewer", "unknown"), "approved_at": dec.get("at"),
        "review_note": dec.get("note", ""), "reviewer_concerns": dec.get("concerns", []),
        "human_edits": dec.get("edited", False),
    }
    cfg["extractor_version"] = extractor_version(cfg)
    CONFIGS.mkdir(exist_ok=True)
    path = CONFIGS / f"{state['slug']}.yaml"
    header = (f"# Mapping config for {cfg['source_id']}\n# GENERATED by {AGENT_VERSION} "
              f"and approved at the review step (approver: provenance.approved_by). Do not hand-edit; "
              "re-run onboarding.\n")
    path.write_text(header + yaml.safe_dump(cfg, sort_keys=False, allow_unicode=True, width=100))
    return {"config_path": str(path.relative_to(ROOT)), "status": "done"}


def write_report(state: dict) -> Path:
    """Per-source run report: step count, tokens, cost, wall-clock, iteration history."""
    REPORTS.mkdir(parents=True, exist_ok=True)
    steps = state.get("steps", [])
    llm_steps = [s for s in steps if s.get("calls")]
    rep = {"source_id": state.get("source_id"), "status": state.get("status"),
           "error": state.get("error"), "steps_executed": len(steps),
           "llm_calls": sum(s.get("calls", 0) for s in steps),
           "tokens_in": sum(s.get("in", 0) for s in steps),
           "tokens_out": sum(s.get("out", 0) for s in steps),
           "usd": round(sum(s.get("usd", 0) for s in steps), 4),
           "agent_wall_clock_secs": round(sum(s["secs"] for s in steps if s["node"] != "review"), 1),
           "inspect_attempts": len(state.get("reader_attempts", [])),
           "revisions": state.get("iteration", 0),
           "validation_history": state.get("validation_history", []),
           "changes_log": state.get("changes_log", []), "steps": steps,
           "llm_steps": len(llm_steps), "config_path": state.get("config_path")}
    path = REPORTS / f"{state['slug']}.json"
    path.write_text(json.dumps(rep, indent=2, default=str))
    return path
