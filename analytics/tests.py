
from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from .models import (
    AttendanceRecord,
    AttendanceSession,
    Course,
    Enrollment,
    Section,
)
from .services import calculate_attendance_percentage, identify_students_below_threshold


class AttendancePercentageTests(TestCase):
    def setUp(self):
        User = get_user_model()

        self.student = User.objects.create_user(
            email="student1@example.com",
            name="Student One",
            role="student",
            password="test-password",
        )
        self.faculty = User.objects.create_user(
            email="faculty1@example.com",
            name="Faculty One",
            role="faculty",
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

class AttendanceShortageTests(AttendancePercentageTests):
    def create_attendance(self, attended, absent):
        for day in range(1, attended + absent + 1):
            session = AttendanceSession.objects.create(
                section=self.section,
                date=date(2026, 2, day),
                closed=True,
            )
            status = (
                AttendanceRecord.Status.PRESENT
                if day <= attended
                else AttendanceRecord.Status.ABSENT
            )
            AttendanceRecord.objects.create(
                session=session,
                student=self.student,
                status=status,
            )

    def test_student_below_threshold_is_identified(self):
        self.create_attendance(attended=7, absent=3)

        results = identify_students_below_threshold(self.course)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["student"], self.student)
        self.assertEqual(
            results[0]["attendance_percentage"],
            Decimal("70.00"),
        )
        self.assertEqual(
            results[0]["threshold"],
            Decimal("75.00"),
        )

    def test_student_at_threshold_is_not_identified(self):
        self.create_attendance(attended=3, absent=1)

        results = identify_students_below_threshold(self.course)

        self.assertEqual(results, [])

    def test_student_above_threshold_is_not_identified(self):
        self.create_attendance(attended=9, absent=1)

        results = identify_students_below_threshold(self.course)

        self.assertEqual(results, [])


class DefaulterReportApiTests(TestCase):
    def setUp(self):
        self.faculty = get_user_model().objects.create_user(
            email="report-faculty@example.com",
            name="Report Faculty",
            role="faculty",
            password="test-password",
        )
        self.other_faculty = get_user_model().objects.create_user(
            email="other-report-faculty@example.com",
            name="Other Faculty",
            role="faculty",
            password="test-password",
        )
        self.admin = get_user_model().objects.create_superuser(
            email="report-admin@example.com",
            name="Report Admin",
            password="test-password",
        )
        self.below = get_user_model().objects.create_user(
            email="below@example.com",
            name="Below Threshold",
            role="student",
            usn="PES1UG24CS001",
        )
        self.at_threshold = get_user_model().objects.create_user(
            email="at@example.com",
            name="At Threshold",
            role="student",
            usn="PES1UG24CS002",
        )
        self.no_attendance = get_user_model().objects.create_user(
            email="none@example.com",
            name="No Attendance",
            role="student",
        )
        self.course = Course.objects.create(
            code="CS201",
            title="Algorithms",
            shortage_threshold=Decimal("75.00"),
        )
        self.section = Section.objects.create(
            course=self.course,
            code="A",
            faculty=self.faculty,
        )
        Enrollment.objects.bulk_create(
            [
                Enrollment(section=self.section, student=student)
                for student in (self.below, self.at_threshold, self.no_attendance)
            ]
        )
        self.client = APIClient()
        self.url = reverse("analytics-defaulters")

    def create_sessions(self, section, total):
        return [
            AttendanceSession.objects.create(
                section=section,
                date=date(2026, 1, 1) + timedelta(days=index),
                closed=True,
            )
            for index in range(total)
        ]

    def add_attendance(self, sessions, student, *, present):
        for index, session in enumerate(sessions):
            status = (
                AttendanceRecord.Status.PRESENT
                if index < present
                else AttendanceRecord.Status.ABSENT
            )
            AttendanceRecord.objects.create(
                session=session,
                student=student,
                status=status,
            )

    def report_as(self, user, section=None):
        self.client.force_authenticate(user=user)
        return self.client.get(
            self.url,
            {"section_id": section.pk if section else self.section.pk},
        )

    def test_report_lists_only_below_threshold_with_required_columns(self):
        sessions = self.create_sessions(self.section, total=20)
        self.add_attendance(sessions, self.below, present=14)
        self.add_attendance(sessions, self.at_threshold, present=15)

        response = self.report_as(self.faculty)

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(
            body["section"],
            {"id": self.section.pk, "code": "A", "course": "CS201"},
        )
        self.assertEqual(len(body["students"]), 2)
        self.assertEqual(
            body["students"],
            [
                {
                    "student_name": "Below Threshold",
                    "usn": "PES1UG24CS001",
                    "course": "CS201",
                    "attendance_percentage": "70.00",
                    "threshold": "75.00",
                    "status": "Defaulter",
                },
                {
                    "student_name": "No Attendance",
                    "usn": None,
                    "course": "CS201",
                    "attendance_percentage": "0.00",
                    "threshold": "75.00",
                    "status": "Defaulter",
                },
            ],
        )

    def test_students_at_or_above_threshold_are_not_reported(self):
        sessions = self.create_sessions(self.section, total=20)
        self.add_attendance(sessions, self.below, present=20)
        self.add_attendance(sessions, self.at_threshold, present=15)
        self.add_attendance(sessions, self.no_attendance, present=20)
        above = get_user_model().objects.create_user(
            email="above@example.com",
            name="Above Threshold",
            role="student",
        )
        Enrollment.objects.create(section=self.section, student=above)
        self.add_attendance(sessions, above, present=16)

        response = self.report_as(self.faculty)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["students"], [])

    def test_threshold_is_taken_from_each_courses_configuration(self):
        second_course = Course.objects.create(
            code="CS202",
            title="Operating Systems",
            shortage_threshold=Decimal("60.00"),
        )
        second_section = Section.objects.create(
            course=second_course,
            code="A",
            faculty=self.faculty,
        )
        Enrollment.objects.filter(section=self.section).exclude(
            student=self.below
        ).delete()
        Enrollment.objects.create(section=second_section, student=self.below)
        first_sessions = self.create_sessions(self.section, total=10)
        second_sessions = self.create_sessions(second_section, total=10)
        self.add_attendance(first_sessions, self.below, present=7)
        self.add_attendance(second_sessions, self.below, present=7)

        first_report = self.report_as(self.faculty, self.section)
        second_report = self.report_as(self.faculty, second_section)

        self.assertEqual(len(first_report.json()["students"]), 1)
        self.assertEqual(first_report.json()["students"][0]["threshold"], "75.00")
        self.assertEqual(second_report.json()["students"], [])

    def test_zero_threshold_does_not_classify_zero_attendance_as_below(self):
        self.course.shortage_threshold = Decimal("0.00")
        self.course.save(update_fields=["shortage_threshold"])

        response = self.report_as(self.faculty)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["students"], [])

    def test_report_is_limited_to_students_enrolled_in_requested_section(self):
        other_course = Course.objects.create(code="CS203", title="Databases")
        other_section = Section.objects.create(
            course=other_course,
            code="B",
            faculty=self.faculty,
        )
        other_student = get_user_model().objects.create_user(
            email="other-student@example.com",
            name="Other Section Student",
            role="student",
        )
        Enrollment.objects.create(section=other_section, student=other_student)

        response = self.report_as(self.faculty, other_section)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [entry["student_name"] for entry in response.json()["students"]],
            ["Other Section Student"],
        )

    def test_missing_malformed_and_unknown_section_ids_are_rejected(self):
        self.client.force_authenticate(user=self.faculty)

        missing = self.client.get(self.url)
        malformed = self.client.get(self.url, {"section_id": "nope"})
        zero = self.client.get(self.url, {"section_id": 0})
        unknown = self.client.get(self.url, {"section_id": 99999})

        self.assertEqual(missing.status_code, 400)
        self.assertEqual(malformed.status_code, 400)
        self.assertEqual(zero.status_code, 400)
        self.assertEqual(unknown.status_code, 404)

    def test_authentication_and_section_authorization_are_enforced(self):
        self.assertEqual(self.client.get(self.url).status_code, 401)

        with self.assertLogs("users.permissions", level="WARNING"):
            student = self.report_as(self.below)
        other_faculty = self.report_as(self.other_faculty)
        administrator = self.report_as(self.admin)
        assigned_faculty = self.report_as(self.faculty)

        self.assertEqual(student.status_code, 403)
        self.assertEqual(other_faculty.status_code, 403)
        self.assertEqual(administrator.status_code, 200)
        self.assertEqual(assigned_faculty.status_code, 200)
