from rest_framework import serializers


class DefaulterReportQuerySerializer(serializers.Serializer):
    section_id = serializers.IntegerField(min_value=1)


class DefaulterReportEntrySerializer(serializers.Serializer):
    student_name = serializers.CharField()
    usn = serializers.CharField(allow_null=True)
    course = serializers.CharField()
    attendance_percentage = serializers.DecimalField(max_digits=5, decimal_places=2)
    threshold = serializers.DecimalField(max_digits=5, decimal_places=2)
    status = serializers.CharField()
