# Native feature parity

Scope: E10-I06–E10-I10 (#122–#126). The reference web client remains present through
the parity PR and is removed only by the separately reviewed cutover PR. Server read
models and commands remain authoritative.

| Surface | Native behavior | Verification |
| --- | --- | --- |
| Today | Device-local requested date, server timezone/day policy, ordered tasks, Continue routing, carryovers, interviews, self-review links, daily close | `TodayFeatureTests`; Today/navigation and daily-close UI journeys |
| Protected study time | Sunday off, Saturday cap, hard-stop and resumability cues; no client-generated extra work | Backend Today tests; native read-model fixtures |
| Notifications | Allowlisted messages, bounded list, mark-read reconciliation, live-stream/retry presentation | `NotificationFeatureTests`, `StatusStreamClientTests`, shell tests |
| Roadmap package | Explicit ZIP/folder selection; normalized relative paths; bounded file-backed multipart; no implicit vault access | `RoadmapPackageTests`, `RoadmapMultipartTests` |
| Roadmap governance | Validation, inspectable semantic changes, explicit approval, mirror retry, history and activation | `RoadmapViewModelTests`; fake-transport select/validate/approve/activate UI journey |
| Activity contract | Objective, source visibility, required output, pass criteria, constraints and assigned procedure | Activity model and workspace tests |
| Independent output | Reading, SQL/results/assistance, case, writing and pipeline editors; immutable commit; mandatory self-review | `ActivityWorkspaceTests`; self-review UI journey; backend learning tests |
| Draft lifecycle | Text and confirmed artifact references retained in memory through navigation and recoverable reload; remote finalization retains a separate read-only recovery copy; cleared after own commit/sign-out | Activity regression tests; navigation/sign-out UI journey |
| Focused timer | Server snapshot plus monotonic interpolation; serialized start/pause/resume/heartbeat; explicit uncertain-command recovery | `ActivityTimerTests`; timer navigation UI journey |
| Artifact lifecycle | Bounded temporary staging, file-backed upload, presign/PUT/confirm, cancel and indeterminate reconciliation | `ActivityArtifactUploadTests` |
| Session boundaries | One workspace window; bearer acquisition failures never send anonymous requests; stale 401 callbacks cannot expire a later sign-in; fresh private state after sign-in | Transport/shell tests, single-window and sign-out UI journeys |
| API schema | Generated `Components.Schemas` at HTTP boundaries with explicit UI-domain projections; local Codable fixture/draft models are not an alternate wire contract | Generated adapter tests; OpenAPI drift check |
| Skill evidence | Server-provided baseline, targets, nullable `/4` estimate, gaps, confidence, trend, recency and exact Decimal strings; missing evidence is never zero | `NativeEvidenceAdapterTests`, `EvidenceLedgerTests`; native Evidence UI journey |
| Calculation ledger | Manifest inclusion/exclusion and used weight remain distinct from raw event weight; basis and nested raw dimensions stay inspectable; absent page events are identified without guessed values | Evidence adapter/model tests; skill disclosure and pagination UI journey |
| Activity evidence | Today preserves the exact activity scope; one bounded page, retry-safe Older/Newest replacement, lineage and evaluator/assistance details; All evidence clears private scope | Evidence route/model tests; scoped Evidence/sign-out UI journey |
| Portfolio history | Independent server-provided `/20` total, all seven components, trend basis and versions remain usable even when skill loading fails | Independent-state model test; section-specific retry UI journey |

## Browser-cutover replacement map

One synthetic scenario is checked at
`tests/fixtures/native-parity/foundation-journey-v1.json`. Its source ZIP digest and
byte count are bound to the real Month 1 package; FastAPI/Pydantic validates every
shared response, and Swift decodes the same copied bytes through generated OpenAPI
types. The copy is drift-checked and exists only in test bundles.

| Former browser journey assertion | Native client evidence | Durable server evidence |
| --- | --- | --- |
| Authenticated owner workspace | Strict DEBUG launch uses bearer-only requests and rejects an unexpected origin, method, header, query or body | Native OAuth start/callback/PKCE exchange creates the ephemeral bearer; only GitHub provider responses are mocked; no owner dependency override |
| Select, validate and idempotently stage Month 1 | Real macOS picker and multipart adapter send the exact shared ZIP, package kind, idempotency key, digest and bytes | Real route stores one import through PostgreSQL and MinIO; replay returns the original import; a fresh S3 adapter reopens the exact bytes |
| Explicit roadmap approval and activation | SwiftUI review/confirmation/activate controls and state transitions | Real service persists `not_required` mirror state with egress disabled, then activates the server-authoritative version |
| Today contains 240 planned minutes and a 45-minute technical reading | Generated Today decoding, visible UI and Continue routing preserve the shared activity relationship | Real Today route rebuilds the complete seven-task day from the activated PostgreSQL roadmap, preserves the 45-minute technical-work assertion, and returns an activity contract consistent with that Today row |
| Timer and closed-source work survive navigation/reload | Start, pause, navigate, resume and hide-source execute through strict request contracts | A fresh bearer client resumes the persisted optimistic version and source-visibility state |
| Attempt A is exact, immutable and idempotent | Every shared output field is entered in the native editors; commit removes mutation controls | Real commit route stores one Attempt and one receipt; replay is byte-for-byte the same response |
| Mandatory self-review uses all six reflections and `/4` score | Native score menu and six editors submit the shared score `3`; completion summary is visible | Real self-review route persists one complete review and final activity state in a fresh database session |
| Missing evidence is not zero; no vanity proxies | Native Evidence UI shows `Not assessed`, exact Decimal/lineage fixtures, independent `/20` portfolio scale, and no forbidden proxy labels | Real skill routes use seeded server configuration and persisted evaluation data; an unassessed skill remains null, and this non-portfolio exercise leaves the independent portfolio history honestly empty |
| Feedback notification is keyboard-readable and idempotent | Enter activates the native default Mark read action and clears unread state | Real outbox delivery creates one notification; two bearer mark-read calls preserve one read timestamp |

This is deliberately layered proof, not a claim that a hosted Swift binary contacted a
deployed server during CI. The native lane proves macOS behavior and exact HTTP
contracts; the Linux lane proves native bearer authentication and durable
PostgreSQL/MinIO behavior through the same FastAPI routes and shared scenario.

## Local 8 GB resource receipt

The opt-in receipt passed on `da4b5463e80a2e10596c343f0f1b3730dadb8c9a`
using a Mac14,7 with 8 GiB RAM and macOS 26.3 (25D125). The ad-hoc signed DEBUG
shared-parity fixture completed five usable cold launches, a 60-second settle, 300
RSS samples on an absolute one-second schedule, 20 Today/Evidence/refresh cycles and
a final 60-second settle. The JSON is retained as
`tamforge-native-resource-receipt` in
`/tmp/tamforge-native-resource-da4b546.xcresult`.

| Measurement | Result |
| --- | ---: |
| Cold launch p50 / p95 | 4.486 s / 7.116 s |
| Idle RSS min / p50 / p95 / max | 8.516 / 17.891 / 31.781 / 48.813 MiB |
| Navigation-cycle peak RSS | 58.172 MiB |
| Post-cycle RSS after 60 s | 21.750 MiB |

The locked idle p95 gate is 180 MiB; the observed 31.781 MiB passed. The post-cycle
gate is idle p95 + 20 MiB (51.781 MiB); the observed 21.750 MiB passed. The test ran
for 578.804 seconds with one pass and zero failures or skips. This receipt measures
the native UI under the shared fixture, not local ASR, recording or live-server work.
Its RSS probe exists only under `DEBUG`; the separate Release gate proves the probe
and all other fixture hooks are absent from the distributable app.

## Evidence boundaries

- Native UI journeys use a DEBUG-only `URLProtocol` fixture, the real SwiftUI views,
  adapters and macOS file picker. They prove client behavior, not deployed backend
  or OAuth connectivity.
- `native-ui` requires the explicit 19-test inventory to pass with zero failures,
  skips or expected failures. Its xcresult is retained on failure. The long local
  resource receipt is opt-in and explicitly excluded from that normal CI inventory.
- `macos-native` separately builds an optimized ad-hoc signed Release app. A fail-closed
  bundle check verifies its identity/executable, signature, single product executable,
  linked libraries and complete file tree. It rejects DEBUG fixture credentials and
  launch hooks plus embedded browser, Node, Python, PostgreSQL or database tooling.
- Unit tests exercise malformed responses, errors, retries and cancellation in
  addition to happy paths. PostgreSQL integration remains a required GitHub CI gate;
  local verification does not start Docker.
- Generated timestamps use the shared RFC3339 codec. The pinned generator omits nil
  optionals even for required-nullable fields; the codec explicitly inserts only
  declared missing JSON nulls (for example daily-close `unfinished_requirement`),
  never overwriting a present value. Tests bind this workaround to the real generated
  command and unchanged FastAPI contract.
- Native accessibility evidence covers labeled editors, keyboard-usable native
  controls, navigable forms, disabled-action gates and reduced-motion shell behavior.
  Evidence uses header traits and stable identifiers on the actual retry, paging,
  activity, manifest and event controls rather than on ancestor containers that hide
  their descendants in the macOS accessibility tree. Its header, skill, portfolio and
  scoped-activity regions are explicit containment groups; UI automation verifies the
  Command-R refresh shortcut, group membership and top-to-bottom landmark placement.
  A retained dark-appearance,
  accessibility-extra-extra-extra-large screenshot at the minimum window size was
  manually inspected: the title hierarchy, score-scale explanation, assessed and
  unassessed cards, all three target gaps, focusable actions, wrapping and contrast
  remained legible without clipped controls. Automated accessibility queries and this
  visual inspection are not a claim of a complete human VoiceOver audit.
- Activity output reads have a 96 MiB collection ceiling to accommodate the server's
  largest text contract and JSON escaping. Ordinary responses retain a 2 MiB ceiling;
  problems retain 64 KiB. These are limits, not reserved memory. Artifact bytes remain
  file-backed rather than being placed in a `Data` payload.
- React removal/distribution cutover (E10-I10), recording, local ASR, and live server
  configuration remain outside the Evidence PR. Evidence is a read-only server ledger;
  it does not claim the recording or English-analysis pipeline is implemented.
- The checked-in API hosts remain `.invalid` pending an approved deployment/configuration
  step. A passing build or merged PR is not a usable production deployment.

## Local verification

Use Xcode 26.6 and the local development signing identity. Keep builds serial and use
two jobs on the 8 GB Mac. Reuse one DerivedData directory. Run `make check` for the
repository checks and a separately signed `TAMForgeUITests` run for native UI journeys.
Do not enable Docker or run production mutations for this verification.

Final test counts, exact reviewed head and CI receipts belong in the PR rather than
this durable behavior matrix.
