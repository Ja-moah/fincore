import uuid

from django.conf import settings
from django.db import models


class AuditEvent(models.Model):
    """An append-only-in-principle record of a security or domain event."""

    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="audit_events",
        null=True,
        blank=True,
    )
    action = models.CharField(max_length=100)
    resource_type = models.CharField(max_length=100)
    resource_id = models.CharField(max_length=255)
    request_id = models.UUIDField(default=uuid.uuid4, editable=False)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["request_id"], name="audit_request_idx"),
            models.Index(
                fields=["resource_type", "resource_id"],
                name="audit_resource_idx",
            ),
            models.Index(fields=["actor", "-created_at"], name="audit_actor_time_idx"),
        ]

    def __str__(self):
        return f"{self.action}: {self.resource_type}/{self.resource_id}"
