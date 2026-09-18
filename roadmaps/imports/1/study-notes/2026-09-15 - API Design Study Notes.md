---
date: 2026-09-15
type: study-note
future-app-source: true
flashcard-source: true
status: completed-with-coaching
actual-focused-minutes: unknown
---

# API Design — Validated Study Notes

## Evidence and assistance

Francisco reported reading H10 API Design. At his request, concrete questions replaced the broad three-ideas recall format. Coached coverage included PATCH, 404, pagination, cursor boundaries, backward compatibility and API/webhook/polling application. He identified offset duplication, versioning and webhook-plus-reconciliation design. Query parameter semantics and logical collections required direct explanation. End-to-end measurement required correction: the learner initially timed receipt-to-processing, and later attributed pre-receipt latency without sufficient evidence. The coach supplied the 38-second conclusion. No fresh independent teach-back after that final correction is claimed. Actual focused time unknown; no real environment test or audio received.

Core reading/application sequence complete as coached practice. Do not count it as the original independent closed-source recall contract or a timed assessment. No further whole-case repeat is required; revisit boundaries through later fresh transfer.

## Sources

- https://www.hellointerview.com/learn/system-design/core-concepts/api-design (assigned reading; learner-reported read)
- https://fastapi.tiangolo.com/tutorial/query-params/
- https://fastapi.tiangolo.com/tutorial/query-params-str-validations/
- https://developer.mozilla.org/en-US/docs/Web/API/URLSearchParams/get
- https://learn.microsoft.com/en-us/azure/architecture/best-practices/api-design

## Polished application

Use source inventory webhooks for prompt notification and periodic API reconciliation for missed changes. Define the 30-second target end to end, from source change to the correct destination state. Measure the proportion meeting the target and investigate tail delays. Validate detection and recovery using intentionally missed events. A five-minute reconciliation schedule cannot guarantee a 30-second bound for every change. Agree exception handling and recovery expectations with the customer; do not infer fault from timestamps alone.

## Card-ready Q/A

### Card 1
Q: Are missing, empty and null query parameters equivalent?
A: No. An omitted parameter is absent; event_id= supplies an empty string; event_id=null supplies the text null. The API contract determines validation and normalization.

### Card 2
Q: Does event_id="" send an empty value?
A: No. Literal quotes in the URL are characters. event_id= sends the empty string.

### Card 3
Q: Are query parameters always optional?
A: No. The API contract decides. In FastAPI, a scalar parameter without a default is required.

### Card 4
Q: How does FastAPI handle a required event_id: int?
A: A missing or invalid integer produces a default 422 response. For event_id: int | None = None, omission uses None but an empty string still fails integer validation.

### Card 5
Q: Does a required string imply nonempty?
A: No. Use an appropriate constraint such as Query(min_length=1); this alone does not reject whitespace or literal quote characters.

### Card 6
Q: Does /events/123/bookings imply a separate database table per event?
A: No. It identifies a logical event-specific collection. Both nested and flat endpoints can use one bookings table with event_id.

### Card 7
Q: How can a booking be created with either nested or flat endpoints?
A: POST /events/123/bookings takes the relationship from the path; POST /bookings can take event_id from the body. When server-generated, the new booking ID is not needed in the creation URL.

### Card 8
Q: How do a nested booking list and a filtered booking list differ?
A: GET /events/123/bookings requires an event in its route; GET /bookings?event_id=123 filters the bookings collection. The contract decides whether that filter is optional.

### Card 9
Q: Is POST guaranteed to create duplicates on retry?
A: No. POST is not inherently idempotent, but an API can provide an explicit idempotency-key contract.

### Card 10
Q: Which operation changes only the email on booking 901?
A: PATCH /bookings/901 with a JSON email field, under the endpoint partial-update contract. Backticks inside the JSON value are literal characters.

### Card 11
Q: What status applies when the requested booking does not exist?
A: 404 Not Found for this scenario.

### Card 12
Q: Why paginate a large list?
A: Limit response size, client memory, bandwidth and request work; large responses can cause timeouts.

### Card 13
Q: How can an insertion cause duplicate results with offset pagination?
A: A new item before the offset shifts a previously returned item into the next page.

### Card 14
Q: How does a cursor avoid that particular offset problem?
A: It marks stable ordering values such as created_at and booking_id rather than a position. Deterministic ordering is necessary; cursor pagination does not guarantee a frozen snapshot.

### Card 15
Q: Is renaming total_amount to amount backward compatible?
A: No for consumers relying on the old field. A new version with a migration/deprecation plan is one option; an additive transition retaining both fields is another.

### Card 16
Q: How can webhooks and polling work together?
A: Webhooks notify promptly; periodic API polling reconciles missed or inconsistent changes. REST describes an interface style and is not an alternative category to webhook delivery or polling.

### Card 17
Q: Does five-minute reconciliation guarantee all changes arrive within 30 seconds?
A: No. A missed webhook can wait nearly a full reconciliation interval plus fetch, processing and destination-update time, assuming recovery succeeds.

### Card 18
Q: Where should end-to-end inventory latency measurement start and end?
A: From the source inventory change to the destination reflecting the correct inventory, not merely webhook receipt to worker completion.

### Card 19
Q: How should a normal-operation 30-second target be verified?
A: Use controlled test changes with correlated timestamps, measure the fraction meeting the target and tail delays, and deliberately test missed-event detection and recovery. Agree the acceptable exceptions and recovery deadline.

### Card 20
Q: Does 20 seconds before webhook receipt plus 18 seconds after receipt meet 30 seconds?
A: No: 38 seconds end to end. Those timestamps locate delay segments but do not prove the cause of the first segment.

## Exact next start

A8 Timeouts, Retries, and Backoff with Jitter reading first; then concrete recall questions. A9 Retry with Backoff Pattern, retry decision table and teach-back remain in the same pending unit. Do not repeat the already completed no-idempotency core case.
