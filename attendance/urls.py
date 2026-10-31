from django.urls import path

from .views import (
    AttendanceHistoryView,
    AttendanceRecordsView,
    MarkAllPresentView,
    SessionCloseView,
    SessionDetailView,
    SessionListView,
    SessionRosterView,
    SessionStartView,
    StudentMarkView,
)

urlpatterns = [
    path(
        "sessions/<int:session_id>/records/<int:student_id>/history",
        AttendanceHistoryView.as_view(),
        name="attendance-history",
    ),
    path("sessions", SessionListView.as_view(), name="attendance-sessions"),
    path("sessions/start", SessionStartView.as_view(), name="attendance-session-start"),
    path(
        "sessions/<int:session_id>",
        SessionDetailView.as_view(),
        name="attendance-session",
    ),
    path(
        "sessions/<int:session_id>/roster",
        SessionRosterView.as_view(),
        name="attendance-session-roster",
    ),
    path(
        "sessions/<int:session_id>/records",
        AttendanceRecordsView.as_view(),
        name="attendance-records",
    ),
    path(
        "sessions/<int:session_id>/records/<int:student_id>",
        StudentMarkView.as_view(),
        name="attendance-student-mark",
    ),
    path(
        "sessions/<int:session_id>/mark-all-present",
        MarkAllPresentView.as_view(),
        name="attendance-mark-all-present",
    ),
    path(
        "sessions/<int:session_id>/close",
        SessionCloseView.as_view(),
        name="attendance-session-close",
    ),
]
