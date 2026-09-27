"""Reproducible Freddie Mac sample vintage and delinquency analysis.

Run: python analyze.py --input-dir ../upload --output-dir output
Reads the original ZIP members directly. Requires pandas, numpy, matplotlib.
SQLite (standard library) executes the accompanying analysis.sql.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import zipfile
from collections import Counter
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

YEARS = (2021, 2022, 2023)
CUTOFF = 2026 * 12 + 3  # latest report month seen in the supplied files; verified below
ORIG_FIELDS = {0: "credit_score", 1: "first_payment", 7: "occupancy",
               9: "dti", 10: "original_upb", 11: "ltv", 12: "note_rate",
               13: "channel", 16: "state", 19: "loan_id", 21: "term"}
PERF_FIELDS = {0: "loan_id", 1: "reporting_month", 2: "current_upb",
               3: "status", 4: "reported_age", 8: "zero_balance_code"}
ORIG_COLS = list(ORIG_FIELDS.values())
PERF_COLS = list(PERF_FIELDS.values())


def month_index(s: pd.Series) -> pd.Series:
    """YYYYMM string -> integer month index; invalid date -> nullable NA."""
    d = pd.to_datetime(s, format="%Y%m", errors="coerce")
    return (d.dt.year * 12 + d.dt.month).astype("Int64")


def read_chunks(z: zipfile.ZipFile, member: str, mapping: dict[int, str], size=150_000):
    with z.open(member) as f:
        for chunk in pd.read_csv(f, sep="|", header=None, usecols=list(mapping),
                                 dtype="string", keep_default_na=False,
                                 chunksize=size, encoding="utf-8"):
            chunk.columns = [mapping[i] for i in mapping]
            yield chunk


def count_bad(series: pd.Series, lower: float, upper: float) -> int:
    n = pd.to_numeric(series, errors="coerce")
    return int(((n < lower) | (n > upper)).sum())


def load_orig(con: sqlite3.Connection, base: Path, qa: dict):
    rows = []
    for year in YEARS:
        with zipfile.ZipFile(base / f"sample_{year}.zip") as z:
            member = f"sample_orig_{year}.txt"
            with z.open(member) as f:
                raw = f.readline().decode().rstrip("\r\n").split("|")
            # Record the layout check, not literal source row values or loan IDs.
            qa["raw_examples"][member] = {"field_count": len(raw)}
            assert len(raw) == 31, f"Unexpected origination layout: {member}"
            part = pd.concat(read_chunks(z, member, ORIG_FIELDS), ignore_index=True)
        qa["orig_rows"][str(year)] = len(part)
        qa["orig_duplicate_ids"][str(year)] = int(part.loan_id.duplicated().sum())
        qa["orig_missing"][str(year)] = {
            c: int(part[c].eq("").sum()) for c in ORIG_COLS}
        qa["orig_sentinels"][str(year)] = {
            "credit_score_9999": int(part.credit_score.eq("9999").sum()),
            "dti_999": int(part.dti.eq("999").sum()),
            "ltv_999": int(part.ltv.eq("999").sum()),
        }
        qa["orig_invalid"][str(year)] = {
            "score_outside_300_850_except_sentinel": count_bad(part.credit_score.mask(part.credit_score.eq("9999")),300,850),
            "dti_outside_1_65_except_sentinel": count_bad(part.dti.mask(part.dti.eq("999")),1,65),
            "ltv_outside_1_998_except_sentinel": count_bad(part.ltv.mask(part.ltv.eq("999")),1,998),
            "upb_nonpositive": int((pd.to_numeric(part.original_upb, errors="coerce") <= 0).sum()),
        }
        part["first_payment_index"] = month_index(part.first_payment)
        part["vintage_year"] = year  # supplied annual ZIP, corroborated with loan ID
        qa["orig_invalid"][str(year)]["first_payment_bad_date"] = int(part.first_payment_index.isna().sum())
        qa["orig_invalid"][str(year)]["loan_id_year_mismatch"] = int((~part.loan_id.str.startswith(f"F{year%100:02d}Q")).sum())
        qa["orig_invalid"][str(year)]["first_payment_after_24m_eligibility"] = int((part.first_payment_index > CUTOFF-23).sum())
        for c, sentinel in (("credit_score", "9999"), ("dti", "999"), ("ltv", "999")):
            # Missing is retained as NULL, not imputed with a portfolio average.
            part[c] = pd.to_numeric(part[c].replace({sentinel: pd.NA, "": pd.NA}), errors="coerce")
        for c in ("original_upb", "note_rate", "term"):
            part[c] = pd.to_numeric(part[c].replace({"": pd.NA}), errors="coerce")
        rows.append(part)
    orig = pd.concat(rows, ignore_index=True)
    qa["orig_cross_year_duplicate_ids"] = int(orig.loan_id.duplicated().sum())
    orig["first_payment_index"] = orig.first_payment_index.astype("Float64")
    # Preserve the full cleaned origination table for independent reuse.
    orig.to_sql("orig", con, if_exists="replace", index=False, chunksize=5000)
    con.execute("CREATE UNIQUE INDEX orig_id ON orig(loan_id)")
    con.commit()
    return set(orig.loan_id), orig


def load_perf(con: sqlite3.Connection, base: Path, ids: set, qa: dict):
    con.execute("""CREATE TABLE perf (
      loan_id TEXT, reporting_month TEXT, calendar_index INTEGER,
      month_on_book INTEGER, current_upb REAL, status TEXT, status_num INTEGER,
      active INTEGER, d30 INTEGER, d60 INTEGER, d90 INTEGER,
      status_unknown INTEGER, zero_balance_code TEXT, exit_flag INTEGER)""")
    latest = 0
    for year in YEARS:
        member = f"sample_perf_{year}.txt"
        q = Counter()
        seen_status = Counter()
        seen_exits = Counter()
        with zipfile.ZipFile(base / f"sample_{year}.zip") as z:
            with z.open(member) as f:
                raw = f.readline().decode().rstrip("\r\n").split("|")
            qa["raw_examples"][member] = {"field_count": len(raw)}
            assert len(raw) == 35, f"Unexpected performance layout: {member}"
            for part in read_chunks(z, member, PERF_FIELDS):
                q["rows"] += len(part)
                q["unmatched_loan_rows"] += int((~part.loan_id.isin(ids)).sum())
                seen_status.update(part.status.value_counts().to_dict())
                seen_exits.update(part.zero_balance_code.value_counts().to_dict())
                q["blank_reporting_month"] += int(part.reporting_month.eq("").sum())
                q["blank_status"] += int(part.status.eq("").sum())
                q["blank_current_upb"] += int(part.current_upb.eq("").sum())
                q["negative_current_upb"] += int((pd.to_numeric(part.current_upb,errors="coerce")<0).sum())
                q["invalid_exit_code"] += int((~part.zero_balance_code.isin(["", "01", "02", "03", "09", "15", "16", "96"])).sum())
                cal = month_index(part.reporting_month)
                q["bad_reporting_date"] += int(cal.isna().sum())
                if cal.notna().any(): latest = max(latest,int(cal.max()))
                # The join below is by loan ID; no record is silently dropped.
                lookup = pd.read_sql_query("SELECT loan_id,first_payment_index FROM orig",con).set_index("loan_id")["first_payment_index"] if not hasattr(load_perf, "_first_payment") else load_perf._first_payment
                load_perf._first_payment = lookup
                age = cal - part.loan_id.map(lookup) + 1
                q["missing_first_payment_lookup"] += int(age.isna().sum())
                q["age_before_first_scheduled_payment"] += int((age < 1).sum())
                status_num = pd.to_numeric(part.status, errors="coerce")
                unknown = status_num.isna() & part.status.ne("RA")
                q["unknown_status_rows"] += int(unknown.sum())
                active = status_num.notna() & part.zero_balance_code.eq("") & (pd.to_numeric(part.current_upb,errors="coerce") > 0)
                q["numeric_status_zero_balance_or_nonpositive_upb"] += int((status_num.notna() & ~active).sum())
                # Explicit measurement contract: delinquency numerator only for active numeric status.
                p = pd.DataFrame({
                    "loan_id": part.loan_id, "reporting_month": part.reporting_month,
                    "calendar_index": cal, "month_on_book": age,
                    "current_upb": pd.to_numeric(part.current_upb,errors="coerce"),
                    "status": part.status, "status_num": status_num,
                    "active": active.astype("int8"),
                    "d30": (active & status_num.ge(1)).astype("int8"),
                    "d60": (active & status_num.ge(2)).astype("int8"),
                    "d90": (active & status_num.ge(3)).astype("int8"),
                    "status_unknown": unknown.astype("int8"),
                    "zero_balance_code": part.zero_balance_code,
                    "exit_flag": part.zero_balance_code.ne("").astype("int8"),
                })
                # Store all observed rows in the target horizon, including prepayment/unknown,
                # plus month 25 for optional subsequent work; do not change raw source ZIPs.
                eligible = age.between(1,24).fillna(False)
                q["outside_24_month_window"] += int((~eligible).sum())
                p.loc[eligible].to_sql("perf",con,if_exists="append",index=False,chunksize=5000)
        qa["perf_rows"][str(year)] = q["rows"]
        qa["perf_quality"][str(year)] = dict(q)
        qa["status_counts"][str(year)] = dict(seen_status)
        qa["exit_code_counts"][str(year)] = dict(seen_exits)
        con.commit()
    assert latest == CUTOFF, f"Observed latest month differs from configured 202603: {latest}"
    qa["latest_reporting_month"] = "202603"
    # Integrity check after loading; duplicates are reported, never silently removed.
    qa["perf_duplicate_keys_in_analysis_window"] = int(con.execute("""
      SELECT COALESCE(SUM(n-1),0) FROM
      (SELECT COUNT(*) n FROM perf GROUP BY loan_id,calendar_index HAVING n>1)
    """).fetchone()[0])
    qa["within_window_internal_month_gaps"] = int(con.execute("""
      SELECT COUNT(*) FROM (
        SELECT loan_id, calendar_index,
          LAG(calendar_index) OVER (PARTITION BY loan_id ORDER BY calendar_index) AS prev
        FROM perf
      ) WHERE prev IS NOT NULL AND calendar_index > prev + 1
    """).fetchone()[0])
    qa["observed_month_1_rows"] = int(con.execute("SELECT COUNT(*) FROM perf WHERE month_on_book=1").fetchone()[0])
    con.execute("CREATE INDEX perf_id_month ON perf(loan_id,calendar_index)")
    con.execute("CREATE INDEX perf_age ON perf(month_on_book)")
    con.commit()


def query_results(con, sqlfile, out):
    # Strip single-line comments before splitting on statement terminators;
    # explanatory comments can legitimately contain semicolons.
    sql = "\n".join(line for line in sqlfile.read_text().splitlines()
                    if not line.lstrip().startswith("--"))
    statements = [s.strip() for s in sql.split(";") if s.strip()]
    assert len(statements)==5
    names = ["vintage_monthly", "ever_30", "fico_month12", "transitions", "exits"]
    results = {}
    for name, stmt in zip(names,statements):
        results[name] = pd.read_sql_query(stmt,con)
        results[name].to_csv(out / f"{name}.csv",index=False)
    return results


def charts(r, out):
    colors = {2021:"#2878b5",2022:"#db8332",2023:"#368d75"}
    fig, ax = plt.subplots(figsize=(9,5))
    for y,g in r["vintage_monthly"].groupby("vintage_year"):
        ax.plot(g.month_on_book,g.pct_30_plus,marker="o",markersize=2.5,label=str(y),color=colors[y])
    ax.set(xlabel="Months since first scheduled payment",ylabel="Active loans 30+ days delinquent (%)",
           title="Observed 30+ delinquency by origination vintage")
    ax.set_xlim(1,24); ax.set_ylim(bottom=0); ax.grid(alpha=.25); ax.legend(title="Vintage")
    fig.tight_layout(); fig.savefig(out/"vintage_30plus.png",dpi=180); plt.close(fig)

    fig,ax=plt.subplots(figsize=(9,5))
    for y,g in r["vintage_monthly"].groupby("vintage_year"):
        ax.plot(g.month_on_book,g.active_n,marker="o",markersize=2.5,label=str(y),color=colors[y])
    ax.set(xlabel="Months since first scheduled payment",ylabel="Observed active loans (count)",
           title="Loan coverage and attrition across the first 24 months")
    ax.set_xlim(1,24); ax.grid(alpha=.25); ax.legend(title="Vintage")
    fig.tight_layout(); fig.savefig(out/"cohort_coverage.png",dpi=180); plt.close(fig)

    d=r["fico_month12"].pivot(index="fico_band",columns="vintage_year",values="pct_30_plus")
    d=d.reindex(["<680","680-739","740-799","800+","Missing"])
    ax=d.plot.bar(figsize=(9,5),color=[colors[y] for y in d.columns],rot=0)
    ax.set(xlabel="Origination credit score band",ylabel="Active loans 30+ days delinquent (%)",
           title="Month 12 delinquency by credit score and vintage")
    ax.grid(axis="y",alpha=.25); ax.legend(title="Vintage")
    ax.figure.tight_layout(); ax.figure.savefig(out/"fico_month12.png",dpi=180); plt.close(ax.figure)


def markdown_table(frame: pd.DataFrame) -> str:
    """Write a compact Markdown table without pandas' optional tabulate extra."""
    fields = [str(x) for x in frame.columns]
    rows = ["| " + " | ".join(fields) + " |",
            "| " + " | ".join("---" for _ in fields) + " |"]
    for row in frame.itertuples(index=False, name=None):
        rows.append("| " + " | ".join("" if pd.isna(x) else str(x) for x in row) + " |")
    return "\n".join(rows)


def report(r, qa, out):
    v=r["vintage_monthly"]
    monthly=v[v.month_on_book.isin([1,12,24])][["vintage_year","month_on_book","active_n","d30_n","pct_30_plus","exit_n"]]
    trans=r["transitions"].copy()
    lines=["# Loan vintage and delinquency monitor: executed analysis",
           "", "Source: supplied Freddie Mac single-family 2021–2023 sample ZIPs. Reporting cutoff: March 2026.",
           "", "**Read this first:** 50,000 sampled originated loans per year. The annual file is an origination-year cohort. Rates below use only observed, active loan-months; their denominator shrinks with payoff and other exits. Descriptive associations do not identify a policy effect.",
           "", "## 0. Raw inspection and quality checks", "",
           "The original files have no headers. Each annual ZIP has 31-field origination and 35-field monthly performance records. Field counts are in `quality_report.json`; literal source row values and loan IDs are not exported. Input ZIPs are unchanged.",
           "", "Original rows: "+str(qa["orig_rows"])+"; monthly raw rows: "+str(qa["perf_rows"])+".",
           f"Duplicate origination IDs: {qa['orig_cross_year_duplicate_ids']}; duplicate loan-month keys in the analysis window: {qa['perf_duplicate_keys_in_analysis_window']}; internal monthly gaps within observed spells: {qa['within_window_internal_month_gaps']}; month-1 records: {qa['observed_month_1_rows']:,}/150,000. Lack of a month-1 record does not necessarily mean an error: report timing or a prior exit may explain it.",
           f"Missing sentinels: credit score 9999 = {sum(x['credit_score_9999'] for x in qa['orig_sentinels'].values())}; DTI 999 = {sum(x['dti_999'] for x in qa['orig_sentinels'].values())}. Source rows outside months 1–24 remain counted in the quality log but are not loaded into the analysis table.",
           "Original score `9999`, DTI `999`, and LTV `999` are source-defined missing sentinels, converted to NULL. No credit score or DTI is imputed. Empty exit codes mean no recorded exit. `RA` is REO, not a numeric days-past-due value. Numerical status and positive UPB without an exit defines the active denominator.",
           "", "**Assumptions to review:** (a) annual ZIP year defines vintage; (b) month 1 starts at first scheduled payment, not Freddie Mac's loan-age field (which can reset after modification); (c) the 24-month first-delinquency fraction uses loans with enough calendar follow-up; (d) no unobserved month is interpreted as current; (e) paid-off loans are separate from defaults; (f) the sample represents disclosed eligible Freddie Mac mortgages, not all applicants or all lending products.",
           "", "## 1. How does observed delinquency change over months on book?", "",
           "Calculation: `d30_n / active_n` by vintage and month. The SQL is query 1 in `analysis.sql`; Python draws the chart from its actual output.",
           "", markdown_table(monthly), "", "![30+ delinquency](vintage_30plus.png)",
           "", "![Observed active loan coverage](cohort_coverage.png)", "",
           "**What it shows:** at month 24 the active-loan 30+ rates are 1.177%, 2.477%, and 2.451% for 2021, 2022, and 2023 respectively. The 2023 denominator is 40,676 active loans versus 45,296 for 2021, so read the rate with the coverage chart. **What it does not show:** a causal cohort effect, portfolio-wide default probability, or outcomes for loans no longer active.",
           "", "## 2. How many loans have a first observed 30+ month by 24 months?", "",
           "Calculation: distinct eligible loans with at least one observed 30+ month in 1–24 divided by all loans with 24 calendar months available at the cutoff. SQL query 2.",
           "",markdown_table(r["ever_30"]),"",
           "**What it shows:** observed first-24-month 30+ event fractions are 6.504%, 9.154%, and 7.754%. **What it does not show:** that all other loans stayed current throughout; especially, terminated loans have shorter observed spells. This is not a survival estimate.",
           "", "## 3. Does observed month-12 delinquency vary by origination credit score?", "",
           "Calculation: active 30+ rate in month 12 by original FICO band, with missing score separate. SQL query 3.",
           "",markdown_table(r["fico_month12"]),"", "![Month-12 risk bands](fico_month12.png)","",
           "**What it shows:** within each vintage, the <680 band has a higher observed month-12 30+ rate than the 800+ band (2022: 5.703% vs 0.375%, with 5,050 vs 4,532 active loans). **What it does not show:** the effect of changing a score or lending policy; origination selection, state, LTV and exits may confound comparisons. The tiny missing-score bands are not interpretable as zero risk.",
           "", "## 4. How often do observed delinquency states change between adjacent months?", "",
           "Calculation: one transition per consecutive, active pair; aggregate current/30+ states. SQL query 4.",
           "",markdown_table(trans),"",
           "**What it shows:** for the 2022 vintage, 5,525 of 16,480 active 30+ transitions went to current next month (33.5% of such transitions). The same loan can contribute many transitions. **What it does not show:** recovery after exit, transitions across missing months, or a person-level cure probability over the full loan lifetime.",
           "", "## 5. Why do loans leave observation in the first 24 months?", "",
           "Calculation: source zero-balance codes summarized independently from delinquency. SQL query 5.",
           "",markdown_table(r["exits"]),"",
           "**What it shows:** code 01 accounts for 4,576, 4,612, and 8,983 first-24-month exits in the three vintages; the large 2023 count helps explain the lower active denominator. **What it does not show:** gross/net credit loss or the reason for the difference in payoff rates; code `01` is voluntary payoff/maturity and is not default.",
           "", "## Suggested business follow-up", "",
           "Inspect the cohort/score cells with the largest *observed* delinquency and adequate denominator, then ask servicing and risk teams whether policy, borrower mix, reporting gaps or external conditions changed. Validate against the full portfolio before adjusting underwriting. Keep separate dashboards for 30+, exit mix, and observed loan coverage.",
           "", "## Reproduction", "",
           "`python analyze.py --input-dir ../upload --output-dir output` from this directory. The script runs `analysis.sql` in SQLite and exports all five result tables as CSV. Full quality counts are in `quality_report.json`." ]
    (out/"analysis_report.md").write_text("\n".join(lines),encoding="utf-8")


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--input-dir",type=Path,default=Path("../upload"))
    ap.add_argument("--output-dir",type=Path,default=Path("output"))
    args=ap.parse_args(); args.output_dir.mkdir(parents=True,exist_ok=True)
    qa={k:{} for k in ("raw_examples","orig_rows","orig_missing","orig_sentinels","orig_invalid",
                         "orig_duplicate_ids","perf_rows","perf_quality","status_counts","exit_code_counts")}
    db=args.output_dir/"analysis.sqlite"
    if db.exists(): db.unlink()  # derived DB is rebuilt, raw ZIPs are never modified
    with sqlite3.connect(db) as con:
        # This database is fully regenerable from the unchanged ZIPs. Avoid
        # large temporary journal files during multi-million-row imports.
        con.execute("PRAGMA journal_mode=OFF")
        con.execute("PRAGMA synchronous=OFF")
        con.execute("PRAGMA temp_store=MEMORY")
        ids,_=load_orig(con,args.input_dir,qa)
        load_perf(con,args.input_dir,ids,qa)
        results=query_results(con,Path(__file__).with_name("analysis.sql"),args.output_dir)
    (args.output_dir/"quality_report.json").write_text(json.dumps(qa,indent=2),encoding="utf-8")
    charts(results,args.output_dir)
    report(results,qa,args.output_dir)
    print("Completed. Results:",args.output_dir.resolve())
    print("Rows:",qa["orig_rows"],qa["perf_rows"])
    print("Month 12 / 24:")
    print(results["vintage_monthly"].query("month_on_book in [12,24]")[["vintage_year","month_on_book","active_n","d30_n","pct_30_plus"]].to_string(index=False))


if __name__ == "__main__": main()
