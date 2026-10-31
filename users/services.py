from urllib.parse import urlencode

from django.conf import settings
from django.contrib.auth.password_validation import validate_password
from django.contrib.auth.tokens import PasswordResetTokenGenerator
from django.core.mail import send_mail
from django.db import transaction
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode

from .models import User

reset_tokens = PasswordResetTokenGenerator()


def send_password_reset_email(*, email, request):
    """FR-034: send a one-time reset link without exposing account existence."""
    user = User.objects.filter(email__iexact=email.strip(), is_active=True).first()
    if user is None:
        return
    query = urlencode(
        {
            "uid": urlsafe_base64_encode(force_bytes(user.pk)),
            "token": reset_tokens.make_token(user),
        }
    )
    link = request.build_absolute_uri(f"/api/auth/password-reset/confirm?{query}")
    send_mail(
        "AttendEase password reset",
        f"Use this link to reset your AttendEase password: {link}",
        settings.DEFAULT_FROM_EMAIL,
        [user.email],
    )


def reset_password(*, uid, token, new_password):
    """Validate a one-time token and invalidate existing JWTs after reset."""
    with transaction.atomic():
        try:
            user_id = urlsafe_base64_decode(uid).decode()
            user = User.objects.select_for_update().get(pk=user_id, is_active=True)
        except (
            TypeError,
            ValueError,
            OverflowError,
            UnicodeDecodeError,
            User.DoesNotExist,
        ):
            return False
        if not reset_tokens.check_token(user, token):
            return False
        validate_password(new_password, user=user)
        user.set_password(new_password)
        user.token_version += 1
        user.save(update_fields=["password", "token_version"])
    return True


def valid_password_reset_token(*, uid, token):
    try:
        user_id = urlsafe_base64_decode(uid).decode()
        user = User.objects.get(pk=user_id, is_active=True)
    except (
        TypeError,
        ValueError,
        OverflowError,
        UnicodeDecodeError,
        User.DoesNotExist,
    ):
        return False
    return reset_tokens.check_token(user, token)


def register_user(*, name, email, password, role, usn=None):
    """Create a student or faculty account with a hashed password."""
    if role not in (User.Role.STUDENT, User.Role.FACULTY):
        raise ValueError("Public registration cannot create administrators")
    return User.objects.create_user(
        name=name,
        email=email,
        password=password,
        role=role,
        usn=usn,
    )
