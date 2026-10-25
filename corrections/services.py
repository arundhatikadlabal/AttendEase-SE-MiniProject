"""Student correction submission (FR-024); decisions are separate stories."""

from django.db import IntegrityError, transaction
from django.shortcuts import get_object_or_404
from rest_framework.exceptions import APIException, PermissionDenied, ValidationError

from analytics.models import AttendanceRecord, Enrollment
from users.models import User

from .models import CorrectionRequest


class PendingCorrectionConflict(APIException):
    status_code = 409
    default_detail = (
        "A pending correction request already exists for this attendance record."
    )
    default_code = "pending_correction_exists"


def submit_correction(*, student, record_id, reason):
    if not student.is_active or student.role != User.Role.STUDENT:
        raise PermissionDenied(
            "Only active students may request attendance corrections."
        )
    reason = reason.strip()
    if not reason or len(reason) > 2000:
        raise ValidationError(
            {"reason": "Provide a reason between 1 and 2000 characters."}
        )

    with transaction.atomic():
        # Scope before lookup so another student's record is never disclosed.
        # Lock the record to serialize submissions on PostgreSQL.
        record = get_object_or_404(
            AttendanceRecord.objects.select_for_update().filter(student=student),
            pk=record_id,
        )
        if not Enrollment.objects.filter(
            section_id=record.session.section_id, student=student
        ).exists():
            raise PermissionDenied("You are not enrolled in this record's section.")

        pending = CorrectionRequest.objects.filter(
            record=record, status=CorrectionRequest.Status.PENDING
        )
        if pending.exists():
            raise PendingCorrectionConflict()

        try:
            with transaction.atomic():
                return CorrectionRequest.objects.create(
                    record=record,
                    student=student,
                    reason=reason,
                    status=CorrectionRequest.Status.PENDING,
                )
        except IntegrityError as error:
            # A concurrent writer bypassing the lock is still caught by the DB.
            if pending.exists():
                raise PendingCorrectionConflict() from error
            raise


def pending_corrections_for_faculty(faculty):
    """FR-026: pending requests in the faculty member's currently assigned sections."""
    if not faculty.is_active or faculty.role != User.Role.FACULTY:
        raise PermissionDenied(
            "Only active faculty may view the pending correction queue."
        )
    return (
        CorrectionRequest.objects.filter(
            status=CorrectionRequest.Status.PENDING,
            record__session__section__faculty=faculty,
        )
        .select_related("student", "record__session__section__course")
        .order_by("created_at", "pk")
    )
