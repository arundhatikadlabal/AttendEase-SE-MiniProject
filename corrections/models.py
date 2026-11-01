from django.conf import settings
from django.db import models


class CorrectionRequest(models.Model):
    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        APPROVED = "APPROVED", "Approved"
        REJECTED = "REJECTED", "Rejected"

    record = models.ForeignKey(
        "analytics.AttendanceRecord",
        on_delete=models.PROTECT,
        related_name="correction_requests",
    )
    student = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="correction_requests",
    )
    reason = models.TextField(max_length=2000)
    rejection_reason = models.TextField(max_length=2000, blank=True, default="")
    status = models.CharField(
        max_length=10, choices=Status.choices, default=Status.PENDING
    )
    created_at = models.DateTimeField(auto_now_add=True)
    acted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="correction_decisions",
        null=True,
        blank=True,
    )
    acted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["created_at", "pk"]
        constraints = [
            models.UniqueConstraint(
                fields=["record"],
                condition=models.Q(status="PENDING"),
                name="one_pending_correction_per_record",
            ),
        ]
