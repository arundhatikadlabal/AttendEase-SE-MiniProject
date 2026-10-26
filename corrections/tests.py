from datetime import date

from django.db import IntegrityError, transaction
from django.db.models.deletion import ProtectedError
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

from .models import CorrectionRequest
from .services import submit_correction


class CorrectionSubmissionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.student = User.objects.create_user(
            email="student@example.com",
            name="Student",
            role=User.Role.STUDENT,
            password="StrongPass123!",
        )
        cls.other_student = User.objects.create_user(
            email="other@example.com", name="Other Student", role=User.Role.STUDENT
        )
        cls.faculty = User.objects.create_user(
            email="faculty@example.com", name="Faculty", role=User.Role.FACULTY
        )
        cls.admin = User.objects.create_superuser(
            email="admin@example.com", name="Admin", password="StrongPass123!"
        )
        cls.course = Course.objects.create(code="CS101", title="Software Engineering")
        cls.section = Section.objects.create(
            course=cls.course, code="A", faculty=cls.faculty
        )
        Enrollment.objects.bulk_create(
            [
                Enrollment(section=cls.section, student=cls.student),
                Enrollment(section=cls.section, student=cls.other_student),
            ]
        )
        cls.session = AttendanceSession.objects.create(
            section=cls.section, date=date(2026, 10, 19), closed=True
        )
        cls.record = AttendanceRecord.objects.create(
            session=cls.session,
            student=cls.student,
            status=AttendanceRecord.Status.ABSENT,
        )
        cls.other_record = AttendanceRecord.objects.create(
            session=cls.session,
            student=cls.other_student,
            status=AttendanceRecord.Status.ABSENT,
        )

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(self.student)
        self.url = reverse("correction-submit")

    def post(self, **overrides):
        payload = {"record_id": self.record.pk, "reason": "I attended this class."}
        payload.update(overrides)
        return self.client.post(self.url, payload, format="json")

    def test_tc07_valid_request_is_pending_and_leaves_attendance_unchanged(self):
        response = self.post()
        self.assertEqual(response.status_code, 201)
        correction = CorrectionRequest.objects.get()
        self.assertEqual(response.data["id"], correction.pk)
        self.assertEqual(response.data["record_id"], self.record.pk)
        self.assertEqual(response.data["student_id"], self.student.pk)
        self.assertEqual(response.data["status"], "PENDING")
        self.assertEqual(correction.reason, "I attended this class.")
        self.assertEqual(correction.student, self.student)
        self.assertIsNone(correction.acted_by)
        self.assertIsNone(correction.acted_at)
        self.assertIsNotNone(correction.created_at)
        self.record.refresh_from_db()
        self.assertEqual(self.record.status, AttendanceRecord.Status.ABSENT)

    def test_reason_is_trimmed(self):
        self.assertEqual(self.post(reason="  I was present.  ").status_code, 201)
        self.assertEqual(CorrectionRequest.objects.get().reason, "I was present.")

    def test_duplicate_pending_request_returns_409_and_preserves_original(self):
        self.assertEqual(self.post().status_code, 201)
        response = self.post(reason="A second request")
        self.assertEqual(response.status_code, 409)
        self.assertIn("pending", str(response.data).lower())
        self.assertEqual(CorrectionRequest.objects.count(), 1)
        self.assertEqual(
            CorrectionRequest.objects.get().reason, "I attended this class."
        )

    def test_database_also_blocks_two_pending_requests(self):
        self.post()
        with self.assertRaises(IntegrityError), transaction.atomic():
            CorrectionRequest.objects.create(
                record=self.record, student=self.student, reason="Duplicate"
            )
        self.assertEqual(CorrectionRequest.objects.count(), 1)

    def test_resolved_requests_do_not_block_a_new_pending_request(self):
        for status in (
            CorrectionRequest.Status.APPROVED,
            CorrectionRequest.Status.REJECTED,
        ):
            CorrectionRequest.objects.create(
                record=self.record,
                student=self.student,
                reason="Earlier request",
                status=status,
            )
        self.assertEqual(self.post().status_code, 201)
        self.assertEqual(CorrectionRequest.objects.count(), 3)
        self.assertEqual(CorrectionRequest.objects.filter(status="PENDING").count(), 1)

    def test_distinct_records_can_each_have_a_pending_request(self):
        second_session = AttendanceSession.objects.create(
            section=self.section, date=date(2026, 10, 20), closed=True
        )
        second_record = AttendanceRecord.objects.create(
            session=second_session, student=self.student, status="ABSENT"
        )
        self.assertEqual(self.post().status_code, 201)
        self.assertEqual(self.post(record_id=second_record.pk).status_code, 201)
        self.assertEqual(CorrectionRequest.objects.count(), 2)

    def test_another_students_record_is_not_disclosed(self):
        response = self.post(record_id=self.other_record.pk)
        self.assertEqual(response.status_code, 404)
        self.assertFalse(CorrectionRequest.objects.exists())

    def test_nonexistent_record_returns_404(self):
        self.assertEqual(self.post(record_id=999999).status_code, 404)
        self.assertFalse(CorrectionRequest.objects.exists())

    def test_unenrolled_student_cannot_request_correction(self):
        Enrollment.objects.filter(student=self.student).delete()
        self.assertEqual(self.post().status_code, 403)
        self.assertFalse(CorrectionRequest.objects.exists())

    def test_faculty_and_admin_cannot_submit_student_requests(self):
        for user in (self.faculty, self.admin):
            with self.subTest(role=user.role):
                self.client.force_authenticate(user)
                self.assertEqual(self.post().status_code, 403)
        self.assertFalse(CorrectionRequest.objects.exists())

    def test_anonymous_request_requires_authentication(self):
        self.client.force_authenticate(None)
        self.assertEqual(self.post().status_code, 401)
        self.assertFalse(CorrectionRequest.objects.exists())

    def test_inactive_student_is_rejected(self):
        self.student.is_active = False
        self.student.save(update_fields=["is_active"])
        self.assertEqual(self.post().status_code, 403)
        self.assertFalse(CorrectionRequest.objects.exists())

    def test_real_jwt_authentication_can_submit_request(self):
        self.client.force_authenticate(None)
        login = self.client.post(
            reverse("login"),
            {"email": self.student.email, "password": "StrongPass123!"},
            format="json",
        )
        self.assertEqual(login.status_code, 200)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {login.data['access']}")
        self.assertEqual(self.post().status_code, 201)

    def test_blank_null_and_oversized_reasons_are_rejected(self):
        for reason in ("", "   ", None, "x" * 2001):
            with self.subTest(
                reason_length=len(reason) if reason is not None else None
            ):
                self.assertEqual(self.post(reason=reason).status_code, 400)
        self.assertFalse(CorrectionRequest.objects.exists())

    def test_maximum_length_reason_is_accepted(self):
        self.assertEqual(self.post(reason="x" * 2000).status_code, 201)

    def test_invalid_record_ids_are_rejected(self):
        for record_id in (None, -1, 0, "invalid", 1.5):
            with self.subTest(record_id=record_id):
                self.assertEqual(self.post(record_id=record_id).status_code, 400)
        self.assertFalse(CorrectionRequest.objects.exists())

    def test_missing_required_fields_are_rejected(self):
        for payload in ({}, {"record_id": self.record.pk}, {"reason": "Present"}):
            with self.subTest(payload=payload):
                response = self.client.post(self.url, payload, format="json")
                self.assertEqual(response.status_code, 400)
        self.assertFalse(CorrectionRequest.objects.exists())

    def test_client_cannot_override_identity_status_or_audit_fields(self):
        response = self.post(
            student_id=self.other_student.pk,
            student=self.other_student.pk,
            status="APPROVED",
            acted_by=self.faculty.pk,
            acted_at="2026-10-20T10:00:00Z",
        )
        self.assertEqual(response.status_code, 201)
        correction = CorrectionRequest.objects.get()
        self.assertEqual(correction.student, self.student)
        self.assertEqual(correction.status, "PENDING")
        self.assertIsNone(correction.acted_by)
        self.assertIsNone(correction.acted_at)

    def test_service_rejects_blank_reason_independently_of_api(self):
        from rest_framework.exceptions import ValidationError

        with self.assertRaises(ValidationError):
            submit_correction(
                student=self.student, record_id=self.record.pk, reason=" "
            )
        self.assertFalse(CorrectionRequest.objects.exists())

    def test_attendance_record_with_request_is_protected_from_deletion(self):
        self.post()
        with self.assertRaises(ProtectedError):
            self.record.delete()
        self.assertTrue(AttendanceRecord.objects.filter(pk=self.record.pk).exists())
