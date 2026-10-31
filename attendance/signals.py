from django.core.exceptions import ValidationError
from django.db.models.deletion import ProtectedError
from django.db.models.signals import pre_delete
from django.dispatch import receiver

from analytics.models import AttendanceRecord

from .models import AttendanceAuditEntry


@receiver(pre_delete, sender=AttendanceRecord)
def preserve_attendance(sender, instance, **kwargs):
    # Includes queryset deletion and deletion cascading from students/sessions.
    raise ProtectedError("Attendance records must be retained (NFR-003).", {instance})


@receiver(pre_delete, sender=AttendanceAuditEntry)
def preserve_audit(sender, instance, **kwargs):
    raise ValidationError("Attendance audit history cannot be deleted.")
