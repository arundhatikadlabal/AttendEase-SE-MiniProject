from datetime import date

from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from analytics.models import (
    AttendanceRecord,
    AttendanceSession,
    Course,
    Enrollment,
    Section,
)
from users.models import User


class StudentDashboardTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.student = User.objects.create_user(
            email="student@example.com", name="Student", role=User.Role.STUDENT
        )
        cls.other_student = User.objects.create_user(
            email="other@example.com", name="Other", role=User.Role.STUDENT
        )
        cls.faculty = User.objects.create_user(
            email="faculty@example.com", name="Faculty", role=User.Role.FACULTY
        )
        cls.course = Course.objects.create(code="CS101", title="Software Engineering")
        cls.section = Section.objects.create(course=cls.course, code="A", faculty=cls.faculty)
        Enrollment.objects.create(section=cls.section, student=cls.student)
        Enrollment.objects.create(section=cls.section, student=cls.other_student)
        cls.closed_present = AttendanceSession.objects.create(
            section=cls.section, date=date(2026, 10, 1), closed=True
        )
        cls.closed_absent = AttendanceSession.objects.create(
            section=cls.section, date=date(2026, 10, 2), closed=True
        )
        cls.open_session = AttendanceSession.objects.create(
            section=cls.section, date=date(2026, 10, 3), closed=False
        )
        AttendanceRecord.objects.create(
            session=cls.closed_present, student=cls.student, status=AttendanceRecord.Status.PRESENT
        )
        AttendanceRecord.objects.create(
            session=cls.closed_absent, student=cls.student, status=AttendanceRecord.Status.ABSENT
        )
        AttendanceRecord.objects.create(
            session=cls.open_session, student=cls.student, status=AttendanceRecord.Status.PRESENT
        )

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(self.student)
        self.url = reverse("student-dashboard")

    def test_tc06_course_percentage_counts_only_closed_sessions(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data["courses"]), 1)
        course = response.data["courses"][0]
        self.assertEqual(course["course_code"], "CS101")
        self.assertEqual(str(course["attendance_percentage"]), "50.00")

    def test_student_only_sees_enrolled_courses(self):
        other_course = Course.objects.create(code="CS202", title="Other")
        Section.objects.create(course=other_course, code="A", faculty=self.faculty)
        response = self.client.get(self.url)
        self.assertEqual([item["course_code"] for item in response.data["courses"]], ["CS101"])

    def test_dashboard_is_student_only(self):
        self.client.force_authenticate(self.faculty)
        self.assertEqual(self.client.get(self.url).status_code, 403)
        self.client.force_authenticate(None)
        self.assertEqual(self.client.get(self.url).status_code, 401)
