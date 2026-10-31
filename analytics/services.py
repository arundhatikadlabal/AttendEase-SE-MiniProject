
from decimal import ROUND_HALF_UP, Decimal

from django.db.models import Count, Max, Min
from rest_framework.exceptions import NotFound, PermissionDenied

from users.models import User

from .models import AttendanceRecord, AttendanceSession, Enrollment, Section


def _filter_session_dates(queryset, *, start_date=None, end_date=None):
    if start_date is not None:
        queryset = queryset.filter(date__gte=start_date)
    if end_date is not None:
        queryset = queryset.filter(date__lte=end_date)
    return queryset


def calculate_attendance_percentage(
    student,
    course,
    *,
    section=None,
    start_date=None,
    end_date=None,
):
    """
    Calculate a student's attendance percentage for one course.

    Only closed sessions in sections where the student is enrolled are counted.
    When ``section`` is provided, the calculation is limited to that section.
    """
    eligible_sessions = AttendanceSession.objects.filter(
        section__course=course,
        section__enrollments__student=student,
        closed=True,
    ).distinct()
    if section is not None:
        eligible_sessions = eligible_sessions.filter(section=section)
    eligible_sessions = _filter_session_dates(
        eligible_sessions,
        start_date=start_date,
        end_date=end_date,
    )

    total_sessions = eligible_sessions.count()

    if total_sessions == 0:
        return Decimal("0.00")

    attended_sessions = AttendanceRecord.objects.filter(
        session__in=eligible_sessions,
        student=student,
        status=AttendanceRecord.Status.PRESENT,
    ).count()

    percentage = (
        Decimal(attended_sessions) * Decimal(100)
        / Decimal(total_sessions)
    )

    return percentage.quantize(
        Decimal("0.01"),
        rounding=ROUND_HALF_UP,
    )


def identify_students_below_threshold(
    course,
    section=None,
    *,
    start_date=None,
    end_date=None,
):
    """
    Return enrolled students whose attendance is below the course threshold.

    Each result contains the student, attendance percentage, and threshold.
    """
    threshold = course.shortage_threshold
    results = []

    enrollments = Enrollment.objects.filter(
        section__course=course,
        student__role=User.Role.STUDENT,
    )
    if section is not None:
        enrollments = enrollments.filter(section=section)
    enrollments = (
        enrollments.select_related("student")
        .order_by("student__name", "student__email")
        .distinct()
    )

    for enrollment in enrollments:
        student = enrollment.student
        percentage = calculate_attendance_percentage(
            student,
            course,
            section=section,
            start_date=start_date,
            end_date=end_date,
        )

        if percentage < threshold:
            results.append(
                {
                    "student": student,
                    "attendance_percentage": percentage,
                    "threshold": threshold,
                }
            )

    return results


def section_defaulters(*, section_id, user, start_date=None, end_date=None):
    """Return enrolled students below this section's course threshold (FR-031)."""
    section = _report_section_for_user(section_id=section_id, user=user)

    defaulters = identify_students_below_threshold(
        section.course,
        section=section,
        start_date=start_date,
        end_date=end_date,
    )
    results = [
        {
            "student_name": defaulter["student"].name,
            "usn": defaulter["student"].usn,
            "course": section.course.code,
            "attendance_percentage": defaulter["attendance_percentage"],
            "threshold": defaulter["threshold"],
            "status": "Defaulter",
        }
        for defaulter in defaulters
    ]

    return section, results


def _report_section_for_user(*, section_id, user):
    section = (
        Section.objects.select_related("course")
        .filter(pk=section_id)
        .first()
    )
    if section is None:
        raise NotFound("Section not found.")

    if user.role != User.Role.ADMIN and (
        user.role != User.Role.FACULTY or section.faculty_id != user.pk
    ):
        raise PermissionDenied("You are not assigned to this section.")

    return section


def section_attendance_summary(
    *,
    section_id,
    user,
    start_date=None,
    end_date=None,
):
    """Summarize closed-session attendance for one section (FR-032)."""
    section = _report_section_for_user(section_id=section_id, user=user)
    closed_sessions = _filter_session_dates(
        AttendanceSession.objects.filter(section=section, closed=True),
        start_date=start_date,
        end_date=end_date,
    )
    session_summary = closed_sessions.aggregate(
        total_sessions=Count("pk"),
        start_date=Min("date"),
        end_date=Max("date"),
    )

    enrollments = (
        Enrollment.objects.filter(
            section=section,
            student__role=User.Role.STUDENT,
        )
        .select_related("student")
        .order_by("student__name", "student__email")
    )
    percentages = [
        calculate_attendance_percentage(
            enrollment.student,
            section.course,
            section=section,
            start_date=start_date,
            end_date=end_date,
        )
        for enrollment in enrollments
    ]
    average = (
        (
            sum(percentages, Decimal("0.00"))
            / Decimal(len(percentages))
        ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        if percentages
        else Decimal("0.00")
    )

    return {
        "section": {
            "id": section.pk,
            "code": section.code,
            "course": section.course.code,
        },
        "date_range": {
            "start_date": session_summary["start_date"],
            "end_date": session_summary["end_date"],
        },
        "average_attendance_percentage": average,
        "total_sessions": session_summary["total_sessions"],
    }
