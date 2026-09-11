# Release checklist (plan 03)

`tamforge_backend.operations.release_checklist.evaluate(repo_root)` judges every item below
against the artifact it names. One unresolved required item refuses the release; there is no
override.

| Item | Area | Evidence | Judged by |
|---|---|---|---|
| native_app.dmg_and_signature | signing | `docs/project/signing-permission-persistence-v1.md` | codesign verify, DMG hash and persistence recorded |
| permissions.persist_across_builds | permissions | same | same |
| recording.runtime_window | recording | `docs/project/recording-verification-v1.json` | not the blocked template; every key passes on this head |
| learning.model_selection | learning | `docs/project/model-benchmark-v1.json` | `chosen_model` decided |
| learning.speech_performance_10m / 60m | learning | `docs/project/speech-performance-*.json` | transcription peak within the 1.5 GiB gate |
| learning.ai_evaluation_runbook | learning | `docs/runbooks/ai-evaluation.md` | present; the suite runs in CI |
| privacy.gastos_inventory_read_only | privacy | `docs/project/gastos-inventory-*.json` | `no_mutation_confirmed` |
| privacy.retention_runbook | privacy | `docs/runbooks/recording-upload-recovery.md` | present |
| recovery.backup_restore_drill | recovery | `docs/project/backup-restore-drill-*.json` | `met` |
| recovery.gastos_restore_drill | recovery | `docs/project/gastos-restore-drill-*.json` | `lamas_untouched` |
| recovery.host_provisioning_runbook | recovery | `docs/runbooks/host-provisioning.md` | present |
| version.tagged_exact_commit | version | `apps/macos/.release-tag` vs `MARKETING_VERSION` | `v<version>+<commit>` matches |

## State on 2026-09-11

Refused. Unresolved: `recording.runtime_window` (no 60-minute runtime window recorded on
this head; the committed report is the blocked template) and `version.tagged_exact_commit`
(no release tag). Everything else resolves, including the 60-minute transcription gate
after the spool read fix in PR 247/248.
