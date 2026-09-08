#!/bin/zsh
# Fetch, verify, and install the pinned whisper.cpp models (transcription +
# VAD) into Application Support.
#
# Idempotent: an artifact already installed with the right size and sha256
# is left alone and nothing is downloaded. Downloads go to a temporary
# staging directory and are verified against config/speech-models.yaml
# before being moved into place; a mismatch deletes the download and fails.
# Pins live only in the manifest; never duplicate them here.
set -euo pipefail
cd "$(dirname "$0")/../.."

MANIFEST="config/speech-models.yaml"

if python3 -c 'import yaml' >/dev/null 2>&1; then
  PY=(python3)
else
  PY=(uv run python)
fi

pin() {
  "${PY[@]}" -c '
import sys
import yaml

with open(sys.argv[1], encoding="utf-8") as handle:
    document = yaml.safe_load(handle)
print(document["artifacts"][sys.argv[2]][sys.argv[3]])
' "$MANIFEST" "$1" "$2"
}

expand_home() {
  case "$1" in
    "~") print -r -- "$HOME" ;;
    "~/"*) print -r -- "$HOME/${1#\~/}" ;;
    *) print -r -- "$1" ;;
  esac
}

sha256_of() {
  shasum -a 256 "$1" | awk '{print $1}'
}

STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT

fetch_one() {
  local key="$1"
  local url filename expected_bytes expected_sha256 install_dir dest
  local download actual_bytes actual_sha256

  url="$(pin "$key" url)"
  filename="$(pin "$key" filename)"
  expected_bytes="$(pin "$key" bytes)"
  expected_sha256="$(pin "$key" sha256)"
  install_dir="$(expand_home "$(pin "$key" installs_to)")"
  dest="$install_dir/$filename"

  if [[ -f "$dest" ]]; then
    actual_bytes="$(stat -f%z "$dest")"
    if [[ "$actual_bytes" == "$expected_bytes" && "$(sha256_of "$dest")" == "$expected_sha256" ]]; then
      echo "$filename already installed at $dest"
      return 0
    fi
  fi

  mkdir -p "$install_dir"
  download="$STAGE/$filename"
  echo "Downloading $filename..."
  curl -sSL --fail --connect-timeout 30 --max-time 900 -o "$download" "$url"

  actual_bytes="$(stat -f%z "$download")"
  if [[ "$actual_bytes" != "$expected_bytes" ]]; then
    rm -f "$download"
    echo "fetch_whisper_models: $filename size mismatch (expected $expected_bytes bytes, got $actual_bytes)" >&2
    exit 1
  fi

  actual_sha256="$(sha256_of "$download")"
  if [[ "$actual_sha256" != "$expected_sha256" ]]; then
    rm -f "$download"
    echo "fetch_whisper_models: $filename sha256 mismatch (expected $expected_sha256, got $actual_sha256)" >&2
    exit 1
  fi

  mv "$download" "$dest"
  echo "Installed $filename to $dest"
}

fetch_one transcription_model
fetch_one vad_model
