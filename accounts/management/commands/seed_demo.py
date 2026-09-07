import uuid
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction as db_transaction

from accounts.models import Account, Currency
from audit.models import AuditEvent
from ledger.models import LedgerEntry
from ledger.services import calculate_balance
from transactions.models import Transaction


DEMO_PASSWORD = "fincore-demo-only"

USERS = {
    "treasury": ("demo_treasury", "DEMO-GHS-TREASURY"),
    "alice": ("demo_alice", "DEMO-GHS-ALICE"),
    "bob": ("demo_bob", "DEMO-GHS-BOB"),
    "charlie": ("demo_charlie", "DEMO-GHS-CHARLIE"),
}

TRANSACTIONS = (
    ("00000000-0000-0000-0000-000000000001", "treasury", "alice", "1200.00"),
    ("00000000-0000-0000-0000-000000000002", "treasury", "bob", "900.00"),
    ("00000000-0000-0000-0000-000000000003", "treasury", "charlie", "900.00"),
    ("00000000-0000-0000-0000-000000000010", "alice", "bob", "100.00"),
)


class Command(BaseCommand):
    help = "Create an idempotent, fictional FinCore demonstration dataset."

    @db_transaction.atomic
    def handle(self, *args, **options):
        accounts = self._ensure_users_and_accounts()
        for transaction_id, sender_name, recipient_name, amount in TRANSACTIONS:
            self._ensure_balanced_transaction(
                transaction_id=uuid.UUID(transaction_id),
                sender=accounts[sender_name],
                recipient=accounts[recipient_name],
                amount=Decimal(amount),
            )

        AuditEvent.objects.get_or_create(
            request_id=uuid.UUID("00000000-0000-0000-0000-000000000100"),
            defaults={
                "actor": accounts["treasury"].user,
                "action": "demo.seeded",
                "resource_type": "dataset",
                "resource_id": "fincore-demo-v1",
                "metadata": {"result": "ready"},
            },
        )

        self.stdout.write(self.style.SUCCESS("Demo data is ready."))
        for name in ("alice", "bob", "charlie"):
            account = accounts[name]
            self.stdout.write(
                f"{account.user.username}: {account.account_number} "
                f"balance={calculate_balance(account):.2f} {account.currency}"
            )
        self.stdout.write(
            "Development-only password for demo_alice/demo_bob/demo_charlie: "
            f"{DEMO_PASSWORD}"
        )

    def _ensure_users_and_accounts(self):
        user_model = get_user_model()
        accounts = {}
        for name, (username, account_number) in USERS.items():
            user, created = user_model.objects.get_or_create(username=username)
            if created:
                user.set_password(DEMO_PASSWORD)
                user.save(update_fields=["password"])

            account, _ = Account.objects.get_or_create(
                account_number=account_number,
                defaults={
                    "user": user,
                    "currency": Currency.GHS,
                    "status": Account.Status.ACTIVE,
                },
            )
            if account.user_id != user.id or account.currency != Currency.GHS:
                raise CommandError(
                    f"Existing account {account_number} conflicts with demo data."
                )
            accounts[name] = account
        return accounts

    def _ensure_balanced_transaction(
        self, *, transaction_id, sender, recipient, amount
    ):
        financial_transaction, created = Transaction.objects.get_or_create(
            id=transaction_id,
            defaults={
                "sender": sender,
                "recipient": recipient,
                "amount": amount,
                "currency": Currency.GHS,
                "status": Transaction.Status.SUCCEEDED,
            },
        )
        expected = (
            financial_transaction.sender_id == sender.id
            and financial_transaction.recipient_id == recipient.id
            and financial_transaction.amount == amount
            and financial_transaction.currency == Currency.GHS
            and financial_transaction.status == Transaction.Status.SUCCEEDED
        )
        if not created and not expected:
            raise CommandError(
                f"Existing transaction {transaction_id} conflicts with demo data."
            )

        entries = list(financial_transaction.ledger_entries.all())
        if not entries:
            LedgerEntry.objects.create(
                transaction=financial_transaction,
                account=sender,
                entry_type=LedgerEntry.EntryType.DEBIT,
                amount=amount,
                currency=Currency.GHS,
            )
            LedgerEntry.objects.create(
                transaction=financial_transaction,
                account=recipient,
                entry_type=LedgerEntry.EntryType.CREDIT,
                amount=amount,
                currency=Currency.GHS,
            )
            return

        expected_entries = {
            (sender.id, LedgerEntry.EntryType.DEBIT, amount, Currency.GHS),
            (recipient.id, LedgerEntry.EntryType.CREDIT, amount, Currency.GHS),
        }
        actual_entries = {
            (entry.account_id, entry.entry_type, entry.amount, entry.currency)
            for entry in entries
        }
        if len(entries) != 2 or actual_entries != expected_entries:
            raise CommandError(
                f"Existing ledger entries for {transaction_id} are not balanced demo data."
            )
