from rest_framework import serializers


class AttendanceEntrySerializer(serializers.Serializer):
    student_id = serializers.IntegerField(min_value=1)
    status = serializers.ChoiceField(choices=("present", "absent"))


class AttendanceSubmissionSerializer(serializers.Serializer):
    records = AttendanceEntrySerializer(many=True, allow_empty=False)


def record_data(record):
    return {
        "id": record.pk,
        "session_id": record.session_id,
        "student_id": record.student_id,
        "status": record.status.lower(),
    }
