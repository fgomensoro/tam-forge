---
type: pipeline-action
phase: 1
roadmap-version: phase-1-six-week-v1
mapping-version: phase-1-transition-v1
status: draft
future-app-source: true
---

# Pipeline Action

Use one note per completed action. Do not store secrets, private recruiter messages, personal contact details, or unredacted customer information.

## Machine-readable record

- action-type: application | recruiter-reply | legacy-artifact
- company: —
- role: —
- source-url-or-context-snapshot: —
- relevance: —
- known-gap: —
- resume-or-story-version: —
- date: —
- completed-action: —
- stage: identified | prepared | applied | recruiter-contact | screen | interview | offer | closed
- exact-next-action: —
- counts-toward-weekly-target: false
- outcome: pending
- outcome-date: —
- conversion-stage-from: —
- conversion-stage-to: —
- evidence: —

## Counting contract

- Count only `application` or `recruiter-reply` when the action is complete, substantive, role-relevant, privacy-safe, and the quality checklist passes.
- A recruiter acknowledgement does not count. A substantive recruiter reply that advances or clarifies the opportunity may count.
- Research alone does not count unless it creates the exact required legacy artifact. Record that separately as `legacy-artifact`; it remains visible but never enters the weekly application/reply total.
- The target is ten quality applications or substantive recruiter replies per full operating week—not two rushed applications every day.
- Week 1 transition is actuals-only. The ten-action target begins in Week 2, the first full operating week.
- One action is one completed application or substantive reply. Preparation fragments and repeated follow-ups for the same unchanged action do not create extra counts.

## Quality checklist

- [ ] The role and company are identified.
- [ ] Relevance to the TAM target is stated.
- [ ] One known gap or risk is stated honestly.
- [ ] The résumé/story version used is recorded.
- [ ] The completed action and exact next action are observable.
- [ ] The source URL or a privacy-safe context snapshot is saved.
- [ ] Customer, employer, recruiter, and personal data are redacted where needed.
- [ ] No API keys, passwords, access tokens, private links, or proprietary payloads are present.
- [ ] The action is not only research or an automatic recruiter acknowledgement.
- [ ] `counts-toward-weekly-target` matches the counting contract.

## Outcome and conversion review

Record the outcome even when it is negative or there is no response.

- Response received: yes | no | pending
- Response quality: substantive | acknowledgement-only | none
- Interview created: yes | no | pending
- Final outcome: advanced | rejected | withdrawn | no-response | pending
- Conversion note: —
- Follow-up due: —
