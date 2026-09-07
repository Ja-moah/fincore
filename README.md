# FinCore Transaction Engine

FinCore is a Django/PostgreSQL backend challenge focused on building safe
financial transfers. The repository is currently at the development-environment
milestone; the financial domain and transfer API are not implemented yet.

## Prerequisites

- Docker with Docker Compose v2
- GNU Make

## Quick start

```bash
cp .env.example .env
make build
make up
make migrate
make check
make test
```

The Django development server is available at <http://localhost:8000> after
`make up`.

Run `make help` for the complete command list. The default setup is intended
for local development only; change `SECRET_KEY`, disable `DEBUG`, and configure
production host and deployment settings before using it outside a development
machine.
