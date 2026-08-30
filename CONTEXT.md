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
