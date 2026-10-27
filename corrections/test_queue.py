from datetime import date, timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied
from rest_framework.test import APIClient

from analytics.models import AttendanceRecord, AttendanceSession, Course, Section
from users.models import User

from .models import CorrectionRequest
from .services import pending_corrections_for_faculty


class PendingCorrectionQueueTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.faculty = User.objects.create_user(
            email="faculty@example.com",
            name="Faculty",
            role=User.Role.FACULTY,
            password="StrongPass123!",
        )
        cls.other_faculty = User.objects.create_user(
            email="other-faculty@example.com",
            name="Other Faculty",
            role=User.Role.FACULTY,
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
        cls.other_section = Section.objects.create(
            course=cls.course, code="B", faculty=cls.other_faculty
        )
        cls.pending = cls.add_request(cls.section, cls.student)
        cls.other_pending = cls.add_request(cls.other_section, cls.student)
        cls.approved = cls.add_request(cls.section, cls.student, status="APPROVED")
        cls.rejected = cls.add_request(cls.section, cls.student, status="REJECTED")

    @staticmethod
    def add_request(section, student, status="PENDING"):
        session = AttendanceSession.objects.create(
            section=section, date=date(2026, 10, 19), closed=True
        )
        record = AttendanceRecord.objects.create(
            session=session, student=student, status="ABSENT"
        )
        return CorrectionRequest.objects.create(
            record=record,
            student=student,
            reason="I attended the class.",
            status=status,
        )

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(self.faculty)
        self.url = reverse("correction-submit")

    def test_only_own_pending_requests_are_returned_with_review_context(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 1)
        self.assertIsNone(response.data["next"])
        self.assertIsNone(response.data["previous"])
        item = response.data["results"][0]
        self.assertEqual(item["id"], self.pending.pk)
        self.assertEqual(item["status"], "PENDING")
        self.assertEqual(item["reason"], self.pending.reason)
        self.assertEqual(item["record_id"], self.pending.record_id)
        self.assertEqual(item["student"], {"id": self.student.pk, "name": "Student"})
        self.assertEqual(item["session"]["date"], "2026-10-19")
        self.assertEqual(item["section"], {"id": self.section.pk, "code": "A"})
        self.assertEqual(
            item["course"],
            {"id": self.course.pk, "code": "CS101", "title": "Software Engineering"},
        )
        self.assertEqual(item["attendance_status"], "ABSENT")
        self.assertIsNotNone(item["created_at"])

    def test_other_faculty_gets_only_their_own_queue(self):
        self.client.force_authenticate(self.other_faculty)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [item["id"] for item in response.data["results"]], [self.other_pending.pk]
        )

    def test_approved_and_rejected_requests_are_excluded(self):
        ids = [item["id"] for item in self.client.get(self.url).data["results"]]
        self.assertNotIn(self.approved.pk, ids)
        self.assertNotIn(self.rejected.pk, ids)

    def test_no_assigned_sections_returns_empty_queue(self):
        Section.objects.filter(faculty=self.faculty).update(faculty=None)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 0)
        self.assertEqual(response.data["results"], [])

    def test_assigned_section_with_no_pending_requests_returns_empty_queue(self):
        CorrectionRequest.objects.filter(pk=self.pending.pk).update(status="APPROVED")
        response = self.client.get(self.url)
        self.assertEqual(response.data["count"], 0)
        self.assertEqual(response.data["results"], [])

    def test_multiple_assigned_sections_are_included(self):
        Section.objects.filter(pk=self.other_section.pk).update(faculty=self.faculty)
        response = self.client.get(self.url)
        self.assertEqual(response.data["count"], 2)
        self.assertEqual(
            {item["id"] for item in response.data["results"]},
            {self.pending.pk, self.other_pending.pk},
        )

    def test_reassignment_removes_old_faculty_access_immediately(self):
        Section.objects.filter(pk=self.section.pk).update(faculty=self.other_faculty)
        self.assertEqual(self.client.get(self.url).data["count"], 0)
        self.client.force_authenticate(self.other_faculty)
        response = self.client.get(self.url)
        self.assertEqual(response.data["count"], 2)

    def test_query_parameters_cannot_expand_access_or_include_resolved_requests(self):
        response = self.client.get(
            self.url,
            {
                "faculty_id": self.other_faculty.pk,
                "section_id": self.other_section.pk,
                "status": "APPROVED",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [item["id"] for item in response.data["results"]], [self.pending.pk]
        )

    def test_students_and_admins_cannot_read_the_faculty_queue(self):
        for user in (self.student, self.admin):
            with self.subTest(role=user.role):
                self.client.force_authenticate(user)
                self.assertEqual(self.client.get(self.url).status_code, 403)

    def test_anonymous_request_requires_authentication(self):
        self.client.force_authenticate(None)
        self.assertEqual(self.client.get(self.url).status_code, 401)

    def test_inactive_faculty_is_rejected(self):
        self.faculty.is_active = False
        self.faculty.save(update_fields=["is_active"])
        self.assertEqual(self.client.get(self.url).status_code, 403)

    def test_requests_are_ordered_oldest_first_with_stable_ties(self):
        second = self.add_request(self.section, self.student)
        third = self.add_request(self.section, self.student)
        fixed = timezone.now()
        CorrectionRequest.objects.filter(pk=self.pending.pk).update(created_at=fixed)
        CorrectionRequest.objects.filter(pk=second.pk).update(
            created_at=fixed - timedelta(days=1)
        )
        CorrectionRequest.objects.filter(pk=third.pk).update(created_at=fixed)
        response = self.client.get(self.url)
        self.assertEqual(
            [item["id"] for item in response.data["results"]],
            [second.pk, self.pending.pk, third.pk],
        )

    def test_default_pagination_is_25_and_second_page_has_remaining_request(self):
        for _ in range(25):
            self.add_request(self.section, self.student)
        first = self.client.get(self.url)
        second = self.client.get(self.url, {"page": 2})
        self.assertEqual(first.data["count"], 26)
        self.assertEqual(len(first.data["results"]), 25)
        self.assertIsNotNone(first.data["next"])
        self.assertIsNone(first.data["previous"])
        self.assertEqual(len(second.data["results"]), 1)
        self.assertIsNone(second.data["next"])
        self.assertIsNotNone(second.data["previous"])
        first_ids = {item["id"] for item in first.data["results"]}
        self.assertNotIn(second.data["results"][0]["id"], first_ids)

    def test_page_size_is_capped_at_100(self):
        for _ in range(100):
            self.add_request(self.section, self.student)
        response = self.client.get(self.url, {"page_size": 1000})
        self.assertEqual(response.data["count"], 101)
        self.assertEqual(len(response.data["results"]), 100)
        self.assertIsNotNone(response.data["next"])

    def test_invalid_page_returns_404(self):
        self.assertEqual(self.client.get(self.url, {"page": 999}).status_code, 404)

    def test_rendering_queue_avoids_per_item_database_queries(self):
        for _ in range(5):
            self.add_request(self.section, self.student)
        # One count query and one joined page query, regardless of queue size.
        with self.assertNumQueries(2):
            response = self.client.get(self.url)
        self.assertEqual(response.data["count"], 6)

    def test_viewing_queue_does_not_change_requests_or_attendance(self):
        before = list(
            CorrectionRequest.objects.values_list(
                "pk", "status", "acted_by_id", "acted_at"
            )
        )
        self.assertEqual(self.client.get(self.url).status_code, 200)
        self.assertEqual(
            list(
                CorrectionRequest.objects.values_list(
                    "pk", "status", "acted_by_id", "acted_at"
                )
            ),
            before,
        )
        self.assertFalse(AttendanceRecord.objects.exclude(status="ABSENT").exists())

    def test_service_rejects_non_faculty_independently_of_api(self):
        with self.assertRaises(PermissionDenied):
            pending_corrections_for_faculty(self.student)

    def test_real_faculty_jwt_can_read_queue(self):
        self.client.force_authenticate(None)
        login = self.client.post(
            reverse("login"),
            {"email": self.faculty.email, "password": "StrongPass123!"},
            format="json",
        )
        self.assertEqual(login.status_code, 200)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {login.data['access']}")
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 1)
