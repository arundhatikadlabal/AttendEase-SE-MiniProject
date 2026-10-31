from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from rest_framework.response import Response
from rest_framework.test import APIRequestFactory, force_authenticate
from rest_framework.views import APIView

from .models import LoginAttempt
from .security import login_failure_key


class RegistrationTests(TestCase):
    def test_tc01_register_student_with_hashed_password(self):
        response = self.client.post(
            reverse("register"),
            {
                "name": "A Student",
                "email": "student@example.com",
                "password": "StrongPass123!",
                "role": "student",
            },
        )

        self.assertEqual(response.status_code, 201)
        user = get_user_model().objects.get(email="student@example.com")
        self.assertEqual(user.name, "A Student")
        self.assertEqual(user.role, "student")
        self.assertIsNone(user.usn)
        self.assertTrue(user.check_password("StrongPass123!"))
        self.assertNotEqual(user.password, "StrongPass123!")
        self.assertNotIn("password", response.json())

    def test_registration_stores_optional_usn(self):
        response = self.client.post(
            reverse("register"),
            {
                "name": "A Student",
                "email": "usn-student@example.com",
                "password": "StrongPass123!",
                "role": "student",
                "usn": "PES1UG24CS083",
            },
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["usn"], "PES1UG24CS083")
        self.assertEqual(
            get_user_model().objects.get(email="usn-student@example.com").usn,
            "PES1UG24CS083",
        )

    def test_public_registration_cannot_create_admin(self):
        response = self.client.post(
            reverse("register"),
            {
                "name": "Unauthorized Admin",
                "email": "admin@example.com",
                "password": "StrongPass123!",
                "role": "admin",
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(get_user_model().objects.filter(email="admin@example.com").exists())

    def test_fr002_rejects_duplicate_email_ignoring_case(self):
        get_user_model().objects.create_user(
            email="student@example.com",
            name="Existing Student",
            role="student",
            password="StrongPass123!",
        )

        response = self.client.post(
            reverse("register"),
            {
                "name": "Another Student",
                "email": "Student@Example.COM",
                "password": "AnotherPass123!",
                "role": "student",
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("email", response.json())
        self.assertEqual(get_user_model().objects.count(), 1)


class LoginTests(TestCase):
    def setUp(self):
        self.email = "student@example.com"
        LoginAttempt.objects.filter(pk=login_failure_key(self.email)).delete()
        get_user_model().objects.create_user(
            email=self.email,
            name="Student",
            role="student",
            password="StrongPass123!",
        )

    def test_fr003_login_issues_jwt_pair(self):
        response = self.client.post(
            reverse("login"),
            {"email": "Student@EXAMPLE.COM", "password": "StrongPass123!"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("access", response.json())
        self.assertIn("refresh", response.json())

    def test_tc02_failed_logins_lock_account_for_cooldown(self):
        for _ in range(5):
            response = self.client.post(
                reverse("login"),
                {"email": self.email, "password": "wrong-password"},
            )
            self.assertEqual(response.status_code, 401)

        blocked = self.client.post(
            reverse("login"),
            {"email": self.email, "password": "StrongPass123!"},
        )
        self.assertEqual(blocked.status_code, 429)

        LoginAttempt.objects.filter(pk=login_failure_key(self.email)).delete()
        recovered = self.client.post(
            reverse("login"),
            {"email": self.email, "password": "StrongPass123!"},
        )
        self.assertEqual(recovered.status_code, 200)


class AdminOnlyAcademicView(APIView):
    allowed_roles = ("admin",)

    def post(self, request):
        return Response({"saved": True})


class RoleAccessTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.student = User.objects.create_user(
            email="student@example.com", name="Student", role="student", password="Pass123!"
        )
        self.admin = User.objects.create_superuser(
            email="admin@example.com", name="Admin", password="Pass123!"
        )

    def test_tc09_student_cannot_call_admin_only_endpoint(self):
        request = APIRequestFactory().post("/api/academic/courses", {})
        force_authenticate(request, user=self.student)

        with self.assertLogs("users.permissions", level="WARNING"):
            response = AdminOnlyAcademicView.as_view()(request)

        self.assertEqual(response.status_code, 403)

    def test_admin_can_call_admin_only_endpoint(self):
        request = APIRequestFactory().post("/api/academic/courses", {})
        force_authenticate(request, user=self.admin)

        response = AdminOnlyAcademicView.as_view()(request)

        self.assertEqual(response.status_code, 200)

    def test_protected_me_endpoint_requires_jwt(self):
        anonymous = self.client.get(reverse("me"))
        self.assertEqual(anonymous.status_code, 401)

        login = self.client.post(
            reverse("login"),
            {"email": "student@example.com", "password": "Pass123!"},
        )
        token = login.json()["access"]
        authorized = self.client.get(reverse("me"), HTTP_AUTHORIZATION=f"Bearer {token}")

        self.assertEqual(authorized.status_code, 200)
        self.assertEqual(authorized.json()["role"], "student")


class LogoutTests(TestCase):
    def setUp(self):
        get_user_model().objects.create_user(
            email="logout@example.com", name="Logout Student", role="student", password="Pass123!"
        )
        login = self.client.post(
            reverse("login"), {"email": "logout@example.com", "password": "Pass123!"}
        )
        self.assertEqual(login.status_code, 200)
        self.access = login.json()["access"]
        self.refresh = login.json()["refresh"]

    def test_fr005_logout_revokes_access_and_refresh_tokens(self):
        before = self.client.get(reverse("me"), HTTP_AUTHORIZATION=f"Bearer {self.access}")
        self.assertEqual(before.status_code, 200)

        logout = self.client.post(reverse("logout"), HTTP_AUTHORIZATION=f"Bearer {self.access}")
        self.assertEqual(logout.status_code, 204)
        self.assertEqual(
            self.client.get(reverse("me"), HTTP_AUTHORIZATION=f"Bearer {self.access}").status_code,
            401,
        )
        self.assertEqual(
            self.client.post(reverse("refresh"), {"refresh": self.refresh}).status_code, 401
        )

        new_login = self.client.post(
            reverse("login"), {"email": "logout@example.com", "password": "Pass123!"}
        )
        self.assertEqual(new_login.status_code, 200)
        self.assertEqual(
            self.client.get(
                reverse("me"), HTTP_AUTHORIZATION=f"Bearer {new_login.json()['access']}"
            ).status_code,
            200,
        )

    def test_refresh_works_before_logout(self):
        response = self.client.post(reverse("refresh"), {"refresh": self.refresh})
        self.assertEqual(response.status_code, 200)
        self.assertIn("access", response.json())

    def test_logout_requires_authentication(self):
        self.assertEqual(self.client.post(reverse("logout")).status_code, 401)
