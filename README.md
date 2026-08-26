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

The optional `compose.dev.yml` provides local PostgreSQL/pgvector and MinIO
services for later integration work. It is never started by the default Make
targets.
