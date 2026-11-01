"""Thin Gemini wrapper: structured output + a usage ledger.

Every call is appended to output/usage.jsonl with token counts and an estimated
cost, so the write-up can report real spend per source and per step.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import TypeVar

from dotenv import load_dotenv
from google import genai
from pydantic import BaseModel

from .paths import OUTPUTS, ROOT

load_dotenv(ROOT / ".env")

# USD per 1M tokens. Source: third-party aggregators (anotherwrapper.com,
# pricepertoken.com), Oct 2026 — NOT verified against Google's rate sheet.
# Thinking tokens are billed as output.
PRICES = {
    "gemini-3.5-flash": {"in": 1.50, "out": 9.00},
    "gemini-3.5-flash-lite": {"in": 0.30, "out": 2.50},
    # Aggregators (pricepertoken.com, verdent.ai, Oct 2026): $2 / $12 under 200k context.
    "gemini-3.1-pro-preview": {"in": 2.00, "out": 12.00},
    # OpenRouter list price (openrouter.ai/api/v1/models, Oct 2026); OpenRouter also returns
    # the billed cost per call, which is preferred when present.
    "anthropic/claude-sonnet-5.5": {"in": 2.00, "out": 10.00},
}
JUDGE = os.environ.get("FIRMABLE_JUDGE_MODEL", "anthropic/claude-sonnet-5.5")
SMART = os.environ.get("FIRMABLE_SMART_MODEL", "gemini-3.5-flash")
CHEAP = os.environ.get("FIRMABLE_CHEAP_MODEL", "gemini-3.5-flash-lite")
# Higher-tier model used only where an independent, stronger judgement is wanted:
# the mapping reviewer (stands in for the human approver) and link labelling.
PRO = os.environ.get("FIRMABLE_PRO_MODEL", "gemini-3.1-pro-preview")

LEDGER = OUTPUTS / "usage.jsonl"

T = TypeVar("T", bound=BaseModel)
_client: genai.Client | None = None


def client() -> genai.Client:
    global _client
    if _client is None:
        _client = genai.Client(api_key=os.environ["GOOGLE_API_KEY"])
    return _client


def structured(prompt: str, schema: type[T], *, model: str = SMART, tag: str = "",
               retries: int = 3) -> T:
    """Call the model and parse the response into `schema`. Retries on transient errors."""
    last: Exception | None = None
    for attempt in range(retries):
        t0 = time.time()
        try:
            resp = client().models.generate_content(
                model=model,
                contents=prompt,
                # Output cap: unbounded thinking on revise prompts ran past the server's
                # connection limit ("Server disconnected") — the cap keeps calls < ~60s.
                config={"response_mime_type": "application/json", "response_schema": schema,
                        "temperature": 0.2, "max_output_tokens": 24000,
                        "http_options": {"timeout": 240_000}},
            )
            parsed = resp.parsed
            if parsed is None:  # schema mismatch: fall back to manual parse for a clearer error
                parsed = schema.model_validate(json.loads(resp.text))
            _record(model, tag, resp.usage_metadata, time.time() - t0)
            return parsed
        except Exception as e:  # noqa: BLE001 - network/quota/parse errors all retry
            last = e
            time.sleep(5 * 3 ** attempt)  # 5s, 15s, 45s
    raise RuntimeError(f"LLM call failed after {retries} attempts ({tag}): {last}")


def openrouter_json(prompt: str, schema: type[T], *, model: str, tag: str = "",
                    retries: int = 3) -> T:
    """Call a non-Gemini model via OpenRouter (OpenAI-compatible) and parse JSON into `schema`.
    Used where an INDEPENDENT model family is wanted, e.g. the shortlist judge."""
    import httpx
    last: Exception | None = None
    for attempt in range(retries):
        t0 = time.time()
        try:
            r = httpx.post(
                "https://openrouter.ai/api/v1/chat/completions", timeout=180,
                headers={"Authorization": f"Bearer {os.environ['OPENROUTER_API_KEY']}"},
                json={"model": model, "temperature": 0, "max_tokens": 4000,
                      "messages": [{"role": "user", "content": prompt + "\n\nRespond with ONLY a "
                                    "JSON object matching this JSON schema:\n"
                                    + json.dumps(schema.model_json_schema())}]})
            r.raise_for_status()
            body = r.json()
            text = body["choices"][0]["message"]["content"].strip()
            text = text[text.find("{"): text.rfind("}") + 1]
            parsed = schema.model_validate_json(text)
            u = body.get("usage", {})
            _record_raw(model, tag, u.get("prompt_tokens", 0), u.get("completion_tokens", 0),
                        time.time() - t0, u.get("cost"))
            return parsed
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(5 * 3 ** attempt)
    raise RuntimeError(f"OpenRouter call failed after {retries} attempts ({tag}): {last}")


JEV_URL = "https://openrouter.ai/api/alpha/decisions"
JEV = os.environ.get("FIRMABLE_JEV_MODEL", "typesafe/jev-1.14")


def jev_decide(state: dict, questions: dict, *, tag: str = "", retries: int = 3) -> dict:
    """TypeSafe Jev decision model via OpenRouter's Decisions API. Questions are typed
    (noul -> P(yes), choice -> option + probabilities, score -> position on a scale), so the
    answer comes back as calibrated probabilities instead of parsed free text."""
    import httpx
    last: Exception | None = None
    for attempt in range(retries):
        t0 = time.time()
        try:
            r = httpx.post(JEV_URL, timeout=30,
                           headers={"Authorization": f"Bearer {os.environ['OPENROUTER_API_KEY']}"},
                           json={"model": JEV, "state": state, "questions": questions})
            if r.status_code == 400:  # schema errors will not fix themselves on retry
                raise ValueError(f"Jev rejected the request: {r.text[:500]}")
            r.raise_for_status()
            body = r.json()
            u = body.get("usage", {})
            _record_raw(body.get("model", JEV), tag, u.get("input_tokens", 0),
                        u.get("output_tokens", 0), time.time() - t0, u.get("cost"))
            return body
        except ValueError:
            raise
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(5 * 3 ** attempt)
    raise RuntimeError(f"Jev call failed after {retries} attempts ({tag}): {last}")


def _record(model: str, tag: str, usage, seconds: float) -> None:
    p_in = usage.prompt_token_count or 0
    p_out = (usage.candidates_token_count or 0) + (getattr(usage, "thoughts_token_count", 0) or 0)
    _record_raw(model, tag, p_in, p_out, seconds)


def _record_raw(model: str, tag: str, p_in: int, p_out: int, seconds: float,
                billed: float | None = None) -> None:
    price = PRICES.get(model, {"in": 0, "out": 0})
    cost = billed if billed is not None else p_in / 1e6 * price["in"] + p_out / 1e6 * price["out"]
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    with LEDGER.open("a") as f:
        f.write(json.dumps({"ts": time.time(), "model": model, "tag": tag, "in": p_in,
                            "out": p_out, "usd": round(cost, 6), "secs": round(seconds, 2)}) + "\n")


def usage_since(ts: float, tag_prefix: str = "") -> dict:
    """Sum ledger rows after `ts` whose tag starts with `tag_prefix`."""
    tot = {"calls": 0, "in": 0, "out": 0, "usd": 0.0}
    if not LEDGER.exists():
        return tot
    for line in LEDGER.read_text().splitlines():
        r = json.loads(line)
        if r["ts"] >= ts and r["tag"].startswith(tag_prefix):
            tot["calls"] += 1
            tot["in"] += r["in"]
            tot["out"] += r["out"]
            tot["usd"] += r["usd"]
    tot["usd"] = round(tot["usd"], 4)
    return tot


def generate(contents, config, *, model: str = SMART, tag: str = "", retries: int = 3):
    """Raw generate_content (for function calling) with the same usage ledger as `structured`."""
    last: Exception | None = None
    for attempt in range(retries):
        t0 = time.time()
        try:
            resp = client().models.generate_content(model=model, contents=contents, config=config)
            _record(model, tag, resp.usage_metadata, time.time() - t0)
            return resp
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(5 * 3 ** attempt)
    raise RuntimeError(f"LLM call failed after {retries} attempts ({tag}): {last}")
