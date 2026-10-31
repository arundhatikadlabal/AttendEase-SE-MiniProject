"""Append-only application audit history for attendance and corrections."""

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


class AuditQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise ValidationError("Attendance audit history cannot be changed.")

    def delete(self):
        raise ValidationError("Attendance audit history cannot be deleted.")

    def bulk_update(self, objs, fields, batch_size=None):
        raise ValidationError("Attendance audit history cannot be changed.")

    def bulk_create(
        self,
        objs,
        batch_size=None,
        ignore_conflicts=False,
        update_conflicts=False,
        update_fields=None,
        unique_fields=None,
    ):
        if update_conflicts:
            raise ValidationError("Attendance audit history cannot be changed.")
        return super().bulk_create(
            objs,
            batch_size=batch_size,
            ignore_conflicts=ignore_conflicts,
            update_conflicts=False,
            update_fields=update_fields,
            unique_fields=unique_fields,
        )


class AttendanceAuditEntry(models.Model):
    class Action(models.TextChoices):
        BASELINE = "BASELINE", "Existing record at migration"
        CREATED = "CREATED", "Initial attendance mark"
        MARKED = "MARKED", "Open-session mark changed"
        EDITED = "EDITED", "Closed-session mark changed"
        APPROVED = "APPROVED", "Correction approved"
        REJECTED = "REJECTED", "Correction rejected"

    record = models.ForeignKey(
        "analytics.AttendanceRecord",
        on_delete=models.PROTECT,
        related_name="audit_entries",
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        related_name="attendance_audit_entries",
    )
    correction = models.ForeignKey(
        "corrections.CorrectionRequest",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="audit_entries",
    )
    action = models.CharField(max_length=10, choices=Action.choices)
    old_status = models.CharField(max_length=10, blank=True)
    new_status = models.CharField(max_length=10)
    reason = models.TextField(blank=True, default="")
    timestamp = models.DateTimeField(default=timezone.now, editable=False)

    objects = AuditQuerySet.as_manager()

    class Meta:
        ordering = ["timestamp", "pk"]

    def save(self, *args, **kwargs):
        if not self._state.adding or (
            self.pk is not None and type(self).objects.filter(pk=self.pk).exists()
        ):
            raise ValidationError("Attendance audit history cannot be changed.")
        # Always insert so a caller cannot replace an existing primary key.
        kwargs["force_insert"] = True
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Attendance audit history cannot be deleted.")
