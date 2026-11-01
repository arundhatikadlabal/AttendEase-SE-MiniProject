import csv
from datetime import date
from io import StringIO

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from .models import AttendanceRecord, AttendanceSession, Course, Enrollment, Section


class ReportExportApiTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.faculty = User.objects.create_user(
            email="exports-faculty@example.com",
            name="Export Faculty",
            role=User.Role.FACULTY,
        )
        self.other_faculty = User.objects.create_user(
            email="exports-other@example.com",
            name="Other Faculty",
            role=User.Role.FACULTY,
        )
        self.student = User.objects.create_user(
            email="exports-student@example.com",
            name="Below Threshold",
            role=User.Role.STUDENT,
            usn="USN001",
        )
        self.course = Course.objects.create(
            code="CS401",
            title="Export Testing",
            shortage_threshold=75,
        )
        self.section = Section.objects.create(
            course=self.course,
            code="A",
            faculty=self.faculty,
        )
        self.other_section = Section.objects.create(
            course=self.course,
            code="B",
            faculty=self.other_faculty,
        )
        Enrollment.objects.create(section=self.section, student=self.student)
        self.client = APIClient()
        self.client.force_authenticate(self.faculty)
        self.defaulters_url = reverse("analytics-defaulters")
        self.summary_url = reverse("analytics-summary")

    def make_sessions(self, dates, *, section=None, present_count=0):
        section = section or self.section
        sessions = []
        for index, session_date in enumerate(dates):
            session = AttendanceSession.objects.create(
                section=section,
                date=session_date,
                closed=True,
            )
            sessions.append(session)
            AttendanceRecord.objects.create(
                session=session,
                student=self.student,
                status=(
                    AttendanceRecord.Status.PRESENT
                    if index < present_count
                    else AttendanceRecord.Status.ABSENT
                ),
            )
        return sessions

    def get_report(self, url, export_format, **filters):
        return self.client.get(
            url,
            {
                "section_id": self.section.pk,
                "export_format": export_format,
                **filters,
            },
        )

    def test_defaulter_csv_has_documented_columns_and_api_values(self):
        dates = [date(2026, 9, 1), date(2026, 9, 2)]
        self.make_sessions(dates, present_count=1)
        api = self.get_report(self.defaulters_url, "json")
        response = self.get_report(self.defaulters_url, "csv")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "text/csv; charset=utf-8")
        self.assertEqual(
            response["Content-Disposition"],
            'attachment; filename="defaulters-cs401-a.csv"',
        )
        rows = list(csv.reader(StringIO(response.content.decode("utf-8"))))
        self.assertEqual(
            rows[0],
            ["Student Name", "USN", "Course", "Attendance %", "Threshold", "Status"],
        )
        self.assertEqual(
            rows[1],
            ["Below Threshold", "USN001", "CS401", "50.00", "75.00", "Defaulter"],
        )
        self.assertEqual(rows[1][3], api.json()["students"][0]["attendance_percentage"])

    def test_defaulter_pdf_is_downloadable_and_contains_report_values(self):
        self.make_sessions([date(2026, 9, 1), date(2026, 9, 2)], present_count=1)
        response = self.get_report(self.defaulters_url, "pdf")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertEqual(
            response["Content-Disposition"],
            'attachment; filename="defaulters-cs401-a.pdf"',
        )
        self.assertTrue(response.content.startswith(b"%PDF-"))
        self.assertTrue(response.content.rstrip().endswith(b"%%EOF"))
        self.assertIn(b"Below Threshold", response.content)

    def test_summary_csv_and_pdf_respect_date_filters_and_api_values(self):
        self.make_sessions(
            [date(2026, 9, 1), date(2026, 9, 2), date(2026, 9, 3)],
            present_count=2,
        )
        filters = {"start_date": "2026-09-02", "end_date": "2026-09-03"}
        api = self.get_report(self.summary_url, "json", **filters)
        csv_response = self.get_report(self.summary_url, "csv", **filters)
        pdf_response = self.get_report(self.summary_url, "pdf", **filters)

        self.assertEqual(csv_response.status_code, 200)
        rows = list(csv.reader(StringIO(csv_response.content.decode("utf-8"))))
        self.assertEqual(
            rows[0],
            ["Section", "Date Range", "Average Attendance %", "Total Sessions"],
        )
        self.assertEqual(
            rows[1],
            ["CS401 - A", "2026-09-02 to 2026-09-03", "50.00", "2"],
        )
        self.assertEqual(rows[1][2], api.json()["average_attendance_percentage"])
        self.assertEqual(pdf_response.status_code, 200)
        self.assertEqual(pdf_response["Content-Type"], "application/pdf")
        self.assertTrue(pdf_response.content.startswith(b"%PDF-"))
        self.assertIn(b"2026-09-02 to 2026-09-03", pdf_response.content)

    def test_empty_reports_still_export_headers_or_zero_summary(self):
        self.make_sessions([date(2026, 9, 1)], present_count=1)
        defaulters = self.get_report(self.defaulters_url, "csv")
        summary = self.get_report(
            self.summary_url,
            "csv",
            start_date="2026-10-01",
            end_date="2026-10-02",
        )

        defaulter_rows = list(csv.reader(StringIO(defaulters.content.decode("utf-8"))))
        summary_rows = list(csv.reader(StringIO(summary.content.decode("utf-8"))))
        self.assertEqual(len(defaulter_rows), 1)
        self.assertEqual(summary_rows[1], ["CS401 - A", "", "0.00", "0"])

        no_matches = self.get_report(
            self.summary_url,
            "pdf",
            start_date="2026-10-01",
            end_date="2026-10-02",
        )
        self.assertEqual(no_matches.status_code, 200)
        self.assertTrue(no_matches.content.startswith(b"%PDF-"))

    def test_invalid_format_dates_and_section_ids_are_rejected(self):
        invalid_format = self.client.get(
            self.defaulters_url,
            {"section_id": self.section.pk, "export_format": "xlsx"},
        )
        invalid_date = self.get_report(
            self.summary_url,
            "csv",
            start_date="not-a-date",
        )
        invalid_range = self.get_report(
            self.summary_url,
            "pdf",
            start_date="2026-09-03",
            end_date="2026-09-01",
        )
        nonexistent = self.client.get(
            self.summary_url,
            {"section_id": 99999, "export_format": "csv"},
        )

        self.assertEqual(invalid_format.status_code, 400)
        self.assertEqual(invalid_date.status_code, 400)
        self.assertEqual(invalid_range.status_code, 400)
        self.assertEqual(nonexistent.status_code, 404)

    def test_json_default_and_export_authorization_are_preserved(self):
        self.assertEqual(self.client.get(self.defaulters_url).status_code, 400)
        self.assertEqual(
            self.client.get(self.summary_url, {"section_id": self.section.pk}).status_code,
            200,
        )
        unauthenticated = APIClient().get(
            self.defaulters_url,
            {"section_id": self.section.pk, "export_format": "pdf"},
        )
        self.assertEqual(unauthenticated.status_code, 401)

        self.client.force_authenticate(self.other_faculty)
        denied = self.client.get(
            self.defaulters_url,
            {"section_id": self.section.pk, "export_format": "csv"},
        )
        self.assertEqual(denied.status_code, 403)
