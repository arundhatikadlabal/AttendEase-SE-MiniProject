from rest_framework.response import Response
from rest_framework.views import APIView

from users.models import User

from .serializers import AttendanceSubmissionSerializer, record_data
from .services import submit_records


class AttendanceRecordsView(APIView):
    """Submit records for an existing open session; duplicates return 409."""

    allowed_roles = (User.Role.FACULTY,)

    def post(self, request, session_id):
        serializer = AttendanceSubmissionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        records = submit_records(
            faculty=request.user,
            session_id=session_id,
            records=serializer.validated_data["records"],
        )
        return Response([record_data(record) for record in records])
