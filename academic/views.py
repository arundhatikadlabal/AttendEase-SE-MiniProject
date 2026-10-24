from django.db.models import Prefetch
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response
from rest_framework.views import APIView

from analytics.models import Course, Enrollment, Section
from users.models import User

from . import services
from .models import Timetable
from .serializers import (
    AssignmentSerializer,
    CourseSerializer,
    EnrollmentSerializer,
    SectionSerializer,
    TimetableSlotSerializer,
    course_data,
    person_data,
    section_data,
    timetable_slot_data,
)

ANY_ROLE = (User.Role.STUDENT, User.Role.FACULTY, User.Role.ADMIN)
ADMIN_ONLY = (User.Role.ADMIN,)


def conflict_response(error):
    return Response({error.field: [error.message]}, status=status.HTTP_409_CONFLICT)


def sections_queryset():
    return (
        Section.objects.select_related("course", "faculty")
        .prefetch_related("timetable_slots")
        .order_by("code")
    )


def courses_queryset():
    return Course.objects.prefetch_related(
        Prefetch("sections", queryset=sections_queryset())
    ).order_by("code")


class CourseListView(APIView):
    """FR-006: list courses with their sections; admins create courses."""

    roles_by_method = {"GET": ANY_ROLE, "POST": ADMIN_ONLY}

    def get(self, request):
        return Response([course_data(course) for course in courses_queryset()])

    def post(self, request):
        serializer = CourseSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            course = services.create_course(**serializer.validated_data)
        except services.AcademicConflict as error:
            return conflict_response(error)
        return Response(course_data(course), status=status.HTTP_201_CREATED)


class CourseDetailView(APIView):
    """FR-006: view or edit one course."""

    roles_by_method = {"GET": ANY_ROLE, "PATCH": ADMIN_ONLY}

    def get(self, request, course_id):
        return Response(course_data(get_object_or_404(courses_queryset(), pk=course_id)))

    def patch(self, request, course_id):
        course = get_object_or_404(Course, pk=course_id)
        serializer = CourseSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        try:
            services.update_course(course, **serializer.validated_data)
        except services.AcademicConflict as error:
            return conflict_response(error)
        return Response(course_data(get_object_or_404(courses_queryset(), pk=course_id)))


class CourseSectionListView(APIView):
    """FR-007 / FR-011: list or create sections within a course."""

    roles_by_method = {"GET": ANY_ROLE, "POST": ADMIN_ONLY}

    def get(self, request, course_id):
        course = get_object_or_404(Course, pk=course_id)
        return Response(
            [section_data(section) for section in sections_queryset().filter(course=course)]
        )

    def post(self, request, course_id):
        course = get_object_or_404(Course, pk=course_id)
        serializer = SectionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            section = services.create_section(course=course, **serializer.validated_data)
        except services.AcademicConflict as error:
            return conflict_response(error)
        section = sections_queryset().get(pk=section.pk)
        return Response(section_data(section, include_course=True), status=status.HTTP_201_CREATED)


class SectionDetailView(APIView):
    """FR-007 / FR-011: view or rename a section."""

    roles_by_method = {"GET": ANY_ROLE, "PATCH": ADMIN_ONLY}

    def get(self, request, section_id):
        section = get_object_or_404(sections_queryset(), pk=section_id)
        return Response(section_data(section, include_course=True))

    def patch(self, request, section_id):
        section = get_object_or_404(Section.objects.select_related("course"), pk=section_id)
        serializer = SectionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            services.update_section(section, **serializer.validated_data)
        except services.AcademicConflict as error:
            return conflict_response(error)
        section = sections_queryset().get(pk=section.pk)
        return Response(section_data(section, include_course=True))


class SectionEnrollmentListView(APIView):
    """FR-008: admins enroll students; admins and the section's faculty see the list."""

    roles_by_method = {"GET": (User.Role.FACULTY, User.Role.ADMIN), "POST": ADMIN_ONLY}

    def get(self, request, section_id):
        section = get_object_or_404(Section, pk=section_id)
        if request.user.role == User.Role.FACULTY and section.faculty_id != request.user.pk:
            raise PermissionDenied("You are not assigned to this section.")
        enrollments = (
            Enrollment.objects.filter(section=section)
            .select_related("student")
            .order_by("student__name", "student__email")
        )
        return Response([person_data(enrollment.student) for enrollment in enrollments])

    def post(self, request, section_id):
        section = get_object_or_404(Section, pk=section_id)
        serializer = EnrollmentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        student = serializer.validated_data["student_id"]
        try:
            services.enroll_student(section=section, student=student)
        except services.AcademicConflict as error:
            return conflict_response(error)
        return Response(
            {"section_id": section.pk, "student": person_data(student)},
            status=status.HTTP_201_CREATED,
        )


class SectionEnrollmentDetailView(APIView):
    """FR-008: admins remove a student from a section."""

    allowed_roles = ADMIN_ONLY

    def delete(self, request, section_id, student_id):
        section = get_object_or_404(Section, pk=section_id)
        student = get_object_or_404(User, pk=student_id)
        if not services.unenroll_student(section=section, student=student):
            return Response(
                {"detail": "This student is not enrolled in this section."},
                status=status.HTTP_404_NOT_FOUND,
            )
        return Response(status=status.HTTP_204_NO_CONTENT)


class SectionTimetableView(APIView):
    """FR-009: view a section's weekly timetable; admins add periods."""

    roles_by_method = {"GET": ANY_ROLE, "POST": ADMIN_ONLY}

    def get(self, request, section_id):
        section = get_object_or_404(Section, pk=section_id)
        return Response(
            [timetable_slot_data(slot) for slot in section.timetable_slots.all()]
        )

    def post(self, request, section_id):
        section = get_object_or_404(Section, pk=section_id)
        serializer = TimetableSlotSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            slot = services.add_timetable_slot(section=section, **serializer.validated_data)
        except services.AcademicConflict as error:
            return conflict_response(error)
        return Response(timetable_slot_data(slot), status=status.HTTP_201_CREATED)


class TimetableSlotDetailView(APIView):
    """FR-009: admins remove a timetable period."""

    allowed_roles = ADMIN_ONLY

    def delete(self, request, slot_id):
        get_object_or_404(Timetable, pk=slot_id).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class AssignmentView(APIView):
    """FR-013: admins assign a faculty member to a course-section."""

    allowed_roles = ADMIN_ONLY

    def post(self, request):
        serializer = AssignmentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        section = services.assign_faculty(
            section=serializer.validated_data["section_id"],
            faculty=serializer.validated_data["faculty_id"],
        )
        section = sections_queryset().get(pk=section.pk)
        return Response(section_data(section, include_course=True))


class MySectionsView(APIView):
    """Sections the caller teaches (faculty) or is enrolled in (student)."""

    allowed_roles = (User.Role.STUDENT, User.Role.FACULTY)

    def get(self, request):
        return Response(
            [
                section_data(section, include_course=True)
                for section in services.sections_for_user(request.user)
            ]
        )
