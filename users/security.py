import hashlib
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from .models import LoginAttempt


def login_failure_key(email):
    digest = hashlib.sha256(email.encode("utf-8")).hexdigest()
    return digest


def is_login_locked(email):
    attempt = LoginAttempt.objects.filter(pk=login_failure_key(email)).first()
    return bool(attempt and attempt.expires_at > timezone.now() and attempt.failures >= 5)


@transaction.atomic
def record_failed_login(email):
    key = login_failure_key(email)
    now = timezone.now()
    attempt, _ = LoginAttempt.objects.select_for_update().get_or_create(
        pk=key,
        defaults={"expires_at": now + timedelta(minutes=15)},
    )
    if attempt.expires_at <= now:
        attempt.failures = 0
        attempt.expires_at = now + timedelta(minutes=15)
    attempt.failures += 1
    attempt.save(update_fields=["failures", "expires_at"])


def clear_failed_logins(email):
    LoginAttempt.objects.filter(pk=login_failure_key(email)).delete()
