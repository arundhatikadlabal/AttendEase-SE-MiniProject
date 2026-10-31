from django.urls import path

from .views import DefaulterReportView

urlpatterns = [
    path("defaulters", DefaulterReportView.as_view(), name="analytics-defaulters"),
]
