
from django.conf import settings
from django.db import models


class Course(models.Model):
    code = models.CharField(max_length=20, unique=True)
    title = models.CharField(max_length=200)
    shortage_threshold = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=75.00,
    )

    def __str__(self):
        return f"{self.code} - {self.title}"


class Section(models.Model):
    course = models.ForeignKey(
        Course,
        on_delete=models.CASCADE,
        related_name="sections",
    )
    code = models.CharField(max_length=20)
    faculty = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="teaching_sections",
        null=True,
        blank=True,
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["course", "code"],
                name="unique_section_code_per_course",
            )
        ]

    def __str__(self):
        return f"{self.course.code} - {self.code}"


class Enrollment(models.Model):
    section = models.ForeignKey(
        Section,
        on_delete=models.CASCADE,
        related_name="enrollments",
    )
    student = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="attendance_enrollments",
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["section", "student"],
                name="unique_student_enrollment_per_section",
            )
        ]


class AttendanceSession(models.Model):
    section = models.ForeignKey(
        Section,
        on_delete=models.CASCADE,
        related_name="attendance_sessions",
    )
    date = models.DateField()
    closed = models.BooleanField(default=False)


class AttendanceRecord(models.Model):
    class Status(models.TextChoices):
        PRESENT = "PRESENT", "Present"
        ABSENT = "ABSENT", "Absent"

    session = models.ForeignKey(
        AttendanceSession,
        on_delete=models.CASCADE,
        related_name="records",
    )
    student = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="attendance_records",
    )
    status = models.CharField(
        max_length=10,
        choices=Status.choices,
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["session", "student"],
                name="unique_attendance_record_per_session_student",
            )
        ]
