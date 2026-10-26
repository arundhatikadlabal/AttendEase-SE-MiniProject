"""Attendance writes over the shared analytics models (FR-037)."""

from django.db import IntegrityError, transaction
from django.shortcuts import get_object_or_404
from rest_framework.exceptions import APIException, PermissionDenied, ValidationError

from analytics.models import AttendanceRecord, AttendanceSession, Enrollment
from users.models import User


class DuplicateAttendance(APIException):
    status_code = 409
    default_detail = "Attendance already exists for this student and session."
    default_code = "duplicate_attendance"


def submit_records(*, faculty, session_id, records):
    """Insert a validated batch atomically; never overwrite existing attendance.

    Lock the session to serialize submissions on PostgreSQL. The existing unique
    database constraint also protects against writers that bypass this service.
    """
    with transaction.atomic():
        session = get_object_or_404(
            AttendanceSession.objects.select_for_update(), pk=session_id
        )
        if (
            not faculty.is_active
            or faculty.role != User.Role.FACULTY
            or session.section.faculty_id != faculty.pk
        ):
            raise PermissionDenied("You are not assigned to this section.")
        if session.closed:
            raise ValidationError({"session": "Attendance session is closed."})

        student_ids = [record["student_id"] for record in records]
        if len(student_ids) != len(set(student_ids)):
            raise DuplicateAttendance()

        enrolled_ids = set(
            Enrollment.objects.filter(
                section_id=session.section_id,
                student_id__in=student_ids,
                student__role=User.Role.STUDENT,
                student__is_active=True,
            ).values_list("student_id", flat=True)
        )
        if set(student_ids) != enrolled_ids:
            raise ValidationError(
                {
                    "records": "Every student must be active and enrolled in this section."
                }
            )

        existing = AttendanceRecord.objects.filter(
            session=session, student_id__in=student_ids
        )
        if existing.exists():
            raise DuplicateAttendance()

        try:
            # Inner savepoint lets us inspect a constraint conflict safely.
            with transaction.atomic():
                return AttendanceRecord.objects.bulk_create(
                    [
                        AttendanceRecord(
                            session=session,
                            student_id=record["student_id"],
                            status=record["status"].upper(),
                        )
                        for record in records
                    ]
                )
        except IntegrityError as error:
            if existing.exists():
                raise DuplicateAttendance() from error
            raise
