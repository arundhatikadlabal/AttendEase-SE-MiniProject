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
