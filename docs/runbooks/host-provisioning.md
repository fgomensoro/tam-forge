# Host provisioning

The post-Gastos TAM Forge host is provisioned from a checked contract, through a plan that
prints by default and writes only through a checkpoint. Nothing here runs against the
host until the decommission gate in `docs/runbooks/gastos-restore.md` has been executed
and a fresh approval exists for provisioning; earlier approvals do not carry over.

## The contract

`infra/config/host-layout.env` holds no secrets: Ubuntu release and architecture, the
approved host name and address, the public ports (exactly 22, 80, 443), the loopback-only
ports (PostgreSQL, the API), pinned packages, the six `tamforge-*` service users and the
shared group, per-service memory budgets, and the directory layout. `infra/host/contract.py`
refuses a contract whose budgets plus a 1 GB reserve for PostgreSQL, Caddy and the OS do
not fit the machine, that opens any other port, or that runs anything as root.

## The gate

`infra/host/provision.py` reads `/etc/os-release`, `uname -m`, `/etc/hostname` and
`docker ps` from the target and refuses unless the host is Ubuntu 24.04 on x86_64, is named
`tamforge-prod`, runs no n8n, NocoDB or gapfiller container, and is not `lamas-prod` or
`n8n-prod-gastos`.

## The plan

`plan(contract)` is the complete ordered list of writes: pinned packages, the shared
group and locked no-login users, every directory with its exact owner and mode
(`/etc/tamforge/secrets` is `root:root 0700`; shared data is setgid `2770`), PostgreSQL
bound to loopback with the `tamforge` database and three least-privilege roles, the
firewall with SSH allowed before anything is denied and the loopback ports denied
externally, then `systemd-analyze verify` before `daemon-reload`. Every step carries a
read-only probe that says whether it is already done, so a second apply changes nothing,
an interrupted apply resumes from its checkpoint, and rollback disables the TAM Forge
units and restores the captured firewall state without removing packages, PostgreSQL data,
the Gastos archive, or anything on another host.

## Units and edge

`infra/systemd/tamforge-*.service` run the API and the general, speech, Claude and
embedding workers as their own users with `NoNewPrivileges`, `PrivateTmp`,
`ProtectSystem=strict`, empty capability sets, `MemoryMax` from the contract, `TasksMax`,
`LimitNOFILE`, bounded restarts and journald rate limits. Credentials are per service
through `LoadCredential`: only the general worker gets the export private key, only the
speech worker gets the recording-manifest keyring, only the Claude worker gets the token;
the API and the general worker get the public trust bundle. No unit `Requires=` Claude or
speech, so ingest and study stay up when those are degraded.

`infra/caddy/Caddyfile` terminates TLS, proxies to `127.0.0.1:8000` with streaming
timeouts for recordings and events, sets security headers, drops cookies and signed URL
values from logs, and answers 404 for operational routes.

## Releases

`infra/host/deploy.py`: preflight (release id, host binding, checksum, free disk, one
Alembic head, PostgreSQL answering), install (unpack into its own directory, migrate once
under a lock as `tamforge_migrator`, switch `current` atomically, restart units), verify
(owner, auth, ingest and job endpoints must answer), rollback (previous release by pointer;
the database is never downgraded).

## Verification

```bash
uv run pytest infra/tests/test_host_provisioning.py infra/tests/test_systemd_units.py infra/tests/test_deploy_scripts.py -q
```

Fixture-only: fake commands, a fixture `/etc`, temporary directories. No apt, systemctl,
ufw, PostgreSQL, Caddy, Docker or network.
