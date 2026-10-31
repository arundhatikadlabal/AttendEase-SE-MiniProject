from rest_framework import status
from rest_framework.pagination import PageNumberPagination
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


class AttendanceHistoryView(APIView):
    """NFR-003: read-only history, restricted to the record's authorized users."""

    allowed_roles = (User.Role.STUDENT, User.Role.FACULTY, User.Role.ADMIN)

    def get(self, request, session_id, student_id):
        from .audit import history_for_user

        history = history_for_user(
            user=request.user, session_id=session_id, student_id=student_id
        )
        paginator = PageNumberPagination()
        paginator.page_size = 25
        entries = paginator.paginate_queryset(history, request, view=self)
        return paginator.get_paginated_response(
            [
                {
                    "id": entry.pk,
                    "record_id": entry.record_id,
                    "action": entry.action,
                    "old_status": entry.old_status,
                    "new_status": entry.new_status,
                    "actor_id": entry.actor_id,
                    "correction_id": entry.correction_id,
                    "reason": entry.reason,
                    "timestamp": entry.timestamp.isoformat(),
                }
                for entry in entries
            ]
        )
