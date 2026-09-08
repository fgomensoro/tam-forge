#!/bin/zsh
# Fetch, verify, and install the pinned whisper.cpp XCFramework.
#
# Idempotent: exits 0 immediately when the macOS slice is already installed.
# Downloads to a temporary staging directory, verifies size and sha256
# against config/speech-models.yaml before moving anything into place, and
# never leaves a corrupt or partial download installed. Pins live only in
# the manifest; never duplicate them here.
set -euo pipefail
cd "$(dirname "$0")/../.."

MANIFEST="config/speech-models.yaml"
ARTIFACT="whisper_framework"

if python3 -c 'import yaml' >/dev/null 2>&1; then
  PY=(python3)
else
  # Ephemeral environment with only PyYAML: never sync the whole project
  # just to read three pins.
  PY=(uv run --no-project --with pyyaml python)
fi

pin() {
  "${PY[@]}" -c '
import sys
import yaml

with open(sys.argv[1], encoding="utf-8") as handle:
    document = yaml.safe_load(handle)
print(document["artifacts"][sys.argv[2]][sys.argv[3]])
' "$MANIFEST" "$ARTIFACT" "$1"
}

sha256_of() {
  shasum -a 256 "$1" | awk '{print $1}'
}

url="$(pin url)"
filename="$(pin filename)"
expected_bytes="$(pin bytes)"
expected_sha256="$(pin sha256)"
dest="$(pin installs_to)"
macos_slice="$dest/macos-arm64_x86_64/whisper.framework"

if [[ -d "$macos_slice" ]]; then
  echo "whisper.xcframework already installed at $dest"
  exit 0
fi

STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT

download="$STAGE/$filename"
echo "Downloading $filename..."
curl -sSL --fail --connect-timeout 30 --max-time 900 -o "$download" "$url"

actual_bytes="$(stat -f%z "$download")"
if [[ "$actual_bytes" != "$expected_bytes" ]]; then
  rm -f "$download"
  echo "fetch_whisper_framework: $filename size mismatch (expected $expected_bytes bytes, got $actual_bytes)" >&2
  exit 1
fi

actual_sha256="$(sha256_of "$download")"
if [[ "$actual_sha256" != "$expected_sha256" ]]; then
  rm -f "$download"
  echo "fetch_whisper_framework: $filename sha256 mismatch (expected $expected_sha256, got $actual_sha256)" >&2
  exit 1
fi

mkdir -p "$STAGE/unzipped"
unzip -q "$download" -d "$STAGE/unzipped"

candidates=("$STAGE"/unzipped/**/*.xcframework(N/))
if (( ${#candidates[@]} != 1 )); then
  echo "fetch_whisper_framework: expected exactly one .xcframework in $filename, found ${#candidates[@]}" >&2
  exit 1
fi
extracted="${candidates[1]}"

mkdir -p "$(dirname "$dest")"
rm -rf "$dest"
mv "$extracted" "$dest"

if [[ ! -d "$macos_slice" ]]; then
  rm -rf "$dest"
  echo "fetch_whisper_framework: installed XCFramework is missing its macOS slice at $macos_slice" >&2
  exit 1
fi

echo "Installed whisper.xcframework ($ARTIFACT $(pin version)) to $dest"
