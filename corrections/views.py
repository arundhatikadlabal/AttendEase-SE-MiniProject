from rest_framework import status
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework.views import APIView

from users.models import User

from .serializers import (
    CorrectionDecisionSerializer,
    CorrectionSubmissionSerializer,
    correction_data,
    pending_correction_data,
)
from .services import (
    approve_correction,
    pending_corrections_for_faculty,
    reject_correction,
    submit_correction,
)


class CorrectionQueuePagination(PageNumberPagination):
    page_size = 25
    page_size_query_param = "page_size"
    max_page_size = 100


class CorrectionSubmissionView(APIView):
    """Students submit requests; faculty list their own pending queue."""

    roles_by_method = {"POST": (User.Role.STUDENT,), "GET": (User.Role.FACULTY,)}

    def get(self, request):
        queryset = pending_corrections_for_faculty(request.user)
        paginator = CorrectionQueuePagination()
        page = paginator.paginate_queryset(queryset, request, view=self)
        return paginator.get_paginated_response(
            [pending_correction_data(correction) for correction in page]
        )

    def post(self, request):
        serializer = CorrectionSubmissionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        correction = submit_correction(
            student=request.user, **serializer.validated_data
        )
        return Response(correction_data(correction), status=status.HTTP_201_CREATED)


class CorrectionDecisionView(APIView):
    """FR-027 / FR-028: assigned faculty approve or reject a pending request."""

    allowed_roles = (User.Role.FACULTY,)

    def patch(self, request, correction_id):
        serializer = CorrectionDecisionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        if serializer.validated_data["action"] == "approve":
            correction = approve_correction(
                faculty=request.user, correction_id=correction_id
            )
        else:
            correction = reject_correction(
                faculty=request.user,
                correction_id=correction_id,
                reason=serializer.validated_data["reason"],
            )
        return Response(correction_data(correction), status=status.HTTP_200_OK)
