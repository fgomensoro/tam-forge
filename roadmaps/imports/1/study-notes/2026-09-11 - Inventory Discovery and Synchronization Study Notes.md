---
date: 2026-09-11
type: study-note
language: English
status: validated
future-app-source: true
flashcard-source: true
assistance: coached
assessment-status: not-independently-assessed
---

# Inventory Discovery and Synchronization

## Corrected and validated note

### Concise rule

Translate the customer’s freshness requirement into an end-to-end latency budget, then verify source capabilities, destination updates, and recovery before selecting a design.

### Plain-English explanation

**Total delay = wait for next poll + fetch/process time + ecommerce update time.**

A polling interval is only one part of this budget. A 60-second interval can consume the entire allowance before processing starts. With a five-minute interval, a change can wait almost zero to almost five minutes under normal scheduling; additional work adds time. Tests must include changes immediately after a poll. A proposed 50-second internal target leaves 10 seconds of margin against the agreed 60-second requirement, but an average below 50 seconds can conceal failures.

### Practical TAM example

Fictional facts: the ERP owns physical stock and available-to-sell equals on-hand minus reservations. A store sale changed SKU JACKET-M from one available unit to zero at 10:01. Ecommerce still showed one at 10:03, when WEB-184 was accepted. Ecommerce polls every five minutes. Physical stores, the website, a marketplace, and warehouse adjustments affect stock. The customer requested propagation within 60 seconds; webhook support remains unknown.

Discovery should establish authoritative data, the acceptable delay, concrete order/timestamp evidence, every stock-changing channel, reservations, and the end-to-end update path. Five-minute polling is a plausible explanation, not a confirmed root cause without logs.

Provisional recommendation: verify ERP-originated inventory notifications and destination update capabilities. If suitable webhooks exist, measure their delivery and full processing path. Otherwise evaluate polling with sufficient margin, compatible API capacity, and customer constraints. Validate changes immediately after a poll and under representative peak load, inspect individual delays/breaches, and agree on the service-level definition. Choose reconciliation frequency from business tolerance and recovery needs.

### Boundary or common mistake

Ecommerce webhooks cannot report changes recorded only in the ERP. Moving store transactions into ecommerce is a business workflow redesign, not an assumed implementation shortcut. Webhooks are not guaranteed instant delivery. Faster-than-required service may add cost or complexity without sufficient benefit. Avoid inventing a 30-second requirement or treating daily reconciliation as adequate without discovery.

### Card-ready Q/A

#### Card 1
Q: What is the end-to-end inventory synchronization delay?
A: Total delay = wait for next poll + fetch/process time + ecommerce update time. Include every stage between the authoritative stock change and its visible destination update.

#### Card 2
Q: What is the worst-case wait for a scheduled poll?
A: A change just after a poll waits almost the full polling interval, assuming the schedule runs as intended. Scheduling delays or failures can add more.

#### Card 3
Q: Why does polling every 60 seconds not guarantee synchronization within 60 seconds?
A: A change may wait almost 60 seconds before fetching even begins; processing and publication then add latency.

#### Card 4
Q: What condition must polling meet for a 60-second target?
A: The polling wait plus fetch/process time plus ecommerce update time must fit within 60 seconds, with operating margin. Check API capacity and load as well as duration.

#### Card 5
Q: What delay does a five-minute poll imply?
A: The scheduling wait ranges from almost zero to almost five minutes, plus processing/publication time. It is not always five minutes; failures or scheduling delays can make it longer.

#### Card 6
Q: When should a test stock change occur to exercise the worst polling wait?
A: Immediately after a scheduled poll, so the change waits nearly the entire interval.

#### Card 7
Q: Where should the synchronization timer start and stop?
A: Start when the physical-store sale changes available-to-sell stock in the authoritative ERP; stop when ecommerce reflects that state. Merely starting the purchase or receiving an API response may measure different boundaries.

#### Card 8
Q: Is an internal target below 50 seconds useful for a 60-second requirement?
A: Yes, as a proposed 10-second safety margin. It is not a substitute for verifying the full requirement or proof that the system meets it.

#### Card 9
Q: Why is an average below 50 seconds insufficient?
A: It can hide individual updates that exceed 60 seconds. Review per-update delay, breaches, and representative peak-load behavior; agree on the required service-level measurement.

#### Card 10
Q: Does one passing synchronization test establish reliability?
A: No. Repeat across relevant conditions, including worst polling alignment and expected peak load. Observed test success does not guarantee every future update.

#### Card 11
Q: Which system must emit a webhook for an ERP-originated stock change?
A: The ERP, or another mechanism actually observing that ERP change. Ecommerce webhook availability alone does not notify the integration of a physical-store stock change recorded only in the ERP.

#### Card 12
Q: What capabilities are needed at both ends of the stock flow?
A: Verify how changes can be obtained from the authoritative ERP and how the destination ecommerce stock can be updated. Outbound webhook support and an inbound update API are different capabilities.

#### Card 13
Q: Does webhook availability guarantee a sub-60-second update?
A: No. Delivery, queues, processing, destination API behavior and failures still affect end-to-end delay. Validate the actual path and retain recovery mechanisms.

#### Card 14
Q: How do a requirement and a solution differ in this case?
A: The requirement is to reflect available-to-sell changes within 60 seconds. Polling and webhooks are solution options. Under 30 seconds was not an agreed customer requirement.

#### Card 15
Q: Is faster synchronization always better?
A: Not automatically. Evaluate customer value against cost, complexity, API limits, and reliability while meeting the agreed requirement.

#### Card 16
Q: What is available-to-sell inventory in the fictional case?
A: On-hand stock minus reservations. This definition was supplied for the scenario; confirm the real customer’s definition before designing a production integration.

#### Card 17
Q: What evidence should discovery request for overselling?
A: A recent order ID, timestamps, and stock shown in each system, plus the systems and channels that change or reserve inventory. Ask for evidence rather than expecting the customer to diagnose the cause.

#### Card 18
Q: Does the five-minute polling interval prove the cause of the example oversell?
A: It is a plausible explanation for the stale display, but sync logs and state history are needed to confirm the incident sequence and exclude other causes.

#### Card 19
Q: Can moving physical-store invoicing to ecommerce solve the integration problem automatically?
A: No. That is a workflow redesign requiring customer agreement and validation of store operations, stock/reservation semantics, and invoicing. It cannot be assumed as an acceptable technical fix.

#### Card 20
Q: How should reconciliation frequency be chosen?
A: Use the acceptable discrepancy window, business impact, API capacity, and recovery needs. Once or twice a day was an unvalidated proposal, not an established requirement.

#### Card 21
Q: Why keep a recommendation provisional during discovery?
A: Webhook availability, API limits, sync duration, and operating constraints are not yet confirmed. State what must be verified before selecting the design.

## Validation evidence and learning status

- Basis: supplied fictional case facts and corrections reviewed in this conversation. No production system, benchmark, or customer result was measured.
- Reviewer: Codex. Validated study content does not mean independent learner mastery.
- Coverage: m1-w1-d05-case. Discovery questions, requirement/risk reasoning, latency testing, and provisional recommendation were completed with substantial coaching and a model recommendation. A separate uncoached case gate is not established.
- Important corrected ideas: source/destination webhook direction, requirement versus solution, polling interval versus total delay, equal attention to per-update breaches and aggregate measures, and customer approval of workflow changes.
- Actual focused time: unknown. No audio file received.
- H10 reading and its closed-source recall remain scheduled for Saturday; this case does not mark them complete.
- Exact next Friday action: Northstar SQL 7, 8, 9, and 13 under the Friday/extended-Saturday plan; no restart of completed DataLemur S3–S5.
