from datetime import date, time, timedelta
from unittest import mock

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from academic.models import Timetable
from analytics.models import (
    AttendanceRecord,
    AttendanceSession,
    Course,
    Enrollment,
    Section,
)
from analytics.services import calculate_attendance_percentage
from users.models import User

from . import services

PASSWORD = "StrongPass123!"
MONDAY = date(2026, 10, 26)


class SessionTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_superuser(
            email="admin@example.com", name="Admin", password=PASSWORD
        )
        cls.faculty = User.objects.create_user(
            email="faculty@example.com", name="Faculty", role="faculty", password=PASSWORD
        )
        cls.other_faculty = User.objects.create_user(
            email="other@example.com", name="Other", role="faculty", password=PASSWORD
        )
        cls.students = [
            User.objects.create_user(
                email=f"student{i}@example.com",
                name=f"Student {i}",
                role="student",
                password=PASSWORD,
            )
            for i in range(3)
        ]
        cls.course = Course.objects.create(code="CS101", title="Software Engineering")
        cls.section = Section.objects.create(
            course=cls.course, code="A", faculty=cls.faculty
        )
        Enrollment.objects.bulk_create(
            [Enrollment(section=cls.section, student=s) for s in cls.students[:2]]
        )
        cls.monday_slot = Timetable.objects.create(
            section=cls.section, day_of_week=1, start_time=time(9), end_time=time(10)
        )

    def setUp(self):
        self.client = APIClient()

    def as_user(self, user):
        self.client.force_authenticate(user=user)
        return self.client

    def jwt_client(self, user):
        login = APIClient().post(
            reverse("login"), {"email": user.email, "password": PASSWORD}
        )
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {login.json()['access']}")
        return client

    def start(self, user=None, slot=None, on=MONDAY):
        payload = {"timetable_slot_id": (slot or self.monday_slot).pk}
        if on is not None:
            payload["date"] = on.isoformat()
        return self.as_user(user or self.faculty).post(
            reverse("attendance-session-start"), payload
        )

    def open_session(self, on=MONDAY):
        return AttendanceSession.objects.create(
            section=self.section, timetable_slot=self.monday_slot, date=on
        )


class StartSessionTests(SessionTestCase):
    """FR-014: faculty start a session for a scheduled section period."""

    def test_fr014_faculty_starts_session_for_scheduled_period(self):
        response = self.start()

        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertEqual(body["date"], "2026-10-26")
        self.assertFalse(body["closed"])
        self.assertEqual(body["section"]["course_code"], "CS101")
        self.assertEqual(body["timetable_slot"]["day_name"], "Monday")
        session = AttendanceSession.objects.get()
        self.assertEqual(session.section, self.section)
        self.assertEqual(session.timetable_slot, self.monday_slot)

    def test_fr014_date_must_match_period_weekday(self):
        response = self.start(on=date(2026, 10, 27))

        self.assertEqual(response.status_code, 400)
        self.assertIn("date", response.json())
        self.assertFalse(AttendanceSession.objects.exists())

    def test_fr014_second_session_for_same_period_and_date_returns_409(self):
        self.assertEqual(self.start().status_code, 201)

        response = self.start()

        self.assertEqual(response.status_code, 409)
        self.assertEqual(AttendanceSession.objects.count(), 1)

    def test_fr014_same_period_on_another_week_is_allowed(self):
        self.assertEqual(self.start().status_code, 201)
        self.assertEqual(self.start(on=date(2026, 10, 19)).status_code, 201)

    def test_fr014_only_the_assigned_faculty_can_start(self):
        response = self.start(user=self.other_faculty)

        self.assertEqual(response.status_code, 403)
        self.assertFalse(AttendanceSession.objects.exists())

    def test_fr014_students_and_admins_cannot_start(self):
        for user in (self.students[0], self.admin):
            with self.subTest(role=user.role), self.assertLogs(
                "users.permissions", level="WARNING"
            ):
                self.assertEqual(self.start(user=user).status_code, 403)

    def test_fr014_unknown_period_is_rejected(self):
        response = self.as_user(self.faculty).post(
            reverse("attendance-session-start"), {"timetable_slot_id": 9999}
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("timetable_slot_id", response.json())

    def test_fr014_works_with_real_jwt_login(self):
        response = self.jwt_client(self.faculty).post(
            reverse("attendance-session-start"),
            {"timetable_slot_id": self.monday_slot.pk, "date": MONDAY.isoformat()},
        )

        self.assertEqual(response.status_code, 201)

    def test_fr014_session_list_and_detail_are_scoped(self):
        session = self.open_session()

        own = self.as_user(self.faculty).get(reverse("attendance-sessions"))
        everything = self.as_user(self.admin).get(reverse("attendance-sessions"))
        other = self.as_user(self.other_faculty).get(reverse("attendance-sessions"))
        hidden = self.client.get(reverse("attendance-session", args=[session.pk]))
        missing = self.as_user(self.faculty).get(
            reverse("attendance-session", args=[9999])
        )

        self.assertEqual([s["id"] for s in own.json()], [session.pk])
        self.assertEqual([s["id"] for s in everything.json()], [session.pk])
        self.assertEqual(other.json(), [])
        self.assertEqual(hidden.status_code, 403)
        self.assertEqual(missing.status_code, 404)


class FutureDateTests(SessionTestCase):
    """NFR-004: attendance cannot be recorded for future dates."""

    def test_nfr004_future_session_date_is_rejected(self):
        next_monday = MONDAY + timedelta(days=7)
        with mock.patch.object(timezone, "localdate", return_value=MONDAY):
            response = self.start(on=next_monday)

        self.assertEqual(response.status_code, 400)
        self.assertIn("future", str(response.json()["date"]))
        self.assertFalse(AttendanceSession.objects.exists())

    def test_nfr004_today_and_past_dates_are_allowed(self):
        with mock.patch.object(timezone, "localdate", return_value=MONDAY):
            today = self.start(on=MONDAY)
            past = self.start(on=MONDAY - timedelta(days=7))

        self.assertEqual(today.status_code, 201)
        self.assertEqual(past.status_code, 201)

    def test_nfr004_missing_date_defaults_to_today(self):
        with mock.patch.object(timezone, "localdate", return_value=MONDAY):
            response = self.start(on=None)

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["date"], MONDAY.isoformat())

    def test_nfr004_records_cannot_be_submitted_for_a_future_session(self):
        session = self.open_session(on=MONDAY + timedelta(days=7))

        with mock.patch.object(timezone, "localdate", return_value=MONDAY):
            response = self.as_user(self.faculty).post(
                reverse("attendance-records", args=[session.pk]),
                {"records": [{"student_id": self.students[0].pk, "status": "present"}]},
                format="json",
            )

        self.assertEqual(response.status_code, 400)
        self.assertIn("session", response.json())
        self.assertFalse(session.records.exists())

    def test_nfr004_service_rejects_future_date(self):
        with mock.patch.object(timezone, "localdate", return_value=MONDAY), self.assertRaises(
            services.ValidationError
        ):
            services.start_session(
                faculty=self.faculty,
                timetable_slot=self.monday_slot,
                date=MONDAY + timedelta(days=7),
            )


class RosterTests(SessionTestCase):
    """FR-015: the enrolled-student roster for the active session."""

    def roster(self, session, user=None):
        return self.as_user(user or self.faculty).get(
            reverse("attendance-session-roster", args=[session.pk])
        )

    def test_fr015_roster_lists_enrolled_students_with_status(self):
        session = self.open_session()
        AttendanceRecord.objects.create(
            session=session, student=self.students[1], status="ABSENT"
        )

        response = self.roster(session)

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["session"]["id"], session.pk)
        self.assertEqual(
            [(s["student_id"], s["status"]) for s in body["students"]],
            [(self.students[0].pk, None), (self.students[1].pk, "absent")],
        )
        self.assertEqual((body["marked"], body["total"]), (1, 2))

    def test_fr015_unenrolled_and_inactive_students_are_excluded(self):
        session = self.open_session()
        self.students[1].is_active = False
        self.students[1].save()

        body = self.roster(session).json()

        self.assertEqual([s["student_id"] for s in body["students"]], [self.students[0].pk])

    def test_fr015_status_is_per_session(self):
        session = self.open_session()
        other = self.open_session(on=date(2026, 10, 19))
        AttendanceRecord.objects.create(
            session=other, student=self.students[0], status="PRESENT"
        )

        body = self.roster(session).json()

        self.assertEqual({s["status"] for s in body["students"]}, {None})

    def test_fr015_roster_visible_to_assigned_faculty_and_admin_only(self):
        session = self.open_session()

        self.assertEqual(self.roster(session).status_code, 200)
        self.assertEqual(self.roster(session, self.admin).status_code, 200)
        self.assertEqual(self.roster(session, self.other_faculty).status_code, 403)
        with self.assertLogs("users.permissions", level="WARNING"):
            self.assertEqual(self.roster(session, self.students[0]).status_code, 403)

    def test_fr015_roster_uses_constant_number_of_queries(self):
        session = self.open_session()
        extra = [
            User.objects.create_user(
                email=f"extra{i}@example.com", name=f"Extra {i}", role="student"
            )
            for i in range(20)
        ]
        Enrollment.objects.bulk_create(
            [Enrollment(section=self.section, student=s) for s in extra]
        )
        self.as_user(self.faculty)

        with self.assertNumQueries(2):
            response = self.client.get(
                reverse("attendance-session-roster", args=[session.pk])
            )

        self.assertEqual(response.json()["total"], 22)


class MarkStudentTests(SessionTestCase):
    """FR-016: faculty mark each student present or absent."""

    def mark(self, session, student, status, user=None):
        return self.as_user(user or self.faculty).put(
            reverse("attendance-student-mark", args=[session.pk, student.pk]),
            {"status": status},
            format="json",
        )

    def test_fr016_faculty_marks_each_student_present_or_absent(self):
        session = self.open_session()

        present = self.mark(session, self.students[0], "present")
        absent = self.mark(session, self.students[1], "absent")

        self.assertEqual(present.status_code, 200)
        self.assertEqual(present.json()["status"], "present")
        self.assertEqual(absent.json()["status"], "absent")
        self.assertEqual(
            dict(session.records.values_list("student_id", "status")),
            {self.students[0].pk: "PRESENT", self.students[1].pk: "ABSENT"},
        )

    def test_fr016_toggling_updates_the_same_record(self):
        session = self.open_session()
        self.mark(session, self.students[0], "present")

        response = self.mark(session, self.students[0], "absent")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(session.records.count(), 1)
        self.assertEqual(session.records.get().status, "ABSENT")

    def test_fr016_roster_reflects_marks(self):
        session = self.open_session()
        self.mark(session, self.students[1], "present")

        roster = self.client.get(reverse("attendance-session-roster", args=[session.pk]))

        statuses = {s["student_id"]: s["status"] for s in roster.json()["students"]}
        self.assertEqual(statuses[self.students[1].pk], "present")
        self.assertIsNone(statuses[self.students[0].pk])

    def test_fr016_invalid_status_is_rejected(self):
        session = self.open_session()

        self.assertEqual(self.mark(session, self.students[0], "late").status_code, 400)
        self.assertFalse(session.records.exists())

    def test_fr016_unenrolled_student_returns_404(self):
        session = self.open_session()

        response = self.mark(session, self.students[2], "present")

        self.assertEqual(response.status_code, 404)
        self.assertFalse(session.records.exists())

    def test_fr016_closed_session_cannot_be_marked(self):
        session = self.open_session()
        session.closed = True
        session.save()

        response = self.mark(session, self.students[0], "present")

        self.assertEqual(response.status_code, 400)
        self.assertIn("session", response.json())

    def test_fr016_only_assigned_faculty_can_mark(self):
        session = self.open_session()

        other = self.mark(session, self.students[0], "present", self.other_faculty)
        with self.assertLogs("users.permissions", level="WARNING"):
            admin = self.mark(session, self.students[0], "present", self.admin)

        self.assertEqual(other.status_code, 403)
        self.assertEqual(admin.status_code, 403)
        self.assertFalse(session.records.exists())


class MarkAllPresentTests(SessionTestCase):
    """FR-017: faculty bulk-mark all students present with a single action."""

    def mark_all(self, session, user=None):
        return self.as_user(user or self.faculty).post(
            reverse("attendance-mark-all-present", args=[session.pk])
        )

    def test_tc04_start_session_then_bulk_mark_all_present(self):
        """TC-04 (FR-014, FR-016, FR-017): roster shows every student present."""
        faculty = self.jwt_client(self.faculty)
        started = faculty.post(
            reverse("attendance-session-start"),
            {"timetable_slot_id": self.monday_slot.pk, "date": MONDAY.isoformat()},
        )
        self.assertEqual(started.status_code, 201)
        session_id = started.json()["id"]

        bulk = faculty.post(reverse("attendance-mark-all-present", args=[session_id]))

        self.assertEqual(bulk.status_code, 200)
        roster = faculty.get(reverse("attendance-session-roster", args=[session_id]))
        body = roster.json()
        self.assertEqual(body["total"], 2)
        self.assertEqual(body["marked"], 2)
        self.assertEqual({s["status"] for s in body["students"]}, {"present"})
        self.assertEqual(
            AttendanceRecord.objects.filter(session_id=session_id).count(), 2
        )

    def test_fr017_overrides_earlier_absent_marks_without_duplicates(self):
        session = self.open_session()
        AttendanceRecord.objects.create(
            session=session, student=self.students[0], status="ABSENT"
        )

        response = self.mark_all(session)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(session.records.count(), 2)
        self.assertEqual(set(session.records.values_list("status", flat=True)), {"PRESENT"})

    def test_fr017_is_safe_to_repeat(self):
        session = self.open_session()
        self.mark_all(session)

        response = self.mark_all(session)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(session.records.count(), 2)

    def test_fr017_individual_student_can_then_be_marked_absent(self):
        session = self.open_session()
        self.mark_all(session)

        self.client.put(
            reverse("attendance-student-mark", args=[session.pk, self.students[1].pk]),
            {"status": "absent"},
            format="json",
        )

        self.assertEqual(
            session.records.get(student=self.students[1]).status, "ABSENT"
        )

    def test_fr017_closed_session_and_other_faculty_are_rejected(self):
        session = self.open_session()

        self.assertEqual(self.mark_all(session, self.other_faculty).status_code, 403)
        session.closed = True
        session.save()
        self.assertEqual(self.mark_all(session).status_code, 400)
        self.assertFalse(session.records.exists())


class CloseSessionTests(SessionTestCase):
    """FR-018: faculty close/finalize a session after marking."""

    def close(self, session, user=None):
        return self.as_user(user or self.faculty).post(
            reverse("attendance-session-close", args=[session.pk])
        )

    def test_fr018_faculty_closes_session(self):
        session = self.open_session()
        self.as_user(self.faculty).post(
            reverse("attendance-mark-all-present", args=[session.pk])
        )

        response = self.close(session)

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["session"]["closed"])
        session.refresh_from_db()
        self.assertTrue(session.closed)

    def test_fr018_closed_session_rejects_further_marking(self):
        session = self.open_session()
        self.close(session)

        toggle = self.client.put(
            reverse("attendance-student-mark", args=[session.pk, self.students[0].pk]),
            {"status": "present"},
            format="json",
        )
        bulk = self.client.post(reverse("attendance-mark-all-present", args=[session.pk]))
        batch = self.client.post(
            reverse("attendance-records", args=[session.pk]),
            {"records": [{"student_id": self.students[0].pk, "status": "present"}]},
            format="json",
        )

        self.assertEqual((toggle.status_code, bulk.status_code, batch.status_code), (400, 400, 400))
        self.assertFalse(session.records.exists())

    def test_fr018_closing_twice_returns_409(self):
        session = self.open_session()
        self.close(session)

        self.assertEqual(self.close(session).status_code, 409)

    def test_fr018_only_assigned_faculty_can_close(self):
        session = self.open_session()

        self.assertEqual(self.close(session, self.other_faculty).status_code, 403)
        with self.assertLogs("users.permissions", level="WARNING"):
            self.assertEqual(self.close(session, self.admin).status_code, 403)
        session.refresh_from_db()
        self.assertFalse(session.closed)

    def test_fr018_closed_session_counts_towards_attendance_percentage(self):
        session = self.open_session()
        self.client.force_authenticate(self.faculty)
        self.client.put(
            reverse("attendance-student-mark", args=[session.pk, self.students[0].pk]),
            {"status": "present"},
            format="json",
        )
        before = calculate_attendance_percentage(self.students[0], self.course)

        self.close(session)

        self.assertEqual(before, 0)
        self.assertEqual(calculate_attendance_percentage(self.students[0], self.course), 100)
        self.assertEqual(calculate_attendance_percentage(self.students[1], self.course), 0)


class SessionTimestampTests(SessionTestCase):
    """FR-019: sessions are timestamped on creation and closure."""

    def test_fr019_creation_is_timestamped(self):
        before = timezone.now()
        response = self.start()
        after = timezone.now()

        session = AttendanceSession.objects.get()
        self.assertTrue(before <= session.created_at <= after)
        self.assertIsNone(session.closed_at)
        self.assertEqual(response.json()["created_at"], session.created_at.isoformat())
        self.assertIsNone(response.json()["closed_at"])

    def test_fr019_closure_is_timestamped(self):
        session = self.open_session()
        before = timezone.now()

        response = self.as_user(self.faculty).post(
            reverse("attendance-session-close", args=[session.pk])
        )

        session.refresh_from_db()
        self.assertTrue(before <= session.closed_at <= timezone.now())
        self.assertGreaterEqual(session.closed_at, session.created_at)
        self.assertEqual(
            response.json()["session"]["closed_at"], session.closed_at.isoformat()
        )

    def test_fr019_failed_second_close_keeps_original_timestamp(self):
        session = self.open_session()
        self.as_user(self.faculty).post(
            reverse("attendance-session-close", args=[session.pk])
        )
        session.refresh_from_db()
        first = session.closed_at

        self.client.post(reverse("attendance-session-close", args=[session.pk]))

        session.refresh_from_db()
        self.assertEqual(session.closed_at, first)

    def test_fr019_timestamps_cannot_be_set_by_the_client(self):
        response = self.as_user(self.faculty).post(
            reverse("attendance-session-start"),
            {
                "timetable_slot_id": self.monday_slot.pk,
                "date": MONDAY.isoformat(),
                "created_at": "2020-01-01T00:00:00Z",
                "closed_at": "2020-01-01T00:00:00Z",
            },
        )

        session = AttendanceSession.objects.get(pk=response.json()["id"])
        self.assertGreater(session.created_at.year, 2020)
        self.assertIsNone(session.closed_at)
