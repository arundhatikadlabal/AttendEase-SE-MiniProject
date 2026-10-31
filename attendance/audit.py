"""Audit helpers called inside the same transaction as the business change."""

from django.shortcuts import get_object_or_404
from rest_framework.exceptions import PermissionDenied

from analytics.models import AttendanceRecord
from users.models import User

from .models import AttendanceAuditEntry


def append_change(*, record, actor, action, old_status, correction=None, reason=""):
    return AttendanceAuditEntry.objects.create(
        record=record,
        actor=actor,
        action=action,
        old_status=old_status,
        new_status=record.status,
        correction=correction,
        reason=reason,
    )


def history_for_user(*, user, session_id, student_id):
    if not user.is_active:
        raise PermissionDenied("Only active users may view attendance history.")
    records = AttendanceRecord.objects.filter(
        session_id=session_id, student_id=student_id
    )
    if user.role == User.Role.STUDENT:
        records = records.filter(student=user)
    elif user.role == User.Role.FACULTY:
        records = records.filter(session__section__faculty=user)
    elif user.role != User.Role.ADMIN:
        raise PermissionDenied("You may not view attendance history.")
    record = get_object_or_404(records)
    return record.audit_entries.all()
