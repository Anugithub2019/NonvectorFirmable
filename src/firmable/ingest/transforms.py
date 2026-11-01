"""The closed transform library.

Mapping configs may only reference ops defined here. The agent composes them; it never
writes code. Adding an op is an engine change (reviewed, versioned), not a config change.

Every op takes a value (str, list[str] or None) plus keyword args and returns a value or None.
Returning None for a non-empty input means "could not transform" and is counted as a failure
by the validator, never silently replaced by a guess.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Callable

from ..ontology import abn_valid, acn_valid

Value = str | list[str] | None
OPS: dict[str, tuple[Callable[..., Value], str]] = {}
# Ops whose None means "deliberately no claim", not "failed to parse".
ABSTAINING = {"entity_type_from_name"}


def op(doc: str):
    def deco(fn):
        OPS[fn.__name__] = (fn, doc)
        return fn
    return deco


def _each(v: Value, fn: Callable[[str], str | None]) -> Value:
    if v is None:
        return None
    if isinstance(v, list):
        out = [r for r in (fn(x) for x in v) if r not in (None, "")]
        return out or None
    r = fn(v)
    return None if r in (None, "") else r


@op("Trim surrounding whitespace.")
def strip(v: Value) -> Value:
    return _each(v, lambda s: s.strip())


@op("Collapse runs of whitespace to one space, and trim.")
def collapse_whitespace(v: Value) -> Value:
    return _each(v, lambda s: re.sub(r"\s+", " ", s).strip())


@op("Uppercase.")
def upper(v: Value) -> Value:
    return _each(v, str.upper)


@op("Lowercase.")
def lower(v: Value) -> Value:
    return _each(v, str.lower)


@op("Title Case (use only for display fields like locality; never for legal names).")
def title_case(v: Value) -> Value:
    return _each(v, lambda s: s.title())


@op("Treat listed placeholder strings as missing. args: values (list[str], case-insensitive).")
def null_if(v: Value, values: list[str]) -> Value:
    bad = {x.strip().lower() for x in values}
    return _each(v, lambda s: None if s.strip().lower() in bad else s)


@op("Keep digits only.")
def digits_only(v: Value) -> Value:
    return _each(v, lambda s: re.sub(r"\D", "", s))


@op("Keep digits and left-pad with zeros to `width` (ACNs/ABNs exported as numbers lose leading "
    "zeros: 90444714 -> 090444714). args: width. Values longer than width are left unchanged.")
def zfill(v: Value, width: int) -> Value:
    return _each(v, lambda s: re.sub(r"\D", "", s).zfill(int(width)) if re.sub(r"\D", "", s) else None)


@op("Regex search; return capture `group` (default 1) or None if no match. args: pattern, group.")
def regex_extract(v: Value, pattern: str, group: int = 1) -> Value:
    rx = re.compile(pattern, re.I)

    def f(s: str) -> str | None:
        m = rx.search(s)
        return m.group(group) if m else None
    return _each(v, f)


@op("Regex substitute. args: pattern, repl.")
def regex_replace(v: Value, pattern: str, repl: str = "") -> Value:
    rx = re.compile(pattern, re.I)
    return _each(v, lambda s: rx.sub(repl, s))


@op("Australian Business Number: strip non-digits; keep ONLY if 11 digits AND checksum passes.")
def abn(v: Value) -> Value:
    def f(s: str) -> str | None:
        d = re.sub(r"\D", "", s)
        return d if abn_valid(d) else None
    return _each(v, f)


@op("Australian Company Number: strip non-digits; keep ONLY if 9 digits AND checksum passes. "
    "Never derives an ACN from an ABN.")
def acn(v: Value) -> Value:
    def f(s: str) -> str | None:
        d = re.sub(r"\D", "", s)
        return d if acn_valid(d) else None
    return _each(v, f)


@op("Parse a date to ISO YYYY-MM-DD. args: formats (list of strptime formats, tried in order). "
    "Excel exports often look like '%Y-%m-%d %H:%M:%S'.")
def parse_date(v: Value, formats: list[str]) -> Value:
    def f(s: str) -> str | None:
        s = s.strip()
        for fmt in formats:
            try:
                return datetime.strptime(s, fmt).date().isoformat()
            except ValueError:
                continue
        return None
    return _each(v, f)


@op("Parse a datetime to ISO 8601. args: formats (list of strptime formats).")
def parse_datetime(v: Value, formats: list[str]) -> Value:
    def f(s: str) -> str | None:
        s = s.strip()
        for fmt in formats:
            try:
                return datetime.strptime(s, fmt).isoformat()
            except ValueError:
                continue
        return None
    return _each(v, f)


@op("Map raw values to canonical values. args: mapping (object raw->canonical), "
    "default (value for unlisted inputs; omit/null to emit nothing). Matching is case-insensitive.")
def map_values(v: Value, mapping: dict[str, str], default: str | None = None) -> Value:
    m = {k.strip().lower(): val for k, val in mapping.items()}
    return _each(v, lambda s: m.get(s.strip().lower(), default))


@op("Infer entity_type from legal-form words in a NAME (PTY LTD/LIMITED/P/L -> company, "
    "INCORPORATED/INC -> incorporated_association, TRUST/ATF -> trust). Emits nothing when "
    "no legal-form word is present (does not guess sole_trader). Derivation L1.")
def entity_type_from_name(v: Value) -> Value:
    def f(s: str) -> str | None:
        u = f" {re.sub(r'[^A-Z0-9& ]', ' ', s.upper())} "
        if re.search(r" (ATF|AS TRUSTEE FOR|TRUSTEE FOR|THE TRUST|TRUST) ", u):
            return "trust"
        if re.search(r" (PTY|PROPRIETARY|LTD|LIMITED|CORPORATION|CORP|NL|P L) ", u):  # P L = "P/L"
            return "company"
        if re.search(r" (INCORPORATED|INC) ", u):
            return "incorporated_association"
        return None
    return _each(v, f)


@op("Extract an Australian postcode (last standalone 4-digit token 0200-9999).")
def au_postcode(v: Value) -> Value:
    def f(s: str) -> str | None:
        hits = [h for h in re.findall(r"(?<!\d)(\d{4})(?!\d)", s) if 200 <= int(h) <= 9999]
        return hits[-1] if hits else None
    return _each(v, f)


_STATES = {"NEW SOUTH WALES": "NSW", "VICTORIA": "VIC", "QUEENSLAND": "QLD",
           "WESTERN AUSTRALIA": "WA", "SOUTH AUSTRALIA": "SA", "TASMANIA": "TAS",
           "AUSTRALIAN CAPITAL TERRITORY": "ACT", "NORTHERN TERRITORY": "NT"}


@op("Extract an Australian state/territory as the ontology enum (NSW, VIC, QLD, WA, SA, TAS, "
    "ACT, NT). Accepts abbreviations or full names anywhere in the text.")
def au_state(v: Value) -> Value:
    def f(s: str) -> str | None:
        u = s.upper()
        for full, ab in _STATES.items():
            if full in u:
                return ab
        hits = re.findall(r"\b(NSW|VIC|QLD|WA|SA|TAS|ACT|NT)\b", u)
        return hits[-1] if hits else None
    return _each(v, f)


@op("Normalise a website: trim, lowercase scheme/host, drop trailing slash; None if no dot.")
def url(v: Value) -> Value:
    def f(s: str) -> str | None:
        s = s.strip().rstrip("/")
        if "." not in s or " " in s:
            return None
        return re.sub(r"^(https?://)?([^/]+)", lambda m: (m.group(1) or "").lower()
                      + m.group(2).lower(), s)
    return _each(v, f)


@op("Split one value into several (each becomes its own observation). args: sep (regex).")
def split(v: Value, sep: str) -> Value:
    if v is None:
        return None
    items = v if isinstance(v, list) else [v]
    out = [p.strip() for s in items for p in re.split(sep, s) if p.strip()]
    return out or None


@op("Split on `sep` and keep the part at `index` (negative counts from the end). args: sep, index.")
def pick_part(v: Value, sep: str, index: int) -> Value:
    def f(s: str) -> str | None:
        parts = [p.strip() for p in s.split(sep)]
        try:
            return parts[index] or None
        except IndexError:
            return None
    return _each(v, f)


@op("Emit a fixed value regardless of input (e.g. country 'AU' for a national register). "
    "args: value.")
def constant(v: Value, value: str) -> Value:
    return value


def apply(steps: list[dict[str, Any]], value: Value) -> Value:
    for step in steps:
        fn, _ = OPS[step["op"]]
        value = fn(value, **(step.get("args") or {}))
        if value is None and step["op"] != "constant":
            return None
    return value


def catalogue() -> str:
    """Human/LLM-readable list of ops, used in prompts."""
    return "\n".join(f"- {name}: {doc}" for name, (_, doc) in OPS.items())
