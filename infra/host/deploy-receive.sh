#!/usr/bin/env bash
# Forced command for the GitHub Actions deploy key. The authorized_keys line is
#   command="/opt/tamforge/bin/deploy-receive",restrict ssh-ed25519 ...
# and the caller runs `git archive --format=tar HEAD | ssh root@host <release-id>`.
# The key can only reach this script: no shell, no forwarding, no other command.
set -euo pipefail

root="${TAMFORGE_ROOT:-/opt/tamforge}"
release_id="${SSH_ORIGINAL_COMMAND:-}"

if [[ ! "$release_id" =~ ^[0-9]{8}T[0-9]{6}Z-[0-9a-f]{7,40}$ ]]; then
  echo "deploy-receive: refused: release id must be <stamp>-<sha>" >&2
  exit 2
fi

release="$root/releases/$release_id"
if [[ -e "$release" ]]; then
  echo "deploy-receive: refused: $release_id already installed" >&2
  exit 2
fi

mkdir -p "$release"
tar -x -C "$release"
exec "${TAMFORGE_RELEASE_SH:-$release/infra/host/release.sh}" "$release"
