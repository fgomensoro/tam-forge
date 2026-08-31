# Native feature parity — Batch 01

Scope: E10-I06 (#122), E10-I07 (#123), and E10-I08 (#124). The reference client
remains `apps/web/src/features/{today,notifications,roadmaps,activities}` until
the separately planned cutover. Server read models and commands remain authoritative.

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
  Automated accessibility queries are not a claim of a complete human VoiceOver audit.
- Activity output reads have a 96 MiB collection ceiling to accommodate the server's
  largest text contract and JSON escaping. Ordinary responses retain a 2 MiB ceiling;
  problems retain 64 KiB. These are limits, not reserved memory. Artifact bytes remain
  file-backed rather than being placed in a `Data` payload.
- Evidence browsing (E10-I09), React removal/distribution cutover (E10-I10), recording,
  local ASR, and live server configuration are outside this PR. The shell gives an
  explicit notice for the not-yet-migrated evidence destination. It does not claim the
  recording or English-analysis pipeline is implemented.
- The checked-in API hosts remain `.invalid` pending an approved deployment/configuration
  step. A passing build or merged PR is not a usable production deployment.

## Local verification

Use Xcode 26.6 and the local development signing identity. Keep builds serial and use
two jobs on the 8 GB Mac. Reuse one DerivedData directory. Run `make check` for the
repository checks and a separately signed `TAMForgeUITests` run for native UI journeys.
Do not enable Docker or run production mutations for this verification.

Final test counts, exact reviewed head and CI receipts belong in the PR rather than
this durable behavior matrix.
