from rest_framework import serializers


class CourseSerializer(serializers.Serializer):
    code = serializers.CharField(max_length=20)
    title = serializers.CharField(max_length=200)


def course_data(course):
    return {"id": course.pk, "code": course.code, "title": course.title}
