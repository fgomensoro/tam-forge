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
password="${TAMFORGE_TEST_DB_PASSWORD-tamforge}"
test_mode="${TAMFORGE_TEST_DB_TEST_MODE:-0}"
test_tool_root="${TAMFORGE_TEST_DB_TOOL_ROOT:-}"
connect_timeout="5"
statement_options="-c statement_timeout=5000 -c lock_timeout=5000"

[[ "$host" == "127.0.0.1" ]] || fail "host must be exactly 127.0.0.1"
[[ "$port" =~ ^[1-9][0-9]{0,4}$ ]] || fail "port must contain only 1 to 5 digits"
port_number=$((10#$port))
(( port_number <= 65535 )) || fail "port is outside the valid range"
[[ "$admin_user" =~ ^[a-z_][a-z0-9_]{0,62}$ ]] || fail "admin user is invalid"
[[ "$admin_database" == "postgres" ]] || fail "admin database must be exactly postgres"
[[ "$target_database" == "tamforge_test" ]] || fail "target database must be exactly tamforge_test"
[[ -n "$password" && ${#password} -le 128 ]] || fail "database password is invalid"
[[ "$password" != *[[:space:]]* && "$password" != *[[:cntrl:]]* ]] \
  || fail "database password is invalid"

file_mode() {
  local path="$1"
  local mode
  if mode="$(/usr/bin/stat -f '%Lp' "$path" 2>/dev/null)"; then
    :
  elif mode="$(/usr/bin/stat -c '%a' "$path" 2>/dev/null)"; then
    :
  else
    fail "could not inspect tool permissions"
  fi
  [[ "$mode" =~ ^[0-7]{3,4}$ ]] || fail "tool permissions are invalid"
  printf '%s' "$mode"
}

assert_not_writable_by_others() {
  local path="$1"
  local mode
  mode="$(file_mode "$path")"
  (( (8#$mode & 8#022) == 0 )) || fail "tool path has unsafe permissions"
}

if [[ "$test_mode" == "1" ]]; then
  [[ "$test_tool_root" == /* && -d "$test_tool_root" && ! -L "$test_tool_root" ]] \
    || fail "isolated test tool root is invalid"
  [[ -O "$test_tool_root" ]] || fail "isolated test tool root has an invalid owner"
  root_mode="$(file_mode "$test_tool_root")"
  [[ "$root_mode" == "700" || "$root_mode" == "0700" ]] \
    || fail "isolated test tool root must have mode 700"
elif [[ "$test_mode" != "0" || -n "$test_tool_root" ]]; then
  fail "isolated test tool settings are invalid"
fi

normalize_path() {
  local path="$1"
  local directory
  local basename
  directory="${path%/*}"
  basename="${path##*/}"
  [[ -n "$directory" && -n "$basename" && -d "$directory" ]] \
    || fail "required tool path is invalid"
  directory="$(cd -P -- "$directory" 2>/dev/null && pwd -P)" \
    || fail "required tool path is invalid"
  printf '%s/%s' "$directory" "$basename"
}

path_is_trusted() {
  local path="$1"
  if [[ "$test_mode" == "1" ]]; then
    [[ "$path" == "$test_tool_root"/* ]]
    return
  fi
  [[
    "$path" == /opt/homebrew/*
    || "$path" == /usr/local/*
    || "$path" == /usr/bin/*
    || "$path" == /Applications/Postgres.app/Contents/Versions/*
  ]]
}

resolve_tool() {
  local name="$1"
  local resolved
  local link_target
  local hops=0
  resolved="$(command -v -- "$name" 2>/dev/null)" || fail "required tool is unavailable"
  [[ "$resolved" == /* && "$resolved" != *$'\n'* ]] \
    || fail "required tool path must be absolute"
  resolved="$(normalize_path "$resolved")"

  while [[ -L "$resolved" ]]; do
    hops=$((hops + 1))
    (( hops <= 20 )) || fail "required tool symlink chain is invalid"
    link_target="$(/usr/bin/readlink "$resolved" 2>/dev/null)" \
      || fail "required tool symlink is invalid"
    [[ -n "$link_target" && "$link_target" != *$'\n'* ]] \
      || fail "required tool symlink is invalid"
    if [[ "$link_target" == /* ]]; then
      resolved="$link_target"
    else
      resolved="${resolved%/*}/$link_target"
    fi
    resolved="$(normalize_path "$resolved")"
  done

  [[ -f "$resolved" && -x "$resolved" ]] \
    || fail "required tool must resolve to a regular executable"
  path_is_trusted "$resolved" || fail "required tool resolved outside trusted roots"
  [[ "$test_mode" != "1" || -O "$resolved" ]] \
    || fail "isolated test tool has an invalid owner"
  assert_not_writable_by_others "$resolved"
  printf '%s' "$resolved"
}

psql_path="$(resolve_tool psql)"
createdb_path="$(resolve_tool createdb)"

database_exists() {
  local output
  if ! output="$(
    PGPASSWORD="$password" \
    PGCONNECT_TIMEOUT="$connect_timeout" \
    PGOPTIONS="$statement_options" \
    "$psql_path" \
      --no-psqlrc \
      --no-password \
      --host "$host" \
      --port "$port" \
      --username "$admin_user" \
      --dbname "$admin_database" \
      --tuples-only \
      --no-align \
      --set=ON_ERROR_STOP=1 \
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

if ! PGPASSWORD="$password" \
  PGCONNECT_TIMEOUT="$connect_timeout" \
  PGOPTIONS="$statement_options" \
  "$createdb_path" \
    --no-password \
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
