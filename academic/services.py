"""Business rules for academic setup (SRS FR-006 to FR-013)."""

import csv
import io

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


INACTIVE_COURSE_MESSAGE = "This course is deactivated."
INACTIVE_SECTION_MESSAGE = "This section or its course is deactivated."


def require_active_section(section):
    """FR-012: no new enrollments, periods or sessions for inactive sections."""
    if not section.is_active or not section.course.is_active:
        raise AcademicConflict("section", INACTIVE_SECTION_MESSAGE)


def set_course_active(course, active):
    """FR-012: deactivate (or reactivate) a course; its data is kept."""
    course.is_active = active
    course.save(update_fields=["is_active"])
    return course


def set_section_active(section, active):
    """FR-012: deactivate (or reactivate) a section; its data is kept."""
    section.is_active = active
    section.save(update_fields=["is_active"])
    return section


def create_section(*, course, code):
    """FR-007 / FR-011: create a section whose code is unique within its course.

    Faculty is assigned separately (FR-013).
    """
    if not course.is_active:
        raise AcademicConflict("course", INACTIVE_COURSE_MESSAGE)
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
    require_active_section(section)
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
    require_active_section(section)
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


def assign_faculty(*, section, faculty):
    """FR-013: make a faculty member responsible for a section."""
    _require_role(faculty, User.Role.FACULTY, "faculty member")
    section.faculty = faculty
    section.save(update_fields=["faculty"])
    return section


def sections_for_user(user):
    """Sections a faculty member teaches, or a student is enrolled in."""
    queryset = Section.objects.select_related("course", "faculty").prefetch_related(
        "timetable_slots"
    )
    queryset = queryset.filter(is_active=True, course__is_active=True)
    if user.role == User.Role.FACULTY:
        return queryset.filter(faculty=user).order_by("course__code", "code")
    if user.role == User.Role.STUDENT:
        return queryset.filter(enrollments__student=user).order_by("course__code", "code")
    return queryset.none()


MAX_CSV_BYTES = 1024 * 1024
MAX_CSV_ROWS = 1000


class CsvEnrollmentError(Exception):
    """The upload is unusable or has invalid rows; nothing was enrolled."""

    def __init__(self, errors):
        super().__init__("CSV enrollment failed")
        self.errors = errors


def _read_csv_emails(upload):
    if upload.size > MAX_CSV_BYTES:
        raise CsvEnrollmentError([{"row": None, "error": "File is larger than 1 MB."}])
    try:
        text = upload.read().decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise CsvEnrollmentError(
            [{"row": None, "error": "File must be UTF-8 encoded CSV."}]
        ) from error
    reader = csv.DictReader(io.StringIO(text))
    headers = {(name or "").strip().lower(): name for name in reader.fieldnames or []}
    if "email" not in headers:
        raise CsvEnrollmentError(
            [{"row": 1, "error": "The first row must be a header with an 'email' column."}]
        )
    rows = [
        (number, (row.get(headers["email"]) or "").strip().lower())
        for number, row in enumerate(reader, start=2)
    ]
    rows = [(number, email) for number, email in rows if email]
    if not rows:
        raise CsvEnrollmentError([{"row": None, "error": "The file has no student rows."}])
    if len(rows) > MAX_CSV_ROWS:
        raise CsvEnrollmentError(
            [{"row": None, "error": f"At most {MAX_CSV_ROWS} rows per upload."}]
        )
    return rows


def enroll_students_from_csv(*, section, upload):
    """FR-010: enroll every student listed in a CSV with an 'email' column.

    All-or-nothing: if any row is invalid nothing is enrolled and every bad
    row is reported. Students already enrolled are skipped, not errors.
    """
    require_active_section(section)
    rows = _read_csv_emails(upload)
    students = {
        user.email: user
        for user in User.objects.filter(
            email__in=[email for _, email in rows],
            role=User.Role.STUDENT,
            is_active=True,
        )
    }
    errors, seen = [], set()
    for number, email in rows:
        if email in seen:
            errors.append({"row": number, "email": email, "error": "Listed twice."})
        elif email not in students:
            errors.append(
                {"row": number, "email": email, "error": "No active student with this email."}
            )
        seen.add(email)
    if errors:
        raise CsvEnrollmentError(errors)

    already = set(
        Enrollment.objects.filter(
            section=section, student__in=students.values()
        ).values_list("student__email", flat=True)
    )
    new = [students[email] for _, email in rows if email not in already]
    with transaction.atomic():
        Enrollment.objects.bulk_create(
            [Enrollment(section=section, student=student) for student in new],
            ignore_conflicts=True,
        )
    return {"enrolled": [s.email for s in new], "already_enrolled": sorted(already)}
