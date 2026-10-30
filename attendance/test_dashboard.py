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
        cls.section = Section.objects.create(
            course=cls.course, code="A", faculty=cls.faculty
        )
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
            session=cls.closed_present,
            student=cls.student,
            status=AttendanceRecord.Status.PRESENT,
        )
        AttendanceRecord.objects.create(
            session=cls.closed_absent,
            student=cls.student,
            status=AttendanceRecord.Status.ABSENT,
        )
        AttendanceRecord.objects.create(
            session=cls.open_session,
            student=cls.student,
            status=AttendanceRecord.Status.PRESENT,
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
        self.assertEqual(
            [item["course_code"] for item in response.data["courses"]], ["CS101"]
        )

    def test_fr022_flags_courses_below_their_own_threshold(self):
        course = self.client.get(self.url).data["courses"][0]
        self.assertEqual(str(course["threshold"]), "75.00")
        self.assertTrue(course["below_threshold"])

        self.course.shortage_threshold = 40
        self.course.save(update_fields=["shortage_threshold"])
        course = self.client.get(self.url).data["courses"][0]
        self.assertFalse(course["below_threshold"])

    def test_dashboard_is_student_only(self):
        self.client.force_authenticate(self.faculty)
        self.assertEqual(self.client.get(self.url).status_code, 403)
        self.client.force_authenticate(None)
        self.assertEqual(self.client.get(self.url).status_code, 401)

    def test_tc06_session_history_is_closed_and_student_scoped(self):
        AttendanceRecord.objects.create(
            session=self.closed_absent,
            student=self.other_student,
            status=AttendanceRecord.Status.PRESENT,
        )
        response = self.client.get(reverse("student-history"))
        self.assertEqual(response.status_code, 200)
        history = response.data["history"]
        self.assertEqual(len(history), 2)
        self.assertEqual(
            [item["date"] for item in history], ["2026-10-02", "2026-10-01"]
        )
        self.assertEqual([item["status"] for item in history], ["absent", "present"])
        self.assertTrue(all(item["course_code"] == "CS101" for item in history))
        self.assertTrue(all(item["section_code"] == "A" for item in history))

    def test_history_requires_student_authentication(self):
        self.client.force_authenticate(self.faculty)
        self.assertEqual(self.client.get(reverse("student-history")).status_code, 403)
        self.client.force_authenticate(None)
        self.assertEqual(self.client.get(reverse("student-history")).status_code, 401)

    def test_fr023_history_filters_inclusive_date_range(self):
        url = reverse("student-history")
        response = self.client.get(url, {"from": "2026-10-02", "to": "2026-10-02"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [item["date"] for item in response.data["history"]], ["2026-10-02"]
        )
        self.assertEqual(
            [
                item["date"]
                for item in self.client.get(url, {"to": "2026-10-01"}).data["history"]
            ],
            ["2026-10-01"],
        )

    def test_fr023_rejects_bad_or_reversed_dates(self):
        url = reverse("student-history")
        for query in (
            {"from": "2026-02-30"},
            {"to": "2026-1-02"},
            {"from": "bad"},
            {"from": "2026-10-03", "to": "2026-10-01"},
        ):
            with self.subTest(query=query):
                self.assertEqual(self.client.get(url, query).status_code, 400)
