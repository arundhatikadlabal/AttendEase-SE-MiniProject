# AttendEase – Student Attendance Management System

A web-based attendance management system built for the PES University Software Engineering Level 3 Mini-Project (Course UE24CS341A). AttendEase lets administrators configure courses and sections, faculty mark attendance and manage correction requests, and students track their own attendance, all through role-based web portals.

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

## Demo Videos

| Sprint | Video | What it shows |
|---|---|---|
| Sprint 1 | [Watch on Google Drive](https://drive.google.com/file/d/1vkmxofvLfEIK8cMxDIwxYYlnoZX04mYq/view?usp=sharing) | Registration and login, roles, academic setup, starting a session, duplicate checks, correction requests, logout |
| Sprint 2 | [Watch on Google Drive](https://drive.google.com/file/d/1zzhsHWEOjevVS80uCQdI6tnA3ZqunwUN/view?usp=sharing) | Mark all present, closing a session, edit window and audit history, student dashboard, approving and rejecting corrections, reports and export, CSV enrollment, performance and coverage |

## Documentation

### Design documents

| Document | Description |
|---|---|
| [SRS](AttendEase_Deliverables/AttendEase_SRS.pdf) | Software Requirements Specification — 38 functional requirements, 8 non-functional requirements, UML use-case diagram, security objectives & requirements |
| [SAD](AttendEase_Deliverables/AttendEase_SAD.pdf) | Software Architecture & Design Specification — component architecture, UML sequence diagrams, API design, security architecture |
| [Test Plan](AttendEase_Deliverables/AttendEase_TestPlan.pdf) | Software Test Plan — test strategy, security validation, 12 traceable test cases |
| [Combined Submission PDF](AttendEase_Combined_SRS_SAD_TestPlan.pdf) | SRS + SAD + Test Plan merged for final submission |
| [Deviations log](deviations.md) | Where the implementation differs from, or decides something not specified in, the SRS, SAD and Test Plan |

### Testing documents

| Document | Description |
|---|---|
| [Test Case Document](docs/Test_Case_Document.pdf) | Test cases TC-01 to TC-13 step by step, with expected and actual results, the automated tests behind each, and a requirement traceability matrix |
| [Unit Test Report](docs/Unit_Test_Report.pdf) | Results of all 320 automated tests, by module, test class and requirement |
| [Code Coverage Report](docs/Code_Coverage_Report.pdf) | Statement coverage of the service layer and all application code, with every line not run |
| [Branch Coverage Report](docs/Branch_Coverage_Report.pdf) | Decision (branch) coverage, with every outcome not taken |
| [System Validation
