from datetime import date
from decimal import Decimal
from unittest.mock import patch

from django.db import DatabaseError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied
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

from .models import CorrectionRequest
from .services import approve_correction


class CorrectionApprovalTests(TestCase):
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
        cls.session = AttendanceSession.objects.create(
            section=cls.section, date=date(2026, 10, 19), closed=True
        )
        cls.record = AttendanceRecord.objects.create(
            session=cls.session, student=cls.student, status="ABSENT"
        )
        cls.correction = CorrectionRequest.objects.create(
            record=cls.record, student=cls.student, reason="I attended this class."
        )

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(self.faculty)
        self.url = reverse("correction-decision", args=[self.correction.pk])

    def approve(self, **extra):
        return self.client.patch(
            self.url, {"action": "approve", **extra}, format="json"
        )

    def assert_pending_unchanged(self):
        self.record.refresh_from_db()
        self.correction.refresh_from_db()
        self.assertEqual(self.record.status, "ABSENT")
        self.assertEqual(self.correction.status, "PENDING")
        self.assertIsNone(self.correction.acted_by_id)
        self.assertIsNone(self.correction.acted_at)

    def test_tc08_approval_updates_attendance_and_records_server_audit_fields(self):
        before = timezone.now()
        response = self.approve()
        after = timezone.now()
        self.assertEqual(response.status_code, 200)
        self.record.refresh_from_db()
        self.correction.refresh_from_db()
        self.assertEqual(self.record.status, "PRESENT")
        self.assertEqual(self.correction.status, "APPROVED")
        self.assertEqual(self.correction.acted_by_id, self.faculty.pk)
        self.assertLessEqual(before, self.correction.acted_at)
        self.assertLessEqual(self.correction.acted_at, after)
        self.assertEqual(response.data["status"], "APPROVED")
        self.assertEqual(response.data["acted_by"], self.faculty.pk)
        self.assertEqual(
            response.data["acted_at"], self.correction.acted_at.isoformat()
        )
        self.assertEqual(self.correction.reason, "I attended this class.")
        self.assertEqual(AttendanceRecord.objects.count(), 1)
        self.session.refresh_from_db()
        self.assertTrue(self.session.closed)

    def test_approved_request_leaves_queue_and_updates_existing_analytics(self):
        self.assertEqual(
            calculate_attendance_percentage(self.student, self.course), Decimal("0.00")
        )
        self.assertEqual(self.approve().status_code, 200)
        queue = self.client.get(reverse("correction-submit"))
        self.assertEqual(queue.data["count"], 0)
        self.assertEqual(
            calculate_attendance_percentage(self.student, self.course),
            Decimal("100.00"),
        )

    def test_repeated_approval_returns_409_and_preserves_decision(self):
        self.assertEqual(self.approve().status_code, 200)
        self.correction.refresh_from_db()
        acted_at = self.correction.acted_at
        response = self.approve()
        self.assertEqual(response.status_code, 409)
        self.correction.refresh_from_db()
        self.assertEqual(self.correction.acted_at, acted_at)
        self.assertEqual(self.correction.acted_by_id, self.faculty.pk)

    def test_rejected_request_cannot_be_approved(self):
        decided_at = timezone.now()
        CorrectionRequest.objects.filter(pk=self.correction.pk).update(
            status="REJECTED", acted_by=self.faculty, acted_at=decided_at
        )
        self.assertEqual(self.approve().status_code, 409)
        self.correction.refresh_from_db()
        self.record.refresh_from_db()
        self.assertEqual(self.correction.status, "REJECTED")
        self.assertEqual(self.correction.acted_at, decided_at)
        self.assertEqual(self.record.status, "ABSENT")

    def test_wrong_faculty_cannot_approve(self):
        self.client.force_authenticate(self.other_faculty)
        self.assertEqual(self.approve().status_code, 403)
        self.assert_pending_unchanged()

    def test_current_assignment_controls_access(self):
        Section.objects.filter(pk=self.section.pk).update(faculty=self.other_faculty)
        self.assertEqual(self.approve().status_code, 403)
        self.client.force_authenticate(self.other_faculty)
        self.assertEqual(self.approve().status_code, 200)
        self.correction.refresh_from_db()
        self.assertEqual(self.correction.acted_by_id, self.other_faculty.pk)

    def test_unassigned_section_cannot_be_approved(self):
        Section.objects.filter(pk=self.section.pk).update(faculty=None)
        self.assertEqual(self.approve().status_code, 403)
        self.assert_pending_unchanged()

    def test_student_and_admin_cannot_approve(self):
        for user in (self.student, self.admin):
            with self.subTest(role=user.role):
                self.client.force_authenticate(user)
                self.assertEqual(self.approve().status_code, 403)
        self.assert_pending_unchanged()

    def test_anonymous_requires_authentication(self):
        self.client.force_authenticate(None)
        self.assertEqual(self.approve().status_code, 401)
        self.assert_pending_unchanged()

    def test_inactive_faculty_cannot_approve(self):
        self.faculty.is_active = False
        self.faculty.save(update_fields=["is_active"])
        self.assertEqual(self.approve().status_code, 403)
        self.assert_pending_unchanged()

    def test_unknown_request_returns_404(self):
        response = self.client.patch(
            reverse("correction-decision", args=[999999]),
            {"action": "approve"},
            format="json",
        )
        self.assertEqual(response.status_code, 404)
        self.assert_pending_unchanged()

    def test_invalid_or_missing_action_is_rejected(self):
        for payload in (
            {},
            {"action": "reject"},
            {"action": "delete"},
            {"action": None},
        ):
            with self.subTest(payload=payload):
                self.assertEqual(
                    self.client.patch(self.url, payload, format="json").status_code, 400
                )
        self.assert_pending_unchanged()

    def test_client_cannot_forge_attendance_or_decision_metadata(self):
        response = self.approve(
            status="REJECTED",
            acted_by=self.other_faculty.pk,
            acted_at="2000-01-01T00:00:00Z",
            student_id=self.admin.pk,
            record_id=999999,
            reason="Overwritten reason",
            attendance_status="ABSENT",
        )
        self.assertEqual(response.status_code, 200)
        self.correction.refresh_from_db()
        self.record.refresh_from_db()
        self.assertEqual(self.correction.acted_by_id, self.faculty.pk)
        self.assertEqual(self.correction.student_id, self.student.pk)
        self.assertEqual(self.correction.record_id, self.record.pk)
        self.assertEqual(self.correction.reason, "I attended this class.")
        self.assertEqual(self.record.status, "PRESENT")

    def test_failed_decision_save_rolls_back_attendance_change(self):
        with patch.object(
            CorrectionRequest, "save", side_effect=DatabaseError("Simulated failure")
        ), self.assertRaises(DatabaseError):
            approve_correction(
                faculty=self.faculty, correction_id=self.correction.pk
            )
        self.assert_pending_unchanged()

    def test_service_enforces_role_independently_of_view(self):
        with self.assertRaises(PermissionDenied):
            approve_correction(faculty=self.student, correction_id=self.correction.pk)
        self.assert_pending_unchanged()

    def test_real_faculty_jwt_can_approve(self):
        self.client.force_authenticate(None)
        login = self.client.post(
            reverse("login"),
            {"email": self.faculty.email, "password": "StrongPass123!"},
            format="json",
        )
        self.assertEqual(login.status_code, 200)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {login.data['access']}")
        self.assertEqual(self.approve().status_code, 200)

    def test_approval_preserves_other_students_attendance(self):
        other = User.objects.create_user(
            email="another@example.com", name="Another", role=User.Role.STUDENT
        )
        record = AttendanceRecord.objects.create(
            session=self.session, student=other, status="ABSENT"
        )
        self.assertEqual(self.approve().status_code, 200)
        record.refresh_from_db()
        self.assertEqual(record.status, "ABSENT")

    def test_already_present_record_can_be_approved_without_duplicate(self):
        AttendanceRecord.objects.filter(pk=self.record.pk).update(status="PRESENT")
        self.assertEqual(self.approve().status_code, 200)
        self.assertEqual(AttendanceRecord.objects.count(), 1)
        self.correction.refresh_from_db()
        self.assertEqual(self.correction.status, "APPROVED")
