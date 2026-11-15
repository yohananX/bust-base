# BUST-BASE — Final Go/No-Go Corrections Before Implementation

**Date:** 2026-10-22  
**Branch:** main  
**Commit:** ae56339 (repo: cleanup & documentation reconciliation)  
**Status:** Read-only review — no files modified, no migrations created, no production data accessed

---

## Executive Summary

The `FEE_REDESIGN_PLAN.md` (target schema and migration decision record) contains several contradictions and unresolved implementation risks that must be corrected before any implementation begins. This document provides the corrected plan with five specific areas addressed.

**Final decision: Implementation is NOT authorized by existing approvals. A new explicit approval is required after the items in Sections B, C, and D are resolved.**

---

## 1. Snapshot Contradictions — Corrected

### Current Plan Contradiction
The plan states: *"Historical backfills leave unverified names NULL"* but Stages 1 and 3 still populate snapshots from current class/stage names and require non-null values.

### Corrected Policy

| Scenario | Snapshot Behavior | Validation |
|----------|-------------------|------------|
| **Newly created offerings** (after cutover) | Capture `class_name`, `stage_name`, `category_name` at creation time | `NOT NULL` enforced at DB level |
| **Historical backfills** (pre-cutover invoices, line items, term results) | Leave `class_name_snapshot`, `stage_name_snapshot`, `category_name_snapshot` **NULL** | `NULL` permitted; `CHECK` constraint allows NULL for `created_at < cutover_date` |
| **Verified historical names** (admin explicitly confirms via UI) | Populate from verified source | Audit log entry required |
| **Booklet/PDF rendering** | `COALESCE(snapshot, current_name, '—')` with visual indicator for NULL | Template-level fallback; never crashes |

### Enforcement & Audit Strategy for Snapshot Immutability
1. **DB-level**: `CHECK (created_at >= '2026-10-22' OR class_name_snapshot IS NULL OR stage_name_snapshot IS NULL OR category_name_snapshot IS NULL)` — permits NULL only for pre-cutover rows.
2. **Model-level**: `clean()` raises `ValidationError` if any snapshot field is modified after `created_at` (immutable after insert).
3. **Authorized corrections**: New `SnapshotCorrection` model (school, target_model, target_pk, field, old_value, new_value, reason, corrected_by, corrected_at). Admin action creates audit row + updates snapshot. Requires `Roles.ADMIN` + explicit confirmation modal.
4. **No silent corrections**: No management command, signal, or background job may modify snapshots.

> **Do not treat a current name copied during migration as a verified historical name.** The migration must leave historical snapshots NULL. Verification is a separate, deliberate admin action post-migration.

---

## 2. Fee-Price Migration — Corrected

### Current Plan Defect
The plan maps legacy `FeePrice.scope=LEVEL` rows to `TermFeeItem.scope=ACADEMIC_STAGE` based on string matching (`level` field → `AcademicStage.name`) or current class membership. This is unsafe.

### Corrected Policy

| Legacy Scope | Proposed Mapping | **Required Validation** |
|--------------|------------------|-------------------------|
| `SCHOOL_WIDE` | `TermFeeItem.scope=SCHOOL_WIDE` | Automatic — no ambiguity |
| `CLASS` | `TermFeeItem.scope=CLASS` + `school_class_id` | Automatic — FK is explicit |
| `LEVEL` | **BLOCKED** — requires admin approval per row | **Manual review queue** |

### LEVEL-Scope Migration Procedure
1. **Create a review queue** (`FeePriceLevelMappingReview`): each legacy `LEVEL` row becomes a review item with `(school, level_string, term, category, student_type, amount, effective_from, effective_to)`.
2. **Admin maps each row** to exactly one of:
   - `SCHOOL_WIDE` (if truly universal)
   - `ACADEMIC_STAGE` + specific `AcademicStage` (if stage-scoped)
   - `CLASS` + specific `SchoolClass` (if class-scoped)
   - `SPLIT` (different amounts for different stages/classes — creates multiple `TermFeeItem` rows)
   - `DISCARD` (obsolete/duplicate)
3. **Validation against actual resolution**: For each proposed mapping, run the **new resolver** (`fees.pricing.resolve_prices`) against a staging copy of production data and compare the resolved price set for every affected `(student, class, term, category)` tuple against the **legacy resolver** output. Differences must be displayed to the admin before approval.
4. **No bulk approval**: Each row or logically grouped set requires explicit admin action. No "approve all" button.
5. **Cutover**: Legacy `FeePrice` rows with `scope=LEVEL` remain in place and active until their review items are resolved. The new resolver ignores unmapped `LEVEL` rows (they are not migrated to `TermFeeItem`).

### Financial Record Preservation — Non-Negotiable
- **Existing invoices, line items, payments, receipts, allocations, balances**: **Zero changes**. No column updates, no row modifications, no recomputation.
- **Invoice totals**: Must match pre-migration baseline to the penny.
- **Payment allocations**: `PaymentLineItem.source_key`, `kind`, `category`, `term`, `session`, `invoice` links unchanged.
- **Receipts**: `FeeReceipt.receipt_number`, `issued_at`, `payment` link unchanged.
- **Webhook logs**: Immutable.

---

## 3. Audit Query Validation — Corrected

The `FEE_REDESIGN_PLAN.md` does not contain explicit SQL queries. The user references "Query A-3" with a `LEFT JOIN` after `WHERE` — this query does not exist in the current documentation. **No audit queries have been executed against production.**

### Required Queries (To Be Authored and Validated Before Phase 0 Baseline)

Each query below must be:
- **Syntax-validated** against the actual Django models (via `django.db.connection.cursor()` or `QuerySet.query`).
- **Dialect-tested** on PostgreSQL (production) and SQLite (dev).
- **Executed only in a read-only staging environment** with a restored production snapshot.
- **Logged** with exact SQL, row counts, and timestamps.

| ID | Purpose | Draft Logic (Not Final SQL) |
|----|---------|----------------------------|
| Q-01 | Invoice counts & totals by term & status | `Invoice.objects.values('term__name', 'status').annotate(count=Count('id'), total=Sum('total_amount'))` |
| Q-02 | Line-item totals by category & term | `InvoiceLineItem.objects.values('category__name', 'term__name').annotate(total=Sum('amount'), count=Count('id'))` |
| Q-03 | Payment counts & statuses by term | `Payment.objects.values('invoice__term__name', 'status').annotate(count=Count('id'), total=Sum('amount'))` |
| Q-04 | Receipt counts & orphan check | `FeeReceipt.objects.filter(payment__isnull=True).count()` + `Payment.objects.filter(receipt__isnull=True, status=CONFIRMED).count()` |
| Q-05 | Outstanding balances (invoice.total - confirmed payments) | `Invoice.objects.annotate(paid=Sum('payments__amount', filter=Q(payments__status=CONFIRMED))).annotate(balance=F('total_amount')-F('paid')).filter(balance__gt=0)` |
| Q-06 | Fee configuration counts & conflicts (duplicate scopes) | `FeePrice.objects.values('school','scope','school_class','level','term','category','student_type').annotate(c=Count('id')).filter(c__gt=1)` |
| Q-07 | Ambiguous student classifications | `Student.objects.filter(classification_review_required=True).count()` + breakdown by `student_type` vs `registration_paid_term` |
| Q-08 | One-time fee usage (categories, line items, sessions billed) | `FeeCategory.objects.filter(billing_cycle=ONE_TIME).annotate(line_count=Count('invoicelineitem')).filter(line_count__gt=0)` |
| Q-09 | Orphaned references (cross-school) | `FeePrice.objects.exclude(school=F('category__school')).count()` + similar for `TermFeeItem` (post-migration), `InvoiceLineItem`, `PaymentLineItem` |
| Q-10 | Category deletion risk (CASCADE on InvoiceLineItem.category) | `FeeCategory.objects.annotate(line_count=Count('invoicelineitem')).filter(line_count__gt=0)` — **must not delete** |

> **Critical**: Query A-3 (referenced by user) does not exist. Any query with `LEFT JOIN` after `WHERE` is invalid SQL. All joins must precede `WHERE`.

### Execution Status
| Query | Syntax Validated | Dialect Tested | Executed on Staging | Notes |
|-------|------------------|----------------|---------------------|-------|
| Q-01 to Q-10 | ❌ No | ❌ No | ❌ No | **Must complete before Phase 0** |

---

## 4. Deletion & Rollback Analysis — Complete

### Foreign-Key Graph (New & Existing Relationships)

```
School (core)
├── AcademicStage (NEW) — PROTECT on SchoolClass.academic_stage
├── SchoolClass (students) — CASCADE on enrollments, teacher assignments, fee prices
│   ├── ClassEnrollment (students) — CASCADE on Student
│   ├── TeacherAssignment (academics) — CASCADE
│   ├── ClassSubject (academics) — CASCADE
│   ├── FeePrice (fees, legacy) — CASCADE
│   └── TermFeeItem (fees, NEW) — CASCADE (scope=CLASS)
├── AcademicSession (core)
│   ├── Term (core) — CASCADE
│   │   ├── Score (academics) — CASCADE
│   │   ├── TermResult (academics) — CASCADE
│   │   ├── Invoice (fees) — CASCADE
│   │   │   ├── InvoiceLineItem (fees) — CASCADE
│   │   │   └── Payment (fees) — CASCADE
│   │   │       ├── PaymentLineItem (fees) — CASCADE
│   │   │       └── FeeReceipt (fees) — CASCADE
│   │   ├── FeePrice (fees, legacy) — CASCADE
│   │   ├── TermFeeItem (fees, NEW) — CASCADE
│   │   └── FeePriceOverride (fees) — CASCADE (student FK)
│   └── ClassEnrollment.session — CASCADE
├── Student (students)
│   ├── ClassEnrollment — CASCADE
│   ├── Score — CASCADE
│   ├── TermResult — CASCADE
│   ├── Invoice — CASCADE
│   ├── Payment — CASCADE
│   ├── FeePriceOverride — CASCADE
│   └── StudentGuardianLink — CASCADE
├── FeeCategory (fees)
│   ├── FeePrice (legacy) — CASCADE
│   ├── TermFeeItem (NEW) — CASCADE
│   ├── FeePriceOverride — CASCADE
│   └── InvoiceLineItem.category — **CASCADE (RISK: deletes line items)**
├── TermFeeItem (NEW)
│   └── FeePrice (NEW, child) — CASCADE
└── User (accounts)
    ├── TeacherAssignment — CASCADE
    ├── Score.entered_by — SET_NULL
    ├── Payment.recorded_by — SET_NULL
    ├── Payment.confirmed_by — SET_NULL
    ├── FeePriceOverride — no direct FK
    └── AuditLog.actor — SET_NULL
```

### Deletion Behavior for New Relationships

| Model | On Delete | Rationale |
|-------|-----------|-----------|
| `AcademicStage` → `SchoolClass` | `PROTECT` | Prevents accidental stage deletion; archival via `is_active=False` |
| `TermFeeItem` → `FeePrice` (child) | `CASCADE` | Price cannot exist without parent item |
| `TermFeeItem` → `AcademicStage` | `PROTECT` | Stage must be deactivated, not deleted |
| `TermFeeItem` → `SchoolClass` | `PROTECT` | Class must be deactivated, not deleted |
| `FeeCategory` → `InvoiceLineItem` | **CASCADE (EXISTING RISK)** | **Must change to `PROTECT` before release** — see below |

### Archival, Deactivation, Payment Reversals, Authorized Corrections

| Operation | Mechanism | Historical Record Preservation |
|-----------|-----------|--------------------------------|
| **Deactivate AcademicStage** | `is_active=False` (no FK cascade) | All historical `TermFeeItem`/`SchoolClass` links intact |
| **Deactivate SchoolClass** | `is_active=False` | Enrollments, invoices, scores, teacher assignments preserved |
| **Deactivate FeeCategory** | `is_active=False` (after FK change to PROTECT) | Line items, prices, overrides preserved |
| **Deactivate TermFeeItem** | `is_active=False` | Child `FeePrice` rows preserved; resolver ignores inactive |
| **Payment reversal** | New `Payment` with `status=FAILED` or `REFUNDED` (new status) + negative `PaymentLineItem` + original `Payment` unchanged | Original payment row immutable; reversal is new transaction |
| **Authorized price correction** | `SnapshotCorrection` audit row + new `FeePrice` with `effective_from=today` | Old price remains for historical resolution; new price applies forward |
| **Invoice correction** | **Not permitted** — create credit note (new `Invoice` with negative amounts) or reversal payment | Original invoice immutable |

### FeeCategory → InvoiceLineItem CASCADE Risk — Mandatory Fix
**Current**: `InvoiceLineItem.category = FK(FeeCategory, on_delete=CASCADE)`  
**Required**: Change to `PROTECT` + data migration to verify no orphaned categories before release.  
**Migration**: `AlterField(on_delete=PROTECT)` — **must run before any category deactivation UI is enabled**.

### Rollback Conditions Per Phase

| Phase | Rollback Trigger | Rollback Action | Safe? |
|-------|------------------|-----------------|-------|
| **Phase 1** (AcademicStage + SchoolClass.stage) | Any `AcademicStage` row has cross-school FK or `SchoolClass.academic_stage` NULL for active class | `DROP TABLE academics_academicstage`, remove `SchoolClass.academic_stage` field, reverse migrations | **Yes** — additive only, no data mutation |
| **Phase 2** (Student classification fields) | Review flag logic produces false positives/negatives in staging | Remove new fields (`is_new_intake_at_admission`, `classification_review_*`), reverse migrations | **Yes** — additive only |
| **Phase 3** (TermFeeItem + new FeePrice) | Resolver output diverges from legacy for any `(student, class, term, category)` | Keep legacy `FeePrice` resolver active; disable new `TermFeeItem` resolver via feature flag; reverse data migration (preserve PK mapping table) | **Conditional** — if new resolver called by application code, rollback requires code deploy + feature flag flip |
| **Phase 4** (Resolver cutover) | Financial baseline mismatch > 0 or any blocked generation | Feature flag → legacy resolver; do **not** drop tables (new records may depend on them) | **No** — irreversible without full DB restore |
| **Phase 5** (Verify & release) | Unexplained financial differences or unresolved one-time policy | Full rollback = restore pre-Phase-0 backup + redeploy pre-migration code | **No** — production release gate |

> **Key principle**: After Phase 3, if application code writes to `TermFeeItem`/`FeePrice` (new schema), dropping tables is **not** a safe rollback. Rollback = feature flag + code deploy + (if needed) DB restore.

---

## 5. Final Go/No-Go Checklist

### A. Safe to Do Now Without Production Access
*Can be implemented in development, tested against local SQLite, and merged to main.*

- [ ] Create `AcademicStage` model + migration (Phase 1 additive)
- [ ] Add nullable `SchoolClass.academic_stage` FK + migration
- [ ] Add `Student.is_new_intake_at_admission`, `classification_review_required`, `classification_review_reason`, `classification_reviewed_at`, `classification_reviewed_by` + migration
- [ ] Add `ClassEnrollment.enrolled_from_term` (nullable FK) + migration
- [ ] Create `TermFeeItem` model + migration (Phase 3 additive)
- [ ] Create new `FeePrice` child model (FK to `TermFeeItem`, `student_group`, `amount`, `is_active`) + migration
- [ ] Create `FeePriceLevelMappingReview` model (review queue for LEVEL-scope migration) + migration
- [ ] Create `SnapshotCorrection` audit model + migration
- [ ] Change `InvoiceLineItem.category.on_delete` from `CASCADE` to `PROTECT` + migration
- [ ] Implement new resolver (`fees.pricing.NewResolver`) alongside legacy — **feature-flagged OFF**
- [ ] Implement snapshot capture on new offering creation (post-cutover)
- [ ] Implement booklet/template fallback: `COALESCE(snapshot, current, '—')`
- [ ] Unit tests for all new models, validators, resolver logic (100% coverage target)
- [ ] Update `seed_fee_structure.py` to use new models

### B. Requires Production Engine Confirmation or Read-Only Audit
*Must run against a restored production snapshot in a read-only staging environment.*

- [ ] Execute Q-01 through Q-10 (Section 3) — capture exact counts, totals, orphans, conflicts
- [ ] Validate `_is_one_time_already_billed()` logic against actual historical line items
- [ ] Enumerate every legacy `FeePrice.scope=LEVEL` row with its `level` string, term, category, amounts, effective dates
- [ ] Verify `AcademicStage` backfill mapping: for each distinct `SchoolClass.level` value, does a unique `AcademicStage` exist or need creation?
- [ ] Confirm no `FeeCategory` with `invoicelineitem` count > 0 will be deleted (CASCADE→PROTECT migration safety)
- [ ] Cross-school reference scan: `FeePrice.school != FeePrice.category.school`, `Invoice.school != Invoice.student.school`, etc.
- [ ] Payment allocation reconciliation: `Payment.amount` == `SUM(PaymentLineItem.amount)` per payment
- [ ] Receipt integrity: every `CONFIRMED` payment has exactly one `FeeReceipt`

### C. Requires Administrative Reconciliation or Product-Owner Decisions
*Cannot be resolved by engineers alone; requires school admin / product owner input.*

- [ ] **One-time billing scope policy**: For each existing `ONE_TIME` category, decide: `ONCE_PER_STUDENT` vs `ONCE_PER_SESSION` vs `ONCE_PER_TERM` (per §4 of FEE_REDESIGN_PLAN). **Release blocker for affected items.**
- [ ] **LEVEL-scope mapping approval**: Admin must review and approve every `FeePriceLevelMappingReview` item (Section 2). No bulk approval.
- [ ] **Historical snapshot verification**: Admin must explicitly verify/confirm historical class/stage/category names for any pre-cutover records they want displayed in booklets. NULL is the default.
- [ ] **Enrollment model sufficiency**: Confirm `ClassEnrollment.enrolled_from_term` is sufficient (no term-level enrollment model needed) by reviewing registration, promotion, transfer, withdrawal workflows with school admin.
- [ ] **Effective-date ranges on prices**: Does the school use `FeePrice.effective_from`/`effective_to` for mid-term price changes? If yes, new `TermFeeItem`/`FeePrice` must preserve this capability (non-overlapping date ranges per uniqueness).
- [ ] **Category rename policy**: Confirm that renaming a `FeeCategory` must never change applicability/pricing — only display label.
- [ ] **Notification preferences**: Deferred per CONTEXT.md — confirm still deferred.

### D. Requires Implementation Approval
*Explicit sign-off from stakeholders before any production migration.*

- [ ] **Product Owner**: Approves one-time billing policy (C.1), LEVEL-scope mapping procedure (C.2), enrollment model sufficiency (C.4).
- [ ] **School Admin (primary tenant)**: Approves historical snapshot verification workflow (C.3), category rename policy (C.6).
- [ ] **Engineering Lead**: Approves Phase 3+ rollback strategy (Section 4), feature-flag architecture for resolver cutover.
- [ ] **Security/Compliance**: Approves `SnapshotCorrection` audit trail, payment reversal workflow, `FeeCategory` CASCADE→PROTECT change.

---

## Final Decision

| Question | Answer |
|----------|--------|
| **Is implementation authorized by existing approvals?** | **NO** |
| **Does it require a new explicit approval?** | **YES** |
| **Minimum approvals needed before Phase 1 merge** | Product Owner + Engineering Lead (Section D items 1, 3) |
| **Minimum approvals needed before Phase 3 (data migration)** | All Section D items + Section B audit complete + Section C items 1-4 resolved |
| **Minimum approvals needed before Phase 5 (production release)** | All Section B, C, D items complete + financial baseline reconciliation within tolerance |

---

## Next Steps (If Approved)

1. **Merge Phase 1-2 additive changes** (Section A) to `main` behind feature flags.
2. **Provision read-only staging** with production snapshot; execute Section B queries.
3. **Convene admin/product review** for Section C decisions; document in `DECISIONS.md`.
4. **Obtain Section D sign-offs** in writing (GitHub issue approvals or signed document).
5. **Only then** begin Phase 3 data migration with review queue.
6. **Phase 4+** require separate go/no-go after staging validation.

---

**Document Control**  
This report supersedes any conflicting statements in `FEE_REDESIGN_PLAN.md`. The plan remains the target architecture; this document corrects its migration execution constraints. No implementation shall proceed until the Section D approvals are recorded.