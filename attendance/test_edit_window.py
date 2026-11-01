from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.test import APIClient

from analytics.models import (
    AttendanceRecord,
    AttendanceSession,
    Course,
    Enrollment,
    Section,
)
from analytics.services import calculate_attendance_percentage
from users.models import User

from .services import edit_closed_record


@override_settings(ATTENDANCE_EDIT_WINDOW_SECONDS=86400)
class AttendanceEditWindowTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.faculty = User.objects.create_user(
            email="faculty@example.com",
            name="Faculty",
            role=User.Role.FACULTY,
            password="StrongPass123!",
        )
        cls.other_faculty = User.objects.create_user(
            email="other@example.com", name="Other Faculty", role=User.Role.FACULTY
        )
        cls.student = User.objects.create_user(
            email="student@example.com", name="Student", role=User.Role.STUDENT
        )
        cls.admin = User.objects.create_superuser(
            email="admin@example.com", name="Admin", password="StrongPass123!"
        )
        cls.course = Course.objects.create(code="CS101", title="Software Engineering")
        cls.section = Section.objects.create(
            course=cls.course, code="A", faculty=cls.faculty
        )
        Enrollment.objects.create(section=cls.section, student=cls.student)
        cls.now = timezone.now()
        cls.closed_at = cls.now - timedelta(hours=1)
        cls.session = AttendanceSession.objects.create(
            section=cls.section,
            date=timezone.localdate() - timedelta(days=1),
            closed=True,
            closed_at=cls.closed_at,
        )
        cls.record = AttendanceRecord.objects.create(
            session=cls.session, student=cls.student, status="ABSENT"
        )

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(self.faculty)
        self.url = reverse(
            "attendance-student-mark", args=[self.session.pk, self.student.pk]
        )

    def edit(self, status="present", **extra):
        return self.client.patch(self.url, {"status": status, **extra}, format="json")

    def assert_unchanged(self):
        self.record.refresh_from_db()
        self.assertEqual(self.record.status, "ABSENT")

    def test_assigned_faculty_can_edit_without_reopening_or_duplicate(self):
        response = self.edit()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["status"], "present")
        self.assertEqual(response.data["id"], self.record.pk)
        self.record.refresh_from_db()
        self.session.refresh_from_db()
        self.assertEqual(self.record.status, "PRESENT")
        self.assertEqual(AttendanceRecord.objects.count(), 1)
        self.assertTrue(self.session.closed)
        self.assertEqual(self.session.closed_at, self.closed_at)
        self.assertEqual(
            calculate_attendance_percentage(self.student, self.course),
            Decimal("100.00"),
        )

    def test_can_change_back_to_absent_within_window(self):
        self.assertEqual(self.edit().status_code, 200)
        self.assertEqual(self.edit("absent").status_code, 200)
        self.assert_unchanged()

    def test_deadline_boundary_is_exclusive(self):
        deadline = self.closed_at + timedelta(seconds=86400)
        for instant, expected in (
            (deadline - timedelta(microseconds=1), 200),
            (deadline, 403),
            (deadline + timedelta(microseconds=1), 403),
        ):
            with (
                self.subTest(instant=instant),
                patch("attendance.services.timezone.now", return_value=instant),
            ):
                AttendanceRecord.objects.filter(pk=self.record.pk).update(
                    status="ABSENT"
                )
                self.assertEqual(self.edit().status_code, expected)
                if expected == 403:
                    self.assert_unchanged()

    def test_exact_closure_time_is_allowed(self):
        with patch("attendance.services.timezone.now", return_value=self.closed_at):
            self.assertEqual(self.edit().status_code, 200)

    @override_settings(ATTENDANCE_EDIT_WINDOW_SECONDS=1800)
    def test_shorter_configured_window_is_enforced(self):
        self.assertEqual(self.edit().status_code, 403)
        self.assert_unchanged()

    @override_settings(ATTENDANCE_EDIT_WINDOW_SECONDS=172800)
    def test_longer_configured_window_allows_older_closed_session(self):
        AttendanceSession.objects.filter(pk=self.session.pk).update(
            closed_at=self.now - timedelta(hours=30)
        )
        self.assertEqual(self.edit().status_code, 200)

    @override_settings(ATTENDANCE_EDIT_WINDOW_SECONDS=0)
    def test_zero_disables_direct_edits(self):
        self.assertEqual(self.edit().status_code, 403)
        self.assert_unchanged()

    def test_missing_closure_timestamp_is_rejected(self):
        AttendanceSession.objects.filter(pk=self.session.pk).update(closed_at=None)
        self.assertEqual(self.edit().status_code, 400)
        self.assert_unchanged()

    def test_future_closure_timestamp_is_rejected(self):
        AttendanceSession.objects.filter(pk=self.session.pk).update(
            closed_at=timezone.now() + timedelta(hours=1)
        )
        self.assertEqual(self.edit().status_code, 400)
        self.assert_unchanged()

    def test_open_session_uses_normal_put_instead(self):
        AttendanceSession.objects.filter(pk=self.session.pk).update(
            closed=False, closed_at=None
        )
        self.assertEqual(self.edit().status_code, 400)
        self.assert_unchanged()
        response = self.client.put(self.url, {"status": "present"}, format="json")
        self.assertEqual(response.status_code, 200)

    def test_closed_session_put_remains_blocked(self):
        self.assertEqual(
            self.client.put(self.url, {"status": "present"}, format="json").status_code,
            400,
        )
        self.assert_unchanged()

    def test_wrong_faculty_cannot_edit(self):
        self.client.force_authenticate(self.other_faculty)
        self.assertEqual(self.edit().status_code, 403)
        self.assert_unchanged()

    def test_current_assignment_controls_access(self):
        Section.objects.filter(pk=self.section.pk).update(faculty=self.other_faculty)
        self.assertEqual(self.edit().status_code, 403)
        self.client.force_authenticate(self.other_faculty)
        self.assertEqual(self.edit().status_code, 200)

    def test_student_admin_and_anonymous_cannot_edit(self):
        for user, expected in ((self.student, 403), (self.admin, 403), (None, 401)):
            with self.subTest(user=user):
                self.client.force_authenticate(user)
                self.assertEqual(self.edit().status_code, expected)
        self.assert_unchanged()

    def test_inactive_faculty_cannot_edit(self):
        self.faculty.is_active = False
        self.faculty.save(update_fields=["is_active"])
        self.assertEqual(self.edit().status_code, 403)
        self.assert_unchanged()

    def test_unknown_session_and_missing_record_return_404_without_creating_records(
        self,
    ):
        for args in ([999999, self.student.pk], [self.session.pk, 999999]):
            with self.subTest(args=args):
                self.url = reverse("attendance-student-mark", args=args)
                self.assertEqual(self.edit().status_code, 404)
        self.assertEqual(AttendanceRecord.objects.count(), 1)
        self.assert_unchanged()

    def test_invalid_or_missing_status_is_rejected(self):
        for payload in ({}, {"status": "late"}, {"status": None}, {"status": ""}):
            with self.subTest(payload=payload):
                self.assertEqual(
                    self.client.patch(self.url, payload, format="json").status_code, 400
                )
        self.assert_unchanged()

    def test_caller_cannot_extend_window_or_change_record_identity(self):
        AttendanceSession.objects.filter(pk=self.session.pk).update(
            closed_at=self.now - timedelta(days=2)
        )
        self.assertEqual(
            self.edit(
                closed_at=self.now.isoformat(),
                edit_window=999999,
                student_id=self.admin.pk,
            ).status_code,
            403,
        )
        self.assert_unchanged()

    def test_future_session_date_is_rejected(self):
        AttendanceSession.objects.filter(pk=self.session.pk).update(
            date=timezone.localdate() + timedelta(days=1)
        )
        self.assertEqual(self.edit().status_code, 400)
        self.assert_unchanged()

    def test_service_checks_permissions_and_status_independently(self):
        with self.assertRaises(PermissionDenied):
            edit_closed_record(
                faculty=self.student,
                session_id=self.session.pk,
                student_id=self.student.pk,
                status="present",
            )
        with self.assertRaises(ValidationError):
            edit_closed_record(
                faculty=self.faculty,
                session_id=self.session.pk,
                student_id=self.student.pk,
                status="late",
            )
        self.assert_unchanged()

    def test_real_faculty_jwt_can_edit(self):
        self.client.force_authenticate(None)
        login = self.client.post(
            reverse("login"),
            {"email": self.faculty.email, "password": "StrongPass123!"},
            format="json",
        )
        self.assertEqual(login.status_code, 200)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {login.data['access']}")
        self.assertEqual(self.edit().status_code, 200)

    def test_edit_does_not_change_another_students_record(self):
        other = User.objects.create_user(
            email="another@example.com", name="Another", role=User.Role.STUDENT
        )
        other_record = AttendanceRecord.objects.create(
            session=self.session, student=other, status="ABSENT"
        )
        self.assertEqual(self.edit().status_code, 200)
        other_record.refresh_from_db()
        self.assertEqual(other_record.status, "ABSENT")
