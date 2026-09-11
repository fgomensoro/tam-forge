# Backup and restore

## Policy

`tamforge_backend.operations.backup_policy.APPROVED`: a backup every day, encrypted with
AES-256-GCM before it leaves the host, versioned (every run is a new directory; nothing is
overwritten), rotated on 7 daily, 5 weekly and 12 monthly restore points. Rotation only
prunes under the dedicated backup prefix, never removes the newest valid point, and never
removes a point whose metadata it cannot verify. Backup rotation and learner-data
retention (`operations/retention.py`) share no numbers and no code path: archive and
deletion never prune a backup, and backup expiry never touches a canonical row.

A restore drill must run in a clean, non-production environment and meet two numbers:
RPO (age of the newest thing in the backup) at most 25 hours, RTO (time the restore took)
at most 60 minutes. Missing either fails the drill.

## Taking a backup

`infra/backup/encrypted.py` `backup()` dumps through an injected step (on the host:
`pg_dump -Fc` as the backup role), encrypts each payload with a 32-byte key that never
enters the manifest, writes ciphertext atomically, and publishes `manifest.json` last. The
manifest holds hashes, sizes, tool versions, the schema head and the names of configuration
keys, and is scanned for anything credential-shaped before it is written.

## Restore drill and evidence

`infra/backup/evidence.py` runs the whole loop against a local container:

```bash
uv run python -m infra.backup.evidence --source-container tfsuite-pg --backups-root ~/tamforge-backups --key-dir ~/.tamforge --evidence-out docs/project/backup-restore-drill-$(date -u +%Y%m%dT%H%M%SZ).json
```

It dumps as the container's own role, encrypts under a fresh key in `~/.tamforge/`,
verifies, restores into a throwaway `postgres:16` container with `--network none`, counts
the restored tables, removes the container, and writes the numbers. The committed evidence
carries the manifest hash, capture time, RPO, RTO, table count and verdict, never a row,
a value or the key.

## Verification

```bash
uv run pytest infra/tests/test_backup_scripts.py apps/backend/tests/unit/operations/test_backup_policy.py -q
```
