from django.urls import path

from .views import CourseDetailView, CourseListView

urlpatterns = [
    path("courses", CourseListView.as_view(), name="academic-courses"),
    path("courses/<int:course_id>", CourseDetailView.as_view(), name="academic-course"),
]
