from django.urls import path

from .views import (
    CourseDetailView,
    CourseListView,
    CourseSectionListView,
    SectionDetailView,
    SectionEnrollmentDetailView,
    SectionEnrollmentListView,
    SectionTimetableView,
    TimetableSlotDetailView,
)

urlpatterns = [
    path("courses", CourseListView.as_view(), name="academic-courses"),
    path("courses/<int:course_id>", CourseDetailView.as_view(), name="academic-course"),
    path(
        "courses/<int:course_id>/sections",
        CourseSectionListView.as_view(),
        name="academic-course-sections",
    ),
    path("sections/<int:section_id>", SectionDetailView.as_view(), name="academic-section"),
    path(
        "sections/<int:section_id>/enrollments",
        SectionEnrollmentListView.as_view(),
        name="academic-section-enrollments",
    ),
    path(
        "sections/<int:section_id>/enrollments/<int:student_id>",
        SectionEnrollmentDetailView.as_view(),
        name="academic-section-enrollment",
    ),
    path(
        "sections/<int:section_id>/timetable",
        SectionTimetableView.as_view(),
        name="academic-section-timetable",
    ),
    path(
        "timetable/<int:slot_id>",
        TimetableSlotDetailView.as_view(),
        name="academic-timetable-slot",
    ),
]
