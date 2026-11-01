"""The retrieval agent: two modes on one graph, with the user guided rather than guessed at.

  route        Jev decides what the message wants (answer | dataset | lookup | meta) and whether
               it is specific enough to act on. The UI mode toggle wins; mismatches are surfaced.
  clarify      one grounded question with concrete options (candidates from the graph, columns
               that exist, time windows), never a vague "can you clarify?"
  intelligent  tool loop (Gemini function calling) over the GraphAPI: resolve -> entity ->
               traversals -> read-only Cypher; answers cite keys, source records and match types,
               and say what could not be determined.
  retriever    natural language -> typed ProjectionSpec (validated against real columns; invalid
               specs are rejected, never silently narrowed) -> preview + counts + restatement
               generated FROM the validated spec -> user confirms -> CSV/Parquet + spec file.

What the code enforces (not the prompt):
  * An `ambiguous` or `abstained` resolve HALTS the tool loop. The reply is composed by code, lists
    the candidates, and the turn ends in a clarification state. The model cannot pick.
  * Typed entity tools (`entity`, `ultimate_parent`, `within_hops(of_key)`) accept only keys that
    were resolved, chosen by the user, or returned by an earlier allowed tool call. Keys the model
    invents, keys from ambiguous candidate lists, and keys read via `read_cypher` are refused.
  * `read_cypher` is refused for name-predicate queries until something has been resolved, so it
    cannot be used to bypass resolution; its rows never unlock typed tools.
  * The budget counts real tool calls and wall-clock seconds, not loop iterations.

Every turn returns a `trace` of tool calls so the demo can show why the agent did what it did.
"""
from __future__ import annotations

import json
import re
import time
from typing import Any, Literal

from google.genai import types
from pydantic import BaseModel, Field
from rapidfuzz.distance import JaroWinkler

from .. import llm
from .graph_api import GraphAPI

MAX_TOOL_CALLS = 8      # real tool invocations per turn (several may happen in one model step)
MAX_TURN_SECONDS = 90   # wall-clock budget for the tool loop
CLARIFY_BELOW = 0.30    # ask only when the decision model is fairly sure the request cannot be acted on
GATED_TOOLS = ("entity", "ultimate_parent", "within_hops")
_NAME_PREDICATE = re.compile(r"(display_name|\.text|normalised)\s*(=|<>|CONTAINS|STARTS\s+WITH|ENDS\s+WITH|=~)", re.I)

ROUTE_Q = {
    "intent": {
        "type": "choice",
        "instructions": "What does the user want from an assistant over a graph of Australian businesses "
                        "(organisations, people, licences, bans, ownership)?",
        "criteria": {
            "answer": "A specific question or fact about particular entities: who owns X, is X banned, what "
                      "licences does X hold, which companies are near a banned party, compare two entities.",
            "dataset": "A list, table, export, extract or projection of MANY entities matching criteria, to take "
                       "away and use elsewhere.",
            "lookup": "To identify or disambiguate one entity from a messy reference (a name, ABN, ACN, LEI).",
            "meta": "Help, capabilities, small talk, confirmation/approval of a previous proposal, or a "
                    "question about the data itself.",
        },
    },
    "specific": {
        "type": "noul",
        "instructions": "Can the assistant act on this request now, using sensible defaults, without first asking "
                        "the user a question? Asking is only justified when the answer would materially change "
                        "depending on the user's reply.",
        "criteria": {
            "true": "A named entity, identifier or clear criteria are given; any missing detail has an obvious "
                    "default (e.g. 'currently', 'all states', 'any licence type') that can simply be stated in the "
                    "answer. Yes/no questions about a named entity are always specific.",
            "false": "No entity or criteria can be identified at all (e.g. 'tell me about Smith', 'give me some "
                     "companies'), or two readings would produce different datasets and neither is a reasonable "
                     "default.",
        },
    },
}


class Clarification(BaseModel):
    question: str = Field(description="One short question, grounded in what the graph holds.")
    options: list[str] = Field(description="2-4 concrete choices the user can pick; last may be 'something else'.")
    why: str = Field(description="One sentence: what would differ depending on the answer.")


class ProjectionFilter(BaseModel):
    column: str
    op: Literal["=", "!=", ">", "<", ">=", "<=", "contains", "in", "is_null", "not_null", "within_days"]
    value: str | int | float | list[str] | None = None


class GraphFilter(BaseModel):
    kind: Literal["within_hops_of_ban", "within_hops_of_key", "has_owner", "has_subsidiary"]
    hops: int = 2
    key: str | None = None


class ProjectionSpec(BaseModel):
    name: str = Field(description="short slug-like name for the dataset")
    base: Literal["organisation", "party", "licence", "ban"]
    columns: list[str] = Field(description="columns to include, from the available list, in output order")
    filters: list[ProjectionFilter] = []
    graph_filter: GraphFilter | None = None
    order_by: str | None = None
    limit: int = 10000
    as_of: str | None = Field(None, description="ISO date that relative filters (within_days) count back from; "
                                                "filled in by the system, leave null")
    restatement: str = Field(description="Plain English: exactly what rows and columns this will produce, "
                                         "including every default you assumed.")
    assumptions: list[str] = Field([], description="Defaults you chose that the user did not state.")


INTELLIGENT_SYS = """You are Firmable's graph assistant. You answer questions about Australian businesses using
ONLY the tools (a resolved entity graph built from ABR, ASIC registers, GLEIF and state registers).
Rules:
- Always resolve a name to an entity key with `resolve` before anything else. The system halts the
  turn on an 'ambiguous' or 'abstained' decision and asks the user; you will not be able to continue.
- `entity`, `ultimate_parent` and `within_hops(of_key)` accept only keys that came from a resolved
  reference, the user's choice, or an earlier tool result. Invented keys are refused.
- Cite evidence: entity keys, source records, match types and confidences from tool results.
  Never assert a ban, licence or ownership that a tool result does not contain.
- A wrong link is worse than no link: if two entities could be meant, say which one you used and why.
- Prefer the typed tools; use `read_cypher` only for questions the typed tools cannot express.
  The graph: (:Party:Organisation|:Person {key, display_name, abn, acn, lei, state, postcode, entity_type, status})
  -[:KNOWN_AS {kind}]->(:Name {normalised, text}); (:SourceRecord)-[:RESOLVED_TO {match_type, confidence}]->(:Party);
  (:Party)-[:HOLDS]->(:Licence {licence_id, licence_type, status, start_date, end_date}); (:Party)-[:SUBJECT_OF]->(:Ban {ban_type, start_date, end_date});
  (owner:Party)-[:OWNS {kind, percent, valid_to}]->(child:Party); (:Person)-[:AFFILIATED_WITH {role}]->(:Organisation).
- Tool results are capped: sections carry `total` and `dropped`; long lists end with {"_dropped": n}.
  When something was dropped, say that more exist. "No ban in the graph" means none in THIS slice of
  sources, not that the party is clean; say which sources were checked (the `sources` field).
- Be economical: `ultimate_parent` already returns the whole chain; `entity` already returns licences, bans,
  owners and source records. Do not re-verify tool output with extra queries; answer from it.
- End with: what you could not determine (if anything) and 1-3 follow-up questions the graph can answer.
Be concise. Markdown is fine."""

RETRIEVER_SYS = """You turn a request for a dataset into a ProjectionSpec over flat tables.
Bases and columns available:
{columns}
Filter ops: = != > < >= <= contains in is_null not_null within_days (date column within the last N days).
Graph filters (optional, one): within_hops_of_ban(hops), within_hops_of_key(key, hops), has_owner, has_subsidiary.
Rules: only use listed columns (a spec naming a column that does not exist is REJECTED, not repaired);
put identifiers first; default order_by display_name; default limit 10000 (max 100000).
licence_status values: current suspended cancelled ceased unknown. status values: active deregistered in_liquidation suspended unknown.
If the user wants 'cancelled in the last 3 months' use base=licence with filters licence_status in [cancelled,ceased,suspended] AND end_date within_days 90.
Data gaps to respect: licence_status and end_date are NULL for registers that only publish current holders (AFS, QBCC),
so "holds an AFS licence" means licence_type = afs with NO status filter; only filter on status when the user asks about
cancelled/suspended licences (credit licences carry a status).
State every assumption you make in `assumptions`."""


def _tools() -> list[types.Tool]:
    fd = types.FunctionDeclaration
    return [types.Tool(function_declarations=[
        fd(name="resolve", description="Messy reference (name / ABN / ACN / LEI) -> ranked candidate entities with match type, score, evidence. Decision: resolved | ambiguous | abstained (the latter two end the turn and ask the user).",
           parameters={"type": "object", "properties": {"reference": {"type": "string"}}, "required": ["reference"]}),
        fd(name="entity", description="Full profile of a RESOLVED entity by key: identifiers, names, source records, licences, bans, owners, subsidiaries, affiliations (capped at 25 per section).",
           parameters={"type": "object", "properties": {"key": {"type": "string"}}, "required": ["key"]}),
        fd(name="ultimate_parent", description="Follow ownership upwards from a resolved entity key to its ultimate parent; reports cycles and depth.",
           parameters={"type": "object", "properties": {"key": {"type": "string"}}, "required": ["key"]}),
        fd(name="within_hops", description="Parties within N hops (ownership/affiliation edges) of any banned party, or of a given resolved entity key.",
           parameters={"type": "object", "properties": {"hops": {"type": "integer"}, "of_key": {"type": "string"}}, "required": ["hops"]}),
        fd(name="read_cypher", description="Run a READ-ONLY Cypher query (row-capped, timed) for questions the other tools cannot express. Its rows do not unlock the typed tools.",
           parameters={"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}),
        fd(name="schema_summary", description="Node labels and relationship types with counts.",
           parameters={"type": "object", "properties": {}}),
    ])]


class Agent:
    def __init__(self, api: GraphAPI):
        self.api = api
        self._columns: dict[str, list[str]] | None = None

    # ------------------------------------------------------------------ routing
    def route(self, message: str, ui_mode: str | None, history: list[dict], pending: dict | None) -> dict:
        state = {"user_message": message, "ui_mode": ui_mode or "auto",
                 "pending_clarification": bool(pending), "pending_kind": (pending or {}).get("kind"),
                 "recent_turns": [h["content"][:300] for h in history[-4:]]}
        try:
            a = llm.jev_decide(state, ROUTE_Q, tag="agent:route", retries=2)["answers"]
            intent, p_specific = a["intent"]["choice"], float(a["specific"]["noul"])
            probs = a["intent"].get("probabilities", {})
        except Exception as e:  # noqa: BLE001 - fall back to the UI mode
            intent, p_specific, probs = ("dataset" if ui_mode == "retriever" else "answer"), 1.0, {"error": str(e)[:60]}
        mode = ui_mode
        if ui_mode in (None, "auto"):
            mode = "retriever" if intent == "dataset" else "intelligent"
        mismatch = None
        if ui_mode == "intelligent" and intent == "dataset" and probs.get("dataset", 0) > 0.7:
            mismatch = "This looks like a request for a dataset; switch to Data retriever mode to export it as a table."
        if ui_mode == "retriever" and intent == "answer" and probs.get("answer", 0) > 0.7:
            mismatch = "This looks like a specific question; Intelligent agent mode would answer it directly."
        return {"intent": intent, "p_specific": p_specific, "mode": mode, "mismatch": mismatch, "probs": probs}

    def clarify(self, message: str, route: dict, candidates: list[dict] | None = None) -> Clarification:
        ctx = {"message": message, "intent": route["intent"], "mode": route["mode"],
               "graph_has": "organisations, people, legal/trading/former names, ABN/ACN/LEI, licences (afs, credit, building, environmental) with status and dates, bans with dates, ownership (GLEIF), affiliations (liquidators-firms)",
               "projection_columns": self.columns() if route["mode"] == "retriever" else None,
               "candidates": candidates}
        return llm.structured("Write one clarifying question for this request. Ground the options in what exists.\n"
                              + json.dumps(ctx, default=str)[:6000], Clarification, model=llm.SMART, tag="agent:clarify")

    # ------------------------------------------------------------------ intelligent mode
    def intelligent(self, message: str, history: list[dict], selected_keys: list[str] | None = None) -> dict:
        """Tool loop. Returns {answer, trace, halt, budget}. `halt` is set when a resolve came back
        ambiguous/abstained: the loop stopped there and `answer` was written by code, not the model."""
        trace: list[dict] = []
        allowed: set[str] = set(selected_keys or [])
        budget = {"calls": 0, "max_calls": MAX_TOOL_CALLS, "max_seconds": MAX_TURN_SECONDS, "exhausted": None}
        t0 = time.time()
        contents = [types.Content(role=("user" if h["role"] == "user" else "model"), parts=[types.Part(text=h["content"])])
                    for h in history[-6:]]
        contents.append(types.Content(role="user", parts=[types.Part(text=message)]))
        cfg = types.GenerateContentConfig(tools=_tools(), system_instruction=INTELLIGENT_SYS, temperature=0.1,
                                          automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True))
        while True:
            resp = llm.generate(contents, cfg, tag="agent:intelligent")
            cand = resp.candidates[0].content
            contents.append(cand)
            calls = [p.function_call for p in cand.parts if p.function_call]
            if not calls:
                text = "".join(p.text or "" for p in cand.parts)
                budget["seconds"] = round(time.time() - t0, 1)
                return {"answer": text, "trace": trace, "halt": None, "budget": budget, "allowed_keys": sorted(allowed)}
            parts = []
            for fc in calls:
                args = dict(fc.args or {})
                if budget["calls"] >= MAX_TOOL_CALLS:
                    budget["exhausted"] = "calls"
                    result = {"error": f"tool budget of {MAX_TOOL_CALLS} calls exhausted"}
                elif time.time() - t0 > MAX_TURN_SECONDS:
                    budget["exhausted"] = "seconds"
                    result = {"error": f"time budget of {MAX_TURN_SECONDS}s exhausted"}
                else:
                    budget["calls"] += 1
                    result = self._call(fc.name, args, allowed)
                trace.append({"tool": fc.name, "args": args, "result": _shrink(result),
                              "gated": result.get("gate") if isinstance(result, dict) else None})
                if fc.name == "resolve" and isinstance(result, dict) and "decision" in result:
                    if result["decision"] == "resolved":
                        allowed.add(result["candidates"][0]["key"])
                    else:
                        # enforced state transition: the turn ends here, the model does not get to continue
                        halt = {"kind": result["decision"], "resolve": result}
                        budget["seconds"] = round(time.time() - t0, 1)
                        return {"answer": _halt_text(halt), "trace": trace, "halt": halt, "budget": budget,
                                "allowed_keys": sorted(allowed)}
                elif fc.name != "read_cypher" and isinstance(result, dict) and "error" not in result:
                    allowed |= _keys_in(result)
                parts.append(types.Part.from_function_response(name=fc.name, response={"result": _shrink(result, 12000)}))
            contents.append(types.Content(role="user", parts=parts))
            if budget["exhausted"]:
                break
        # budget exhausted: one last call with tools disabled forces a summary of what was found
        contents.append(types.Content(role="user", parts=[types.Part(text=
            "Tool budget exhausted. Answer now from the tool results above: state what was established, cite keys "
            "and match types, and list what could not be determined.")]))
        final = llm.generate(contents, types.GenerateContentConfig(system_instruction=INTELLIGENT_SYS, temperature=0.1),
                             tag="agent:intelligent")
        budget["seconds"] = round(time.time() - t0, 1)
        return {"answer": "".join(p.text or "" for p in final.candidates[0].content.parts), "trace": trace,
                "halt": None, "budget": budget, "allowed_keys": sorted(allowed)}

    def _call(self, name: str, args: dict, allowed: set[str]) -> Any:
        """Execute one tool call under the key gate. `allowed` is the set of entity keys this turn may
        touch with the typed tools; it is grown only by resolved references and allowed tool results."""
        try:
            if name in GATED_TOOLS:
                key = args.get("key") if name != "within_hops" else args.get("of_key")
                if key and key not in allowed:
                    return {"error": f"key {key!r} is not a resolved or user-selected entity in this turn; "
                                     "call resolve(reference) first (or the user must choose a candidate)",
                            "gate": "unresolved_key"}
            if name == "resolve":
                return self.api.resolve(args["reference"])
            if name == "entity":
                return self.api.entity(args["key"]) or {"error": f"no entity with key {args['key']}"}
            if name == "ultimate_parent":
                return self.api.ultimate_parent(args["key"])
            if name == "within_hops":
                return self.api.within_hops(int(args.get("hops", 2)), args.get("of_key"))
            if name == "read_cypher":
                if not allowed and _NAME_PREDICATE.search(args["query"]):
                    return {"error": "refused: looking entities up by name must go through resolve(reference)",
                            "gate": "name_predicate_before_resolve"}
                return self.api.read_cypher(args["query"])
            if name == "schema_summary":
                return self.api.schema_summary()
        except Exception as e:  # noqa: BLE001
            return {"error": f"{type(e).__name__}: {str(e)[:200]}"}
        return {"error": f"unknown tool {name}"}

    # ------------------------------------------------------------------ retriever mode
    def columns(self) -> dict[str, list[str]]:
        if self._columns is None:
            self._columns = {b: self.api.projection_columns(b) for b in self.api.PROJECTION_BASES}
        return self._columns

    def retriever_spec(self, message: str, history: list[dict], previous: dict | None) -> tuple[ProjectionSpec, list[str]]:
        """Request -> validated ProjectionSpec. An invalid spec gets ONE repair round with the problems
        spelled out; if it is still invalid the problems are returned and nothing is previewed. The
        restatement is regenerated from the validated spec, so it cannot describe something else."""
        cols = "\n".join(f"- {b}: {', '.join(c)}" for b, c in self.columns().items())
        prompt = RETRIEVER_SYS.format(columns=cols) + "\n\nConversation:\n" + \
            "\n".join(f"{h['role']}: {h['content'][:500]}" for h in history[-6:]) + \
            (f"\n\nPrevious spec (the user may be adjusting it):\n{json.dumps(previous)}" if previous else "") + \
            f"\n\nRequest: {message}"
        spec = llm.structured(prompt, ProjectionSpec, model=llm.SMART, tag="agent:retriever")
        problems = self.api.validate_projection(spec.model_dump())
        if problems:
            repair = prompt + "\n\nYour previous spec was rejected:\n- " + "\n- ".join(problems) + \
                "\n\nPrevious spec:\n" + json.dumps(spec.model_dump()) + "\nProduce a corrected spec using only listed columns."
            spec = llm.structured(repair, ProjectionSpec, model=llm.SMART, tag="agent:retriever:repair")
            problems = self.api.validate_projection(spec.model_dump())
        if not problems:
            spec.restatement = restate(spec)
        return spec, problems

    def retriever_preview(self, spec: ProjectionSpec) -> dict:
        return self.api.projection(spec.model_dump(), preview=True)

    def retriever_export(self, spec: ProjectionSpec) -> dict:
        return self.api.projection(spec.model_dump(), preview=False)

    # ------------------------------------------------------------------ one turn
    def turn(self, message: str, ui_mode: str | None, history: list[dict], pending: dict | None) -> dict:
        """Returns {reply, mode, route, trace, pending, data}. `pending` carries a clarification or an
        unconfirmed projection into the next turn."""
        msg = message.strip()
        # confirmation of a pending projection
        if pending and pending.get("kind") == "projection" and re.fullmatch(r"(yes|y|ok|okay|confirm|export|go|do it|looks good)[.! ]*", msg.lower()):
            spec = ProjectionSpec(**pending["spec"])
            res = self.retriever_export(spec)
            if "error" in res:
                return {"reply": f"Export failed: {res['error']}", "mode": "retriever", "route": None, "trace": [], "pending": None, "data": res}
            reply = (f"Exported **{res['exported_count']} rows** to `{res['csv']}` (and Parquet)."
                     + (f" **{res['matched_count']} rows matched; the export was cut at the limit of {res['export_limit']}.**"
                        if res["truncated"] else f" All {res['matched_count']} matching rows are included.")
                     + f" Spec saved to `{res['spec_file']}` (data generation `{res['generation']}`, as_of {res['spec']['as_of']}, "
                       f"content hash `{res['content_sha1']}`) - re-run it on this generation for the same table.")
            return {"reply": reply, "mode": "retriever", "route": None, "trace": [{"tool": "projection", "args": spec.model_dump(), "result": _shrink(res)}],
                    "pending": None, "data": res}
        # the user picked a candidate after an ambiguous/abstained resolve: that key is now allowed, no re-resolve
        if pending and pending.get("kind") == "clarification" and pending.get("candidates"):
            sel = select_candidate(msg, pending)
            if sel is not None:
                key, name = sel["key"], sel["name"]
                note = ("(The user chose entity key {k} ({n}) for '{r}'; use that key directly with the typed tools, "
                        "do not resolve it again.)").format(k=key, n=name, r=pending.get("reference", ""))
                res = self.intelligent(f"{pending['original']}\n{note}", history, selected_keys=[key])
                res["trace"].insert(0, {"tool": "user_selected", "args": {"key": key, "after": pending.get("halt")}, "result": {"name": name}})
                return self._intelligent_reply(res, "intelligent", None, pending["original"])
        route = self.route(msg, ui_mode, history, pending)
        mode = route["mode"]
        if pending and pending.get("kind") == "clarification":
            msg = f"{pending['question']} -> user answered: {msg}\n(original request: {pending['original']})"
        if route["p_specific"] < CLARIFY_BELOW and not (pending and pending.get("kind") == "clarification"):
            c = self.clarify(msg, route)
            reply = f"{c.question}\n\n" + "\n".join(f"- {o}" for o in c.options) + f"\n\n_{c.why}_"
            return {"reply": reply, "mode": mode, "route": route, "trace": [],
                    "pending": {"kind": "clarification", "question": c.question, "original": msg}, "data": None}
        if mode == "retriever":
            prev = pending["spec"] if pending and pending.get("kind") == "projection" else None
            spec, problems = self.retriever_spec(msg, history, prev)
            if problems:
                reply = ("I could not build an executable dataset spec for that, and I will not guess:\n- "
                         + "\n- ".join(problems) + "\n\nAvailable columns: "
                         + "; ".join(f"{b}: {', '.join(c)}" for b, c in self.columns().items())
                         + "\n\nTell me which columns or filters to use.")
                return {"reply": reply, "mode": mode, "route": route, "trace": [{"tool": "projection.validate", "args": spec.model_dump(), "result": {"problems": problems}}],
                        "pending": None, "data": {"problems": problems, "spec": spec.model_dump()}}
            pv = self.retriever_preview(spec)
            if "error" in pv:
                return {"reply": f"I could not build that projection: {pv['error']}", "mode": mode, "route": route, "trace": [], "pending": None, "data": pv}
            spec.as_of = pv["spec"]["as_of"]   # pin the date the preview used so the export reproduces it
            lines = [f"**Proposed dataset: {spec.name}** - {spec.restatement}"]
            if pv["matched_count"] == 0 and spec.filters:
                # guide the user: which filter emptied the result?
                diag = []
                for i, f in enumerate(spec.filters):
                    trial = spec.model_dump(); trial["filters"] = [x.model_dump() for j, x in enumerate(spec.filters) if j != i]
                    n = self.api.projection(trial, preview=True).get("matched_count", 0)
                    diag.append(f"without `{f.column} {f.op} {f.value}` → {n} rows")
                lines.append("No rows match. Dropping one filter at a time: " + "; ".join(diag) + ". Tell me which to relax.")
            if spec.assumptions:
                lines.append("Assumptions: " + "; ".join(spec.assumptions))
            count_line = f"**{pv['matched_count']} rows match**; export limit {pv['export_limit']}, so the file will hold " \
                         f"**{min(pv['matched_count'], pv['export_limit'])} rows**"
            if pv["matched_count"] > pv["export_limit"]:
                count_line += " (truncated - raise the limit if you want them all)"
            lines.append(count_line + f". Columns: {', '.join(pv['columns'])}. Preview shows the first {pv['preview_rows']}.")
            lines.append("Reply **yes** to export (CSV + Parquet + re-runnable spec), or tell me what to change.")
            reply = "\n\n".join(lines) + (("\n\n" + route["mismatch"]) if route["mismatch"] else "")
            return {"reply": reply, "mode": mode, "route": route, "trace": [{"tool": "projection.preview", "args": spec.model_dump(), "result": _shrink(pv)}],
                    "pending": {"kind": "projection", "spec": spec.model_dump()}, "data": pv}
        res = self.intelligent(msg, history)
        return self._intelligent_reply(res, mode, route, msg)

    def _intelligent_reply(self, res: dict, mode: str, route: dict | None, original: str) -> dict:
        reply, pend, data = res["answer"], None, None
        if res["halt"]:
            r = res["halt"]["resolve"]
            pend = {"kind": "clarification", "question": "Which entity did you mean?", "original": original,
                    "reference": r["reference"], "halt": res["halt"]["kind"],
                    "candidates": [c["key"] for c in r["candidates"]],
                    "candidate_names": [c["name"] for c in r["candidates"]]}
            data = r
        if route and route.get("mismatch"):
            reply += "\n\n" + route["mismatch"]
        return {"reply": reply, "mode": mode, "route": route, "trace": res["trace"], "pending": pend, "data": data,
                "budget": res.get("budget")}


# ---------------------------------------------------------------------- deterministic text
def _halt_text(halt: dict) -> str:
    """Reply for an ambiguous/abstained resolve, written by code so nothing can be asserted."""
    r = halt["resolve"]
    rows = []
    for i, c in enumerate(r["candidates"], 1):
        ids = " ".join(f"{k.upper()} {c['evidence'][k]}" for k in ("abn", "acn", "lei") if c.get("evidence", {}).get(k))
        rows.append(f"{i}. **{c['name']}** · `{c['key']}` · {c.get('state') or '?'} {c.get('postcode') or ''} · "
                    f"{c.get('entity_type') or ''} · {c['match_type']} {c['score']}" + (f" · {ids}" if ids else ""))
    if halt["kind"] == "ambiguous":
        head = (f"'{r['reference']}' matches more than one entity above the threshold ({r['threshold']}), and I will "
                f"not pick one for you. Which did you mean?")
        tail = "Reply with a number, or give an ABN/ACN."
    else:
        best = r["candidates"][0]["score"] if r["candidates"] else 0.0
        head = (f"I could not confidently match '{r['reference']}' to an entity in the graph "
                f"(best score {best} < threshold {r['threshold']}).")
        tail = ("Nearest candidates, **not matched**. Reply with a number to use one anyway (this will be recorded as "
                "your choice), or give an ABN/ACN." if r["candidates"] else
                "No candidate came close. Try an ABN/ACN, or a different spelling.")
    return "\n\n".join([head, "\n".join(rows), tail] if rows else [head, tail])


def select_candidate(msg: str, pending: dict) -> dict | None:
    """Map the user's reply to one pending candidate: an index ('2'), a key, or a close name. None if
    the reply is not a selection (then it is treated as a new request)."""
    keys, names = pending.get("candidates") or [], pending.get("candidate_names") or []
    m = re.fullmatch(r"\s*(?:option\s*|number\s*|#)?(\d{1,2})\s*[.)]?\s*", msg, flags=re.I)
    if m and 1 <= int(m.group(1)) <= len(keys):
        i = int(m.group(1)) - 1
        return {"key": keys[i], "name": names[i] if i < len(names) else keys[i]}
    for i, k in enumerate(keys):
        if k in msg:
            return {"key": k, "name": names[i] if i < len(names) else k}
    best = max(((JaroWinkler.similarity(msg.upper(), (n or "").upper()), i) for i, n in enumerate(names)), default=(0, -1))
    if best[0] >= 0.92:
        return {"key": keys[best[1]], "name": names[best[1]]}
    return None


def restate(spec: ProjectionSpec) -> str:
    """Plain-English description generated FROM the validated spec (not from the model's intent)."""
    base = {"organisation": "organisations", "party": "parties (organisations and people)",
            "licence": "licence holdings (one row per licence record)", "ban": "bans (one row per ban record)"}[spec.base]
    conds = []
    for f in spec.filters:
        if f.op == "within_days":
            conds.append(f"{f.column} within the last {f.value} days before {spec.as_of or 'today'}")
        elif f.op in ("is_null", "not_null"):
            conds.append(f"{f.column} is {'empty' if f.op == 'is_null' else 'present'}")
        elif f.op == "in":
            conds.append(f"{f.column} is one of {f.value}")
        elif f.op == "contains":
            conds.append(f"{f.column} contains '{f.value}'")
        else:
            conds.append(f"{f.column} {f.op} {f.value!r}")
    if spec.graph_filter:
        g = spec.graph_filter
        conds.append({"within_hops_of_ban": f"within {g.hops} ownership/affiliation hops of a banned party",
                      "within_hops_of_key": f"within {g.hops} hops of entity {g.key}",
                      "has_owner": "has a declared owner", "has_subsidiary": "has a declared subsidiary"}[g.kind])
    s = f"All {base}" + (" where " + " AND ".join(conds) if conds else "") + "."
    s += f" Columns: {', '.join(spec.columns)}. Ordered by {spec.order_by or spec.columns[0]} (ties broken by key)."
    s += f" At most {spec.limit} rows."
    return s


def _keys_in(obj: Any) -> set[str]:
    """Entity keys that appear in an allowed tool result (so the model can follow edges it was shown)."""
    out: set[str] = set()
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in ("key", "ultimate_parent") and isinstance(v, str):
                out.add(v)
            else:
                out |= _keys_in(v)
    elif isinstance(obj, list):
        for v in obj:
            out |= _keys_in(v)
    return out


def _cap(x: Any, cap: int) -> Any:
    if isinstance(x, list):
        return [_cap(i, cap) for i in x[:cap]] + ([{"_dropped": len(x) - cap}] if len(x) > cap else [])
    if isinstance(x, dict):
        return {k: _cap(v, cap) for k, v in x.items()}
    if isinstance(x, str) and len(x) > 600:
        return x[:600] + "…"
    return x


def _shrink(obj: Any, limit: int = 4000) -> Any:
    """Keep tool results inside the context budget by shortening LISTS (with an explicit {_dropped: n}
    marker) rather than cutting JSON mid-field; counts, keys and provenance fields survive."""
    s = json.dumps(obj, default=str)
    if len(s) <= limit:
        return obj
    for cap in (10, 5, 2, 1):
        o = _cap(obj, cap)
        s = json.dumps(o, default=str)
        if len(s) <= limit:
            return o
    return {"truncated_json": s[:limit], "note": f"result was {len(s)} chars even after list capping"}
