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


def pending_correction_data(correction):
    """Include enough attendance context for a faculty member to review a request."""
    data = correction_data(correction)
    session = correction.record.session
    section = session.section
    course = section.course
    data.update(
        {
            "student": {"id": correction.student_id, "name": correction.student.name},
            "session": {"id": session.pk, "date": session.date.isoformat()},
            "section": {"id": section.pk, "code": section.code},
            "course": {"id": course.pk, "code": course.code, "title": course.title},
            "attendance_status": correction.record.status,
        }
    )
    return data


class CorrectionApprovalSerializer(serializers.Serializer):
    action = serializers.ChoiceField(choices=("approve",))
