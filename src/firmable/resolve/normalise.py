"""Name normalisation and blocking keys. Deterministic; shared by the exact path, the semantic
path and the `resolve` lookup so all three see the same string.

normalise("\"Over The Top\" Roof Restorations Pty. Ltd")  -> "OVER THE TOP ROOF RESTORATIONS"
legal_form(...)                                            -> "PTY LTD"
blocking_keys(...)                                         -> {"t:OVER", "t:ROOF", "s:OVE", ...}
"""
from __future__ import annotations

import re
import unicodedata

# Legal-form and noise tokens removed before comparison. Kept separately as `legal_form`
# because PTY LTD vs LIMITED vs INC is evidence about entity type, not identity.
LEGAL_FORMS = [
    r"PROPRIETARY LIMITED", r"PTY\.? LTD\.?", r"PTY\.? LIMITED", r"P/L", r"PTY\.?", r"LIMITED",
    r"LTD\.?", r"INCORPORATED", r"INC\.?", r"CO-?OPERATIVE", r"CO-?OP", r"CORPORATION", r"CORP\.?",
    r"NO LIABILITY", r"NL", r"ASSOCIATION", r"ASSOC\.?", r"AUSTRALIA", r"AUSTRALIAN", r"AUST\.?",
    r"THE TRUSTEE FOR", r"TRUSTEE FOR", r"ATF", r"AS TRUSTEE FOR", r"THE",
]
_LEGAL_RX = re.compile(r"\b(" + "|".join(LEGAL_FORMS) + r")\b", re.I)
_FORM_RX = re.compile(r"\b(PROPRIETARY LIMITED|PTY\.? LTD\.?|PTY\.? LIMITED|P/L|PTY|LIMITED|LTD|"
                      r"INCORPORATED|INC|CO-?OPERATIVE|CO-?OP|CORPORATION|CORP|NL|ASSOCIATION)\b", re.I)
_PUNCT_RX = re.compile(r"[^A-Z0-9& ]+")
_WS_RX = re.compile(r"\s+")
_FORM_CANON = {"PROPRIETARY LIMITED": "PTY LTD", "PTY LIMITED": "PTY LTD", "P/L": "PTY LTD",
               "PTY. LTD.": "PTY LTD", "PTY. LTD": "PTY LTD", "PTY LTD.": "PTY LTD", "LTD": "LTD",
               "LIMITED": "LTD", "INCORPORATED": "INC", "CORPORATION": "CORP", "COOPERATIVE": "CO-OP",
               "CO-OPERATIVE": "CO-OP", "COOP": "CO-OP", "ASSOCIATION": "ASSOC"}

# Generic names that block badly: they would put thousands of unrelated parties in one block.
GENERIC_TOKENS = {"PTY", "LTD", "THE", "AND", "OF", "GROUP", "HOLDINGS", "INVESTMENTS", "SERVICES",
                  "FAMILY", "TRUST", "SUPER", "FUND", "SUPERANNUATION", "NOMINEES", "ENTERPRISES",
                  "TRADING", "COMPANY", "CO", "AUSTRALIA", "QLD", "QUEENSLAND", "NSW", "VIC",
                  "MANAGEMENT", "CONSULTING", "SOLUTIONS", "PROPERTIES", "DEVELOPMENTS", "A", "&"}


def ascii_upper(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()
    return s.upper().strip()


def legal_form(name: str) -> str | None:
    m = _FORM_RX.findall(ascii_upper(name))
    if not m:
        return None
    last = m[-1].upper().replace(".", "")
    return _FORM_CANON.get(last, last)


def normalise(name: str) -> str:
    """Comparison form: upper ASCII, '&'->'AND', legal-form words and punctuation removed."""
    s = ascii_upper(name).replace("&", " AND ")
    s = _LEGAL_RX.sub(" ", s)
    s = _PUNCT_RX.sub(" ", s)
    s = _WS_RX.sub(" ", s).strip()
    return s


def tokens(name_norm: str) -> list[str]:
    return [t for t in name_norm.split() if t]


def blocking_keys(name_norm: str, state: str | None = None, postcode: str | None = None) -> set[str]:
    """Keys a record is indexed under. A candidate pair must share at least one key.
    - t:<token>      each non-generic token of >= 3 chars (so 'SMITH PLUMBING' meets 'SMITH PLUMBING SERVICES')
    - f:<first3>:<state>  first-token prefix + state, catches typos in later tokens
    - p:<postcode>:<first3>  postcode + first-token prefix
    Generic tokens are excluded: 'HOLDINGS' alone would block 10^5 records together.
    The recall cost is measured in evaluation.md (hidden-identifier test)."""
    toks = tokens(name_norm)
    keys: set[str] = set()
    for t in toks:
        if len(t) >= 3 and t not in GENERIC_TOKENS:
            keys.add(f"t:{t}")
    if toks:
        head = toks[0][:3]
        if state:
            keys.add(f"f:{head}:{state}")
        if postcode:
            keys.add(f"p:{postcode}:{head}")
    return keys


def digits(s: str | None) -> str:
    return re.sub(r"\D", "", s or "")


def canonical_key(abn: str | None, acn: str | None, lei: str | None) -> str | None:
    """Key precedence: ABN > ACN > LEI. None when no identifier is present."""
    if abn:
        return f"abn:{abn}"
    if acn:
        return f"acn:{acn}"
    if lei:
        return f"lei:{lei}"
    return None
