# Native feature parity

Scope: E10-I06–E10-I09 (#122–#125). The reference client remains
`apps/web/src/features/{today,notifications,roadmaps,activities,evidence}` until
the separately gated E10-I10 cutover. Server read models and commands remain authoritative.

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

## Evidence boundaries

- Native UI journeys use a DEBUG-only `URLProtocol` fixture, the real SwiftUI views,
  adapters and macOS file picker. They prove client behavior, not deployed backend
  or OAuth connectivity.
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
  their descendants in the macOS accessibility tree. A retained dark-appearance,
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
