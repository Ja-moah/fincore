import logging
from decimal import Decimal

from django.db import transaction as db_transaction

from accounts.models import Account
from audit.models import AuditEvent
from ledger.models import LedgerEntry
from ledger.services import (
    CurrencyMismatchError as LedgerCurrencyMismatchError,
)
from ledger.services import calculate_balance

from .models import Transaction


logger = logging.getLogger(__name__)


class TransferError(Exception):
    code = "transfer_error"


class InvalidTransferError(TransferError):
    code = "invalid_transfer"


class AccountNotFoundError(TransferError):
    code = "account_not_found"


class AccountUnavailableError(TransferError):
    code = "account_unavailable"


class CurrencyMismatchError(TransferError):
    code = "currency_mismatch"


class InsufficientFundsError(TransferError):
    code = "insufficient_funds"


class LedgerImbalanceError(TransferError):
    code = "ledger_imbalance"


def _validate_request(sender_id, recipient_id, amount, currency):
    if sender_id is None or recipient_id is None:
        raise AccountNotFoundError("Both sender and recipient accounts are required.")
    if sender_id == recipient_id:
        raise InvalidTransferError("Sender and recipient accounts must be different.")
    if not isinstance(amount, Decimal):
        raise InvalidTransferError("Transfer amount must be a Decimal instance.")
    if not amount.is_finite():
        raise InvalidTransferError("Transfer amount must be finite.")
    if amount <= Decimal("0.00"):
        raise InvalidTransferError("Transfer amount must be positive.")
    if amount.as_tuple().exponent < -2:
        raise InvalidTransferError("Transfer amount cannot have more than two decimals.")
    if not currency:
        raise CurrencyMismatchError("Transfer currency is required.")


def _get_locked_accounts(sender_id, recipient_id):
    account_ids = (sender_id, recipient_id)
    accounts = list(
        Account.objects.select_for_update().filter(pk__in=account_ids).order_by("pk")
    )
    accounts_by_id = {account.pk: account for account in accounts}

    if sender_id not in accounts_by_id:
        raise AccountNotFoundError("Sender account does not exist.")
    if recipient_id not in accounts_by_id:
        raise AccountNotFoundError("Recipient account does not exist.")
    return accounts_by_id[sender_id], accounts_by_id[recipient_id]


def _validate_accounts(sender, recipient, currency):
    if sender.status != Account.Status.ACTIVE:
        raise AccountUnavailableError(
            f"Sender account is {sender.status.lower()} and cannot transfer funds."
        )
    if recipient.status == Account.Status.CLOSED:
        raise AccountUnavailableError("Recipient account is closed.")
    if sender.currency != currency or recipient.currency != currency:
        raise CurrencyMismatchError(
            "Transfer currency must match both account currencies."
        )


def _create_balanced_entries(financial_transaction, sender, recipient):
    debit = LedgerEntry.objects.create(
        transaction=financial_transaction,
        account=sender,
        entry_type=LedgerEntry.EntryType.DEBIT,
        amount=financial_transaction.amount,
        currency=financial_transaction.currency,
    )
    credit = LedgerEntry.objects.create(
        transaction=financial_transaction,
        account=recipient,
        entry_type=LedgerEntry.EntryType.CREDIT,
        amount=financial_transaction.amount,
        currency=financial_transaction.currency,
    )

    if (
        debit.transaction_id != credit.transaction_id
        or debit.currency != credit.currency
        or debit.amount != credit.amount
        or debit.signed_amount + credit.signed_amount != Decimal("0.00")
    ):
        raise LedgerImbalanceError("Transfer ledger entries do not balance.")
    return debit, credit


def transfer_funds(
    *,
    sender_id,
    recipient_id,
    amount,
    currency,
    actor=None,
    request_id=None,
):
    """Atomically transfer money between two internal accounts.

    The accounts are locked in primary-key order before the authoritative ledger
    balance is read. Any exception rolls back the transaction row, both ledger
    entries, and the success audit event together.
    """

    _validate_request(sender_id, recipient_id, amount, currency)

    with db_transaction.atomic():
        sender, recipient = _get_locked_accounts(sender_id, recipient_id)
        _validate_accounts(sender, recipient, currency)

        try:
            sender_balance = calculate_balance(sender, currency=currency)
        except LedgerCurrencyMismatchError as exc:
            raise CurrencyMismatchError(str(exc)) from exc
        if sender_balance < amount:
            raise InsufficientFundsError("Sender account has insufficient funds.")

        financial_transaction = Transaction.objects.create(
            sender=sender,
            recipient=recipient,
            amount=amount,
            currency=currency,
            status=Transaction.Status.PENDING,
        )
        financial_transaction.status = Transaction.Status.PROCESSING
        financial_transaction.save(update_fields=["status", "updated_at"])

        _create_balanced_entries(financial_transaction, sender, recipient)

        financial_transaction.status = Transaction.Status.SUCCEEDED
        financial_transaction.save(update_fields=["status", "updated_at"])

        audit_kwargs = {
            "actor": actor or sender.user,
            "action": "transfer.succeeded",
            "resource_type": "transaction",
            "resource_id": str(financial_transaction.id),
            "metadata": {
                "result": "succeeded",
                "sender_account_id": sender.pk,
                "recipient_account_id": recipient.pk,
                "amount": str(amount),
                "currency": currency,
            },
        }
        if request_id is not None:
            audit_kwargs["request_id"] = request_id
        AuditEvent.objects.create(**audit_kwargs)

        transaction_id = financial_transaction.id
        db_transaction.on_commit(
            lambda: logger.info(
                "transfer_committed transaction_id=%s result=succeeded",
                transaction_id,
            )
        )

        return financial_transaction
