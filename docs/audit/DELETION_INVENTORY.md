# Deletion-Path Inventory (R-07)

**Version:** 1.0.0
**Date:** 2026-10-23
**Repository state:** branch `main`, HEAD `8a1bdcc`, working tree dirty. `AcademicStage` and its migration exist only as uncommitted/untracked work and are included where relevant.

## 0. Scope and evidence legend

This inventory covers academic records, students, staff, fee configuration,
invoices, payments, receipts, allocations, and directly related rows. It
records **model-level deletion policies** (`on_delete`) and **application-level
deletion entry points** (views, admin actions, management commands, services).

| Tag | Meaning |
|---|---|
| **[V]** | Verified by reading the model field, view, command, or service in the working tree. |
| **[A]** | Assumption based on Django behaviour or on the code's intent; not executed. |
| **[U]** | Untested database behaviour. No delete was executed during this readiness batch. |

**No deletion was performed in this batch.** All cascade statements are static
traces of `on_delete` declarations and Django's documented collector behaviour.
They are not runtime observations. Raw SQL deletes that bypass the ORM are not
covered by these traces.

## 1. Critical findings

1. **[V] `Payment.recorded_by` is `CASCADE`, not `SET_NULL`.**
   `fees/models.py:460-466`. Deleting a staff user deletes every payment that
   user recorded. The earlier `FINAL_GO_NOGO_CORRECTIONS.md` graph claims
   `SET_NULL`; that claim is wrong for the working tree.
2. **[V] `Score.entered_by` is `CASCADE`, not `SET_NULL`.**
   `academics/models.py:196-201`. Deleting a teacher deletes scores they
   entered, not merely the attribution.
3. **[V] `InvoiceLineItem.category` is `CASCADE`.**
   `fees/models.py:337-341`. Deleting a fee category can destroy historical
   invoice lines and break invoice-total reconciliation.
4. **[V] `FeeCategoryDeleteView` guards only on `FeePrice`.**
   `school_admin/views/fee_categories.py:89-95`. A category with historical
   line items but no current price can be deleted, cascading those lines.
5. **[V] Student delete is exposed and cascades financial/academic history.**
   `school_admin/views/students.py:472-507`; `Student` is a `TenantScopedModel`
   and the child FKs are `CASCADE`.
6. **[V] Payment delete is exposed without a replacement/reversal record.**
   `school_admin/views/invoices.py:493-507`. It deletes the payment and its
   receipt. `AuditLog` logs the `Payment` delete, but no compensating financial
   record is created.
7. **[V] Staff delete is superadmin-only but still hard-deletes a `User`.**
   `school_admin/views/staff.py:198-258`. The `User` delete cascades payroll,
   teaching assignments, entered scores, recorded payments, inventory rows, and
   notifications.
8. **[V] Admin site exposes default delete for registered models.**
   No `has_delete_permission` override was found. `core/admin.py` registers
   `School`, `AcademicSession`, and `Term`; `fees/admin.py` registers fee
   configuration and invoices. Superusers can therefore delete root records
   through Django admin. **[A]** Django's default delete permission applies.
9. **[V] Destructive utilities exist in-tree.**
   `fees/reset.py`, `fees/management/commands/clear_student_payment_history.py`,
   and `core/management/commands/clear_student_data.py` issue bulk deletes.
   `clear_student_payment_history` has no dry-run or confirmation flag.
10. **[V] `sync_class_invoices` deletes and rewrites line items on unpaid
    invoices.** `fees/generation.py:157-202`. This is an application-level
    historical rewrite, not a deletion of the invoice itself.

## 2. Model-level deletion policies

### 2.1 Tenant root and academic structure

| Parent | Child field | Policy | Verified location |
|---|---|---|---|
| `School` | every `TenantScopedModel.school` | `CASCADE` | `core/models.py:16-25` |
| `School` | `User.school` | `CASCADE` | `accounts/models.py:39-45` |
| `AcademicSession` | `Term.session` | `CASCADE` | `core/models.py:117-123` |
| `AcademicStage` | `SchoolClass.academic_stage` | **`PROTECT`** | `students/models.py:44-52` |
| `Term` | `FeePrice.term` | `CASCADE` | `fees/models.py:86-92` |
| `Term` | `Score.term` | `CASCADE` | `academics/models.py:159-164` |
| `Term` | `TermResult.term` | `CASCADE` | `academics/models.py:328-331` |
| `Term` | `Invoice.term` | `CASCADE` | `fees/models.py:265-268` |

**Consequence [A].** Deleting an `AcademicSession` cascades its `Term` rows,
which in turn cascade scores, term results, invoices, and term-scoped fee
prices. Deleting `School` cascades every tenant-scoped row, including users.
`AcademicStage` is protected only from deletion while a `SchoolClass` points to
it; it does not protect classes from deletion.

### 2.2 Students, guardians, enrollment

| Parent | Child field | Policy | Verified location |
|---|---|---|---|
| `User` | `Student.user` | `CASCADE` | `students/models.py:91-96` |
| `Term` | `Student.registration_paid_term` | `SET_NULL` | `students/models.py:127-135` |
| `Student` | `ClassEnrollment.student` | `CASCADE` | `students/models.py:220-224` |
| `SchoolClass` | `ClassEnrollment.school_class` | `CASCADE` | `students/models.py:226-230` |
| `AcademicSession` | `ClassEnrollment.session` | `CASCADE` | `students/models.py:232-236` |
| `Student` | `StudentGuardianLink.student` | `CASCADE` | `students/models.py:271-275` |
| `User` (guardian) | `StudentGuardianLink.guardian` | `CASCADE` | `students/models.py:277-282` |

**Consequence [A].** `Student.delete()` removes enrollments and guardian links,
but does **not** delete the linked `User`, because the cascade direction is
`Student.user -> User` (deleting the user deletes the student). Deleting a
student's `User` first deletes the student profile and then all student-owned
financial/academic records. This is the broadest student path.

### 2.3 Academic records

| Parent | Child field | Policy | Verified location |
|---|---|---|---|
| `SchoolClass` | `ClassSubject.school_class` | `CASCADE` | `academics/models.py:43-47` |
| `Subject` | `ClassSubject.subject` | `CASCADE` | `academics/models.py:49-53` |
| `User` (teacher) | `TeacherAssignment.teacher` | `CASCADE` | `academics/models.py:80-85` |
| `Subject` | `TeacherAssignment.subject` | `CASCADE` | `academics/models.py:87-91` |
| `SchoolClass` | `TeacherAssignment.school_class` | `CASCADE` | `academics/models.py:93-97` |
| `AcademicSession` | `TeacherAssignment.session` | `CASCADE` | `academics/models.py:99-103` |
| `Student` | `Score.student` | `CASCADE` | `academics/models.py:147-151` |
| `Subject` | `Score.subject` | `CASCADE` | `academics/models.py:153-157` |
| `Term` | `Score.term` | `CASCADE` | `academics/models.py:159-164` |
| `User` | `Score.entered_by` | **`CASCADE`** | `academics/models.py:196-201` |
| `User` | `Score.moderated_by` | `SET_NULL` | `academics/models.py:219-224` |
| `Student` | `TermResult.student` | `CASCADE` | `academics/models.py:324-327` |
| `Term` | `TermResult.term` | `CASCADE` | `academics/models.py:328-331` |

### 2.4 Fee configuration

| Parent | Child field | Policy | Verified location |
|---|---|---|---|
| `FeeCategory` | `FeePrice.category` | `CASCADE` | `fees/models.py:66-70` |
| `Term` | `FeePrice.term` | `CASCADE` | `fees/models.py:86-92` |
| `SchoolClass` | `FeePrice.school_class` | `CASCADE` | `fees/models.py:107-112` |
| `Student` | `FeePriceOverride.student` | `CASCADE` | `fees/models.py:197-201` |
| `FeeCategory` | `FeePriceOverride.category` | `CASCADE` | `fees/models.py:203-207` |
| `FeeCategory` | `FeeCategoryInventoryItem.fee_category` | `CASCADE` | `inventory/models.py:62-66` |

Deleting a `FeeCategory` therefore removes its prices, overrides, inventory
links, and (through the separate `InvoiceLineItem.category` FK) historical line
items. `PaymentLineItem.category` is `SET_NULL`, so allocations survive but lose
their category link.

### 2.5 Invoices, payments, receipts, allocations

| Parent | Child field | Policy | Verified location |
|---|---|---|---|
| `Student` | `Invoice.student` | `CASCADE` | `fees/models.py:259-263` |
| `Term` | `Invoice.term` | `CASCADE` | `fees/models.py:265-268` |
| `School` | `InvoiceLineItem.school` (nullable) | `CASCADE` | `fees/models.py:324-329` |
| `Invoice` | `InvoiceLineItem.invoice` | `CASCADE` | `fees/models.py:331-335` |
| `FeeCategory` | `InvoiceLineItem.category` | **`CASCADE`** | `fees/models.py:337-341` |
| `Term` | `InvoiceLineItem.term` | `CASCADE` | `fees/models.py:357-362` |
| `AcademicSession` | `InvoiceLineItem.session` | `CASCADE` | `fees/models.py:364-369` |
| `Invoice` | `Payment.invoice` | `CASCADE` | `fees/models.py:412-418` |
| `Student` | `Payment.student` | `CASCADE` | `fees/models.py:420-426` |
| `LessonEnrollment` | `Payment.lesson_enrollment` | `SET_NULL` | `fees/models.py:428-434` |
| `User` | `Payment.recorded_by` | **`CASCADE`** | `fees/models.py:460-466` |
| `User` | `Payment.confirmed_by` | `SET_NULL` | `fees/models.py:496-502` |
| `Payment` | `FeeReceipt.payment` (OneToOne) | `CASCADE` | `fees/models.py:567-572` |
| `Payment` | `PaymentLineItem.payment` | `CASCADE` | `fees/models.py:661-665` |
| `School` | `PaymentLineItem.school` (nullable) | `CASCADE` | `fees/models.py:667-672` |
| `FeeCategory` | `PaymentLineItem.category` | `SET_NULL` | `fees/models.py:678-683` |
| `Term` | `PaymentLineItem.term` | `SET_NULL` | `fees/models.py:685-690` |
| `AcademicSession` | `PaymentLineItem.session` | `SET_NULL` | `fees/models.py:692-697` |
| `Invoice` | `PaymentLineItem.invoice` | `SET_NULL` | `fees/models.py:699-704` |
| `User` | `InvoiceResetLog.reset_by` | `SET_NULL` | `fees/models.py:595-600` |
| `User` | `FeeValidationError.resolved_by` | `SET_NULL` | `fees/models.py:633-638` |

### 2.6 Payroll

| Parent | Child field | Policy | Verified location |
|---|---|---|---|
| `User` | `StaffProfile.user` | `CASCADE` | `payroll/models.py:34-39` |
| `PayGrade` | `StaffProfile.pay_grade` | `SET_NULL` | `payroll/models.py:63-69` |
| `PayGrade` | `AllowanceDefinition.pay_grade` | `CASCADE` | `payroll/models.py:129-135` |
| `StaffProfile` | `AllowanceDefinition.target_staff` | `CASCADE` | `payroll/models.py:137-142` |
| `PayGrade` | `DeductionDefinition.pay_grade` | `CASCADE` | `payroll/models.py:179-185` |
| `StaffProfile` | `DeductionDefinition.target_staff` | `CASCADE` | `payroll/models.py:187-192` |
| `User` | `PayrollRun.generated_by` | `CASCADE` | `payroll/models.py:230-235` |
| `StaffProfile` | `Payslip.staff` | `CASCADE` | `payroll/models.py:281-286` |
| `PayrollRun` | `Payslip.payroll_run` | `CASCADE` | `payroll/models.py:287-292` |
| `Payslip` | `PayslipLineItem.payslip` | `CASCADE` | `payroll/models.py:362-366` |
| `Payslip` | `SalaryDisbursement.payslip` | `CASCADE` | `payroll/models.py:405-410` |
| `User` | `SalaryDisbursement.recorded_by` | `CASCADE` | `payroll/models.py:432-437` |

### 2.7 Finance (protective contrast)

| Parent | Child field | Policy | Verified location |
|---|---|---|---|
| `User` | `Project.created_by` | **`PROTECT`** | `finance/models.py:41-45` |
| `Project` | `Expenditure.project` | `SET_NULL` | `finance/models.py:88-92` |
| `ExpenditureCategory` | `Expenditure.category` | **`PROTECT`** | `finance/models.py:96-100` |
| `User` | `Expenditure.recorded_by` | **`PROTECT`** | `finance/models.py:112-116` |

Finance is the only area that already prevents deleting a user/category that
has history. It is a useful reference for the required fee/student/staff fixes.

### 2.8 Lessons and notifications

| Parent | Child field | Policy | Verified location |
|---|---|---|---|
| `LessonPeriod` | `LessonClass.period` | `CASCADE` | `lessons/models.py:59-64` |
| `SchoolClass` | `LessonClass.school_class` | `SET_NULL` | `lessons/models.py:80-86` |
| `LessonClass` | `LessonTeacherAssignment.lesson_class` | `CASCADE` | `lessons/models.py:116-120` |
| `User` | `LessonTeacherAssignment.teacher` | `CASCADE` | `lessons/models.py:122-127` |
| `LessonClass` | `LessonEnrollment.lesson_class` | `CASCADE` | `lessons/models.py:164-169` |
| `Student` | `LessonEnrollment.student` | `SET_NULL` | `lessons/models.py:172-178` |
| `User` | `NotificationLog.recipient` | `CASCADE` | `notifications/models.py:20-24` |

## 3. Cascade traces

### 3.1 `Student.delete()` [V/A]

```
Student
├── ClassEnrollment                     CASCADE
├── StudentGuardianLink                 CASCADE
├── Invoice                             CASCADE
│   ├── InvoiceLineItem                 CASCADE
│   ├── Payment                         CASCADE
│   │   ├── FeeReceipt                  CASCADE
│   │   └── PaymentLineItem             CASCADE
│   └── PaymentLineItem.invoice         SET_NULL (survives if payment survives)
├── Payment (student FK)                CASCADE
│   ├── FeeReceipt                      CASCADE
│   └── PaymentLineItem                 CASCADE
├── FeePriceOverride                    CASCADE
├── Score                               CASCADE
├── TermResult                          CASCADE
├── LessonEnrollment.student            SET_NULL
└── registration_paid_term              not affected (FK is on Student)
```

The linked `User` is **not** deleted by `Student.delete()` [V]. The user,
guardian links to other users, notifications, and any `Payment.student=None`
rows remain. `AuditLog` has no `Student` watcher, so the student deletion itself
is not audited [V].

### 3.2 `User.delete()` (staff or parent/student account) [V/A]

```
User
├── Student.user                        CASCADE -> trace 3.1
├── StaffProfile                        CASCADE
│   ├── Payslip                         CASCADE
│   │   ├── PayslipLineItem             CASCADE
│   │   └── SalaryDisbursement           CASCADE
│   ├── AllowanceDefinition             CASCADE
│   └── DeductionDefinition             CASCADE
├── TeacherAssignment                   CASCADE
├── Score.entered_by                    CASCADE
├── Payment.recorded_by                 CASCADE
├── PayrollRun.generated_by             CASCADE -> Payslip CASCADE
├── SalaryDisbursement.recorded_by      CASCADE
├── LessonTeacherAssignment             CASCADE
├── InventoryProcurement.purchased_by   CASCADE
├── InventoryTransaction.created_by     CASCADE
├── NotificationLog.recipient           CASCADE
├── StudentGuardianLink.guardian        CASCADE
├── Score.moderated_by                  SET_NULL
├── Payment.confirmed_by                SET_NULL
├── AuditLog.actor                      SET_NULL
├── InvoiceResetLog.reset_by            SET_NULL
├── FeeValidationError.resolved_by      SET_NULL
└── Finance FKs                         PROTECT (may block the delete)
```

This is the highest-impact staff path. `StaffDeleteView` warns about only five
related counts (teacher assignments, scores entered, notifications, procurement,
inventory transactions) and does not mention recorded payments, payroll runs,
payslips, disbursements, or the `PROTECT` finance rows that can block the
transaction [V].

### 3.3 `FeeCategory.delete()` [V/A]

```
FeeCategory
├── FeePrice                            CASCADE
├── FeePriceOverride                    CASCADE
├── InvoiceLineItem.category            CASCADE  <-- historical financial data
├── PaymentLineItem.category            SET_NULL (allocation survives, link lost)
├── FeeCategoryInventoryItem            CASCADE
└── inventory links                     CASCADE
```

The view blocks only if `FeePrice.objects.filter(category=category).exists()`
[V]. It does not block on `InvoiceLineItem`, `FeePriceOverride`,
`PaymentLineItem`, or inventory links.

### 3.4 `Invoice.delete()` [V/A]

```
Invoice
├── InvoiceLineItem                     CASCADE
├── Payment                             CASCADE
│   ├── FeeReceipt                      CASCADE
│   └── PaymentLineItem                 CASCADE
└── PaymentLineItem.invoice             SET_NULL (only for other payments)
```

`NotificationLog` uses string references such as `receipt:{payment_id}`, not a
FK, so notifications are not deleted automatically [V]. `AuditLog` logs the
`Invoice` and each `Payment` delete because both are watched [V]; it does not
log `InvoiceLineItem` or `FeeReceipt` deletes [V].

### 3.5 `Payment.delete()` [V/A]

```
Payment
├── FeeReceipt                          CASCADE
└── PaymentLineItem                     CASCADE
```

The invoice remains with its original `total_amount`; its computed balance
increases. `AuditLog` writes a DELETE snapshot for the payment [V]. No
reversal/credit record is created [V].

### 3.6 `SchoolClass.delete()` [V/A]

```
SchoolClass
├── ClassEnrollment                     CASCADE (including historical sessions)
├── ClassSubject                        CASCADE
├── TeacherAssignment                   CASCADE
├── FeePrice (class-scoped)             CASCADE
├── LessonClass.school_class            SET_NULL
└── AcademicStage                       PROTECT is on the child, not the class
```

`ClassDeleteView` warns if currently enrolled students exist but proceeds [V].
It does not warn about past enrollments, assignments, subjects, or prices.

### 3.7 `Term` / `AcademicSession` / `School` [V/A]

Deleting a `Term` cascades invoices, scores, term results, term-scoped fee
prices, and line items. Deleting an `AcademicSession` first cascades its terms
and class enrollments. Deleting a `School` cascades every tenant-scoped row,
including users and audit logs. These root deletions are exposed through
Django admin because `Term`, `AcademicSession`, and `School` are registered
[V].

## 4. Application-level deletion entry points

| # | Entry point | Role / guard | Effect | Evidence |
|---|---|---|---|---|
| D-01 | `school_admin:student_delete` (`POST /students/<pk>/delete/`) | `RoleRequiredMixin` ADMIN, school-scoped | `student.delete()`; warns on enrollments, guardian links, invoices only | `school_admin/views/students.py:472-507` [V] |
| D-02 | `school_admin:payment_delete` (`POST /fees/payments/<pk>/delete/`) | ADMIN, school-scoped | `payment.delete()`; receipt and allocations cascade | `school_admin/views/invoices.py:493-507` [V] |
| D-03 | `school_admin:staff_delete` (`POST /staff/<pk>/delete/`) | ADMIN role **and** superuser; cannot delete self | `User.delete()`; broad cascade, `PROTECT` finance may block | `school_admin/views/staff.py:198-258` [V] |
| D-04 | `school_admin:fee_category_delete` | ADMIN, school-scoped; blocks only if `FeePrice` exists | `category.delete()`; line items, overrides, inventory links cascade | `school_admin/views/fee_categories.py:76-99` [V] |
| D-05 | `school_admin:fee_pricing_delete` | ADMIN, school-scoped | `FeePrice.delete()`; no invoice rows reference `FeePrice` | `school_admin/views/fee_pricing.py:676-700` [V] |
| D-06 | `school_admin:class_delete` | ADMIN, school-scoped; warns on current enrollments | `SchoolClass.delete()`; historical enrollments and class-scoped prices cascade | `school_admin/views/classes.py:163-205` [V] |
| D-07 | `school_admin:subject_delete` | ADMIN, school-scoped; warns on assignments/scores | `Subject.delete()`; assignments, class subjects, scores, M2M cascade | `school_admin/views/academics.py:164-205` [V] |
| D-08 | `school_admin:assignment_delete` | ADMIN, school-scoped | `TeacherAssignment.delete()`; no dependants | `school_admin/views/academics.py:243-260` [V] |
| D-09 | `school_admin:class_subject_remove` | ADMIN, school-scoped | `ClassSubject.delete()`; no dependants | `school_admin/views/classes.py:324-343` [V] |
| D-10 | `school_admin:student_delete_guardian` | ADMIN, school-scoped | `StudentGuardianLink.delete()`; no dependants | `school_admin/views/students.py:678-689` [V] |
| D-11 | `lessons:class_delete` | ADMIN, school-scoped; blocks if enrollments exist | `LessonClass.delete()`; teacher assignments cascade | `lessons/views.py:213-225` [V] |
| D-12 | Lessons teacher removal | ADMIN, school-scoped | `LessonTeacherAssignment.delete()` | `lessons/views.py:245-257` [V] |
| D-13 | `InvoiceResetService.reset_term/class/student/school` | Service has **no internal authorization**; admin actions check superuser; `reset_school` requires `force=True` | Bulk-deletes allocations, payments, line items, invoices; receipts cascade; writes `InvoiceResetLog` | `fees/reset.py:16-150` [V] |
| D-14 | Django admin actions on `Invoice` (`reset_invoices_for_term/class/student`) | Superuser check inside each action | Calls D-13 | `fees/admin.py:190-320` [V] |
| D-15 | `clear_student_payment_history --user-id` | No dry-run, no confirmation flag | Deletes allocations, receipts, payments, line items, invoices, notification logs; writes `InvoiceResetLog` | `fees/management/commands/clear_student_payment_history.py` [V] |
| D-16 | `clear_student_data --school [--dry-run]` | Dry-run optional; no confirmation flag | Deletes notifications, scores, results, lesson enrollments, payments, invoices, enrollments, guardian links, students, orphan rows | `core/management/commands/clear_student_data.py` [V] |
| D-17 | `sync_class_invoices` | Called from fee-pricing views after create/update | Deletes and rewrites all line items and total on invoices with zero payments | `fees/generation.py:157-202` [V] |
| D-18 | `recompute` ranking cleanup | Called by result computation | Deletes stale `TermResult` rows for enrolled students with no approved complete scores | `academics/ranking.py:165-175` [V] |
| D-19 | Django admin delete action | Default admin permission; no `has_delete_permission` override found | Deletes any registered model, including `School`, `AcademicSession`, `Term`, `Student`, `FeeCategory`, `Invoice`, payroll and lesson models | Admin registrations; grep found no override [A] |
| D-20 | Direct ORM / shell / future scripts | None | Any `.delete()` or raw SQL can bypass all view guards | Structural risk [U] |

## 5. Audit-trail coverage

`core/audit.py` watches only `Payment`, `Invoice`, `Score`, `Payslip`, and
`SalaryDisbursement` [V]. It writes `AuditLog` rows on `post_delete` with a
snapshot, and requires a non-null `school` [V]. Consequences:

- Student, guardian, enrollment, class, subject, teacher-assignment, fee
  category, fee price, fee override, invoice-line-item, receipt, allocation,
  term-result, and notification deletions are **not audited** [V].
- Bulk `QuerySet.delete()` still emits `post_delete` for watched models [A];
  `QuerySet.update()` and `bulk_update()` do not emit `post_save` and are
  explicitly documented as bypassing the audit trail [V].
- Deleting a `School` deletes its `AuditLog` rows via the tenant `CASCADE` [V],
  so root deletion also destroys its own audit evidence.
- Deleting a staff user sets `AuditLog.actor` to NULL on prior rows [V],
  removing attribution while keeping the row.

## 6. Verified, assumed, untested

### Verified in code [V]

- Every `on_delete` value in §2.
- Every view/command/service entry point listed in §4.
- `Payment.recorded_by` and `Score.entered_by` are `CASCADE`.
- `FeeCategoryDeleteView` only checks `FeePrice`.
- `StudentDeleteView` and `PaymentDeleteView` call `.delete()` directly.
- `StaffDeleteView` is superuser-only.
- `reset_school` requires `force=True`; the other reset scopes do not.
- `clear_student_payment_history` has no dry-run/confirmation flag.
- `sync_class_invoices` deletes line items on invoices with zero payments.
- No `has_delete_permission` override exists in project code.

### Assumed [A]

- Django's collector performs the cascades described above on both SQLite and
  PostgreSQL. This is documented Django behaviour but was not executed here.
- Django's default admin delete permission applies to registered models.
- `QuerySet.delete()` emits `post_delete` for watched models.
- `PROTECT` finance rows can block a staff delete at runtime.

### Untested [U]

- Actual cascade execution on SQLite or PostgreSQL. No delete was run.
- Database-level `ON DELETE` behaviour for raw SQL deletes.
- Whether any production row currently depends on a path (IC-10 only counts
  at-risk rows on synthetic data).
- Concurrency/transaction behaviour when a delete races with payment or score
  creation.
- Restore/backup recovery for any of these paths.

## 7. Regression tests to add before any deletion-policy change

These are **proposed**, not implemented in this readiness batch:

1. Student delete is refused when invoices/payments/receipts exist, or is
   replaced by archive/deactivate.
2. Payment delete is replaced by a reversal record; receipt remains traceable.
3. Staff delete is refused when the user has recorded payments, entered scores,
   or payroll history; attribution is preserved.
4. Fee-category delete is refused when `InvoiceLineItem`,
   `FeePriceOverride`, or `PaymentLineItem` references exist.
5. Class delete is refused when historical `ClassEnrollment` exists.
6. Subject delete is refused when scores exist.
7. `clear_student_payment_history` requires an explicit confirmation flag and
   writes a dry-run plan first.
8. `clear_student_data` requires a confirmation flag in addition to
   `--dry-run`.
9. `sync_class_invoices` is disabled or explicitly approved; a test proves it
   cannot rewrite a paid invoice.
10. Each destructive path writes an audit row naming actor, scope, counts, and
    reason, and the audit row survives the delete.

## 8. Conflicts with prior documentation

| Claim in prior docs | Working-tree reality | Impact |
|---|---|---|
| `Payment.recorded_by` is `SET_NULL` | `CASCADE` (`fees/models.py:460-466`) | Staff delete destroys payments. |
| `Score.entered_by` is `SET_NULL` | `CASCADE` (`academics/models.py:196-201`) | Staff delete destroys scores. |
| "Delete a student cascades invoices, payments, receipts, scores and results" | True, and also enrollments, guardian links, overrides; the linked `User` is not deleted | The prior graph omitted the user direction and overrides. |
| `FeeCategoryDeleteView` blocks deletion when referenced | It blocks only when `FeePrice` exists | Line items can still be destroyed. |
| "Existing invoices are immutable" | `sync_class_invoices` rewrites unpaid invoices | Not immutable. |

## 9. Open questions for PD-07 / PD-08

1. Is student removal archive-only, or is hard delete ever permitted?
2. Are staff removals deactivation-only, and who owns reassignment of their
   payments/scores?
3. Does category lifecycle become deactivate-only, with deletion reserved for
   never-used categories?
4. Is payment correction a reversal/credit record, and is a receipt ever
   deletable?
5. Which destructive utilities are removed from the production image versus
   hard-gated behind maintenance mode plus a second approver?
6. Should `AuditLog` cover all deletion paths, and how is a school-root delete
   prevented from destroying its own audit history?
