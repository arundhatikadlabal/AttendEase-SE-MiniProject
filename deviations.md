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

### D-07: "Today" for future-date checks uses the server time zone, UTC (NFR-004)

**Documents:** NFR-004 says the system shall prevent attendance being recorded for future dates. It doesn't say whose "today" applies.

**Implementation:** Starting a session with a date after today returns 400, and so does submitting records for a session dated after today. A missing `date` defaults to today. "Today" comes from Django's `timezone.localdate()`, so it follows `TIME_ZONE` in `config/settings.py`, which is currently `UTC`.

**Why it matters:** From 00:00 to 05:30 IST the UTC date is still the previous day, so a session dated "today" in India would count as future during those hours. Classes don't run then, so this doesn't affect normal use. Setting `TIME_ZONE = "Asia/Kolkata"` would remove the gap, but that is a project-wide setting, so it is left for a team decision.

**Introduced in:** `feature/nfr-004-no-future-dates`.

### D-08: Per-student marks can be changed while a session is open (FR-016)

**Documents:** FR-016 says faculty mark each student present or absent. SAD §5 describes the marking screen as a roster with a per-student toggle. FR-037 (Role 3) prevents duplicate records.

**Implementation:** `PUT /api/attendance/sessions/{id}/records/{student_id}` with `{"status": "present"|"absent"}` creates the student's record, or changes it if it already exists, while the session is open. It still never creates a second record for the same student and session, so FR-037 holds. Once the session is closed (FR-018), marks can only change through Role 3's edit-window and correction flows (FR-038, FR-027). The FR-037 batch endpoint `POST .../records` is unchanged: it still refuses to overwrite existing records.

**Why:** A toggle that couldn't be undone would make a mis-click permanent before the session is even closed.

**Introduced in:** `feature/fr-016-mark-student`.

### D-09: Performance is measured in the automated test suite (NFR-001, NFR-002 / TC-11)

**Documents:** NFR-001 requires that 95% of API requests complete within 2 seconds with up to 50 concurrent users. NFR-002 requires the roster to load within 3 seconds for a section of up to 80 students. TC-11 says to simulate 50 concurrent users loading the roster for an 80-student section.

**Implementation:** `attendance/test_performance.py` runs on every CI build:
- **NFR-002:** with a real JWT login, the 80-student roster and "mark all present" each finish within 3 seconds. The roster also uses a fixed number of database queries (3) whatever the class size.
- **TC-11 / NFR-001:** 50 threads request the 80-student roster at the same time, and the 95th-percentile response time must be under 2 seconds. A second run mixes five read endpoints under the same load. A local run measured a median of 0.21 s and a 95th percentile of 0.37 s.

**Difference from a production load test:** these tests call the app in-process against the SQLite test database. They don't go over a network to the PostgreSQL deployment from `docker-compose`, so they guard against regressions rather than certify production capacity. A load test against the deployed stack, for example with Locust, would be the full TC-11 measurement if evaluators require it.

**Introduced in:** `feature/nfr-002-roster-performance` and `feature/nfr-001-concurrent-load`.


## Attendance corrections (Role 3 — Anshdeep Singh Sachdeva)

### D-10: Direct attendance edits default to 24 hours after closure (FR-038)

**Documents:** FR-038 requires a configurable edit window after session closure. SAD §4.6 leaves its duration and whether it is per-course undecided.

**Implementation:** `ATTENDANCE_EDIT_WINDOW_SECONDS` is a deployment-wide environment setting, defaulting to 86400 seconds (24 hours); zero disables direct edits. The assigned active faculty member may `PATCH /api/attendance/sessions/{id}/records/{student_id}` with `{"status": "present"|"absent"}` to update an existing record. Edits are allowed from `closed_at` up to, but excluding, `closed_at + window`. Missing or future closure timestamps are rejected instead of guessing a deadline. An edit never reopens the session or changes `closed_at`. The open-session `PUT` and duplicate-protected batch `POST` retain their existing behavior.

**Why:** A configurable deployment default supports a working demo without adding a per-course policy or an administration interface not defined in the documents. Legacy closed sessions without a closure timestamp cannot safely establish eligibility. Approval of a student correction remains the separate FR-027 workflow.

**Introduced in:** `feature/fr-038-attendance-edit-window`.
