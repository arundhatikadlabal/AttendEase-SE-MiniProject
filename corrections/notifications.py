"""Faculty email notifications for submitted correction requests (FR-025)."""

import logging
from smtplib import SMTPException

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.core.mail import send_mail

from users.models import User

from .models import CorrectionRequest

logger = logging.getLogger(__name__)


def notify_faculty(correction_id):
    """Attempt delivery twice, logging failures without undoing submission.

    Call only after the submission transaction commits. Local development uses
    the console backend; deployments can configure SMTP through the environment.
    """
    correction = (
        CorrectionRequest.objects.select_related(
            "student",
            "record__session__section__course",
            "record__session__section__faculty",
        )
        .filter(pk=correction_id)
        .first()
    )
    if correction is None:
        logger.warning(
            "Correction email skipped: request_id=%s no longer exists", correction_id
        )
        return False

    section = correction.record.session.section
    faculty = section.faculty
    if (
        faculty is None
        or not faculty.is_active
        or faculty.role != User.Role.FACULTY
        or not faculty.email
    ):
        logger.warning(
            "Correction email skipped: request_id=%s has no active assigned faculty recipient",
            correction_id,
        )
        return False

    subject = f"AttendEase: attendance correction request #{correction.pk}"
    message = (
        f"A student has submitted an attendance correction request.\n\n"
        f"Request: #{correction.pk}\n"
        f"Student: {correction.student.name}\n"
        f"Course: {section.course.code} - {section.course.title}\n"
        f"Section: {section.code}\n"
        f"Session date: {correction.record.session.date.isoformat()}\n"
        f"Recorded attendance: {correction.record.get_status_display()}\n"
        f"Reason: {correction.reason}\n\n"
        "Review the request in AttendEase. This email does not change attendance.\n"
    )

    for attempt in range(1, 3):
        try:
            sent = send_mail(
                subject=subject,
                message=message,
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[faculty.email],
                fail_silently=False,
            )
            if sent == 1:
                return True
            logger.warning(
                "Correction email not sent: request_id=%s attempt=%s/2",
                correction_id,
                attempt,
            )
        except (
            SMTPException,
            OSError,
            ValueError,
            ImproperlyConfigured,
            ImportError,
        ) as error:
            # Email backends can raise SMTP, network, or configuration errors.
            # Log the type, never credentials, email addresses, or request reasons.
            logger.warning(
                "Correction email failed: request_id=%s attempt=%s/2 error_type=%s",
                correction_id,
                attempt,
                type(error).__name__,
            )
    return False
