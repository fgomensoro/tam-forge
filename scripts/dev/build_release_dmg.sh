#!/bin/zsh
# Build the Release app with the stable local signing identity, verify the
# bundle, and package it as a DMG. Signing material never enters the repository.
set -euo pipefail
cd "$(dirname "$0")/../.."
IDENTITY="${TAMFORGE_SIGNING_IDENTITY:-TAM Forge Local Development}"
DERIVED="${TAMFORGE_DERIVED_DATA:-${TMPDIR:-/tmp}/tamforge-release}"
OUT="${1:-$PWD/build/TAMForge.dmg}"
DEVELOPER_DIR="${DEVELOPER_DIR:-$(xcode-select -p)}"
export DEVELOPER_DIR

if ! security find-identity -v -p codesigning | grep -q "\"$IDENTITY\""; then
  echo "signing identity '$IDENTITY' is not in the login keychain" >&2
  exit 2
fi

xcodebuild -jobs 2 -skipPackagePluginValidation \
  -project apps/macos/TAMForge.xcodeproj -scheme TAMForge \
  -configuration Release -destination 'platform=macOS' \
  -derivedDataPath "$DERIVED" \
  CODE_SIGN_IDENTITY="$IDENTITY" CODE_SIGNING_ALLOWED=YES CODE_SIGN_STYLE=Manual build

APP="$DERIVED/Build/Products/Release/TAMForge.app"
python3 scripts/ci/check_native_bundle.py "$APP" --require-identity "$IDENTITY"

STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT
cp -R "$APP" "$STAGE/"
ln -s /Applications "$STAGE/Applications"
mkdir -p "$(dirname "$OUT")"
rm -f "$OUT"
hdiutil create -quiet -volname "TAM Forge" -srcfolder "$STAGE" -ov -format UDZO "$OUT"

codesign -dv --verbose=2 "$APP" 2>&1 | grep -E "^(Identifier|Authority|CDHash|TeamIdentifier)=" || true
echo "DMG written: $OUT"
