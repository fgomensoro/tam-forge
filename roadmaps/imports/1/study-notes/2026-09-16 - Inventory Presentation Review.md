---
date: 2026-09-16
type: coached-presentation-review
future-app-source: true
flashcard-source: true
status: closed-with-learning-gap
actual-focused-minutes: unknown
---

# Inventory Presentation — Validated Review

Scope: a physical-store sale already changes ERP inventory; the goal is for ecommerce to reflect that change within 60 seconds. Existing inventory polling is every five minutes. ERP webhook availability is unknown. Do not invent ERP polling of ecommerce orders; it is outside this scenario.

Learner identified source webhooks, reconciliation, polling workload and processing duration. Coach corrected directionality and the end-to-end timing calculation. This was coached presentation practice, not a demonstrated independent pass. No audio or focused timing received.

## Polished recommendation

Check whether ERP inventory-change webhooks are available and suitable. If using them, measure source-change-to-destination-visibility latency and plan reconciliation for missed events. If polling, assess rate limits, workload, concurrency and total delay: wait for next poll plus fetch/process and destination-update time. A run finishing before the next scheduled run is not sufficient evidence that the business latency target is met. Validate under realistic load, especially changes occurring just after a product was checked.

## Cards

### Card 1
Q: What flow is under investigation when a store sale already updated ERP stock?
A: ERP inventory to ecommerce inventory, unless evidence establishes additional relevant flows.

### Card 2
Q: Does a polling run shorter than its interval prove the customer latency target is met?
A: No. Add the wait until the next poll and all downstream processing/update time.

### Card 3
Q: With 40-second polling and 25 seconds from fetch through destination confirmation, what is the approximate worst scheduling delay?
A: Almost 65 seconds for a change just missed by the previous poll, so a 60-second target is not met.

### Card 4
Q: If processing takes 25 seconds and the total target is 60 seconds, what interval fits the simple budget?
A: At most 35 seconds under those assumptions, shorter for a buffer. Validate tail processing times and capacity; this calculation alone is not a production guarantee.
