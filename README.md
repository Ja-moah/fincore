# FinCore Transaction Engine

FinCore is a backend engineering challenge that demonstrates how an internal
financial transfer differs from ordinary CRUD. A transfer is an atomic,
authorized, retry-safe state transition backed by double-entry ledger records,
database constraints, row locking, audit context, and failure tests.

## Live evaluator demo

- Transaction console: <https://fincore-clj7.onrender.com/>
- Service health: <https://fincore-clj7.onrender.com/health/>
- Swagger UI: <https://fincore-clj7.onrender.com/api/docs/>
- OpenAPI schema: <https://fincore-clj7.onrender.com/api/schema/>
- Django admin: <https://fincore-clj7.onrender.com/admin/>

This is a disposable challenge staging environment with the public fictional
credentials listed below. It must not be used for real money or personal data.

## Technology stack

- Python 3.14, Django, and Django REST Framework
- PostgreSQL 17 and psycopg
- Simple JWT authentication
- drf-spectacular OpenAPI/Swagger documentation
- Docker Compose, GNU Make, pytest, and GitHub Actions

## Core guarantees

- Every successful transfer creates one equal debit and credit.
- The ledger—not an account balance column—is financial truth.
- PostgreSQL transactions prevent partial movement during crashes.
- Ordered row locks prevent concurrent overspending.
- User-scoped idempotency provides at-most-once movement for retries.
- Authenticated ownership scopes transfer initiation and transaction reads.
- Database constraints enforce positive amounts and distinct accounts.

## Prerequisites

- Docker with Docker Compose v2
- GNU Make

## Quick start

```bash
cp .env.example .env
make bootstrap
```

The FinCore transaction console is available at <http://localhost:8000> after
bootstrap. Swagger is at <http://localhost:8000/api/docs/> and health status is
at <http://localhost:8000/health/>. Run `make help` for individual commands.

`make bootstrap` validates Compose configuration, builds and starts services,
applies migrations, creates deterministic demo data, and runs Django checks.

## Demo data

Run `make seed` at any time. The command is idempotent and creates fictional,
balanced demo history with these known roles, credentials, and account balances:

| Username | Password | Role | Account | Balance |
| --- | --- | --- | --- | ---: |
| `Admin` | `admin123` | Django administrator | `DEMO-GHS-ADMIN` | GHS 5,750.00 |
| `Justice` | `just123` | Standard user | `DEMO-GHS-JUSTICE` | GHS 2,650.00 |
| `Ama` | `ama123` | Standard user | `DEMO-GHS-AMA` | GHS 1,250.00 |
| `Kojo` | `kojo123` | Standard user | `DEMO-GHS-KOJO` | GHS 850.00 |

`Admin` may use both the transaction console and `/admin/`; all other listed
users are ordinary non-staff users. The internal `demo_treasury` account cannot
log in. These predictable credentials are only for the public challenge staging
demo and must never be reused for a real system or live-money environment.

The Render startup script runs this idempotent seed after migrations by default,
so a fresh hosted database is immediately testable. Set
`SEED_DEMO_ON_START=false` for any environment that should not contain the demo.

## Architecture documentation

- [Architecture and sequence diagrams](docs/architecture.md)
- [Database and ER diagram](docs/database.md)
- [Deployment guide](docs/deployment.md)
- [Failure scenarios and executable evidence](docs/failure-scenarios.md)
- [Security review](docs/security.md)
- [Technical decisions](docs/technical-decisions.md)

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
| GET | `/` | Interactive transaction console |
| GET/POST | `/admin/` | Django administration for the demo administrator |
| POST | `/api/v1/auth/token/` | Obtain access and refresh tokens |
| POST | `/api/v1/auth/token/refresh/` | Refresh an access token |
| POST | `/api/v1/transfers/` | Create or replay an internal transfer |
| GET | `/api/v1/accounts/me/` | Read the authenticated user's account |
| GET | `/api/v1/accounts/me/balance/` | Read the ledger-derived balance |
| GET | `/api/v1/transactions/` | Paginated transaction history, newest first |
| GET | `/api/v1/transactions/{uuid}/` | Authorized transaction detail |
| GET | `/health/` | Application and database health |
| GET | `/api/schema/` | OpenAPI schema |
| GET | `/api/docs/` | Swagger UI |

Swagger documents JWT authentication, request and response bodies, error
responses, and the required `Idempotency-Key` header. Use the **Authorize**
control with a valid access token to call protected endpoints.

## Transaction console

The root route provides a responsive demo interface over the existing API. It
supports demo-user login, ledger-derived balances, transfers, explicit
idempotent retries, insufficient-funds demonstrations, transaction history,
service health, and a visible request trail. JWTs are retained only in browser
session storage and cleared when the tab session ends or the user signs out.

The console contains no financial business rules. It sends requests to the same
documented endpoints as any other client, and it renders API results without
using client input as trusted financial state.

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

## Testing and CI

```bash
make check       # Django system checks
make test        # complete pytest suite against PostgreSQL
make coverage    # branch and line coverage with missing lines
```

CI runs on every push and pull request with a PostgreSQL 17 service. It installs
pinned dependencies, runs Django checks, rejects migration drift, applies all
migrations, validates OpenAPI, and executes the complete suite.

The current complete suite contains 57 passing tests, including real PostgreSQL
concurrency coverage for overspending and duplicate idempotent requests.

The highest-value evidence is indexed in
[docs/failure-scenarios.md](docs/failure-scenarios.md), including real concurrent
PostgreSQL tests for duplicate requests and overspending.

## Known limitations

FinCore has no deposit/opening-balance product workflow, reversal workflow,
reconciliation engine, idempotency cleanup job, multi-account API selection,
external payment rail, rate limiting, fraud engine, database HA/PITR setup, or
durable external audit sink. The demo treasury allocator is development-only.

## Biggest technical risk

The biggest risk is preserving ledger correctness as new money-moving paths and
operational failure modes are introduced. Current controls—one PostgreSQL ACID
boundary, deterministic row locking, double-entry construction, balancing
checks, database constraints, idempotency uniqueness, rollback tests, and real
concurrency tests—protect the implemented internal transfer path.

I would address growth risk with centralized posting primitives, mandatory
reconciliation, database-level monitoring for invariant violations, a
transactional outbox for external effects, independent ledger audit tooling,
strict code review around lock ordering, and database backup/restore drills.

## If I had another 72 hours, I would…

Build explicit reversal and reconciliation workflows first, then add a
transactional outbox and tamper-resistant audit sink. I would add production
secret management, rate limiting, fraud/risk controls, richer observability,
database high availability and point-in-time recovery, dependency/container
scanning, and restore/load testing before integrating any external payment
provider. These are future improvements, not capabilities claimed here.
