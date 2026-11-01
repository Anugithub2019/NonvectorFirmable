"""Tier-1 slicing. Deterministic SQL over the raw national files, run BEFORE the onboarding
agent sees them. Slicing is a volume decision, not a mapping decision, so it is code, not config.

The slice has two parts, both documented in README:
  geographic : ABR records that are ACTIVE, companies (PRV/PUB), in QLD, in the chosen
               postcode bands  (small enough to iterate on, large enough that blocking matters)
  referenced : every ABR / ASIC-company record whose ABN or ACN is carried by ANY attached
               source (tier 2, extra sources, GLEIF registeredAs), regardless of state.
               Without this, attachment could never be tested outside the geographic slice.

Outputs (CSV, read by the agent like any other source):
  data/raw/abr-slice/abr_slice.csv
  data/raw/asic-companies-slice/asic_companies_slice.csv   (incl. former-name rows)
  data/raw/_tier/slice_report.json
"""
from __future__ import annotations

import json
import sys
import zipfile

import duckdb

from ..paths import RAW

ABR_PARQUET = RAW / "abr" / "abr_all.parquet"
ASIC_ZIP = RAW / "data-gov-au__asic-companies" / "company_202610.zip"
POSTCODE_BANDS = ("400", "401", "402", "403")   # Brisbane CBD + inner suburbs (~50k active companies)

# Raw identifier columns in TIER-2 sources (before any mapping). Used only for slicing: every
# tier-2 identifier gets its backbone record so keyed attachment is testable end to end.
# The extra state/charity registers (QBCC, SOR, ACNC) are deliberately NOT here: they are
# national/state-wide and would pull 140k+ backbone rows in; they attach only inside the
# geographic slice, and their records outside it become singleton parties.
REFERENCING = {
    "data-gov-au__asic-afs-licensee/afs_lic_202610.csv": ["AFS_LIC_ABN_ACN"],
    "data-gov-au__asic-credit-licensee/cred_lic_202610.tsv": ["CRED_LIC_ABN_ACN"],
    "data-gov-au__asic-banned-disqualified-org/bd_org_202610.csv": ["BD_ORG_ACN"],
    "gleif/lei_au.csv": ["registered_as"],
}


def referenced_identifiers(con: duckdb.DuckDBPyConnection) -> None:
    """TEMP TABLE ref_ids(digits) from every attached source's raw identifier columns."""
    con.execute("CREATE OR REPLACE TEMP TABLE ref_ids (digits VARCHAR, src VARCHAR)")
    for pattern, cols in REFERENCING.items():
        files = sorted(RAW.glob(pattern))
        for f in files:
            for c in cols:
                try:
                    if f.suffix == ".xlsx":
                        con.execute("INSTALL excel; LOAD excel;")
                        q = f"SELECT \"{c}\" AS v FROM read_xlsx('{f}', header=true, all_varchar=true)"
                    else:
                        head = f.open(encoding="utf-8-sig", errors="replace").readline()
                        sep = "\t" if head.count("\t") > head.count(",") else ","
                        q = (f"SELECT \"{c}\" AS v FROM read_csv('{f}', header=true, all_varchar=true, "
                             f"delim='{sep}', quote='\"', ignore_errors=true)")
                    con.execute(f"""INSERT INTO ref_ids SELECT regexp_replace(v, '[^0-9]', '', 'g'), '{f.parent.name}'
                                    FROM ({q}) WHERE v IS NOT NULL""")
                except Exception as e:  # noqa: BLE001
                    print(f"  ! {f.name}.{c}: {str(e)[:100]}", file=sys.stderr)
    con.execute("DELETE FROM ref_ids WHERE length(digits) NOT IN (9, 11)")


def run(bands: tuple[str, ...] = POSTCODE_BANDS) -> dict:
    con = duckdb.connect()
    referenced_identifiers(con)
    n_ref = con.execute("SELECT count(DISTINCT digits), count(*) FROM ref_ids").fetchone()
    abr = str(ABR_PARQUET)
    band_sql = " OR ".join(f"postcode LIKE '{b}%'" for b in bands)
    con.execute(f"""CREATE OR REPLACE TEMP TABLE abr_slice AS
        SELECT a.*, CASE WHEN ({band_sql}) AND state='QLD' AND abn_status='ACT'
                          AND entity_type_code IN ('PRV','PUB') THEN 'geographic' ELSE 'referenced' END AS slice_reason
        FROM '{abr}' a
        WHERE (({band_sql}) AND state='QLD' AND abn_status='ACT' AND entity_type_code IN ('PRV','PUB'))
           OR a.abn IN (SELECT digits FROM ref_ids WHERE length(digits)=11)
           OR (a.acn <> '' AND a.acn IN (SELECT digits FROM ref_ids WHERE length(digits)=9))""")
    out_abr = RAW / "abr-slice" / "abr_slice.csv"
    out_abr.parent.mkdir(parents=True, exist_ok=True)
    con.execute(f"COPY abr_slice TO '{out_abr}' (HEADER, DELIMITER ',')")
    geo, ref = con.execute("SELECT count(*) FILTER (slice_reason='geographic'), count(*) FILTER (slice_reason='referenced') FROM abr_slice").fetchone()

    # ASIC companies: rows (current + former names) whose ACN is in the ABR slice or referenced
    with zipfile.ZipFile(ASIC_ZIP) as z:
        member = z.namelist()[0]
        z.extract(member, ASIC_ZIP.parent)
    asic_csv = ASIC_ZIP.parent / member
    con.execute(f"""CREATE OR REPLACE TEMP TABLE asic_slice AS
        SELECT * FROM read_csv('{asic_csv}', header=true, delim='\\t', all_varchar=true, quote='', ignore_errors=true)
        WHERE "ACN" IN (SELECT acn FROM abr_slice WHERE acn <> '')
           OR "ACN" IN (SELECT digits FROM ref_ids WHERE length(digits)=9)
           OR "ABN" IN (SELECT digits FROM ref_ids WHERE length(digits)=11)""")
    out_asic = RAW / "asic-companies-slice" / "asic_companies_slice.csv"
    out_asic.parent.mkdir(parents=True, exist_ok=True)
    con.execute(f"COPY asic_slice TO '{out_asic}' (HEADER, DELIMITER ',')")
    asic_n, asic_current = con.execute("""SELECT count(*), count(*) FILTER ("Current Name Indicator"='Y') FROM asic_slice""").fetchone()
    asic_csv.unlink()
    report = {"postcode_bands": list(bands), "referenced_identifiers": {"distinct": n_ref[0], "mentions": n_ref[1]},
              "abr_slice": {"geographic": geo, "referenced_only": ref, "total": geo + ref},
              "asic_companies_slice": {"rows": asic_n, "current_name_rows": asic_current,
                                       "former_name_rows": asic_n - asic_current},
              "abr_parquet_rows": con.execute(f"SELECT count(*) FROM '{abr}'").fetchone()[0]}
    (RAW / "_tier" / "slice_report.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=1))
    return report


if __name__ == "__main__":
    run()
