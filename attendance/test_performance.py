"""Performance tests for the attendance roster (NFR-001, NFR-002 / TC-11)."""

import time
from datetime import date
from datetime import time as clock

from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from academic.models import Timetable
from analytics.models import AttendanceSession, Course, Enrollment, Section
from users.models import User

PASSWORD = "StrongPass123!"
CLASS_SIZE = 80
ROSTER_LIMIT_SECONDS = 3.0


def build_section(class_size=CLASS_SIZE):
    """An 80-student section with one open session, as NFR-002 describes."""
    faculty = User.objects.create_user(
        email="perf-faculty@example.com",
        name="Perf Faculty",
        role=User.Role.FACULTY,
        password=PASSWORD,
    )
    course = Course.objects.create(code="PERF101", title="Performance")
    section = Section.objects.create(course=course, code="A", faculty=faculty)
    students = User.objects.bulk_create(
        [
            User(
                email=f"perf-student{i:03d}@example.com",
                name=f"Student {i:03d}",
                role=User.Role.STUDENT,
            )
            for i in range(class_size)
        ]
    )
    Enrollment.objects.bulk_create(
        [Enrollment(section=section, student=student) for student in students]
    )
    slot = Timetable.objects.create(
        section=section, day_of_week=1, start_time=clock(9), end_time=clock(10)
    )
    session = AttendanceSession.objects.create(
        section=section, timetable_slot=slot, date=date(2026, 10, 26)
    )
    return faculty, session


def jwt_client(user):
    login = APIClient().post(
        reverse("login"), {"email": user.email, "password": PASSWORD}
    )
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {login.json()['access']}")
    return client


class RosterPerformanceTests(TestCase):
    """NFR-002: the roster loads within 3 seconds for a section of 80 students."""

    @classmethod
    def setUpTestData(cls):
        cls.faculty, cls.session = build_section()

    def test_nfr002_roster_for_80_students_loads_within_3_seconds(self):
        client = jwt_client(self.faculty)
        url = reverse("attendance-session-roster", args=[self.session.pk])

        started = time.perf_counter()
        response = client.get(url)
        elapsed = time.perf_counter() - started

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["total"], CLASS_SIZE)
        self.assertLess(elapsed, ROSTER_LIMIT_SECONDS)

    def test_nfr002_marking_actions_for_80_students_stay_within_3_seconds(self):
        client = jwt_client(self.faculty)

        started = time.perf_counter()
        bulk = client.post(
            reverse("attendance-mark-all-present", args=[self.session.pk])
        )
        elapsed = time.perf_counter() - started

        self.assertEqual(bulk.status_code, 200)
        self.assertEqual(bulk.json()["marked"], CLASS_SIZE)
        self.assertLess(elapsed, ROSTER_LIMIT_SECONDS)

    def test_nfr002_roster_query_count_does_not_grow_with_class_size(self):
        client = jwt_client(self.faculty)
        url = reverse("attendance-session-roster", args=[self.session.pk])
        client.get(url)

        # JWT user lookup + session lookup + one roster query.
        with self.assertNumQueries(3):
            response = client.get(url)

        self.assertEqual(response.json()["total"], CLASS_SIZE)
