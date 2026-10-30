from django.urls import path

from .views import (
    AttendanceRecordsView,
    SessionDetailView,
    SessionListView,
    SessionStartView,
)

urlpatterns = [
    path("sessions", SessionListView.as_view(), name="attendance-sessions"),
    path("sessions/start", SessionStartView.as_view(), name="attendance-session-start"),
    path(
        "sessions/<int:session_id>",
        SessionDetailView.as_view(),
        name="attendance-session",
    ),
    path(
        "sessions/<int:session_id>/records",
        AttendanceRecordsView.as_view(),
        name="attendance-records",
    ),
]
