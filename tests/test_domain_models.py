from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.db.models.deletion import ProtectedError

from accounts.models import Account, Currency
from audit.models import AuditEvent
from ledger.models import LedgerEntry
from ledger.services import CurrencyMismatchError, calculate_balance
from transactions.models import IdempotencyRecord, Transaction


pytestmark = pytest.mark.django_db


@pytest.fixture
def user():
    return get_user_model().objects.create_user(username="sender")


@pytest.fixture
def other_user():
    return get_user_model().objects.create_user(username="recipient")


@pytest.fixture
def accounts(user, other_user):
    return (
        Account.objects.create(user=user, account_number="GH0000000001"),
        Account.objects.create(user=other_user, account_number="GH0000000002"),
    )


@pytest.fixture
def financial_transaction(accounts):
    sender, recipient = accounts
    return Transaction.objects.create(
        sender=sender,
        recipient=recipient,
        amount=Decimal("100.00"),
        currency=Currency.GHS,
    )


def test_account_creation_defaults_to_ghs_and_active(user):
    account = Account.objects.create(user=user, account_number="GH0000000001")

    assert account.currency == Currency.GHS
    assert account.status == Account.Status.ACTIVE
    assert account.user == user
    assert not hasattr(account, "balance")


def test_duplicate_account_number_is_rejected(user, other_user):
    Account.objects.create(user=user, account_number="GH0000000001")

    with pytest.raises(IntegrityError):
        Account.objects.create(user=other_user, account_number="GH0000000001")


def test_transaction_amount_must_be_positive(accounts):
    sender, recipient = accounts

    with pytest.raises(IntegrityError):
        Transaction.objects.create(
            sender=sender,
            recipient=recipient,
            amount=Decimal("0.00"),
        )


def test_self_transfer_is_rejected_by_validation_and_database(accounts):
    sender, _ = accounts
    candidate = Transaction(
        sender=sender,
        recipient=sender,
        amount=Decimal("1.00"),
    )

    with pytest.raises(ValidationError):
        candidate.full_clean()

    with pytest.raises(IntegrityError):
        Transaction.objects.create(
            sender=sender,
            recipient=sender,
            amount=Decimal("1.00"),
        )


def test_ledger_entries_expose_debit_and_credit_signs(
    financial_transaction, accounts
):
    sender, recipient = accounts
    debit = LedgerEntry.objects.create(
        transaction=financial_transaction,
        account=sender,
        entry_type=LedgerEntry.EntryType.DEBIT,
        amount=Decimal("25.00"),
        currency=Currency.GHS,
    )
    credit = LedgerEntry.objects.create(
        transaction=financial_transaction,
        account=recipient,
        entry_type=LedgerEntry.EntryType.CREDIT,
        amount=Decimal("25.00"),
        currency=Currency.GHS,
    )

    assert debit.signed_amount == Decimal("-25.00")
    assert credit.signed_amount == Decimal("25.00")


def test_balance_is_calculated_from_ledger_entries(financial_transaction, accounts):
    sender, _ = accounts
    LedgerEntry.objects.create(
        transaction=financial_transaction,
        account=sender,
        entry_type=LedgerEntry.EntryType.CREDIT,
        amount=Decimal("150.00"),
        currency=Currency.GHS,
    )
    LedgerEntry.objects.create(
        transaction=financial_transaction,
        account=sender,
        entry_type=LedgerEntry.EntryType.DEBIT,
        amount=Decimal("40.25"),
        currency=Currency.GHS,
    )

    balance = calculate_balance(sender)

    assert isinstance(balance, Decimal)
    assert balance == Decimal("109.75")


def test_balance_rejects_mixed_currencies(financial_transaction, accounts):
    sender, _ = accounts
    LedgerEntry.objects.create(
        transaction=financial_transaction,
        account=sender,
        entry_type=LedgerEntry.EntryType.CREDIT,
        amount=Decimal("10.00"),
        currency="USD",
    )

    with pytest.raises(CurrencyMismatchError):
        calculate_balance(sender)


def test_ledger_protects_transaction_and_account(financial_transaction, accounts):
    sender, _ = accounts
    LedgerEntry.objects.create(
        transaction=financial_transaction,
        account=sender,
        entry_type=LedgerEntry.EntryType.DEBIT,
        amount=Decimal("5.00"),
        currency=Currency.GHS,
    )

    with pytest.raises(ProtectedError):
        financial_transaction.delete()
    with pytest.raises(ProtectedError):
        sender.delete()


def test_idempotency_key_is_unique_per_user(user, financial_transaction):
    IdempotencyRecord.objects.create(
        user=user,
        key="transfer-request-1",
        request_fingerprint="a" * 64,
        transaction=financial_transaction,
    )

    with pytest.raises(IntegrityError):
        IdempotencyRecord.objects.create(
            user=user,
            key="transfer-request-1",
            request_fingerprint="a" * 64,
        )


def test_same_idempotency_key_is_allowed_for_different_users(
    user, other_user, financial_transaction
):
    IdempotencyRecord.objects.create(
        user=user,
        key="shared-key",
        request_fingerprint="a" * 64,
        transaction=financial_transaction,
    )

    record = IdempotencyRecord.objects.create(
        user=other_user,
        key="shared-key",
        request_fingerprint="b" * 64,
    )

    assert record.pk is not None


def test_audit_event_creation(user, financial_transaction):
    event = AuditEvent.objects.create(
        actor=user,
        action="transaction.created",
        resource_type="transaction",
        resource_id=str(financial_transaction.id),
        metadata={"source": "test"},
    )

    assert event.request_id is not None
    assert event.metadata == {"source": "test"}
    assert event.created_at is not None
