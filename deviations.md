# AttendEase — Deviations from SRS / SAD / Test Plan

Running log of places where the implementation differs from, or makes a decision not specified by, the submitted SRS v1.2, SAD v1.0 and Test Plan. Each entry names the requirement and the pull request that introduced it, so it can be explained at the final demo.

## Academic setup (Role 2 — Arundhati K)

### D-01: Course codes are case-insensitive (FR-006)

**Documents:** SRS FR-006 and Appendix B.1 define a course `code` but do not say whether `cs101` and `CS101` are the same course.

**Implementation:** Course codes are trimmed and stored upper-case. `cs101`, `CS101` and ` CS101 ` therefore refer to the same course, and creating a second one returns 409 Conflict. The existing `unique=True` constraint on `analytics.Course.code` stays as the database backstop.

**Why:** Course codes are identifiers that people type inconsistently. Treating different spellings as different courses would let duplicates through.

**Introduced in:** `feature/fr-006-course-management`.

### D-02: Error responses use DRF's default body, not the SAD envelope (FR-006 onwards)

**Documents:** SAD §4.4 says all API errors return `{"error_code", "message", "details"}`, and that validation conflicts such as duplicates return 409 Conflict with a descriptive `error_code`.

**Implementation:**
- **Status codes follow the SAD.** Duplicates return 409, malformed input 400, wrong role 403, unknown ids 404 and missing authentication 401.
- **The body follows DRF's default instead of the envelope.** It is `{"<field>": ["<message>"]}`, for example `{"code": ["A course with this code already exists."]}`. Errors that aren't tied to a field use `{"detail": "..."}`.

**Why:** This is the format the already-merged `users` app (FR-001 to FR-005) returns. The envelope is a cross-cutting concern and isn't implemented anywhere in the codebase yet. Adding it only to the academic endpoints would give the frontend two error formats. It should be added project-wide in one change, for example with a custom DRF `EXCEPTION_HANDLER`.

**Introduced in:** `feature/fr-006-course-management`.

### D-03: Duplicate section codes are detected case-insensitively (FR-011)

**Documents:** SRS FR-011 says the system shall prevent duplicate section codes within a course. It does not say whether `a` and `A` are the same code.

**Implementation:** Section codes are trimmed and stored upper-case, the same rule as course codes (D-01). Creating or renaming a section to a code that another section in the same course already uses returns 409 Conflict. This holds whatever the case or surrounding whitespace, so ` a ` clashes with `A`. The same code is still allowed in a different course. The existing `unique_section_code_per_course` constraint on `analytics.Section` remains the database backstop.

**Why:** A case-sensitive check would let `A` and `a` exist side by side. Users can't tell those apart on a roster or report, which defeats the purpose of FR-011.

**Introduced in:** `feature/fr-007-section-management` (upper-case normalisation) and `feature/fr-011-duplicate-section-validation` (the 409 duplicate check).

### D-04: Academic endpoints beyond the SAD's API table (FR-006 to FR-013)

**Documents:** SAD §4.3 lists only `GET /api/academic/courses` and `POST /api/academic/assignments` for academic setup, and says the remaining endpoints follow the same conventions.

**Implementation:** These endpoints were added to cover FR-006 to FR-009 and TC-03:
- `courses/{id}`
- `courses/{id}/sections`
- `sections/{id}`
- `sections/{id}/enrollments[/{student_id}]`
- `sections/{id}/timetable`
- `timetable/{id}`
- `my-sections`

They use the same no-trailing-slash style as `/api/auth/`. `my-sections` returns the sections a faculty member teaches or a student is enrolled in. It lets the API demonstrate TC-03's expected result ("faculty sees the section on their dashboard") until the faculty web UI exists.

**Introduced in:** `feature/fr-006-course-management` through `feature/fr-013-faculty-assignment`.

### D-05: Course, Section and Enrollment stay in the `analytics` app (FR-006 to FR-013)

**Documents:** SAD §3.4 assigns course, section and timetable management to the Academic Setup API & Service.

**Implementation:**
- **Models stay in `analytics`.** `Course`, `Section` and `Enrollment` were already defined in `analytics/models.py`, and the FR-029/FR-030 attendance calculations read from them. The `academic` app provides the API and service layer over those models instead of defining its own. Only the new `Timetable` model lives in `academic`.
- **Faculty is optional when a section is created.** `analytics.Section.faculty` was made nullable (migration `analytics/0002`), so a section can exist before an administrator assigns a faculty member. This keeps FR-007 (create section) and FR-013 (assign faculty) separate. Nothing in `analytics` reads `Section.faculty`.

**Why:** A second copy of these tables would split enrollment data between two apps. Moving the models into `academic` is possible later, as a migration agreed with the analytics owner.

**Introduced in:** `feature/fr-006-course-management` (reuse) and `feature/fr-007-section-management` (nullable faculty).

## Attendance recording (Role 2 — Arundhati K)

### D-06: Attendance sessions are linked to a timetable period (FR-014)

**Documents:** SRS Appendix B.1 lists AttendanceSession fields as `id, section_id, date, status, created_at, closed_at`. FR-014 says faculty start a session "for a scheduled section period".

**Implementation:** `analytics.AttendanceSession` gains a nullable `timetable_slot` link to `academic.Timetable`, plus a unique constraint on (period, date). `POST /api/attendance/sessions/start` takes `{timetable_slot_id, date}`, and `date` defaults to today. The date must fall on the period's weekday. Starting a second session for the same period and date returns 409. Only the section's assigned faculty member can start it.

**Why:** Without a link to the period, "scheduled section period" can't be checked, and one class could be recorded twice on the same day. The link is nullable, so sessions created before this change, and the existing tests that create them directly, still work.

**Introduced in:** `feature/fr-014-start-session`.
