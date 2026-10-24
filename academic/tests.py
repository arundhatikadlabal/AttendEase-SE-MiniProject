from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from analytics.models import Course

PASSWORD = "StrongPass123!"


class AcademicTestCase(TestCase):
    def setUp(self):
        User = get_user_model()
        self.admin = User.objects.create_superuser(
            email="admin@example.com", name="Admin", password=PASSWORD
        )
        self.faculty = User.objects.create_user(
            email="faculty@example.com", name="Faculty One", role="faculty", password=PASSWORD
        )
        self.other_faculty = User.objects.create_user(
            email="faculty2@example.com", name="Faculty Two", role="faculty", password=PASSWORD
        )
        self.student = User.objects.create_user(
            email="student@example.com", name="Student One", role="student", password=PASSWORD
        )
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

    def make_course(self, code="CS101", title="Intro to Programming"):
        return Course.objects.create(code=code, title=title)


class CourseTests(AcademicTestCase):
    """FR-006: administrators create and edit courses."""

    def test_fr006_admin_creates_course(self):
        response = self.as_user(self.admin).post(
            reverse("academic-courses"), {"code": " cs101 ", "title": "Intro to Programming"}
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["code"], "CS101")
        self.assertTrue(Course.objects.filter(code="CS101").exists())

    def test_fr006_admin_edits_course(self):
        course = self.make_course()

        response = self.as_user(self.admin).patch(
            reverse("academic-course", args=[course.pk]),
            {"title": "Programming Fundamentals"},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        course.refresh_from_db()
        self.assertEqual(course.title, "Programming Fundamentals")
        self.assertEqual(course.code, "CS101")

    def test_fr006_duplicate_course_code_is_rejected(self):
        self.make_course(code="CS101")

        created = self.as_user(self.admin).post(
            reverse("academic-courses"), {"code": "cs101", "title": "Copy"}
        )
        other = self.make_course(code="CS102")
        renamed = self.client.patch(
            reverse("academic-course", args=[other.pk]), {"code": "CS101"}, format="json"
        )

        self.assertEqual(created.status_code, 409)
        self.assertEqual(renamed.status_code, 409)
        self.assertIn("code", created.json())
        self.assertEqual(Course.objects.filter(code="CS101").count(), 1)

    def test_fr006_invalid_course_payload_is_rejected(self):
        response = self.as_user(self.admin).post(
            reverse("academic-courses"), {"code": "", "title": "No Code"}
        )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(Course.objects.exists())

    def test_fr006_unknown_course_returns_404(self):
        response = self.as_user(self.admin).patch(
            reverse("academic-course", args=[9999]), {"title": "X"}, format="json"
        )

        self.assertEqual(response.status_code, 404)

    def test_fr006_any_role_lists_courses(self):
        self.make_course(code="CS102", title="Data Structures")
        self.make_course(code="CS101")

        response = self.as_user(self.student).get(reverse("academic-courses"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual([c["code"] for c in response.json()], ["CS101", "CS102"])

    def test_fr006_non_admins_cannot_create_or_edit_courses(self):
        course = self.make_course()
        for user in (self.student, self.faculty):
            with self.subTest(role=user.role), self.assertLogs(
                "users.permissions", level="WARNING"
            ):
                create = self.as_user(user).post(
                    reverse("academic-courses"), {"code": "CS999", "title": "Nope"}
                )
                edit = self.client.patch(
                    reverse("academic-course", args=[course.pk]),
                    {"title": "Nope"},
                    format="json",
                )
            self.assertEqual(create.status_code, 403)
            self.assertEqual(edit.status_code, 403)
        self.assertEqual(Course.objects.count(), 1)

    def test_course_endpoints_require_authentication(self):
        self.assertEqual(self.client.get(reverse("academic-courses")).status_code, 401)

    def test_tc09_student_calling_real_admin_endpoint_is_denied(self):
        """TC-09 / SEC-003 repeated against the real academic-setup endpoint."""
        client = self.jwt_client(self.student)

        with self.assertLogs("users.permissions", level="WARNING"):
            response = client.post(
                reverse("academic-courses"), {"code": "CS999", "title": "Nope"}
            )

        self.assertEqual(response.status_code, 403)
        self.assertFalse(Course.objects.exists())
