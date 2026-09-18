---
date: 2026-09-10
type: study-note
language: English
status: validated
future-app-source: true
flashcard-source: true
assistance: post-attempt-guided-review
---

# SQL Missing Records and Conditional Aggregation

## Corrected and validated note

### Concise rule

Choose joins, NULL predicates, and aggregation to match the required rows and output shape.

### Plain-English explanation

LEFT JOIN preserves every left-side row; unmatched right-side columns are NULL in the query result, not inserted into the underlying table. IS NULL tests missing values specifically, not zero, false, or empty strings. Comparisons using = NULL evaluate to unknown; WHERE keeps true conditions. SUM(CASE...) counts matching rows by adding 1 or 0. Without GROUP BY, aggregates summarize the whole input; GROUP BY creates a result per grouping value.

### Practical TAM example

Find orders missing payments with an outer join; identify unfinished work through a missing completion timestamp; summarize successful and failed operations into separate columns with conditional aggregation.

## Validated exercises

### S3 — Page With No Likes

```sql
SELECT pages.page_id
FROM pages
LEFT OUTER JOIN page_likes
  ON pages.page_id = page_likes.page_id
WHERE page_likes.page_id IS NULL
ORDER BY pages.page_id;
```

Accepted screenshot: 20701 and 32728, matching expected output. Sorting qualification is a clarity edit to the learner's accepted query. Earlier accepted history was also visible, so this is successful repeat practice. Learner explanation was correct; review clarified that the NULLs are in the joined result.

### S4 — Unfinished Parts

```sql
SELECT part, assembly_step
FROM parts_assembly
WHERE finish_date IS NULL;
```

Accepted screenshot: bumper/3, bumper/4, engine/5. In this exercise NULL finish_date means an unfinished step. The learner initially confused NULL with falsy values and = NULL with exact equality; the distinction was corrected and a check confirmed only NULL is selected from 0, NULL, and 5.

### S5 — Laptop vs. Mobile Viewership

```sql
SELECT
  SUM(CASE WHEN device_type = 'laptop' THEN 1 ELSE 0 END) AS laptop_views,
  SUM(CASE WHEN device_type IN ('phone', 'tablet') THEN 1 ELSE 0 END) AS mobile_views
FROM viewership;
```

Accepted screenshot: laptop_views = 2, mobile_views = 3. CASE contributes 1 or 0 per row; SUM adds those contributions. No GROUP BY is required for one summary row. The learner understood the CASE contribution; GROUP BY semantics required correction. Grouping by device_type returns device-level rows; combining phone/tablet counts later is valid but adds aggregation and still needs the required output shape.

### Boundary or common mistake

GROUP BY does not inherently produce 0/1 groups: its chosen expression determines the groups. A category-based GROUP BY returning laptop/mobile rows differs from the exercise's two columns in one row. NULL is not a general falsy value. WHERE filters rows; HAVING filters groups.

### Card-ready Q/A

#### Card 1
Q: How does LEFT JOIN plus IS NULL find missing related records?
A: It preserves left-side rows and selects those whose right-side join key is NULL because no match exists.

#### Card 2
Q: Does IS NULL select zero, FALSE, or an empty string?
A: No. It selects NULL specifically.

#### Card 3
Q: Why does = NULL not test for a missing value?
A: Ordinary comparisons with NULL produce unknown; use IS NULL to test for NULL.

#### Card 4
Q: How does SUM(CASE WHEN condition THEN 1 ELSE 0 END) count matches?
A: Each matching row contributes 1 and every other row contributes 0; SUM adds them.

#### Card 5
Q: Why omit GROUP BY for the laptop/mobile exercise?
A: The required result is one row summarizing the entire table, with a separate conditional aggregate for each category.

#### Card 6
Q: When is GROUP BY device_type appropriate?
A: When the required output is one row per device type rather than separate totals in columns.

## Validation evidence

- Sources: learner queries and DataLemur accepted-result screenshots supplied in this conversation for S3, S4, S5.
- Reviewer: Codex; validated against visible expected outputs and SQL semantics.
- All three exercises accepted; conceptual explanation reviewed with corrections. This is not a timed independent assessment.
- Actual focused time unknown; submission timestamps do not establish focused minutes. No claim that the 25-minute allocation was met.
- Coverage: m1-w1-d05-sql. SQLBolt 9–12 stays complete. Separate SQLBolt subqueries/unions and Northstar tasks 1–4 remain pending with an unresolved date allocation.
- Exact next start: H10 API Design, then the scheduled discovery application and closeout.
