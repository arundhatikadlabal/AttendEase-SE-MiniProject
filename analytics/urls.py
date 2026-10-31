from django.urls import path

from .views import DefaulterReportView, SectionAttendanceSummaryView

urlpatterns = [
    path("defaulters", DefaulterReportView.as_view(), name="analytics-defaulters"),
    path("summary", SectionAttendanceSummaryView.as_view(), name="analytics-summary"),
]
