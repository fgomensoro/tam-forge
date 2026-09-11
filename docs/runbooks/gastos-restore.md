# Gastos archive and restore

The Gastos stack on `hetzner-server-2` (hostname `n8n-prod-gastos`) is archived with
`infra/gastos/archive.py`. The archive is a directory of AES-256-GCM ciphertexts plus a
`manifest.json`; the key is a separate 32-byte file that is never written into the
repository or the archive. Nothing here needs the source host once the archive exists.

## What the archive holds

| Payload | Produced by | Restores |
|---|---|---|
| `postgres/n8n.dump`, `postgres/leadgen.dump`, `postgres/postgres.dump` | `pg_dump -Fc` inside `n8n-postgres-1` | each database, PostgreSQL 16 custom format |
| `postgres/globals.sql` | `pg_dumpall --globals-only` | roles and their password hashes |
| `volumes/n8n_n8n_data.tar` | `tar -C /home/node/.n8n` inside `n8n-n8n-1` | n8n workflows, credentials store, settings |
| `volumes/n8n_nocodb_data.tar` | `tar -C /usr/app/data` inside `n8n-nocodb-1` | NocoDB metadata |
| `volumes/n8n_caddy_data.tar`, `volumes/n8n_caddy_config.tar` | `tar` inside `n8n-caddy-1` | TLS certificates and Caddy state |
| `config/n8n/docker-compose.yml`, `config/n8n/Caddyfile`, `config/n8n/.env` | `cat` on the host | the compose project, including `N8N_ENCRYPTION_KEY` and the database password |
| `config/gapfiller-bridge/source.tar` | `tar -C /root/gapfiller-bridge` | the bridge's compose file and source |
| `config/containers.json` | `docker inspect` | image digests, mounts and environment of every container |

Every command is a read. `assert_read_only` screens the list against the inventory's
mutating-token list and an allowlist of command prefixes before the first SSH call, and
the hostname is checked against `n8n-prod-gastos` first; `lamas-prod` is refused by name.

## Creating an archive

```bash
uv run python -m infra.gastos.archive create ~/tamforge-gastos-archive/gastos-archive-$(date -u +%Y%m%dT%H%M%SZ) --key-out ~/.tamforge/gastos-archive-$(date -u +%Y%m%dT%H%M%SZ).key
```

One Bitwarden SSH approval covers the whole run (the connection is multiplexed). Then:

1. Verify it, with the key, so the plaintext hashes are proven and not only recorded:

   ```bash
   uv run python -m infra.gastos.archive verify ~/tamforge-gastos-archive/<archive> --key ~/.tamforge/<key>
   ```

2. Put the key file in Bitwarden as an attachment on the `hetzner-server-2` item and keep
   the archive directory on at least one other disk. The manifest alone cannot restore
   anything; the key alone cannot either.
3. Commit a copy of `manifest.json` under `docs/project/gastos-archive-<stamp>.manifest.json`.
   It holds names, sizes, hashes, nonces and commands, and no payload content.

## Proving the archive restores (the drill)

`infra/gastos/restore_drill.py` is the automated version of the section below, and the
evidence the decommission gate asks for. It verifies the archive with the key, decrypts
into a private temporary directory, starts a throwaway PostgreSQL 16 container with
`--network none`, loads the roles and both databases from the dumps, reads back table and
row counts and the n8n workflow inventory, integrity-checks the NocoDB SQLite file, lets
Caddy validate the Caddyfile (in a network-less container when the `caddy:2` image is
present, otherwise with a local `caddy` binary), checks every variable the compose file
references exists in the restored `.env` by name, then removes the container and the
plaintext directory.

```bash
uv run python -m infra.gastos.restore_drill ~/tamforge-gastos-archive/<archive> --key ~/.tamforge/<key> --evidence-out docs/project/gastos-restore-drill-$(date -u +%Y%m%dT%H%M%SZ).json
```

Every Docker command passes through one gate that refuses anything not addressed to a
`gastos-restore-*` container, any network or published port, the Docker socket, and any
mention of the production containers, the Hetzner host, or Lamas. The drill has no SSH
runner: it cannot reach the host even by mistake. The evidence names the archive by the
SHA-256 of its manifest, records counts only (never rows), and redacts the throwaway
database password and the working directory from the command log.

First drill, 2026-09-11: `docs/project/gastos-restore-drill-20260911T022228Z.json`, archive
`20260911T013332Z`, PostgreSQL 16.15, 3 roles, `n8n` 51 tables (8 workflows, 9 credentials,
36 executions), `leadgen` 2 tables (770 leads, 8 searches), NocoDB SQLite integrity ok with
132 tables, Caddyfile valid, all 6 referenced environment keys present.

## Restoring without the source host

Requirements: Docker, the archive directory, the key file. No network access to Hetzner.

1. Decrypt every payload after a full verification:

   ```bash
   uv run python -m infra.gastos.archive restore <archive> --key <key> --into ./gastos-restore
   ```

2. Start PostgreSQL 16 in isolation and load roles and databases:

   ```bash
   docker run -d --name gastos-restore-pg -e POSTGRES_PASSWORD=restore -p 127.0.0.1:55432:5432 postgres:16
   docker cp gastos-restore/postgres gastos-restore-pg:/restore
   docker exec gastos-restore-pg psql -U postgres -f /restore/globals.sql
   for db in n8n leadgen; do
     docker exec gastos-restore-pg createdb -U postgres "$db"
     docker exec gastos-restore-pg pg_restore -U postgres -d "$db" --no-owner "/restore/$db.dump"
   done
   ```

   `postgres.dump` is the maintenance database and normally needs no restore.

3. Recreate the named volumes from the tar streams:

   ```bash
   for v in n8n_n8n_data n8n_nocodb_data n8n_caddy_data n8n_caddy_config; do
     docker volume create "$v"
     docker run --rm -v "$v":/target -v "$PWD/gastos-restore/volumes":/src alpine sh -c "tar -C /target -xf /src/$v.tar"
   done
   ```

4. Bring the stack up from the restored compose project (`gastos-restore/config/n8n`), with
   `.env` restored beside it. The `N8N_ENCRYPTION_KEY` in that file is what makes the
   restored n8n credentials readable; without it the workflows load and the credentials do
   not. Change the DNS-facing Caddyfile hostnames before starting Caddy if the restore must
   not answer for the production names.

5. Check: `n8n` lists the expected workflows, NocoDB opens its bases, and the row counts of
   the restored databases match the sizes in the inventory artifact for the same date.

## Retiring the stack (the decommission gate)

`infra/gastos/decommission.py` is a plan by default. Without `--execute` it prints the
fixed target list (the two compose projects, five containers, five volumes, two
directories and the DNS name), the commands it would run, and exits having run nothing
on the host. The list lives in the file; nothing is discovered on the host at run time
and no glob is accepted.

```bash
uv run python -m infra.gastos.decommission --archive ~/tamforge-gastos-archive/<archive> --key ~/.tamforge/<key> --drill-evidence docs/project/gastos-restore-drill-<stamp>.json
```

Execution needs all of the following, checked in order, and any one missing is a
refusal with the reason printed:

1. The resolved hostname is `n8n-prod-gastos`; `lamas-prod` is refused by name.
2. The archive verifies with its key.
3. The restore drill evidence names the same manifest hash and shows a successful,
   host-untouched restore.
4. A separately written approval artifact names that manifest hash and the exact
   target digest printed by the plan, was written after the drill, has not expired, and
   lasts at most 24 hours:

   ```json
   {
     "archive_manifest_sha256": "<from the plan>",
     "target_digest": "<from the plan>",
     "approved_at": "2026-09-12T10:00:00+00:00",
     "expires_at": "2026-09-12T18:00:00+00:00",
     "approved_by": "frank"
   }
   ```

5. `--execute` on the command line.

Even then, the plan runs `docker compose down` for each project and `docker volume rm`
for each named volume, in order, stopping at the first failure. It does not rename the
server, change DNS, or rebuild anything; those are later, separately gated steps.
