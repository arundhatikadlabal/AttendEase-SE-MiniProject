from datetime import date
from smtplib import SMTPException
from unittest.mock import patch

from django.core import mail
from django.db import transaction
from django.test import TestCase, override_settings
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
from .notifications import notify_faculty
from .services import submit_correction


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    DEFAULT_FROM_EMAIL="attendease@example.com",
)
class CorrectionNotificationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.student = User.objects.create_user(
            email="student@example.com", name="Student", role=User.Role.STUDENT
        )
        cls.faculty = User.objects.create_user(
            email="faculty@example.com", name="Faculty", role=User.Role.FACULTY
        )
        cls.unrelated_faculty = User.objects.create_user(
            email="unrelated@example.com", name="Other Faculty", role=User.Role.FACULTY
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

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(self.student)
        self.url = reverse("correction-submit")

    def submit(self):
        return submit_correction(
            student=self.student,
            record_id=self.record.pk,
            reason="I attended this class.",
        )

    def create_request(self):
        return CorrectionRequest.objects.create(
            record=self.record, student=self.student, reason="I attended this class."
        )

    def test_tc07_success_sends_one_email_only_to_assigned_faculty(self):
        with self.captureOnCommitCallbacks(execute=True) as callbacks:
            response = self.client.post(
                self.url,
                {"record_id": self.record.pk, "reason": "I attended this class."},
                format="json",
            )
            self.assertEqual(response.status_code, 201)
            self.assertEqual(len(mail.outbox), 0)
        self.assertEqual(len(callbacks), 1)
        self.assertEqual(len(mail.outbox), 1)
        email = mail.outbox[0]
        self.assertEqual(email.to, [self.faculty.email])
        self.assertEqual(email.cc, [])
        self.assertEqual(email.bcc, [])
        self.assertEqual(email.from_email, "attendease@example.com")
        self.assertIn(str(response.data["id"]), email.subject)
        for value in (
            "Student",
            "CS101",
            "Section: A",
            "2026-10-19",
            "Absent",
            "I attended this class.",
        ):
            self.assertIn(value, email.body)
        self.assertNotIn(self.unrelated_faculty.email, email.to)
        self.assertEqual(CorrectionRequest.objects.get().status, "PENDING")
        self.record.refresh_from_db()
        self.assertEqual(self.record.status, "ABSENT")

    def test_transaction_rollback_sends_no_email(self):
        with (
            self.captureOnCommitCallbacks(execute=True) as callbacks,
            self.assertRaises(RuntimeError),
            transaction.atomic(),
        ):
            self.submit()
            raise RuntimeError("Rollback submission")
        self.assertEqual(callbacks, [])
        self.assertEqual(len(mail.outbox), 0)
        self.assertFalse(CorrectionRequest.objects.exists())

    def test_duplicate_request_registers_no_email(self):
        self.create_request()
        with self.captureOnCommitCallbacks(execute=True) as callbacks:
            response = self.client.post(
                self.url,
                {"record_id": self.record.pk, "reason": "Duplicate"},
                format="json",
            )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(callbacks, [])
        self.assertEqual(len(mail.outbox), 0)

    def test_invalid_reason_registers_no_email(self):
        with self.captureOnCommitCallbacks(execute=True) as callbacks:
            response = self.client.post(
                self.url, {"record_id": self.record.pk, "reason": " "}, format="json"
            )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(callbacks, [])
        self.assertEqual(len(mail.outbox), 0)

    def test_unauthorized_user_registers_no_email(self):
        self.client.force_authenticate(self.faculty)
        with self.captureOnCommitCallbacks(execute=True) as callbacks:
            response = self.client.post(
                self.url,
                {"record_id": self.record.pk, "reason": "Present"},
                format="json",
            )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(callbacks, [])
        self.assertEqual(len(mail.outbox), 0)

    def test_temporary_smtp_error_retries_once_then_succeeds(self):
        correction = self.create_request()
        with (
            patch(
                "corrections.notifications.send_mail",
                side_effect=[SMTPException("temporary"), 1],
            ) as send,
            self.assertLogs("corrections.notifications", level="WARNING"),
        ):
            self.assertTrue(notify_faculty(correction.pk))
        self.assertEqual(send.call_count, 2)
        self.assertEqual(send.call_args_list[0], send.call_args_list[1])

    def test_successful_delivery_is_not_retried(self):
        correction = self.create_request()
        with patch("corrections.notifications.send_mail", return_value=1) as send:
            self.assertTrue(notify_faculty(correction.pk))
        send.assert_called_once()
        self.assertEqual(send.call_args.kwargs["recipient_list"], [self.faculty.email])
        self.assertFalse(send.call_args.kwargs["fail_silently"])

    def test_permanent_smtp_failure_preserves_created_request_and_201(self):
        with (
            patch(
                "corrections.notifications.send_mail",
                side_effect=SMTPException("secret-provider-detail"),
            ) as send,
            self.assertLogs("corrections.notifications", level="WARNING") as logs,
            self.captureOnCommitCallbacks(execute=True),
        ):
            response = self.client.post(
                self.url,
                {"record_id": self.record.pk, "reason": "I attended this class."},
                format="json",
            )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(send.call_count, 2)
        self.assertEqual(CorrectionRequest.objects.get().status, "PENDING")
        self.assertEqual(len(logs.output), 2)
        self.assertNotIn("secret-provider-detail", " ".join(logs.output))
        self.assertNotIn("I attended this class.", " ".join(logs.output))

    def test_network_failure_is_retried_once(self):
        correction = self.create_request()
        with (
            patch(
                "corrections.notifications.send_mail",
                side_effect=OSError("unreachable"),
            ) as send,
            self.assertLogs("corrections.notifications", level="WARNING"),
        ):
            self.assertFalse(notify_faculty(correction.pk))
        self.assertEqual(send.call_count, 2)
        self.assertTrue(CorrectionRequest.objects.filter(pk=correction.pk).exists())

    def test_zero_messages_sent_is_retried_and_logged(self):
        correction = self.create_request()
        with (
            patch("corrections.notifications.send_mail", return_value=0) as send,
            self.assertLogs("corrections.notifications", level="WARNING"),
        ):
            self.assertFalse(notify_faculty(correction.pk))
        self.assertEqual(send.call_count, 2)

    def test_unassigned_section_logs_failure_without_breaking_submission(self):
        Section.objects.filter(pk=self.section.pk).update(faculty=None)
        with (
            self.assertLogs("corrections.notifications", level="WARNING"),
            self.captureOnCommitCallbacks(execute=True),
        ):
            correction = self.submit()
        self.assertTrue(CorrectionRequest.objects.filter(pk=correction.pk).exists())
        self.assertEqual(len(mail.outbox), 0)

    def test_inactive_faculty_does_not_receive_email(self):
        correction = self.create_request()
        User.objects.filter(pk=self.faculty.pk).update(is_active=False)
        with self.assertLogs("corrections.notifications", level="WARNING"):
            self.assertFalse(notify_faculty(correction.pk))
        self.assertEqual(len(mail.outbox), 0)

    def test_non_faculty_assignee_does_not_receive_email(self):
        correction = self.create_request()
        Section.objects.filter(pk=self.section.pk).update(faculty=self.student)
        with self.assertLogs("corrections.notifications", level="WARNING"):
            self.assertFalse(notify_faculty(correction.pk))
        self.assertEqual(len(mail.outbox), 0)

    def test_faculty_with_no_email_does_not_receive_email(self):
        correction = self.create_request()
        User.objects.filter(pk=self.faculty.pk).update(email="")
        with self.assertLogs("corrections.notifications", level="WARNING"):
            self.assertFalse(notify_faculty(correction.pk))
        self.assertEqual(len(mail.outbox), 0)

    def test_missing_request_is_logged_without_sending(self):
        with self.assertLogs("corrections.notifications", level="WARNING"):
            self.assertFalse(notify_faculty(999999))
        self.assertEqual(len(mail.outbox), 0)

    def test_custom_backend_error_is_nonfatal_and_retried(self):
        correction = self.create_request()
        with (
            patch(
                "corrections.notifications.send_mail",
                side_effect=ValueError("configuration error"),
            ) as send,
            self.assertLogs("corrections.notifications", level="WARNING"),
        ):
            self.assertFalse(notify_faculty(correction.pk))
        self.assertEqual(send.call_count, 2)
