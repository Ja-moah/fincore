from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command

from accounts.models import Account
from audit.models import AuditEvent
from ledger.models import LedgerEntry
from ledger.services import calculate_balance
from transactions.models import Transaction


pytestmark = pytest.mark.django_db


def test_seed_demo_is_idempotent_and_creates_known_balances():
    call_command("seed_demo", verbosity=0)
    first_counts = (
        get_user_model().objects.count(),
        Account.objects.count(),
        Transaction.objects.count(),
        LedgerEntry.objects.count(),
        AuditEvent.objects.count(),
    )

    call_command("seed_demo", verbosity=0)

    assert (
        get_user_model().objects.count(),
        Account.objects.count(),
        Transaction.objects.count(),
        LedgerEntry.objects.count(),
        AuditEvent.objects.count(),
    ) == first_counts
    assert first_counts == (4, 4, 4, 8, 1)
    assert calculate_balance(Account.objects.get(account_number="DEMO-GHS-ALICE")) == Decimal(
        "1100.00"
    )
    assert calculate_balance(Account.objects.get(account_number="DEMO-GHS-BOB")) == Decimal(
        "1000.00"
    )
    assert calculate_balance(
        Account.objects.get(account_number="DEMO-GHS-CHARLIE")
    ) == Decimal("900.00")
