# Technical decisions

## Ledger-derived balances

The ledger is the only financial source of truth. A mutable balance column would
create a second value that could diverge during failures. The tradeoff is that
balance queries grow with ledger history; production options include verified
snapshots or cached projections that can always be reconciled to the ledger.

## Database row locking

Transfers lock both accounts in primary-key order before reading balance. This
serializes conflicting spends and reduces deadlock risk. Correctness assumes all
money-moving paths follow the same locking protocol.

## Atomic idempotency

The user/key record is inserted in the same transaction as the transfer. Its
unique constraint is the concurrency arbiter. Failed attempts roll back the key;
committed attempts retain the response for safe replay. Expiry is modeled but no
retention job is implemented because deleting keys is a business/risk decision.

## One deployable application

A modular Django monolith and PostgreSQL keep the financial commit local. Redis,
Kafka, Celery, and microservices were omitted because they would introduce
distributed-state failure modes without a requirement for asynchronous scale.

## Failed transaction records

Requests rejected before movement do not create `FAILED` transaction rows.
Unexpected mid-transfer failures roll back the pending row. Operational logs can
record rejected attempts, while the database audit table records committed
outcomes. A future attempt ledger/outbox should be designed separately rather
than implying that rolled-back audit writes are durable.

## Primary account API policy

The data model permits multiple accounts per user, but the challenge request
shape intentionally omits a sender identifier. The API therefore requires one
account and rejects ambiguous users instead of silently choosing. A future API
would use an authorized account-scoped route or explicit account selector.

