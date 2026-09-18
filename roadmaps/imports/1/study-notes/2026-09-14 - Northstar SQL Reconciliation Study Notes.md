---
date: 2026-09-14
type: study-note
language: English
status: validated-coached
future-app-source: true
flashcard-source: true
assistance: progressive-hints-and-explanation
actual-focused-minutes: unknown
---

# Northstar SQL — Missing Records and Reconciliation

## Evidence and status

Tasks 7, 8, 9, and 13 are complete as coached practice across the Friday carryover and September 14 continuation. Queries below are polished versions, not raw attempts. LEFT/INNER joins simplify earlier FULL OUTER JOIN solutions; sorting and output aliases improve clarity. Codex executed these versions against the unchanged Northstar setup in a fresh in-memory SQLite database at closeout. No PostgreSQL execution or independent timed mastery is claimed. Formal learner self-review and focused duration were not recorded.

## Task 7

```sql
SELECT orders.order_id FROM orders LEFT JOIN payments ON orders.order_id = payments.order_id WHERE payments.payment_id IS NULL ORDER BY orders.order_id;
```

Validated result: `[(202,), (501,)]`.

No payment row is recorded. This does not prove payment failed; investigate timing, workflow, or missing data.

## Task 8

```sql
SELECT orders.order_id, payments.payment_id, orders.amount_cents AS order_amount, payments.amount_cents AS payment_amount FROM orders JOIN payments ON orders.order_id = payments.order_id WHERE orders.amount_cents <> payments.amount_cents;
```

Validated result: `[(402, 4002, 13300, 12000)]`.

Order 402 differs by 1,300 cents. Review taxes, discounts, fees and installment arrangements before calling this an error.

## Task 9

```sql
SELECT orders.order_id, SUM(CASE WHEN payments.status = 'CAPTURED' THEN 1 ELSE 0 END) AS captured_payments FROM orders LEFT JOIN payments ON orders.order_id = payments.order_id GROUP BY orders.order_id HAVING SUM(CASE WHEN payments.status = 'CAPTURED' THEN 1 ELSE 0 END) > 1;
```

Validated result: `[(109, 2)]`.

Order 109 has two captured payments. This may indicate installments rather than a duplicate charge; review references, amounts and the agreed payment arrangement.

## Task 13

```sql
SELECT orders.order_id FROM orders LEFT JOIN sync_attempts ON orders.order_id = sync_attempts.order_id AND sync_attempts.destination = 'ERP' AND sync_attempts.status = 'SUCCESS' WHERE sync_attempts.attempt_id IS NULL ORDER BY orders.order_id;
```

Validated result: `[(103,), (104,), (105,), (110,), (202,), (204,), (401,), (501,)]`.

These orders have no successful ERP attempt recorded. This includes no attempts and unsuccessful attempts only. It does not prove the ERP has no order: a lost response may leave local evidence incomplete.

## Card-ready Q/A

### Card 1
Q: What does LEFT JOIN preserve?
A: Every left-side row; unmatched right-side columns become NULL in the result, not in the underlying table.

### Card 2
Q: How do you find orders without any payment row?
A: LEFT JOIN payments by order ID, then WHERE payments.payment_id IS NULL.

### Card 3
Q: Does a missing payment row prove payment failure?
A: No. It is an investigation signal, not a confirmed business outcome.

### Card 4
Q: Does an amount mismatch prove an incorrect charge?
A: No. Check taxes, discounts, fees, partial payments and the business agreement.

### Card 5
Q: Does more than one captured payment prove a duplicate charge?
A: No. Multiple captures may be legitimate installments.

### Card 6
Q: How does SUM(CASE WHEN condition THEN 1 ELSE 0 END) count matches?
A: Each matching row contributes one; other rows contribute zero; SUM adds them per group.

### Card 7
Q: What is the retained WHERE/HAVING rule?
A: WHERE filters rows; HAVING filters groups.

### Card 8
Q: Can PostgreSQL HAVING use a SELECT output alias?
A: Not directly. Repeat the aggregate expression or put the result in a subquery. SQLite accepting an alias does not establish PostgreSQL compatibility.

### Card 9
Q: Why is filtering status not SUCCESS insufficient to find orders that never succeeded?
A: An order can have both a failed and successful attempt. Filtering individual failures still retains that order.

### Card 10
Q: What belongs in ON for the missing-success anti-join?
A: Order ID equality, destination ERP, and status SUCCESS. These define a qualifying match.

### Card 11
Q: What belongs in WHERE for that anti-join?
A: sync_attempts.attempt_id IS NULL, selecting orders with no qualifying match.

### Card 12
Q: Why not put attempt_id IS NULL in ON?
A: A real attempt primary key cannot be NULL; no attempts would match, and the LEFT JOIN would preserve every order.

### Card 13
Q: Why use IS NULL rather than = NULL?
A: Ordinary equality with NULL evaluates to unknown. WHERE retains true conditions. IS NULL tests missingness specifically, not zero, false or empty strings.

### Card 14
Q: Does missing local ERP success prove the destination order does not exist?
A: No. Reconcile with the destination because the response or local completion record may be missing.

## Learning checkpoint

Strongest evidence: learner distinguished anomaly signals from confirmed financial errors and correctly explained exclusion of an order with a successful attempt. Main corrections: NULL testing and ON versus WHERE; aggregation syntax and HAVING required substantial guidance. Task 13 join scaffold and final NULL predicate were provided by the coach. No fresh independent assessment has been passed.
