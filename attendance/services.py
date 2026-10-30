"""Attendance sessions and records over the shared analytics models (FR-014 to FR-019, FR-037)."""

from django.db import IntegrityError, transaction
from django.db.models import OuterRef, Subquery
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.exceptions import (
    APIException,
    NotFound,
    PermissionDenied,
    ValidationError,
)

from academic.services import sections_for_user
from analytics.models import AttendanceRecord, AttendanceSession, Enrollment
from analytics.services import calculate_attendance_percentage
from users.models import User


class DuplicateAttendance(APIException):
    status_code = 409
    default_detail = "Attendance already exists for this student and session."
    default_code = "duplicate_attendance"


def student_dashboard_courses(student):
    """FR-020: one attendance percentage per enrolled active course."""
    courses = {
        section.course_id: section.course
        for section in sections_for_user(student)
    }
    return [
        {
            "course_id": course.pk,
            "course_code": course.code,
            "course_title": course.title,
            "attendance_percentage": calculate_attendance_percentage(student, course),
        }
        for course in sorted(courses.values(), key=lambda item: item.code)
    ]


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
        reject_future_date(session.date, field="session")

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


FUTURE_DATE_MESSAGE = "Attendance cannot be recorded for a future date."


def reject_future_date(value, field="date"):
    """NFR-004: no session or attendance may be dated after today."""
    if value > timezone.localdate():
        raise ValidationError({field: FUTURE_DATE_MESSAGE})


class SessionConflict(APIException):
    status_code = 409
    default_detail = "An attendance session already exists for this period and date."
    default_code = "session_exists"


def _require_assigned_faculty(user, section):
    if (
        not user.is_active
        or user.role != User.Role.FACULTY
        or section.faculty_id != user.pk
    ):
        raise PermissionDenied("You are not assigned to this section.")


def sessions_for_user(user):
    """Faculty see sessions for sections they teach; admins see every session."""
    queryset = AttendanceSession.objects.select_related(
        "section__course", "timetable_slot"
    ).order_by("-date", "timetable_slot__start_time", "pk")
    if user.role == User.Role.ADMIN:
        return queryset
    if user.role == User.Role.FACULTY:
        return queryset.filter(section__faculty=user)
    return queryset.none()


def get_session_for_user(user, session_id):
    """Return a session the caller may see, or raise 404 / 403."""
    session = (
        AttendanceSession.objects.select_related("section__course", "timetable_slot")
        .filter(pk=session_id)
        .first()
    )
    if session is None:
        raise NotFound("Attendance session not found.")
    if user.role != User.Role.ADMIN:
        _require_assigned_faculty(user, session.section)
    return session


def start_session(*, faculty, timetable_slot, date):
    """FR-014: start a session for one of the faculty member's scheduled periods.

    The date must fall on the period's weekday, and each period can only have
    one session per date.
    """
    section = timetable_slot.section
    _require_assigned_faculty(faculty, section)
    reject_future_date(date)
    if not section.is_active or not section.course.is_active:
        raise ValidationError({"section": "This section or its course is deactivated."})
    if date.isoweekday() != timetable_slot.day_of_week:
        raise ValidationError(
            {
                "date": (
                    f"{date.isoformat()} is a {date.strftime('%A')}, but this period "
                    f"is scheduled on {timetable_slot.get_day_of_week_display()}."
                )
            }
        )
    if AttendanceSession.objects.filter(timetable_slot=timetable_slot, date=date).exists():
        raise SessionConflict()
    try:
        with transaction.atomic():
            return AttendanceSession.objects.create(
                section=section, timetable_slot=timetable_slot, date=date
            )
    except IntegrityError as error:
        raise SessionConflict() from error


def session_roster(session):
    """FR-015: enrolled active students with their status in this session.

    One query: the status comes from a subquery, so the cost does not grow
    with the number of students (NFR-002).
    """
    status = AttendanceRecord.objects.filter(
        session=session, student=OuterRef("pk")
    ).values("status")[:1]
    return (
        User.objects.filter(
            attendance_enrollments__section_id=session.section_id,
            role=User.Role.STUDENT,
            is_active=True,
        )
        .annotate(attendance_status=Subquery(status))
        .order_by("name", "email")
    )


def _require_open(session):
    if session.closed:
        raise ValidationError({"session": "Attendance session is closed."})
    reject_future_date(session.date, field="session")


def _locked_session_for_marking(faculty, session_id):
    session = get_object_or_404(
        AttendanceSession.objects.select_for_update().select_related("section"),
        pk=session_id,
    )
    _require_assigned_faculty(faculty, session.section)
    _require_open(session)
    return session


def mark_student(*, faculty, session_id, student_id, status):
    """FR-016: set or change one student's mark while the session is open."""
    with transaction.atomic():
        session = _locked_session_for_marking(faculty, session_id)
        enrolled = Enrollment.objects.filter(
            section_id=session.section_id,
            student_id=student_id,
            student__role=User.Role.STUDENT,
            student__is_active=True,
        ).exists()
        if not enrolled:
            raise NotFound("This student is not enrolled in this section.")
        record, _ = AttendanceRecord.objects.update_or_create(
            session=session,
            student_id=student_id,
            defaults={"status": status.upper()},
        )
        return record


def mark_all_present(*, faculty, session_id):
    """FR-017: mark every enrolled active student present in one action."""
    with transaction.atomic():
        session = _locked_session_for_marking(faculty, session_id)
        student_ids = list(
            Enrollment.objects.filter(
                section_id=session.section_id,
                student__role=User.Role.STUDENT,
                student__is_active=True,
            ).values_list("student_id", flat=True)
        )
        AttendanceRecord.objects.filter(
            session=session, student_id__in=student_ids
        ).exclude(status=AttendanceRecord.Status.PRESENT).update(
            status=AttendanceRecord.Status.PRESENT
        )
        already = set(
            AttendanceRecord.objects.filter(
                session=session, student_id__in=student_ids
            ).values_list("student_id", flat=True)
        )
        AttendanceRecord.objects.bulk_create(
            [
                AttendanceRecord(
                    session=session,
                    student_id=student_id,
                    status=AttendanceRecord.Status.PRESENT,
                )
                for student_id in student_ids
                if student_id not in already
            ]
        )
        return session


class SessionAlreadyClosed(APIException):
    status_code = 409
    default_detail = "This attendance session is already closed."
    default_code = "session_closed"


def close_session(*, faculty, session_id):
    """FR-018 / FR-019: finalize a session and record when it was closed.

    Students left unmarked are not attending, so they count as absent in the
    attendance percentage (FR-029), which only counts present records.
    """
    with transaction.atomic():
        session = get_object_or_404(
            AttendanceSession.objects.select_for_update().select_related("section"),
            pk=session_id,
        )
        _require_assigned_faculty(faculty, session.section)
        if session.closed:
            raise SessionAlreadyClosed()
        session.closed = True
        session.closed_at = timezone.now()
        session.save(update_fields=["closed", "closed_at"])
        return session
