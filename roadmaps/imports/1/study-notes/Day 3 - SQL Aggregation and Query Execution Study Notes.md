---
title: Day 3 - SQL Aggregation and Query Execution Study Notes
date: 2026-08-28
type: study-note
topic: sql-aggregation
language: English
status: completed-with-guided-review
future-app-source: true
tags:
  - tam
  - sql
  - aggregation
  - day-3
---

# Day 3 — SQL Aggregation and Query Execution Study Notes

Legacy roadmap: [[Roadmap.archive-20260828-month1-v2/Week 1 - SQL foundations, HTTP, troubleshooting, and story inventory#Day 3 — Aggregation, idempotency, and audience switching|Week 1 — Day 3]]
Current Phase 1 coverage: [[Roadmap/docs/Coverage Ledger#m1-w1-d03-sql]]

## Completed material

SQLBolt lessons 9–12:

1. Expressions and aliases
2. Aggregate functions
3. Grouped aggregates and `HAVING`
4. Logical query execution order

## Core concepts

- Expressions calculate a value from one or more columns.
- `AS` gives a calculated or aggregated result a clear name.
- `COUNT`, `SUM`, `AVG`, `MIN`, and `MAX` summarize rows.
- `GROUP BY` creates one result group for each distinct grouping value.
- Every table referenced by a query must appear in `FROM` or a `JOIN`.
- With `GROUP BY`, each selected column should normally be either grouped or aggregated. Avoid `SELECT *` unless every selected value has defined grouping semantics.

> [!important] Rule to remember
> **`WHERE` filters rows; `HAVING` filters groups.**

## Why aggregate conditions use `HAVING`

`WHERE` runs before grouping and aggregation. At that point, a value such as `MAX(column4)` does not exist yet.

`HAVING` runs after `GROUP BY`. The grouped result and its aggregate values now exist, so SQL can filter them.

```sql
SELECT role, COUNT(*) AS employee_count
FROM employees
WHERE years_employed > 0
GROUP BY role
HAVING COUNT(*) >= 2
ORDER BY employee_count DESC;
```

In this example:

- `WHERE` removes individual employee rows before grouping.
- `GROUP BY` creates one group per role.
- `COUNT(*)` calculates the size of each role group.
- `HAVING` keeps only role groups containing at least two employees.

## Written clause order

```text
SELECT → FROM / JOIN → WHERE → GROUP BY → HAVING → ORDER BY → LIMIT / OFFSET
```

## Logical execution order

```text
FROM / JOIN → WHERE → GROUP BY → HAVING → SELECT → ORDER BY → LIMIT / OFFSET
```

This explains why:

- `WHERE` cannot filter an aggregate result.
- `HAVING` can filter an aggregate result.
- A `SELECT` alias is generally unavailable to `WHERE` because `SELECT` runs later.
- `ORDER BY` can commonly use a `SELECT` alias because ordering runs afterward.

## Corrective rules from validation

Before executing an aggregate query, check:

1. Every referenced table appears in `FROM` or `JOIN`.
2. Every `JOIN` has the intended relationship in its `ON` condition.
3. Every non-aggregated selected column appears in `GROUP BY`.
4. Row-level conditions use `WHERE`.
5. Aggregate or group-level conditions use `HAVING`.
6. `ORDER BY` uses the intended aggregate or its clear alias.

## Flashcard-ready questions and model answers

### What is the difference between `WHERE` and `HAVING`?

`WHERE` filters individual rows before grouping. `HAVING` filters groups after `GROUP BY` and aggregate calculations.

### Why can `WHERE` not filter `MAX(column4)`?

`WHERE` runs before aggregation, so `MAX(column4)` has not been calculated yet. Use `HAVING` to filter the aggregate result after grouping.

### What does `GROUP BY` do?

It combines rows sharing the same grouping value, allowing aggregate functions to calculate one result per group.

### Which columns can appear in `SELECT` when a query uses `GROUP BY`?

Normally, each selected column must either appear in `GROUP BY` or be passed to an aggregate function such as `COUNT`, `SUM`, `AVG`, `MIN`, or `MAX`.

### What is the logical execution order of an aggregate query?

`FROM` and `JOIN`, then `WHERE`, `GROUP BY`, `HAVING`, `SELECT`, `ORDER BY`, and finally `LIMIT` or `OFFSET`.

### What is the difference between `COUNT(*)` and `COUNT(column)`?

`COUNT(*)` counts rows. `COUNT(column)` counts only rows where that column is not `NULL`.

## Assessment

- SQLBolt lessons 9–12: reported completed
- Validation: completed with tutor guidance
- Strong retained rule: `WHERE` filters rows; `HAVING` filters groups
- Review priorities: logical execution order, grouped-column validity, and complete `JOIN` clauses
- Elapsed time: not captured
- Assistance: tutor correction during post-attempt validation
