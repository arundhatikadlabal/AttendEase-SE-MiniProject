# AttendEase – Student Attendance Management System

A web-based attendance management system built for the PES University Software Engineering Level 3 Mini-Project (Course UE24CS341A). AttendEase lets administrators configure courses and sections, faculty mark attendance and manage correction requests, and students track their own attendance ,all through role-based web portals.

## Team 3

| Name | USN | Role | Secondary Responsibility |
|---|---|---|---|
| Arundhati K | PES1UG24CS083 | Academic & Attendance Setup | Database design & data validation |
| Anshdeep Singh Sachdeva | PES1UG24CS070 | Attendance Updates & Corrections | API integration & code review |
| Atharva Ashish Vyas | PES1UG24CS093 | User Access & Student Portal | UI/UX & frontend support |
| Bhoomika Dayanand Jituri | PES1UG25CS807 | Attendance Analytics & Reporting | Testing, CI/CD, Jira & documentation |

## Project Overview

AttendEase addresses the manual, error-prone process of attendance tracking in academic institutions. It provides:

- **Authentication & role-based access** for Students, Faculty, and Administrators
- **Academic setup**: course, section, timetable, and faculty-assignment management
- **Attendance recording**: session-based marking with duplicate-entry prevention
- **Correction requests**: students can dispute records; faculty approve/reject with a full audit trail
- **Analytics & reporting**: attendance-shortage identification and defaulter reports

## Tech Stack

- **Backend**: Python 3.11, Django 4.x, Django REST Framework
- **Database**: PostgreSQL 14+
- **Frontend**: Django Templates, Bootstrap 5
- **CI/CD**: GitHub Actions
- **Containerization**: Docker, docker-compose
- **Project Tracking**: Jira / GitHub Projects

## Repository Structure

```
.
├── project-documentation/
│   ├── AttendEase_SRS.pdf
│   ├── AttendEase_SAD.pdf
│   ├── AttendEase_TestPlan.pdf
│   └── AttendEase_Combined_SRS_SAD_TestPlan.pdf
└── README.md
```

## Documentation

| Document | Description |
|---|---|
| [SRS](project-documentation/AttendEase_SRS.pdf) | Software Requirements Specification — 38 functional requirements, 8 non-functional requirements, UML use-case diagram, security objectives & requirements |
| [SAD](project-documentation/AttendEase_SAD.pdf) | Software Architecture & Design Specification — component architecture, UML sequence diagrams, API design, security architecture |
| [Test Plan](project-documentation/AttendEase_TestPlan.pdf) | Software Test Plan — test strategy, security validation, 12 traceable test cases |
| [Combined Submission PDF](project-documentation/AttendEase_Combined_SRS_SAD_TestPlan.pdf) | SRS + SAD + Test Plan merged for final submission |

## Methodology

This project follows an Agile methodology with sprint-based development, mandatory pull-request code review, CI/CD via GitHub Actions, and task tracking via Jira/GitHub Projects. Each team member owns one functional area end-to-end, from requirements through testing.
