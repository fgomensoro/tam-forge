---
date: 2026-09-15
type: study-note
future-app-source: true
flashcard-source: true
status: in-progress
actual-focused-minutes: unknown
---

# SQL Browser Practice

## Evidence and assistance

Cities With Completed Trades: learner reported solved after hints on SELECT versus GROUP BY, descending ordering and filtering completed trades. The supplied screenshot was of the earlier mismatched query; final acceptance/query not received. Do not label platform acceptance independently verified.

Average Review Ratings: supplied screenshot confirms Accepted, September 15 submission, with visible rows (8,50001,4.00), (9,69852,2.00), (10,50001,3.00), (10,69852,3.50). Coaching supplied EXTRACT, comma-separated GROUP BY and ROUND syntax. Explanation of product/month grouping required correction. Visible ORDER BY mth was accepted but does not satisfy the full requested secondary sort; coach supplied ORDER BY mth, product_id. Learner acknowledged; corrected execution not received. Screenshot clips the SELECT expression at the right; the following is a polished reference, not a verbatim extraction.

```sql
SELECT EXTRACT(MONTH FROM submit_date) AS mth,
       product_id,
       ROUND(AVG(stars), 2) AS avg_stars
FROM reviews
GROUP BY product_id, mth
ORDER BY mth, product_id;
```

This is coached practice, not a timed independent pass. Screen timer/submission timestamps do not establish focused duration. Date extraction/grouping does not complete the remaining date-filter requirement; grouped SUM remains pending.

## Validated lessons and cards

### Card 1
Q: Why does SELECT * usually fail when grouping trade rows by city?
A: Individual trade fields can have multiple values per city; select grouping columns and appropriate aggregates instead.

### Card 2
Q: Where should completed-trade filtering occur before counting per city?
A: WHERE filters individual trade rows before GROUP BY computes the city totals. WHERE filters rows; HAVING filters groups.

### Card 3
Q: How do you extract a numeric month in PostgreSQL?
A: EXTRACT(MONTH FROM submit_date). MONTH(submit_date) is not PostgreSQL's built-in syntax.

### Card 4
Q: How do you group by two dimensions?
A: Separate expressions with commas, such as GROUP BY product_id, mth, not AND. PostgreSQL permits an unambiguous output alias in GROUP BY; that does not imply aliases work in HAVING.

### Card 5
Q: Why group by both product and month for monthly product ratings?
A: Each product/month combination needs its own average. Grouping only by product merges months; selecting an ungrouped month then raises an error here.

### Card 6
Q: How do you round the average to two decimal places?
A: ROUND(AVG(stars), 2), for the numeric result in this exercise. It rounds to the nearest value rather than always upward.

### Card 7
Q: Does ORDER BY mth guarantee product order within a month?
A: No. Add product_id as a secondary key: ORDER BY mth, product_id.

## Next start

Select a DataLemur grouped-sum problem within the existing SQL allocation. Date-filter coverage remains open. No extra time or completion is inferred.
