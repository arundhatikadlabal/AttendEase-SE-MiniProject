"""Business rules for academic setup (SRS FR-006 to FR-013)."""

from django.db import IntegrityError, transaction

from analytics.models import Course, Enrollment, Section
from users.models import User

from .models import Timetable


class AcademicConflict(Exception):
    """A write would break a uniqueness or scheduling rule; mapped to HTTP 409."""

    def __init__(self, field, message):
        super().__init__(message)
        self.field = field
        self.message = message


def normalize_code(code):
    return code.strip().upper()


def _require_role(user, role, label):
    if user.role != role or not user.is_active:
        raise ValueError(f"User {user.pk} is not an active {label}")


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


DUPLICATE_SECTION_MESSAGE = "This course already has a section with this code."


def _section_code_taken(course, code, exclude_pk=None):
    queryset = Section.objects.filter(course=course, code=code)
    if exclude_pk is not None:
        queryset = queryset.exclude(pk=exclude_pk)
    return queryset.exists()


def create_section(*, course, code):
    """FR-007 / FR-011: create a section whose code is unique within its course.

    Faculty is assigned separately (FR-013).
    """
    code = normalize_code(code)
    if _section_code_taken(course, code):
        raise AcademicConflict("code", DUPLICATE_SECTION_MESSAGE)
    try:
        with transaction.atomic():
            return Section.objects.create(course=course, code=code)
    except IntegrityError as error:
        raise AcademicConflict("code", DUPLICATE_SECTION_MESSAGE) from error


def update_section(section, *, code):
    """FR-007 / FR-011: rename a section without colliding with a sibling."""
    code = normalize_code(code)
    if _section_code_taken(section.course, code, exclude_pk=section.pk):
        raise AcademicConflict("code", DUPLICATE_SECTION_MESSAGE)
    section.code = code
    try:
        with transaction.atomic():
            section.save(update_fields=["code"])
    except IntegrityError as error:
        raise AcademicConflict("code", DUPLICATE_SECTION_MESSAGE) from error
    return section


DUPLICATE_ENROLLMENT_MESSAGE = "This student is already enrolled in this section."


def enroll_student(*, section, student):
    """FR-008: enroll a student into a section exactly once."""
    _require_role(student, User.Role.STUDENT, "student")
    if Enrollment.objects.filter(section=section, student=student).exists():
        raise AcademicConflict("student_id", DUPLICATE_ENROLLMENT_MESSAGE)
    try:
        with transaction.atomic():
            return Enrollment.objects.create(section=section, student=student)
    except IntegrityError as error:
        raise AcademicConflict("student_id", DUPLICATE_ENROLLMENT_MESSAGE) from error


def unenroll_student(*, section, student):
    """FR-008: remove a student from a section. Returns False if not enrolled."""
    deleted, _ = Enrollment.objects.filter(section=section, student=student).delete()
    return deleted > 0


OVERLAP_MESSAGE = "This period overlaps an existing period for this section."


def add_timetable_slot(*, section, day_of_week, start_time, end_time):
    """FR-009: add a weekly period, rejecting overlaps within the same section."""
    if end_time <= start_time:
        raise ValueError("end_time must be after start_time")
    overlapping = Timetable.objects.filter(
        section=section,
        day_of_week=day_of_week,
        start_time__lt=end_time,
        end_time__gt=start_time,
    )
    if overlapping.exists():
        raise AcademicConflict("start_time", OVERLAP_MESSAGE)
    try:
        with transaction.atomic():
            return Timetable.objects.create(
                section=section,
                day_of_week=day_of_week,
                start_time=start_time,
                end_time=end_time,
            )
    except IntegrityError as error:
        raise AcademicConflict("start_time", OVERLAP_MESSAGE) from error
