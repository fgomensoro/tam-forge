---
title: Northstar Scenario 1 - API Down but Monitoring Green
date: 2026-08-27
type: case-analysis
topic: api-troubleshooting
language: English
status: guided-completion
future-app-source: true
tags:
  - tam
  - northstar
  - api
  - troubleshooting
  - customer-communication
---

# Northstar Scenario 1 — “Your API Is Down,” but Monitoring Is Green

Legacy roadmap: [[Roadmap.archive-20260828-month1-v2/Week 1 - SQL foundations, HTTP, troubleshooting, and story inventory|Week 1 — Day 2]]
Current Phase 1 coverage: [[Roadmap/docs/Coverage Ledger#m1-w1-d02-case]]

## Scenario

Northstar Retail reports that the integration platform's API is down, while global platform monitoring remains green. The report must be converted from a broad conclusion into specific, testable symptoms before proposing a fix.

## Fifteen clarifying questions

1. **Exact symptom and evidence:** What exact error are you receiving? Please provide the HTTP status code, response body, affected endpoint, timestamp with timezone, and a request or correlation ID.
2. **Scope:** Is this affecting every request or only a subset? If it is a subset, do the failures share an endpoint, event type, account, region, payload characteristic, or time window?
3. **Timeline and pattern:** When did you first observe the problem, including the timezone? Have requests failed continuously since then, or are successful and failed requests interspersed? When was the last known successful request?
4. **Business impact:** How is this affecting your operation? Is it blocking order creation or fulfillment? Approximately how many orders or users are affected, and do you have a temporary workaround?
5. **Recent changes:** Were there any recent changes to the storefront, marketplace connection, credentials, account settings, network, or order data shortly before this began—including changes made by a vendor?
6. **Reproducibility:** When you repeat the same failed operation, does it fail every time? Are all affected operations returning the same status code and error message, or are you seeing different errors?
7. **HTTP response versus connection failure:** Are you receiving an HTTP status code and response body, or is the request failing before any HTTP response through a timeout, DNS, TLS, or connection error?
8. **Acceptance versus downstream completion:** Does the API return a successful status such as `200` or `202`? If so, do you receive a request or event ID, and is the actual failure that the order never appears in the ERP?
9. **Failed-versus-successful comparison:** Can you provide one failed and one successful request from the same period, including timestamps, endpoint, method, sanitized headers and payloads, status codes, response bodies, and request IDs?
10. **Tenant or credential isolation:** Do the failed requests share the same account, tenant, store, or credential? Does the same operation succeed when performed through another one?
11. **Latency and client timeout:** Are the requests timing out? If so, after how many seconds, what timeout is configured on your client, and do any timed-out operations later complete successfully?
12. **Retry behavior:** What retry policy is configured—maximum attempts, delay, backoff, and jitter? Are retries still running, exhausted, or blocked, and could they be increasing the request volume?
13. **Authentication:** Are the affected requests returning `401` or `403`? When was the access token issued, when does it expire, and did token refresh or reauthentication succeed? What exact authentication error was returned?
14. **Network or regional isolation:** Do the failed requests share the same network, source IP, office, internet provider, or geographic region? Do requests from another network or region succeed?
15. **Backlog and workaround:** How many orders are currently affected or backlogged, what is the oldest affected order, and can your team temporarily process them manually or through an alternative workflow while we investigate?

> [!warning] Credential handling
> Never ask a customer to send an access token, refresh token, API key, password, or other secret. Request sanitized logs and non-sensitive authentication metadata according to company policy.

## Study questions and model answers

### How should a TAM respond when a customer says, “Your API is down”?

Do not accept or reject the conclusion immediately. Convert it into observable symptoms by collecting the exact error, status code, response body, endpoint, timestamp, request ID, affected scope, and business impact. Global monitoring can remain green during customer-specific, regional, endpoint-specific, authentication, or downstream failures.

### What is the difference between a customer question and an investigation action?

A customer question collects missing context or evidence, such as a request ID or affected account. An investigation action uses that evidence internally, such as searching logs or comparing service metrics. Ask focused questions before jumping to internal fixes.

### What does receiving a `404` prove?

It proves that an HTTP server or gateway responded. The problem is therefore not a complete DNS, TLS, or network outage. The cause may be an incorrect route, method, version, environment, tenant, resource identifier, or an intentionally hidden protected resource.

### Why does a `200` or `202` not always prove business success?

The status applies to the endpoint's contract. It may mean that the API accepted or queued the request, while asynchronous ERP creation or another downstream operation can still fail later. Use a request or event ID to trace the complete workflow.

### Why compare a failed request with a successful request?

A controlled comparison can reveal the discriminating variable: endpoint, tenant, credential, payload field, region, timestamp, client version, or network. Compare complete sanitized request-and-response pairs from the same period.

### What evidence should be sanitized before sharing?

Remove access tokens, refresh tokens, API keys, passwords, payment details, and unnecessary personal data. Preserve safe diagnostic evidence such as timestamps, request IDs, endpoint names, status codes, error types, and non-sensitive metadata.

### Why are timeouts dangerous for state-changing operations?

The client may time out even though the server eventually commits the operation. An automatic retry can then create a duplicate order, payment, or record. Before retrying, determine whether the first operation completed and use idempotency or duplicate detection where possible.

### What should be captured about retry behavior?

Capture maximum attempts, retry interval, backoff strategy, jitter, terminal state, and current retry volume. Confirm that retries are not amplifying an outage or rate-limit condition.

### What authentication evidence is safe to request?

Request the HTTP status, exact authentication error, token issue and expiry times, refresh result, and sanitized metadata according to company policy. Never request the actual access token, refresh token, API key, or password.

### How should customer impact be measured?

Measure affected users, stores, tenants, and orders; backlog size and age; blocked workflows; financial or fulfillment exposure; and whether a temporary workaround exists. “The API is down” is not an adequate impact statement.

### What makes a good clarifying question?

A good question resolves a specific uncertainty, requests evidence the customer can reasonably provide, avoids embedding an unproven diagnosis, and changes the next investigation decision.

## Three hypotheses

### Hypothesis 1 — Northstar's token has insufficient scopes

**Hypothesis:** Northstar's OAuth access token may not contain the scope required for the affected operation.

**Why global monitoring could remain green:** Global monitoring may use a different tenant, credential, role, or scope set and therefore would not detect a Northstar-specific authorization failure.

**Evidence that would support it:**

- Northstar receives `403 Forbidden` responses.
- The response or `WWW-Authenticate` information indicates `insufficient_scope` or a missing permission.
- Refreshing the token produces another token with the same insufficient scope set.
- The problem began after credential, role, or authorization-policy changes.
- Other customers or credentials with the required scope continue succeeding.

**Evidence that would falsify it:**

- The same Northstar credential succeeds against the same endpoint, resource, and operation.
- The token contains the required scope and authorization checks succeed.
- Failed requests pass authorization and later return a downstream `5xx` response or timeout.
- Multiple unrelated credentials with correct scopes fail in the same way.

### Hypothesis 2 — Northstar-specific routing or deployment problem

**Hypothesis:** Northstar's order-creation requests may be affected by a tenant-specific routing or deployment configuration problem inside the integration platform.

**Why global monitoring could remain green:** Global monitoring may use a synthetic tenant, another region, a general health endpoint, or a request that does not exercise Northstar's tenant-specific order-creation route.

**Evidence that would support it:**

- The same method, endpoint, and equivalent sanitized payload succeed for another tenant but fail for Northstar.
- Other tenants in the same region succeed, isolating the failure to Northstar's tenant configuration.
- Northstar requests consistently route to the wrong, missing, or unhealthy upstream target.
- Gateway or routing logs show a tenant-specific route, deployment version, feature flag, or configuration difference.
- A controlled request succeeds after correcting only the Northstar routing or tenant configuration.

**Evidence that would falsify it:**

- A controlled Northstar request reaches the correct service and succeeds through the same route.
- Northstar and comparison tenants use identical routing and deployment configuration.
- Evidence shows that the failure occurs before routing, such as invalid authentication.
- Evidence shows that the request routes correctly and fails later in the ERP or another downstream dependency.

### Hypothesis 3 — Downstream ERP or asynchronous-processing failure

**Hypothesis:** Northstar's request may reach the integration API successfully, while asynchronous processing or the ERP fails afterward.

**Why global monitoring could remain green:** General API monitoring may verify health or synchronous request acceptance without exercising Northstar's complete asynchronous workflow and ERP dependency.

**Evidence that would support it:**

- The API returns `200` or `202` and provides a request or event ID.
- Ingestion logs confirm that the platform accepted the request.
- Orders accumulate in a pending or unsent state.
- Worker logs show ERP timeouts, `429` responses, `5xx` responses, authentication failures, or validation errors.
- Orders never appear in the ERP even though other API operations succeed.

**Evidence that would falsify it:**

- Failed requests never reach the integration platform.
- Authentication or tenant routing rejects the request before asynchronous processing begins.
- The ERP operation completes successfully and the expected order is present.
- A controlled end-to-end request through the same path succeeds while the customer request fails before acceptance.

## Supporting and falsifying evidence

Supporting evidence makes a hypothesis more likely. Falsifying evidence is deliberately sought because a good investigation attempts to disprove its own assumptions. The evidence for each hypothesis is recorded directly under that hypothesis above.

## Investigation order

1. **Establish severity and scope.** Confirm the affected workflow, tenants, regions, start time, backlog, oldest affected order, and business impact.
2. **Trace one failed and one successful example.** Use timestamps and request IDs to follow both requests across the gateway, API, asynchronous worker, and ERP.
3. **Segment the failures.** Compare status codes and results by endpoint, tenant, credential, payload type, client, network, and region.
4. **Validate authentication and routing.** Confirm token scope and expiry, tenant configuration, route selection, deployment version, and feature flags against a known-good comparison.
5. **Inspect asynchronous and downstream health.** Check pending work, worker failures, ERP response codes and latency, rate limits, recent changes, and whether timed-out operations later completed.

## First mitigation

**Mitigation:** Ask Northstar to stop aggressive or manual blind retries while the team preserves affected orders for controlled replay. If operations are critically blocked, agree on a small, deduplicated manual path for priority orders.

**Why it is appropriate:** Timed-out state-changing requests may already have completed. Uncontrolled retries can create duplicate ERP orders and increase load during an incident.

**Risk:** Pausing retries can temporarily delay valid orders, while a manual workaround can introduce human error.

**Verification:** Monitor new request volume, backlog growth, duplicate-order indicators, and the success of a small controlled replay.

**Rollback condition:** Restore normal automated processing only after the failing layer is stable and replay or duplicate-prevention behavior has been verified.

## Customer update

> We are investigating your report that order requests are failing. Our global monitoring is currently green, but that does not rule out a Northstar-specific, endpoint-specific, regional, or downstream issue. We are tracing failed and successful examples across authentication, tenant routing, asynchronous processing, and ERP delivery. We still need the exact backlog and business impact, so please provide the oldest affected order and one failed request ID if available. To reduce duplicate risk, please avoid additional manual retries until we confirm whether timed-out operations completed. We own the investigation and will provide the next update within 30 minutes.

## Spoken summary

Use this two-minute structure without reading full sentences:

1. Customer report and business risk
2. Why green monitoring does not dismiss the report
3. Three testable hypotheses
4. First five investigation actions
5. Safe temporary mitigation
6. Ownership and next update time

## Assessment note

- Clarifying questions were completed interactively.
- Hypothesis 1 was produced by Frank with correction.
- Hypotheses 2–3, investigation order, mitigation, and customer update were completed as guided model material to protect the study timebox.
- This case should be revisited later through retrieval practice rather than extended further today.
