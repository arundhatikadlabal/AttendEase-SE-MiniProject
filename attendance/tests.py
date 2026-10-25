from datetime import date

from django.db import IntegrityError, transaction
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


class AttendanceSubmissionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.faculty = User.objects.create_user(
            email="faculty@example.com", name="Faculty", role=User.Role.FACULTY
        )
        cls.other_faculty = User.objects.create_user(
            email="other-faculty@example.com", name="Other", role=User.Role.FACULTY
        )
        cls.admin = User.objects.create_superuser(
            email="admin@example.com", password="test-password", name="Admin"
        )
        cls.students = [
            User.objects.create_user(
                email=f"student{i}@example.com",
                name=f"Student {i}",
                role=User.Role.STUDENT,
            )
            for i in range(3)
        ]
        cls.course = Course.objects.create(code="CS101", title="Software Engineering")
        cls.section = Section.objects.create(
            course=cls.course, code="A", faculty=cls.faculty
        )
        Enrollment.objects.bulk_create(
            [
                Enrollment(section=cls.section, student=student)
                for student in cls.students[:2]
            ]
        )
        cls.session = AttendanceSession.objects.create(
            section=cls.section, date=date(2026, 10, 19)
        )

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(self.faculty)
        self.url = reverse("attendance-records", args=[self.session.pk])

    def post(self, records):
        return self.client.post(self.url, {"records": records}, format="json")

    def entry(self, index=0, status="present"):
        return {"student_id": self.students[index].pk, "status": status}

    def test_valid_batch_saves_present_and_absent(self):
        response = self.post([self.entry(), self.entry(1, "absent")])
        self.assertEqual(response.status_code, 200)
        self.assertEqual([r["status"] for r in response.data], ["present", "absent"])
        self.assertEqual(AttendanceRecord.objects.count(), 2)

    def test_tc05_repeated_submission_returns_409_without_overwrite(self):
        self.assertEqual(self.post([self.entry()]).status_code, 200)
        response = self.post([self.entry(status="absent")])
        self.assertEqual(response.status_code, 409)
        self.assertIn("already exists", str(response.data))
        self.assertEqual(AttendanceRecord.objects.count(), 1)
        self.assertEqual(
            AttendanceRecord.objects.get().status, AttendanceRecord.Status.PRESENT
        )

    def test_duplicate_inside_batch_returns_409_and_saves_nothing(self):
        response = self.post([self.entry(), self.entry(status="absent")])
        self.assertEqual(response.status_code, 409)
        self.assertFalse(AttendanceRecord.objects.exists())

    def test_existing_duplicate_rejects_whole_batch(self):
        self.post([self.entry()])
        response = self.post([self.entry(1), self.entry()])
        self.assertEqual(response.status_code, 409)
        self.assertFalse(
            AttendanceRecord.objects.filter(student=self.students[1]).exists()
        )

    def test_database_constraint_protects_direct_writes(self):
        self.post([self.entry()])
        with self.assertRaises(IntegrityError), transaction.atomic():
            AttendanceRecord.objects.create(
                session=self.session, student=self.students[0], status="ABSENT"
            )
        self.assertEqual(AttendanceRecord.objects.count(), 1)

    def test_same_student_can_have_records_in_different_sessions(self):
        self.post([self.entry()])
        second = AttendanceSession.objects.create(
            section=self.section, date=date(2026, 10, 20)
        )
        self.url = reverse("attendance-records", args=[second.pk])
        self.assertEqual(self.post([self.entry()]).status_code, 200)
        self.assertEqual(AttendanceRecord.objects.count(), 2)

    def test_unenrolled_student_rejects_whole_batch(self):
        self.assertEqual(self.post([self.entry(), self.entry(2)]).status_code, 400)
        self.assertFalse(AttendanceRecord.objects.exists())

    def test_inactive_student_is_rejected(self):
        User.objects.filter(pk=self.students[0].pk).update(is_active=False)
        self.assertEqual(self.post([self.entry()]).status_code, 400)
        self.assertFalse(AttendanceRecord.objects.exists())

    def test_bad_payloads_are_rejected_without_writes(self):
        for records in (
            [],
            [self.entry(status="late")],
            [{"student_id": -1, "status": "present"}],
            [{}],
        ):
            with self.subTest(records=records):
                self.assertEqual(self.post(records).status_code, 400)
        self.assertFalse(AttendanceRecord.objects.exists())

    def test_missing_records_is_rejected(self):
        self.assertEqual(self.client.post(self.url, {}, format="json").status_code, 400)

    def test_closed_session_is_rejected(self):
        AttendanceSession.objects.filter(pk=self.session.pk).update(closed=True)
        self.assertEqual(self.post([self.entry()]).status_code, 400)
        self.assertFalse(AttendanceRecord.objects.exists())

    def test_other_faculty_cannot_mark_this_section(self):
        self.client.force_authenticate(self.other_faculty)
        self.assertEqual(self.post([self.entry()]).status_code, 403)
        self.assertFalse(AttendanceRecord.objects.exists())

    def test_student_and_admin_cannot_submit_attendance(self):
        for user in (self.students[0], self.admin):
            with self.subTest(role=user.role):
                self.client.force_authenticate(user)
                self.assertEqual(self.post([self.entry()]).status_code, 403)
        self.assertFalse(AttendanceRecord.objects.exists())

    def test_anonymous_request_requires_authentication(self):
        self.client.force_authenticate(None)
        self.assertEqual(self.post([self.entry()]).status_code, 401)

    def test_unknown_session_returns_404(self):
        self.url = reverse("attendance-records", args=[999999])
        self.assertEqual(self.post([self.entry()]).status_code, 404)
