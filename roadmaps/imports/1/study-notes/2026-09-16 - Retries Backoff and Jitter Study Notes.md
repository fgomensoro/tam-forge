---
date: 2026-09-16
type: study-note
future-app-source: true
flashcard-source: true
status: completed-with-coaching
actual-focused-minutes: unknown
---

# Retries, Backoff and Jitter

## Evidence and status

Francisco reported finishing the assigned reading, then answered concrete scenarios for 429, invalid-payload 400 and safe-GET 503, followed by a teach-back. Reading comprised A8/A9 as assigned; individual reading durations and full section coverage were not separately confirmed. This unit is complete with coaching, not an independent assessment. Budget was 20 focused minutes (12 reading, 6 practice, 2 close); actual time unknown, so adherence cannot be claimed. Reading and practice crossed calendar dates; do not infer duration from that gap.

Correct learner reasoning: reuse the persisted key for the same intended operation, use jitter to spread retries, do not repeat invalid payloads unchanged, increase delays and cap retries. Correction: numeric Retry-After is seconds, not minutes. Coach supplied payload-change/idempotency caveat and bounded later-recovery policy. Final teach-back correctly explained doubling delays and congestion reduction; clarify idempotency concerns intended effect rather than a guarantee of one execution.

## Polished reference explanation

Backoff delays retries to reduce pressure on a failing service; exponential backoff increases those delays, typically with a cap. Jitter randomizes timing so many clients do not retry together. Idempotency makes repeated requests for the same intended operation avoid additional business effects under the API contract. It does not guarantee success or mean every internal execution happens exactly once.

Five, ten, twenty and forty minutes illustrate exponential growth, not a universally recommended retry schedule. Choose base delay, cap, attempt count and overall deadline for the API contract and business requirements.

## Retry decision table

| Evidence | Decision | Boundary |
|---|---|---|
| 429, Retry-After: 30, supported idempotency contract | Wait at least 30 seconds, spread retries with jitter and retain the same key/parameters for the same operation. | Scope of throttling depends on the API. Waiting does not guarantee success. |
| 400, quantity must be greater than zero | Stop unchanged automatic retries and correct the invalid input. | Changed parameters may require a new key; follow the provider contract. |
| Safe GET repeatedly returns 503 | Use capped exponential backoff with jitter and a bounded attempt/time budget. | Six retries is an example policy, not a standard. Stop and record exhaustion. |
| Retry budget exhausted | Use a defined recovery/escalation process rather than immediately restarting another batch. | A scheduled later attempt needs its own controls; indefinite batches defeat the budget. |

## Card-ready Q/A

### Card 1
Q: What unit does a numeric Retry-After use?
A: Seconds. Retry-After: 30 means at least 30 seconds; alternatively the field may specify an HTTP date.

### Card 2
Q: How should jitter interact with a server-required minimum wait?
A: Do not schedule earlier than the minimum. Randomize additional delay or otherwise enforce the lower bound.

### Card 3
Q: What problem does backoff solve?
A: It spaces retries to reduce pressure on a failing or overloaded dependency.

### Card 4
Q: What makes backoff exponential?
A: Delays grow multiplicatively, for example 5, 10, 20 and 40. Production policies should include a cap and a total retry budget.

### Card 5
Q: What problem does jitter solve?
A: It spreads retry times so many clients do not retry in synchronized bursts.

### Card 6
Q: What problem does idempotency solve?
A: It prevents repeated requests for the same operation from adding unintended business effects under the API contract; it is not congestion control.

### Card 7
Q: Should an unchanged invalid quantity be retried with backoff?
A: No. Time does not fix invalid input; correct it first.

### Card 8
Q: Can a changed payload automatically reuse its old idempotency key?
A: Do not assume so. Follow the API contract; many APIs reject key reuse with different parameters.

### Card 9
Q: Should a safe GET that returns 503 retry forever?
A: No. Use backoff/jitter with an attempt limit or deadline, then record failure and follow a bounded recovery/escalation policy.

### Card 10
Q: Does 429 necessarily apply to every customer and endpoint?
A: No. Determine the provider-defined quota scope, such as account, endpoint or shared global limit.

## References

- Assigned A8: https://aws.amazon.com/builders-library/timeouts-retries-and-backoff-with-jitter/
- Assigned A9: https://docs.aws.amazon.com/prescriptive-guidance/latest/cloud-design-patterns/retry-backoff.html
- Retry-After units: https://www.rfc-editor.org/rfc/rfc9110.html#name-retry-after

## Next start

Two-company research/motivation block, 30 focused minutes. Choose current target companies; do not assume the closed Sprig candidacy is active. No extra retry exercise required.
