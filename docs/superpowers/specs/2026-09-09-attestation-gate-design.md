# Data-model-improvement attestation gate

Issue #104 (E9-I02), Task 3 of the agents/interviews/operations plan.

Claude stays disabled until a current model-improvement-off attestation and a
subscription-policy acknowledgement are stored.

## Scope

This slice opens the Claude work. Nothing about Claude configuration exists in the
repository yet, so it creates the settings module, the attestation record and the
status vocabulary that #65 and #66 then extend. The dependency chain is
#104 → #65 → #66, so this is the base rather than a leaf.

It does not implement the compatibility probe that checks the installed SDK, the
subscription login and the model, which is #65. It does not reject Anthropic API
credentials or enforce the no-paid-fallback policy, which is #66. It does not run
Claude jobs, which is #67.

## The attestation is provenance, not configuration

`PrivacyAttestation` extends the `Record` base already shared by prompt versions,
model runs and analysis publications, so it inherits canonical JSON bytes, a
database-verified content hash, and the triggers that reject updates and deletes.

An environment variable was considered and rejected. This is a privacy claim about
what a third party is permitted to do with the learner's work. A claim that can be
rewritten in place, with no history and no trace, proves nothing on the day it
matters. Append-only rows mean the question "when did I attest, and to what" always
has an answer.

Each row records the policy version acknowledged, that data-model-improvement is off,
and when it was made. The current attestation is the newest row. Earlier ones stay as
history.

## Currency is a version comparison, not a clock

The code carries the Anthropic data policy version it expects as a constant. An
attestation is current when its recorded version equals that constant.

A time-based expiry was considered. It answers the wrong question: what matters is
not how long ago the learner attested but whether what they agreed to is still what
governs. A yearly TTL would keep a stale attestation valid for months after a policy
change, and would invalidate a perfectly accurate one on an arbitrary date. Bumping
the constant when Anthropic changes its policy invalidates every prior attestation at
exactly the right moment, with no clock to mock in tests and no migration.

The cost: someone has to notice the policy changed and bump the constant. The runbook
makes that an explicit step and pins where to check.

## Disabled is a valid, working state

`CLAUDE_ENABLED=false` keeps the application configuration valid and the API healthy.
Every independent study path works without Claude, so a missing attestation degrades
one feature rather than breaking the product.

Enabling Claude without a current attestation reports `disabled` rather than raising.
The application must not refuse to start over a missing attestation: that would take
the whole product down to protect one feature. The gate still fails closed, because
`disabled` is the default and the absence of evidence is never read as permission.

Status carries a machine-readable, non-secret reason. No endpoint accepts or returns
a Claude token. The worker that refuses to claim jobs on a disabled status is #67's
work; this slice deliberately ships no exception type for a caller that does not
exist yet.

## Testing

The version comparison and the fail-closed settings rules are unit tests with no
database. The attestation record's shape and immutability wiring follow the existing
provenance tests; the trigger behaviour itself belongs to the `postgres_integration`
marker.
