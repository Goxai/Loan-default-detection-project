# Loan Vintage and Delinquency Monitor

**Domain:** U.S. mortgage portfolio risk  
**Tools:** Python, pandas, NumPy, Matplotlib, SQL (SQLite)  
**Scope:** Freddie Mac Single-Family Loan-Level Dataset sample, 2021–2023 origination vintages; monthly performance available through March 2026  
**Code:** [`analyze.py`](analyze.py) · [`analysis.sql`](analysis.sql) · [quality checks](output/quality_report.json)

## 1. Executive Summary

I built a 24-month vintage monitor for 150,000 sampled mortgages to compare observed delinquency, transitions, and loan exits at comparable months since the first scheduled payment. At month 24, 30+ delinquency among **observed active loans** was **1.177%** for the 2021 vintage, **2.477%** for 2022, and **2.451%** for 2023. The 2022 cohort also had the highest fraction of loans with a first **observed** 30+ month within the horizon (**9.154%**, versus **6.504%** in 2021 and **7.754%** in 2023). These are descriptive sample results. They justify further investigation, not a claim that a policy or economic event caused the differences.

## 2. Business Problem

A lending risk team needs to spot changing credit performance early while distinguishing delinquency from voluntary payoff and other exits. A headline delinquency rate can mislead if loans from different vintages have different seasoning or if the active population shrinks.

## 3. Business Context

This is a **portfolio case study**, not an analysis commissioned by Freddie Mac or an assessment of an actual lender's policy. The hypothetical stakeholder is a mortgage portfolio risk manager reviewing originated loans. The sample covers selected Freddie Mac single-family mortgages; it does not contain declined applications or represent every lending product or borrower.

## 4. Objectives

1. Compare 2021–2023 origination vintages at the same months since first scheduled payment.
2. Measure point-in-time 30+ delinquency and first observed 30+ occurrence over 24 months.
3. Examine credit-score segments and adjacent-month delinquency transitions.
4. Separate voluntary payoffs and other exits from delinquency, and show the changing active denominator.

## 5. Dataset and Data Sources

- **Source:** [Freddie Mac Single-Family Loan-Level Dataset](https://www.freddiemac.com/research/datasets/sf-loanlevel-dataset) and its [General User Guide](https://www.freddiemac.com/fmac-resources/research/pdf/user_guide.pdf).
- **Files analyzed:** user-supplied `sample_2021.zip`, `sample_2022.zip`, and `sample_2023.zip`; each contains a headerless, pipe-delimited origination file and monthly performance file. Source ZIPs are not redistributed here.
- **Grain:** one origination row per loan; one performance row per loan per observed reporting month.
- **Volume:** 50,000 originations per year (**150,000 total**) and **6,030,021** raw performance rows. The first-24-month analytical table contains **3,398,838** observed records; rows outside that scope remain counted in the quality log.
- **Relevant fields:** loan ID, first-payment month, original credit score, DTI, LTV, note rate, original balance, state, loan term; reporting month, current balance, delinquency status, and zero-balance exit code.

## 6. Data Quality and Cleaning

The workflow inspects raw records and asserts the supplied file widths (**31 origination fields; 35 performance fields**) before assigning documented positions. It verifies the origination-to-performance join, dates, score and ratio ranges, exit codes, and balances. It found **zero duplicate origination IDs** and **zero duplicate loan-month keys within the analysis window**. All performance loan IDs matched an origination ID. Within observed 24-month spells, there were **zero internal monthly gaps**; only **148,408 of 150,000** loans had an observed month-1 record, so absence at the start is not treated as evidence of a current loan.

Source missing-value codes were handled explicitly: credit score `9999` occurred **32** times and DTI `999` **14** times. These became null; no score or DTI was imputed. Missing-score loans remain in a separate analysis band. Records with an exit code or REO status are retained, but excluded from the *active delinquency-rate denominator*. Source rows outside months 1–24 were counted and left out of this defined analysis window; no source ZIP was edited. See [`quality_report.json`](output/quality_report.json) for counts by year.

## 7. Methodology / Analytical Approach

- **Vintage:** origination year represented by the supplied annual sample, corroborated by loan IDs.
- **Month on book:** calendar months from the first scheduled payment, with that month numbered 1. This avoids relying on the source loan-age field, which may reset after a modification.
- **Active 30+ rate:** active loans with numeric delinquency status of at least `1` divided by observed active loans at that month on book. Active means positive current balance, numeric status, and no zero-balance exit code; `1` represents 30–59 days delinquent.
- **First observed 30+:** distinct loans with a 30+ record during months 1–24 divided by loans whose first-payment date permits 24 calendar months by the March 2026 cutoff. There are **50,000**, **49,998**, and **49,964** eligible loans by vintage. This fraction is **not** a survival estimate: payoff or another exit can shorten observation.
- **Transitions:** consecutive observed *active-to-active* months, grouped as current or 30+. One loan may contribute multiple transitions.
- **Exits:** source zero-balance codes counted separately. Code `01` is prepaid or matured, **not default**.

The workflow stages the analytical tables in SQLite, executes five documented queries in [`analysis.sql`](analysis.sql), and exports their results as CSV for review or BI use.

## 8. Exploratory Data Analysis

The analysis checks the number of active loans and observed exits at each loan age before comparing rates. For example, 2023 had **49,377** active loans at month 1 and **40,676** at month 24; 2021 had **49,411** and **45,296**, respectively. Thus, the month-24 rates describe different remaining populations. Original score mix also differs: the number of below-680 loans at origination was **4,060** in 2021, **5,346** in 2022, and **4,008** in 2023. These observations motivate segmented comparisons; they do not explain all of the vintage gap.

## 9. Key Findings

| Finding | Observed result | Interpretation boundary |
| --- | --- | --- |
| Later vintage delinquency | At month 24, active 30+ rates were **1.177% (2021)**, **2.477% (2022)**, and **2.451% (2023)**. | Different calendar conditions, origination mix, and exits may contribute; the result does not establish cause. |
| First observed 30+ | Within 24 months: **3,252 / 50,000 (6.504%)** in 2021; **4,577 / 49,998 (9.154%)** in 2022; **3,874 / 49,964 (7.754%)** in 2023. | A loan without an observed event might have exited before 24 months. |
| Score segmentation | At month 12 in 2022, **288 / 5,050 (5.703%)** active loans below 680 were 30+, versus **17 / 4,532 (0.375%)** at 800+. | An unadjusted association among already originated, active loans; not an estimate of a cutoff change's impact. |
| Monthly transitions | Of the 2022 active 30+ transitions, **5,525 / 16,480 (33.53%)** were current in the next observed month. Corresponding shares: **42.09%** in 2021, **29.04%** in 2023. | Repeated monthly pairs, not distinct-loan cure probabilities or evidence about collections effectiveness. |
| Exit mix | Code `01` payoffs/maturities in months 1–24: **4,576 (2021)**, **4,612 (2022)**, **8,983 (2023)**. | Payoff is not default; this count alone does not explain *why* 2023 had more exits. |

At month 12, the 2022–2021 30+ gap was **0.750 percentage points**. A descriptive standardization using the 2021 score-band rates associates about **0.114 points** of that gap with the observed score-band mix and **0.636 points** with differences within bands under that specific weighting. This is a sensitivity check, **not** a causal decomposition; other attributes and selection into the active population remain unadjusted.

## 10. Visualizations

**30+ delinquency by vintage.** Rates are calculated among observed active loans, aligned on months since first payment.

![Observed active 30+ delinquency by vintage](output/vintage_30plus.png)

**Active-loan coverage.** Read this alongside the rate chart; the denominator falls over time.

![Observed active loan counts by vintage](output/cohort_coverage.png)

**Original credit-score bands at month 12.** The chart shows unadjusted rate differences and should be read with the cell counts in [`fico_month12.csv`](output/fico_month12.csv).

![Observed month-12 30+ delinquency by score band](output/fico_month12.png)

## 11. Business Insights

- The **2022 vintage** deserves a focused review: it has both a higher month-24 active 30+ rate than 2021 and more distinct loans with an observed 30+ event in the first 24 months.
- **Credit score is useful for monitoring**, but a score-band association cannot establish the effect of changing approval policy. Both mix and within-band performance need investigation.
- The **2023 active population contracts more**, with substantially more recorded payoffs/maturities. Exit monitoring is necessary to interpret its delinquency rate.
- Transition counts raise a **collections question**, but they do not measure treatment effectiveness without an appropriate comparison and treatment information.

## 12. Recommendations

1. **Publish a vintage monitor with rates, numerators, active-loan counts, and exits together.** The observed 2023 payoff count and falling active denominator show why a rate alone is insufficient.
2. **Investigate the 2022 cohort within comparable loan segments before changing underwriting.** Its observed month-24 30+ rate and first-30+ fraction exceed 2021's; score mix differs, while the descriptive score-only comparison leaves a within-band gap. Add LTV, term, state, first-payment quarter, and other available origination factors.
3. **Track first 30+ entry and subsequent transitions separately.** The 2022 cohort has the highest first observed 30+ fraction, while active-to-active transition patterns vary by vintage. Separate metrics can focus review on entry into delinquency versus persistence or return to current.
4. **Audit the 2023 exit pattern before interpreting cross-vintage risk as a portfolio forecast.** It recorded 8,983 payoff/maturity exits versus 4,612 in 2022. Review exit timing and composition; do not count code `01` as a credit loss.

These are monitoring and investigation recommendations. No financial benefit, policy effect, or expected loss saving has been estimated.

## 13. Limitations

- **Selection and scope:** sampled, acquired Freddie Mac mortgages; no rejected applications or full lending-market population. Results do not transfer automatically to SME, unsecured, or consumer loans.
- **Comparability:** origination year and calendar environment change together. Cohort differences are observational, not causal.
- **Changing risk set:** payoff and other exits remove loans from later active-rate denominators. The first-observed-30+ fraction is not a competing-risk-adjusted cumulative incidence estimate.
- **Outcome scope:** 30+ is an early delinquency indicator, not default or realized credit loss. No loss/financial impact analysis was completed.
- **Transition scope:** only adjacent active months are counted; exits and repeated transitions require separate interpretation.
- **Data handling:** observed records from months outside 1–24 are excluded from analytical tables by design. The 2024 and 2025 supplied vintages were not analyzed here.

## 14. Possible Next Steps

1. Standardize vintage comparisons jointly for score, LTV, term, state, first-payment quarter, and occupancy; show cell sizes.
2. Model first 30+ and payoff as competing outcomes, with explicit time at risk and an appropriate observation cutoff.
3. Review monthly transitions by starting severity (30, 60, 90+), loan age, and modification status, with exits as a separate next state.
4. Validate any proposed action against a fuller portfolio and its underwriting, servicing, and loss data before estimating a policy impact.
5. Import the exported CSV results into Power BI and document the same denominators and exit definitions in the dashboard.

## 15. Technical Skills Demonstrated

- Inspecting and parsing compressed, headerless loan files with an explicit field map.
- Data-quality checks for keys, dates, sentinels, ranges, joins, and source-vs-analysis row counts.
- Memory-conscious Python loading; reusable functions, nullable types, and reproducible outputs.
- SQL joins, conditional aggregation, cohort metrics, and window functions (`LEAD`) for transitions.
- Labeled Python visualizations and business interpretation with clear denominators and limitations.

### Verify or add before publishing

- Replace the project URL and author/profile details if you want them in the GitHub repository. Confirm that `CASE_STUDY.md`, `analyze.py`, `analysis.sql`, and the `output/` images and small CSV/JSON files are placed together so relative links render.
- Verify the precise release/version and permitted attribution or redistribution terms for the ZIPs you downloaded. Link readers to Freddie Mac's download page; do not upload source ZIPs without checking the terms.
- If you claim a policy, collections, or financial impact in a résumé or interview, add the required comparison, business data, and validated result first. None is established by this case study.
