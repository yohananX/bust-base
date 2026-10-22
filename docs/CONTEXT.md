# CONTEXT — School Management Platform (bust-base)

## Project overview

A multi-tenant school management platform (Django 6, SQLite dev / tenant-scoped models)
covering academics (scores, results, term results), fees (invoices, payments via Paystack,
bank transfers, receipts), finance, payroll, data import, and role-specific portals
(admin, teacher, parent, student). Notification delivery is synchronous in-process;
EMAIL/SMS are audit records, IN_APP rows power the bell.

## Glossary

| Term | Definition |
|---|---|
| Toast | Transient (~3s) in-session feedback, top-right. Surface for the **online** recipient and for the actor's own action confirmation. |
| Bell | Durable personal inbox (base.html, all roles). **Offline catch-up + action center.** Newest on top, scrollable box, per-row dismiss + Clear all. |
| Notification row | One `NotificationLog` row per recipient an event concerns. IN_APP QUEUED = unread, SENT = read; `dismissed=True` hides from bell (record kept for audit). |
| Badge | Unread count. Open = read, dismiss = gone. Login never toast-storms — only rows arriving after page load toast. |
| Actor | The user who performed the action. Gets toast feedback, **never** a bell row. |
| Recipient | Someone the event concerns who did NOT perform it. Gets a row (+toast if online). |
| Action item | A row that needs action (transfer request, failed payment). Carries deep link; toast may render an inline action button. |
| `notify_admins` | Only for action items/exceptions, never routine confirmations. |

## Core rule

> **Every event creates one durable row per recipient it concerns. That row toasts
> instantly if the recipient is online; otherwise it waits in the bell. The actor
> who performed the action gets the toast as feedback and no row.**

## Decisions (grill-me session, 2026-08-18)

1. Bell audience: admin, parents, students, staff — everyone gets the same system.
2. One row per recipient, always; toast if online (poll delta detects new arrivals).
3. Actor = toast only, no row.
4. Offline catch-up is the bell's core job; rows persist until read/dismissed.
5. Clear = per-row X + "Clear all"; rows are hidden (`dismissed`), never deleted.
6. Bell UI: newest on top, scrollable fixed-height box.
7. Links everywhere: toast AND row carry the same deep link; action items get an
   inline action button in the toast.
8. Badge: unread count; open = read; poll toasts only rows arriving after page load.
9. Scoping: parents see only their own children's events; teachers never see fees;
   staff get toasts + bell for payroll/moderation/term events; admin bell = action
   items + exceptions only.
10. EMAIL/SMS: unchanged — sync delivery, audit log only.

## Event → audience map

| Event | Recipients (row) | Actor (toast only) |
|---|---|---|
| Payment confirmed (webhook/verify) | Paying student + all its guardians | — |
| Payment failed | Student + guardians; admin (exception) | — |
| Receipt issued | Student + guardians | — |
| Transfer submitted | Admin (action item, deep link to pending transfers) | Student (messages toast) |
| Transfer confirmed/rejected | Student + guardians | Admin (messages toast) |
| Payment recorded by admin | Student + guardians | Admin (messages toast) |
| Results published | Per child: guardians (child-specific link) + the student | Admin (messages toast) |

## Key routes

- Student: `student-overview`, `student-result-booklet` (term_id)
- Parent: `parent-child-result-booklet` (child_pk, term_id), `parent-invoice-detail`,
  `parent-children`, `parent-child-detail`
- Admin: `school_admin:pending_transfers`, `school_admin:student_detail`,
  `school_admin:invoice_detail`, `school_admin:notification_log` (audit, all channels)
- Notifications: `/notifications/bell/count/`, `bell/dropdown/`, `bell/poll/?since=<pk>`,
  `bell/<pk>/dismiss/` (POST), `bell/clear-all/` (POST)

## Producer rules

- `notify(recipient, channel, subject, message, reference, url, action_label)`
- `notify_many(recipients=[...], ...)` — batch helper.
- References: `payment-confirm:{id}`, `payment-fail:{id}`, `receipt:{id}`,
  `transfer-pending:{student}:{ts}`, `transfer-confirm:{id}`, `transfer-reject:{id}`,
  `payment-record:{id}`, `term-results:{term}:g:{child}` / `:s:{child}` (per-recipient
  dedup by reference + recipient).
- EMAIL/SMS delivered synchronously in `notify()`; SENT on success, FAILED + error
  message on failure; None when recipient has no school.

## Active assumptions

- One admin per school; ~40 teachers/staff. `notify_admins` = that one admin.
- Teachers/staff will get bell notifications later (payroll, moderation, term events).
- Paystack webhooks may fire while the recipient is browsing → poll delivers the toast.

## Multi-tenancy

- Every business model inherits `TenantScopedModel` (school FK). Views scope by
  `school=request.school` (set by `SchoolMiddleware` from `user.school`).
- **Superusers (school=None):** `request.school` is `None`; `RoleRequiredMixin`
  rejects them from every tenant portal (role `''` never matches), so a superuser
  can never view tenant data. Cross-school work happens in the Django admin
  (`/secure-control-panel/`); school admins are redirected away from it.
- **No-user lookups:** when a queryset has no `school=` kwarg it must derive the
  tenant transitively (e.g. `filter(student=...)` where the student was already
  school-scoped, or `guardian=request.user`). New views must follow this rule;
  direct `pk` lookups without `school=` are a bug.
- **Paystack webhook** (`fees/paystack.py`) is the one intentional cross-tenant
  entry point — it resolves by reference and re-checks HMAC + idempotency.
- Portal-level leakage tests live in `tests/test_tenancy.py` (two schools × every
  portal + superuser behaviour). Keep them green when adding views.
- **PostgreSQL RLS is future work** (noted, not implemented); app-level scoping +
  the tenancy test suite is the accepted protection today.

## Remaining ambiguities

- Toast stacking limit (max 5 visible today).
- Exact action labels per event (labels live on the row: `action_label`).
- Staff event catalog (payroll/moderation) is future work.
- **Notification preferences (per-recipient channel opt-out: e.g. email-only or
  quiet hours for the bell) is explicitly deferred** — user said "later". All
  channels remain all-on until then.

## Extra Lessons / Summer School (lessons app, 2026-08-20)

- New Django app `lessons`. Admin-centric holiday-programme registration stream
  (paper "Summer School Registration Form" parity). Student and parent portals
  exist for viewing enrollments and making payments; teachers get a read-only
  roster of their assigned classes.
- **Models** (all `TenantScopedModel`): `LessonPeriod` (DRAFT/OPEN/CLOSED),
  `LessonClass` (per-period, fixed `fee_amount` editable anytime), 
  `LessonTeacherAssignment` (teacher = accounts.User, role TEACHER), and
  `LessonEnrollment` (REGISTERED/PAID/CANCELLED).
- **Enrollment** links an existing Student OR captures an external child
  (`external_name`, `age`, `current_class_text`). Parent/guardian, learning goals,
  referral/source, and consent fields mirror the paper form.
- **Payments** reuse `fees.Payment` via a new nullable `lesson_enrollment` FK
  (migration `fees.0008_payment_lesson_enrollment`); `issue_receipt` issues the
  standard `FeeReceipt`. `LessonEnrollment.payment_status` is PAID/PARTIAL/UNPAID
  from confirmed payments; recording full payment auto-marks the enrollment PAID.
- **Routes**: admin under `/school-admin/lessons/` (namespace `lessons`), teacher
  under `/teacher/lessons/` (namespace `lessons_teacher`). Sidebar: "Extra Lessons"
  (admin, Academics section) and "My Extra Classes" (teacher).
- **CSV export** (`enrollments/export/`) honours the same period/status filters.
- **Notification**: payment recorded for a linked student sends an IN_APP row
  (`lesson-payment:{id}`) to the student only (no email unless explicit); fee
  receipts reuse the existing receipt flow.
- **Test**: `lessons/tests.py` (22 tests: model, admin CRUD, enrollment, payment,
  CSV, teacher scoping). Run `python manage.py test lessons`.

## Fee Payment Redesign — Apply Payment Screen (in progress)

### Problem
The "Apply Payment to" panel in the admin's `StudentRecordPaymentView` (and the
parent/student payment flows) shows a flat checkbox list of every applicable fee
for the current term. For a NEW JSS1 student that is 7–8 items totalling NGN
78,500 (or 80,000 once the `School Fees` category is collapsed into `Tuition
Fee`). The list is hard to scan, requires manual selection, and the NEW vs
RETURNING distinction is invisible to the admin.

### Decisions reached (grill-me session 2026-09-02)

1. **Collapse duplicate "School Fees" categories into `Tuition Fee`.** Tuition
   is the canonical per-term class fee; the per-class "X School Fees" rows are
   deleted. The resolver and seed command produce only one Tuition row per
   (class, term).

2. **NEW student onboarding total = NGN 80,000** for JSS1, made up of:

   | Category | Cycle | Type | Amount |
   |---|---|---|---:|
   | Tuition Fee | PER_TERM | ALL | 33,000 |
   | Registration Form | ONE_TIME | NEW | 2,000 |
   | Uniforms | ONE_TIME | NEW | 40,000 |
   | PTA | ONE_TIME | NEW | 1,000 |
   | File Jacket | ONE_TIME | NEW | 500 |
   | Maintenance | ONE_TIME | NEW | 1,000 |
   | Examination Fee | ONE_TIME | NEW | 2,500 |
   | **Total — Full Package** | pseudo-row | NEW | **80,000** |

   (Christmas/End of Term Party Fee is **not** in the package; see §4 below.)

3. **NEW vs RETURNING auto-flip rule.** When a NEW student records a payment
   that includes the Registration Form line item, their `student_type` is set
   to RETURNING **for subsequent terms only**. The current-term view still
   treats them as NEW (so the package total still shows). Concretely: the
   `student_type` field on `Student` is updated to RETURNING at the moment the
   Registration Form line is marked paid, but a per-term override caches the
   "still NEW for this term" state until term rollover. (Implementation: store
   `registration_paid_term` on the Student; the view-time check is
   `student.registration_paid_term == current_term → still NEW`.)

4. **Christmas/End of Term Party Fee** is treated as **per-session** (charged
   once per academic session, in the first term only). For NEW students the
   default Apply-Payment view shows it unchecked; for RETURNING students it is
   hidden unless the current term is the first term of the current session.
   Admin can always add it via the "Add manual fee" line.

5. **One-time fees do NOT auto-reset between academic sessions.** Once paid,
   the student is marked as having paid that onboarding fee for life. The
   `one-time guard` in `fees.generation` continues to skip rebilling.

6. **Uniforms remains selectable for returning students** (a returning pupil
   may need a replacement uniform). It is not in the default RETURNING
   auto-selection set but is always visible in the Apply-Payment list.

### Apply-Payment UI redesign (specification)

- **Above the list**: a New / Returning toggle (default = `student.student_type`
  but overridable for the current payment). Toggling re-renders the list.
- **Above the list**: a single summary checkbox
  `Total — Full Package (NGN 80,000)`. When NEW is selected, this is auto-ticked
  on load and ticking/unticking it checks/unchecks all 7 onboarding items. When
  RETURNING is selected, the pseudo-row is hidden.
- **Item states**:
  - **Checked by default (NEW)**: Tuition, Registration, Uniforms, PTA, File
    Jacket, Maintenance, Examination. Total pseudo-row reflects "all 7".
  - **Checked by default (RETURNING)**: Tuition only.
  - **Hidden (RETURNING)**: Registration, PTA, File Jacket, Maintenance,
    Examination. (These are one-time + already paid.)
  - **Visible but unchecked (both)**: Christmas/End of Term Party Fee (only
    when first term of session).
  - **Always visible, unchecked (RETURNING)**: Uniforms (admin adds manually
    if needed).
  - **Disabled (greyed)**: any item the student has already paid for in full
    across all sessions (e.g. PTA if paid last year). The view computes
    "paid" from `InvoiceLineItem` + `PaymentLineItem` history, scoped to
    category.

- **Save behaviour**: the form posts `selected_line_items` (a list of
  `FeePrice` IDs). The view creates one `InvoiceLineItem` per selected fee
  and one `Payment` linking them. If the Total pseudo-row was checked, the
  seven underlying items are recorded (the pseudo-row itself is not stored).

### Data model changes

- **`Student`**: add `registration_paid_term` (nullable FK to `Term`).
  When a Registration Form line is recorded as paid, set
  `student.registration_paid_term = invoice.term`.
- **`FeeCategory`**: delete all "X School Fees" categories (one per class) via
  data migration. Update `seed_fee_structure.py` to no longer create them.
- **No change to `FeePrice` model.**

### Files affected

| File | Change |
|---|---|
| `students/models.py` | add `registration_paid_term` FK on `Student` |
| `fees/views.py` (`student_line_items_api`) | NEW/RETURNING aware; emit list with `disabled`, `default_checked`, `hidden` flags; include Total pseudo-row for NEW |
| `fees/templates/fees/partials/student_line_items_breakdown.html` | render New/Returning toggle, Total pseudo-checkbox, hide/grey logic |
| `fees/checkout.py` | align checkout with NEW/RETURNING classification for parent/student flows |
| `school_admin/views/fees.py` (`StudentRecordPaymentView`) | after recording a Registration Form payment, set `student.registration_paid_term` and flip `student_type` to RETURNING |
| `fees/generation.py` | collapse duplicate School Fees during resolve (or via `FeePrice.objects.exclude(category__name__endswith='School Fees')` filter) |
| `fees/management/commands/seed_fee_structure.py` | remove "X School Fees" rows; keep Tuition per-class |
| `fees/migrations/00XX_*.py` | `registration_paid_term` column; data migration to delete School Fees categories and orphan FeePrice rows |
| `fees/test_payment_recording.py` | add tests: NEW shows 7 + Total; RETURNING shows Tuition + Uniforms; Total unchecking unchecks children; disabled already-paid items |

### Out of scope (this iteration)

- Parent portal UX beyond plumbing (toggle/pseudo-row render in parent
  `fee_breakdown` partial too, but visual polish in a follow-up).
- Bulk "promote all NEW students who paid Registration" admin action
  (single-student auto-flip is enough for now).
- Historical invoice/payment backfill (only the new model applies
  going forward).

### Test plan

1. `fees/test_pricing.py` — resolver no longer returns School Fees rows.
2. `fees/test_payment_recording.py` — NEW student view: 8 rows (7 items +
   pseudo), 7 default-checked, sum = 80,000.
3. `fees/test_payment_recording.py` — RETURNING student view: 2 rows
   (Tuition + Uniforms), Tuition default-checked, Uniforms unchecked.
4. `fees/test_payment_recording.py` — recording a payment with Registration
   Form line flips `student.registration_paid_term` and `student_type`.
5. `fees/test_payment_recording.py` — Total pseudo-row click selects all 7.
6. Migration test: deleting School Fees categories leaves Tuition intact,
   resolver still works.
