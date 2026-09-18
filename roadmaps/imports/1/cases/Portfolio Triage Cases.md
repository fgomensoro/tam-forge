# Portfolio Triage Cases

These cases add the portfolio judgment that TAM interviews commonly test: several customers need attention at the same time, but you cannot personally investigate everything at once.

Use one case each Saturday from Week 2 onward. Do not add study time; the weekly roadmap already reserves time for it.

## Operating rules

1. Ask only the minimum questions needed to determine priority.
2. Make an explicit ranking. Do not say that everything is equally urgent.
3. Separate **severity** from account size or customer loudness.
4. Decide what you personally own, what you delegate, and what you escalate.
5. Give every customer an immediate response and a next-update time, including customers not ranked first.
6. State what new evidence would change your ranking.
7. When the scenario changes, reprioritize rather than defending the original answer.
8. Deliver the exercise in English.

Use [[../templates/portfolio_triage|the portfolio triage template]] for every case.

---

# Week 2 — Two competing incidents

## Initial state

### Customer A — Northstar Retail

- 18% of checkout payment attempts are failing in production.
- The issue began 12 minutes ago.
- No reliable workaround has been confirmed.
- Failed attempts directly prevent customers from purchasing.
- Northstar launches a major campaign today.
- Payments Engineering has not yet joined the incident.

### Customer B — BluePeak Commerce

- ERP order synchronization is delayed by approximately 45 minutes.
- Events are currently queued and no permanent data loss is confirmed.
- Operations can manually export urgent orders every 30 minutes.
- The backlog has been growing for two hours.
- BluePeak's operations director has escalated through WhatsApp.

## Your task — 20 minutes

1. Ask up to six clarifying questions.
2. Rank the two customers.
3. Define your first action for each.
4. Assign owners and escalation paths.
5. Give both customers an update cadence.
6. Explain what evidence would reverse your ranking.

## Mid-case injection

After ten minutes, assume:

- Northstar's failure rate falls from 18% to 3% after a rollback, but root cause remains unknown.
- BluePeak's queue begins rejecting new events because storage is near capacity.

Re-rank the situations and explain the change.

## Strong-answer signals

- Direct financial/customer impact is initially prioritized over a safely queued delay.
- BluePeak is still acknowledged and actively delegated rather than ignored.
- The ranking changes when BluePeak develops credible data-loss risk.
- Account size or who complained most loudly is not the primary criterion.

---

# Week 3 — Reactive work versus proactive account commitments

## Portfolio snapshot

### Northstar Retail

- Payment retry rate increased from 0.5% to 2.5%.
- All retries are currently succeeding.
- No customer-visible payment loss is confirmed.

### Meridian Market

- Production launch is in three days.
- Rollback criteria and alert ownership are not finalized.
- The customer needs a launch-readiness review.

### Cedar Finance

- OAuth migration deadline is in ten days.
- 40% of connected accounts have not reauthorized.
- Missing the deadline will disconnect those accounts.

### Alto Supply

- Requests a general architecture review.
- No incident, deadline, or committed project depends on it.

### Harbor Goods

- Renewal is in 60 days.
- Product adoption is 20%.
- The executive sponsor has stopped attending meetings.
- No current production incident exists.

## Your task — 20 minutes

1. Rank the five accounts for the next working day.
2. Allocate a hypothetical eight-hour day across them.
3. State what you personally handle and what you delegate.
4. Protect at least one proactive activity; do not allow all time to become firefighting.
5. Give each customer a communication or follow-up commitment.
6. State the conditions that would change your schedule.

## Mid-case injection

Northstar's retry success drops and 12% of payments now fail without a workaround.

Rebuild the schedule in two minutes and explain what gets displaced, delegated, or rescheduled.

## Strong-answer signals

- Meridian and Cedar receive proactive attention because deadlines create future production risk.
- Harbor's renewal risk is not ignored merely because there is no incident.
- Alto is deliberately scheduled later with clear expectation setting.
- Northstar moves to the top only after material customer impact is confirmed.

---

# Week 4 — Five-customer timed portfolio triage

## Incoming situations

### Customer A — Small account, direct financial risk

- Five potentially duplicate card captures are confirmed.
- The affected volume is low, but customers may have been charged twice.
- No automatic reversal has been confirmed.

### Customer B — Largest account, broad but contained delay

- 30,000 order events are delayed.
- Events are durably queued and processing continues slowly.
- No confirmed loss or corruption exists.
- A manual priority lane is available for critical orders.

### Customer C — Launch tomorrow

- Final testing shows the integration does not deduplicate retried order creation.
- The launch plan assumes at-least-once delivery.
- The customer asks for approval to proceed anyway.

### Customer D — Authentication degradation

- OAuth refresh tokens were revoked for 30 customer accounts.
- Reconnection is required.
- The issue is limited to one product integration.

### Customer E — Executive feature request

- A strategic customer's CTO wants a roadmap commitment before next week's QBR.
- No production issue or contractual deadline exists today.

## Your task — 15 to 20 minutes

1. Ask up to eight clarifying questions.
2. Rank all five situations.
3. For each one, state:
   - Immediate action.
   - Owner.
   - Customer message.
   - Next review time.
4. State which proactive commitment you will preserve.
5. Explain what you will not do personally.

## Interviewer injections

Use at least two:

- Customer B's durable queue starts dropping new events.
- Customer A's processor confirms automatic reversals are already underway.
- Customer C agrees to a limited launch with a feature flag and manual reconciliation.
- Customer D affects a regulated workflow with a hard reporting deadline.
- Customer E's request becomes tied to a signed renewal condition.

Reprioritize after every injection.

## Strong-answer signals

- Five duplicate charges may outrank high-volume delay because financial integrity and trust matter.
- The largest account is not automatically first.
- The launch is not approved merely to please the customer.
- Every lower-priority customer still receives ownership and communication.
- The answer changes when evidence changes.

---

# Scoring rubric — 20 points

| Dimension | Points | Standard |
|---|---:|---|
| Impact and risk assessment | 0–4 | Distinguishes financial, data, security, compliance, availability, and operational risk |
| Explicit prioritization | 0–3 | Makes a clear ranking and defends it |
| Delegation and ownership | 0–3 | Uses Support, Engineering, Product, and customer owners rather than personally doing everything |
| Communication control | 0–3 | Gives every customer a message and next-update time |
| Proactive-work protection | 0–2 | Prevents the portfolio from becoming permanently reactive |
| Reprioritization | 0–3 | Changes the plan when new evidence changes risk |
| English clarity | 0–2 | Concise, decisive, and understandable under time pressure |

**Pass target:** 14/20 in Week 2, 15/20 in Week 3, and 16/20 by the Month 1 final assessment.

## Five-minute answer structure

1. **Decision:** “My current priority order is…”
2. **Reason:** one sentence per customer using impact, risk, deadline, and workaround.
3. **Execution:** what you own, delegate, and escalate.
4. **Communication:** immediate message and next-update cadence for each customer.
5. **Reversal conditions:** what new facts would change the order.
