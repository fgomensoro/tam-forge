# TAM Forge

TAM Forge is a private, single-user learning workspace for Technical Account
Manager interview practice.

## Local development

Install the toolchains and workspace dependencies:

```bash
make install
```

Run the default unit checks (Docker is not required):

```bash
make check
```

The optional `compose.dev.yml` provides local PostgreSQL/pgvector and a pinned
MinIO release for later local integration work. It is never started by the
default Make targets and is not a production deployment configuration.

## GitHub planning catalog

The approved milestones, labels, epics, and child issues are declared in
`docs/project/github-issues.yml`. Previewing the catalog is safe and is the
default behavior:

```bash
uv run python scripts/github/sync_issues.py \
  --repo fgomensoro/tam-forge \
  --manifest docs/project/github-issues.yml \
  --dry-run
```

Before `origin` points to the private target repository, that command plans
against an offline empty state and does not invoke GitHub. Once the verified
private remote is configured, it reads all open and closed planning records.

Applying is an external write and must only happen after separately confirming
the authenticated GitHub account, immutable owner ID, and private personal
repository:

```bash
uv run python scripts/github/sync_issues.py \
  --repo fgomensoro/tam-forge \
  --manifest docs/project/github-issues.yml \
  --apply
```

Apply never deletes or closes issues, never reopens closed managed issues, and
never removes unrelated labels. Re-run the dry-run after an apply; it should
report zero planned creates or updates.
