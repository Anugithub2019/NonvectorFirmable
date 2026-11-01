"""Streamlit demo: the graph, legible. `uv run streamlit run demo/app.py`

Pages (sidebar): Chat (two modes) | Resolve | Entity | Traversals | Abstentions | Datasets
Everything shown comes from GraphAPI / Agent; nothing is stubbed.

Layout note: the chat lives at the top level of the page, not inside st.tabs. Streamlit pins
st.chat_input to the bottom of the window and auto-scrolls to new messages only when it is a
top-level element; inside a tab it renders inline and drifts down as the history grows.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from firmable.paths import OUTPUTS  # noqa: E402
from firmable.retrieval.agent import Agent  # noqa: E402
from firmable.retrieval.graph_api import GraphAPI  # noqa: E402

st.set_page_config(page_title="Firmable market graph", layout="wide", initial_sidebar_state="expanded")

PAGES = ["Chat", "Resolve", "Entity", "Traversals", "Abstentions", "Datasets"]
EXAMPLES = [
    "Who ultimately owns Commonwealth Bank of Australia?",
    "Does Commonwealth Super Corp hold any licences?",
    "Organisations in QLD with an AFS licence, with ABN and licence number",
    "What is ABN 51 824 753 556?",
]


@st.cache_resource
def _api() -> GraphAPI:
    return GraphAPI()


@st.cache_resource
def _agent() -> Agent:
    return Agent(_api())


api, agent = _api(), _agent()
ss = st.session_state
ss.setdefault("history", [])      # [{role, content, data?, route?, mode?, trace?}] - the agent reads only role/content
ss.setdefault("pending", None)
ss.setdefault("entity_key", None)
ss.setdefault("queued", None)     # a message injected by a button, processed like typed input
ss.setdefault("nav_to", None)     # page requested by a button, applied before the sidebar radio renders
ss.setdefault("page", "Chat")

if ss.nav_to:
    ss.page, ss.nav_to = ss.nav_to, None


def goto(page: str, key: str | None = None) -> None:
    ss.nav_to = page
    if key:
        ss.entity_key = key


def df(rows, **kw) -> None:
    st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True, **kw)


def show_candidates(res: dict, prefix: str = "", selectable: bool = False) -> None:
    st.markdown(f"**decision: `{res['decision']}`** · threshold {res['threshold']} · {res['latency_ms']} ms · normalised `{res['normalised']}`")
    for i, c in enumerate(res["candidates"]):
        col1, col2 = st.columns([5, 1])
        with col1:
            st.markdown(f"**{i + 1}. {c['name']}** · `{c['key']}` · {c.get('state') or ''} {c.get('postcode') or ''} · "
                        f"{c.get('entity_type') or ''} · sources: {', '.join(c.get('sources') or [])}")
            st.caption(f"match_type `{c['match_type']}` · score **{c['score']}** · evidence: {json.dumps(c['evidence'], default=str)}")
        with col2:
            if selectable and st.button(f"use {i + 1}", key=f"{prefix}use_{i}_{c['key']}", help="answer the question with this entity"):
                ss.queued = str(i + 1)
                st.rerun()
            st.button("open", key=f"{prefix}open_{i}_{c['key']}", on_click=goto, args=("Entity", c["key"]))
    with st.expander("paths tried (the queries that found these)"):
        for p in res["paths"]:
            st.code(p, language="cypher")


def show_entity(key: str) -> None:
    e = api.entity(key)
    if not e:
        st.warning(f"no entity {key}")
        return
    p = e["party"]
    st.subheader(p.get("display_name") or key)
    st.markdown(f"`{key}` · ABN {p.get('abn') or '-'} · ACN {p.get('acn') or '-'} · LEI {p.get('lei') or '-'} · "
                f"{p.get('entity_type') or ''} · {p.get('status') or ''} · {p.get('state') or ''} {p.get('postcode') or ''} · "
                f"sources: {', '.join(p.get('sources') or [])}" + (" · ⚠ name conflict between sources" if p.get("name_conflict") else ""))
    for section, label in [("names", "Names (legal / trading / former)"), ("records", "Source records behind this entity"),
                           ("licences", "Licences"), ("bans", "Bans / disqualifications"), ("owners", "Owners"),
                           ("subsidiaries", "Subsidiaries"), ("affiliations", "Affiliations (people ↔ firms)")]:
        sec = e[section]
        if sec["total"]:
            st.markdown(f"**{label}** ({sec['total']}" + (f", showing {len(sec['items'])}, {sec['dropped']} dropped by '{sec['drop_rule']}'" if sec["dropped"] else "") + ")")
            df(sec["items"])
            if section in ("owners", "subsidiaries", "affiliations"):
                cols = st.columns(min(5, max(1, len(sec["items"][:10]))))
                for j, it in enumerate(sec["items"][:10]):
                    if it.get("key"):
                        cols[j % len(cols)].button(f"→ {it.get('name') or it['key']}", key=f"nav_{section}_{it['key']}",
                                                   on_click=goto, args=("Entity", it["key"]))
    with st.expander("query"):
        st.code(e["query"], language="cypher")


def render_assistant(h: dict, idx: int, live: bool) -> None:
    """One assistant message: reply text, routing caption, and the data behind it (table / candidates).
    `live` = this is the newest message, so candidate buttons may act on the pending clarification."""
    st.markdown(h["content"])
    r = h.get("route")
    if r:
        tools = [t["tool"] for t in h.get("trace") or []]
        st.caption(f"routed to **{h.get('mode')}** · intent `{r['intent']}` · P(specific)={r['p_specific']:.2f}"
                   + (f" · tools: {tools}" if tools else ""))
    d = h.get("data")
    if isinstance(d, dict):
        if d.get("rows"):
            df(d["rows"])
        if d.get("candidates"):
            show_candidates(d, prefix=f"m{idx}_", selectable=live and bool(ss.pending) and ss.pending.get("kind") == "clarification")
    if live and ss.pending and ss.pending.get("kind") == "projection":
        if st.button("✅ export this dataset", key=f"export_{idx}"):
            ss.queued = "yes"
            st.rerun()
    if h.get("trace"):
        with st.expander("why: tool calls behind this answer"):
            st.json({"mode": h.get("mode"), "route": r, "trace": h["trace"]}, expanded=False)


# ---------------------------------------------------------------------------------- sidebar
with st.sidebar:
    st.markdown("## Firmable market graph")
    page = st.radio("page", PAGES, key="page", label_visibility="collapsed")
    if page == "Chat":
        st.divider()
        mode = st.radio("mode", ["auto", "intelligent", "retriever"], horizontal=True,
                        help="Intelligent agent answers a specific question. Data retriever builds a flat table you can take away. Auto lets the decision model route.")
        st.markdown("**Try one**")
        for ex in EXAMPLES:
            if st.button(ex, key=f"ex_{ex}", width="stretch"):
                ss.queued = ex
                st.rerun()
        if ss.pending:
            st.info(f"waiting on you: {ss.pending['kind']}" + (f" ({ss.pending.get('halt')})" if ss.pending.get("halt") else ""))
        if ss.history and st.button("clear chat", width="stretch"):
            ss.history, ss.pending, ss.queued = [], None, None
            st.rerun()

# ---------------------------------------------------------------------------------- pages
if page == "Chat":
    st.markdown("### Graph assistant")
    if not ss.history:
        st.caption("Ask about a business (intelligent agent) or describe a dataset you need (data retriever). "
                   "When a name is ambiguous or unmatched the agent stops and shows candidates; pick one with a button or reply with its number.")
    last_assistant = max((i for i, h in enumerate(ss.history) if h["role"] == "assistant"), default=-1)
    for i, h in enumerate(ss.history):
        with st.chat_message(h["role"]):
            if h["role"] == "user":
                st.markdown(h["content"])
            else:
                render_assistant(h, i, live=(i == last_assistant))

    typed = st.chat_input("Ask about a business, or describe a dataset you need")   # top level: pinned + auto-scroll
    msg = typed or ss.queued
    ss.queued = None
    if msg:
        ss.history.append({"role": "user", "content": msg})
        with st.chat_message("user"):
            st.markdown(msg)
        with st.chat_message("assistant"):
            with st.spinner("thinking…"):
                res = agent.turn(msg, None if mode == "auto" else mode, ss.history[:-1], ss.pending)
        ss.pending = res["pending"]
        ss.history.append({"role": "assistant", "content": res["reply"], "data": res.get("data"),
                           "route": res.get("route"), "mode": res.get("mode"), "trace": res.get("trace")})
        st.rerun()   # redraw from history so the new answer renders once, with its buttons wired to the pending state

elif page == "Resolve":
    st.markdown("### resolve(reference)")
    ref = st.text_input("messy reference", placeholder="e.g. commonwealth bank of aust, 51 824 753 556, OVER THE TOP ROOF RESTORATIONS")
    if ref:
        show_candidates(api.resolve(ref), prefix="r_")
    st.caption("Try: `Commonwealth Bank of Australia` then `Commonwealth Superannuation Corporation` — similar names, unrelated entities.")

elif page == "Entity":
    st.markdown("### Entity")
    key = st.text_input("entity key", value=ss.entity_key or "", placeholder="abn:… / acn:… / lei:… / src:…")
    if key:
        ss.entity_key = key
        show_entity(key)

elif page == "Traversals":
    st.markdown("### Traversals only the graph can answer")
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**Ultimate parent** (follows OWNS upward, bounded, cycle-safe)")
        k = st.text_input("entity key for ultimate parent", key="up_key", value=ss.entity_key or "")
        if k:
            r = api.ultimate_parent(k)
            st.json({x: r.get(x) for x in ("ultimate_parent", "terminated_by", "depth", "selection_rule", "chain_kind", "as_of", "latency_ms")})
            df(r["chain"])
            st.code(r["query"], language="cypher")
    with c2:
        st.markdown("**Within N hops** (ownership / affiliation edges; never through shared names)")
        hops = st.slider("hops", 1, 4, 2)
        of_key = st.text_input("of entity key (blank = of any banned party)", key="hops_key")
        r = api.within_hops(hops, of_key or None)
        st.markdown(f"{r['count']} parties · {r['latency_ms']} ms · view `{r.get('view', 'current')}`" + (" · capped" if r.get("capped") else ""))
        if r["count"] == 0 and not of_key:
            st.info("No banned organisation in this slice has recorded ownership or affiliation edges — an honest zero. "
                    "Try a GLEIF-owned company's key to see a non-empty neighbourhood.")
        df(r["results"])
        st.code(r["query"], language="cypher")

elif page == "Abstentions":
    st.markdown("### Abstentions — records we believed were businesses and refused to link")
    p = OUTPUTS / "abstentions.jsonl"
    if not p.exists() and p.with_suffix(".jsonl.gz").exists():
        import gzip
        rows = [json.loads(l) for l in gzip.open(p.with_suffix(".jsonl.gz"), "rt")]
    elif p.exists():
        rows = [json.loads(l) for l in p.read_text().splitlines()]
    else:
        rows = None
    if rows is not None:
        d = pd.DataFrame(rows)
        st.markdown(f"{len(d)} abstentions · by reason: {d['reason'].value_counts().to_dict()}")
        reason = st.selectbox("reason", ["all"] + sorted(d["reason"].unique()))
        view = d if reason == "all" else d[d["reason"] == reason]
        df(view[["source", "record_id", "name", "best_candidate", "best_score", "reason", "evidence"]].head(500))
    else:
        st.info("run `python -m firmable graph resolve` first")

elif page == "Datasets":
    st.markdown("### Datasets produced by Data-retriever mode")
    d = OUTPUTS / "projections"
    specs = sorted(d.glob("*.spec.json"), reverse=True) if d.exists() else []
    if not specs:
        st.info("none yet — ask the chat for a dataset and reply **yes** to export it")
    for sp in specs[:20]:
        meta = json.loads(sp.read_text())
        n = meta.get("exported_count", meta.get("row_count"))
        extra = f" of {meta['matched_count']} matched" if meta.get("truncated") else ""
        with st.expander(f"{sp.name} — {n} rows{extra} · generation {meta.get('generation', '?')} · sha {meta['content_sha1']}"):
            st.json(meta["spec"])
            csv = sp.with_name(sp.name.replace(".spec.json", ".csv"))
            if csv.exists():
                st.download_button("download CSV", csv.read_bytes(), file_name=csv.name, key=sp.name)
