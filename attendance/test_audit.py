from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch

from django.apps import apps
from django.core.exceptions import ValidationError
from django.db import DatabaseError, connection, transaction
from django.db.models.deletion import ProtectedError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from analytics.models import (
    AttendanceRecord,
    AttendanceSession,
    Course,
    Enrollment,
    Section,
)
from corrections.models import CorrectionRequest
from corrections.services import approve_correction, reject_correction
from users.models import User

from .models import AttendanceAuditEntry
from .services import edit_closed_record, mark_all_present, mark_student, submit_records


class AttendanceAuditTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.faculty = User.objects.create_user(
            email="faculty@example.com", name="Faculty", role=User.Role.FACULTY
        )
        cls.other_faculty = User.objects.create_user(
            email="other@example.com", name="Other Faculty", role=User.Role.FACULTY
        )
        cls.student = User.objects.create_user(
            email="student@example.com", name="Student", role=User.Role.STUDENT
        )
        cls.other_student = User.objects.create_user(
            email="other-student@example.com",
            name="Other Student",
            role=User.Role.STUDENT,
        )
        cls.admin = User.objects.create_superuser(
            email="admin@example.com", name="Admin", password="StrongPass123!"
        )
        cls.course = Course.objects.create(code="CS101", title="Software Engineering")
        cls.section = Section.objects.create(
            course=cls.course, code="A", faculty=cls.faculty
        )
        Enrollment.objects.create(section=cls.section, student=cls.student)
        Enrollment.objects.create(section=cls.section, student=cls.other_student)
        cls.session = AttendanceSession.objects.create(
            section=cls.section, date=timezone.localdate()
        )

    def mark(self, status="absent"):
        return mark_student(
            faculty=self.faculty,
            session_id=self.session.pk,
            student_id=self.student.pk,
            status=status,
        )

    def request(self):
        return CorrectionRequest.objects.create(
            record=self.mark(), student=self.student, reason="I attended."
        )

    def test_initial_mark_and_changes_form_ordered_history(self):
        record = self.mark()
        self.mark("present")
        self.mark("absent")
        entries = list(record.audit_entries.all())
        self.assertEqual(
            [(e.action, e.old_status, e.new_status) for e in entries],
            [
                ("CREATED", "", "ABSENT"),
                ("MARKED", "ABSENT", "PRESENT"),
                ("MARKED", "PRESENT", "ABSENT"),
            ],
        )
        self.assertTrue(all(e.actor_id == self.faculty.pk for e in entries))
        self.assertTrue(all(e.timestamp for e in entries))
        self.assertEqual(AttendanceRecord.objects.count(), 1)

    def test_batch_submission_records_each_initial_mark(self):
        records = submit_records(
            faculty=self.faculty,
            session_id=self.session.pk,
            records=[
                {"student_id": self.student.pk, "status": "present"},
                {"student_id": self.other_student.pk, "status": "absent"},
            ],
        )
        self.assertEqual(AttendanceAuditEntry.objects.count(), 2)
        self.assertEqual(
            set(AttendanceAuditEntry.objects.values_list("record_id", flat=True)),
            {r.pk for r in records},
        )
        self.assertEqual(
            set(AttendanceAuditEntry.objects.values_list("action", flat=True)),
            {"CREATED"},
        )

    def test_bulk_mark_records_created_and_changed_values(self):
        record = self.mark()
        mark_all_present(faculty=self.faculty, session_id=self.session.pk)
        entry = record.audit_entries.last()
        self.assertEqual(
            (entry.action, entry.old_status, entry.new_status),
            ("MARKED", "ABSENT", "PRESENT"),
        )
        other = AttendanceRecord.objects.get(student=self.other_student)
        self.assertEqual(other.audit_entries.get().action, "CREATED")
        self.assertEqual(other.audit_entries.get().actor_id, self.faculty.pk)

    def test_no_op_marking_and_bulk_mark_do_not_invent_changes(self):
        self.mark("present")
        self.mark("present")
        mark_all_present(faculty=self.faculty, session_id=self.session.pk)
        before = AttendanceAuditEntry.objects.count()
        mark_all_present(faculty=self.faculty, session_id=self.session.pk)
        self.assertEqual(AttendanceAuditEntry.objects.count(), before)

    def test_timed_edit_preserves_original_value_and_actor(self):
        record = self.mark()
        AttendanceSession.objects.filter(pk=self.session.pk).update(
            closed=True, closed_at=timezone.now() - timedelta(minutes=1)
        )
        edit_closed_record(
            faculty=self.faculty,
            session_id=self.session.pk,
            student_id=self.student.pk,
            status="present",
        )
        entry = record.audit_entries.last()
        self.assertEqual(
            (entry.action, entry.old_status, entry.new_status),
            ("EDITED", "ABSENT", "PRESENT"),
        )
        self.assertEqual(entry.actor_id, self.faculty.pk)

    def test_approval_preserves_old_value_and_links_decision(self):
        correction = self.request()
        approve_correction(faculty=self.faculty, correction_id=correction.pk)
        entry = AttendanceAuditEntry.objects.get(action="APPROVED")
        self.assertEqual((entry.old_status, entry.new_status), ("ABSENT", "PRESENT"))
        self.assertEqual(entry.correction_id, correction.pk)
        self.assertEqual(entry.reason, "I attended.")
        self.assertEqual(entry.actor_id, self.faculty.pk)
        self.assertEqual(entry.record_id, correction.record_id)

    def test_rejection_logs_decision_even_without_mark_change(self):
        correction = self.request()
        reject_correction(
            faculty=self.faculty,
            correction_id=correction.pk,
            reason="Register confirms absence.",
        )
        entry = AttendanceAuditEntry.objects.get(action="REJECTED")
        self.assertEqual((entry.old_status, entry.new_status), ("ABSENT", "ABSENT"))
        self.assertEqual(entry.reason, "Register confirms absence.")
        self.assertEqual(entry.correction_id, correction.pk)
        self.assertEqual(entry.actor_id, self.faculty.pk)
        correction.record.refresh_from_db()
        self.assertEqual(correction.record.status, "ABSENT")

    def test_failed_audit_insert_rolls_back_mark_creation(self):
        with (
            patch(
                "attendance.services.append_change",
                side_effect=DatabaseError("Audit unavailable"),
            ),
            self.assertRaises(DatabaseError),
        ):
            self.mark()
        self.assertEqual(AttendanceRecord.objects.count(), 0)
        self.assertEqual(AttendanceAuditEntry.objects.count(), 0)

    def test_failed_audit_insert_rolls_back_approval_and_attendance(self):
        correction = self.request()
        with (
            patch(
                "corrections.services.append_change",
                side_effect=DatabaseError("Audit unavailable"),
            ),
            self.assertRaises(DatabaseError),
        ):
            approve_correction(faculty=self.faculty, correction_id=correction.pk)
        correction.refresh_from_db()
        correction.record.refresh_from_db()
        self.assertEqual(correction.status, "PENDING")
        self.assertIsNone(correction.acted_by_id)
        self.assertEqual(correction.record.status, "ABSENT")
        self.assertFalse(
            AttendanceAuditEntry.objects.filter(action="APPROVED").exists()
        )

    def test_failed_audit_insert_rolls_back_rejection(self):
        correction = self.request()
        with (
            patch(
                "corrections.services.append_change",
                side_effect=DatabaseError("Audit unavailable"),
            ),
            self.assertRaises(DatabaseError),
        ):
            reject_correction(
                faculty=self.faculty, correction_id=correction.pk, reason="Absent"
            )
        correction.refresh_from_db()
        self.assertEqual(correction.status, "PENDING")
        self.assertEqual(correction.rejection_reason, "")

    def test_audit_model_and_queryset_changes_are_blocked(self):
        entry = self.mark().audit_entries.get()
        entry.reason = "Tampered"
        for operation in (
            entry.save,
            entry.delete,
            lambda: AttendanceAuditEntry.objects.filter(pk=entry.pk).update(
                reason="Tampered"
            ),
            lambda: AttendanceAuditEntry.objects.filter(pk=entry.pk).delete(),
            lambda: AttendanceAuditEntry.objects.bulk_update([entry], ["reason"]),
        ):
            with self.subTest(operation=operation), self.assertRaises(ValidationError):
                operation()
        entry.refresh_from_db()
        self.assertEqual(entry.reason, "")
        replacement = AttendanceAuditEntry(
            pk=entry.pk, record=entry.record, action="CREATED", new_status="PRESENT"
        )
        with self.assertRaises(ValidationError):
            replacement.save()

    def test_record_instance_and_queryset_deletion_are_blocked(self):
        record = self.mark()
        for operation in (
            record.delete,
            lambda: AttendanceRecord.objects.filter(pk=record.pk).delete(),
        ):
            with (
                self.subTest(operation=operation),
                self.assertRaises(ProtectedError),
                transaction.atomic(),
            ):
                operation()
        self.assertTrue(AttendanceRecord.objects.filter(pk=record.pk).exists())

    def test_legacy_record_without_audit_cannot_be_deleted(self):
        record = AttendanceRecord.objects.create(
            session=self.session, student=self.student, status="ABSENT"
        )
        with self.assertRaises(ProtectedError), transaction.atomic():
            record.delete()
        self.assertTrue(AttendanceRecord.objects.filter(pk=record.pk).exists())

    def test_cascading_deletions_cannot_erase_attendance(self):
        self.mark()
        for obj in (self.session, self.student, self.section, self.course):
            with (
                self.subTest(model=type(obj).__name__),
                self.assertRaises(ProtectedError),
                transaction.atomic(),
            ):
                obj.delete()
        self.assertEqual(AttendanceRecord.objects.count(), 1)

    def test_existing_records_receive_honest_unknown_actor_baseline(self):
        from importlib import import_module

        migration = import_module(
            "attendance.migrations.0002_existing_attendance_baseline"
        )
        record = AttendanceRecord.objects.create(
            session=self.session, student=self.student, status="ABSENT"
        )
        migration.snapshot_existing_records(
            apps, SimpleNamespace(connection=connection)
        )
        entry = record.audit_entries.get()
        self.assertEqual(
            (entry.action, entry.old_status, entry.new_status),
            ("BASELINE", "", "ABSENT"),
        )
        self.assertIsNone(entry.actor_id)

    def test_history_is_scoped_to_student_assigned_faculty_and_admin(self):
        record = self.mark()
        client = APIClient()
        url = reverse("attendance-history", args=[self.session.pk, self.student.pk])
        for user, expected in (
            (self.student, 200),
            (self.faculty, 200),
            (self.admin, 200),
            (self.other_student, 404),
            (self.other_faculty, 404),
            (None, 401),
        ):
            with self.subTest(user=user):
                client.force_authenticate(user)
                response = client.get(url)
                self.assertEqual(response.status_code, expected)
                if expected == 200:
                    self.assertEqual(
                        response.data["results"][0]["record_id"], record.pk
                    )
                    self.assertEqual(
                        response.data["results"][0]["actor_id"], self.faculty.pk
                    )

    def test_history_is_paginated_and_read_only(self):
        self.mark()
        for i in range(30):
            self.mark("present" if i % 2 == 0 else "absent")
        client = APIClient()
        client.force_authenticate(self.faculty)
        url = reverse("attendance-history", args=[self.session.pk, self.student.pk])
        first = client.get(url)
        second = client.get(url, {"page": 2})
        self.assertEqual(first.data["count"], 31)
        self.assertEqual(len(first.data["results"]), 25)
        self.assertEqual(len(second.data["results"]), 6)
        self.assertEqual(client.patch(url, {}, format="json").status_code, 405)
        self.assertEqual(client.delete(url).status_code, 405)
        self.assertEqual(AttendanceAuditEntry.objects.count(), 31)

    def test_upsert_cannot_replace_audit_history(self):
        entry = self.mark().audit_entries.get()
        replacement = AttendanceAuditEntry(
            pk=entry.pk, record=entry.record, action="CREATED", new_status="PRESENT"
        )
        with self.assertRaises(ValidationError):
            AttendanceAuditEntry.objects.bulk_create(
                [replacement],
                update_conflicts=True,
                update_fields=["new_status"],
                unique_fields=["id"],
            )
        entry.refresh_from_db()
        self.assertEqual(entry.new_status, "ABSENT")

    def test_failed_bulk_audit_write_rolls_back_bulk_attendance(self):
        with (
            patch(
                "attendance.models.AuditQuerySet.bulk_create",
                side_effect=DatabaseError("Audit unavailable"),
            ),
            self.assertRaises(DatabaseError),
        ):
            mark_all_present(faculty=self.faculty, session_id=self.session.pk)
        self.assertEqual(AttendanceRecord.objects.count(), 0)
        self.assertEqual(AttendanceAuditEntry.objects.count(), 0)

    def test_failed_edit_audit_write_preserves_original_mark(self):
        record = self.mark()
        AttendanceSession.objects.filter(pk=self.session.pk).update(
            closed=True, closed_at=timezone.now() - timedelta(minutes=1)
        )
        with (
            patch(
                "attendance.services.append_change",
                side_effect=DatabaseError("Audit unavailable"),
            ),
            self.assertRaises(DatabaseError),
        ):
            edit_closed_record(
                faculty=self.faculty,
                session_id=self.session.pk,
                student_id=self.student.pk,
                status="present",
            )
        record.refresh_from_db()
        self.assertEqual(record.status, "ABSENT")
        self.assertEqual(record.audit_entries.count(), 1)
