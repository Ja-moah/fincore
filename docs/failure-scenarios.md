# Failure scenarios and evidence

These scenarios are executable tests against PostgreSQL, not source-code checks
or mocked database locks.

| Scenario | Expected result | Evidence |
| --- | --- | --- |
| Same key and payload retried | Original response; one movement | `test_exact_retry_returns_original_result_without_duplicate_movement` |
| Same key, different payload | `409 IDEMPOTENCY_CONFLICT` | `test_same_key_with_different_payload_returns_conflict` |
| Concurrent duplicate requests | One transaction and two entries | `test_concurrent_duplicate_requests_create_one_movement` |
| Two GHS 400 spends from GHS 500 | One success, one insufficient-funds failure, GHS 100 remains | `test_concurrent_transfers_cannot_overspend` |
| Exception after debit creation | Transaction and all entries roll back | `test_mid_transfer_exception_rolls_back_everything` |
| Unrelated transaction detail | `404` without resource disclosure | `test_transaction_detail_is_visible_to_sender_and_recipient_only` |
| Insufficient funds | No transaction, ledger, idempotency, or audit mutation | `test_insufficient_funds_creates_no_financial_records` and API equivalent |

## Crash boundaries

Before commit, a process crash or lost database connection causes PostgreSQL to
roll back the transaction. After commit, the ledger movement and stored
idempotent response both exist, so a client retry returns the original result.
There is no interval where a committed debit exists without its matching credit.

Database audit events share the financial transaction and therefore roll back
with it. They are evidence of committed outcomes, not a durable record of every
attempt. An external audit sink would require a transactional outbox or another
delivery design that explicitly handles duplicates and failures.

