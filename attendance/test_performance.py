"""Performance tests for the attendance roster (NFR-001, NFR-002 / TC-11)."""

import statistics
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from datetime import time as clock

from django.db import connections
from django.test import TestCase, TransactionTestCase
from django.urls import reverse
from rest_framework.test import APIClient

from academic.models import Timetable
from analytics.models import AttendanceSession, Course, Enrollment, Section
from users.models import User

PASSWORD = "StrongPass123!"
CLASS_SIZE = 80
ROSTER_LIMIT_SECONDS = 3.0
CONCURRENT_USERS = 50
REQUEST_LIMIT_SECONDS = 2.0


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


def percentile(values, fraction):
    ordered = sorted(values)
    index = max(0, round(fraction * len(ordered)) - 1)
    return ordered[index]


class ConcurrentLoadTests(TransactionTestCase):
    """NFR-001 / TC-11: 95% of requests finish within 2 s with 50 concurrent users.

    TransactionTestCase commits the data, so every worker thread (each with its
    own database connection) sees the same section.
    """

    def setUp(self):
        self.faculty, self.session = build_section()
        self.client = jwt_client(self.faculty)
        self.token = self.client._credentials["HTTP_AUTHORIZATION"]

    def timed_request(self, url):
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=self.token)
        try:
            started = time.perf_counter()
            response = client.get(url)
            return response.status_code, time.perf_counter() - started
        finally:
            connections.close_all()

    def run_concurrently(self, url, users=CONCURRENT_USERS):
        with ThreadPoolExecutor(max_workers=users) as pool:
            return list(pool.map(self.timed_request, [url] * users))

    def test_tc11_50_concurrent_roster_requests_within_2_seconds(self):
        url = reverse("attendance-session-roster", args=[self.session.pk])

        results = self.run_concurrently(url)

        statuses = [code for code, _ in results]
        timings = [seconds for _, seconds in results]
        self.assertEqual(statuses, [200] * CONCURRENT_USERS)
        p95 = percentile(timings, 0.95)
        print(
            f"\nTC-11 roster x{CONCURRENT_USERS}: "
            f"median {statistics.median(timings):.3f}s, "
            f"p95 {p95:.3f}s, max {max(timings):.3f}s"
        )
        self.assertLess(p95, REQUEST_LIMIT_SECONDS)

    def test_nfr001_mixed_api_requests_under_concurrent_load(self):
        urls = [
            reverse("attendance-session-roster", args=[self.session.pk]),
            reverse("attendance-sessions"),
            reverse("attendance-session", args=[self.session.pk]),
            reverse("academic-courses"),
            reverse("academic-my-sections"),
        ] * (CONCURRENT_USERS // 5)

        with ThreadPoolExecutor(max_workers=CONCURRENT_USERS) as pool:
            results = list(pool.map(self.timed_request, urls))

        self.assertTrue(all(code == 200 for code, _ in results))
        timings = [seconds for _, seconds in results]
        self.assertLess(percentile(timings, 0.95), REQUEST_LIMIT_SECONDS)

    def test_percentile_helper(self):
        self.assertEqual(percentile(list(range(1, 101)), 0.95), 95)
        self.assertEqual(percentile([0.5], 0.95), 0.5)
