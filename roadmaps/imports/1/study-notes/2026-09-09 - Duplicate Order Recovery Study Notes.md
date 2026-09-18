---
date: 2026-09-09
type: study-note
language: English
status: validated
future-app-source: true
flashcard-source: true
assistance: coached
assessment-status: not-independently-assessed
---

# Duplicate Order Recovery Study Notes

## Corrected and validated note

### Concise rule

Preserve one intended business operation across retries, then reconcile every duplicate side effect before closing an incident.

### Plain-English explanation

A timeout establishes that the client did not receive a response in time; it does not establish whether the server committed the operation. Persist an outbound idempotency key before the first request and reuse it with the same parameters for the same intended operation, subject to the destination API's documented support and retention window. A new intended operation needs a different key.

### Practical TAM example

In the fictional coached case, the ERP created ERP-440 for ecommerce order shop-184, but the response was not received. The worker crashed before recording completion. Redelivery of evt-772 led to a new key and a second order, ERP-441.

- Diagnosis: a new key let the same intended creation be treated as another operation. The missing completion record allowed redelivery to reach the ERP again.
- Mitigation: hold fulfillment of the suspected duplicate, identify the valid order, and check payment and shipment status before canceling safely.
- Prevention: persist and reuse the operation key, with durable processing state and recovery after a worker crash. An atomic claim alone does not prove successful processing.
- Validation: simulate commit followed by response loss and worker crash; verify recovery preserves one ERP order. Test in a controlled environment before rollout, then monitor.
- Reconciliation: link records through the external order ID and correct store/tenant. Preserve the valid order, payment, and reservation; cancel the duplicate, refund its payment, release its reservation, and verify completion. Canceled records may remain for audit.

### Boundary or common mistake

An order ID identifies a business object; an event ID identifies a specific event. Separate updates to the same order can have different event IDs. Scope the provider's documented stable event identifier appropriately, for example by tenant and provider. Provider alone does not distinguish creation from updates. Store-level scoping may also be necessary. A database uniqueness constraint must enforce the claim atomically; a separate search followed by insertion is insufficient under concurrency. A business-order uniqueness constraint is a separate safeguard and is not automatically an outbound idempotency key.

Matching amount, date, and customer identifies candidates, not proof of duplication. Canceling an ERP record does not necessarily refund a captured payment or stop a shipment. In the reconciliation exercise, cancellation was given as complete; refund and reservation release remained unverified until evidence could establish them.

### Card-ready Q/A

#### Card 1
Q: What does a timeout tell you about a state-changing request?
A: The client did not receive a response in time; the business outcome may still be successful and is uncertain from the client's perspective.
Why it matters for a TAM: Avoid recommending a retry that creates a duplicate.

#### Card 2
Q: How must an idempotency key survive a worker crash?
A: Persist it before the first outbound request and retrieve it for retries of that same intended operation.
Why it matters for a TAM: Recovery must remain safe after process memory is lost.

#### Card 3
Q: How do mitigation, prevention, validation, and reconciliation differ?
A: Mitigation limits current harm; prevention changes future behavior; validation tests the change; reconciliation corrects and verifies affected business records and side effects.
Why it matters for a TAM: A deployed fix alone does not resolve customer impact.

#### Card 4
Q: What should remain after reconciling a duplicated purchase?
A: One valid order with its valid payment and reservation, with duplicate effects corrected and their final states verified.
Why it matters for a TAM: Preserve the legitimate purchase while removing duplicate impact.

#### Card 5
Q: Why is an order ID insufficient for webhook-event deduplication?
A: Multiple legitimate events can concern the same order. Use a documented stable event identifier with the appropriate scope.
Why it matters for a TAM: Avoid suppressing valid updates.

## Validation evidence

- Basis: fictional scenario facts and corrected reasoning reviewed in this Codex conversation; synthesis saved September 9, not a claim that all practice occurred today.
- Related source: [[Docs/Day 3 - Idempotency and Retry Safety Study Notes]].
- Reviewer: Codex.
- Validation state: validated study content; not independently demonstrated learner performance.
- Mapped coverage IDs: m1-w1-d03-case, m1-w1-d03-technical.
- Assistance: progressive hints, explanations, and model answers; coached.
- Timing: unknown. No audio recording received here.
- Exact next transfer check: fresh case under the scheduled assessment contract; do not reopen completed component questions.
