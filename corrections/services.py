"""Correction submission, faculty queue, and decision services."""

from functools import partial

from django.db import IntegrityError, transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.exceptions import APIException, PermissionDenied, ValidationError

from analytics.models import AttendanceRecord, Enrollment
from attendance.audit import append_change
from users.models import User

from .models import CorrectionRequest
from .notifications import notify_faculty


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
                correction = CorrectionRequest.objects.create(
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

        # A rolled-back request must never send an email. Unexpected callback
        # failures are also non-fatal to the already committed correction.
        transaction.on_commit(partial(notify_faculty, correction.pk), robust=True)
        return correction


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


class CorrectionAlreadyResolved(APIException):
    status_code = 409
    default_detail = "This correction request is no longer pending."
    default_code = "correction_resolved"


def approve_correction(*, faculty, correction_id):
    """FR-027: approve a pending request and its attendance update atomically."""
    if not faculty.is_active or faculty.role != User.Role.FACULTY:
        raise PermissionDenied("Only active faculty may approve corrections.")

    with transaction.atomic():
        record, correction = _locked_pending_correction(faculty, correction_id)

        old_status = record.status
        record.status = AttendanceRecord.Status.PRESENT
        record.save(update_fields=["status"])
        correction.status = CorrectionRequest.Status.APPROVED
        correction.acted_by = faculty
        correction.acted_at = timezone.now()
        correction.save(update_fields=["status", "acted_by", "acted_at"])
        append_change(
            record=record,
            actor=faculty,
            action="APPROVED",
            old_status=old_status,
            correction=correction,
            reason=correction.reason,
        )
        return correction


def _locked_pending_correction(faculty, correction_id):
    """Shared decision checks; the caller must hold an atomic transaction."""
    reference = get_object_or_404(CorrectionRequest, pk=correction_id)
    # Match submission's record-first lock order, including when a new
    # pending request is submitted as an earlier request is resolved.
    record = AttendanceRecord.objects.select_for_update().get(pk=reference.record_id)
    correction = CorrectionRequest.objects.select_for_update().get(pk=correction_id)
    if record.session.section.faculty_id != faculty.pk:
        raise PermissionDenied("You are not assigned to this section.")
    if correction.status != CorrectionRequest.Status.PENDING:
        raise CorrectionAlreadyResolved()
    return record, correction


def reject_correction(*, faculty, correction_id, reason):
    """FR-028: reject with a reason, preserving the original attendance mark."""
    if not faculty.is_active or faculty.role != User.Role.FACULTY:
        raise PermissionDenied("Only active faculty may reject corrections.")
    if not isinstance(reason, str) or not reason.strip() or len(reason.strip()) > 2000:
        raise ValidationError(
            {"reason": "Provide a reason between 1 and 2000 characters."}
        )

    with transaction.atomic():
        record, correction = _locked_pending_correction(faculty, correction_id)
        correction.status = CorrectionRequest.Status.REJECTED
        correction.rejection_reason = reason.strip()
        correction.acted_by = faculty
        correction.acted_at = timezone.now()
        correction.save(
            update_fields=["status", "rejection_reason", "acted_by", "acted_at"]
        )
        append_change(
            record=record,
            actor=faculty,
            action="REJECTED",
            old_status=record.status,
            correction=correction,
            reason=correction.rejection_reason,
        )
        return correction
