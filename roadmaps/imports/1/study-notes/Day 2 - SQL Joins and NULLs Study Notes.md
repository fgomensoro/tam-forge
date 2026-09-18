---
title: Day 2 - SQL Joins and NULLs Study Notes
date: 2026-08-27
type: study-note
topic: sql-joins-and-nulls
language: English
status: completed-with-guided-review
future-app-source: true
tags:
  - tam
  - sql
  - joins
  - day-2
---

# Day 2 — SQL Joins and NULLs Study Notes

Legacy roadmap: [[Roadmap.archive-20260828-month1-v2/Week 1 - SQL foundations, HTTP, troubleshooting, and story inventory#Day 2 — Joins and diagnostic questions|Week 1 — Day 2]]
Current Phase 1 coverage: [[Roadmap/docs/Coverage Ledger#m1-w1-d02-sql]]

## Completed material

SQLBolt lessons 6–8:

1. Multi-table queries with `JOIN`
2. Outer joins
3. `NULL` values
4. Finding records that have no related row

## Core concepts

- A join combines related rows from two tables.
- The `ON` condition defines the relationship between the tables.
- An `INNER JOIN` returns only rows with a match on both sides.
- A `LEFT JOIN` keeps every row from the left table and fills unmatched right-side columns with `NULL`.
- Use `IS NULL` and `IS NOT NULL`; do not compare `NULL` with `=` or `!=`.
- Verify the real table schema and join keys before writing the query.

## Finding rows without a related record

Requirement: find movies that have no matching box-office record.

```sql
SELECT movies.title
FROM movies
LEFT JOIN boxoffice
  ON movies.id = boxoffice.movie_id
WHERE boxoffice.movie_id IS NULL;
```

Why it works:

1. `LEFT JOIN` preserves every movie.
2. Movies with a match receive values from `boxoffice`.
3. Movies without a match receive `NULL` for the right-side columns.
4. `WHERE boxoffice.movie_id IS NULL` keeps only unmatched movies.

> [!important] Rule to remember
> To find rows with no related record, `LEFT JOIN` the related table and filter a non-nullable right-side key with `IS NULL`.

## Corrective rules from validation

Before executing a join query, check:

1. Actual table and column names from the schema
2. Correct primary-key-to-foreign-key relationship
3. Whether unmatched left-side rows must be preserved
4. Whether the `NULL` check targets a reliable right-side key
5. Whether a later `WHERE` condition accidentally removes outer-join rows

## Flashcard-ready questions and model answers

### What is the difference between `INNER JOIN` and `LEFT JOIN`?

`INNER JOIN` returns only matching rows. `LEFT JOIN` returns every row from the left table, plus matching right-side data when it exists.

### How do you find rows that have no related record?

Use a `LEFT JOIN`, then filter a non-nullable key from the right table with `IS NULL`.

### Why use `IS NULL` instead of `= NULL`?

`NULL` represents an unknown or missing value. SQL uses `IS NULL` and `IS NOT NULL` to test that state.

### Why should the `NULL` check use a right-side key?

A non-nullable right-side key becomes `NULL` only when the join found no matching row, making it reliable evidence of an unmatched record.

### Why verify the schema before correcting a query?

A syntactically valid query still fails when it assumes nonexistent columns or the wrong relationship. Schema inspection establishes the real tables, columns, and join keys first.

## Assessment

- SQLBolt lessons 6–8: completed
- Outer-join and `NULL` challenge: completed after guided correction
- Verified relationship: `movies.id = boxoffice.movie_id`
- Review priorities: schema-first reasoning and choosing the correct join type
- Elapsed time: not captured
- Assistance: tutor correction during validation
