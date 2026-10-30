from datetime import date, time, timedelta
from unittest import mock

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from academic.models import Timetable
from analytics.models import AttendanceSession, Course, Enrollment, Section
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
