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


USERS = {
    "treasury": {
        "username": "demo_treasury",
        "account_number": "DEMO-GHS-TREASURY",
        "password": None,
        "is_staff": False,
        "is_superuser": False,
    },
    "admin": {
        "username": "Admin",
        "account_number": "DEMO-GHS-ADMIN",
        "password": "admin123",
        "is_staff": True,
        "is_superuser": True,
    },
    "justice": {
        "username": "Justice",
        "account_number": "DEMO-GHS-JUSTICE",
        "password": "just123",
        "is_staff": False,
        "is_superuser": False,
    },
    "ama": {
        "username": "Ama",
        "account_number": "DEMO-GHS-AMA",
        "password": "ama123",
        "is_staff": False,
        "is_superuser": False,
    },
    "kojo": {
        "username": "Kojo",
        "account_number": "DEMO-GHS-KOJO",
        "password": "kojo123",
        "is_staff": False,
        "is_superuser": False,
    },
}

TRANSACTIONS = (
    ("00000000-0000-0000-0000-000000000201", "treasury", "admin", "6000.00"),
    ("00000000-0000-0000-0000-000000000202", "treasury", "justice", "2500.00"),
    ("00000000-0000-0000-0000-000000000203", "treasury", "ama", "1200.00"),
    ("00000000-0000-0000-0000-000000000204", "treasury", "kojo", "800.00"),
    ("00000000-0000-0000-0000-000000000210", "admin", "justice", "250.00"),
    ("00000000-0000-0000-0000-000000000211", "justice", "ama", "100.00"),
    ("00000000-0000-0000-0000-000000000212", "ama", "kojo", "50.00"),
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
            request_id=uuid.UUID("00000000-0000-0000-0000-000000000200"),
            defaults={
                "actor": accounts["treasury"].user,
                "action": "demo.seeded",
                "resource_type": "dataset",
                "resource_id": "fincore-demo-v2",
                "metadata": {"result": "ready"},
            },
        )

        self.stdout.write(self.style.SUCCESS("Demo data is ready."))
        for name in ("admin", "justice", "ama", "kojo"):
            account = accounts[name]
            self.stdout.write(
                f"{account.user.username}: {account.account_number} "
                f"balance={calculate_balance(account):.2f} {account.currency}"
            )
        self.stdout.write("Demo credentials configured as documented in README.md.")

    def _ensure_users_and_accounts(self):
        user_model = get_user_model()
        accounts = {}
        for name, user_spec in USERS.items():
            username = user_spec["username"]
            account_number = user_spec["account_number"]
            user, _ = user_model.objects.get_or_create(username=username)
            user.is_staff = user_spec["is_staff"]
            user.is_superuser = user_spec["is_superuser"]
            user.is_active = True
            if user_spec["password"] is None:
                user.set_unusable_password()
            else:
                user.set_password(user_spec["password"])
            user.save(
                update_fields=["password", "is_active", "is_staff", "is_superuser"]
            )

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
            if account.status != Account.Status.ACTIVE:
                account.status = Account.Status.ACTIVE
                account.save(update_fields=["status", "updated_at"])
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
