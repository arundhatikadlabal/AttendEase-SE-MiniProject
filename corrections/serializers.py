from rest_framework import serializers


class CorrectionSubmissionSerializer(serializers.Serializer):
    record_id = serializers.IntegerField(min_value=1)
    reason = serializers.CharField(
        max_length=2000, allow_blank=False, trim_whitespace=True
    )


def correction_data(correction):
    return {
        "id": correction.pk,
        "record_id": correction.record_id,
        "student_id": correction.student_id,
        "reason": correction.reason,
        "status": correction.status,
        "created_at": correction.created_at.isoformat(),
        "acted_by": correction.acted_by_id,
        "acted_at": correction.acted_at.isoformat() if correction.acted_at else None,
    }
