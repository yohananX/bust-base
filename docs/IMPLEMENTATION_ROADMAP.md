# BUST-BASE — Authoritative Implementation Roadmap

**Status:** Planning and Phase 1 review. No production access, no production migration, no restore, no deletion-policy change.
**Date:** 2026-10-23
**Branch:** `feat/academic-structure-phase1`
**Baseline commit:** `8a1bdcc287826253ee51bf9d2e3619706ee15546` (`main`)
**Companion register:** [`docs/IMPLEMENTATION_DEPENDENCY_REGISTER.md`](IMPLEMENTATION_DEPENDENCY_REGISTER.md)

---

## 0. Document control and reconciliation

### 0.1 Why this document exists

The repository contains several planning and audit documents written at different times, against different working-tree states. They are useful but not directly executable as one plan:

| Document | Actual role | What it is not |
|---|---|---|
| `docs/FEE_REDESIGN_PLAN.md` | Target architecture, constraints, migration principles, acceptance criteria | Not an execution schedule; its Phase 0–5 numbering is not aligned with `fee_redesign.md` Stage 0–8 |
| `docs/FINAL_GO_NOGO_CORRECTIONS.md` | Corrected execution constraints, especially snapshots, LEVEL mapping, deletion and rollback | Not current: it cites commit `ae56339`, not HEAD; two FK claims are factually wrong (see §0.3) |
| `docs/PHASE0_READINESS_PLAN.md` | Readiness workstreams R/DA/PD/IM/AP and gates G0–G6 | Not a consolidated current-state report; it predates the Phase 0 audit harness and the AcademicStage corrections in this task |
| `fee_redesign.md` (root) | Implementation prompt and non-negotiable rules | Its Stage numbers do not map to the plan's Phase numbers; it points to a root `FEE_REDESIGN_PLAN.md` that does not exist |
| `docs/audit/*` | Evidence, query catalogue, dialect matrix, deletion inventory, recovery investigation | Readiness evidence only; queries are `DRAFT`; PostgreSQL is not executed |
| `docs/AUDIT_STATUS.md` | Historical status note | Stale: cites `ae56339` and claims that public dumps were purged; the recovery investigation contradicts that claim |

This roadmap is the single execution-order document. It **preserves** the architecture and invariants in `docs/FEE_REDESIGN_PLAN.md` and the corrected constraints in `docs/FINAL_GO_NOGO_CORRECTIONS.md`, except where this document explicitly records a factual correction. It does not delete or rewrite the source documents.

The dependency register is separate because it is operational: it records each affected symbol, consumer, prerequisite, test, risk and status. Keeping it separate avoids turning the roadmap into an unmaintainable code inventory.

### 0.2 Numbering reconciliation

The project has three numbering schemes. This roadmap uses **P0–P8** and maps them to the older schemes:

| Roadmap phase | `FEE_REDESIGN_PLAN.md` phase | `fee_redesign.md` stage | `PHASE0_READINESS_PLAN.md` gate |
|---|---|---|---|
| P0 — Baseline and evidence | Phase 0 | Stage 0–1 | G0 |
| P1 — Academic structure | Phase 1 | Stage 2 | G1 |
| P2 — Student classification | Phase 2 | Stage 3 | G2 |
| P3 — Enrollment / offering decision | Phase 2 (enrollment part) | Stage 3 (enrollment part) | G1/G3 |
| P4 — Scoped fee configuration (schema) | Phase 3 | Stage 4 | G3 |
| P5 — Resolver and generation cutover | Phase 4 | Stages 5–6 | G4/G5 |
| P6 — Historical snapshots and booklets | Phase 5 (snapshot part) | Stage 7 | G5 |
| P7 — Deletion, audit, tenant hardening | Cross-cutting | Stage 7 | G4/G5 |
| P8 — Production migration and cutover | Phase 5 | Stage 8 | G5/G6 |

### 0.3 Corrections to prior documents

These are factual corrections, not architectural changes:

1. **Stale commit.** `docs/FINAL_GO_NOGO_CORRECTIONS.md` cites `ae56339`; the verified baseline is `8a1bdcc`.
2. **Deletion-policy facts.** `docs/FINAL_GO_NOGO_CORRECTIONS.md` states `Payment.recorded_by` and `Score.entered_by` are `SET_NULL`. The working tree has both as `CASCADE` (`fees/models.py`, `Payment.recorded_by`; `academics/models.py`, `Score.entered_by`). `docs/audit/DELETION_INVENTORY.md` already records this correctly.
3. **Path drift.** `fee_redesign.md` says the specification is at the repository root. It is at `docs/FEE_REDESIGN_PLAN.md`.
4. **Working-tree drift.** `docs/audit/RECOVERY_EVIDENCE_INVESTIGATION.md` says its own addition is the only repository change. At the start of this task the tree also contained uncommitted AcademicStage work and Phase 0 audit artefacts. The recovery report's Git-object findings remain valid; its working-tree statement is stale.
5. **Local database state.** The local SQLite database has `students.0008_add_academic_stage` applied (verified read-only in `django_migrations`). It contains zero `students_academicstage` and zero `students_schoolclass` rows. This does not make the migration deployed or production-proven.
6. **Snapshot policy is already violated in data history.** `fees/migrations/0022_backfill_fee_price_and_line_item_names.py` already wrote current category names into historical `InvoiceLineItem.item_name` and `FeePrice.name`. The corrected policy must not be “fixed” by nulling those values; provenance must be decided (PD-04).

### 0.4 Evidence labels

| Label | Meaning |
|---|---|
| **Verified** | Observed in the working tree, a read-only database query, or an executed test. |
| **Partially verified** | Some evidence exists, but a required consumer, engine, or environment was not checked. |
| **Unverified** | Plausible but not observed; must not be reported as fact. |
| **Blocked** | Cannot proceed without a decision, evidence, or authorization. |
| **Complete** | Implemented and tested for the stated scope. |

---

## 1. Baseline and repository state

### 1.1 Git state at task start

- Branch: `main`
- HEAD: `8a1bdcc287826253ee51bf9d2e3619706ee15546`
- Staged changes: none (`git diff --cached` empty)
- Stashes: none
- Working tree: dirty

Pre-existing modifications (not authored by this task):

| File | SHA-1 at start |
|---|---|
| `docs/FEE_REDESIGN_PLAN.md` | `4b546661ff571819627e088a2c0a8c3d8168164b` |
| `students/admin.py` | `3fa763c327d03c2ff21dd95115a015e17a62cb99` |
| `students/models.py` | `5372fd0cffba2837b92ac90fd82b039fb4aa1578` |
| `students/tests.py` | `571365b33f2f22b4e582a0080aa26a96e61f53a8` |

Pre-existing untracked files:

`docs/FINAL_GO_NOGO_CORRECTIONS.md`, `docs/PHASE0_READINESS_PLAN.md`, `docs/audit/*`, `fee_redesign.md`, `scripts/audit/*`, `students/migrations/0008_add_academic_stage.py`.

A full baseline record (status, diff, untracked hashes) was written to `/tmp/opencode/bustbase-baseline/baseline.txt`; its SHA-256 is `9e25437052db7c0981a72ccbde1d26d1af7e228171ce6ca2df89c2c854f9ce91`.

### 1.2 Branch decision

`feat/academic-structure-phase1` did not exist locally or remotely. It was created from `8a1bdcc` with `git switch -c`. No file was stashed, reset, cleaned, overwritten, staged, or committed. All pre-existing modifications and untracked files were preserved byte-for-byte (hashes re-checked after branch creation).

### 1.3 What must not be assumed

- The AcademicStage work is **uncommitted**. It is not merged, deployed, or present in production.
- `students.0008_add_academic_stage` is applied only in the local development database. That is not staging or production evidence.
- No PostgreSQL test was executed in this task. SQLite results do not prove PostgreSQL compatibility.
- The recovery investigation's “no production loss” / “loss confirmed” question remains unresolved.

---

## 2. Current-state assessment

| Area | State | Evidence | What remains |
|---|---|---|---|
| AcademicStage model | **Implemented, uncommitted, corrected in this task** | `students/models.py:10`; `students/migrations/0008_add_academic_stage.py`; `students/migrations/0009_academicstage_normalized_unique.py` | Review and commit; decide whether to add a school-admin stage selector |
| AcademicStage school scoping | **Verified for model and class validation** | `TenantScopedModel`; `AcademicStage.clean()`; `SchoolClass._validate_academic_stage_school()` | Cross-table tenant rule is not DB-enforced; `bulk_create`/`update` bypass it |
| AcademicStage normalized uniqueness | **Complete for SQLite; PostgreSQL unverified** | `UniqueConstraint(Lower(Trim('name')), 'school')`; 12 targeted tests pass | Run on PostgreSQL in a non-production environment |
| Stage ordering / activation | **Implemented** | `display_order`, `is_active`, `Meta.ordering` | No default-stage seeding; no “one active stage per order” rule |
| Class stage selector (school admin portal) | **Not implemented** | `school_admin/views/classes.py:54-160`; `school_admin/templates/school_admin/class_form.html` only posts `name`, `level`, `is_active` | Add stage dropdown scoped to `request.school`, or explicitly defer |
| Stage backfill from `level` | **Not implemented** | No data migration | Needs IC-3 evidence and per-row approval (PD-05) |
| `SchoolClass.level` | **Retained** | `students/models.py:62`; migration 0008 only changes help text | Must remain until every consumer is migrated and removal is approved |
| `SchoolClass.is_active` | **Retained** | `students/models.py:76` | Must not be removed in this work |
| Student classification fields | **Planned** | `docs/FEE_REDESIGN_PLAN.md` §2.2 | PD-02, schema, backfill, review queue |
| `ClassEnrollment` term dimension | **Planned / undecided** | `students/models.py:254-291`; unique `(student, session)` | PD-03; no `enrolled_from_term` yet |
| `ClassOffering` | **Absent** | No symbol in code or docs | Define grain and FK semantics before any migration |
| `TermFeeItem` / group-specific prices | **Planned** | `docs/FEE_REDESIGN_PLAN.md` §2.3 | PD-01, PD-06, schema, mapping, dual resolver |
| Legacy `FeePrice` resolver | **Live** | `fees/pricing.py:resolve_prices` | Cross-term fallback, category-name gate, one-time prior-session guard |
| Invoice generation | **Live, side-effecting** | `fees/generation.py`; `school_admin/views/fee_pricing.py` calls generation and `sync_class_invoices` | Explicit/idempotent generation is not implemented |
| Historical snapshots | **Partially corrupted** | `fees/migrations/0022_*`; `InvoiceLineItem.item_name` | PD-04 provenance/verification; do not re-null |
| Deletion protections | **Not implemented** | `docs/audit/DELETION_INVENTORY.md` | PD-07/PD-08; category, payment, student, staff, class paths |
| Audit coverage | **Gap** | `core/audit.py` watches only five models | Extend only after `school` nullability and deletion policy are decided |
| Phase 0 harness | **Readiness complete, SQLite only** | `scripts/audit/*`; `docs/audit/READINESS_REPORT.md` | PostgreSQL run; production-derived evidence is blocked |
| Recovery / data-loss question | **Unverified** | `docs/audit/RECOVERY_EVIDENCE_INVESTIGATION.md` | Owner-authorized evidence gathering; no restore attempted |

### 2.1 AcademicStage implementation status detail

**Verified implemented:**

- Tenant-scoped `AcademicStage` with `name`, `display_order`, `is_active`.
- `SchoolClass.academic_stage` nullable FK with `PROTECT`.
- Admin registration for both models; stage autocomplete on class admin.
- School-scoped exact uniqueness plus normalized case/whitespace uniqueness.
- Model-level and write-path validation that a class's stage belongs to the same school.
- Ordering by `display_order`, then `level`, then `name`.
- Tests for creation, exact/case/whitespace duplicates, cross-school isolation, normalization, ordering, and inactive-stage preservation.

**Verified limitations:**

- `SchoolClass.clean()`/`save()` cannot prevent `QuerySet.update()` or `bulk_create()` from setting a cross-school stage. No single-table DB constraint can express this.
- The normalized uniqueness constraint is a functional unique index. It was exercised on SQLite 3.45.1 only.
- There is no school-admin class form selector, so classes created through `school_admin` have `academic_stage = NULL`.
- No stage backfill exists. That is correct for this task: current `level` values are not reliable historical stage evidence.
- `AcademicStage` has no timestamp fields. This follows the existing `TenantScopedModel` convention but differs from models that define `created_at`; not a correctness defect.

### 2.2 Bounded Phase 1 corrections applied in this task

| # | Defect (file / symbol) | Expected behaviour and why in scope | Regression test | Smallest change | Result |
|---|---|---|---|---|---|
| C1 | `students/models.py:AcademicStage.Meta` had only exact `unique_together ('school','name')`; `clean()` used `iexact` but was bypassed by `objects.create()`. Case/whitespace variants could exist in one school. | School-scoped uniqueness must include the documented case/whitespace policy. This is an explicit P1 acceptance criterion. | `test_academic_stage_case_insensitive_unique_per_school`, `test_academic_stage_whitespace_insensitive_unique_per_school`, `test_academic_stage_name_is_normalized_on_save` | Add `UniqueConstraint(Lower(Trim('name')), 'school')`; normalize on `save()`; call `super().clean()`. Additive migration `0009`. | 12 targeted tests pass on SQLite; PostgreSQL unverified |
| C2 | `students/models.py:SchoolClass.clean()` enforced same-school stage, but `objects.create()`/`save()` did not. | A class must not reference another tenant's stage on ordinary writes. Tenant isolation is a critical project pattern; the requirement explicitly warns not to assume `clean()` protects every ORM path. | `test_school_class_cross_school_stage_rejected_on_orm_create` | Extract `_validate_academic_stage_school()` and call it from both `clean()` and `save()`. | Targeted and `students` suites pass |
| C3 | `students/admin.py:SchoolClassAdmin.list_filter` replaced the existing `level` filter with `academic_stage`. | Existing class filtering must not break; `level` remains a live field and consumer input. | Existing `school_admin` suite; admin behaviour smoke | Add `level` back alongside `academic_stage`; add `list_select_related`. | `school_admin`: 103 tests pass |

**Why these are in scope:** each is a narrow correction to an existing Phase 1 implementation, not a new phase. C1 and C2 enforce stated P1 invariants; C3 prevents a regression in existing class filtering. None touches historical financial or academic records, deletion policy, or a broad schema redesign.

**What was deliberately not changed:** stage backfill, school-admin stage selector, `level` removal, `is_active` removal, historical snapshots, enrollment, fees, scores, results, deletion policy, and production configuration.

---

## 3. Phase sequence, scope, and acceptance criteria

The ordering rule is strict: a phase may not begin until its prerequisites are complete. “Can start now” means without production access and without a new decision.

### P0 — Baseline, evidence, and safety rails

**Purpose:** establish a trustworthy baseline before any schema or data change.

**Prerequisites:** none.

**Scope:**

- Record Git HEAD, branch, working-tree hashes, and database identity.
- Complete the read-only query catalogue and schema validator.
- Run the catalogue on synthetic data and on SQLite; record PostgreSQL as `NOT RUN`.
- Inventory deletion paths and audit coverage.
- Freeze unattended destructive migration execution (separate approval; not done).
- Obtain owner authorization for read-only production-derived evidence (not done).

**Acceptance criteria:**

- Baseline record exists and is reproducible.
- Every query has an ID, grain, expected columns, and a `DRAFT`/`EXECUTED` status.
- No query has been reported as passed without captured output.
- PostgreSQL is explicitly `NOT RUN` unless it was actually executed.
- Deletion inventory distinguishes verified, assumed, and untested behaviour.

**Current status:** **Partially complete.** Readiness artefacts exist and their tests pass; production-derived execution and PostgreSQL remain blocked.

### P1 — Academic structure

**Purpose:** introduce `AcademicStage` without changing historical enrollment, result, or fee behaviour.

**Prerequisites:** P0 baseline; P1 decision on whether the school-admin class form must expose the stage selector in this phase.

**Scope:**

- `AcademicStage` model and migration.
- Nullable `SchoolClass.academic_stage`; keep `level` and `is_active`.
- School-scoped uniqueness with a documented case/whitespace policy.
- Same-school validation on model and ordinary write paths.
- Admin registration and filters.
- Tests for valid records, duplicates, cross-school isolation, normalization, ordering, and edge cases.

**Explicit non-goals:**

- No stage backfill from `level`.
- No removal of `level`.
- No historical snapshot population.
- No ClassOffering creation.
- No fee, invoice, score, or result mutation.

**Acceptance criteria:**

- A school can create, rename, reorder, and deactivate stages.
- Duplicate names within a school are rejected regardless of case and outer whitespace.
- The same name in another school is allowed.
- A class cannot reference another school's stage through `full_clean()` or ordinary `save()`/`create()`.
- Existing class creation/editing/filtering/rendering still works.
- `makemigrations --check` reports no missing migration.
- Targeted and broader SQLite tests pass; PostgreSQL compatibility is separately verified or explicitly unverified.

**Current status:** **Substantially complete for the model/admin/test scope.** The school-admin stage selector and PostgreSQL verification remain open.

### P2 — Student classification

**Purpose:** make new-intake status an explicit admission decision, not a payment side effect.

**Prerequisites:** P1; PD-02; P0 evidence for legacy ambiguity; AP-01.

**Scope:** new admission indicator, review fields, classification resolver, review queue, generation blocking. Keep `student_type` and `registration_paid_term` during transition.

**Acceptance criteria:**

- New-intake checkbox defaults off and persists.
- First enrolled term can be Term 1, 2, or 3.
- Subsequent terms resolve as returning.
- Registration Form payment never changes classification.
- Ambiguous legacy students are blocked from generation until reviewed.
- Review completion is explicit, authorized, and auditable.

**Current status:** **Not started.** `fees/utils.resolve_student_type` still uses prior enrollment and `registration_paid_term`; `school_admin/views/invoices.py` still flips `student_type` on registration payment.

### P3 — Enrollment and class-offering decision

**Purpose:** decide whether the existing one-class-per-session model can represent first-enrolled-term and mid-session changes.

**Prerequisites:** P1; PD-03; evidence from registration/promotion/transfer/withdrawal workflows.

**Scope:** either add nullable `ClassEnrollment.enrolled_from_term` with session/school validation, or introduce a term-level enrollment/offering model. Do not overwrite history.

**Acceptance criteria:**

- The chosen model has a documented grain and FK delete behaviour.
- Session/school consistency is validated.
- One-placement-per-student-per-session (or the approved replacement) is enforced.
- Historical enrollment is not reinterpreted from current data.
- `ClassOffering` is defined or explicitly rejected with rationale.

**Current status:** **Blocked on PD-03.** No `ClassOffering` symbol exists.

### P4 — Scoped fee configuration (schema only)

**Purpose:** separate fee-item applicability from group-specific prices.

**Prerequisites:** P2/P3 as applicable; PD-01, PD-05, PD-06; AP-02.

**Scope:** `TermFeeItem`, child price model, scope check constraints, tenant validation, LEVEL mapping review queue. Legacy `FeePrice` fields remain.

**Acceptance criteria:**

- Scope/target integrity is DB-enforced where possible and service-validated for cross-table rules.
- Uniqueness prevents duplicate active scoped items/prices.
- Existing `FeePrice` rows remain available; no destructive conversion.
- LEVEL rows are not auto-mapped; each requires approval.
- Effective-date semantics are preserved or explicitly retired by decision.

**Current status:** **Not started.** Blocked on PD-01 and PD-06; `TermFeeItem` does not exist.

### P5 — Resolver and generation cutover

**Purpose:** one canonical resolver and explicit, idempotent invoice generation.

**Prerequisites:** P4; equivalence harness; AP-04/AP-05.

**Scope:** new resolver behind a flag; remove cross-term fallback and category-name gates only after equivalence is measured; stop generation on registration/class changes and fee-config saves; preflight, atomicity, batch reporting; no automatic notifications.

**Acceptance criteria:**

- Legacy resolver remains default until approved.
- Every legacy/new difference is explained per `(school, student, class, term, category, group)`.
- Re-running generation skips existing invoices and never reprices.
- Concurrent generation preserves `(school, student, term)` uniqueness.
- Failed generation does not leave partial invoices.
- No email/SMS is sent by generation.

**Current status:** **Not started.** `school_admin/views/fee_pricing.py` still calls generation and `sync_class_invoices`; `fees/generation.py` still deletes/rewrites unpaid invoice lines.

### P6 — Historical snapshots and booklets

**Purpose:** stop presenting current names as historical facts.

**Prerequisites:** P0 evidence; PD-04; P5 where generation writes new snapshots.

**Scope:** decide NULL-with-fallback vs provenance marker vs admin verification; add capture at creation; render fallback; authorized correction audit.

**Acceptance criteria:**

- New records capture names at creation.
- Historical unverified names are NULL or explicitly provenance-marked.
- Booklets render without crashing and disclose fallback.
- No migration re-copies current names into history.
- Corrections require admin role, reason, old/new values, and immutable audit.

**Current status:** **Blocked on PD-04.** `0022` already wrote current names into history; `academics/booklet.py` reads current `SchoolClass` names via enrollment.

### P7 — Deletion, audit, and tenant hardening

**Purpose:** prevent ordinary operations from destroying financial/academic history.

**Prerequisites:** PD-07, PD-08; P0 deletion inventory; AP-04.

**Scope:** category `PROTECT`/preflight; student/payment/staff/class deletion guards or archival; reversal records; destructive utility gating; audit coverage; tenant consistency checks.

**Acceptance criteria:**

- Referenced categories/payments/students cannot be hard-deleted without an approved path.
- A reversal exists instead of deleting payment history.
- Destructive commands require explicit maintenance mode and confirmation.
- Audit rows name actor, scope, counts, and reason and survive the operation.
- No production data is deleted as part of this phase.

**Current status:** **Not started.** `docs/audit/DELETION_INVENTORY.md` documents the live paths.

### P8 — Production migration and cutover

**Purpose:** execute approved schema/data changes and switch the resolver in a controlled window.

**Prerequisites:** P0–P7 as applicable; AP-03, AP-04, AP-05; staging verification; backup/restore drill; rollback owner.

**Scope:** run migrations/backfills on a staging copy first; reconcile financial baseline; deploy; observe; roll back on defined triggers.

**Acceptance criteria:**

- Pre/post invoice, line-item, payment, receipt, allocation and balance baselines reconcile, or differences are documented and approved.
- No unexplained invoice total/line-item mismatch.
- Resolver flag can be disabled without dropping tables.
- Rollback owner and abort thresholds are recorded.
- Production credentials and data are handled only by authorized humans.

**Current status:** **NO-GO.** Gate 0 evidence is incomplete and no production access is authorized.

---

## 4. Migration strategy

### 4.1 Principles

1. Additive first; expand/contract. Do not rewrite, squash, or delete existing migrations.
2. Never use reset utilities, invoice deletion, or payment-history clearing to make a schema fit.
3. Keep legacy columns until all consumers are migrated and removal is separately approved.
4. Backfill only from reliable evidence. If the mapping is ambiguous, leave NULL and report it.
5. Never populate historical snapshots from current names merely because a current record exists.
6. Use transactions for backfills; make large backfills restartable and idempotent.
7. Capture pre/post counts, totals, and checksums before and after every data migration.
8. A failed migration stops the rollout; it is not repaired by resetting financial data.

### 4.2 Phase 1 schema changes in this task

| Migration | Operation | Safety | Notes |
|---|---|---|---|
| `students/0008_add_academic_stage.py` | Create `AcademicStage`; add nullable `SchoolClass.academic_stage`; alter class ordering/help text | Additive; nullable FK; no data mutation | Pre-existing untracked work, reviewed and retained |
| `students/0009_academicstage_normalized_unique.py` | Add functional unique constraint on `(school, Lower(Trim(name)))` | Additive constraint | Fails if pre-existing case/whitespace duplicates exist; local DB has zero stage rows; production state unverified |

**Important:** 0009 is a schema migration and requires review/approval before production. It was exercised only in the SQLite test database. Do not apply it to a real database in this task.

### 4.3 Data migrations not authorized here

- Stage backfill from `SchoolClass.level`.
- `ClassEnrollment.enrolled_from_term` backfill.
- Student classification backfill or review flagging.
- `TermFeeItem` / price conversion.
- Snapshot provenance or correction.
- Any invoice, line-item, payment, receipt, allocation, score, or result mutation.

### 4.4 Reconciliation and integrity checks

Use the catalogue in `docs/audit/QUERY_SPEC.md` and the SQL in `docs/audit/HISTORICAL_DATA_LOSS_REVIEW.md` §5.3. The minimum set before any data migration:

- Invoice `total_amount` vs `SUM(line_items.amount)`.
- Invoices with zero surviving lines but non-zero totals.
- `PaymentLineItem` with NULL category/invoice or orphaned invoice.
- `FeeReceipt` presence vs confirmed payments.
- `FeeCategory` / `FeePrice` / `FeePriceOverride` counts and cross-school references.
- `SchoolClass.level` distinct values vs stage names (IC-3).
- `Payment.amount` vs `SUM(PaymentLineItem.amount)`.
- Duplicate `FeePrice` rows, especially nullable `school_class`/`level`/`term` dimensions.
- Deletion exposure counts (IC-10).

All queries remain `DRAFT` until executed against an authorized, restored, read-only copy and recorded with the R-11 evidence template.

---

## 5. Testing strategy

### 5.1 Test layers

| Layer | Purpose | Current state |
|---|---|---|
| Targeted unit/model tests | New constraints, validation, ordering, tenant rules | 12 AcademicStage tests pass on SQLite |
| App regression tests | `students`, `school_admin` behaviour after model/admin changes | `students`: 89 pass; `school_admin`: 103 pass (SQLite) |
| Cross-app regression | Fees, academics, data import, notifications, tenancy | Full suite started; see final report for actual result |
| Migration-state check | `makemigrations --check`, `manage.py check` | Both pass |
| Database-engine matrix | SQLite + PostgreSQL | SQLite only; PostgreSQL **NOT RUN** |
| Staging verification | Realistic restored copy, read-only audit, then migration rehearsal | Blocked |

### 5.2 Required commands (record actual output, never assume)

```bash
.venv/bin/python manage.py test students.tests.AcademicStageTests -v 2
.venv/bin/python manage.py test students -v 1
.venv/bin/python manage.py test school_admin -v 1
.venv/bin/python manage.py makemigrations --check --dry-run
.venv/bin/python manage.py check
```

PostgreSQL and full-suite commands must be reported separately. A SQLite pass is not a PostgreSQL pass.

### 5.3 Test data rules

- Use synthetic or test-database data only.
- Do not copy production PII into fixtures.
- Do not run destructive management commands.
- Do not assert a cascade was executed unless it was executed; static `on_delete` inspection is labelled as such.

---

## 6. Rollback and recovery

### 6.1 Phase-level rollback truth table

| After… | Drop new tables/columns | Revert code | Restore backup | Notes |
|---|---|---|---|---|
| Additive schema, no writes | Safe | Safe | Unnecessary | P1 model/constraint only |
| Stage rows written, no classes linked | Safe if approved | Safe | Unnecessary | Preserve audit/evidence first |
| Classes linked to stages | **Unsafe** to drop blindly | Safe | Safe | Dropping loses classification evidence |
| Classification/backfill written | **Unsafe** | Safe if legacy path intact | Safe | Do not reclassify silently |
| New resolver issues invoices | **Unsafe** | Only with legacy resolver restored | Point-in-time only | New invoices are real records |
| Financial records mutated | **Never** | **Never** | Only recovery | Stop and escalate |

### 6.2 Detection and abort criteria

- Any migration error or constraint failure: stop; do not “fix” by deleting rows.
- Any unexpected change in invoice totals, line-item sums, payment allocations, receipts, or balances: stop.
- Any cross-school reference introduced: stop and identify the write path.
- Any test failure caused by the change: fix or revert the change; do not weaken the test.
- Any PostgreSQL-only failure: do not claim compatibility; record and resolve before production.

### 6.3 Recovery boundaries

- No restore is authorized by this roadmap.
- No deletion of Git branches, history rewrite, cache purge, credential rotation, or production access is authorized.
- The surviving dumps cannot restore records they do not contain.
- A missing backup is not “permanently unrecoverable” while inaccessible locations remain unexamined.

---

## 7. Approval gates

| Gate | Covers | Does not cover |
|---|---|---|
| Ordinary code change | Model/view/admin/test edits in the repository | Schema migration execution, data change, deployment |
| Schema migration | Adding a migration file and applying it in a non-production environment | Production migration, historical-data transformation |
| Historical-data transformation | Backfills, reclassification, snapshot correction, reconciliation writes | Production deployment |
| Production deployment | Running migrations and code in production | Future schema changes or resolver cutover beyond the approved scope |

**Rules:**

- A merged migration is not an executed migration.
- Additive does not automatically mean safe.
- No phase may be marked complete because tests pass if the relevant environment was not tested.
- The Phase 1 corrections in this task are ordinary code + additive schema. They do **not** authorize production execution.

### 7.1 Incident-response boundary (not authorized here)

The recovery investigation identifies actions that require separate human authorization. This task does **not** authorize:

- Rotating credentials or revoking sessions.
- Deleting branches, rewriting Git history, or requesting GitHub cache purges.
- Accessing `/root`, inaccessible media, or protected Docker volumes.
- Obtaining production credentials or accessing production data.
- Running production queries or migrations.
- Restoring a database.
- Changing deletion policies.

These are tracked as separate decisions in §8 and §10. They do not block safe, unrelated code review.

---

## 8. Unresolved decisions requiring owner authorization

| ID | Decision | Why it blocks | Recommended option |
|---|---|---|---|
| PD-01 | One-time billing scope (`ONCE_PER_STUDENT`, `ONCE_PER_SESSION`, `ONCE_PER_TERM`, per-item configurable) | `TermFeeItem.term` nullability and generation enforcement | Per-item configurable scope; do not infer from names |
| PD-02 | Classification source of truth and fate of payment auto-flip | P2 schema, backfill, resolver | Explicit admission flag + review queue; no payment-driven flip |
| PD-03 | Enrollment grain and `ClassOffering` semantics | P3 schema and deletion analysis | Prove whether one class per session is sufficient before adding a table |
| PD-04 | Historical snapshot treatment, including rows already written by 0022 | P6 booklets and correction workflow | Provenance marker + admin verification; do not re-null or re-copy |
| PD-05 | LEVEL-scope mapping and per-row approval | P4 migration | Per-row admin approval; no bulk approval |
| PD-06 | Whether `effective_from`/`effective_to` remain supported | P4 uniqueness/resolver | Inspect actual use; preserve if used |
| PD-07 | Category/student/payment/staff lifecycle: deactivate-only vs delete | P7 protections | Deactivate-only for referenced records; hard delete only for never-used records |
| PD-08 | Payment reversal and invoice correction policy | P7 and financial integrity | Reversal/credit record; never edit or delete original |
| SEC-01 | Treat public dump exposure as an incident? | Credential/session risk | Yes; preserve evidence first, then rotate and purge under authorization |
| SEC-02 | Authorize controlled dump copies and branch/history purge? | Public exposure | Yes, with chain of custody |
| SEC-03 | Authorize read-only inspection of Docker volume / `/root` / `/media`? | Missing backup evidence | Yes, read-only |
| SEC-04 | Authorize production evidence acquisition? | Data-loss quantification | Yes; read-only replica/dump, no production writes |
| SEC-05 | Change deletion policies now? | P7 | Defer until evidence and PD-07/PD-08 |
| SEC-06 | Notify affected users/schools? | Exposure scope | Pending evidence |

---

## 9. Parallel investigations that can proceed safely

These do not require production access and do not block Phase 1:

| Investigation | Deliverable | Why safe |
|---|---|---|
| Admission-number header mapping | Consumer map for `students/utils.py:_map_class_to_header`; decide whether stage should ever feed it | Read-only; no behavior change |
| `SchoolClass.is_active` invoice filters | List every generation/filter path and whether inactive classes are included | Read-only |
| `ClassEnrollment` consistency | Enumerate writers and missing school/session checks | Read-only |
| `ClassSubject` session dimension | Confirm it is session-agnostic and list consumers | Read-only |
| `TeacherAssignment` session scope | Confirm existing session FK and consumers | Read-only |
| Score/report historical class display | Trace `academics/booklet.py`, `students/views.py`, `school_admin/views/invoices.py` | Read-only |
| FeePrice scope/precedence | Trace `fees/pricing.py` and all callers | Read-only |
| Invoice/payment/receipt history | Map models and read paths; run synthetic queries only | Read-only |
| Tenant isolation | Static scan for unscoped queries and cross-school FKs | Read-only |
| Deletion/audit | Extend `DELETION_INVENTORY.md` with runtime tests later | Read-only |

These must wait for evidence or a decision:

- Stage backfill from `level` (needs IC-3 and PD-05).
- Classification backfill (PD-02).
- Enrollment/offering schema (PD-03).
- `TermFeeItem` conversion (PD-01/PD-06).
- Snapshot correction (PD-04).
- Deletion-policy changes (PD-07/PD-08).
- Any production migration or restore (AP-03/AP-04/AP-05).

### 9.1 Consumer migration order (do not invert)

1. **Enrollment grain (P3) before class-scoped fee items (P4).** A class-scoped `TermFeeItem` is only meaningful once the system can say which class a student belonged to in the target term.
2. **Fee schema (P4) before resolver (P5).** The resolver must not read half-migrated configuration.
3. **Resolver equivalence (P5) before generation cutover.** A green unit suite is not equivalence evidence.
4. **Generation cutover before snapshot capture (P6) for new rows.** New rows must capture names at creation; historical rows remain untouched.
5. **Deletion/audit hardening (P7) before production migration (P8).** A production migration must not create new records that an unguarded delete can destroy.
6. **`level` removal last.** Order: admission-number mapping decision → fee LEVEL/stage mapping → generation filters → import/export → search/list display → removal approval. Until then, `level` remains authoritative for live paths.
7. **`is_active` semantics first, not removal.** Audit every generation/filter path before changing what “inactive class” means. Do not remove the field.

### 9.2 What can proceed independently

- Read-only consumer tracing for admission numbers, class lists, invoice lists, booklets, and results.
- Synthetic-query work for tenant isolation and deletion exposure.
- Documentation and test strengthening that does not change behaviour.
- PostgreSQL setup for the existing Phase 0 harness, provided it is a synthetic database and not production.

### 9.3 What must wait for historical-data evidence

- Any statement about whether production data was lost.
- Any reconciliation write.
- Any backfill that would classify a student, stage, or price from current values.
- Any restore or production query.
- Any claim that a missing backup is unrecoverable.

---

## 10. Recovery investigation: precise conclusions

The following is a faithful summary of `docs/audit/RECOVERY_EVIDENCE_INVESTIGATION.md`. It is evidence, not authorization.

**Verified:**

1. Two SQL dumps survive in Git history, reachable through Dependabot branches and commit references; they are publicly accessible at branch and commit level.
2. Both are from 2026-09-09, plain SQL (not gzip), PostgreSQL 17.10, and stop at `fees.0019`.
3. Both contain zero fee categories, prices, invoices, line items, payments, receipts, students, scores, or results.
4. They expose two `pbkdf2_sha256` password hashes and two expired session rows.
5. The dumps were taken after `0017`/`0018`, which ran during a fresh migration before the first school existed in that environment.
6. The local SQLite database applied fees migrations through `0022` on an empty database.
7. Staging PostgreSQL applied the potentially destructive migrations before its first school was created.
8. `backup_20260922_082845.sql.gz` was not found in the locations examined; some locations remain inaccessible.
9. No restore was attempted and no deletion-policy or application-code change was made during the investigation.

**Unverified:**

- Whether Docker Compose or an external production environment ran the migrations against populated data.
- Whether a production database exists at all.
- Whether inaccessible volumes/paths contain the missing backup or populated data.
- Whether `0017`/`0018` ever ran against populated data anywhere.
- Whether any operator used a live hard-delete path after migration.

**What must not be claimed:**

- That production data was lost.
- That production data was not lost.
- That a restore can recover deleted fees or invoices.
- That the surviving dumps are a usable financial backup.
- That the exposed credentials have been rotated or the public dumps purged.
- That the missing backup is permanently unrecoverable.

**Interpretation:**

- The surviving dumps cannot restore records they do not contain.
- Staging's migration chronology is evidence about staging, not proof of production behavior.
- Actual production data loss remains unverified.
- Containment actions remain separate, unauthorized work.

---

## 11. Recommended next task

**Task:** Complete Phase 1 review and close the remaining P1 gaps without starting Phase 2.

**Prerequisites:**

- Review and approve the Phase 1 diff, including `students/0009_academicstage_normalized_unique.py`.
- Decide whether the school-admin class form must expose an active-stage selector in P1 or in a later P1 follow-up.
- Provide a non-production PostgreSQL environment for the functional unique constraint test.

**Acceptance criteria:**

- `git diff` review confirms only intended files changed.
- `makemigrations --check` and `manage.py check` pass.
- Targeted, `students`, and `school_admin` tests pass on SQLite.
- PostgreSQL migration + targeted tests pass, or the limitation is explicitly recorded as unverified.
- No stage backfill, no historical data mutation, and no fee/invoice behavior change.
- Dependency register and roadmap statuses are updated.

**Do not do next without approval:** stage backfill, classification fields, `ClassOffering`, `TermFeeItem`, resolver changes, deletion-policy changes, production migration, restore, credential rotation, or Git-history rewrite.
