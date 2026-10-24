from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

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
        self.assertTrue(user.check_password("StrongPass123!"))
        self.assertNotEqual(user.password, "StrongPass123!")
        self.assertNotIn("password", response.json())

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
