
from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase

from .models import (
    AttendanceRecord,
    AttendanceSession,
    Course,
    Enrollment,
    Section,
)
from .services import calculate_attendance_percentage


class AttendancePercentageTests(TestCase):
    def setUp(self):
        User = get_user_model()

        self.student = User.objects.create_user(
            username="student1",
            password="test-password",
        )
        self.faculty = User.objects.create_user(
            username="faculty1",
            password="test-password",
        )
        self.course = Course.objects.create(
            code="CS101",
            title="Computer Science",
        )
        self.section = Section.objects.create(
            course=self.course,
            code="A",
            faculty=self.faculty,
        )
        Enrollment.objects.create(
            section=self.section,
            student=self.student,
        )

    def test_percentage_is_75_for_18_of_24_sessions(self):
        for day in range(1, 25):
            session = AttendanceSession.objects.create(
                section=self.section,
                date=date(2026, 1, day),
                closed=True,
            )
            status = (
                AttendanceRecord.Status.PRESENT
                if day <= 18
                else AttendanceRecord.Status.ABSENT
            )
            AttendanceRecord.objects.create(
                session=session,
                student=self.student,
                status=status,
            )

        result = calculate_attendance_percentage(
            self.student,
            self.course,
        )

        self.assertEqual(result, Decimal("75.00"))

    def test_no_closed_sessions_returns_zero(self):
        result = calculate_attendance_percentage(
            self.student,
            self.course,
        )

        self.assertEqual(result, Decimal("0.00"))

    def test_open_sessions_are_not_counted(self):
        session = AttendanceSession.objects.create(
            section=self.section,
            date=date(2026, 1, 1),
            closed=False,
        )
        AttendanceRecord.objects.create(
            session=session,
            student=self.student,
            status=AttendanceRecord.Status.PRESENT,
        )

        result = calculate_attendance_percentage(
            self.student,
            self.course,
        )

        self.assertEqual(result, Decimal("0.00"))
