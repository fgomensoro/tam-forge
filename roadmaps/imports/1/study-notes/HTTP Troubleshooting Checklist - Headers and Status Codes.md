---
title: HTTP Troubleshooting Checklist - Headers and Status Codes
type: study-note
topic: http-troubleshooting
created: 2026-08-26
updated: 2026-08-26
language: English
status: active
future-app-source: true
tags:
  - tam
  - http
  - api
  - troubleshooting
  - interview-preparation
---

# HTTP Troubleshooting Checklist — Headers and Status Codes

Related: [[HTTP, TCP, and TLS - TAM Interview Question Bank]]

## Core troubleshooting principle

An HTTP status code identifies the general result of a request. It does not prove the exact root cause. A TAM should combine the status code with the response body, headers, request details, logs, timing, scope, and recent changes before recommending a fix.

## Important HTTP headers

| Header | Direction | TAM purpose |
|---|---|---|
| `Authorization` | Request | Carries credentials such as a bearer token. Check presence, scheme, token validity, expiry, issuer, and audience. |
| `WWW-Authenticate` | Response | Describes how the client should authenticate after a `401` response. |
| `Content-Type` | Request or response | Describes the format of the body being sent, such as `application/json`. |
| `Accept` | Request | Describes the response formats the client can process. |
| `Host` | Request | Identifies the target host. It is especially relevant when several services share infrastructure. |
| `User-Agent` | Request | Identifies the client software and can help isolate client-specific behavior. |
| `Cache-Control` | Request or response | Defines caching behavior. Incorrect caching can produce stale or unexpected results. |
| `ETag` | Response | Identifies a specific version of a resource and supports conditional requests. |
| `If-None-Match` | Request | Asks whether the resource differs from a previously received `ETag`. |
| `Retry-After` | Response | Tells the client when it should try again, commonly with `429` or `503`. |
| `traceparent` or request-ID header | Request or response | Connects the customer-visible request to gateway, application, and dependency logs. |
| `Location` | Response | Identifies a newly created resource or redirect destination. |

## Status-code diagnostic checklist

### `401 Unauthorized`

**Meaning:** Authentication is missing, malformed, invalid, or expired. Despite the name, this normally means the client has not been successfully authenticated.

**Check:**

1. Is the `Authorization` header present and using the required scheme?
2. Is the token valid and unexpired?
3. Does the token have the correct issuer, audience, signature, and environment?
4. Does `WWW-Authenticate` provide a more specific reason?

**Action:** Correct or refresh authentication before retrying.

### `403 Forbidden`

**Meaning:** The server refuses the operation. In a common API scenario, the identity is recognized but lacks the necessary permission, role, scope, or resource access.

**Check:**

1. Which role or scope does the endpoint require?
2. Does the current token contain that role or scope?
3. Was the token issued before permissions changed and therefore needs refreshing?
4. Does the identity have access to this specific account, tenant, or resource?

**Action:** Correct authorization. Repeating the same unchanged request usually will not help.

### `404 Not Found`

**Meaning:** The route or requested resource was not found. Some APIs also use `404` to avoid revealing that a protected resource exists.

**Check:**

1. Verify the base URL, route, API version, and HTTP method.
2. Verify the path parameters and resource identifier.
3. Verify the environment, account, tenant, and region.
4. Confirm that the resource exists and has not been deleted or moved.

**Action:** Correct the route or resource context before retrying.

### `409 Conflict`

**Meaning:** The request is valid, but it conflicts with the resource's current state.

**Common examples:**

- A resource with the same unique identifier already exists.
- The client tries to update an outdated resource version.
- The requested operation is invalid in the resource's current workflow state.
- Concurrent processes attempt incompatible updates.

**Check:**

1. Read the error body for the specific conflicting resource or state.
2. Determine whether the resource already exists or changed after the client retrieved it.
3. Check unique identifiers, idempotency keys, version fields, and concurrent requests.

**Action:** Retrieve the current state, resolve the conflict, and then decide whether a modified request is safe.

### `429 Too Many Requests`

**Meaning:** The client exceeded a rate or usage limit.

**Check:**

1. Inspect `Retry-After` and available rate-limit headers.
2. Determine whether the limit applies by API key, customer, account, IP, or endpoint.
3. Measure the real request rate during the affected period.
4. Check whether an error loop or aggressive retry behavior amplified traffic.

**Action:** Follow `Retry-After` when provided. Otherwise use controlled exponential backoff with jitter, reduce unnecessary requests, and avoid synchronized retries.

### `500 Internal Server Error`

**Meaning:** The server encountered an unexpected condition. The status alone does not reveal which internal component failed.

**Check:** Capture the error response, request ID, timestamp, reproducibility, application evidence, and recent changes.

### `502 Bad Gateway`

**Meaning:** A gateway or proxy contacted an upstream service but received an invalid or unusable response.

**Check:** Identify the gateway and upstream service, inspect gateway logs, verify upstream health, and look for connection resets or malformed responses.

### `503 Service Unavailable`

**Meaning:** The service is temporarily unavailable, commonly because of maintenance, overload, insufficient capacity, or dependency health.

**Check:** Inspect `Retry-After`, service-health signals, capacity, deployment status, maintenance, and dependency availability.

### `504 Gateway Timeout`

**Meaning:** A gateway or proxy did not receive an upstream response within its configured timeout.

**Check:** Compare gateway timeout settings with upstream latency, identify slow dependencies, and determine whether the upstream operation eventually completed.

## The essential `5xx` distinction

```text
500 → The application encountered an unexpected error.
502 → The upstream service returned a bad response to a gateway.
503 → The service is temporarily unavailable.
504 → The upstream service did not answer the gateway in time.
```

## Evidence to collect before escalating a `5xx`

1. Exact timestamp and timezone
2. Environment, region, account, and tenant
3. HTTP method and endpoint
4. Sanitized request parameters or payload
5. Status code, response headers, and sanitized response body
6. Request, correlation, or trace ID
7. Response time
8. Frequency and reproducibility
9. Affected customers and business impact
10. Retry results
11. Recent application, configuration, infrastructure, or dependency changes
12. Relevant gateway, application, and dependency evidence

## Safe retry questions

Before retrying, ask:

1. Is the failure temporary?
2. Is the operation naturally idempotent?
3. If it changes state, does it use a reliable idempotency key or duplicate-prevention mechanism?
4. Could the first attempt have completed even though the client received an error or timeout?
5. Are `Retry-After`, backoff, jitter, and retry limits being respected?

Blindly retrying a state-changing request can create duplicate orders, charges, or records.

## Day 2 review priorities

- Do not confuse `403 Forbidden` with `402`.
- Practice explaining `409 Conflict` using a real state-conflict example.
- Distinguish `502`, `503`, and `504` by identifying the gateway, upstream service, availability, and timeout behavior.

## Sources

- [Postman: What are HTTP headers?](https://blog.postman.com/what-are-http-headers/)
- [HTTP.dev: HTTP status codes](https://http.dev/status)
- [MDN: HTTP headers](https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers)
- [MDN: HTTP response status codes](https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Status)

