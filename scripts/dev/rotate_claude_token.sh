#!/bin/bash
# Rotates one of the two Claude subscription token slots on the production host.
# Usage: rotate_claude_token.sh [a|b]   (make rotate-claude-token SLOT=b); the slot defaults to a.
#
# The token is read with echo off and travels only on ssh's stdin: never in argv or a
# local file. Everything on the host happens inside one ssh session, so the Bitwarden
# agent prompts once. See
# docs/runbooks/claude-subscription.md, "Rotating the token".
set -euo pipefail

host="${TAMFORGE_HOST:-hetzner-server-2}"
# The worker beats only after a whole step, and with a working token that step runs the
# Claude jobs queued while it was down, each bounded by its lease; cover one of them.
wait_seconds="${TAMFORGE_ROTATE_WAIT_SECONDS:-900}"

slot="${1:-a}"
# Slot A keeps the file and variable the host had before slots existed.
case "$slot" in
  a) file=claude-oauth.env; variable=CLAUDE_CODE_OAUTH_TOKEN ;;
  b) file=claude-oauth-b.env; variable=CLAUDE_CODE_OAUTH_TOKEN_B ;;
  *)
    echo "SLOT must be a or b. Nothing changed." >&2
    exit 1
    ;;
esac
label="$(printf '%s' "$slot" | tr '[:lower:]' '[:upper:]')"

if [ "${TAMFORGE_SKIP_SETUP_TOKEN:-0}" != "1" ]; then
  if command -v claude >/dev/null 2>&1; then
    echo "Running 'claude setup-token'. Finish the browser sign-in, then copy the token it prints."
    claude setup-token
  else
    echo "The claude CLI is not on PATH. Run 'claude setup-token' elsewhere and paste its token here." >&2
  fi
fi

printf 'Paste the new token (input is hidden): ' >&2
IFS= read -rs token
# `claude setup-token` hard-wraps the token, so a copy of it arrives as several lines in
# one paste. Take the rest of that paste too; it is already buffered, so the wait is short.
while IFS= read -rs -t 1 more; do token+="$more"; done
printf '\n' >&2
token="${token//[[:space:]]/}"
case "$token" in
  sk-ant-oat*) ;;
  *)
    echo "That is not a subscription token (expected the sk-ant-oat prefix). Nothing changed." >&2
    exit 1
    ;;
esac

remote="$(cat <<REMOTE
set -euo pipefail
umask 077
cat > /etc/tamforge/secrets/$file.new
chown root:tamforge-claude /etc/tamforge/secrets/$file.new
chmod 0640 /etc/tamforge/secrets/$file.new
mv -f /etc/tamforge/secrets/$file.new /etc/tamforge/secrets/$file
# The API reads the tokens too, for the Claude calls it answers inside a request.
systemctl restart tamforge-claude-worker tamforge-api
# The heartbeat speaks for the active slot only; rotating the other one has nothing to wait for.
# The first owner, as the worker picks it.
active="\$(sudo -u postgres psql -d tamforge -Atc "select coalesce((select slot from claude_token_slots where owner_id = (select min(id) from owners)), 'a')")"
if [ "\$active" != "$slot" ]; then echo "inactive \$active"; exit 0; fi
# Read after the restart and from the database's own clock: restart returns only once the
# old process has exited, including its last beat, so any newer row is the new process's.
started="\$(sudo -u postgres psql -d tamforge -Atc 'select clock_timestamp()')"
for _ in \$(seq 1 $((wait_seconds / 5))); do
  sleep 5
  beat="\$(sudo -u postgres psql -d tamforge -Atc "select status || ' ' || reason from worker_heartbeats where worker = 'claude' and observed_at > '\$started'")"
  if [ -n "\$beat" ]; then echo "\$beat"; exit 0; fi
  printf . >&2
done
echo "unknown not_observed"
REMOTE
)"

echo "Installing the slot $label token and waiting up to $((wait_seconds / 60)) minutes for the Claude worker's first heartbeat."
# printf is a shell builtin, so the token never shows up in a process listing.
if ! result="$(printf '%s=%s\n' "$variable" "$token" | ssh "$host" "$remote")"; then
  unset token
  echo "The host step failed, possibly after the new token was installed. Check 'journalctl -u tamforge-claude-worker -u tamforge-api' on the host." >&2
  exit 1
fi
unset token
printf '\n' >&2

status="${result%% *}"
reason="${result#* }"
next="$(date -u -v+1y +%Y-%m-%d 2>/dev/null || date -u -d '+1 year' +%Y-%m-%d)"
if [ "$status" = "inactive" ]; then
  active_label="$(printf '%s' "$reason" | tr '[:lower:]' '[:upper:]')"
  echo "Token installed in slot $label. Slot $active_label is active; switch to slot $label in Settings > Claude to use it. Rotate again before $next."
  exit 0
fi
if [ "$status" = "ok" ]; then
  echo "Claude worker is ready with the new slot $label token. Rotate again before $next."
  exit 0
fi
echo "Token installed in slot $label, but the Claude worker reports $status ($reason). See docs/runbooks/claude-subscription.md." >&2
exit 1
