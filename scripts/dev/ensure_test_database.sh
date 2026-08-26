#!/bin/bash
set -euo pipefail

fail() {
  printf 'ensure_test_database: %s\n' "$1" >&2
  exit 1
}

host="${TAMFORGE_TEST_DB_HOST:-127.0.0.1}"
port="${TAMFORGE_TEST_DB_PORT:-54329}"
admin_user="${TAMFORGE_TEST_DB_ADMIN_USER:-tamforge}"
admin_database="${TAMFORGE_TEST_DB_ADMIN_DATABASE:-postgres}"
target_database="${TAMFORGE_TEST_DB_NAME:-tamforge_test}"

[[ "$host" == "127.0.0.1" ]] || fail "host must be exactly 127.0.0.1"
[[ "$port" =~ ^[1-9][0-9]{0,4}$ ]] || fail "port must contain only 1 to 5 digits"
port_number=$((10#$port))
(( port_number <= 65535 )) || fail "port is outside the valid range"
[[ "$admin_user" =~ ^[a-z_][a-z0-9_]{0,62}$ ]] || fail "admin user is invalid"
[[ "$admin_database" == "postgres" ]] || fail "admin database must be exactly postgres"
[[ "$target_database" == "tamforge_test" ]] || fail "target database must be exactly tamforge_test"

resolve_tool() {
  local name="$1"
  local resolved
  resolved="$(command -v -- "$name" 2>/dev/null)" || fail "required tool is unavailable"
  [[ "$resolved" == /* ]] || fail "required tool path must be absolute"
  [[ "$resolved" != *$'\n'* ]] || fail "required tool path is invalid"
  [[ -f "$resolved" && -x "$resolved" && ! -L "$resolved" ]] \
    || fail "required tool must be a regular non-symlink executable"
  printf '%s' "$resolved"
}

psql_path="$(resolve_tool psql)"
createdb_path="$(resolve_tool createdb)"

database_exists() {
  local output
  if ! output="$("$psql_path" \
    --no-psqlrc \
    --host "$host" \
    --port "$port" \
    --username "$admin_user" \
    --dbname "$admin_database" \
    --tuples-only \
    --no-align \
    --set ON_ERROR_STOP=1 \
    --command "SELECT 1 FROM pg_database WHERE datname = 'tamforge_test'"
  )"; then
    fail "psql database existence check failed"
  fi
  [[ "$output" =~ ^[[:space:]]*1[[:space:]]*$ ]]
}

if database_exists; then
  printf 'tamforge_test already exists\n'
  exit 0
fi

if ! "$createdb_path" \
  --host "$host" \
  --port "$port" \
  --username "$admin_user" \
  --maintenance-db "$admin_database" \
  "$target_database"; then
  if database_exists; then
    printf 'tamforge_test was created concurrently\n'
    exit 0
  fi
  fail "createdb failed and tamforge_test is still absent"
fi

database_exists || fail "tamforge_test was not visible after creation"
printf 'tamforge_test created\n'
