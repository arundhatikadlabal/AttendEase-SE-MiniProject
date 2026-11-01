from urllib.parse import parse_qs, urlparse

from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework.test import APIClient

from users.models import User


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class PasswordResetTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="student@example.com",
            name="Student",
            role=User.Role.STUDENT,
            password="OldStrongPass123!",
        )
        self.client = APIClient()

    def request_link(self):
        response = self.client.post(
            reverse("password-reset"), {"email": "Student@EXAMPLE.COM"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(mail.outbox), 1)
        link = mail.outbox[0].body.split()[-1]
        return parse_qs(urlparse(link).query)

    def test_fr034_request_does_not_reveal_unknown_email(self):
        known = self.client.post(reverse("password-reset"), {"email": self.user.email})
        unknown = self.client.post(
            reverse("password-reset"), {"email": "nobody@example.com"}
        )
        self.assertEqual(known.status_code, unknown.status_code)
        self.assertEqual(known.data, unknown.data)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, [self.user.email])

    def test_fr034_confirm_changes_password_once_and_revokes_jwt(self):
        login = self.client.post(
            reverse("login"),
            {"email": self.user.email, "password": "OldStrongPass123!"},
        )
        old_access = login.data["access"]
        query = self.request_link()
        payload = {
            "uid": query["uid"][0],
            "token": query["token"][0],
            "new_password": "NewStrongPass123!",
        }
        confirm_url = reverse("password-reset-confirm")
        self.assertEqual(
            self.client.get(
                confirm_url, {"uid": payload["uid"], "token": payload["token"]}
            ).status_code,
            200,
        )
        self.assertEqual(self.client.post(confirm_url, payload).status_code, 200)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("NewStrongPass123!"))
        self.assertEqual(self.client.post(confirm_url, payload).status_code, 400)
        self.assertEqual(
            self.client.get(
                reverse("me"), HTTP_AUTHORIZATION=f"Bearer {old_access}"
            ).status_code,
            401,
        )
        self.assertEqual(
            self.client.post(
                reverse("login"),
                {"email": self.user.email, "password": "NewStrongPass123!"},
            ).status_code,
            200,
        )

    def test_fr034_rejects_bad_token_and_weak_password(self):
        query = self.request_link()
        payload = {
            "uid": query["uid"][0],
            "token": "invalid",
            "new_password": "NewStrongPass123!",
        }
        url = reverse("password-reset-confirm")
        self.assertEqual(self.client.post(url, payload).status_code, 400)
        payload["token"] = query["token"][0]
        payload["new_password"] = "123"
        self.assertEqual(self.client.post(url, payload).status_code, 400)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("OldStrongPass123!"))
