---
title: Day 3 - Idempotency and Retry Safety Study Notes
date: 2026-08-28
type: study-note
topic: idempotency-and-retries
language: English
status: completed-with-guided-review
future-app-source: true
tags:
  - tam
  - api
  - idempotency
  - retries
  - day-3
---

# Day 3 — Idempotency and Retry Safety Study Notes

Legacy roadmap: [[Roadmap.archive-20260828-month1-v2/Week 1 - SQL foundations, HTTP, troubleshooting, and story inventory#Day 3 — Aggregation, idempotency, and audience switching|Week 1 — Day 3]]
Current Phase 1 coverage: [[Roadmap/docs/Coverage Ledger#m1-w1-d03-technical]]

## Core definition

Idempotency means repeated requests for the same intended operation have the same business effect as one request.

> [!important] Rule to remember
> Retry the same intended operation with the **same idempotency key and the same parameters**.

## Idempotency key versus API key

- An **API key** authenticates the calling application and may determine its permissions.
- An **idempotency key** identifies one intended state-changing operation so retries can be recognized.
- API keys are long-lived credentials and must remain secret.
- Idempotency keys are operation identifiers. They must not contain sensitive customer information.

Confusing these keys is dangerous: an API key answers “Who is calling?” while an idempotency key answers “Is this the same intended operation being retried?”

## Stripe behavior

- Stripe accepts idempotency keys for `POST` requests. `GET` and `DELETE` are already idempotent in Stripe and do not use them.
- After endpoint execution begins, Stripe stores the first request's resulting status code and response body, including a `500` result.
- Repeating the same key with the same parameters returns the stored result.
- Repeating the same key with different parameters produces an idempotency error.
- Sending a different key represents a different operation and can create a duplicate.
- Validation failures and concurrent-request conflicts that occur before endpoint execution are not stored as idempotent results and can be retried.
- A connection error leaves the outcome indeterminate. Retry with the same key and parameters until a clear result is received, or verify state through retrieval or webhooks.
- Rate-limit retries require delay and exponential backoff. A `429` can occur before the idempotency layer.
- A UUID v4 is a common high-entropy key choice. Stripe allows keys up to 255 characters and may prune them after at least 24 hours.

## Multi-tenant integration example

Inbound webhook deduplication and outbound API idempotency are related but distinct:

1. **Inbound webhook:** store a provider event ID scoped by tenant and provider, and atomically reject or reuse an already-claimed event.
2. **Outbound state-changing request:** use a stable idempotency key for the tenant, operation, and business object when calling a destination API that supports it.
3. **Authentication:** use the tenant's API credentials only to authenticate. Do not use the credential itself as the idempotency key.

Example: when processing a Shopify order webhook, deduplicate the inbound event using Shopify's event identifier. If the integration then creates an order or payment in another API, use a separate stable idempotency key for that outbound creation.

## Boundaries and failure modes

- A new key on every retry defeats deduplication and can create duplicates.
- The same key with changed parameters is misuse and should be rejected.
- A non-atomic “check, then insert” allows concurrent requests to pass the check together.
- Key expiration can make an old retry appear new.
- Idempotency at one API boundary does not automatically deduplicate downstream side effects, webhook deliveries, or other systems.

## Flashcard-ready questions and model answers

### What is the difference between an API key and an idempotency key?

An API key authenticates the caller. An idempotency key identifies one intended operation so repeated requests can be handled without repeating its business effect.

### What happens when the same idempotency key is reused with different parameters?

The request should be rejected as idempotency-key misuse. Stripe returns an idempotency error because the retry does not match the original operation.

### What happens when a retry uses a different idempotency key?

The server can treat it as a new operation. If the original request already succeeded, the retry can create a duplicate.

### Why is a connection error dangerous for a state-changing request?

The client cannot know whether the server committed the operation before the connection failed. The outcome is indeterminate until the client safely retries with the same key or verifies the resulting state.

### How should inbound webhooks be deduplicated?

Use a stable provider event identifier, scoped to the correct tenant and provider, and claim it atomically before processing side effects.

## Current assessment

- Focused reading: completed
- Closed-source recall: completed with guided correction
- Strong recalled ideas: state-changing requests need idempotency protection; retries depend on error type; UUID v4 is a common key choice
- Corrections required: distinguish API credentials from idempotency keys; distinguish a new key from same-key/different-parameter misuse
- Unresolved question: none reported
- Application sequence: completed with guided correction
- Teach-back: completed with guided correction
- Elapsed time: not captured
- Assistance: tutor correction after committed recall, application, and teach-back

## Validated application sequence

1. A client sends a state-changing request with an idempotency key.
2. The server commits the operation, but the response is lost, so the client cannot determine the outcome.
3. The client retries with the same idempotency key and the same parameters.
4. The server recognizes the retry, avoids repeating the business effect, and returns the stored result.
5. Retrying with a new key can be treated as a new operation and can create a duplicate.
6. A database uniqueness constraint on a stable business identifier, scoped by tenant where appropriate, provides an additional atomic safeguard.

## Validated teach-back

An API key identifies and authenticates the calling application and may determine its permissions. An idempotency key identifies one intended outbound state-changing operation. When a timeout leaves the result uncertain, the client retries with the same idempotency key and parameters so the server can return the original result without repeating the business effect.

Inbound webhook deduplication uses the provider's stable event identifier, scoped by tenant and provider, and claims it atomically before executing side effects. The provider event ID is distinct from an outbound idempotency key. If processing the webhook causes an order to be created in an ERP, that outbound API request should use a separate stable idempotency key when the ERP supports one.

### Business meaning

These controls prevent duplicate orders, charges, fulfillment, and reconciliation work while allowing safe recovery from network failures and repeated webhook delivery.

## Sources

- [Stripe — Idempotent requests](https://docs.stripe.com/api/idempotent_requests)
- [Stripe — Error handling](https://docs.stripe.com/error-handling)
- [Stripe — Advanced error handling](https://docs.stripe.com/error-low-level)
