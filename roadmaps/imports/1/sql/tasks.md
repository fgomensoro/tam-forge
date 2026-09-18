
> [!important] SQL platform amendment — September 15
> [[Docs/2026-09-15 - SQL Platform Plan]] controls all future SQL reading, practice and assessment across the six weeks. Use SQLBolt for foundations and DataLemur for progressive browser exercises. Older Northstar task references and SQL contract text below are retained as coverage lineage, not active platform assignments. Preserve completed evidence, skill objectives, time limits and independence rules.

# Northstar SQL Tasks

Do each task without AI first. Run the query, inspect the rows, and explain why the answer is correct. Ask AI for critique only after you commit to an answer.

## Foundations
1. Return all Northstar Retail orders created on 2026-08-18.
2. Return all orders whose status is `PAID`, ordered newest first.
3. Count orders by customer.
4. Calculate total order value by customer.
5. Return customers with more than three orders.
6. Return every order with its customer name and tier.

## Investigation and reconciliation
7. Find orders that have no payment row.
8. Find payments whose amount does not equal the order amount.
9. Find orders with more than one captured payment.
10. Find captured payments that have not settled.
11. Find webhook provider event IDs received more than once.
12. Find failed webhook events and their related customer, when an order exists.
13. Find orders with no successful ERP sync attempt.
14. Find orders where the latest ERP attempt failed.
15. Find orders that initially failed but later succeeded.
16. Calculate ERP success rate by customer using orders as the denominator.
17. Calculate retry rate by customer.
18. Find the most common final error code by customer.

## Intermediate
19. Use `ROW_NUMBER()` to return only the latest sync attempt for each order.
20. Use `LAG()` to calculate time between successive attempts for each order.
21. Calculate average and maximum webhook processing delay by status.
22. Return the three customers with the highest failed-attempt rate.
23. Build a reconciliation result with one row per order and flags for: missing payment, amount mismatch, duplicate captured payment, unsettled captured payment, and no successful ERP sync.
24. Produce an executive summary query by customer: order count, order value, payment issue count, ERP issue count, and webhook failure count.
