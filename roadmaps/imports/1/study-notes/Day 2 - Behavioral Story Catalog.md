---
title: Day 2 - Behavioral Story Catalog
date: 2026-08-27
type: behavioral-story-catalog
language: English
status: first-pass
future-app-source: true
tags:
  - tam
  - behavioral-interview
  - story-catalog
  - career
---

# Day 2 — TAM Behavioral Story Catalog

Legacy roadmap: [[Roadmap.archive-20260828-month1-v2/Week 1 - SQL foundations, HTTP, troubleshooting, and story inventory|Week 1 — Day 2]]
Current Phase 1 coverage: [[Roadmap/docs/Coverage Ledger#m1-w1-d02-communication]]

## Catalog

The catalog contains only validated facts supplied by Frank. Missing information is labeled rather than invented.

| ID | Polished story title | Competencies | Known context and actions | Known result or evidence | Information still needed |
|---|---|---|---|---|---|
| S01 | Correcting an order assigned to the wrong customer | Ownership, customer judgment, incident response, technical depth | An order was processed under the wrong customer. | A real production/customer-data incident occurred. | Root cause, detection, immediate containment, customer communication, correction, prevention, and business impact. |
| S02 | Maintaining customer ownership during a conflicting meeting | Prioritization, customer judgment, communication, ownership | While Frank was in a meeting, a customer called. He could not answer, so he immediately acknowledged the issue by message and stated that he was taking ownership. | The customer received an immediate acknowledgment rather than silence. | Actual severity, competing priorities, response time, investigation, final result, and whether the promised timeline was met. |
| S03 | Sending Odoo orders to Zeta ERP within seconds | Technical depth, implementation, ownership, business impact | Built or supported an integration that moved Odoo orders into Zeta ERP within seconds. | Near-real-time order delivery. | Previous process, precise architecture, Frank's actions, measured latency, reliability, adoption, and customer impact. |
| S04 | Diagnosing missing Mercado Libre OAuth scopes | Technical depth, troubleshooting, ambiguity, customer judgment | A Mercado Libre token lacked required scopes, preventing retrieval of complete order information. | The authorization-scope problem was identified. | Diagnostic steps, misleading symptoms, exact fix, verification, customer impact, and prevention. |
| S05 | Building an application and back office for a medical clinic | Ownership, ambiguity, project leadership, business impact | Built an application and administrative back office for users of a medical clinic. | A complete customer-facing and administrative product was produced. | Customer problem, requirements, constraints, stakeholders, decisions, delivery result, usage, and measurable value. |
| S06 | Recovering from transcript loss during a meeting-bot migration | Failure, ownership, technical depth, learning | During a meeting-bot migration, one meeting transcript was lost. Database backups operated at four-hour intervals, and recovery produced approximately three hours of duplicated data. | Concrete data-loss and recovery incident with a known backup limitation. | Why the migration failed, immediate communication, recovery and deduplication actions, permanent safeguards, and final customer impact. |
| S07 | Consolidating origin and destination DAGs into one orchestrated workflow | Technical depth, proactive improvement, ownership, business impact | Converted separate origin and destination DAGs into tasks inside one chained DAG. | Processing rounds decreased from approximately five minutes to approximately one minute. | Initial bottleneck, design trade-offs, rollout safety, reliability effect, scale, and customer value. |
| S08 | Moving webhook processing from Airflow to FastAPI workers | Technical depth, proactive improvement, architecture judgment, business impact | Moved immediate webhook handling to a FastAPI worker because Airflow pod startup added substantial latency. Airflow remained the reconciliation path. | Webhook processing decreased from approximately three minutes to under thirty seconds. | Rollout method, monitoring, failure recovery, volume, measured percentile, and customer impact. |
| S09 | Designing a multitenant integration platform | Ownership, ambiguity, project leadership, technical depth | Built or helped build a multitenant integration platform. | The platform supported multiple customers. | Frank's exact ownership, tenant-isolation design, hardest decision, security and scale constraints, incident history, and business result. |
| S10 | Growing the integration platform from zero to twenty-five clients | Ownership, business impact, leadership, prioritization | Contributed to growing the platform from zero to twenty-five clients. | Customer count increased from 0 to 25. | Timeframe, Frank's specific contribution, technical and operational changes, retention, revenue or usage evidence, and hardest scaling challenge. |

## Competency coverage

| Competency required by the roadmap | Current candidate stories |
|---|---|
| Ownership | S01, S02, S03, S05, S06, S07, S08, S09, S10 |
| Conflict | No strong specific story yet |
| Ambiguity | S04, S05, S09 |
| Customer judgment | S01, S02, S04 |
| Technical depth | S01, S03, S04, S06, S07, S08, S09 |
| Business impact | S03, S05, S07, S08, S10 |

## Strongest five candidates for immediate development

1. **S10 — Platform growth from 0 to 25 clients:** strongest potential business-impact and ownership story.
2. **S08 — Webhook latency from 3 minutes to under 30 seconds:** strongest architecture-judgment story.
3. **S04 — Mercado Libre OAuth scopes:** strongest concise API troubleshooting story.
4. **S06 — Transcript loss during migration:** strongest failure, ownership, and learning story.
5. **S01 — Order assigned to the wrong customer:** strongest customer-judgment and incident-response candidate.

S07 is a strong alternative when an interviewer asks specifically about performance improvement or process redesign.

## Interview-quality warning

S02 is not complete until the incident has a verified outcome. In interviews, avoid promising that a solution will be found by a specific time before the issue is understood. Promise ownership and the next update time instead.

## Behavioral story-selection principles

1. **Decode the question first.** Identify the competency being tested, such as ownership, conflict, ambiguity, judgment, technical depth, or impact.
2. **Select evidence, not merely a related topic.** Choose a story in which Frank personally made decisions and can explain the result.
3. **Prefer meaningful stakes.** The best stories involve customer impact, business risk, difficult trade-offs, or measurable improvement.
4. **Separate “we” from “I.”** Explain the team context, then identify Frank's specific responsibility, actions, and decisions.
5. **Use a complete arc.** Situation and stakes → responsibility → actions and decisions → result → learning.
6. **Do not invent metrics.** Use verified measurements, honest directional outcomes, or state that the exact historical value is unavailable.
7. **Match one primary competency.** A story can demonstrate several skills, but the answer should emphasize the competency asked by the interviewer.
8. **Include reflection.** Explain what changed afterward and what Frank would repeat or improve.

## Next enrichment fields

For every strong story, collect:

1. Situation and stakes
2. Frank's responsibility
3. Exact actions and decisions
4. Alternatives or trade-offs
5. Result with evidence
6. Learning and what changed afterward
