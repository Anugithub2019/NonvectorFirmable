"""Terminal chat: `python -m firmable chat [--mode intelligent|retriever|auto]`."""
from __future__ import annotations

import json

from rich.console import Console
from rich.markdown import Markdown

from .agent import Agent
from .graph_api import GraphAPI


def repl(mode: str = "auto") -> None:
    con = Console()
    api = GraphAPI()
    agent = Agent(api)
    history: list[dict] = []
    pending: dict | None = None
    con.print(f"[bold]Firmable graph assistant[/] mode={mode}. Commands: /mode <intelligent|retriever|auto>, /trace, /quit")
    last_trace: list = []
    while True:
        try:
            msg = con.input("[cyan]you>[/] ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not msg:
            continue
        if msg.startswith("/mode"):
            mode = msg.split(maxsplit=1)[1] if " " in msg else "auto"
            con.print(f"mode = {mode}")
            continue
        if msg == "/trace":
            con.print(json.dumps(last_trace, indent=1, default=str)[:6000])
            continue
        if msg in ("/quit", "/exit"):
            break
        res = agent.turn(msg, None if mode == "auto" else mode, history, pending)
        pending, last_trace = res["pending"], res["trace"]
        tag = f"[{res['mode']}" + (f" | intent={res['route']['intent']} specific={res['route']['p_specific']:.2f}" if res.get("route") else "") + "]"
        con.print(f"[dim]{tag} tools: {[t['tool'] for t in res['trace']]}[/]")
        con.print(Markdown(res["reply"]))
        history += [{"role": "user", "content": msg}, {"role": "assistant", "content": res["reply"]}]
    api.close()
