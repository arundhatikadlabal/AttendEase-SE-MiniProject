from datetime import time

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from analytics.models import Course, Enrollment, Section

from . import services
from .models import Timetable

PASSWORD = "StrongPass123!"


class AcademicTestCase(TestCase):
    def setUp(self):
        User = get_user_model()
        self.admin = User.objects.create_superuser(
            email="admin@example.com", name="Admin", password=PASSWORD
        )
        self.faculty = User.objects.create_user(
            email="faculty@example.com", name="Faculty One", role="faculty", password=PASSWORD
        )
        self.other_faculty = User.objects.create_user(
            email="faculty2@example.com", name="Faculty Two", role="faculty", password=PASSWORD
        )
        self.student = User.objects.create_user(
            email="student@example.com", name="Student One", role="student", password=PASSWORD
        )
        self.client = APIClient()

    def as_user(self, user):
        self.client.force_authenticate(user=user)
        return self.client

    def jwt_client(self, user):
        login = APIClient().post(
            reverse("login"), {"email": user.email, "password": PASSWORD}
        )
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {login.json()['access']}")
        return client

    def make_course(self, code="CS101", title="Intro to Programming"):
        return Course.objects.create(code=code, title=title)

    def make_section(self, course, code="A", faculty=None):
        return Section.objects.create(course=course, code=code, faculty=faculty)


class CourseTests(AcademicTestCase):
    """FR-006: administrators create and edit courses."""

    def test_fr006_admin_creates_course(self):
        response = self.as_user(self.admin).post(
            reverse("academic-courses"), {"code": " cs101 ", "title": "Intro to Programming"}
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["code"], "CS101")
        self.assertTrue(Course.objects.filter(code="CS101").exists())

    def test_fr006_admin_edits_course(self):
        course = self.make_course()

        response = self.as_user(self.admin).patch(
            reverse("academic-course", args=[course.pk]),
            {"title": "Programming Fundamentals"},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        course.refresh_from_db()
        self.assertEqual(course.title, "Programming Fundamentals")
        self.assertEqual(course.code, "CS101")

    def test_fr006_duplicate_course_code_is_rejected(self):
        self.make_course(code="CS101")

        created = self.as_user(self.admin).post(
            reverse("academic-courses"), {"code": "cs101", "title": "Copy"}
        )
        other = self.make_course(code="CS102")
        renamed = self.client.patch(
            reverse("academic-course", args=[other.pk]), {"code": "CS101"}, format="json"
        )

        self.assertEqual(created.status_code, 409)
        self.assertEqual(renamed.status_code, 409)
        self.assertIn("code", created.json())
        self.assertEqual(Course.objects.filter(code="CS101").count(), 1)

    def test_fr006_invalid_course_payload_is_rejected(self):
        response = self.as_user(self.admin).post(
            reverse("academic-courses"), {"code": "", "title": "No Code"}
        )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(Course.objects.exists())

    def test_fr006_unknown_course_returns_404(self):
        response = self.as_user(self.admin).patch(
            reverse("academic-course", args=[9999]), {"title": "X"}, format="json"
        )

        self.assertEqual(response.status_code, 404)

    def test_fr006_any_role_lists_courses(self):
        self.make_course(code="CS102", title="Data Structures")
        self.make_course(code="CS101")

        response = self.as_user(self.student).get(reverse("academic-courses"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual([c["code"] for c in response.json()], ["CS101", "CS102"])

    def test_fr006_non_admins_cannot_create_or_edit_courses(self):
        course = self.make_course()
        for user in (self.student, self.faculty):
            with self.subTest(role=user.role), self.assertLogs(
                "users.permissions", level="WARNING"
            ):
                create = self.as_user(user).post(
                    reverse("academic-courses"), {"code": "CS999", "title": "Nope"}
                )
                edit = self.client.patch(
                    reverse("academic-course", args=[course.pk]),
                    {"title": "Nope"},
                    format="json",
                )
            self.assertEqual(create.status_code, 403)
            self.assertEqual(edit.status_code, 403)
        self.assertEqual(Course.objects.count(), 1)

    def test_course_endpoints_require_authentication(self):
        self.assertEqual(self.client.get(reverse("academic-courses")).status_code, 401)

    def test_tc09_student_calling_real_admin_endpoint_is_denied(self):
        """TC-09 / SEC-003 repeated against the real academic-setup endpoint."""
        client = self.jwt_client(self.student)

        with self.assertLogs("users.permissions", level="WARNING"):
            response = client.post(
                reverse("academic-courses"), {"code": "CS999", "title": "Nope"}
            )

        self.assertEqual(response.status_code, 403)
        self.assertFalse(Course.objects.exists())


class SectionTests(AcademicTestCase):
    """FR-007: administrators create and edit sections within a course."""

    def setUp(self):
        super().setUp()
        self.course = self.make_course()

    def test_fr007_admin_creates_section_without_faculty(self):
        response = self.as_user(self.admin).post(
            reverse("academic-course-sections", args=[self.course.pk]), {"code": "a"}
        )

        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertEqual(body["code"], "A")
        self.assertEqual(body["course"]["code"], "CS101")
        self.assertIsNone(body["faculty"])
        section = Section.objects.get(course=self.course, code="A")
        self.assertIsNone(section.faculty)

    def test_fr007_admin_edits_section_code(self):
        section = self.make_section(self.course, code="A")

        response = self.as_user(self.admin).patch(
            reverse("academic-section", args=[section.pk]), {"code": "c"}, format="json"
        )

        self.assertEqual(response.status_code, 200)
        section.refresh_from_db()
        self.assertEqual(section.code, "C")

    def test_fr007_section_code_is_required(self):
        response = self.as_user(self.admin).post(
            reverse("academic-course-sections", args=[self.course.pk]), {"code": " "}
        )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(Section.objects.exists())

    def test_fr007_unknown_course_or_section_returns_404(self):
        create = self.as_user(self.admin).post(
            reverse("academic-course-sections", args=[9999]), {"code": "A"}
        )
        detail = self.client.get(reverse("academic-section", args=[9999]))

        self.assertEqual(create.status_code, 404)
        self.assertEqual(detail.status_code, 404)

    def test_fr007_lists_sections_for_course(self):
        self.make_section(self.course, code="B")
        self.make_section(self.course, code="A", faculty=self.faculty)
        self.make_section(self.make_course(code="CS102"), code="Z")

        response = self.as_user(self.student).get(
            reverse("academic-course-sections", args=[self.course.pk])
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual([s["code"] for s in response.json()], ["A", "B"])
        self.assertEqual(response.json()[0]["faculty"]["name"], "Faculty One")

    def test_fr007_course_list_includes_sections(self):
        self.make_section(self.course, code="B")
        self.make_section(self.course, code="A")

        response = self.as_user(self.faculty).get(reverse("academic-courses"))

        [listed] = response.json()
        self.assertEqual([s["code"] for s in listed["sections"]], ["A", "B"])

    def test_fr007_non_admins_cannot_create_or_edit_sections(self):
        section = self.make_section(self.course, code="A")
        with self.assertLogs("users.permissions", level="WARNING"):
            create = self.as_user(self.faculty).post(
                reverse("academic-course-sections", args=[self.course.pk]), {"code": "B"}
            )
            edit = self.as_user(self.student).patch(
                reverse("academic-section", args=[section.pk]), {"code": "Z"}, format="json"
            )

        self.assertEqual(create.status_code, 403)
        self.assertEqual(edit.status_code, 403)
        section.refresh_from_db()
        self.assertEqual(section.code, "A")


class DuplicateSectionCodeTests(AcademicTestCase):
    """FR-011: section codes are unique within a course."""

    def setUp(self):
        super().setUp()
        self.course = self.make_course()
        self.section_a = self.make_section(self.course, code="A")

    def test_fr011_duplicate_section_code_in_same_course_is_rejected(self):
        response = self.as_user(self.admin).post(
            reverse("academic-course-sections", args=[self.course.pk]), {"code": " a "}
        )

        self.assertEqual(response.status_code, 409)
        self.assertIn("code", response.json())
        self.assertEqual(Section.objects.filter(course=self.course).count(), 1)

    def test_fr011_same_section_code_allowed_in_different_course(self):
        other_course = self.make_course(code="CS102")

        response = self.as_user(self.admin).post(
            reverse("academic-course-sections", args=[other_course.pk]), {"code": "A"}
        )

        self.assertEqual(response.status_code, 201)

    def test_fr011_renaming_to_sibling_code_is_rejected(self):
        section_b = self.make_section(self.course, code="B")

        response = self.as_user(self.admin).patch(
            reverse("academic-section", args=[section_b.pk]), {"code": "a"}, format="json"
        )

        self.assertEqual(response.status_code, 409)
        section_b.refresh_from_db()
        self.assertEqual(section_b.code, "B")

    def test_fr011_renaming_section_to_its_own_code_is_allowed(self):
        response = self.as_user(self.admin).patch(
            reverse("academic-section", args=[self.section_a.pk]), {"code": "a"}, format="json"
        )

        self.assertEqual(response.status_code, 200)

    def test_fr011_database_enforces_unique_section_code(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            Section.objects.create(course=self.course, code="A")


class EnrollmentTests(AcademicTestCase):
    """FR-008: administrators enroll students into a section."""

    def setUp(self):
        super().setUp()
        self.section = self.make_section(self.make_course(), faculty=self.faculty)
        self.url = reverse("academic-section-enrollments", args=[self.section.pk])

    def test_fr008_admin_enrolls_student(self):
        response = self.as_user(self.admin).post(self.url, {"student_id": self.student.pk})

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["student"]["id"], self.student.pk)
        self.assertTrue(
            Enrollment.objects.filter(section=self.section, student=self.student).exists()
        )

    def test_fr008_duplicate_enrollment_is_rejected(self):
        Enrollment.objects.create(section=self.section, student=self.student)

        response = self.as_user(self.admin).post(self.url, {"student_id": self.student.pk})

        self.assertEqual(response.status_code, 409)
        self.assertIn("student_id", response.json())
        self.assertEqual(Enrollment.objects.count(), 1)

    def test_fr008_only_student_accounts_can_be_enrolled(self):
        response = self.as_user(self.admin).post(self.url, {"student_id": self.faculty.pk})

        self.assertEqual(response.status_code, 400)
        self.assertIn("student_id", response.json())
        self.assertFalse(Enrollment.objects.exists())

    def test_fr008_inactive_student_cannot_be_enrolled(self):
        self.student.is_active = False
        self.student.save()

        response = self.as_user(self.admin).post(self.url, {"student_id": self.student.pk})

        self.assertEqual(response.status_code, 400)

    def test_fr008_unknown_section_returns_404(self):
        response = self.as_user(self.admin).post(
            reverse("academic-section-enrollments", args=[9999]),
            {"student_id": self.student.pk},
        )

        self.assertEqual(response.status_code, 404)

    def test_fr008_roster_visible_to_admin_and_assigned_faculty_only(self):
        Enrollment.objects.create(section=self.section, student=self.student)

        admin_view = self.as_user(self.admin).get(self.url)
        faculty_view = self.as_user(self.faculty).get(self.url)
        other_faculty_view = self.as_user(self.other_faculty).get(self.url)
        with self.assertLogs("users.permissions", level="WARNING"):
            student_view = self.as_user(self.student).get(self.url)

        self.assertEqual(admin_view.status_code, 200)
        self.assertEqual([s["id"] for s in admin_view.json()], [self.student.pk])
        self.assertEqual(faculty_view.status_code, 200)
        self.assertEqual(other_faculty_view.status_code, 403)
        self.assertEqual(student_view.status_code, 403)

    def test_fr008_non_admin_cannot_enroll(self):
        with self.assertLogs("users.permissions", level="WARNING"):
            response = self.as_user(self.faculty).post(
                self.url, {"student_id": self.student.pk}
            )

        self.assertEqual(response.status_code, 403)
        self.assertFalse(Enrollment.objects.exists())

    def test_fr008_admin_unenrolls_student(self):
        Enrollment.objects.create(section=self.section, student=self.student)
        url = reverse(
            "academic-section-enrollment", args=[self.section.pk, self.student.pk]
        )

        first = self.as_user(self.admin).delete(url)
        second = self.client.delete(url)

        self.assertEqual(first.status_code, 204)
        self.assertEqual(second.status_code, 404)
        self.assertFalse(Enrollment.objects.exists())

    def test_fr008_service_rejects_non_student(self):
        with self.assertRaises(ValueError):
            services.enroll_student(section=self.section, student=self.faculty)


class TimetableTests(AcademicTestCase):
    """FR-009: administrators define a weekly timetable per section."""

    def setUp(self):
        super().setUp()
        self.section = self.make_section(self.make_course())
        self.url = reverse("academic-section-timetable", args=[self.section.pk])

    def add_slot(self, day, start, end, section_url=None):
        return self.as_user(self.admin).post(
            section_url or self.url,
            {"day_of_week": day, "start_time": start, "end_time": end},
        )

    def test_fr009_admin_defines_weekly_timetable(self):
        friday = self.add_slot(5, "14:00", "15:00")
        monday = self.add_slot(1, "09:00", "10:00")

        self.assertEqual(friday.status_code, 201)
        self.assertEqual(monday.status_code, 201)
        self.assertEqual(monday.json()["day_name"], "Monday")

        listed = self.as_user(self.student).get(self.url)
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(
            [(s["day_of_week"], s["start_time"], s["end_time"]) for s in listed.json()],
            [(1, "09:00", "10:00"), (5, "14:00", "15:00")],
        )
        section = self.as_user(self.faculty).get(
            reverse("academic-section", args=[self.section.pk])
        )
        self.assertEqual(len(section.json()["timetable"]), 2)

    def test_fr009_end_time_must_follow_start_time(self):
        response = self.add_slot(1, "10:00", "09:00")

        self.assertEqual(response.status_code, 400)
        self.assertIn("end_time", response.json())
        self.assertFalse(Timetable.objects.exists())

    def test_fr009_invalid_day_is_rejected(self):
        self.assertEqual(self.add_slot(8, "09:00", "10:00").status_code, 400)

    def test_fr009_overlapping_period_in_same_section_is_rejected(self):
        self.add_slot(1, "09:00", "10:00")

        overlap = self.add_slot(1, "09:30", "10:30")
        adjacent = self.add_slot(1, "10:00", "11:00")
        other_day = self.add_slot(2, "09:30", "10:30")

        self.assertEqual(overlap.status_code, 409)
        self.assertEqual(adjacent.status_code, 201)
        self.assertEqual(other_day.status_code, 201)
        self.assertEqual(Timetable.objects.count(), 3)

    def test_fr009_other_sections_can_use_same_period(self):
        self.add_slot(1, "09:00", "10:00")
        other = self.make_section(self.section.course, code="B")

        response = self.add_slot(
            1, "09:00", "10:00", reverse("academic-section-timetable", args=[other.pk])
        )

        self.assertEqual(response.status_code, 201)

    def test_fr009_admin_removes_period(self):
        slot = Timetable.objects.create(
            section=self.section, day_of_week=1, start_time=time(9), end_time=time(10)
        )

        response = self.as_user(self.admin).delete(
            reverse("academic-timetable-slot", args=[slot.pk])
        )

        self.assertEqual(response.status_code, 204)
        self.assertFalse(Timetable.objects.exists())

    def test_fr009_non_admin_cannot_change_timetable(self):
        slot = Timetable.objects.create(
            section=self.section, day_of_week=1, start_time=time(9), end_time=time(10)
        )
        with self.assertLogs("users.permissions", level="WARNING"):
            create = self.as_user(self.faculty).post(
                self.url, {"day_of_week": 2, "start_time": "09:00", "end_time": "10:00"}
            )
            delete = self.client.delete(reverse("academic-timetable-slot", args=[slot.pk]))

        self.assertEqual(create.status_code, 403)
        self.assertEqual(delete.status_code, 403)
        self.assertEqual(Timetable.objects.count(), 1)

    def test_fr009_service_detects_overlap(self):
        services.add_timetable_slot(
            section=self.section, day_of_week=3, start_time=time(11), end_time=time(12)
        )

        with self.assertRaises(services.AcademicConflict):
            services.add_timetable_slot(
                section=self.section,
                day_of_week=3,
                start_time=time(10, 30),
                end_time=time(11, 30),
            )
