from datetime import date
from decimal import Decimal
from unittest.mock import patch

from django.db import DatabaseError
from django.test import TestCase
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

from .models import CorrectionRequest
from .services import reject_correction, submit_correction


class CorrectionRejectionTests(TestCase):
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

    def reject(self, **overrides):
        payload = {
            "action": "reject",
            "reason": "The attendance register confirms absence.",
        }
        payload.update(overrides)
        return self.client.patch(self.url, payload, format="json")

    def assert_pending_unchanged(self):
        self.correction.refresh_from_db()
        self.record.refresh_from_db()
        self.assertEqual(self.record.status, "ABSENT")
        self.assertEqual(self.correction.status, "PENDING")
        self.assertEqual(self.correction.rejection_reason, "")
        self.assertIsNone(self.correction.acted_by_id)
        self.assertIsNone(self.correction.acted_at)

    def test_rejection_saves_separate_reason_and_server_audit_fields(self):
        before = timezone.now()
        response = self.reject(reason="  Register confirms absence.  ")
        self.assertEqual(response.status_code, 200)
        self.correction.refresh_from_db()
        self.record.refresh_from_db()
        self.assertEqual(self.correction.status, "REJECTED")
        self.assertEqual(self.correction.reason, "I attended this class.")
        self.assertEqual(self.correction.rejection_reason, "Register confirms absence.")
        self.assertEqual(self.correction.acted_by_id, self.faculty.pk)
        self.assertLessEqual(before, self.correction.acted_at)
        self.assertLessEqual(self.correction.acted_at, timezone.now())
        self.assertEqual(
            response.data["rejection_reason"], self.correction.rejection_reason
        )
        self.assertEqual(response.data["acted_by"], self.faculty.pk)
        self.assertEqual(
            response.data["acted_at"], self.correction.acted_at.isoformat()
        )
        self.assertEqual(response.data["status"], "REJECTED")
        self.assertEqual(self.record.status, "ABSENT")

    def test_rejection_removes_queue_item_without_changing_attendance_percentage(self):
        self.assertEqual(self.reject().status_code, 200)
        self.assertEqual(self.client.get(reverse("correction-submit")).data["count"], 0)
        self.assertEqual(
            calculate_attendance_percentage(self.student, self.course), Decimal("0.00")
        )

    def test_missing_blank_null_and_oversized_reasons_are_rejected(self):
        missing = self.client.patch(self.url, {"action": "reject"}, format="json")
        self.assertEqual(missing.status_code, 400)
        for reason in ("", " \n\t ", None, "x" * 2001):
            with self.subTest(reason=reason):
                response = self.reject(reason=reason)
                self.assertEqual(response.status_code, 400)
                self.assertIn("reason", response.data)
        self.assert_pending_unchanged()

    def test_maximum_reason_length_is_accepted(self):
        self.assertEqual(self.reject(reason="x" * 2000).status_code, 200)
        self.correction.refresh_from_db()
        self.assertEqual(len(self.correction.rejection_reason), 2000)

    def test_repeated_rejection_preserves_original_decision(self):
        self.assertEqual(self.reject().status_code, 200)
        self.correction.refresh_from_db()
        original = (self.correction.rejection_reason, self.correction.acted_at)
        self.assertEqual(self.reject(reason="Changed decision").status_code, 409)
        self.correction.refresh_from_db()
        self.assertEqual(
            (self.correction.rejection_reason, self.correction.acted_at), original
        )

    def test_approved_request_cannot_be_rejected(self):
        response = self.client.patch(self.url, {"action": "approve"}, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.reject().status_code, 409)
        self.correction.refresh_from_db()
        self.record.refresh_from_db()
        self.assertEqual(self.correction.status, "APPROVED")
        self.assertEqual(self.correction.rejection_reason, "")
        self.assertEqual(self.record.status, "PRESENT")

    def test_rejected_request_cannot_be_approved(self):
        self.assertEqual(self.reject().status_code, 200)
        response = self.client.patch(self.url, {"action": "approve"}, format="json")
        self.assertEqual(response.status_code, 409)
        self.correction.refresh_from_db()
        self.record.refresh_from_db()
        self.assertEqual(self.correction.status, "REJECTED")
        self.assertEqual(self.record.status, "ABSENT")

    def test_wrong_faculty_cannot_reject(self):
        self.client.force_authenticate(self.other_faculty)
        self.assertEqual(self.reject().status_code, 403)
        self.assert_pending_unchanged()

    def test_reassignment_moves_rejection_permission(self):
        Section.objects.filter(pk=self.section.pk).update(faculty=self.other_faculty)
        self.assertEqual(self.reject().status_code, 403)
        self.client.force_authenticate(self.other_faculty)
        self.assertEqual(self.reject().status_code, 200)
        self.correction.refresh_from_db()
        self.assertEqual(self.correction.acted_by_id, self.other_faculty.pk)

    def test_unassigned_section_cannot_be_rejected(self):
        Section.objects.filter(pk=self.section.pk).update(faculty=None)
        self.assertEqual(self.reject().status_code, 403)
        self.assert_pending_unchanged()

    def test_students_and_admin_cannot_reject(self):
        for user in (self.student, self.admin):
            with self.subTest(role=user.role):
                self.client.force_authenticate(user)
                self.assertEqual(self.reject().status_code, 403)
        self.assert_pending_unchanged()

    def test_anonymous_requires_authentication(self):
        self.client.force_authenticate(None)
        self.assertEqual(self.reject().status_code, 401)
        self.assert_pending_unchanged()

    def test_inactive_faculty_cannot_reject(self):
        self.faculty.is_active = False
        self.faculty.save(update_fields=["is_active"])
        self.assertEqual(self.reject().status_code, 403)
        self.assert_pending_unchanged()

    def test_unknown_request_returns_404(self):
        self.url = reverse("correction-decision", args=[999999])
        self.assertEqual(self.reject().status_code, 404)
        self.assert_pending_unchanged()

    def test_caller_cannot_forge_decision_metadata_or_replace_student_reason(self):
        self.assertEqual(
            self.reject(
                acted_by=self.other_faculty.pk,
                acted_at="2000-01-01T00:00:00Z",
                status="APPROVED",
                rejection_reason="Forged reason",
                record_id=999999,
                student_id=self.admin.pk,
            ).status_code,
            200,
        )
        self.correction.refresh_from_db()
        self.assertEqual(self.correction.acted_by_id, self.faculty.pk)
        self.assertEqual(self.correction.student_id, self.student.pk)
        self.assertEqual(self.correction.record_id, self.record.pk)
        self.assertEqual(self.correction.reason, "I attended this class.")
        self.assertEqual(
            self.correction.rejection_reason,
            "The attendance register confirms absence.",
        )

    def test_service_validates_reason_independently_of_api(self):
        for reason in (None, "", "  ", "x" * 2001):
            with self.subTest(reason=reason), self.assertRaises(ValidationError):
                reject_correction(
                    faculty=self.faculty,
                    correction_id=self.correction.pk,
                    reason=reason,
                )
        self.assert_pending_unchanged()

    def test_service_enforces_role_independently_of_api(self):
        with self.assertRaises(PermissionDenied):
            reject_correction(
                faculty=self.student, correction_id=self.correction.pk, reason="Absent"
            )
        self.assert_pending_unchanged()

    def test_failed_save_leaves_pending_request_and_attendance_unchanged(self):
        with (
            patch.object(
                CorrectionRequest,
                "save",
                side_effect=DatabaseError("Simulated failure"),
            ),
            self.assertRaises(DatabaseError),
        ):
            reject_correction(
                faculty=self.faculty, correction_id=self.correction.pk, reason="Absent"
            )
        self.assert_pending_unchanged()

    def test_student_can_raise_new_request_after_rejection_and_old_reason_is_preserved(
        self,
    ):
        self.assertEqual(self.reject().status_code, 200)
        new = submit_correction(
            student=self.student, record_id=self.record.pk, reason="New evidence"
        )
        self.correction.refresh_from_db()
        self.assertNotEqual(new.pk, self.correction.pk)
        self.assertEqual(new.status, "PENDING")
        self.assertEqual(new.rejection_reason, "")
        self.assertEqual(self.correction.status, "REJECTED")
        self.assertEqual(self.correction.reason, "I attended this class.")

    def test_real_faculty_jwt_can_reject(self):
        self.client.force_authenticate(None)
        login = self.client.post(
            reverse("login"),
            {"email": self.faculty.email, "password": "StrongPass123!"},
            format="json",
        )
        self.assertEqual(login.status_code, 200)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {login.data['access']}")
        self.assertEqual(self.reject().status_code, 200)

    def test_rejection_preserves_present_record_too(self):
        AttendanceRecord.objects.filter(pk=self.record.pk).update(status="PRESENT")
        self.assertEqual(self.reject().status_code, 200)
        self.record.refresh_from_db()
        self.assertEqual(self.record.status, "PRESENT")
