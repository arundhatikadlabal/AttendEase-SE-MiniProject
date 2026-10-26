from django.urls import path

from .views import CorrectionSubmissionView

urlpatterns = [
    path("", CorrectionSubmissionView.as_view(), name="correction-submit"),
]
