
from rest_framework.response import Response
from rest_framework.views import APIView

from users.models import User

from . import services
from .exports import report_export_response
from .serializers import (
    DefaulterReportEntrySerializer,
    SectionAttendanceSummarySerializer,
    SectionReportQuerySerializer,
)


class DefaulterReportView(APIView):
    """FR-031: list defaulters enrolled in a section for faculty or admins."""

    allowed_roles = (User.Role.FACULTY, User.Role.ADMIN)

    def get(self, request):
        query = SectionReportQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        section, entries = services.section_defaulters(
            section_id=query.validated_data["section_id"],
            user=request.user,
            start_date=query.validated_data.get("start_date"),
            end_date=query.validated_data.get("end_date"),
        )
        report = {
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
        return _report_response(report, "defaulters", query.validated_data)


class SectionAttendanceSummaryView(APIView):
    """FR-032: summarize closed-session attendance for a section."""

    allowed_roles = (User.Role.FACULTY, User.Role.ADMIN)

    def get(self, request):
        query = SectionReportQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        summary = services.section_attendance_summary(
            section_id=query.validated_data["section_id"],
            user=request.user,
            start_date=query.validated_data.get("start_date"),
            end_date=query.validated_data.get("end_date"),
        )
        report = SectionAttendanceSummarySerializer(instance=summary).data
        return _report_response(report, "summary", query.validated_data)


def _report_response(report, report_type, query):
    export_format = query["export_format"]
    if export_format == "json":
        return Response(report)
    return report_export_response(
        report,
        report_type=report_type,
        export_format=export_format,
    )
