from rest_framework import serializers


class SectionReportQuerySerializer(serializers.Serializer):
    section_id = serializers.IntegerField(min_value=1)
    start_date = serializers.DateField(required=False)
    end_date = serializers.DateField(required=False)
    export_format = serializers.ChoiceField(
        choices=("json", "csv", "pdf"),
        required=False,
        default="json",
    )

    def validate(self, attrs):
        start_date = attrs.get("start_date")
        end_date = attrs.get("end_date")
        if start_date is not None and end_date is not None and start_date > end_date:
            raise serializers.ValidationError(
                {"end_date": "End date must be on or after start date."}
            )
        return attrs


class DefaulterReportEntrySerializer(serializers.Serializer):
    student_name = serializers.CharField()
    usn = serializers.CharField(allow_null=True)
    course = serializers.CharField()
    attendance_percentage = serializers.DecimalField(max_digits=5, decimal_places=2)
    threshold = serializers.DecimalField(max_digits=5, decimal_places=2)
    status = serializers.CharField()


class ReportSectionSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    code = serializers.CharField()
    course = serializers.CharField()


class AttendanceDateRangeSerializer(serializers.Serializer):
    start_date = serializers.DateField(allow_null=True)
    end_date = serializers.DateField(allow_null=True)


class SectionAttendanceSummarySerializer(serializers.Serializer):
    section = ReportSectionSerializer()
    date_range = AttendanceDateRangeSerializer()
    average_attendance_percentage = serializers.DecimalField(
        max_digits=5,
        decimal_places=2,
    )
    total_sessions = serializers.IntegerField(min_value=0)
