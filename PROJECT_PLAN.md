# Project Plan — Grace House School System

## Overview

This plan covers the next development phase focused on four functional improvements
derived from operational gaps identified during the SUMMER SCHOOL 2026 data analysis
and UI/UX review of the existing admin and student portals.

---

## 1. Name Field Update — Middle Name Parity

### Problem
The generic user creation/edit form (`school_admin/user_form.html`) only captures
`first_name` and `last_name`. The student registration form already supports
`middle_name`, and the `User` model already has the field, but the generic user
management flow does not.

### Changes

| File | Change |
|------|--------|
| `accounts/models.py` | No change — `middle_name` already exists |
| `school_admin/templates/school_admin/user_form.html` | Add `Middle Name` input between first and last name |
| `school_admin/views/users.py` | `UserCreateView.post()`: read `middle_name` and pass to `create_user()` |
| `school_admin/views/users.py` | `UserEditView.post()`: read/write `middle_name` |
| `school_admin/views/users.py` | `UserListView.get()`: include `middle_name` in `Q` search |
| `school_admin/templates/school_admin/user_list.html` | Display middle name where present |

### Acceptance Criteria
- Admin can set a middle name when creating any user role
- Admin can edit the middle name later
- Middle name appears in user listings and full-name displays
- `get_full_name()` continues to omit blank middle names

---

## 2. Phone Number Input UI — Dynamic "Add Number"

### Problem
`User.phone_number` and `LessonEnrollment.parent_phone` are single `CharField`s.
The SUMMER SCHOOL 2026 spreadsheet contains parents with multiple contact numbers.
The student registration form already uses a dynamic "Add another guardian" pattern,
but within a single guardian entry only one phone number is supported.

### Changes

| File | Change |
|------|--------|
| `accounts/models.py` | Add `other_phones = models.JSONField(default=list, blank=True)` for extra numbers |
| `students/models.py` | Add `other_phones = models.JSONField(default=list, blank=True)` to `StudentGuardianLink` |
| `lessons/models.py` | Replace `parent_phone` with `parent_phones = models.JSONField(default=list, blank=True)` |
| `school_admin/templates/school_admin/user_form.html` | Render primary phone + dynamic "Add Number" button that appends an input |
| `school_admin/views/users.py` | Parse repeated `phone_number_extra[]` fields into `other_phones` list on save |
| `lessons/templates/lessons/admin/enrollment_form.html` | Replace static `parent_phone` with dynamic list input |
| `lessons/views.py` | `EnrollmentFormView.post()`: parse list of phones into `parent_phones` |
| `lessons/templates/lessons/admin/enrollment_list.html` | Render comma-separated phone list |
| `lessons/templates/lessons/admin/enrollment_detail.html` | Render comma-separated phone list |
| `lessons/templates/lessons/admin/enrollment_print.html` | Render comma-separated phone list |
| `lessons/templates/lessons/teacher/class_detail.html` | Render comma-separated phone list |
| `lessons/export` | Export `parent_phones` as joined string |

### UI Pattern
```
[ Primary phone (required) ]
[ + Add Number ]  <-- button
[ Extra phone 1 ] [ x ]
[ Extra phone 2 ] [ x ]
```

### Acceptance Criteria
- One required primary phone field is always visible
- "Add Number" button appends a removable extra phone input
- All extra numbers are stored as a JSON list
- Lists render as comma-separated values in read-only views
- Export includes all numbers

---

## 3. Flexible Fee Structure — Default + Class-Specific Pricing

### Problem
`LessonClass.fee_amount` is a fixed per-class fee. There is no concept of a
default/period-level fee that individual classes can override.

### Changes

| File | Change |
|------|--------|
| `lessons/models.py` | Add `default_fee_amount = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))` to `LessonPeriod` |
| `lessons/models.py` | Make `LessonClass.fee_amount` nullable (`null=True, blank=True`); null means "use period default" |
| `lessons/models.py` | Update `LessonEnrollment.fee_amount` property to resolve: `lesson_class.fee_amount or lesson_class.period.default_fee_amount` |
| `lessons/templates/lessons/admin/class_form.html` | Show period default fee; indicate when class fee overrides it |
| `lessons/templates/lessons/admin/enrollment_form.html` | Show resolved fee (read-only) next to class selector |
| `lessons/templates/lessons/admin/enrollment_detail.html` | Show resolved fee |
| `lessons/tests.py` | Add tests for fee resolution: class override, period fallback, both null |

### Fee Resolution Logic
```
resolved_fee = (
    lesson_class.fee_amount
    if lesson_class.fee_amount is not None
    else lesson_class.period.default_fee_amount
)
```

### Acceptance Criteria
- Admin sets a default fee at the period level
- Individual classes can override with their own fee or inherit the default
- Enrollment shows the resolved fee at registration and in all read views
- Existing `LessonClass` records without explicit fees inherit the period default

---

## 4. Class Data Integration — Reuse Existing SchoolClass

### Problem
`LessonClass` requires manual creation of a redundant set of class names (e.g.,
"JSS1 Revision", "Mathematics Booster") instead of linking to the school's
existing `students.SchoolClass` records.

### Changes

| File | Change |
|------|--------|
| `lessons/models.py` | Add `school_class = models.ForeignKey('students.SchoolClass', on_delete=models.SET_NULL, null=True, blank=True, related_name='lesson_classes')` to `LessonClass` |
| `lessons/migrations/` | New migration for the FK |
| `lessons/templates/lessons/admin/class_form.html` | Add optional "Link to school class" dropdown |
| `lessons/templates/lessons/admin/class_list.html` | Show linked school class name |
| `lessons/templates/lessons/admin/enrollment_form.html` | When a linked school class exists, display it as a hint |
| `lessons/views.py` | No change to core logic; FK is optional |
| `lessons/tests.py` | Add test for school-class-linked LessonClass |

### Backward Compatibility
- `school_class` is nullable
- Existing `LessonClass` records without a link continue to work unchanged
- The `name` field on `LessonClass` remains the display name (e.g., "JSS1 Revision")

### Acceptance Criteria
- Admin can optionally link a LessonClass to an existing SchoolClass
- Linked classes show the school class name in lists and forms
- Unlinked classes continue to work exactly as before

---

## Implementation Order

1. **Phase 1 — Models & Migrations** (foundation for all other work)
   - Middle name parity: view/template only, no migration
   - Phone numbers: JSONField additions + migrations
   - Fee structure: `LessonPeriod.default_fee_amount` + nullable `LessonClass.fee_amount` + migration
   - Class integration: `LessonClass.school_class` FK + migration

2. **Phase 2 — View Logic**
   - User views: middle name + phone list parsing
   - Lesson views: fee resolution + phone list parsing

3. **Phase 3 — Templates & UI**
   - User form: middle name + dynamic phones
   - Lesson class form: school class link + default fee display
   - Lesson enrollment form: dynamic phones + resolved fee display
   - All read-only templates: updated phone and fee rendering

4. **Phase 4 — Tests & Polish**
   - Update existing tests for changed fields
   - Add new tests for fee resolution and class linking
   - Run full test suite: `python manage.py test`

---

## Migration Notes

- `User.middle_name`: already exists, no migration needed
- `User.other_phones`: new JSONField, default `[]`
- `StudentGuardianLink.other_phones`: new JSONField, default `[]`
- `LessonEnrollment.parent_phones`: new JSONField, replace `parent_phone`; data migration copies existing `parent_phone` into `parent_phones[0]`
- `LessonPeriod.default_fee_amount`: new DecimalField, default `0.00`
- `LessonClass.fee_amount`: alter to `null=True, blank=True`
- `LessonClass.school_class`: new nullable FK to `students.SchoolClass`

---

## Out of Scope

- Student/parent self-service portals for extra lessons (explicitly v1-excluded per CONTEXT.md)
- SMS/email notifications for lesson enrollments (IN_APP only)
- PostgreSQL RLS (future work per CONTEXT.md)
