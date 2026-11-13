from django.urls import path

from .views import (
    CorrectionDecisionView,
    CorrectionSubmissionView,
    StudentCorrectionsView,
)

urlpatterns = [
    path(
        "corrections/mine", StudentCorrectionsView.as_view(), name="student-corrections"
    ),
    path(
        "corrections/<int:correction_id>",
        CorrectionDecisionView.as_view(),
        name="correction-decision",
    ),
    path("corrections", CorrectionSubmissionView.as_view(), name="correction-submit"),
]
