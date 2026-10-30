from django.urls import path

from .views import (
    AssignmentView,
    CourseActivationView,
    CourseDetailView,
    CourseListView,
    CourseSectionListView,
    MySectionsView,
    SectionActivationView,
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
    path(
        "courses/<int:course_id>/deactivate",
        CourseActivationView.as_view(active=False),
        name="academic-course-deactivate",
    ),
    path(
        "courses/<int:course_id>/activate",
        CourseActivationView.as_view(active=True),
        name="academic-course-activate",
    ),
    path(
        "sections/<int:section_id>/deactivate",
        SectionActivationView.as_view(active=False),
        name="academic-section-deactivate",
    ),
    path(
        "sections/<int:section_id>/activate",
        SectionActivationView.as_view(active=True),
        name="academic-section-activate",
    ),
    path("assignments", AssignmentView.as_view(), name="academic-assignments"),
    path("my-sections", MySectionsView.as_view(), name="academic-my-sections"),
]
