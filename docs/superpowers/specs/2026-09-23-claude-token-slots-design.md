# Two Claude subscription token slots

## Goal

The owner has two Claude subscriptions. Each one's token is installed on the production
host in its own slot, A or B, and the Mac app's Settings > Claude pane chooses which slot
the Claude worker uses. When the active subscription runs out of quota, one click moves
the worker to the other. The switch is manual: the worker never changes slots on its own.

## Constraint kept from the rotation work

No TAM Forge endpoint, request body, log line, database row or repository file carries a
token. Tokens still reach the host only through `make rotate-claude-token` over ssh stdin.
The app and the API handle nothing but the slot name, `"a"` or `"b"`.

## Host

- Slot A is the existing `/etc/tamforge/secrets/claude-oauth.env` holding
  `CLAUDE_CODE_OAUTH_TOKEN`. Nothing on the host migrates.
- Slot B is `/etc/tamforge/secrets/claude-oauth-b.env` holding `CLAUDE_CODE_OAUTH_TOKEN_B`,
  same owner and mode (`root:tamforge-claude`, 0640). The worker unit loads it optionally
  (`EnvironmentFile=-...`), like slot A.
- `make rotate-claude-token SLOT=b` installs slot B; `SLOT` defaults to `a`. The worker
  restarts either way. When the rotated slot is the active one, the script waits for the
  new worker's first heartbeat as it does today. When it is not, the script reports the
  token as installed and says to switch to it in Settings.

## Database and API

- Table `claude_token_slots`: `owner_id` (primary key, FK to `owners`), `slot` (text,
  check `slot IN ('a', 'b')`), `updated_at`. No row means slot A.
- `GET /ops/claude/slot` returns `{"slot": "a"}`; owner only.
- `PUT /ops/claude/slot` with `{"slot": "b"}` stores the choice and echoes it; owner only,
  with the existing CSRF rule for cookie sessions. Any other body is a 422.
- Both stay out of OpenAPI, like every `/ops` route.

## Worker

- On its first beat the worker records both installed tokens from its environment.
- Every beat it reads the active slot and sets `CLAUDE_CODE_OAUTH_TOKEN` to that slot's
  token, or removes it when the slot has none. Everything downstream (the settings gate,
  the probe, the SDK runtime) keeps reading that one variable and does not change.
- A slot change drops the cached probe verdict, so the next beat probes the new token
  instead of reporting the old slot's state for up to 15 minutes.
- A chosen slot with no token installed reports `auth`, exactly like a missing token today.

## Mac app

- Settings > Claude gets a segmented Slot A / Slot B control above the status. Choosing a
  slot sends the PUT and refreshes. The status shown is always the active slot's.
- The rotation command shows the chosen slot: `make rotate-claude-token SLOT=b`.
- The quota-spent detail tells the owner to switch to the other slot or wait for the reset.

## Out of scope

Automatic failover between slots, custom slot names, more than two slots, per-slot status
for the inactive slot.

## Testing

Integration test for the slot table (default, upsert, check constraint); unit tests for the
routes (owner only, 422 on anything but a slot, out of OpenAPI), for the worker's slot
switch (token swap, probe reset, slot A surviving a switch to B and back), for the rotation
script with `SLOT=b` and an inactive slot, for the systemd unit loading both files, and for
the Swift model and live client.
