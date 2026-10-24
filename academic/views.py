from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from analytics.models import Course
from users.models import User

from . import services
from .serializers import CourseSerializer, course_data

ANY_ROLE = (User.Role.STUDENT, User.Role.FACULTY, User.Role.ADMIN)
ADMIN_ONLY = (User.Role.ADMIN,)


def conflict_response(error):
    return Response({error.field: [error.message]}, status=status.HTTP_409_CONFLICT)


def courses_queryset():
    return Course.objects.order_by("code")


class CourseListView(APIView):
    """FR-006: list courses; admins create courses."""

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
