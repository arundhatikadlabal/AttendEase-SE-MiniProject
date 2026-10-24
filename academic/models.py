from django.db import models
from django.db.models import F, Q


class Timetable(models.Model):
    """One weekly recurring class period for a section (FR-009).

    Course, Section and Enrollment are the shared models in the analytics app;
    the academic app manages them through its service layer.
    """

    class Weekday(models.IntegerChoices):
        MONDAY = 1, "Monday"
        TUESDAY = 2, "Tuesday"
        WEDNESDAY = 3, "Wednesday"
        THURSDAY = 4, "Thursday"
        FRIDAY = 5, "Friday"
        SATURDAY = 6, "Saturday"
        SUNDAY = 7, "Sunday"

    section = models.ForeignKey(
        "analytics.Section",
        on_delete=models.CASCADE,
        related_name="timetable_slots",
    )
    day_of_week = models.PositiveSmallIntegerField(choices=Weekday.choices)
    start_time = models.TimeField()
    end_time = models.TimeField()

    class Meta:
        ordering = ["day_of_week", "start_time"]
        constraints = [
            models.CheckConstraint(
                check=Q(end_time__gt=F("start_time")),
                name="timetable_end_after_start",
            ),
            models.UniqueConstraint(
                fields=["section", "day_of_week", "start_time"],
                name="unique_timetable_slot_start_per_section_day",
            ),
        ]

    def __str__(self):
        return (
            f"{self.section} {self.get_day_of_week_display()} "
            f"{self.start_time:%H:%M}-{self.end_time:%H:%M}"
        )
