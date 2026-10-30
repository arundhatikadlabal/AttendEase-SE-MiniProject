from django.utils import timezone
from rest_framework import serializers

from academic.models import Timetable


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


class StartSessionSerializer(serializers.Serializer):
    timetable_slot_id = serializers.PrimaryKeyRelatedField(
        queryset=Timetable.objects.select_related("section"),
        error_messages={"does_not_exist": "No timetable period exists with this id."},
    )
    date = serializers.DateField(required=False)

    def validate(self, attrs):
        attrs.setdefault("date", timezone.localdate())
        return attrs


def session_data(session):
    section = session.section
    slot = session.timetable_slot
    return {
        "id": session.pk,
        "date": session.date.isoformat(),
        "closed": session.closed,
        "section": {
            "id": section.pk,
            "code": section.code,
            "course_code": section.course.code,
        },
        "timetable_slot": None
        if slot is None
        else {
            "id": slot.pk,
            "day_name": slot.get_day_of_week_display(),
            "start_time": slot.start_time.strftime("%H:%M"),
            "end_time": slot.end_time.strftime("%H:%M"),
        },
    }
