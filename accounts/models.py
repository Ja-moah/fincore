from django.conf import settings
from django.db import models


class Currency(models.TextChoices):
    GHS = "GHS", "Ghanaian cedi"


class Account(models.Model):
    class Status(models.TextChoices):
        ACTIVE = "ACTIVE", "Active"
        FROZEN = "FROZEN", "Frozen"
        CLOSED = "CLOSED", "Closed"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="financial_accounts",
    )
    account_number = models.CharField(max_length=34, unique=True)
    currency = models.CharField(
        max_length=3,
        choices=Currency,
        default=Currency.GHS,
    )
    status = models.CharField(
        max_length=10,
        choices=Status,
        default=Status.ACTIVE,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["user", "status"], name="account_user_status_idx"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=~models.Q(account_number=""),
                name="account_number_not_empty",
            ),
        ]

    def __str__(self):
        return self.account_number
