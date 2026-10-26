from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from users.models import User

from .serializers import CorrectionSubmissionSerializer, correction_data
from .services import submit_correction


class CorrectionSubmissionView(APIView):
    allowed_roles = (User.Role.STUDENT,)

    def post(self, request):
        serializer = CorrectionSubmissionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        correction = submit_correction(
            student=request.user, **serializer.validated_data
        )
        return Response(correction_data(correction), status=status.HTTP_201_CREATED)
