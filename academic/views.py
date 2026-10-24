from django.db.models import Prefetch
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from analytics.models import Course, Section
from users.models import User

from . import services
from .serializers import CourseSerializer, SectionSerializer, course_data, section_data

ANY_ROLE = (User.Role.STUDENT, User.Role.FACULTY, User.Role.ADMIN)
ADMIN_ONLY = (User.Role.ADMIN,)


def conflict_response(error):
    return Response({error.field: [error.message]}, status=status.HTTP_409_CONFLICT)


def sections_queryset():
    return Section.objects.select_related("course", "faculty").order_by("code")


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
    """FR-007: list or create sections within a course."""

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
        section = services.create_section(course=course, **serializer.validated_data)
        section = sections_queryset().get(pk=section.pk)
        return Response(section_data(section, include_course=True), status=status.HTTP_201_CREATED)


class SectionDetailView(APIView):
    """FR-007: view or rename a section."""

    roles_by_method = {"GET": ANY_ROLE, "PATCH": ADMIN_ONLY}

    def get(self, request, section_id):
        section = get_object_or_404(sections_queryset(), pk=section_id)
        return Response(section_data(section, include_course=True))

    def patch(self, request, section_id):
        section = get_object_or_404(Section.objects.select_related("course"), pk=section_id)
        serializer = SectionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.update_section(section, **serializer.validated_data)
        section = sections_queryset().get(pk=section.pk)
        return Response(section_data(section, include_course=True))
