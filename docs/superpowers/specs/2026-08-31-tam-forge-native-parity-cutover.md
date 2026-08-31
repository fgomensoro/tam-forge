# TAM Forge native evidence and client cutover

Status: Locked on 2026-08-31. User approved D1/D2 and confirmed the Sol xhigh execution handoff.

## 1. Outcome and scope

Finish the already-approved full SwiftUI client migration. Deliver E10-I09 (#125), then E10-I10 (#126). Two broad tickets form a coherent batch; do not pad it with recording work to reach fifteen. Split execution into three reviewable PRs: evidence, parity/replacement checks, then web removal.

This extends the locked `2026-08-28-tam-forge-native-macos-redesign.md`, not its audio, privacy, signing, deployment, or English-analysis decisions. The interface remains a native macOS workspace, using the existing design language and controls.

Non-goals: recording, ASR, new scoring formulas, new AI feedback, new database schema, roadmap-v2 changes, server provisioning, public distribution, DMG release, paid services, and production configuration. In particular, implementing the Evidence destination does not imply that an unimplemented AI feedback report exists.

## 2. Verified baseline

- Planning base: `52c0858221524fa6c35fb18c2804c0d5874ce62a`, PR #129 merged; main CI run `33428685373` passed. Batch 01 tickets #117–#124 are closed. Recheck before execution.
- The native shell implements Today, notifications, roadmap administration, activities, authentication and transport. Its Evidence action currently displays a migration notice and drops the activity ID.
- The backend exposes owner-authenticated read-only skill, evidence-event and portfolio APIs. They set `Cache-Control: no-store`; Decimal response values are strings in the generated contract.
- Browser evidence UI shows skill snapshots, formula manifests, confidence/trend bases, and separate portfolio scores. Its first-page-only behavior is not a reason to hide older evidence in SwiftUI.
- Native UI tests use a DEBUG-only URLProtocol fixture. Browser e2e tests currently also exercise persistent PostgreSQL/object-storage behavior. Removing the browser must not silently remove that coverage.
- Production and preview API hosts remain `.invalid`. Merged client code is not a deployment. The separate dirty roadmap worktree and old recording branch are outside scope.

## 3. Approach and alternatives

Selected: reuse generated API types, existing URLSession transport, feature-local state and native controls; migrate evidence, establish replacement checks, then remove tracked web code/tooling in Git. Retain backend browser OAuth/cookie/CSRF compatibility during this batch: it is a separate security surface and is still useful regression coverage, not an embedded client runtime.

Alternative: combine native completion with recording. Rejected because capture topology needs hardware proof and capture/spool/upload has a separate high-risk dependency chain.

Alternative: delete React immediately after an evidence screenshot. Rejected because contract, workflow, accessibility and backend-state evidence would remain incomplete.

## 4. Evidence interface and data flow

Add an Evidence sidebar destination and `ShellRoute.evidence(activityID: Int?)`. Restore only the static `evidence` destination, never a private activity ID. Today `review_feedback` routes to the supplied activity's evidence. A clear “All evidence” action returns to the full ledger; activity detail provides a route back to that activity. A missing activity ID must not silently open another activity's history.

Use a scrollable native list with titled sections and native disclosure controls:

1. Intro: measured performance; self scores remain separate; missing evidence is not zero.
2. Skill summaries: name, baseline/targets, assessed level `/ 4` or “Not assessed”, target gaps, confidence, trend, recency and last strong evidence date.
3. Selected skill inspection: formula version, effective weight, qualifying/event-type counts, all three gaps, confidence/trend basis and manifest entries. Show inclusion/exclusion reason and the **manifest's used weight**, not just the event's original weight.
4. Activity inspection: scoped immutable events, evaluator, assistance/practice mode, raw dimension scores, dates and formula/rubric/mapping lineage. Reachable directly from Today and from portfolio rows.
5. Portfolio history: independent `/ 20` metric, seven server-provided components, versions, date and trend basis. Related skill evidence is fetched lazily; use readable slugs if the skill-name request failed. Do not hide valid portfolio data behind a skills failure.

No charts, locally recomputed estimates, additional API framework or local database. Structured basis dictionaries get readable labels for known fields and an inspectable deterministic text fallback for unknown fields. Unknown values are not interpreted as favorable or unfavorable results. Raw dimensions may contain nested objects/arrays, not only scalar numbers; never render them as an opaque object placeholder.

### API mapping

| Intent | Existing endpoint | Generated response |
|---|---|---|
| List skill estimates | `GET /api/v1/skills` | `SkillListResponse` |
| Read one skill if needed on refresh | `GET /api/v1/skills/{slug}` | `SkillSummaryResponse` |
| Inspect skill history | `GET /api/v1/skills/{slug}/evidence?limit=20&cursor=…` | `EvidenceEventPage` |
| Inspect activity history | `GET /api/v1/activities/{id}/evidence?limit=20&cursor=…` | `EvidenceEventPage` |
| Browse portfolio | `GET /api/v1/portfolio-judgment?limit=20&cursor=…` | `PortfolioHistoryResponse` |

Use `Components.Schemas` at HTTP boundaries and explicit immutable UI projections. No parallel handwritten wire schema. Preserve Decimal strings exactly for calculation evidence; display formatting must not introduce binary floating-point artifacts, coerce null to zero, or change scoring. Use the existing timestamp codec; date-only snapshot fields remain calendar dates, not timezone-shifted instants.

### Bounded loading algorithm

```text
open destination:
  invalidate prior destination generation
  independently load skills and one portfolio page
  if activity context exists, load its first event page

inspect skill/activity:
  cancel prior inspector request and clear its page
  capture (session generation, destination, scope, request generation)
  fetch one page; validate scope, unique IDs and cursor progress
  publish only if all captured identities still match

Older:
  fetch next_cursor once; replace the current page, never append forever
  on failure keep the visible page and retry the same cursor explicitly
Newest:
  reset cursor and replace the page after a successful response

refresh / relevant status invalidation:
  refresh visible evidence; mark hidden evidence stale for its next appearance
  coalesce bursts using the existing workspace refresh mechanism

sign-out / expiry:
  cancel work, invalidate generations, discard all private feature state
```

The client retains a skills snapshot, one portfolio page, and at most one active skill inspector and one activity inspector. Requests use the existing 2 MiB standard response ceiling; no automatic all-history scan, prefetch or audio download. “Older” and “Newest” provide full forward traversal without retaining every visited page. Pages contain 20 items, never more than the server's maximum 100. A malformed/non-advancing cursor is a retryable contract error, not an infinite loop.

The snapshot manifest remains authoritative even when its event is absent from the currently loaded page. Show event ID, inclusion and used weight, with “Outside this page; browse older evidence” rather than inventing raw scores. Excluded/self events stay inspectable and distinct. Empty scoped history is not a fabricated zero score.

## 5. Edge and error matrix

| Condition | Required result |
|---|---|
| No snapshots / empty history | Honest unassessed/empty state; no zero or success claim |
| Skills fail, portfolio succeeds (or converse) | Independent data stays usable; section-specific Retry |
| Page request fails | Keep old page with an error; do not advance cursor |
| Refresh changes snapshot | Replace manifest and inspector context together; discard stale completion |
| Missing manifest event | Explicit outside-page explanation; no guessed values |
| Unknown basis/dimension shape | Deterministic readable fallback; no client scoring |
| Wrong scope / malformed decimals / duplicate IDs | Reject the affected payload; clear explanation and Retry |
| 401 or sign-out during request | Existing session policy; no anonymous retry or later private-state resurrection |
| 403/404/409/422, offline, oversize | Safe allowlisted error; never raw problem detail or credential logging |
| Rapid route/selection/status changes | Cancellation plus identity checks; latest relevant result wins |

## 6. Parity and cutover invariants

1. Backend scoring, qualification, assistance rules, immutability and owner boundaries remain unchanged.
2. Every current browser learning-journey assertion maps to native UI behavior and/or durable backend integration evidence before deletion. Static JSON alone does not prove persistence, auth, idempotency or object upload.
3. Shared synthetic fixtures must be checked against real FastAPI/Pydantic responses. Native generated adapters and UI consume those same fixture contracts; expected results are not independently hand-maintained on each side.
4. Native behavioral tests cover sign-in/out shell, Today/Continue, notification read state, roadmap import/validation/diff/approval/activation, activity timers/artifact upload/commit/self-review, evidence drill-down, error recovery and keyboard navigation.
5. Release-build checks prove fixture authentication/transport seams are absent and no product Node/React/Vite/Python/database runtime is embedded. Python on a developer/CI host for backend tests is allowed. GitHub's JavaScript-based official actions are not a Node dependency of the product and need not be replaced.
6. Retire web CI only after its replacement checks pass. Never rename required checks into permanent pending state, insert success placeholders, weaken protection, or call skipped UI tests a pass.
7. Keep no production test-login endpoint, seeded production sessions, credential-bearing artifacts or real study/audio fixture data.
8. Keep local builds serial (`-jobs 2`), reuse one task-specific DerivedData directory, and do not start Docker locally. Native parity does not require recording or transcription jobs.
9. Keyboard/VoiceOver reading order, labels, focus, long text, light/dark contrast, reduced motion, empty/loading/error/retry states and narrow-window layout must be checked. Automated labels alone are not a complete VoiceOver audit.
10. Record launch and settled idle measurements on the M2/8 GB Mac with the signed synthetic-fixture app; require the existing idle p95 RSS gate of 180 MiB. Mark production-network measurements unavailable, not passed, while hosts remain `.invalid`.

## 7. Recovery and boundaries

Evidence is read-only: failed requests never mutate or invalidate server history. Retiring tracked web code is a reviewable Git change recoverable from the previous commit; do not delete unrelated files, installed tools, branches, working copies or secrets. If parity fails, keep web code and its checks until repaired. After merge, an in-scope regression can be corrected normally; a broader rollback or changed architecture returns to the coordinator rather than bypassing evidence gates.

Standing merge authorization applies to all three PRs once exact-head independent review and required CI pass. It does not authorize deployment, release, production changes, Docker, destructive cleanup, paid tools or branch-protection changes.

## 8. Decisions for the end-of-planning packet

Both recommendations below were approved by the user on 2026-08-31. Their alternatives remain historical decision context, not pending questions.

**D1 — Parity proof. Recommended:** layered verification: strict native UI/request-contract tests plus the matching real FastAPI/PostgreSQL/object-storage journey in Linux CI, tied by shared synthetic fixtures. This replaces the current browser test without adding a cross-runner tunnel or local database. It proves client behavior and persistent backend behavior separately; it is not a live native-to-server end-to-end run. Alternative: retain React until an additional real native/backend CI journey is designed and proved. That increases test infrastructure and execution work. Applies to #126; reversible before deletion, recoverable via Git afterward.

**D2 — Merge enforcement. Recommended:** preserve the private repository and have the coordinator explicitly enforce the named CI checks plus independent exact-head review before each merge, using the user's existing standing merge authorization. Read-only protection/ruleset queries returned 403 with GitHub's private-plan entitlement message; server-side enforcement is not verified. Do not claim branch protection exists. Alternative: user arranges an eligible GitHub plan and configures required checks before cutover; no purchase is authorized here. Applies to #126's check transition and all three merges. This is not permission to bypass any enforced restriction: a blocked merge remains blocked. User confirmation is required before locking this fallback; do not make the repository public.

D1/D2 are resolved. The reviewed design is locked; the user-selected Sol xhigh coordinator may execute the batch.

## 9. Source pointers

Current implementation: `apps/web/src/features/evidence/`, `apps/backend/src/tamforge_backend/evidence/{routes,schemas,repository}.py`, `apps/macos/TAMForge/App/{TAMForgeApp,ShellSessionModel,NativeUIFixtures}.swift`, `apps/macos/TAMForge/Core/{AppDependencies.swift,API/}`, `.github/workflows/ci.yml`, `docs/testing/native-feature-parity.md`.

External technical checks: [Apple XCUIApplication](https://developer.apple.com/documentation/xcuiautomation/xcuiapplication) describes app launch/monitoring and launch environment; [GitHub workflow syntax](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax) requires Linux for service containers. Therefore PostgreSQL/object-storage integration stays on isolated Linux CI; do not assume macOS service containers are available.
