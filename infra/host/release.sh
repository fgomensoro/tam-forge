#!/usr/bin/env bash
# Make one unpacked release current on tamforge-prod. Runs as root, from deploy-receive
# or by hand:  infra/host/release.sh /opt/tamforge/releases/<id>
# Steps: uv sync at the release root, migrate as tamforge_migrator, switch the `current`
# link, reinstall units, restart, wait for /readyz 200. On failure the link moves back to
# the previous release; the database is never downgraded.
set -euo pipefail

release="${1:?usage: release.sh <release dir>}"
root="$(dirname "$(dirname "$release")")"
current="$root/current"
previous="$(readlink -f "$current" 2>/dev/null || true)"
units=(tamforge-api tamforge-worker tamforge-claude-worker)

log() { echo "release: $*"; }

log "syncing $release"
cd "$release"
/usr/local/bin/uv sync --frozen --no-dev --project apps/backend
chown -R root:tamforge "$release"
chmod -R o-rwx "$release"

log "migrating as tamforge_migrator"
MIGRATION_URL="postgresql+psycopg://tamforge_migrator:$(cat /etc/tamforge/secrets/pg-tamforge_migrator.password)@127.0.0.1:5432/tamforge" \
  flock /run/tamforge/migrate.lock .venv/bin/python -c '
import os
from alembic import command
from alembic.config import Config
c = Config("apps/backend/alembic.ini")
c.attributes["database_url"] = os.environ["MIGRATION_URL"]
command.upgrade(c, "head")
'

swap() {
  ln -sfn "$1" "$current.next"
  mv -T "$current.next" "$current"
  install -m 0644 "$current"/infra/systemd/tamforge-*.service /etc/systemd/system/
  mkdir -p "$root/bin"
  install -m 0755 "$current/infra/host/deploy-receive.sh" "$root/bin/deploy-receive"
  systemctl daemon-reload
  systemctl restart "${units[@]}"
}

ready() {
  for _ in $(seq 1 30); do
    if [[ "$(curl -s -o /dev/null -w '%{http_code}' --max-time 2 http://127.0.0.1:8000/readyz)" == "200" ]]; then
      return 0
    fi
    sleep 1
  done
  return 1
}

log "switching current to $release"
swap "$release"
if ! ready; then
  log "readyz did not answer 200 in 30s"
  if [[ -n "$previous" && -d "$previous" ]]; then
    log "rolling current back to $previous (database left at head)"
    swap "$previous"
  fi
  journalctl -u tamforge-api -n 40 --no-pager >&2 || true
  exit 1
fi
log "readyz 200, current is $(readlink -f "$current")"

# Keep the last five releases, never the live one, so a rollback always has a target.
# grep exits 1 when nothing is left to prune; that is not a failed release.
ls -1d "$root"/releases/*/ | sort | head -n -5 | { grep -vx "$(readlink -f "$current")/" || true; } | xargs -r rm -rf
