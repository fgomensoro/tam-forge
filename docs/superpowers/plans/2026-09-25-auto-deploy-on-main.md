# Auto Deploy on Main Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every push to `main` with green CI deploys the backend to `tamforge-prod` without a human on the keyboard.

**Architecture:** GitHub Actions streams `git archive HEAD` over ssh to a forced-command key on the host. The forced command (`deploy-receive`) validates the release id, unpacks the tar into `/opt/tamforge/releases/<id>` and hands over to that release's own `infra/host/release.sh`, which runs the proven manual procedure: `uv sync`, migrations as `tamforge_migrator`, atomic `current` swap, unit install and restart, `/readyz` check with symlink rollback on failure. The deploy key can only run the receiver, never a shell.

**Tech Stack:** bash, GitHub Actions, OpenSSH forced commands, uv, alembic, systemd.

**Spec:** the design agreed in chat on 2026-09-25 (bounded; no spec file). The manual procedure it scripts is `docs/runbooks/production-release.md` after this change.

## Global Constraints

- The host is `tamforge-prod` (`46.224.232.77`, root, Ubuntu 24.04). API listens on `127.0.0.1:8000`.
- Release id format is `<UTC stamp>-<7 hex sha>`, matching `RELEASE_ID_PATTERN` in `infra/host/deploy.py`.
- Migrations run as `tamforge_migrator`; the password is read from `/etc/tamforge/secrets/pg-tamforge_migrator.password` and never printed.
- Only `tamforge-api`, `tamforge-worker` and `tamforge-claude-worker` are restarted; speech and embedding units stay disabled.
- `/readyz` HTTP 200 is the pass condition; the body is `degraded` by design.
- The database is never downgraded on rollback; only the `current` link moves back.
- Nothing in the workflow or scripts echoes a secret. The private key exists only in the `PROD_DEPLOY_KEY` repository secret.

---

### Task 1: Host scripts and their test

**Files:**
- Create: `infra/host/deploy-receive.sh`
- Create: `infra/host/release.sh`
- Test: `infra/tests/test_deploy_receive.py`

**Interfaces:**
- Produces: `deploy-receive.sh` reads the release id from `SSH_ORIGINAL_COMMAND`, the tar from stdin, honours `TAMFORGE_ROOT` (default `/opt/tamforge`) and `TAMFORGE_RELEASE_SH` (default `<release>/infra/host/release.sh`) for tests. Exit 0 on success, 2 on a refused id.
- Produces: `release.sh <release dir>` runs on the host as root and expects `uv` at `/usr/local/bin/uv`.

- [ ] **Step 1: Write the failing test**

```python
# infra/tests/test_deploy_receive.py
from __future__ import annotations

import io
import os
import subprocess
import tarfile
from pathlib import Path

RECEIVE = Path(__file__).resolve().parents[1] / "host" / "deploy-receive.sh"


def _tar_with(name: str, body: bytes) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        info = tarfile.TarInfo(name)
        info.size = len(body)
        tar.addfile(info, io.BytesIO(body))
    return buf.getvalue()


def _run(tmp_path: Path, release_id: str, payload: bytes) -> subprocess.CompletedProcess[str]:
    stub = tmp_path / "release.sh"
    stub.write_text("#!/bin/sh\necho ran \"$1\" > \"$1/ran\"\n")
    stub.chmod(0o755)
    env = {**os.environ, "TAMFORGE_ROOT": str(tmp_path), "TAMFORGE_RELEASE_SH": str(stub), "SSH_ORIGINAL_COMMAND": release_id}
    return subprocess.run(["bash", str(RECEIVE)], input=payload, env=env, capture_output=True, text=True, check=False)


def test_a_release_is_unpacked_and_handed_to_its_release_script(tmp_path: Path) -> None:
    result = _run(tmp_path, "20260925T010203Z-abcdef0", _tar_with("README.md", b"hi"))
    assert result.returncode == 0, result.stderr
    release = tmp_path / "releases" / "20260925T010203Z-abcdef0"
    assert (release / "README.md").read_text() == "hi"
    assert (release / "ran").read_text().strip() == str(release)


def test_a_malformed_release_id_is_refused_before_touching_disk(tmp_path: Path) -> None:
    result = _run(tmp_path, "../../etc", _tar_with("x", b""))
    assert result.returncode == 2
    assert "release id" in result.stderr
    assert not (tmp_path / "releases").exists()


def test_a_release_id_is_installed_once(tmp_path: Path) -> None:
    (tmp_path / "releases" / "20260925T010203Z-abcdef0").mkdir(parents=True)
    result = _run(tmp_path, "20260925T010203Z-abcdef0", _tar_with("x", b""))
    assert result.returncode == 2
    assert "already installed" in result.stderr
```

- [ ] **Step 2: Run it, expect failure because the script does not exist**

Run: `uv run pytest infra/tests/test_deploy_receive.py -q`
Expected: 3 failed (`No such file or directory` for the script).

- [ ] **Step 3: Write `infra/host/deploy-receive.sh`**

```bash
#!/usr/bin/env bash
# Forced command for the GitHub Actions deploy key.
# authorized_keys: command="/opt/tamforge/bin/deploy-receive",restrict ssh-ed25519 ...
# The caller runs `git archive --format=tar HEAD | ssh root@host <release-id>`.
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
```

- [ ] **Step 4: Run the test, expect pass**

Run: `uv run pytest infra/tests/test_deploy_receive.py -q`
Expected: 3 passed.

- [ ] **Step 5: Write `infra/host/release.sh`** (host-only, no unit test; verified live in Task 3)

```bash
#!/usr/bin/env bash
# Make one unpacked release current on tamforge-prod. Runs as root from deploy-receive
# or by hand: infra/host/release.sh /opt/tamforge/releases/<id>
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
if ready; then
  log "readyz 200, current is $(readlink -f "$current")"
else
  log "readyz did not answer 200 in 30s"
  if [[ -n "$previous" && -d "$previous" ]]; then
    log "rolling current back to $previous (database left at head)"
    swap "$previous"
  fi
  journalctl -u tamforge-api -n 40 --no-pager >&2 || true
  exit 1
fi

# Keep the last five releases so a rollback always has a target.
ls -1d "$root"/releases/*/ | sort | head -n -5 | xargs -r rm -rf
```

- [ ] **Step 6: Lint and commit**

Run: `bash -n infra/host/release.sh infra/host/deploy-receive.sh && uv run ruff check infra/tests && uv run pytest infra/tests -q`
Expected: no syntax errors, ruff clean, all infra tests pass.

```bash
git add infra/host/deploy-receive.sh infra/host/release.sh infra/tests/test_deploy_receive.py
git commit -m "feat(infra): script the production release and its ssh receiver"
```

### Task 2: Deploy job in CI

**Files:**
- Modify: `.github/workflows/ci.yml` (append a job after `secret-scan`)

**Interfaces:**
- Consumes: repository secret `PROD_DEPLOY_KEY` (Task 3) and the host's ed25519 public key pinned in the job.

- [ ] **Step 1: Capture the host key** (public information, pinned to stop MITM)

Run: `ssh-keyscan -t ed25519 46.224.232.77 2>/dev/null`
Paste the resulting line into the `known_hosts` step below.

- [ ] **Step 2: Append the job**

```yaml
  deploy:
    if: github.event_name == 'push' && github.ref == 'refs/heads/main'
    needs: [macos-native, native-ui, backend-unit, backend-integration, e2e, openapi, secret-scan]
    runs-on: ubuntu-latest
    concurrency:
      group: deploy-prod
      cancel-in-progress: false
    steps:
      - uses: actions/checkout@v4
      - name: Install the deploy key
        run: |
          mkdir -p ~/.ssh
          printf '%s\n' "${{ secrets.PROD_DEPLOY_KEY }}" > ~/.ssh/deploy
          chmod 0600 ~/.ssh/deploy
          echo "<line from ssh-keyscan>" > ~/.ssh/known_hosts
      - name: Ship this commit as a release
        run: |
          release="$(date -u +%Y%m%dT%H%M%SZ)-${GITHUB_SHA::7}"
          echo "release $release"
          git archive --format=tar HEAD \
            | ssh -i ~/.ssh/deploy -o IdentitiesOnly=yes -o BatchMode=yes root@46.224.232.77 "$release"
      - name: Verify the public endpoint
        run: curl --fail --silent --show-error --output /dev/null --write-out 'readyz %{http_code}\n' https://app.homegastos.xyz/readyz
```

- [ ] **Step 3: Validate and commit**

Run: `uv run python -c "import yaml; yaml.safe_load(open('.github/workflows/ci.yml'))"`
Expected: no error.

```bash
git add .github/workflows/ci.yml
git commit -m "ci: deploy main to tamforge-prod after every green run"
```

### Task 3: One-time host and secret setup (this session, by hand)

**Files:** none in the repo. Host: `/root/.ssh/authorized_keys`, `/opt/tamforge/bin/deploy-receive`.

- [ ] **Step 1: Generate a dedicated key in the scratchpad and store it as a secret**

```bash
ssh-keygen -t ed25519 -N '' -C 'tam-forge github deploy' -f "$SCRATCH/deploy_key"
/opt/homebrew/bin/gh secret set PROD_DEPLOY_KEY < "$SCRATCH/deploy_key"
```

- [ ] **Step 2: Install the receiver and the forced-command key on the host**

```bash
scp infra/host/deploy-receive.sh hetzner-server-2:/opt/tamforge/bin/deploy-receive   # after mkdir -p /opt/tamforge/bin, chmod 0755
printf 'command="/opt/tamforge/bin/deploy-receive",restrict %s\n' "$(cat $SCRATCH/deploy_key.pub)" | ssh hetzner-server-2 'cat >> /root/.ssh/authorized_keys'
```

- [ ] **Step 3: Prove the key can only deploy**

Run: `ssh -i $SCRATCH/deploy_key -o IdentitiesOnly=yes root@46.224.232.77 'id'`
Expected: exit 2, `refused: release id must be <stamp>-<sha>`. No shell.

- [ ] **Step 4: Deploy the branch head through the real path before merging**

Run: `git archive --format=tar HEAD | ssh -i $SCRATCH/deploy_key -o IdentitiesOnly=yes root@46.224.232.77 "$(date -u +%Y%m%dT%H%M%SZ)-$(git rev-parse --short=7 HEAD)"`
Expected: `release: readyz 200, current is /opt/tamforge/releases/<id>`; `curl https://app.homegastos.xyz/readyz` gives 200.

- [ ] **Step 5: Shred the local private key**

```bash
rm -P "$SCRATCH/deploy_key" 2>/dev/null || rm "$SCRATCH/deploy_key"
```

### Task 4: Runbook

**Files:**
- Modify: `docs/runbooks/production-release.md`

- [ ] **Step 1: Add a "Backend deploy" section** stating: every push to `main` with green CI runs the `deploy` job; what it does (receiver, release.sh, rollback rule, five releases kept); how to redeploy by hand (`git archive ... | ssh root@host <id>` with a personal key, or `infra/host/release.sh <dir>` on the host); how to rotate the deploy key (new pair, `gh secret set`, replace the `authorized_keys` line). Keep the existing macOS DMG steps as they are; they are not automated.

- [ ] **Step 2: Commit**

```bash
git add docs/runbooks/production-release.md
git commit -m "docs: describe the automatic backend deploy and how to redo it by hand"
```

### Task 5: Merge and watch the first automatic deploy

- [ ] Open the PR, wait for CI, merge with admin.
- [ ] Watch the `deploy` job on the resulting `main` run; confirm `readyz 200` in its log and `readlink -f /opt/tamforge/current` on the host ends with the merge sha.
