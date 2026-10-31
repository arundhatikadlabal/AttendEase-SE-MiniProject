
from decimal import ROUND_HALF_UP, Decimal

from rest_framework.exceptions import NotFound, PermissionDenied

from users.models import User

from .models import AttendanceRecord, AttendanceSession, Enrollment, Section


def calculate_attendance_percentage(student, course):
    """
    Calculate a student's attendance percentage for one course.

    Only closed sessions in sections where the student is enrolled
    are included in the calculation.
    """
    eligible_sessions = AttendanceSession.objects.filter(
        section__course=course,
        section__enrollments__student=student,
        closed=True,
    ).distinct()

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


def identify_students_below_threshold(course, section=None):
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
        percentage = calculate_attendance_percentage(student, course)

        if percentage < threshold:
            results.append(
                {
                    "student": student,
                    "attendance_percentage": percentage,
                    "threshold": threshold,
                }
            )

    return results


def section_defaulters(*, section_id, user):
    """Return enrolled students below this section's course threshold (FR-031)."""
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

    defaulters = identify_students_below_threshold(section.course, section=section)
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
