import re
from datetime import date

from django.views.generic import TemplateView
from rest_framework import status
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from users.models import User

from . import services
from .serializers import (
    AttendanceSubmissionSerializer,
    StartSessionSerializer,
    StudentMarkSerializer,
    record_data,
    roster_data,
    session_data,
)
from .services import submit_records

FACULTY_OR_ADMIN = (User.Role.FACULTY, User.Role.ADMIN)


class StudentPortalView(TemplateView):
    """NFR-007: responsive page; all student data still comes from protected APIs."""

    template_name = "attendance/student_portal.html"


class StudentDashboardView(APIView):
    """FR-020: show the student's attendance for each enrolled course."""

    allowed_roles = (User.Role.STUDENT,)

    def get(self, request):
        return Response({"courses": services.student_dashboard_courses(request.user)})


class StudentHistoryView(APIView):
    """FR-021: finalized session-by-session attendance for a student."""

    allowed_roles = (User.Role.STUDENT,)

    def get(self, request):
        dates = {}
        for key in ("from", "to"):
            raw = request.query_params.get(key)
            if raw is None:
                dates[key] = None
                continue
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
                raise ValidationError({key: "Use YYYY-MM-DD."})
            try:
                dates[key] = date.fromisoformat(raw)
            except ValueError as error:
                raise ValidationError({key: "Enter a valid date."}) from error
        if dates["from"] and dates["to"] and dates["from"] > dates["to"]:
            raise ValidationError({"from": "Must be on or before to."})
        return Response(
            {
                "history": services.student_session_history(
                    request.user, from_date=dates["from"], to_date=dates["to"]
                )
            }
        )


class AttendanceRecordsView(APIView):
    """Submit records for an existing open session; duplicates return 409."""

    allowed_roles = (User.Role.FACULTY,)

    def post(self, request, session_id):
        serializer = AttendanceSubmissionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        records = submit_records(
            faculty=request.user,
            session_id=session_id,
            records=serializer.validated_data["records"],
        )
        return Response([record_data(record) for record in records])


class SessionListView(APIView):
    """List sessions: faculty see their own sections, admins see all."""

    allowed_roles = FACULTY_OR_ADMIN

    def get(self, request):
        return Response(
            [session_data(s) for s in services.sessions_for_user(request.user)]
        )


class SessionStartView(APIView):
    """FR-014: faculty start a session for a scheduled period of their section."""

    allowed_roles = (User.Role.FACULTY,)

    def post(self, request):
        serializer = StartSessionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        session = services.start_session(
            faculty=request.user,
            timetable_slot=serializer.validated_data["timetable_slot_id"],
            date=serializer.validated_data["date"],
        )
        session = services.get_session_for_user(request.user, session.pk)
        return Response(session_data(session), status=status.HTTP_201_CREATED)


class SessionDetailView(APIView):
    """View one session (the section's faculty member or an admin)."""

    allowed_roles = FACULTY_OR_ADMIN

    def get(self, request, session_id):
        return Response(
            session_data(services.get_session_for_user(request.user, session_id))
        )


class SessionRosterView(APIView):
    """FR-015: the enrolled-student roster for a session, with marked status."""

    allowed_roles = FACULTY_OR_ADMIN

    def get(self, request, session_id):
        session = services.get_session_for_user(request.user, session_id)
        return Response(roster_data(session, services.session_roster(session)))


class StudentMarkView(APIView):
    """FR-016: open-session marking; FR-038: edits after session closure."""

    allowed_roles = (User.Role.FACULTY,)

    def put(self, request, session_id, student_id):
        serializer = StudentMarkSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        record = services.mark_student(
            faculty=request.user,
            session_id=session_id,
            student_id=student_id,
            status=serializer.validated_data["status"],
        )
        return Response(record_data(record))

    def patch(self, request, session_id, student_id):
        serializer = StudentMarkSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        record = services.edit_closed_record(
            faculty=request.user,
            session_id=session_id,
            student_id=student_id,
            status=serializer.validated_data["status"],
        )
        return Response(record_data(record))


class MarkAllPresentView(APIView):
    """FR-017: faculty mark every enrolled student present with one action."""

    allowed_roles = (User.Role.FACULTY,)

    def post(self, request, session_id):
        services.mark_all_present(faculty=request.user, session_id=session_id)
        session = services.get_session_for_user(request.user, session_id)
        return Response(roster_data(session, services.session_roster(session)))


class SessionCloseView(APIView):
    """FR-018: faculty close (finalize) a session after marking."""

    allowed_roles = (User.Role.FACULTY,)

    def post(self, request, session_id):
        services.close_session(faculty=request.user, session_id=session_id)
        session = services.get_session_for_user(request.user, session_id)
        return Response(roster_data(session, services.session_roster(session)))
