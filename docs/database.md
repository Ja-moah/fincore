# Database design

```mermaid
erDiagram
    USER ||--o{ ACCOUNT : owns
    USER ||--o{ IDEMPOTENCY_RECORD : scopes
    USER o|--o{ AUDIT_EVENT : acts
    ACCOUNT ||--o{ TRANSACTION : sends
    ACCOUNT ||--o{ TRANSACTION : receives
    TRANSACTION ||--o{ LEDGER_ENTRY : posts
    ACCOUNT ||--o{ LEDGER_ENTRY : records
    TRANSACTION o|--o{ IDEMPOTENCY_RECORD : fulfills

    USER {
        int id PK
        string username UK
    }
    ACCOUNT {
        bigint id PK
        int user_id FK
        string account_number UK
        string currency
        string status
    }
    TRANSACTION {
        uuid id PK
        bigint sender_id FK
        bigint recipient_id FK
        decimal amount
        string currency
        string status
    }
    LEDGER_ENTRY {
        bigint id PK
        uuid transaction_id FK
        bigint account_id FK
        string entry_type
        decimal amount
        string currency
    }
    IDEMPOTENCY_RECORD {
        bigint id PK
        int user_id FK
        string key
        string request_fingerprint
        uuid transaction_id FK
        json response_body
    }
    AUDIT_EVENT {
        bigint id PK
        int actor_id FK
        uuid request_id
        string action
        string resource_type
        string resource_id
        json metadata
    }
```

## Invariants and deletion policy

- Money uses `numeric(19,2)` through Django `DecimalField`; floats are rejected.
- Transaction and ledger amounts have positive database check constraints.
- A transaction has distinct sender and recipient accounts by database check.
- `(user_id, idempotency_key)` is unique and arbitrates concurrent duplicates.
- Financial foreign keys use `PROTECT`; parent deletion does not cascade history.
- Account balance is not stored. It is credit totals minus debit totals for one
  currency, calculated from ledger entries.

The transfer service creates exactly one debit and one credit for an internal
transfer and checks that their signed sum is zero. Cross-row balance is enforced
by the atomic service because a conventional row-level check constraint cannot
validate a pair of rows. Production reconciliation should independently scan
for missing or unbalanced postings.

The demo bootstrap uses deterministic, balanced treasury allocations because a
production opening-balance/deposit workflow is outside the challenge scope.

