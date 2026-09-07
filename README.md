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
reversals, and durable external audit delivery.

## API authentication and authorization

The API uses standard JWT access and refresh tokens from Simple JWT. Obtain a
token pair with `POST /api/v1/auth/token/` using a Django username and password,
then send the access token as `Authorization: Bearer <token>`. Refresh access
tokens with `POST /api/v1/auth/token/refresh/`.

The authenticated user determines the sender account; the transfer request has
no trusted sender field. This API milestone requires exactly one account per
user and returns `ACCOUNT_SELECTION_REQUIRED` for ambiguous multi-account
users. Transaction list and detail querysets include only transactions where
one of the user's accounts is sender or recipient. An unrelated transaction is
returned as `404`, avoiding disclosure that its identifier exists.

### Endpoints

| Method | Path | Purpose |
| --- | --- | --- |
| POST | `/api/v1/auth/token/` | Obtain access and refresh tokens |
| POST | `/api/v1/auth/token/refresh/` | Refresh an access token |
| POST | `/api/v1/transfers/` | Create or replay an internal transfer |
| GET | `/api/v1/accounts/me/` | Read the authenticated user's account |
| GET | `/api/v1/accounts/me/balance/` | Read the ledger-derived balance |
| GET | `/api/v1/transactions/` | Paginated transaction history, newest first |
| GET | `/api/v1/transactions/{uuid}/` | Authorized transaction detail |
| GET | `/api/schema/` | OpenAPI schema |
| GET | `/api/docs/` | Swagger UI |

Swagger documents JWT authentication, request and response bodies, error
responses, and the required `Idempotency-Key` header. Use the **Authorize**
control with a valid access token to call protected endpoints.

### Transfer example

```http
POST /api/v1/transfers/
Authorization: Bearer <access-token>
Idempotency-Key: ABC123
Content-Type: application/json

{
  "recipient_account": "GH0000000002",
  "amount": "250.00",
  "currency": "GHS"
}
```

```json
{
  "id": "e1c8d333-a4d7-40c6-bbb0-f7dcfeff6f9c",
  "status": "SUCCEEDED",
  "amount": "250.00",
  "currency": "GHS",
  "sender_account": "GH0000000001",
  "recipient_account": "GH0000000002",
  "created_at": "2026-09-07T12:00:00Z"
}
```

Stable error codes include `AUTHENTICATION_REQUIRED`,
`INVALID_AUTHENTICATION`, `INVALID_AMOUNT`, `INSUFFICIENT_FUNDS`,
`ACCOUNT_UNAVAILABLE`, `CURRENCY_MISMATCH`, `IDEMPOTENCY_KEY_REQUIRED`, and
`IDEMPOTENCY_CONFLICT`.

### Idempotency and retry semantics

An idempotency key is scoped to the authenticated user. Its SHA-256 fingerprint
contains the normalized sender, recipient, two-decimal amount, and currency.
The key record and financial transfer commit in one outer database transaction.

If the same request arrives twice sequentially, the stored status and response
body are returned and no transfer logic runs again. If the payload differs, the
API returns `409 IDEMPOTENCY_CONFLICT`. If two duplicates arrive concurrently,
both race to insert the same database-unique `(user, key)` pair. PostgreSQL
blocks the competing insert until the winner commits; the loser then locks and
replays the completed record. This provides at-most-once financial movement
without an unsafe check-then-insert race.

If validation or the transfer fails before commit, the idempotency record rolls
back too, so the same key may be retried. If the transfer commits but the HTTP
response is lost, retrying returns the stored successful response. Expiry is
recorded by the model but keys remain reserved until an explicit retention job
deletes them; no cleanup job is implemented yet.

Run `make help` for the complete command list. The default setup is intended
for local development only; change `SECRET_KEY`, disable `DEBUG`, and configure
production host and deployment settings before using it outside a development
machine.
