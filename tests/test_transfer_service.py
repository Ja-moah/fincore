import threading
import time
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.db import close_old_connections, connection

from accounts.models import Account, Currency
from audit.models import AuditEvent
from ledger.models import LedgerEntry
from ledger.services import calculate_balance
from transactions import services as transfer_services
from transactions.models import Transaction
from transactions.services import (
    AccountNotFoundError,
    AccountUnavailableError,
    CurrencyMismatchError,
    InsufficientFundsError,
    InvalidTransferError,
    transfer_funds,
)


pytestmark = pytest.mark.django_db


@pytest.fixture
def transfer_accounts():
    user_model = get_user_model()
    treasury_user = user_model.objects.create_user(username="treasury")
    sender_user = user_model.objects.create_user(username="transfer-sender")
    recipient_user = user_model.objects.create_user(username="transfer-recipient")
    other_recipient_user = user_model.objects.create_user(username="other-recipient")
    return {
        "treasury": Account.objects.create(
            user=treasury_user, account_number="GH-TREASURY"
        ),
        "sender": Account.objects.create(
            user=sender_user, account_number="GH-SENDER"
        ),
        "recipient": Account.objects.create(
            user=recipient_user, account_number="GH-RECIPIENT"
        ),
        "other_recipient": Account.objects.create(
            user=other_recipient_user, account_number="GH-OTHER-RECIPIENT"
        ),
    }


def fund_account(treasury, account, amount=Decimal("500.00")):
    funding = Transaction.objects.create(
        sender=treasury,
        recipient=account,
        amount=amount,
        currency=Currency.GHS,
        status=Transaction.Status.SUCCEEDED,
    )
    LedgerEntry.objects.create(
        transaction=funding,
        account=treasury,
        entry_type=LedgerEntry.EntryType.DEBIT,
        amount=amount,
        currency=Currency.GHS,
    )
    LedgerEntry.objects.create(
        transaction=funding,
        account=account,
        entry_type=LedgerEntry.EntryType.CREDIT,
        amount=amount,
        currency=Currency.GHS,
    )
    return funding


def test_successful_transfer_is_balanced_and_audited(transfer_accounts):
    sender = transfer_accounts["sender"]
    recipient = transfer_accounts["recipient"]
    fund_account(transfer_accounts["treasury"], sender)

    result = transfer_funds(
        sender_id=sender.pk,
        recipient_id=recipient.pk,
        amount=Decimal("125.25"),
        currency=Currency.GHS,
    )

    result.refresh_from_db()
    entries = list(result.ledger_entries.order_by("entry_type"))
    debit = next(entry for entry in entries if entry.entry_type == "DEBIT")
    credit = next(entry for entry in entries if entry.entry_type == "CREDIT")

    assert result.status == Transaction.Status.SUCCEEDED
    assert len(entries) == 2
    assert debit.account == sender
    assert debit.amount == Decimal("125.25")
    assert credit.account == recipient
    assert credit.amount == Decimal("125.25")
    assert debit.signed_amount + credit.signed_amount == Decimal("0.00")
    assert calculate_balance(sender) == Decimal("374.75")
    assert calculate_balance(recipient) == Decimal("125.25")

    audit_event = AuditEvent.objects.get(
        action="transfer.succeeded", resource_id=str(result.id)
    )
    assert audit_event.actor == sender.user
    assert audit_event.metadata["result"] == "succeeded"
    assert audit_event.metadata["amount"] == "125.25"


def test_insufficient_funds_creates_no_financial_records(transfer_accounts):
    sender = transfer_accounts["sender"]
    recipient = transfer_accounts["recipient"]
    fund_account(transfer_accounts["treasury"], sender, Decimal("50.00"))
    transaction_count = Transaction.objects.count()
    ledger_count = LedgerEntry.objects.count()

    with pytest.raises(InsufficientFundsError):
        transfer_funds(
            sender_id=sender.pk,
            recipient_id=recipient.pk,
            amount=Decimal("50.01"),
            currency=Currency.GHS,
        )

    assert Transaction.objects.count() == transaction_count
    assert LedgerEntry.objects.count() == ledger_count
    assert AuditEvent.objects.count() == 0


@pytest.mark.parametrize("amount", [Decimal("0.00"), Decimal("-1.00")])
def test_non_positive_amount_is_rejected(transfer_accounts, amount):
    with pytest.raises(InvalidTransferError):
        transfer_funds(
            sender_id=transfer_accounts["sender"].pk,
            recipient_id=transfer_accounts["recipient"].pk,
            amount=amount,
            currency=Currency.GHS,
        )


def test_non_decimal_amount_is_rejected(transfer_accounts):
    with pytest.raises(InvalidTransferError):
        transfer_funds(
            sender_id=transfer_accounts["sender"].pk,
            recipient_id=transfer_accounts["recipient"].pk,
            amount=10.0,
            currency=Currency.GHS,
        )


def test_self_transfer_is_rejected(transfer_accounts):
    sender = transfer_accounts["sender"]

    with pytest.raises(InvalidTransferError):
        transfer_funds(
            sender_id=sender.pk,
            recipient_id=sender.pk,
            amount=Decimal("1.00"),
            currency=Currency.GHS,
        )


@pytest.mark.parametrize("status", [Account.Status.FROZEN, Account.Status.CLOSED])
def test_unavailable_sender_is_rejected(transfer_accounts, status):
    sender = transfer_accounts["sender"]
    sender.status = status
    sender.save(update_fields=["status", "updated_at"])

    with pytest.raises(AccountUnavailableError):
        transfer_funds(
            sender_id=sender.pk,
            recipient_id=transfer_accounts["recipient"].pk,
            amount=Decimal("1.00"),
            currency=Currency.GHS,
        )


def test_closed_recipient_is_rejected(transfer_accounts):
    recipient = transfer_accounts["recipient"]
    recipient.status = Account.Status.CLOSED
    recipient.save(update_fields=["status", "updated_at"])

    with pytest.raises(AccountUnavailableError):
        transfer_funds(
            sender_id=transfer_accounts["sender"].pk,
            recipient_id=recipient.pk,
            amount=Decimal("1.00"),
            currency=Currency.GHS,
        )


def test_frozen_recipient_may_receive(transfer_accounts):
    sender = transfer_accounts["sender"]
    recipient = transfer_accounts["recipient"]
    recipient.status = Account.Status.FROZEN
    recipient.save(update_fields=["status", "updated_at"])
    fund_account(transfer_accounts["treasury"], sender)

    result = transfer_funds(
        sender_id=sender.pk,
        recipient_id=recipient.pk,
        amount=Decimal("1.00"),
        currency=Currency.GHS,
    )

    assert result.status == Transaction.Status.SUCCEEDED


def test_currency_mismatch_is_rejected(transfer_accounts):
    with pytest.raises(CurrencyMismatchError):
        transfer_funds(
            sender_id=transfer_accounts["sender"].pk,
            recipient_id=transfer_accounts["recipient"].pk,
            amount=Decimal("1.00"),
            currency="USD",
        )


@pytest.mark.parametrize("missing_party", ["sender", "recipient"])
def test_missing_account_is_reported_as_domain_error(transfer_accounts, missing_party):
    sender_id = transfer_accounts["sender"].pk
    recipient_id = transfer_accounts["recipient"].pk
    if missing_party == "sender":
        sender_id = 999_999
    else:
        recipient_id = 999_999

    with pytest.raises(AccountNotFoundError):
        transfer_funds(
            sender_id=sender_id,
            recipient_id=recipient_id,
            amount=Decimal("1.00"),
            currency=Currency.GHS,
        )


def test_mid_transfer_exception_rolls_back_everything(
    transfer_accounts, monkeypatch
):
    sender = transfer_accounts["sender"]
    recipient = transfer_accounts["recipient"]
    fund_account(transfer_accounts["treasury"], sender)
    original_balance = calculate_balance(sender)
    transaction_count = Transaction.objects.count()
    ledger_count = LedgerEntry.objects.count()

    def create_debit_then_crash(financial_transaction, locked_sender, _recipient):
        LedgerEntry.objects.create(
            transaction=financial_transaction,
            account=locked_sender,
            entry_type=LedgerEntry.EntryType.DEBIT,
            amount=financial_transaction.amount,
            currency=financial_transaction.currency,
        )
        raise RuntimeError("simulated process failure")

    monkeypatch.setattr(
        transfer_services, "_create_balanced_entries", create_debit_then_crash
    )

    with pytest.raises(RuntimeError, match="simulated process failure"):
        transfer_funds(
            sender_id=sender.pk,
            recipient_id=recipient.pk,
            amount=Decimal("100.00"),
            currency=Currency.GHS,
        )

    assert Transaction.objects.count() == transaction_count
    assert LedgerEntry.objects.count() == ledger_count
    assert calculate_balance(sender) == original_balance
    assert calculate_balance(recipient) == Decimal("0.00")
    assert AuditEvent.objects.count() == 0


@pytest.mark.django_db(transaction=True)
def test_concurrent_transfers_cannot_overspend(transfer_accounts, monkeypatch):
    sender = transfer_accounts["sender"]
    first_recipient = transfer_accounts["recipient"]
    second_recipient = transfer_accounts["other_recipient"]
    fund_account(transfer_accounts["treasury"], sender)

    first_balance_read = threading.Event()
    release_first_transfer = threading.Event()
    second_worker_started = threading.Event()
    invocation_lock = threading.Lock()
    invocation_count = 0
    original_calculate_balance = calculate_balance

    def controlled_balance(account, *, currency=None):
        nonlocal invocation_count
        with invocation_lock:
            invocation_count += 1
            is_first_read = invocation_count == 1
        if is_first_read:
            first_balance_read.set()
            if not release_first_transfer.wait(timeout=5):
                raise RuntimeError("concurrency test timed out")
        return original_calculate_balance(account, currency=currency)

    monkeypatch.setattr(
        transfer_services, "calculate_balance", controlled_balance
    )

    def attempt_transfer(recipient_id, started_event=None):
        close_old_connections()
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_backend_pid()")
                backend_pid = cursor.fetchone()[0]
            if started_event is not None:
                started_event.set()
            try:
                result = transfer_funds(
                    sender_id=sender.pk,
                    recipient_id=recipient_id,
                    amount=Decimal("400.00"),
                    currency=Currency.GHS,
                )
                return "succeeded", result.id, backend_pid
            except InsufficientFundsError:
                return "insufficient_funds", None, backend_pid
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(attempt_transfer, first_recipient.pk)
        assert first_balance_read.wait(timeout=5)
        second = executor.submit(
            attempt_transfer, second_recipient.pk, second_worker_started
        )
        assert second_worker_started.wait(timeout=5)
        time.sleep(0.2)
        assert not second.done(), "second transfer did not wait on the row lock"
        release_first_transfer.set()
        results = [first.result(timeout=5), second.result(timeout=5)]

    outcomes = sorted(result[0] for result in results)
    backend_pids = {result[2] for result in results}
    assert outcomes == ["insufficient_funds", "succeeded"]
    assert len(backend_pids) == 2
    assert calculate_balance(sender) == Decimal("100.00")
    assert sum(
        entry.signed_amount
        for entry in LedgerEntry.objects.filter(
            transaction__sender=sender,
            transaction__amount=Decimal("400.00"),
        )
    ) == Decimal("0.00")
    assert Transaction.objects.filter(
        sender=sender,
        amount=Decimal("400.00"),
        status=Transaction.Status.SUCCEEDED,
    ).count() == 1
