from decimal import Decimal

from rest_framework import serializers

from analytics.models import Section
from users.models import User

from .models import Timetable


def _active_users(role, label):
    return serializers.PrimaryKeyRelatedField(
        queryset=User.objects.filter(role=role, is_active=True),
        error_messages={"does_not_exist": f"No active {label} exists with this id."},
    )


class CourseSerializer(serializers.Serializer):
    code = serializers.CharField(max_length=20)
    title = serializers.CharField(max_length=200)
    shortage_threshold = serializers.DecimalField(
        max_digits=5,
        decimal_places=2,
        min_value=Decimal("0.00"),
        max_value=Decimal("100.00"),
        required=False,
    )


class SectionSerializer(serializers.Serializer):
    code = serializers.CharField(max_length=20)


class EnrollmentSerializer(serializers.Serializer):
    student_id = _active_users(User.Role.STUDENT, "student")


class TimetableSlotSerializer(serializers.Serializer):
    day_of_week = serializers.ChoiceField(choices=Timetable.Weekday.choices)
    start_time = serializers.TimeField()
    end_time = serializers.TimeField()

    def validate(self, attrs):
        if attrs["end_time"] <= attrs["start_time"]:
            raise serializers.ValidationError(
                {"end_time": "End time must be after start time."}
            )
        return attrs


class AssignmentSerializer(serializers.Serializer):
    section_id = serializers.PrimaryKeyRelatedField(
        queryset=Section.objects.all(),
        error_messages={"does_not_exist": "No section exists with this id."},
    )
    faculty_id = _active_users(User.Role.FACULTY, "faculty member")


def person_data(user):
    if user is None:
        return None
    return {"id": user.pk, "name": user.name, "email": user.email}


def timetable_slot_data(slot):
    return {
        "id": slot.pk,
        "day_of_week": slot.day_of_week,
        "day_name": slot.get_day_of_week_display(),
        "start_time": slot.start_time.strftime("%H:%M"),
        "end_time": slot.end_time.strftime("%H:%M"),
    }


def section_data(section, include_course=False):
    data = {
        "id": section.pk,
        "code": section.code,
        "is_active": section.is_active,
        "faculty": person_data(section.faculty),
        "timetable": [timetable_slot_data(slot) for slot in section.timetable_slots.all()],
    }
    if include_course:
        course = section.course
        data["course"] = {"id": course.pk, "code": course.code, "title": course.title}
    return data


def course_data(course):
    return {
        "id": course.pk,
        "code": course.code,
        "title": course.title,
        "shortage_threshold": course.shortage_threshold,
        "is_active": course.is_active,
        "sections": [section_data(section) for section in course.sections.all()],
    }


class CsvEnrollmentSerializer(serializers.Serializer):
    file = serializers.FileField()
