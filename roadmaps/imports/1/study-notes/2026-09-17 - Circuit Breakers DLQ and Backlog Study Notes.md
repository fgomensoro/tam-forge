---
date: 2026-09-17
type: study-note
future-app-source: true
flashcard-source: true
status: completed-with-coaching
actual-focused-minutes: unknown
---

# Circuit Breakers, Dead-Letter Queues and Backlog Control

## Practice record

Francisco described pausing ERP traffic on repeated 503s, later checking recovery and draining queued work gradually. He proposed a token bucket per account, selective DLQ replay and checking destination order creation before retrying. Coach corrected that /health returning 200 does not establish order-creation recovery; half-open trials must be representative and safe. Backoff controls retry spacing, while the breaker controls calls to the failing dependency. Queue figures were corrected from an accidental 60,000 to the scenario's 6,000 orders. The 90 minus 20 and 90 minus 40 allocations were answered correctly after clarification. This is coached practice, not an independent timed assessment. No actual focused duration or recording was received.

## Polished operating model

When the ERP's order endpoint repeatedly returns 503, open a circuit for that failing dependency and retain work durably. After cooldown, allow a small number of representative, retry-safe half-open operations. A generic health-check success alone does not justify fully reopening order traffic. On sufficient operation-level recovery, close the breaker gradually and drain the backlog under shared account-level rate and concurrency controls.

For a failed order with a missing SKU, preserve the message and diagnostic context in a DLQ after its retry policy is exhausted. Other orders continue. After the SKU is corrected, select only eligible items by tenant, destination, SKU and failure reason; check for an ERP order already created and honor the original idempotency contract before replay. Track requeued separately from confirmed success.

For 6,000 queued orders with an ERP limit of 100 requests per second per account, choose a lower safe operating budget, e.g. 90 per second, and share it across new orders, backlog and retries. If new orders use 20 per second, at most 70 per second remains for backlog under those simplified assumptions; if new orders rise to 40, backlog falls to 50. Token buckets can reserve new-order capacity, while a shared per-account cap, burst control and concurrency limit protect the dependency. The arithmetic is an illustrative scenario, not a measured production rate or recovery ETA.

Customer update: [[Docs/2026-09-17 - Backlog Customer Update Study Notes]].

## Card-ready Q/A

### Card 1
Q: When should a circuit breaker open?
A: When repeated failures show a dependency cannot currently handle normal traffic; pause most calls according to a defined policy.

### Card 2
Q: What does half-open mean?
A: After a cooldown, allow a small number of representative trial operations; close only after sufficient success, otherwise reopen.

### Card 3
Q: Does a healthy /health endpoint prove POST /orders has recovered?
A: No. Recovery evidence should represent the operation that failed; an order-creation probe must itself be safe and tracked.

### Card 4
Q: How is a circuit breaker different from exponential backoff?
A: Backoff changes the delay between retries. A circuit breaker temporarily blocks calls to a failing dependency and controls recovery trials.

### Card 5
Q: What belongs with an order moved to a DLQ?
A: Payload or durable reference, tenant and order IDs, destination, failure reason and retry history, without unnecessary sensitive data.

### Card 6
Q: Should a DLQ item be marked successful when requeued?
A: No. Requeued means durably handed off for another attempt; resolved means the intended outcome was confirmed.

### Card 7
Q: How should 20 affected orders be selected from a 500-item DLQ?
A: Filter by correct tenant/destination, the fixed failure reason and affected SKU; inspect and replay only eligible items.

### Card 8
Q: What prevents duplicate creation after a crash following ERP creation?
A: Reconcile the destination outcome and reuse the persisted idempotency key for the same operation when the ERP supports it.

### Card 9
Q: What must share a per-account request budget?
A: New orders, backlog work, retries and any other callers subject to that account quota.

### Card 10
Q: With a safe total of 90 requests/s and 20 new orders/s, what remains for backlog?
A: 70 requests/s, assuming one request per order and no retry overhead.

### Card 11
Q: How do token buckets help protect new orders during backlog drain?
A: Reserve capacity for priority traffic while both streams obey a shared per-account cap; also control burst size and concurrency.

### Card 12
Q: Why does jitter alone not control backlog drain?
A: Jitter spreads request timing but does not impose a sustained rate or concurrency ceiling.

## Evidence limits and exact next start

The scheduled technical block was 75 focused minutes across four subparts; actual total is unknown. Outcome is coached completion of the attempted learning sequence with documented gaps, not a verified on-time or independent pass. The original Monday closeout is completed administratively with this note and [[Docs/2026-09-17 - Study Index]]. Next session must reconcile unstarted Tuesday-through-Thursday roadmap rows against actual study capacity. Do not infer those rows completed because their dates elapsed, and do not add them all to a single day. Retain the user-directed skips and removed application slot as skips, not completed actions.
