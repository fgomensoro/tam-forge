# TAM Forge Native macOS Batch 02 Implementation Plan

> For agentic workers: use `subagent-driven-development` for bounded delegated slices, or `executing-plans` for coordinator-owned work. Follow the batch gates below; do not begin implementation during the Ultra planning turn.

**Status:** Locked on 2026-08-31 after independent Sol Ultra review and user approval of D1/D2. Sol xhigh execution handoff confirmed.

**Goal:** Finish native evidence browsing and replace web runtime/tooling only after equivalent verification is established.

**Architecture:** Existing SwiftUI shell, generated `Components.Schemas`, URLSession transport and server-authoritative FastAPI/PostgreSQL. No new client framework, local database, scoring algorithm or production service.

**Tech stack:** Swift 6, SwiftUI/macOS 15+, Xcode 26.6 locally, XCTest/XCUITest; Python 3.12/FastAPI/Pydantic/pytest for backend and development checks; existing isolated Linux CI PostgreSQL/object store.

**Spec:** `docs/superpowers/specs/2026-08-31-tam-forge-native-parity-cutover.md` and the locked 2026-08-28 native redesign.

**Scope:** #125 / E10-I09 and #126 / E10-I10. Two large tickets, three PRs; recording remains the next separate planning batch. This is client migration, not release or live deployment.

## 1. Execution gates and routing

Planning model verified: `gpt-5.6-sol / ultra`. Execution coordinator: `gpt-5.6-sol / xhigh`. Start only after this plan is locked, material questions resolved, and the user changes model/effort and replies `continue`.

| Ticket / cluster | Owner | Model / effort | Reason |
|---|---|---|---|
| #125 evidence models, adapter, views and focused tests | Bounded worker | Terra xhigh | Production feature with fixed read-only contracts and strong tests |
| #125 shared shell, session lifecycle and refresh integration | Coordinator | Sol xhigh | Shared routing/concurrency/privacy boundaries |
| #126 parity, fixture provenance, durable journey, native UI/release CI, cutover | Coordinator | Sol xhigh | Coupled verification, authentication seams and CI safety |
| #126 isolated bootstrap-check port / reference cleanup | Optional bounded worker | Terra high | Mechanical only after Sol locks exact behavior/files; no CI/security decisions |
| Independent implementation review of each final PR head | Separate reviewer | Sol xhigh | Review must not be authored by the implementer |

Every dispatch includes the relevant spec/plan slice, exact base, file ownership, tests, completed dependencies and escalation triggers. Do not launch one worker per tiny subtask. Maximum one coding worker beside the coordinator; only one native build/test process at a time.

### Required preflight

- [ ] Revalidate clean execution worktree and current `origin/main`; planning base is `52c0858221524fa6c35fb18c2804c0d5874ce62a` (main CI run `33428685373`, success). Preserve the dirty six-week-roadmap worktree and `codex/recording-speech`.
- [ ] Confirm #122, #123 and #124 remain closed with merged evidence; #125 starts first. #126 removal waits for #125 and its own parity PR.
- [ ] Read repo startup files, this locked spec/plan, native parity matrix, security threat model, Makefile and workflow.
- [ ] Verify selected full Xcode/local signing identity, available disk and current CI budget. Use a single task-specific DerivedData directory and `-jobs 2` locally. Do not install tools or change signing policy silently.
- [ ] Read current branch/ruleset requirements and record their check contexts. Missing/inaccessible policy is not permission to bypass it.
- [ ] No Docker/Testcontainers/Compose locally without explicit approval in that execution turn. No production credentials, deployments, service changes, release, paid tools, branch deletion, force-push or unrelated cleanup.

Escalate a worker to Sol xhigh for shared API/auth/session behavior, unclear data semantics, privacy/race failures or verification beyond its scope. Return to Ultra and re-lock for new architecture, changed scoring, new production/test infrastructure or material decisions. Fix ordinary in-scope failures without stopping the batch.

## 2. PR sequence and ownership

1. **PR A — native evidence:** closes #125 only after merge. Keep all web source, TypeScript generation and existing CI intact.
2. **PR B — native parity checks:** contributes to #126, does not close it. Add replacement verification while retaining browser checks. Complete and independently review the parity matrix.
3. **PR C — native cutover:** remove only the approved tracked web/tooling surface after A/B are merged and gates pass. Closes #126 after final-head CI and merge; close parent #116 only after verifying all ten children are closed.

Do not stop between these PRs for merge permission: standing authorization covers every batch, subject to exact-head independent review, required CI, correct base/dependencies and mergeability. It does not authorize changing repository protection.

Coordinator owns `TAMForgeApp.swift`, `ShellSessionModel.swift`, `Core/AppDependencies.swift`, shared transport/generation, the Xcode project, shared fixture resources, workflow and integration. The #125 worker owns only its new `Features/Evidence/` and named evidence test files until coordinator integration. No overlapping live edits.

## 3. Ticket #125 — evidence ledger

**Dependencies:** #122 Today and #124 activity workspace, both merged in PR #129. Dispatch after preflight and locked plan. Route: Terra xhigh worker plus Sol xhigh shell integration.

### File map

Create:

- `apps/macos/TAMForge/Features/Evidence/EvidenceModels.swift`
- `apps/macos/TAMForge/Features/Evidence/LiveEvidenceAPI.swift`
- `apps/macos/TAMForge/Features/Evidence/EvidenceLedgerModel.swift`
- `apps/macos/TAMForge/Features/Evidence/EvidenceLedgerView.swift`
- `apps/macos/TAMForgeTests/NativeEvidenceAdapterTests.swift`
- `apps/macos/TAMForgeTests/EvidenceLedgerTests.swift`

Modify:

- `apps/macos/TAMForge/App/{TAMForgeApp,ShellSessionModel,NativeUIFixtures}.swift`
- `apps/macos/TAMForge/Core/AppDependencies.swift`
- `apps/macos/TAMForge/Core/API/GeneratedOpenAPIContract.swift`
- `apps/macos/TAMForgeTests/{ShellSessionModelTests,AppDependenciesTests}.swift`
- `apps/macos/TAMForgeUITests/TAMForgeUITests.swift`
- Xcode target/resource membership if not automatically synchronized; `docs/testing/native-feature-parity.md`.

Reference, not rewrite: backend `evidence/{routes,schemas,repository}.py`; web `features/evidence/`; native `LiveActivityAPI.swift`, `NativeAPITransport.swift`, `TodayFeature.swift`.

### A1. Contract and projections — tests first

- [x] Add failing generated-adapter tests for all five existing GET shapes, required-nullable snapshots/cursors, Decimal strings, date-only values, nested raw dimensions, unknown basis fields and error mapping.
- [x] Assert GET-only bounded requests, encoded/validated slug and positive activity ID, cursor/limit construction, bearer use, standard response ceiling and no secret/body logging.
- [x] Implement `EvidenceServicing` plus live adapter and immutable projections. Match existing generated-type/transport patterns; do not introduce another wire schema or recompute levels.
- [x] Verify null snapshot != zero, manifest used weight != raw event weight, portfolio `/20` != skill `/4`, evaluator/assistance/qualification lineage preserved.
- [x] Run focused adapter tests, then add regression fixtures for malformed decimals, wrong scope and duplicate IDs. Commit coherent tests and implementation together after proving red-to-green.

### A2. Feature state — tests first

- [x] Add failing tests for independent skill/portfolio success/failure, empty/not-assessed state, single active inspector per kind, Older/Newest page replacement, failed-page retry without cursor advance, and non-progressing cursor rejection.
- [x] Test rapid selection/destination changes, stale refresh completions, sign-out/expiry cancellation, and no private response publishing after session generation changes.
- [x] Implement feature-local main-actor state consistent with the existing app. Capture request identities, cancel obsolete tasks, and release replaced pages. Retain no unbounded history or disk cache.
- [x] Test manifest events outside the page, unknown nested bases, excluded self evidence, separate portfolio success when skills fail, and scoped empty activity evidence.
- [x] Add explicit visible refresh and stale-data/error messaging. Coalesce status refresh using existing workspace machinery; inactive evidence is invalidated rather than continually fetched.

### A3. View and shell integration — tests first

- [x] Worker builds native list/disclosure views using existing semantic fonts/colors/spacing. No custom chart, font download, invented estimate, or new design system.
- [x] Coordinator adds Evidence feature/service/state/sidebar and `ShellRoute.evidence(activityID:)`. Store only static restoration ID. Replace migration alert; preserve Today target activity ID and support All evidence/back-to-activity.
- [x] Extend shell tests for route restoration and fresh evidence state after sign-in. Extend UI fixture with assessed/unassessed skills, inclusion/exclusion, multipage evidence, portfolio components, scoped activity history and failure/retry states.
- [x] Add UI journeys proving sidebar access, disclosure/cursor controls, exact activity routing, not-assessed copy, separate score scales, section-specific Retry and sign-out clearing. Stable accessibility identifiers and condition waits, never sleep-to-pass assertions.
- [x] Verify keyboard use, focus visibility/order, VoiceOver reading order, long text, light/dark, increased text size, reduced motion and minimum supported window. Record what was automated versus manually observed.
- [ ] Run focused tests, complete native regression suite, required CI and independent final-head review; merge PR A. Update parity documentation honestly; do not claim backend deployment or AI report generation.

**Acceptance:** all spec sections 4–5 pass, generated contracts used, full lineage inspectable, histories bounded, scoped routing correct, no stale private state, accessible retryable UI. **Completion evidence:** exact commit/test counts, UI result bundle, updated matrix, independent review and CI URLs in PR A. Closing #125 requires its merge.

## 4. Ticket #126 — parity before removal

**Dependencies:** #122–#125, with A merged; PR B verification precedes PR C removal. Owner Sol xhigh. Optional Terra high only for the frozen mechanical port below.

### File map and CI contract

Create `apps/backend/tests/integration/test_native_foundation_journey.py`, `scripts/ci/check_native_parity_fixtures.py`, `scripts/ci/tests/test_native_parity_fixtures.py`, `scripts/ci/check_native_bundle.py`, `scripts/ci/tests/test_native_bundle.py`, and synthetic scenario/response records under `tests/fixtures/native-parity/`. Port bootstrap/Compose guards to `scripts/verify_bootstrap.py`, `scripts/verify_compose.py`, with tests under `scripts/ci/tests/`. These are proposed paths, not existing passing checks.

Modify the existing Makefile, CI workflow, native project/scheme/test fixtures and UI tests, `scripts/ci/check_openapi.py` and tests, repository policy/tests, `scripts/dev/seed_foundation_demo.py` and `scripts/dev/tests/test_seed_foundation_demo.py`, README, `.gitignore` and parity matrix. Delete web-only sources/manifests/scripts only in C1. Preserve `compose.dev.yml`, `uv.lock`, Python manifests, database helpers and isolation/selection tests.

Initial observed check contexts (publisher GitHub Actions, app ID 15368): `macos-native`, `backend-unit`, `web`, `backend-integration`, `e2e`, `openapi`, `secret-scan`. PR B adds `native-ui` and keeps all seven existing contexts. PR C retains `e2e` as the durable backend journey, removes `web` only after replacement evidence, and retains the other contexts plus `native-ui`. Release bundle verification is a real step in `macos-native`, not a synthetic success context. No mandatory path filtering or skip-to-green. A required context unexpectedly remaining pending blocks merge; never use `--admin` or modify protection to get around it.

Under D2, these named checks and exact-head review form the explicit coordinator gate even when GitHub protection cannot be inspected. Recheck policy at execution; if enforced settings become visible, respect them. Protection changes or paid upgrades need separate user direction.

### B1. Freeze the behavioral inventory

- [ ] Enumerate assertions in `apps/web/e2e/foundation-learning.spec.ts`, evidence component tests, and the current native parity matrix. Map each to a retained/new native UI assertion and/or real database/object-store integration test. Do not mark a missing assertion covered by a screenshot.
- [ ] Minimum journey: real Month-1 ZIP upload, validate/diff/approve/mirror-not-required/activate; fixed 2026-08-24 Today with 240 planned minutes and 45-minute reading activity; start/pause/reload/resume; source hide; independent reading output and immutable Attempt A; six mandatory reflections/self-score 3/read-only result/no Attempt C; Evidence unassessed/nonzero-missing distinction/no vanity proxies; keyboard notification mark-read. Retain actual backend Sunday-policy tests rather than treating absence of UI reminder text as proof.
- [ ] Extend `docs/testing/native-feature-parity.md` with stable scenario IDs, exact fixture provenance, backend/client tests, error/empty/accessibility cases and release/nondeployment boundaries.
- [ ] Use synthetic shared response fixtures under `tests/fixtures/native-parity/`; test schema/semantic agreement against FastAPI/Pydantic. Test native generated decoding from those same fixtures. Keep build-resource copies generated/checked, not independently edited.
- [ ] The durable journey compares actual route responses with shared fixtures using an explicit allowlist for volatile IDs/timestamps, preserving cross-response ID relationships and every business field. Native UI fixtures enforce method/path, relevant headers, command bodies, multipart contents and valid state transitions; unexpected requests fail, not default to HTTP 200. Pass fixture files from the test bundle via DEBUG-only launch configuration; no Release resource copy or production environment override.
- [ ] Keep actual authentication/owner, PostgreSQL transaction, idempotency, artifact persistence and workflow sequencing checks in isolated integration CI. No production route accepting fixture credentials or bypassing owner dependencies.
- [ ] Reuse `integration/auth/test_native_auth_integration.py`: mock GitHub provider responses only, then call native start/callback/exchange for an ephemeral bearer. Never override authenticated-owner dependencies for the durable journey. Re-read persisted results in fresh DB sessions. Validate test environment/owner, exact loopback test DB/port/name with no URL query parameters and isolated MinIO endpoint/bucket/credentials before migrations or fixture mutation; disable mirror/provider egress and ambient `.env`. Never emit tokens or credential-bearing artifacts.

### B2. Replacement checks and cutover proof

- [ ] Add native UI verification to CI with executable assertions and explicit result-count/failure/skip checks. Keep the existing native unit job and browser e2e during the proving PR. A nonlaunching app or skipped UI suite blocks removal.
- [ ] Prove the `macos-26` runner UI path first using an ad-hoc signature only for synthetic CI UI tests (`CODE_SIGN_IDENTITY=- CODE_SIGNING_ALLOWED=YES`, explicit signing settings as needed). Local/distribution stable identity policy is unchanged. Keep PostgreSQL/MinIO on Linux: no macOS service-container assumption. If native UI execution cannot be proved on the existing runner, stop this lane before deletion and return the runner choice to the user; do not purchase or register a runner.
- [ ] Preserve the durable learning journey with a backend integration test before removing its browser driver. Preserve native UI journey coverage separately; record their combined coverage and limitations, not a fictitious live deployed end-to-end result.
- [ ] If the assertion inventory exposes a missing native migration behavior, repair that existing feature with a failing regression test before cutover. Sol owns classification/integration; a bounded production UI fix may use Terra xhigh with explicit nonoverlapping files. Do not treat the gap as waived or expand into unimplemented recording/AI products.
- [ ] Build Release separately and check bundle/runtime contents and fixture-seam exclusion. Tests must reject product embedded browser/Node/Python/database runtime and release test authentication hooks; do not forbid Python backend tooling or JavaScript official GitHub actions.
- [ ] Add an exact-head parity checklist covering behavioral, generated contract, integration, native UI, accessibility and measured idle/launch evidence. Inspect the signed app, not just source.
- [ ] Local resource receipt: serial signed build; five cold launches recording time to a usable fixture Today/Evidence view; after 60 seconds settling, collect RSS once/second for five minutes; report p50/p95, macOS/hardware/build/config and scenario. Existing idle p95 <=180 MiB is a gate. Repeated navigation/refresh across 20 cycles must release retired evidence models/pages; investigate sustained growth, do not weaken the bound or silently lower quality.
- [ ] Run required CI and independent final-head review; merge PR B only when replacement evidence passes. #126 remains open.

### C1. Remove only the tracked legacy client/tooling

- [ ] Revalidate A/B exact merged commits and all parity gates. Inventory tracked removal candidates with Git before deletion; use reviewable file edits, not recursive workspace cleanup.
- [ ] Remove `apps/web/`, web-only root pnpm/package manifests/lockfile, TypeScript OpenAPI generation and web-only build/deployment references. Preserve Python backend/protocol workspace and unrelated user files.
- [ ] Port needed bootstrap/compose assertions from `scripts/verify_bootstrap.mjs`, `scripts/verify_compose.mjs` and its tests to focused Python checks/tests before removing those Node scripts. Terra high may perform this port only against the coordinator's explicit assertion inventory and file set; no CI/auth ownership.
- [ ] Preserve Compose rejection tests for aliases/anchors/tags, duplicate keys, multiple YAML documents, unexpected services/volumes/ports and unapproved images. PyYAML is already available; `safe_load` alone does not preserve these guards. Drop only obsolete Node-version/build-script requirements.
- [ ] After replacing the browser driver, make `seed_foundation_demo.py` data-only: keep isolated learner/config/notification setup, remove cookie-session creation/output, and update its tests. Native test tokens belong to the integration journey's real auth flow, never to a new application endpoint.
- [ ] Make `scripts/ci/check_openapi.py` native-only while preserving schema normalization and drift failure tests. Update `scripts/ci/tests/test_check_openapi.py` with failing regression tests before the port.
- [ ] Update Makefile, README, workflow and maintained development/test docs to the native toolchain. Remove `setup-node`, pnpm/Vite/Playwright steps only after their replacements pass. Preserve legacy historical plan/closed-issue records, browser auth backend compatibility and isolated integration support.
- [ ] Add a repository-policy regression test for accidentally reintroduced product Node/web runtime/tooling, using a narrow active-surface allowlist rather than banning historical text or third-party action internals.
- [ ] Run checks without a project Node/pnpm install; Python backend and Xcode tooling remain available. Prove `make install`, `make check`, OpenAPI drift and policy commands have no Node invocation; missing Xcode cannot be represented as a successful required native check.
- [ ] Final full native unit/UI, backend unit/security/integration, OpenAPI, policy and release artifact evidence; independent review of exact final head; correct base and all required CI green; merge PR C and close #126. Then verify all E10 children before closing #116.

**Acceptance:** every retained behavior has mapped evidence; new native/UI and backend checks pass before browser deletion; no product Node/React/Vite runtime/tooling remains; no weakened CI/security; native app is inspectable and accessible with measured low idle memory. **Completion evidence:** final parity matrix, deletion inventory, exact-head review, CI and UI result counts, signed Release bundle checks and redacted M2 measurements. `.invalid` backend hosts stay explicit; DMG/recording release is E3-I12, not this ticket.

## 5. Verification commands

Commands below are execution steps, not claims that this planning turn ran app tests. New named tests/scripts are created in B/C. Inspect test markers before local invocation; integration runs in existing isolated CI unless the user explicitly approves local Docker.

```bash
# Native: single shared cache, no concurrent xcodebuild.
xcodebuild -jobs 2 -skipPackagePluginValidation \
  -derivedDataPath /tmp/tamforge-native-batch-02 \
  -project apps/macos/TAMForge.xcodeproj -scheme TAMForge \
  -destination 'platform=macOS' \
  -only-testing:TAMForgeTests/NativeEvidenceAdapterTests \
  -only-testing:TAMForgeTests/EvidenceLedgerTests test

make macos-check MACOS_BUILD_ARGUMENTS='-jobs 2 -derivedDataPath /tmp/tamforge-native-batch-02'

xcodebuild -jobs 2 -skipPackagePluginValidation \
  -derivedDataPath /tmp/tamforge-native-batch-02 \
  -project apps/macos/TAMForge.xcodeproj -scheme TAMForge \
  -destination 'platform=macOS' -only-testing:TAMForgeUITests test

# Focused non-Docker checks before complete repository verification.
uv run pytest apps/backend/tests/unit/evidence/test_evidence_routes.py \
  scripts/ci/tests/test_check_openapi.py -m 'not integration' -q
uv run python scripts/ci/check_openapi.py
uv run python scripts/ci/check_repository_policy.py
make check

# Isolated Linux CI only, or separately approved local integration environment.
uv run pytest apps/backend/tests/integration -m integration -q
```

Before each PR merge record the exact head, reviewer scope/verdict, required contexts and results. A changed head invalidates prior evidence unless an explicit reviewed/tested delta is recorded; missing CI is not green. Failures stay visible even if an unchanged rerun succeeds. Do not retry persistently failing UI tests until luck produces a pass.

## 6. Planning/catalog publication and handoff

Update only #125/#126's deferred entries in `docs/project/github-issues.yml`: concrete acceptance/verification, this plan path and section, explicit model/effort/reason/dispatch/escalation. Preserve all unrelated and historical issue records. Validate the manifest and inspect the live dry-run. Apply only after exact private-repository/owner preflight, then verify no unintended writes and zero drift.

Planning verification on 2026-08-31: issue-sync unit suite **109 passed**, focused Ruff and `git diff --check` passed; live catalog dry-run reported **create=0, update=2, stale=0, applied_writes=0**. Only E10-I09/E10-I10 changed. The catalog routing assertion was updated with those proposed routes and still requires a locked Ultra plan. No app code, builds, Docker, deployment or GitHub issue writes occurred. Publish/commit the reviewed planning changes and apply catalog updates after D1/D2 approval; do not claim this paragraph is execution evidence.

Independent Sol Ultra document reviewer `01a05950-9949-70b3-8022-c65d481a04a8` approved both spec and plan, conditional on D1/D2 approval. No blocking findings. Review covered contracts, bounded history/state, privacy/session races, CI replacement, fixture provenance, release exclusions, accessibility and resource evidence. This is document approval, not implementation approval or CI evidence.

Full SwiftUI replacement and both recommended verification decisions are approved. D1 uses layered native/backend parity; D2 uses explicit coordinator-enforced checks while private-repository protection remains unverified. No protection bypass, paid upgrade or production change is authorized. See spec section 8 for the retained decision context.

The user switched to **Sol xhigh**, asked whether anything else was needed, and approved the final two recommendations in response to the execution handoff. The model/effort was verified from the active turn before execution. Continue the entire three-PR batch without per-PR merge questions. Recording is not silently added mid-batch.

## 7. Execution checkpoint — 2026-08-31

Planning commit `3818bd2` is pushed on `codex/native-evidence-batch-02`. Live catalog apply updated only #125/#126; follow-up dry-run has zero drift. Base remains `52c0858221524fa6c35fb18c2804c0d5874ce62a`. No implementation PR or merge has occurred.

PR A implementation is committed in the existing `native-macos-batch-02-plan` worktree through feature checkpoint `89cdd04`, review/accessibility/receipt fixes through `e783cf8`, and the final fixture correction recorded below. The coordinator completed the Terra xhigh worker's bounded draft after that worker stopped responding. Native Evidence now has generated-contract projections, fail-closed score/cursor/scope validation, independent bounded skill/portfolio/activity state, cancellation and session-generation guards, semantic SwiftUI disclosure/paging/retry views, shell routing, DEBUG-only strict fixtures and nine Evidence UI journeys. React and all legacy checks remain intact.

Verified local receipts at this checkpoint:

- Evidence adapter/model RED was preserved, then the final focused coverage reached **34 passed, 0 failed** across seventeen adapter and seventeen model tests in `/tmp/tamforge-native-batch-02/Logs/Test/Test-TAMForge-review-fixtures-unit.xcresult`. Those suites also pass inside the final native unit result. Regressions bind authoritative component names/maxima without recalculating the portfolio total, exact origin and cursor validation, backend Decimal and qualification relationships, snapshot gaps/manifest totals, stale-manifest exclusion, cancellation-resistant route departure/refresh/caller cancellation, selected-inspector recovery, rapid request ordering, bounded waits and readable lineage fallback.
- Complete signed native build and unit regression: **196 passed, 0 failed, 0 skipped**, result `/tmp/tamforge-native-batch-02/Logs/Test/Test-TAMForge-review-contract-final-unit.xcresult`, using the shared two-job DerivedData cache.
- Backend evidence routes/service plus the seed-config fixture drift regression: **11 passed**; focused Ruff, OpenAPI drift, repository policy, project plist and whitespace checks passed. Existing web evidence/unit regression remained green while React is intentionally retained in PR A.
- All eight original Evidence UI journeys passed together in `Test-TAMForge-2026.08.31_16-33-25--0700.xcresult`. After the final fixture, contract and asynchronous-label corrections, the complete native UI target passed **18 tests, 0 failed, 0 skipped** in `/tmp/tamforge-native-batch-02/Logs/Test/Test-TAMForge-review-contract-final-ui.xcresult`.
- No Docker command/workload, deployment, production credential, recording or legacy-client removal occurred. A Docker Desktop error window started independently and invalidated one UI run; its user processes were terminated before the clean final run.

Two independent Sol xhigh reviews of `89cdd04` returned changes required. Their concrete findings are addressed in `98d4879`: route departure now invalidates noncooperative reads; skill retries have their own request identity; portfolio responses require exactly seven unique canonical components while retaining the server-authoritative total; basis fields are readable while unknown nested values remain escaped; all three gaps appear in the summary; strict fixture cursors and asynchronous test waits fail closed; ancestor accessibility identifiers no longer mask interactive descendants.

Two further independent Sol xhigh reviews of `b6a11c5` also returned changes required. `1af0392` prevents stale manifest/event combinations, enforces authoritative per-component maxima, retains server-provided skill names, rejects incoherent fixture/domain values, validates the selected fixture origin and makes all asynchronous UI sections wait independently. `c1cc385` then grouped the header, skill, portfolio and scoped-activity accessibility regions, gave skill headings stable identities and added Command-R plus containment/visual-order assertions.

Two independent Sol xhigh reviews of `7097234` returned changes required. The fixes through `e783cf8` make a successful skill-summary retry restore an inspector cleared by a failed refresh, prevent an older cancellation-resistant refresh from cancelling a newer skill selection, settle every cancelled request, and enforce backend gap, aggregate-weight, event-weight, skill-impact and qualification relationships. Reviews of `cf2815a` then found two backend-reproducibility defects: the DEBUG fixture had drifted from canonical seed targets/rubric manifests, and nonqualifying responses bypassed observable attempt/mode/assistance reason precedence. The final correction derives a CI drift contract from checked-in config, uses backend-shaped raw dimension manifests, enforces the complete observable precedence, and keeps paging assertions asynchronous. Deterministic unit, backend and UI regressions cover every finding.

Two independent Sol xhigh reviews of `d73ac19` returned changes required. The final review delta propagates caller cancellation into all Evidence reads and settles every section without publishing cancellation-resistant errors; enforces qualifying-attempt/mode/assistance and snapshot gap/manifest relationships; corrects the synthetic snapshot; gives every repeated Retry/Older/Newest control a section-specific spoken label; and removes the local portfolio-component sum so Swift never recalculates the server-authoritative total. Snapshot validation checks redundant response relationships only and does not derive an estimate from evidence events.

The local PR A gate is complete. Sidebar reachability, activity-scope/sign-out, independent skill retry, scale/missing-evidence, lineage disclosure, portfolio/activity paging, empty state, keyboard refresh, accessibility grouping/order and dark/large-text paths all pass. The retained dark/large-text attachment from `Test-TAMForge-2026.08.31_15-53-13--0700.xcresult` was manually inspected and recorded in the parity matrix. This evidence does not claim a complete human VoiceOver audit. Invalid UI runs caused by foreground apps, Notification Center banners or transient macOS automation setup are retained in logs but are not counted as passing product evidence. Next: commit these final review fixes and receipts, obtain fresh independent Sol xhigh spec and quality reviews of the exact head, push PR A, require all named CI contexts, and merge under standing authorization.
