# Production release

1. Run the checklist and read the refusal, if any:

   ```bash
   uv run python -c "from pathlib import Path; from tamforge_backend.operations.release_checklist import evaluate; print(evaluate(Path('.')).render())"
   ```

   Every unresolved item names its artifact and why it does not resolve. Resolve the
   artifact; never the checklist.

2. Tag the exact commit as `v<MARKETING_VERSION>+<short sha>` and write it to
   `apps/macos/.release-tag`. The version item resolves only when the tag matches the
   project's `MARKETING_VERSION`.

3. Build and verify the DMG (`make macos-release-dmg`,
   `scripts/ci/check_native_bundle.py --require-identity "TAM Forge Local Development"`),
   and record the signature, DMG hash and permission persistence in
   `docs/project/signing-permission-persistence-v1.md` for this head.

4. Record the 60-minute recording runtime window on this head
   (`docs/project/issue-36-recording-verification-handoff.md`) so
   `docs/project/recording-verification-v1.json` is no longer the blocked template.

5. Confirm CI is green on the exact head, then run the checklist again. A release ships
   only when `releasable` is true. Merge and deployment stay separate approvals; a green
   checklist is not a deployment.

## Backend deploy

The backend deploys itself. Every push to `main` whose CI run is green ends in the
`deploy` job of `.github/workflows/ci.yml`, which streams `git archive HEAD` over ssh to
`tamforge-prod` as a release named `<UTC stamp>-<short sha>`.

On the host the deploy key is bound in `/root/.ssh/authorized_keys` to
`/opt/tamforge/bin/deploy-receive` with `restrict`, so it can only run that script. The
receiver (`infra/host/deploy-receive.sh`) validates the release id, unpacks the tar into
`/opt/tamforge/releases/<id>` and hands over to that release's own
`infra/host/release.sh`, which:

1. runs `uv sync --frozen --no-dev --project apps/backend` at the release root;
2. migrates as `tamforge_migrator` under `/run/tamforge/migrate.lock`;
3. switches `/opt/tamforge/current`, reinstalls the systemd units and the receiver,
   restarts `tamforge-api`, `tamforge-worker` and `tamforge-claude-worker`;
4. waits up to 30 s for `http://127.0.0.1:8000/readyz` to answer 200. If it does not, the
   `current` link moves back to the previous release and the job fails. The database is
   never downgraded;
5. keeps the last five releases so a rollback always has a target.

`/readyz` answering 200 with `{"status":"degraded"}` is the normal state.

Redeploy by hand, from a checkout with ssh access to the host:

```bash
release="$(date -u +%Y%m%dT%H%M%SZ)-$(git rev-parse --short=7 origin/main)"
git archive --format=tar origin/main \
  | ssh hetzner-server-2 "SSH_ORIGINAL_COMMAND=$release /opt/tamforge/bin/deploy-receive"
```

A personal key gets a shell, so the release id travels in the variable the forced
command would otherwise set.

or, already on the host with a release unpacked:

```bash
/opt/tamforge/releases/<id>/infra/host/release.sh /opt/tamforge/releases/<id>
```

Rotate the deploy key with a fresh pair, `gh secret set PROD_DEPLOY_KEY < key`, and replace
the `command="/opt/tamforge/bin/deploy-receive",restrict ...` line in `authorized_keys`.
The macOS DMG steps above stay manual.
