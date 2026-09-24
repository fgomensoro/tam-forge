#!/bin/bash
# Rotates the Claude subscription token on the production host.
#
# The token is read with echo off and travels only on ssh's stdin: never in argv, a
# local file, or the terminal scrollback. Everything on the host happens inside one
# ssh session, so the Bitwarden agent prompts once. See
# docs/runbooks/claude-subscription.md, "Rotating the token".
set -euo pipefail

host="${TAMFORGE_HOST:-hetzner-server-2}"
wait_seconds="${TAMFORGE_ROTATE_WAIT_SECONDS:-90}"

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
cat > /etc/tamforge/secrets/claude-oauth.env.new
chown root:tamforge-claude /etc/tamforge/secrets/claude-oauth.env.new
chmod 0640 /etc/tamforge/secrets/claude-oauth.env.new
mv -f /etc/tamforge/secrets/claude-oauth.env.new /etc/tamforge/secrets/claude-oauth.env
started="\$(date -u +%Y-%m-%dT%H:%M:%SZ)"
systemctl restart tamforge-claude-worker
for _ in \$(seq 1 $((wait_seconds / 5))); do
  sleep 5
  beat="\$(sudo -u postgres psql -d tamforge -Atc "select status || ' ' || reason from worker_heartbeats where worker = 'claude' and observed_at > '\$started'")"
  if [ -n "\$beat" ]; then echo "\$beat"; exit 0; fi
done
echo "unknown not_observed"
REMOTE
)"

# printf is a shell builtin, so the token never shows up in a process listing.
result="$(printf 'CLAUDE_CODE_OAUTH_TOKEN=%s\n' "$token" | ssh "$host" "$remote")"
unset token

status="${result%% *}"
reason="${result#* }"
next="$(date -u -v+1y +%Y-%m-%d 2>/dev/null || date -u -d '+1 year' +%Y-%m-%d)"
if [ "$status" = "ok" ]; then
  echo "Claude worker is ready with the new token. Rotate again before $next."
  exit 0
fi
echo "Token installed, but the Claude worker reports $status ($reason). See docs/runbooks/claude-subscription.md." >&2
exit 1
