# R2 Sealed Checkpoints and Startup Origin Plan

Spec: `docs/superpowers/specs/2026-09-01-r2-sealed-checkpoints-startup-origin.md`

1. Sealed checkpoint regressions
   - Add tests for aligned last-record removal, whole-track removal, and corrupt ciphertext with matching checkpoint.
   - Add schema-3 per-track checkpoints at seal and exact comparison during recovery.
   - Deferred verification: focused recording tests in parent batch.

2. Two-track startup regressions
   - Add tests for system-first/later-earlier microphone replay, one-track bound failure, and one-track finish failure.
   - Add bounded startup input gate and explicit timeline origin initialization.
   - Deferred verification: focused recording tests in parent batch.

3. Coordinator fail-closed regression
   - Add test proving `requiredTracksMissing` never seals and remains recoverable.
   - Track fatal capture coverage failure through stop/failure finalization.
   - Deferred verification: focused recording tests in parent batch.

4. Static closeout
   - Run `swiftc -frontend -parse`, `git diff --check`, and manual diff inspection only.
   - Commit amendment and report exact HEAD plus deferred runtime risk.
