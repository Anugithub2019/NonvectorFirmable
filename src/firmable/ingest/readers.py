"""Format readers, driven by the `reader` block of a mapping config.

Also exposes the two tools the agent's inspect step uses:
  sniff(path)            -> what the bytes actually are (not what the catalogue claims)
  try_read(path, spec)   -> parse with a proposed reader spec and report warning signs
"""
from __future__ import annotations

import csv
import io
import json
import re
import zipfile
from pathlib import Path
from typing import Iterator

import pandas as pd

FORMATS = ("csv", "tsv", "xlsx", "xls", "json", "geojson", "xml")


def iter_xml_records(path: Path, record_tag: str, sep: str = " | "):
    """Stream `<record_tag>` elements from an arbitrarily large XML file (zip members too)
    and flatten each to {column: text}. Column names are element paths below the record
    ('MainEntity.BusinessAddress.State'); attributes become 'Elem@attr'; repeated paths are
    joined with `sep` so a config can `split` them. Memory stays flat: each record element is
    cleared after it is yielded."""
    import xml.etree.ElementTree as ET
    import zipfile

    def flatten(el) -> dict:
        return _flatten_element(el, sep)

    def stream(fh):
        for event, el in ET.iterparse(fh, events=("end",)):
            if el.tag.split("}")[-1] == record_tag:
                yield flatten(el)
                el.clear()

    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as z:
            for name in z.namelist():
                if name.lower().endswith(".xml"):
                    with z.open(name) as fh:
                        yield from stream(fh)
    else:
        with path.open("rb") as fh:
            yield from stream(fh)


def _flatten_element(el, sep: str = " | ") -> dict:
    """Flatten one element subtree to {path: text}; attributes as 'Elem@attr'; repeats joined."""
    row: dict[str, str] = {}

    def walk(e, prefix):
        name = e.tag.split("}")[-1]
        key = f"{prefix}.{name}" if prefix else name
        for a, v in e.attrib.items():
            _put(row, f"{key}@{a}", v, sep)
        text = (e.text or "").strip()
        if text:
            _put(row, key, text, sep)
        for c in e:
            walk(c, key)
    for a, v in el.attrib.items():
        _put(row, f"@{a}", v, sep)
    for c in el:
        walk(c, "")
    return row


def _put(row: dict, key: str, value: str, sep: str) -> None:
    row[key] = f"{row[key]}{sep}{value}" if key in row else value


def _magic(head: bytes) -> str:
    if head.startswith(b"PK\x03\x04"):
        return "zip"
    if head.startswith(b"\xd0\xcf\x11\xe0"):
        return "ole2"  # legacy .xls
    h = head.lstrip()[:200].lower()
    if h.startswith((b"<!doctype html", b"<html")) or b"<html" in h:
        return "html"
    if h.startswith((b"{", b"[")):
        return "json"
    if h.startswith(b"<?xml") or h.startswith(b"<"):
        return "xml"
    return "text"


def _decode(raw: bytes) -> tuple[str, str]:
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return raw.decode(enc), enc
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1", errors="replace"), "latin-1"


def encoding_check(path: Path) -> dict[str, str]:
    """Decode the WHOLE file under each candidate encoding. Bad bytes are often deep in a file,
    where a head-only preview never sees them."""
    raw = path.read_bytes()
    out = {}
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            raw.decode(enc)
            out[enc] = "ok"
        except UnicodeDecodeError as e:
            ctx = raw[max(0, e.start - 30):e.start + 10]
            out[enc] = f"fails at byte {e.start} (0x{raw[e.start]:02x}) near {ctx!r}"
    return out


def sniff(path: Path) -> dict:
    """Describe the file from its bytes. Cheap; never parses the whole thing."""
    head = path.read_bytes()[:65536]
    kind = _magic(head)
    info: dict = {"path": path.name, "bytes": path.stat().st_size, "magic": kind,
                  "extension": path.suffix.lower()}
    if kind == "zip":
        try:
            with zipfile.ZipFile(path) as z:
                names = z.namelist()
            info["zip_members"] = names[:30]
            if any(n.startswith("xl/") for n in names):
                info["magic"] = "xlsx"
        except zipfile.BadZipFile:
            info["zip_error"] = "bad zip"
    if info["magic"] in ("xlsx", "ole2"):
        try:
            xl = pd.ExcelFile(path)
            info["sheets"] = {}
            for sh in xl.sheet_names[:5]:
                df = pd.read_excel(xl, sheet_name=sh, header=None, nrows=12, dtype=str)
                info["sheets"][sh] = df.fillna("").astype(str).map(lambda s: s[:40]).values.tolist()
        except Exception as e:  # noqa: BLE001
            info["excel_error"] = str(e)[:200]
    if info["magic"] in ("text", "json", "xml", "html"):
        text, enc = _decode(head)
        info["encoding_guess"] = enc
        info["encoding_check_full_file"] = encoding_check(path)
        info["text_preview"] = "\n".join(text.splitlines()[:25])[:4000]
        if info["magic"] == "text":
            try:
                info["delimiter_guess"] = csv.Sniffer().sniff(text[:20000], ",\t;|").delimiter
            except csv.Error:
                info["delimiter_guess"] = None
    return info


def read_frame(path: Path, spec: dict, nrows: int | None = None) -> pd.DataFrame:
    """Parse to a DataFrame of strings (no type coercion: raw values stay raw)."""
    fmt = spec["format"]
    header_row = int(spec.get("header_row", 0) or 0)
    if fmt in ("csv", "tsv"):
        sep = "\t" if fmt == "tsv" else (spec.get("delimiter") or ",")
        df = pd.read_csv(path, sep=sep, header=None, dtype=str, keep_default_na=False,
                         encoding=spec.get("encoding") or "utf-8-sig", on_bad_lines="warn",
                         nrows=None if nrows is None else nrows + header_row + 1,
                         quotechar=spec.get("quotechar") or '"', engine="python" if sep not in (",", "\t") else "c")
    elif fmt in ("xlsx", "xls"):
        df = pd.read_excel(path, sheet_name=spec.get("sheet") or 0, header=None, dtype=str,
                           nrows=None if nrows is None else nrows + header_row + 1)
        df = df.fillna("")
    elif fmt in ("json", "geojson"):
        data = json.loads(path.read_text(encoding=spec.get("encoding") or "utf-8"))
        for key in [k for k in (spec.get("records_path") or "").split(".") if k]:
            data = data[key]
        if fmt == "geojson" or (isinstance(data, dict) and "features" in data):
            data = [f.get("properties", {}) for f in (data["features"] if isinstance(data, dict) else data)]
        df = pd.json_normalize(data).astype(str)
        return df.head(nrows) if nrows else df
    elif fmt == "xml":
        rows = []
        for i, r in enumerate(iter_xml_records(path, spec["record_tag"])):
            rows.append(r)
            if nrows is not None and i + 1 >= nrows:
                break
        df = pd.DataFrame(rows).fillna("").astype(str)
        return df
    else:
        raise ValueError(f"unsupported reader format {fmt!r}; supported: {FORMATS}")

    header = [str(c).strip() for c in df.iloc[header_row].tolist()]
    df = df.iloc[header_row + 1 + int(spec.get("skip_rows_after_header", 0) or 0):]
    df.columns = _dedupe_columns(header)
    df = df.astype(str).map(lambda s: "" if s in ("nan", "NaT", "None") else s)
    if spec.get("drop_empty_rows", True):
        df = df[(df != "").any(axis=1)]
    return df.reset_index(drop=True)


def _dedupe_columns(cols: list[str]) -> list[str]:
    seen: dict[str, int] = {}
    out = []
    for i, c in enumerate(cols):
        c = c or f"unnamed_{i}"
        if c in seen:
            seen[c] += 1
            c = f"{c}__{seen[c]}"
        else:
            seen[c] = 0
        out.append(c)
    return out


def iter_records(path: Path, spec: dict, nrows: int | None = None) -> Iterator[tuple[int, dict]]:
    """Yield (row_number, {column: raw string}). row_number is 0-based within data rows."""
    df = read_frame(path, spec, nrows)
    for i, row in enumerate(df.to_dict(orient="records")):
        yield i, row


def try_read(path: Path, spec: dict) -> dict:
    """Parse a preview with `spec` and flag signs the spec is wrong. Used as an agent tool."""
    if spec["format"] in ("csv", "tsv", "json", "geojson"):
        enc = spec.get("encoding") or "utf-8-sig"
        try:
            path.read_bytes().decode(enc)
        except (UnicodeDecodeError, LookupError) as e:
            return {"ok": False, "error": f"encoding {enc!r} cannot decode the full file: {e}. "
                    f"Full-file check: {encoding_check(path)}"}
    try:
        df = read_frame(path, spec, nrows=400)
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"{type(e).__name__}: {str(e)[:300]}"}
    cols = list(df.columns)
    warnings = []
    if len(cols) == 1:
        warnings.append("only one column: delimiter or format is probably wrong")
    unnamed = [c for c in cols if c.startswith("unnamed_")]
    if len(unnamed) > max(1, len(cols) // 3):
        warnings.append(f"{len(unnamed)}/{len(cols)} columns have no header: header_row may be wrong")
    data_like = [c for c in cols if re.fullmatch(r"[\d\-/.: ]{4,}|\d{9,11}", c)]
    if data_like:
        warnings.append(f"header cells look like data values {data_like[:3]}: header_row may be wrong")
    if any("__" in c for c in cols):
        warnings.append("duplicate column names were suffixed with __N")
    empty = [c for c in cols if (df[c] == "").all()]
    if len(empty) > len(cols) // 2:
        warnings.append(f"{len(empty)} columns are entirely empty in the preview")
    if len(df) == 0:
        warnings.append("no data rows parsed")
    return {"ok": True, "columns": cols, "preview_rows": len(df),
            "first_rows": df.head(5).map(lambda s: s[:60]).to_dict(orient="records"),
            "warnings": warnings}


def count_rows(path: Path, spec: dict) -> int:
    return len(read_frame(path, spec))


def to_text_table(rows: list[dict], width: int = 40) -> str:
    buf = io.StringIO()
    for r in rows:
        buf.write(json.dumps({k: str(v)[:width] for k, v in r.items()}, ensure_ascii=False) + "\n")
    return buf.getvalue()
