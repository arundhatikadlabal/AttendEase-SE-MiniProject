"""Business rules for academic setup (SRS FR-006 to FR-013)."""

from django.db import IntegrityError, transaction

from analytics.models import Course


class AcademicConflict(Exception):
    """A write would break a uniqueness or scheduling rule; mapped to HTTP 409."""

    def __init__(self, field, message):
        super().__init__(message)
        self.field = field
        self.message = message


def normalize_code(code):
    return code.strip().upper()


DUPLICATE_COURSE_MESSAGE = "A course with this code already exists."


def create_course(*, code, title):
    """FR-006: create a course with a unique code."""
    code = normalize_code(code)
    if Course.objects.filter(code=code).exists():
        raise AcademicConflict("code", DUPLICATE_COURSE_MESSAGE)
    try:
        with transaction.atomic():
            return Course.objects.create(code=code, title=title.strip())
    except IntegrityError as error:
        raise AcademicConflict("code", DUPLICATE_COURSE_MESSAGE) from error


def update_course(course, *, code=None, title=None):
    """FR-006: edit a course's code and/or title."""
    if code is not None:
        code = normalize_code(code)
        if Course.objects.filter(code=code).exclude(pk=course.pk).exists():
            raise AcademicConflict("code", DUPLICATE_COURSE_MESSAGE)
        course.code = code
    if title is not None:
        course.title = title.strip()
    try:
        with transaction.atomic():
            course.save()
    except IntegrityError as error:
        raise AcademicConflict("code", DUPLICATE_COURSE_MESSAGE) from error
    return course
