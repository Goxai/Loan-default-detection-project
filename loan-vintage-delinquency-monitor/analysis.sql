-- Freddie Mac sample, 2021–2023. SQLite dialect. Populated by analyze.py.
-- The analytical month is 1 + months(reporting_month - first_payment_month).
-- These are descriptive comparisons of sampled, acquired mortgages, not causal tests.

-- 1. Cohort coverage and point-in-time 30+/60+/90+ among observed ACTIVE loans.
-- Terminal rows, REO, and missing statuses remain in the data but outside the rate denominator.
SELECT o.vintage_year, p.month_on_book,
       COUNT(*) AS observed_rows,
       SUM(p.active) AS active_n,
       SUM(p.d30) AS d30_n, SUM(p.d60) AS d60_n, SUM(p.d90) AS d90_n,
       SUM(p.exit_flag) AS exit_n,
       SUM(CASE WHEN p.status_unknown=1 THEN 1 ELSE 0 END) AS unknown_n,
       ROUND(100.0*SUM(p.d30)/NULLIF(SUM(p.active),0),3) AS pct_30_plus,
       ROUND(100.0*SUM(p.d60)/NULLIF(SUM(p.active),0),3) AS pct_60_plus,
       ROUND(100.0*SUM(p.d90)/NULLIF(SUM(p.active),0),3) AS pct_90_plus
FROM perf p JOIN orig o ON p.loan_id=o.loan_id
WHERE p.month_on_book BETWEEN 1 AND 24
GROUP BY o.vintage_year,p.month_on_book
ORDER BY o.vintage_year,p.month_on_book;

-- 2. First observed 30+ in months 1–24: event count / all loans whose first
-- payment gives them 24 calendar months by the data cutoff. A missing month
-- may hide a first delinquency, so this is an observed-event fraction.
WITH eligible AS (
  SELECT * FROM orig WHERE first_payment_index <= (2026*12+3)-23
), firsts AS (
  SELECT loan_id, MIN(month_on_book) AS first_30_month
  FROM perf WHERE month_on_book BETWEEN 1 AND 24 AND d30=1
  GROUP BY loan_id
)
SELECT e.vintage_year, COUNT(*) AS eligible_loans,
       SUM(CASE WHEN f.first_30_month IS NOT NULL THEN 1 ELSE 0 END) AS ever_30_n,
       ROUND(100.0*SUM(CASE WHEN f.first_30_month IS NOT NULL THEN 1 ELSE 0 END)
             / COUNT(*),3) AS pct_ever_30_observed
FROM eligible e LEFT JOIN firsts f ON e.loan_id=f.loan_id
GROUP BY e.vintage_year ORDER BY e.vintage_year;

-- 3. Risk segmentation using attributes known at origination. Month 12 only,
-- to avoid repeatedly counting the same loan. Null score has its own bucket.
SELECT o.vintage_year,
       CASE WHEN o.credit_score IS NULL THEN 'Missing'
            WHEN o.credit_score < 680 THEN '<680'
            WHEN o.credit_score < 740 THEN '680-739'
            WHEN o.credit_score < 800 THEN '740-799'
            ELSE '800+' END AS fico_band,
       COUNT(*) AS observed_rows, SUM(p.active) AS active_n,
       SUM(p.d30) AS d30_n,
       ROUND(100.0*SUM(p.d30)/NULLIF(SUM(p.active),0),3) AS pct_30_plus
FROM orig o JOIN perf p ON p.loan_id=o.loan_id
WHERE p.month_on_book=12
GROUP BY o.vintage_year,fico_band ORDER BY o.vintage_year,fico_band;

-- 4. Next-month transitions for adjacent OBSERVED active rows in months 1–24.
-- Current -> 30+ is deterioration; 30+ -> current is a cure. Missing months
-- and loan exits are not classified as cures.
WITH ordered AS (
  SELECT p.*,
         LEAD(calendar_index) OVER (PARTITION BY loan_id ORDER BY calendar_index) AS next_month,
         LEAD(active) OVER (PARTITION BY loan_id ORDER BY calendar_index) AS next_active,
         LEAD(d30) OVER (PARTITION BY loan_id ORDER BY calendar_index) AS next_d30
  FROM perf p WHERE month_on_book BETWEEN 1 AND 24
), transitions AS (
  SELECT o.vintage_year,
         CASE WHEN x.d30=0 THEN 'Current to next month'
              ELSE '30+ to next month' END AS from_group,
         CASE WHEN x.next_d30=1 THEN '30+' ELSE 'Current' END AS to_group
  FROM ordered x JOIN orig o ON o.loan_id=x.loan_id
  WHERE x.active=1 AND x.next_active=1 AND x.next_month=x.calendar_index+1
)
SELECT vintage_year,from_group,to_group,COUNT(*) AS transition_n
FROM transitions GROUP BY vintage_year,from_group,to_group
ORDER BY vintage_year,from_group,to_group;

-- 5. Exit reason in months 1–24 by vintage. 01 is voluntary payoff/maturity,
-- never a delinquency or default. Other exit categories are shown distinctly.
SELECT o.vintage_year, p.zero_balance_code,
       CASE p.zero_balance_code WHEN '01' THEN 'Prepaid/matured'
            WHEN '02' THEN 'Third-party sale' WHEN '03' THEN 'Short sale/charge-off'
            WHEN '09' THEN 'REO disposition' WHEN '15' THEN 'Whole-loan sale'
            WHEN '16' THEN 'Reperforming securitization' WHEN '96' THEN 'Defect'
            ELSE 'Other code' END AS exit_type,
       COUNT(*) AS exits
FROM perf p JOIN orig o ON o.loan_id=p.loan_id
WHERE p.month_on_book BETWEEN 1 AND 24 AND p.exit_flag=1
GROUP BY o.vintage_year,p.zero_balance_code
ORDER BY o.vintage_year,exits DESC;
