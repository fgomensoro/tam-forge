# Claude subscription activation

Claude stays disabled until a human carries out this procedure and its outcome is
stored as a `PrivacyAttestation` row (`apps/backend/src/tamforge_backend/agents/models.py`).
`claude_status` (`apps/backend/src/tamforge_backend/agents/compatibility.py`) reads that
row through `AttestationRepository.current` and reports `disabled` for every
combination except `CLAUDE_ENABLED=true` plus a current attestation. This document is
that procedure: obtaining the credential, judging the policy it operates under, and
recording that judgment. It does not cover the compatibility probe that checks the
installed SDK, the subscription login and the resolved model, which is #65's work, or
the API-credential rejection and no-paid-fallback policy, which is #66's. Both extend
`agents/compatibility.py`; neither exists yet.

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
requires. `PrivacyAttestation` is append-only, like every other row on the `Record`
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
