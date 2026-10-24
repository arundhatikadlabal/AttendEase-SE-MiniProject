from rest_framework import serializers

from users.models import User


def _active_users(role, label):
    return serializers.PrimaryKeyRelatedField(
        queryset=User.objects.filter(role=role, is_active=True),
        error_messages={"does_not_exist": f"No active {label} exists with this id."},
    )


class CourseSerializer(serializers.Serializer):
    code = serializers.CharField(max_length=20)
    title = serializers.CharField(max_length=200)


class SectionSerializer(serializers.Serializer):
    code = serializers.CharField(max_length=20)


class EnrollmentSerializer(serializers.Serializer):
    student_id = _active_users(User.Role.STUDENT, "student")


def person_data(user):
    if user is None:
        return None
    return {"id": user.pk, "name": user.name, "email": user.email}


def section_data(section, include_course=False):
    data = {
        "id": section.pk,
        "code": section.code,
        "faculty": person_data(section.faculty),
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
        "sections": [section_data(section) for section in course.sections.all()],
    }
