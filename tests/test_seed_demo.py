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

    admin = get_user_model().objects.get(username="Admin")
    admin.is_staff = False
    admin.is_superuser = False
    admin.set_password("changed-password")
    admin.save(update_fields=["password", "is_staff", "is_superuser"])

    call_command("seed_demo", verbosity=0)

    assert (
        get_user_model().objects.count(),
        Account.objects.count(),
        Transaction.objects.count(),
        LedgerEntry.objects.count(),
        AuditEvent.objects.count(),
    ) == first_counts
    assert first_counts == (5, 5, 7, 14, 1)
    expected_balances = {
        "DEMO-GHS-ADMIN": Decimal("5750.00"),
        "DEMO-GHS-JUSTICE": Decimal("2650.00"),
        "DEMO-GHS-AMA": Decimal("1250.00"),
        "DEMO-GHS-KOJO": Decimal("850.00"),
    }
    for account_number, expected_balance in expected_balances.items():
        assert calculate_balance(
            Account.objects.get(account_number=account_number)
        ) == expected_balance

    user_model = get_user_model()
    admin = user_model.objects.get(username="Admin")
    assert admin.is_staff is True
    assert admin.is_superuser is True
    assert admin.check_password("admin123")

    for username, password in (
        ("Justice", "just123"),
        ("Ama", "ama123"),
        ("Kojo", "kojo123"),
    ):
        user = user_model.objects.get(username=username)
        assert user.is_staff is False
        assert user.is_superuser is False
        assert user.check_password(password)

    assert not user_model.objects.get(username="demo_treasury").has_usable_password()
