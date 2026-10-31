from django.urls import path

from .views import CorrectionDecisionView, CorrectionSubmissionView

urlpatterns = [
    path(
        "corrections/<int:correction_id>",
        CorrectionDecisionView.as_view(),
        name="correction-decision",
    ),
    path("corrections", CorrectionSubmissionView.as_view(), name="correction-submit"),
]
