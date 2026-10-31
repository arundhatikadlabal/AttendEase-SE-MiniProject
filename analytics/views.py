
from rest_framework.response import Response
from rest_framework.views import APIView

from users.models import User

from . import services
from .serializers import DefaulterReportEntrySerializer, DefaulterReportQuerySerializer


class DefaulterReportView(APIView):
    """FR-031: list defaulters enrolled in a section for faculty or admins."""

    allowed_roles = (User.Role.FACULTY, User.Role.ADMIN)

    def get(self, request):
        query = DefaulterReportQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        section, entries = services.section_defaulters(
            section_id=query.validated_data["section_id"],
            user=request.user,
        )
        return Response(
            {
                "section": {
                    "id": section.pk,
                    "code": section.code,
                    "course": section.course.code,
                },
                "students": DefaulterReportEntrySerializer(
                    instance=entries,
                    many=True,
                ).data,
            }
        )
