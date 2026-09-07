from decimal import Decimal

from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Q

from accounts.models import Account, Currency
from transactions.models import Transaction


class LedgerEntry(models.Model):
    class EntryType(models.TextChoices):
        DEBIT = "DEBIT", "Debit"
        CREDIT = "CREDIT", "Credit"

    transaction = models.ForeignKey(
        Transaction,
        on_delete=models.PROTECT,
        related_name="ledger_entries",
    )
    account = models.ForeignKey(
        Account,
        on_delete=models.PROTECT,
        related_name="ledger_entries",
    )
    entry_type = models.CharField(max_length=6, choices=EntryType)
    amount = models.DecimalField(
        max_digits=19,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.01"))],
    )
    currency = models.CharField(max_length=3, choices=Currency)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(
                fields=["transaction", "entry_type"],
                name="ledger_txn_type_idx",
            ),
            models.Index(
                fields=["account", "currency", "created_at"],
                name="ledger_acct_curr_time_idx",
            ),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(amount__gt=0),
                name="ledger_entry_amount_positive",
            ),
        ]

    @property
    def signed_amount(self):
        if self.entry_type == self.EntryType.DEBIT:
            return -self.amount
        return self.amount

    def __str__(self):
        return f"{self.entry_type} {self.amount} {self.currency}"
