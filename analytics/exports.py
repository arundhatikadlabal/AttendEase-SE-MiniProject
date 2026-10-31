"""Render report payloads in downloadable formats without recalculating them."""

import csv
from io import BytesIO, StringIO
from xml.sax.saxutils import escape

from django.http import HttpResponse
from django.utils.text import slugify
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Table, TableStyle

REPORT_COLUMNS = {
    "defaulters": (
        ("Student Name", "student_name"),
        ("USN", "usn"),
        ("Course", "course"),
        ("Attendance %", "attendance_percentage"),
        ("Threshold", "threshold"),
        ("Status", "status"),
    ),
    "summary": (
        ("Section", "section"),
        ("Date Range", "date_range"),
        ("Average Attendance %", "average_attendance_percentage"),
        ("Total Sessions", "total_sessions"),
    ),
}


def report_export_response(report, *, report_type, export_format):
    """Return CSV or PDF from the exact payload used by the JSON response."""
    columns = REPORT_COLUMNS[report_type]
    rows = _report_rows(report, report_type)
    if export_format == "csv":
        content = _csv_content(columns, rows)
        content_type = "text/csv; charset=utf-8"
    else:
        content = _pdf_content(report_type, columns, rows)
        content_type = "application/pdf"

    section = report["section"]
    section_name = slugify(f"{section['course']}-{section['code']}")
    filename = f"{report_type}-{section_name}.{export_format}"
    response = HttpResponse(content, content_type=content_type)
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


def _report_rows(report, report_type):
    if report_type == "defaulters":
        return [
            [entry[key] if entry[key] is not None else "" for _, key in REPORT_COLUMNS[report_type]]
            for entry in report["students"]
        ]

    section = report["section"]
    date_range = report["date_range"]
    start_date = date_range["start_date"]
    end_date = date_range["end_date"]
    formatted_range = (
        f"{start_date} to {end_date}"
        if start_date is not None and end_date is not None
        else ""
    )
    return [[
        f"{section['course']} - {section['code']}",
        formatted_range,
        report["average_attendance_percentage"],
        report["total_sessions"],
    ]]


def _csv_content(columns, rows):
    output = StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow([label for label, _ in columns])
    writer.writerows(rows)
    return output.getvalue()


def _pdf_content(report_type, columns, rows):
    output = BytesIO()
    document = SimpleDocTemplate(
        output,
        pagesize=landscape(A4),
        leftMargin=15 * mm,
        rightMargin=15 * mm,
        topMargin=15 * mm,
        bottomMargin=15 * mm,
        pageCompression=0,
    )
    styles = getSampleStyleSheet()
    title_style = styles["Title"]
    title_style.alignment = TA_CENTER
    title = "Defaulter Report" if report_type == "defaulters" else "Section Attendance Summary"
    table_data = [[Paragraph(escape(label), styles["BodyText"]) for label, _ in columns]]
    table_data.extend(
        [[Paragraph(escape(str(value)), styles["BodyText"]) for value in row] for row in rows]
    )
    table = Table(table_data, repeatRows=1, hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e8eef5")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#172b4d")),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#9aa7b5")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    document.build([Paragraph(escape(title), title_style), table])
    return output.getvalue()
