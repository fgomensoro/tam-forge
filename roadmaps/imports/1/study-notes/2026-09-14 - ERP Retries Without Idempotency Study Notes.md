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

# ERP Retries Without Idempotency Support

## Scenario and validated recommendation

A worker sends POST /orders with ecommerce reference WEB-184. The request times out. The ERP accepts the reference but does not enforce uniqueness and does not support idempotency keys. Search can lag creation by 30 seconds. These are fictional practice facts, not a real incident.

Search within the correct tenant/account and verify the matching order. If found, persist its ERP ID and the successful outcome linked to the ecommerce order and destination. Future workers must check that durable state before sending; a local flag alone does not guarantee exactly-once behavior across concurrent workers or remote calls.

If nothing is found, do not treat absence as proof of failure. Hold this operation as outcome unknown and stop its automatic resubmission while unrelated work continues. Use request status, processing logs or ERP support to determine whether the original request completed, failed without creating an order, or remains active. A definitive failure without a side effect permits a controlled retry. An unresolved outcome requires reconciliation and investigation.

Three minutes, three hours or six hours are not universal safe retry thresholds. Search visibility delay starts after creation; the original request could still be processing. Documented processing and visibility bounds can inform a checkpoint only when their guarantees apply and the lookup is reliable and correctly scoped. Agree an escalation deadline based on business impact, but do not confuse an operational deadline with technical proof that resubmission is safe.

## Interview-ready answer

“If a creation request times out and the ERP lacks idempotency support, I reconcile using the external order reference within the correct account. If the matching order exists, I save its ERP ID and mark the operation successful so workers do not resend it. If the outcome is unknown, I hold the operation and investigate the original request. I retry only when there is sufficient evidence that the original operation cannot still create the order. Waiting alone does not make a retry safe.”

## Evidence and limits

The learner identified searching by reference, recognized duplicate risk after a delayed original completion, chose holding for reconciliation, and explained marking a found order as sent. The coach corrected retry-on-empty-search and arbitrary waiting thresholds, explained the investigation process, and supplied the durable ERP ID detail. Core case complete with substantial coaching; no timed independent performance, final uninterrupted presentation, mandatory self-review, audience-specific presentation or audio received. Actual focused minutes unknown. This does not complete A8/A9 reading or the broader formal case assessment.

## Card-ready Q/A

### Card 1
Q: Does a timeout prove the ERP failed to create an order?
A: No. The side effect may have occurred even though no response arrived.

### Card 2
Q: Does searching an external order reference make it an idempotency mechanism?
A: No. Search aids reconciliation; without enforced uniqueness, repeated POSTs may create duplicates.

### Card 3
Q: Why can an empty search result be unsafe grounds for retrying?
A: The request may still be processing or the created order may not yet be searchable.

### Card 4
Q: When does the scenario’s 30-second search lag begin?
A: After order creation, not necessarily when the caller times out.

### Card 5
Q: What does hold for reconciliation mean operationally?
A: Persist outcome unknown, stop automatic retries for that operation, search the destination and investigate the original request.

### Card 6
Q: What evidence can support a controlled retry?
A: Confirmation that the original request failed without creating an order and cannot later commit it; absence alone is insufficient.

### Card 7
Q: What should be persisted when reconciliation finds the matching order?
A: Successful operation state and the ERP order ID linked to the correct tenant/account, ecommerce order and destination.

### Card 8
Q: What is the difference between an escalation deadline and a safe retry threshold?
A: The deadline manages business delay; a safe retry decision needs evidence about the original operation and possible side effects.

