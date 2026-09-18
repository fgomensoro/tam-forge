---
date: 2026-09-09
type: study-note
topic: webhooks-rate-limits-and-recovery
language: English
status: validated
future-app-source: true
flashcard-source: true
assistance: coached
assessment-status: not-independently-assessed
---

# Webhooks, Rate Limits, and Recovery

## Corrected and validated note

### Concise rule

Acknowledge durable webhook acceptance promptly; process downstream effects safely with scoped throttling, persistent retry state, atomic freshness checks, and reconciliation.

### Plain-English explanation

Webhook reception and downstream execution are separate responsibilities. Queueing absorbs bursts but does not itself guarantee unique business effects or successful delivery to an ERP. Record progress so crashes do not lose work or make successful steps execute unsafely again. Restrict retries to the actual scope of the quota rather than pausing unrelated work.

### Practical TAM example

The fictional case supplies signed events containing an event ID, order ID, per-order version, and full snapshot. A verified event is durably queued before acknowledgment. Workers compare and update versions atomically, and establish durable outbound work. ERP requests retain their operation key and parameters across retries. A 429 delays affected work according to its quota and retry instruction. Recovery compares source API records against local state, and failed work has a monitored DLQ and controlled replay path.

This is a reviewed design, not an implemented or tested system. The complete scenario's fields and guarantees must not be assumed for every provider.

### Boundary or common mistake

A unique business-order constraint prevents duplicate rows but does not itself prevent stale overwrites. Redis deduplication requires suitable persistence, expiry, and coordination with durable work; a marker alone is not a completion guarantee. Full-snapshot version handling does not automatically solve partial-update dependencies. Local version checks alone also do not serialize all downstream writes: ordering/concurrency protection must be verified at the ERP boundary where needed. That downstream-ordering detail remains a future transfer check, not independently demonstrated today.

### Card-ready Q/A

#### Card 1
Q: Does every Stripe 429 prove the global requests-per-second limit was exceeded?
A: No. Inspect the error and Stripe-Rate-Limited-Reason header. Endpoint limits, concurrency limits, or a lock timeout can require different action.

#### Card 2
Q: Are rate limits always per account?
A: No. Determine the documented quota scope: account, shared credential, endpoint, resource, or service. Throttle the work sharing that quota.

#### Card 3
Q: How do rate and concurrency limits differ?
A: Rate concerns requests over time; concurrency concerns requests simultaneously in progress.

#### Card 4
Q: What does Retry-After: 30 mean for a retry?
A: Wait at least 30 seconds before the next attempt. Availability at that point does not guarantee immediate execution.

#### Card 5
Q: Why use exponential backoff with jitter?
A: Backoff spreads attempts over increasing delays; jitter helps prevent many retries from occurring together. Honor the applicable server-directed minimum delay.

#### Card 6
Q: What does a token bucket control?
A: It limits the rate at which requests are admitted, allowing only the configured burst capacity. Backoff instead controls retry timing after failures.

#### Card 7
Q: What does a delayed queue do?
A: It holds work unavailable until the delay expires. A worker executes the API request; the queue does not execute it.

#### Card 8
Q: Is cron a valid retry scheduler?
A: Yes. A scheduler can query durable jobs whose next_attempt_at is due and claim them safely. Traditional cron has minute-level scheduling, so retries may occur later than a 30-second minimum.

#### Card 9
Q: What should be persisted to recover retry work after a crash?
A: The job identity, completed steps, pending operation, retry state, and stable outbound idempotency key established before the first request.

#### Card 10
Q: Should one rate-limited customer stop every other customer?
A: Only work sharing the exhausted quota should be throttled. Separate quotas can continue; a shared exhausted credential may affect several customers.

#### Card 11
Q: What does the webhook receiver acknowledge in our design?
A: It has verified and durably accepted the event for processing. A 200 response does not establish ERP success or prove that the worker has not started.

#### Card 12
Q: Why keep the receiver lightweight?
A: Durably accept the event and respond promptly, leaving expensive downstream processing to workers so delivery bursts do not block acknowledgment.

#### Card 13
Q: Does inbound event deduplication replace outbound idempotency?
A: No. Event deduplication tracks inbound work; a stable operation key protects a retried downstream effect. A crash can happen between the downstream commit and local completion recording.

#### Card 14
Q: What is the risk of a processed-event marker without durable work?
A: It may cause a retry to be acknowledged and skipped even though processing was lost. Queue acceptance, marker state, persistence, expiry, and crash recovery must be coordinated.

#### Card 15
Q: How should incoming version 3 be handled when the database holds version 2, 3, or 4?
A: Apply it only to version 2. Equal version 3 is not newer; version 4 makes it stale. Compare and update atomically.

#### Card 16
Q: Does upsert alone prevent stale webhook state?
A: No. An upsert can overwrite newer values with older ones. Use documented ordering information; an update can create a missing entity only when its payload is sufficient, otherwise retrieve current source state.

#### Card 17
Q: How does an event ID differ from an order ID?
A: An order ID identifies a business object; different events can concern that object. Deduplicate using the provider-documented event identity and scope, not just the order ID.

#### Card 18
Q: How can missed webhook changes be recovered after retries stop?
A: Fetch affected current records from the source API and reconcile them against local state; recover missing or newer records and keep downstream effects idempotent.

#### Card 19
Q: Can a hash determine which record is newer?
A: No. A hash can reveal a difference between consistently represented comparable fields. A documented version or other source contract is needed to establish freshness.

#### Card 20
Q: What does a DLQ need beyond storage?
A: An owner, alerting, diagnosis, and safe replay after the cause is addressed. Moving work to a DLQ is not successful processing.

#### Card 21
Q: What determines a reconciliation interval?
A: Customer tolerance for stale data, available API capacity, and recovery requirements. Six hours was a proposed interval in practice, not a universal rule.

#### Card 22
Q: What are useful general names for items being processed?
A: An order, product, or payment is a business entity. A processing task is a job or work item. A processing record stores its progress and outcome.

## Source-specific reference

Checked September 9, 2026. Stripe's documented general live-mode limit is 100 requests per second, with separate endpoint and concurrency constraints; avoid memorizing 100 as universal. Plaid documents non-200 responses or no response within ten seconds as failed delivery, with retries up to 24 hours and additional retry-policy exceptions. Its guidance addresses duplicate and out-of-order delivery and recovery through API access when delivery is missed. Provider-specific retry behavior should be checked against the current contract.

## Validation evidence

- Assigned A7: [Stripe Rate Limits](https://docs.stripe.com/rate-limits).
- Assigned A12: [Plaid Webhooks](https://plaid.com/docs/api/webhooks/).
- Supplemental clarification requested by Francisco, not a new course: [SQS delay queues](https://docs.aws.amazon.com/AWSSimpleQueueService/latest/SQSDeveloperGuide/sqs-delay-queues.html), [SQS visibility timeout](https://docs.aws.amazon.com/AWSSimpleQueueService/latest/SQSDeveloperGuide/sqs-visibility-timeout.html).
- Reviewer: Codex, using the source pages and concrete scenario evidence in this conversation.
- Reading: learner reported complete. Recall: committed before review, with guided clarification of the failure-mode prompt.
- Application: answers, integrated design, and acknowledgment teach-back completed with coaching. Independent assessment and implementation testing: not performed.
- Material corrections: scope 429 diagnosis; distinguish worker from retry strategy; cron remains valid; protect against equal/stale versions; coordinate deduplication with durable work; preserve outbound keys; acknowledge acceptance rather than downstream success.
- Focused and elapsed study time: unknown. No audio artifact received here.
- Coverage: m1-w1-d04-technical and m1-w1-d04-case. Coached application does not satisfy an independent case gate.
- Exact next transfer check: apply ordering and crash recovery to a fresh case when scheduled; do not repeat today's component questions.
