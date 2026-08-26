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
