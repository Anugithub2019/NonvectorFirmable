"""ABR bulk extract (tier 1 backbone): 20 XML members x ~1M records, ~12 GB uncompressed.

parse_all()  streams every member through the generic XML flattener (readers.iter_xml_records)
             in parallel and writes one compact CSV per member, then a single parquet
             (data/raw/abr/abr_all.parquet, ~20M rows). This is the only full pass over the
             national file; every later slice is a DuckDB query over the parquet.
slice()      writes the tier-1 slice CSV the onboarding agent maps (see slices.py).

Licence: CC-BY 3.0 AU (data.gov.au catalogue). Weekly refresh: re-running parse_all with a new
extract replaces the parquet; the graph load is idempotent on (abn, content hash).
"""
from __future__ import annotations

import csv
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from ..paths import RAW
from . import readers

ZIP_DIR = RAW / "data-gov-au__abn-bulk-extract"
OUT = RAW / "abr"
COLUMNS = ["abn", "abn_status", "abn_status_from", "entity_type_code", "entity_type_text",
           "name", "name_type", "acn", "acn_type", "state", "postcode", "gst_status",
           "gst_from", "other_names", "other_name_types", "record_last_updated", "replaced",
           "source_member"]


def _row(rec: dict, member: str) -> dict:
    """Select the columns the graph needs from a flattened <ABR> record."""
    name = rec.get("MainEntity.NonIndividualName.NonIndividualNameText")
    name_type = rec.get("MainEntity.NonIndividualName@type")
    if not name:  # individual / sole trader: LegalEntity.IndividualName
        parts = [rec.get("LegalEntity.IndividualName.GivenName", ""),
                 rec.get("LegalEntity.IndividualName.FamilyName", "")]
        name = " ".join(p for p in parts if p).replace(" | ", " ")
        name_type = rec.get("LegalEntity.IndividualName@type", "IND")
    state = rec.get("MainEntity.BusinessAddress.AddressDetails.State") or \
        rec.get("LegalEntity.BusinessAddress.AddressDetails.State", "")
    postcode = rec.get("MainEntity.BusinessAddress.AddressDetails.Postcode") or \
        rec.get("LegalEntity.BusinessAddress.AddressDetails.Postcode", "")
    return {
        "abn": rec.get("ABN", ""), "abn_status": rec.get("ABN@status", ""),
        "abn_status_from": rec.get("ABN@ABNStatusFromDate", ""),
        "entity_type_code": rec.get("EntityType.EntityTypeInd", ""),
        "entity_type_text": rec.get("EntityType.EntityTypeText", ""),
        "name": name, "name_type": name_type or "",
        "acn": rec.get("ASICNumber", ""), "acn_type": rec.get("ASICNumber@ASICNumberType", ""),
        "state": state, "postcode": postcode,
        "gst_status": rec.get("GST@status", ""), "gst_from": rec.get("GST@GSTStatusFromDate", ""),
        "other_names": rec.get("OtherEntity.NonIndividualName.NonIndividualNameText", ""),
        "other_name_types": rec.get("OtherEntity.NonIndividualName@type", ""),
        "record_last_updated": rec.get("@recordLastUpdatedDate", ""),
        "replaced": rec.get("@replaced", ""), "source_member": member,
    }


def parse_member(args: tuple[str, str]) -> tuple[str, int, float]:
    import zipfile
    zip_path, member = args
    t0 = time.time()
    out = OUT / "members" / (Path(member).stem + ".csv")
    out.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with zipfile.ZipFile(zip_path) as z, z.open(member) as fh, out.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        for rec in _stream(fh):
            w.writerow(_row(rec, member))
            n += 1
    return member, n, round(time.time() - t0, 1)


def _stream(fh):
    """Stream <ABR> records from an open file handle via the generic flattener."""
    import xml.etree.ElementTree as ET
    flatten = readers._flatten_element
    for _, el in ET.iterparse(fh, events=("end",)):
        if el.tag == "ABR":
            yield flatten(el)
            el.clear()


def parse_all(workers: int = 8) -> Path:
    import duckdb
    jobs = []
    import zipfile
    for zp in sorted(ZIP_DIR.glob("*.zip")):
        with zipfile.ZipFile(zp) as z:
            jobs += [(str(zp), m) for m in z.namelist() if m.lower().endswith(".xml")]
    done = {p.stem for p in (OUT / "members").glob("*.csv")} if (OUT / "members").exists() else set()
    todo = [j for j in jobs if Path(j[1]).stem not in done]
    print(f"abr: {len(jobs)} members, {len(todo)} to parse with {workers} workers", file=sys.stderr)
    with ProcessPoolExecutor(workers) as ex:
        for member, n, secs in ex.map(parse_member, todo):
            print(f"  {member}: {n} records in {secs}s", file=sys.stderr, flush=True)
    out = OUT / "abr_all.parquet"
    con = duckdb.connect()
    # explicit dialect: the sniffer fails on members with unusual name strings
    con.execute(f"""COPY (SELECT * FROM read_csv('{OUT / 'members'}/*.csv', header=true, all_varchar=true,
                 delim=',', quote='"', escape='"', max_line_size=10000000, union_by_name=true))
                 TO '{out}' (FORMAT PARQUET, COMPRESSION ZSTD)""")
    n = con.execute(f"SELECT count(*) FROM '{out}'").fetchone()[0]
    print(f"abr: wrote {out} with {n} rows", file=sys.stderr)
    return out


if __name__ == "__main__":
    parse_all()
