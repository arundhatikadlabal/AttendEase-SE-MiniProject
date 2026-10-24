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
