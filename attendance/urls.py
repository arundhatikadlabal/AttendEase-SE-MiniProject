from django.urls import path

from .views import AttendanceRecordsView

urlpatterns = [
    path(
        "sessions/<int:session_id>/records",
        AttendanceRecordsView.as_view(),
        name="attendance-records",
    ),
]
