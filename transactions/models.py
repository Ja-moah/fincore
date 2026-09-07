import uuid
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import F, Q

from accounts.models import Account, Currency


class Transaction(models.Model):
    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        PROCESSING = "PROCESSING", "Processing"
        SUCCEEDED = "SUCCEEDED", "Succeeded"
        FAILED = "FAILED", "Failed"
        REVERSED = "REVERSED", "Reversed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    sender = models.ForeignKey(
        Account,
        on_delete=models.PROTECT,
        related_name="sent_transactions",
    )
    recipient = models.ForeignKey(
        Account,
        on_delete=models.PROTECT,
        related_name="received_transactions",
    )
    amount = models.DecimalField(
        max_digits=19,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.01"))],
    )
    currency = models.CharField(
        max_length=3,
        choices=Currency,
        default=Currency.GHS,
    )
    status = models.CharField(
        max_length=10,
        choices=Status,
        default=Status.PENDING,
    )
    failure_code = models.CharField(max_length=64, blank=True)
    failure_reason = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["sender", "-created_at"], name="txn_sender_created_idx"),
            models.Index(
                fields=["recipient", "-created_at"],
                name="txn_recipient_created_idx",
            ),
            models.Index(fields=["status", "-created_at"], name="txn_status_created_idx"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(amount__gt=0),
                name="transaction_amount_positive",
            ),
            models.CheckConstraint(
                condition=~Q(sender=F("recipient")),
                name="transaction_distinct_accounts",
            ),
        ]

    def clean(self):
        super().clean()
        if self.sender_id and self.sender_id == self.recipient_id:
            raise ValidationError(
                {"recipient": "Sender and recipient accounts must be different."}
            )

    def __str__(self):
        return str(self.id)


class IdempotencyRecord(models.Model):
    """A user-scoped record used to safely replay a request result."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="idempotency_records",
    )
    key = models.CharField(max_length=255)
    request_fingerprint = models.CharField(max_length=64)
    transaction = models.ForeignKey(
        Transaction,
        on_delete=models.PROTECT,
        related_name="idempotency_records",
        null=True,
        blank=True,
    )
    response_status = models.PositiveSmallIntegerField(null=True, blank=True)
    response_body = models.JSONField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user", "key"],
                name="idempotency_user_key_unique",
            ),
        ]
        indexes = [
            models.Index(fields=["user", "-created_at"], name="idem_user_created_idx"),
            models.Index(fields=["expires_at"], name="idem_expires_idx"),
        ]

    def __str__(self):
        return f"{self.user_id}:{self.key}"
