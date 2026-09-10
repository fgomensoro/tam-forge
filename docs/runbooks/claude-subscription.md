# Claude subscription activation

Claude stays disabled until a human carries out this procedure and its outcome is
stored as a `PrivacyAttestation` row (`apps/backend/src/tamforge_backend/agents/models.py`).
`claude_status` (`apps/backend/src/tamforge_backend/agents/compatibility.py`) reads that
row through `AttestationRepository.current` and reports `disabled` for every
combination except `CLAUDE_ENABLED=true` plus a current attestation. This document is
that procedure: obtaining the credential, judging the policy it operates under, and
recording that judgment. The compatibility probe that checks the installed SDK, the
subscription login, the resolved model and the structured-response path now lives
beside it in the same module and is described under "Running the compatibility probe"
below. The API-credential rejection and no-paid-fallback policy lives beside both, under
"Refusing every other way in" below.

This is a manual, single-operator procedure, run once per Anthropic policy version,
not an onboarding flow a second user ever goes through. TAM Forge is, per its own
README, "a private, single-user learning workspace." Everything below assumes that
remains true.

## Getting the token

Run `claude setup-token` locally and complete Anthropic's browser-based OAuth flow.
This binds the Claude Agent SDK to the operator's own Claude subscription rather than
to metered API billing. Before running it, confirm at
`https://support.claude.com/en/articles/15036540-use-the-claude-agent-sdk-with-your-claude-plan`
and `https://code.claude.com/docs/en/authentication` that this is still the current,
supported way to authorize the SDK against a subscription plan; Anthropic controls
that flow and can change its mechanics without changing this document.

Never paste the resulting token into chat, into GitHub (an issue, a PR description, a
commit, a gist), or into the TAM Forge UI. No TAM Forge endpoint accepts a Claude
token; if a workflow ever seems to need one pasted somewhere, that workflow is wrong,
not this rule.

## Storing it safely

Install the token as a root-owned service credential: a file the backend's own
service account can read, that the interactive login the operator deploys with
cannot write to and that a stray `git add` cannot pick up. Restrict its permissions
to that one reader. TAM Forge's own repository and database store no token and no
copy of one; the attestation this procedure produces records that the operator
looked at the policy, never the secret that lets Claude run.

Record the rotation date, one year from issuance, somewhere durable outside this
repository. Rotating on schedule, not on failure, is what keeps an expired token from
turning into an unplanned outage of the one feature that depends on it.

## Confirming the policy

Before recording anything, re-read the current text at each of these locations. They
are pinned here because they are the specific pages this gate exists to track, not
because their content is frozen:

- `https://code.claude.com/docs/en/data-usage` — confirm data-model-improvement is
  off for the plan in use. This is the claim `AttestationRecord.model_improvement_disabled`
  asserts; it must be true before it is attested, not assumed.
- `https://support.claude.com/en/articles/15036540-use-the-claude-agent-sdk-with-your-claude-plan`
  — confirm the subscription-to-SDK arrangement this runbook relies on is still the
  current official policy. This is what `AttestationRecord.subscription_policy_acknowledged`
  asserts.
- `https://code.claude.com/docs/en/agent-sdk/overview` — confirm nothing about how the
  Agent SDK itself is meant to be run has changed in a way that affects this setup.

## Recording the attestation

`EXPECTED_POLICY_VERSION` in `apps/backend/src/tamforge_backend/agents/settings.py` is
the version string the code expects. If what the pages above currently say differs
from the policy that constant names, bump it first, as its own change, before
recording a new attestation. Bumping it is exactly what makes every previously stored
attestation `attestation_superseded` (`attestation_is_current`, same module): an
attestation recorded against the old value would be born stale if the constant moved
out from under it afterward.

Only once the constant names the policy just confirmed does recording the attestation
mean anything: a `PrivacyAttestation` row whose `policy_version` matches
`EXPECTED_POLICY_VERSION`, and whose `model_improvement_disabled` and
`subscription_policy_acknowledged` are both true, exactly as `AttestationRecord`
requires.

Record it through `AttestationRepository.record`
(`apps/backend/src/tamforge_backend/agents/compatibility.py`), never by hand. The table
checks that `canonical_json` is in exact canonical form and that `content_hash` is the
SHA-256 of those precise bytes, so a hand-written INSERT is not a procedure anyone can
follow correctly. Recording the same policy version twice is a no-op rather than a
duplicate, so re-running the procedure after re-reading the pages above is safe. `PrivacyAttestation` is append-only, like every other row on the `Record`
base: a fresh attestation is a new row, never an edit to an old one, so the history of
what was attested and when is never lost.

## If the product changes

This entire procedure rests on TAM Forge being personal and single-user: one
operator, one subscription, one attestation. If that stops being true, stop. Do not
keep routing other people's use through this operator's individual subscription
token; that is very likely a violation of the plan it was issued under, not just a
policy this repository can wave through by bumping a constant. A product that is no
longer personal and single-user needs its own credential and billing arrangement,
which this document does not cover.

## Confirming the gate without touching the secret

Status is derived entirely from `CLAUDE_ENABLED` (`TAMFORGE_CLAUDE_ENABLED`) and the
newest stored attestation; nothing else is consulted and no code path returns the
token itself. `claude_status` reports `("ready", "none")` only when Claude is enabled
and the newest attestation is current. Every other combination reports `"disabled"`
with a reason from the closed `DISABLED_REASONS` vocabulary — `not_enabled`,
`attestation_missing`, or `attestation_superseded` — never free text and never a
secret. `apps/backend/tests/unit/agents/test_settings.py` and
`test_compatibility.py` are the executable form of this rule; rerunning them is
sufficient to confirm the gate still behaves as this document describes.

## Running the compatibility probe

Recording the attestation opens the gate; it does not prove the host can actually run
Claude work. `probe_claude_compatibility` answers that second question by asking the
installed runtime what it is. It sends no owner content: one requested model
identifier goes out, and versions, an authentication method, a resolved model and a
fixed structured echo come back. It also runs the attestation gate first and skips the
runtime entirely while Claude is disabled, so an operator can never learn anything
about the runtime that the gate has not already permitted.

The result is one of four statuses. `ready` means every check passed and Claude work
may claim jobs. `disabled` repeats the gate's own reason. `blocked` means the host is
misconfigured in a way a human has to fix: the SDK is missing or below
`MINIMUM_SDK_VERSION`, the credential is absent or is not the subscription one, the
requested model did not resolve to one the subscription supports, the structured
response did not come back, the credential was refused, or Anthropic policy refused
the use. `needs_attention` means the quota is spent or the probe itself did not
complete, both of which resolve without a configuration change.

Every reason carries nonsecret remediation from `PROBE_REMEDIATION`, and every entry
in that table is safe to display anywhere. An unexpected runtime exception is
classified as `probe_failed` and its message is deliberately dropped rather than
rendered, because an SDK error can carry the credential it tried to use. Read the
worker host's own logs for the detail.

Two rules matter operationally. A quota failure is not a retry loop: wait for the
window rather than hammering it, and never resolve it by adding an API key. And a
`blocked` result stops Claude work from claiming jobs without making the API
unready — every non-Claude study path keeps working, which is the whole point of the
gate failing closed.

## Refusing every other way in

`ClaudeSubscriptionSettings.for_worker` decides whether the Claude worker may start at
all. It judges an environment mapping the caller passes in rather than reading the
process environment, so a stray variable from a shell, a dotenv file or a secrets
directory cannot reach the decision.

It refuses when any of `FORBIDDEN_CREDENTIAL_VARS` is present. That list is longer than
an API key on purpose. An unset `ANTHROPIC_API_KEY` does not mean there are no
credentials: the SDK also resolves `ANTHROPIC_AUTH_TOKEN`, a named profile through
`ANTHROPIC_PROFILE`, and a workload-identity federation set, and `ANTHROPIC_BASE_URL`
can point an otherwise valid token at another endpoint. The Bedrock, Vertex and Foundry
switches are on the list for the same reason. Presence is what counts, not the value:
an empty `ANTHROPIC_API_KEY` still outranks the subscription profile in the SDK's
resolution order.

It then requires a current attestation and the subscription credential itself. A
missing credential is a refusal, never a fallback, because a fallback is exactly what
must not exist here. Every rejection names the variable and never its value, and the
token is a `SecretStr` that stays redacted in reprs, dumps and JSON.

The worker process receives only what `worker_environment()` returns: the subscription
token plus the telemetry opt-outs. Nonessential traffic, error reporting and the bug
command are all off, because this is a private single-user workspace and its
transcripts are the last thing that should leave it in a crash report. Concurrency is
fixed at one job, since a personal subscription is not a pool and parallel jobs turn a
quota into an outage.

None of this makes the API depend on a Claude credential. With `CLAUDE_ENABLED` false
the application starts with no credential at all and every non-Claude study path works.
