
from decimal import ROUND_HALF_UP, Decimal

from .models import AttendanceRecord, AttendanceSession


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
