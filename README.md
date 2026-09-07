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

## Internal transfer engine

Internal transfers are application-service operations, not model CRUD. The
service opens a PostgreSQL transaction and locks the sender and recipient
account rows in ascending primary-key order. It then reads the sender's balance
from the ledger while those locks are held. Consistent lock ordering reduces
deadlock risk when transfers touch the same accounts.

A valid transfer progresses through `PENDING`, `PROCESSING`, and `SUCCEEDED`
inside one database transaction. Only the final state becomes externally
visible. Requests rejected before financial movement—such as insufficient
funds, invalid amounts, unavailable accounts, or currency mismatches—do not
create misleading failed transaction rows. A frozen account cannot send but
may receive; a closed account can do neither.

Every successful transfer creates exactly two entries linked to the same
transaction: a sender debit and a recipient credit with equal amounts and
currency. The service checks that their signed sum is zero before committing.
The success audit event is committed atomically with those entries.

### Simultaneous transfers and failures

If two transfers try to spend the same funds simultaneously, both must acquire
the sender's row lock. PostgreSQL serializes them: the second transfer reads the
ledger only after the first commits, so it sees the new lower balance and fails
if funds are no longer sufficient.

If the process raises an exception or the server connection fails before the
database commit, PostgreSQL rolls back the transaction row, ledger entries, and
success audit event. No partial debit or credit remains. Because an audit event
written inside the failed transaction also rolls back, this database audit log
does not claim to durably record aborted attempts. Production-grade failed
attempt telemetry would require an external or tamper-resistant audit channel
with carefully defined delivery guarantees.

Known limitations include the absence of an opening-balance/funding workflow,
reversals, idempotent request handling, HTTP endpoints, and durable external
audit delivery. Those concerns are intentionally outside this milestone.

Run `make help` for the complete command list. The default setup is intended
for local development only; change `SECRET_KEY`, disable `DEBUG`, and configure
production host and deployment settings before using it outside a development
machine.
