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
