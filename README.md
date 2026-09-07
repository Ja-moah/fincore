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

## Financial data model

Account balances are not stored as mutable fields. The ledger is the
authoritative financial record, and balances are derived by adding credits and
subtracting debits. This avoids two independently mutable representations of
the same financial truth.

Transactions and ledger entries are protected from accidental cascading
deletion. Idempotency keys are unique per user and may carry an explicit expiry
timestamp; a production retention process must account for dispute, audit, and
replay-safety requirements before deleting expired records.

Audit events are append-only by application convention. A production system
with stronger compliance requirements would also need restricted database
permissions and tamper-evident or externally anchored audit storage.

Run `make help` for the complete command list. The default setup is intended
for local development only; change `SECRET_KEY`, disable `DEBUG`, and configure
production host and deployment settings before using it outside a development
machine.
