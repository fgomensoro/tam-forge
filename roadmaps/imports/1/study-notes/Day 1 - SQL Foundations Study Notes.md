---
title: Day 1 - SQL Foundations Study Notes
date: 2026-08-25
type: study-note
topic: sql-foundations
language: English
status: completed
future-app-source: true
focused-time-minutes: 40
elapsed-time-minutes: 45-50
tags:
  - tam
  - sql
  - day-1
---

# Day 1 — SQL Foundations Study Notes

## Completed material

SQLBolt lessons 1–4:

1. Basic `SELECT` queries
2. Numeric constraints
3. Text constraints
4. Filtering and sorting results

## Core query structure

```sql
SELECT column_1, column_2
FROM table_name
WHERE condition
ORDER BY column_1 DESC, column_2 ASC
LIMIT 5;
```

The clauses appear once and in this order:

```text
SELECT → FROM → WHERE → ORDER BY → LIMIT → OFFSET
```

## Important concepts

- `SELECT` chooses the output columns.
- `FROM` identifies the source table.
- `WHERE` filters rows.
- Multiple conditions can be combined with `AND` or `OR`.
- `BETWEEN 2000 AND 2010` includes both boundary values.
- SQL string literals should use single quotes: `'Toy'`.
- `%` in a `LIKE` pattern matches any sequence of characters.
- `NOT LIKE '%Toy%'` excludes values containing `Toy` anywhere.
- Multiple sorting rules belong in one `ORDER BY` clause, separated by commas.
- `LIMIT 5` returns at most five rows.
- `OFFSET 0` is valid but unnecessary because zero is the default starting position.

## Integrated query

Requirement: return five movies released from 2000 through 2010, exclude titles containing “Toy,” sort newest first, and break equal-year ties alphabetically.

```sql
SELECT title, director, year
FROM movies
WHERE year BETWEEN 2000 AND 2010
  AND title NOT LIKE '%Toy%'
ORDER BY year DESC, title ASC
LIMIT 5;
```

## Mistakes discovered

The first attempt contained:

- A comma after the `WHERE` condition
- Two separate `ORDER BY` clauses
- Double quotes around a string pattern
- An unnecessary `OFFSET 0`

## Corrective rule

Before executing a query, scan it once for:

1. Correct table and column names
2. One instance of each clause
3. Valid clause order
4. Single-quoted text values
5. Commas only inside column and sorting lists—not between clauses

## Assessment

- Lessons: completed
- Conceptual understanding: good
- Integrated query: correct after hints
- Review priority: clause syntax and independent recall

