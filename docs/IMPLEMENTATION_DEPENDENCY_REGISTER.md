# BUST-BASE — Implementation Dependency Register

**Status:** Phase 1 review register. Read-only evidence plus the bounded Phase 1 corrections recorded below.
**Date:** 2026-10-23
**Branch:** `feat/academic-structure-phase1`
**Baseline:** `8a1bdcc287826253ee51bf9d2e3619706ee15546`
**Roadmap:** [`docs/IMPLEMENTATION_ROADMAP.md`](IMPLEMENTATION_ROADMAP.md)

**Status values:** `complete`, `verified`, `partially verified`, `unverified`, `blocked`.
“Complete” means implemented and tested for the stated scope, not deployed.

> **Repository-state warning (updated 2026-10-26).** `AcademicStage` and its migration were uncommitted at task start (2026-10-23). They are now committed and the branch `feat/academic-structure-phase1` **is pushed to origin**; it is **not merged, not deployed, and not present in production**. The single-concept convergence work of 2026-10-26 (§2.6 of the roadmap) is on the same branch in later commits. This register records the working tree at review time, not a merged or deployed commit.

---

## 0. How to use this register

- Every row names an actual file and symbol. Line numbers are deliberately avoided where symbols are stable.
- “Consumers” means code that reads or writes the symbol, not every import.
- “Migration/backfill” states whether a schema change or data change is required. “None” means no migration for the proposed change.
- “Tests” names the existing or required test class; a test name is not evidence unless it was executed.
- “Risk” records data-loss or compatibility exposure. “None known” is not a guarantee.

---

## 1. Academic structure (P1)

| ID | File / symbol | Current behaviour | Proposed change | Direct consumers / downstream | Prerequisites | Migration / backfill | Tests / acceptance | Risk | Status | Evidence |
|---|---|---|---|---|---|---|---|---|---|---|
| AS-01 | `students/models.py` → `AcademicStage` | Tenant-scoped model with `name`, `display_order`, `is_active` | Keep; review and commit | `SchoolClass.academic_stage`; admin; tests | P1 approval | `students/0008_add_academic_stage.py` | Creation, ordering, uniqueness, cross-school tests | Committed locally; not deployed | **complete (SQLite)** | Model + migrations; 14 targeted tests pass on SQLite |
| AS-02 | `AcademicStage.school` (inherited `TenantScopedModel.school`) | Required FK to `core.School`; cascade on school delete | Keep | All stage queries; class validation | None | Already in 0008 | Same name in two schools allowed | School delete cascades stages | **verified** | `core/models.py:TenantScopedModel`; `test_academic_stage_unique_per_school` |
| AS-03 | `AcademicStage.name` | `CharField(100)`; `unique_together (school, name)` | Add normalized write and uniqueness policy | `__str__`; admin search; class ordering; future backfill | None | 0009 constraint | Exact/case/whitespace duplicate tests; bulk-write constraint test | Case/whitespace duplicates previously possible via ORM; `bulk_create` bypasses `save()` but is caught by the DB index | **complete (SQLite)** | `students/models.py:normalize_name`, `Meta.constraints`; `test_academic_stage_constraint_blocks_unnormalized_bulk_write` |
| AS-04 | `AcademicStage.display_order` | `PositiveIntegerField(default=0)` | Keep; used for ordering | `Meta.ordering`; class ordering; admin | None | None | Ordering test | Equal values tie-break by name | **verified** | `test_academic_stage_ordering` |
| AS-05 | `AcademicStage.is_active` | Boolean default true; no delete cascade | Keep; deactivation is archival | Admin; portal stage selector | None | None | Inactive still selectable when already assigned; not offered for new assignments | Portal rejects inactive stages for new assignments and preserves a currently assigned inactive stage on edit | **complete (SQLite)** | `test_inactive_stage_preserves_existing_class_links`; `test_create_class_rejects_inactive_stage`; `test_edit_class_preserves_assigned_inactive_stage` |
| AS-06 | `AcademicStage.clean()` | Case-insensitive duplicate check after trim; did not call `super().clean()` | Normalize name, call `super().clean()`, keep duplicate check | Admin ModelForm; `full_clean()` callers | None | None | `test_academic_stage_name_normalization` | ORM `create()` bypasses `clean()`; DB constraint now covers duplicates | **complete** | `students/models.py:clean` |
| AS-07 | `AcademicStage.save()` | No normalization | Collapse whitespace and trim on every save | All writes | None | None | `test_academic_stage_name_is_normalized_on_save` | `bulk_create` bypasses `save()` | **complete** | `students/models.py:save` |
| AS-08 | `AcademicStage.Meta.constraints` | None before this task; exact `unique_together` only | Add `UniqueConstraint(Lower(Trim('name')), 'school')` | Database; admin; all writes | 0009 migration approval | `students/0009_academicstage_normalized_unique.py` | Case/whitespace duplicate tests; bulk-write test; migration check | Fails on existing normalized duplicates; PostgreSQL **NOT VERIFIED** | **complete (SQLite)** | 0009; 14 targeted tests pass; PostgreSQL SQL generated offline only |
| AS-09 | `SchoolClass.academic_stage` | Nullable FK, `PROTECT`, `related_name='classes'`; authoritative classification. Required in the portal/admin workflow whenever the school has active stages | Keep; backfill designed in roadmap §2.6 (owner deferred implementation) | Admin; portal selector; `stage.classes`; future fee stage scope | Backfill migration approval | 0008; planned 0010 | Class creation/edit with stage; cross-school rejection | Nullable means legacy/imported classes can remain unclassified | **complete (model + portal + admin)** | `students/models.py`; `SchoolClassStageSelectorTests` |
| AS-10 | `SchoolClass.level` | **Transitional derived snapshot (2026-10-26)**: no user-facing input; written only when a stage is first assigned or changed (`_apply_class_level`, `SchoolClassAdminForm.save`); still read by admission-number mapping, fee LEVEL resolution, generation filters | Keep populated until every consumer migrates; removal subject to the §2.6 gate | `students/utils._map_class_to_header`; `fees/pricing._is_applicable`; `fees/generation.generate_invoices_for_level`; `data_import.importers`; class `Meta.ordering` | Removal gate items in roadmap §2.6 | None now | Selector + admin-form derivation tests | Removing it while consumers read it would break live paths; renames must not rewrite it | **transitional** | `school_admin/views/classes.py`; `students/admin.py` |
| AS-11 | `SchoolClass.is_active` | Boolean default true; used in invoice generation and lists | Keep; no removal | `fees/generation.generate_invoices_for_level`, `sync_level_invoices`, `generate_invoices_school_wide`, `sync_school_wide_invoices`; admin lists; `school_admin.views.invoices` | None | None | Class list/filter tests; fee generation tests | Inactive classes can still have historical enrollments | **verified** | `students/models.py:is_active`; `fees/generation.py` |
| AS-12 | `SchoolClass.Meta.ordering` | Changed from `['level','name']` to `['academic_stage__display_order','level','name']` | Keep if intended; document join/NULL ordering | All default `SchoolClass` querysets | Review | 0008 | `test_school_class_ordering_by_stage` | Adds JOIN; NULL stages sort first on SQLite and last on PostgreSQL by default; class list overrides ordering | **partially verified** | 0008; ordering test |
| AS-13 | `SchoolClass.clean()` / `_validate_academic_stage_school()` / `save()` | `clean()` only checked same-school stage; `save()` did not; invalid FK raised `DoesNotExist` | Share guard; enforce on ordinary writes; raise `ValidationError` for a missing stage | Admin, views, scripts using `create()`/`save()` | None | None | Cross-school tests; `test_school_class_missing_stage_rejected_on_save` | `bulk_create`/`update` still bypass; cross-table rule not DB-enforceable | **complete (ordinary ORM writes)** | `students/models.py`; targeted tests pass |
| AS-14 | `students/admin.py` → `AcademicStageAdmin` | Registered; list/filter/search/order | Keep | Admin UI | None | None | Admin smoke via system check | `search_fields` required for autocomplete; present | **verified** | `students/admin.py` |
| AS-15 | `students/admin.py` → `SchoolClassAdmin` | Stage-only form (`SchoolClassAdminForm`) since 2026-10-26: `level` excluded and derived; list/filter/search present stage only | Keep; converge ordering later | Admin class list/form | Roadmap §2.6 | None | `SchoolClassStageOnlyAdminFormTests` | Editing legacy classes via admin must not silently rewrite `level` when the stage is unchanged | **complete** | `students/admin.py`; new tests in `students/tests.py` |
| AS-16 | `students/migrations/0008_add_academic_stage.py` | Creates model, nullable FK, ordering/help changes | Retain; review before commit | DB schema | Migration approval | Applied only in local SQLite | `makemigrations --check` | Uncommitted; may not exist in any deployed DB | **partially verified** | Local `django_migrations`; `makemigrations --check` |
| AS-17 | `students/migrations/0009_academicstage_normalized_unique.py` | New functional unique constraint | Review; apply in non-production only | DB schema | Approval | Additive constraint | Case/whitespace duplicate tests; bulk-write test | Existing duplicates would fail migration; PostgreSQL **BLOCKED** (no credentials) | **complete (SQLite test DB); PostgreSQL NOT VERIFIED** | Migration file; tests; offline PostgreSQL SQL: `CREATE UNIQUE INDEX ... ((LOWER(TRIM("name"))), "school_id")` |
| AS-18 | `students/tests.py` → `AcademicStageTests` | 8 weak tests before; 14 after | Keep; PostgreSQL cases added later | CI | None | None | 14/14 pass | Tests do not cover admin UI or PostgreSQL | **complete (SQLite)** | `.venv/bin/python manage.py test students.tests.AcademicStageTests -v 2` |
| AS-19 | `school_admin/views/classes.py` → `ClassCreateView`, `ClassEditView` | Stage is the single classification field **and is required when the school has active stages**; unclassified save allowed only when no stages exist; legacy `level` derived via `_apply_class_level` on assignment-change only | Keep; stage-management UI decision still open | Class create/edit; admin portal | Owner decision 2026-10-26 | None | Updated `SchoolClassStageSelectorTests` | Stage renames do not rewrite the snapshot; explicit reassignment does | **complete (SQLite)** | `_stage_options`, `_resolve_academic_stage`, `_apply_class_level`; tests pass |
| AS-20 | `school_admin/templates/school_admin/class_form.html`, `class_list.html`, `class_detail.html`, `class_confirm_delete.html` | One stage field/column with an "Unclassified" state; **no Level input or column since 2026-10-26** | Keep | Admin portal | AS-19 | None | Template render assertions in selector tests | Imported/unclassified classes render "Unclassified"; legacy level remains visible in Django admin only via derived value | **complete** | Templates updated; tests pass |
| AS-21 | `students/utils.py` → `_map_class_to_header` | Unchanged: reads `school_class.level` first, then `name`, then initials/digits. With the transitional snapshot rule the level equals what the admin previously typed per class; with a compressed stage name (e.g. "JSS" instead of "JSS1") the name heuristic still applies | Do not change now; switching the keys to stage names is an explicit decision recorded at the §2.6 gate | `generate_admission_number`; student creation | Owner decision at removal gate | None | `test_admission_header_uses_stage_derived_level` | Changing it would alter admission numbers | **verified (current, governed)** | `students/utils.py`; new stability test in `students/tests.py` |
| AS-22 | `data_import/importers.py` → class import | Creates classes with `level` from `section`; **links an existing stage by exact (case-insensitive, whitespace-collapsed) name identity; unknown sections stay unclassified; never creates stages (2026-10-26)** | Keep; stage creation from imports remains prohibited without owner approval | CSV import | None for identity reuse | None | New `data_import` tests: identity reuse, no-match unclassified, school scoping | Stage rename later makes imported level diverge from stage name (transitional, governed) | **complete (SQLite)** | `ClassImporter._build_stage_map`; new tests pass |
| AS-23 | `data_import/management/commands/export_data.py` | Exports `section` from `level`; orders by `level,name` | Later: decide stage export at the §2.6 gate | Data export | Removal-gate item 3 | None | Export tests | No stage in export | **partially verified** | Command inspected |
| AS-24 | `school_admin/views/search.py` → class search API | Orders `SchoolClass` by `level,name` (display-only, unchanged); subtitle now prefers `academic_stage.name`, falling back to the legacy level for unclassified classes | Convert ordering at the §2.6 gate | Autocomplete | AS-19 | None | Selector tests; existing search tests | Subtitle no longer duplicates level and stage for classified classes | **complete** | `school_admin/views/search.py` |
| AS-25 | `fees/pricing.py` → `_is_applicable` | LEVEL match uses `school_class.level == price.level` | Keep until P4/P5; future stage scope must not infer | Fee resolution | PD-05 | None | Fee pricing tests | String equality remains fragile | **verified** | `fees/pricing.py` |
| AS-26 | `fees/generation.py` → `generate_invoices_for_level`, `sync_level_invoices` | Filters `SchoolClass.objects.filter(level=..., is_active=True)` | Keep until P4/P5 | Invoice generation | PD-05 | None | Fee generation tests | Level-based generation remains live | **verified** | `fees/generation.py` |
| AS-27 | `fees/generation.py` → `generate_invoices_for_class`, `generate_invoices_for_term` | Class helper does not filter `is_active`; term helper filters active students/enrollments, not class status | Audit and document intended semantics before P5 | Bulk generation | P5 | None | Generation filter tests | Inactive-class students may be billed | **partially verified** | `fees/generation.py` |
| AS-28 | `school_admin/views/invoices.py` → invoice list class filter | `SchoolClass.objects.filter(school=school, is_active=True)` | Keep; later align with generation semantics | Admin invoice list/CSV | P5 | None | Invoice list tests | UI and generation may disagree | **verified** | `school_admin/views/invoices.py` |
| AS-29 | Bulk/direct writes to `SchoolClass.academic_stage` | No production `bulk_create`, `bulk_update`, or `QuerySet.update` assigns a stage. The only stage writers are the class form (`create`/`save`) and Django admin (`full_clean` + `save`). | No change in Phase 1; add a manager/queryset guard or composite `(school_id, academic_stage_id)` FK if a bulk writer appears | Future importers, scripts, admin actions | None | None | Static grep; selector tests | A future bulk path could bypass tenant validation | **audited; no reachable gap** | `grep` across `*.py`; `data_import/importers.py` creates classes without a stage |
| AS-30 | PostgreSQL execution of `0009` | Local PG on `127.0.0.1:5433` requires a password; no DSN, no `psql`, Docker denied; documented dev credentials rejected | Run the §5.4 procedure on a disposable database | Migration confidence | PG credentials + disposable DB | 0009 | Positive/negative duplicate cases | Migration may fail on existing normalized duplicates | **blocked** | Roadmap §5.4; offline SQL generated only |
| AS-31 | School-admin `AcademicStage` management UI | None; stages are managed in Django admin | Defer; decide in P2/P4 whether it belongs in settings | Portal usability | Product decision | None | N/A | Admins cannot create stages in the portal | **out of scope (P1)** | `grep` templates/views |

---

## 2. Enrollment and class offerings (P2/P3)

| ID | File / symbol | Current behaviour | Proposed change | Direct consumers / downstream | Prerequisites | Migration / backfill | Tests / acceptance | Risk | Status | Evidence |
|---|---|---|---|---|---|---|---|---|---|---|
| EN-01 | `students/models.py` → `ClassEnrollment` | One row per `(student, session)`; `school_class`, `session`, `is_current` | Decide whether to add `enrolled_from_term` or a term-level model | Promotion, transfer, invoices, scores, booklets, portals | PD-03 | Possible nullable FK or new table | Session/school consistency tests | Unique `(student, session)` cannot represent mid-session class changes | **blocked (PD-03)** | Model + consumers |
| EN-02 | `ClassEnrollment.Meta.unique_together` | `('student','session')` | Keep or replace per PD-03 | All enrollment writes | PD-03 | Possible constraint change | One-placement tests | Changing it is a schema/data decision | **blocked** | `students/models.py` |
| EN-03 | `ClassEnrollment.save()` | Flips other `is_current` rows for the student, then saves | Add school/session consistency validation if PD-03 retains model | Promotion/transfer views | PD-03 | None | Cross-school enrollment tests | No validation that student/class/session share a school | **partially verified** | `students/models.py:save` |
| EN-04 | `school_admin/views/students.py` → `StudentCreateView`, `StudentEditView`, transfer/move paths | Creates enrollments with `school`, `student`, `school_class`, `session`; no explicit consistency check | Validate same-school/session | Enrollment history; invoice generation | PD-03 | None | Student create/transfer tests | Cross-school enrollment possible via crafted POST/ORM | **partially verified** | `school_admin/views/students.py` |
| EN-05 | `ClassOffering` (no symbol) | Does not exist | Define or reject with rationale | Future term-level offerings, fees, staffing | PD-03 | Unknown | Decision record | Cannot specify deletion semantics for a non-existent model | **blocked** | `grep` finds no symbol |
| EN-06 | `academics/models.py` → `ClassSubject` | Links subject to class; no session/term dimension | Keep for now; decide whether offerings need session | Subject assignment, score entry, booklets | PD-03 | Possible new model/field | Subject/class tests | Historical “which subject in which session” is implicit | **verified (current)** | `academics/models.py` |
| EN-07 | `academics/models.py` → `TeacherAssignment` | Has explicit `session` FK; unique `(teacher, subject, class, session)` | Keep; use as evidence that session scope is representable | Teacher portals, score entry | None | None | Assignment tests | No term dimension | **verified** | `academics/models.py` |

---

## 3. Student classification (P2)

| ID | File / symbol | Current behaviour | Proposed change | Direct consumers / downstream | Prerequisites | Migration / backfill | Tests / acceptance | Risk | Status | Evidence |
|---|---|---|---|---|---|---|---|---|---|---|
| CL-01 | `students/models.py` → `Student.student_type` | Live `NEW`/`RETURNING`; auto-flipped on registration payment | Retain during transition; new resolver must not rely on it | `fees/utils.resolve_student_type`; fee generation; admin | PD-02 | Later classification fields | Classification tests | Payment history currently changes classification | **verified (current)** | `students/models.py`; `school_admin/views/invoices.py` |
| CL-02 | `students/models.py` → `Student.registration_paid_term` | `SET_NULL` FK; used by resolver and auto-flip | Retain; do not use as sole classification evidence | `fees/utils.resolve_student_type`; payment confirmation | PD-02 | None | Payment tests | Historical value may be incomplete | **verified (current)** | `students/models.py` |
| CL-03 | `fees/utils.py` → `resolve_student_type` | New if no prior enrollment and no registration term; otherwise returning | Replace with explicit admission indicator + review queue | Pricing, generation, checkout | PD-02 | New fields + backfill/review | New intake/returning tests | Current logic infers from financial history | **verified** | `fees/utils.py` |
| CL-04 | `school_admin/views/invoices.py` → payment confirmation auto-flip | Sets `registration_paid_term` and `student_type='RETURNING'` on registration payment | Remove flip after PD-02; retain fields | Payment confirmation; classification | PD-02 | None | Payment does not change classification | Behavior change affects billing | **verified (current)** | `school_admin/views/invoices.py` |
| CL-05 | Planned `Student.is_new_intake_at_admission`, `classification_review_*` | Do not exist | Add per FEE plan §2.2 | Resolver, review UI, generation blocking | PD-02 | New migration | Checkbox default, review blocking | Not started | **blocked** | `docs/FEE_REDESIGN_PLAN.md` §2.2 |
| CL-06 | `fees/generation.py` → `generate_invoice_for_student` | Resolves type and generates without classification blocking | Add preflight/review blocking | Generation, checkout | PD-02 | None | Blocked generation tests | Ambiguous students can be billed | **verified (current)** | `fees/generation.py` |

---

## 4. Fee configuration and pricing (P4/P5)

| ID | File / symbol | Current behaviour | Proposed change | Direct consumers / downstream | Prerequisites | Migration / backfill | Tests / acceptance | Risk | Status | Evidence |
|---|---|---|---|---|---|---|---|---|---|---|
| FP-01 | `fees/models.py` → `FeeCategory` | Stable category with `billing_cycle`, `student_type`, `is_compulsory` | Retain; deactivate rather than delete referenced rows | FeePrice, overrides, invoices, inventory | PD-07 | None | Category tests | Delete cascades historical lines | **verified (current)** | `fees/models.py` |
| FP-02 | `fees/models.py` → `FeePrice` | Amount, term, scope, class/level, type, effective dates | Adapt to child of `TermFeeItem`; keep legacy during transition | Resolver, generation, admin, sync | PD-01, PD-06 | New schema + mapping | Scope/precedence/effective-date tests | Nullable uniqueness does not prevent duplicates; 0017 already deleted history | **verified (current)** | `fees/models.py`; `docs/audit/HISTORICAL_DATA_LOSS_REVIEW.md` |
| FP-03 | `fees/models.py` → `FeePriceOverride` | Student/category override with date range | Preserve as exceptional layer | Resolver | None | None | Override tests | Must remain above class scope | **verified** | `fees/models.py`; `fees/pricing.py:_get_active_override` |
| FP-04 | `fees/pricing.py` → `resolve_prices`, `_resolve_from_feeprice` | Two-stage precedence; cross-term fallback; one-time prior-session guard | Replace behind flag with exact-term resolver; measure equivalence | Generation, checkout, previews, dashboards | PD-01/PD-06; equivalence harness | None for code; P4 for schema | Pricing precedence tests | Price changes mid-year; silent fallback | **verified (current)** | `fees/pricing.py` |
| FP-05 | `fees/pricing.py` → `_is_applicable` | LEVEL exact string match; school-wide must have no class/level | Future stage scope; do not infer | Pricing | PD-05 | None | Scope tests | String mismatch silently misses prices | **verified** | `fees/pricing.py` |
| FP-06 | `fees/pricing.py` → `_is_first_term_of_session`, `_apply_christmas_fee_gate` | Drops Christmas fee outside first term; category-name gate | Remove after PD-01/PD-02; do not use names as rules | Pricing | PD-01/PD-02 | None | Christmas fee tests | Category-name coupling | **verified** | `fees/pricing.py` |
| FP-07 | `fees/generation.py` → `_is_one_time_already_billed` | Checks only earlier sessions | Replace with explicit scope enforcement | Pricing/generation | PD-01 | None | One-time tests | Can rebill in another term of same session | **verified** | `fees/generation.py` |
| FP-08 | `fees/generation.py` → `sync_class_invoices` | Deletes and rewrites line items on unpaid invoices | Remove from normal config workflows; preserve only behind approved path | Fee pricing views, admin actions | PD-07; AP-04 | None | No reprice test | Mutates invoice history | **verified** | `fees/generation.py` |
| FP-09 | `school_admin/views/fee_pricing.py` → `FeePricingCreateView`, `FeePricingUpdateView` | On save, generates invoices and syncs/re-prices | Remove generation/reprice side effects | Invoice generation | PD-07; P5 | None | Config save does not generate | Current behavior contradicts invariants | **verified** | `school_admin/views/fee_pricing.py` |
| FP-10 | Planned `TermFeeItem` | Does not exist | Add per FEE plan §2.3 | Resolver, generation, admin | PD-01/PD-05/PD-06 | New migration | Scope integrity tests | One-time term nullability unresolved | **blocked** | `docs/FEE_REDESIGN_PLAN.md` §2.3 |
| FP-11 | `fees/migrations/0017_cleanup_duplicate_one_time_prices.py` | Deleted non-current-term and class-scoped one-time prices; reverse noop | Do not reverse or rewrite; treat as historical evidence | Fee history | None | Already applied | Historical review | Data may be unrecoverable | **verified (code)** | `docs/audit/HISTORICAL_DATA_LOSS_REVIEW.md` §2.1 |
| FP-12 | `fees/migrations/0018_delete_school_fees_categories.py` | Deleted categories ending “School Fees”; reverse pass | Do not reverse; assess invoice/line-item damage | Invoice line items | None | Already applied | IC-8 | Cascade may have deleted line items | **verified (code)** | `docs/audit/HISTORICAL_DATA_LOSS_REVIEW.md` §2.2 |
| FP-13 | `fees/migrations/0022_backfill_fee_price_and_line_item_names.py` | Filled names from current categories | Do not re-run or re-null; PD-04 provenance | Historical display | PD-04 | Already applied | IC-9 | Historical names may be reconstructed, not original | **verified (code)** | `docs/audit/HISTORICAL_DATA_LOSS_REVIEW.md` §2.3 |

---

## 5. Financial records (P5/P6/P7)

| ID | File / symbol | Current behaviour | Proposed change | Direct consumers / downstream | Prerequisites | Migration / backfill | Tests / acceptance | Risk | Status | Evidence |
|---|---|---|---|---|---|---|---|---|---|---|
| FI-01 | `fees/models.py` → `Invoice` | `unique_together (school, student, term)`; total, generated_on | Preserve identity and uniqueness | Payments, receipts, booklets, portals | None | None | Invoice uniqueness tests | Generation race must rely on DB constraint | **verified** | `fees/models.py` |
| FI-02 | `fees/models.py` → `InvoiceLineItem` | `category` CASCADE; `item_name` snapshot; nullable `school`, `term`, `session` | Change category to `PROTECT` later; preserve snapshots | Invoice display, reconciliation | PD-07 | Later `AlterField` | Category delete blocked test | Category delete destroys history | **verified** | `fees/models.py`; `DELETION_INVENTORY` |
| FI-03 | `fees/models.py` → `Payment` | Status PENDING/CONFIRMED/FAILED; `recorded_by` CASCADE; invoice nullable | Preserve; later protect attribution/reversal | Receipts, allocations, balances | PD-07/PD-08 | Later FK change | Payment tests | Staff delete destroys payments | **verified** | `fees/models.py` |
| FI-04 | `fees/models.py` → `PaymentLineItem` | Allocation rows; category/term/session/invoice SET_NULL | Preserve; reconciliation | Balances, receipts | None | None | Allocation tests | Orphaned links possible after deletes | **verified** | `fees/models.py` |
| FI-05 | `fees/models.py` → `FeeReceipt` | OneToOne payment; cascade | Preserve; reversal policy | Parent/student receipts | PD-08 | None | Receipt integrity tests | Payment delete deletes receipt | **verified** | `fees/models.py` |
| FI-06 | `fees/models.py` → `WebhookLog` | Immutable provider log | Preserve | Paystack audit | None | None | Webhook tests | Do not mutate | **verified** | `fees/models.py` |
| FI-07 | `fees/models.py` → `InvoiceResetLog` | Audit of resets | Preserve; do not use reset as migration tool | Audit | None | None | Reset tests | Reset deletes financial records | **verified** | `fees/models.py`; `fees/reset.py` |
| FI-08 | `fees/reset.py` → `InvoiceResetService` | Bulk deletes invoices/payments/lines/receipts; writes log | Gate/remove from production image later | Admin actions, command | PD-07/PD-08 | None | Dry-run/confirmation tests | Destructive | **verified** | `docs/audit/DELETION_INVENTORY.md` D-13 |
| FI-09 | `fees/management/commands/clear_student_payment_history.py` | Deletes history with no dry-run/confirmation | Gate later | Operators | PD-07 | None | Confirmation test | Destructive | **verified** | `DELETION_INVENTORY` D-15 |
| FI-10 | `fees/paystack.py` (webhook/verify/receipt) | Webhook-first confirmation; lazy receipt | Preserve; no changes in P1 | Payments/receipts | None | None | Payment E2E tests | Do not alter idempotency | **partially verified** | Existing tests; not re-run in full yet |

---

## 6. Results and historical display (P6)

| ID | File / symbol | Current behaviour | Proposed change | Direct consumers / downstream | Prerequisites | Migration / backfill | Tests / acceptance | Risk | Status | Evidence |
|---|---|---|---|---|---|---|---|---|---|---|
| RS-01 | `academics/models.py` → `Score` | Score per student/subject/term; `entered_by` CASCADE | Preserve; later protect attribution | Results, booklets, rankings | PD-07 | Later FK change | Score tests | Staff delete destroys scores | **verified** | `academics/models.py` |
| RS-02 | `academics/models.py` → `TermResult` | Aggregate per student/term; no class snapshot | Preserve; decide whether to snapshot class/stage | Booklets, reports | PD-04 | Later snapshot columns | Result tests | Historical class shown from current enrollment | **verified** | `academics/models.py` |
| RS-03 | `academics/ranking.py` → `compute_positions`, `compute_term_summary` | Uses enrollment by term session | Preserve; snapshot decision later | Rankings, booklets | PD-03/PD-04 | None | Ranking tests | Class changes can alter historical context | **verified** | `academics/ranking.py` |
| RS-04 | `academics/booklet.py` → `build_booklet_context` | Reads enrollment by `term.session`; class from current `SchoolClass` | Add snapshot/fallback per PD-04 | Student/parent booklets, PDF | PD-04 | Later columns | Booklet render tests | Current name presented as historical | **verified** | `academics/booklet.py` |
| RS-05 | `students/views.py` → student results history | Class name from enrollment by session | Use snapshot/fallback later | Student portal | PD-04 | None | Portal tests | Same historical-display issue | **verified** | `students/views.py` |
| RS-06 | `school_admin/views/invoices.py` → invoice list | `current_class_name` Subquery from current enrollment | Later: historical class display for invoice | Admin invoice list/CSV | PD-04 | None | Invoice list tests | Invoice list shows current, not billed, class | **verified** | `school_admin/views/invoices.py` |
| RS-07 | `students/templates/students/result_booklet.html`, `results_history.html` | Render `school_class.name` / `class_name` | Add fallback/label later | Parent/student UI | PD-04 | None | Template tests | NULL snapshot could render blank | **verified (current)** | Templates inspected |

---

## 7. Tenant isolation, deletion, and audit (P7)

| ID | File / symbol | Current behaviour | Proposed change | Direct consumers / downstream | Prerequisites | Migration / backfill | Tests / acceptance | Risk | Status | Evidence |
|---|---|---|---|---|---|---|---|---|---|---|
| TN-01 | `core/models.py` → `TenantScopedModel`, `TenantScopedManager.for_school` | Every business model has `school`; manager helper | Keep; enforce scoping in views/services | All apps | None | None | Tenancy tests | Unscoped `objects` queries remain possible | **verified** | `core/models.py`; `tests/test_tenancy.py` |
| TN-02 | `students/models.py` → `SchoolClass` | `school` FK; stage cross-school guard | Keep | Classes, fees, academics | None | None | Cross-school stage tests | `bulk_create` bypass | **partially verified** | `students/models.py` |
| TN-03 | `fees/models.py` → `FeePrice`, `FeePriceOverride` | `school` FK; cross-school target possible via ORM | Validate same school in future schema | Pricing | P4 | Later validation/constraints | Cross-school price tests | Cross-school config possible | **verified (risk)** | `fees/models.py` |
| TN-04 | `academics/models.py` → `ClassSubject`, `TeacherAssignment`, `Score` | `school` FK; no cross-table school validation | Add service/model validation later | Academics | P7 | None | Cross-school tests | Crafted writes can mismatch | **verified (risk)** | `academics/models.py` |
| DL-01 | `school_admin/views/students.py` → `StudentDeleteView` | Hard-deletes student; warns on enrollments/guardians/invoices | Archive/deactivate or block | Financial/academic history | PD-07 | None | Delete refusal tests | Cascades invoices/payments/scores/results | **verified (risk)** | `DELETION_INVENTORY` D-01 |
| DL-02 | `school_admin/views/invoices.py` → `PaymentDeleteView` | Hard-deletes payment/receipt/allocations | Reversal record or block | Finance | PD-08 | None | Reversal tests | History loss | **verified (risk)** | `DELETION_INVENTORY` D-02 |
| DL-03 | `school_admin/views/staff.py` → `StaffDeleteView` | Superuser hard-deletes user; broad cascade | Deactivate or block when history exists | Payroll, scores, payments | PD-07 | Later FK changes | Staff delete tests | Destroys payments/scores | **verified (risk)** | `DELETION_INVENTORY` D-03 |
| DL-04 | `school_admin/views/fee_categories.py` → `FeeCategoryDeleteView` | Blocks only on `FeePrice` | Block on line items/overrides/allocations; `PROTECT` | Fee catalog | PD-07 | Later `AlterField` | Category delete tests | Line-item cascade | **verified (risk)** | `DELETION_INVENTORY` D-04 |
| DL-05 | `school_admin/views/classes.py` → `ClassDeleteView` | Warns on current enrollments, then deletes | Block if historical enrollments exist | Enrollment/academics/fees | PD-07 | None | Class delete tests | Cascades history | **verified (risk)** | `DELETION_INVENTORY` D-06 |
| DL-06 | `core/audit.py` → `WATCHED_MODELS` | Watches Payment, Invoice, Score, Payslip, SalaryDisbursement | Extend after `school` nullability handled | Audit | PD-07 | Later migration if needed | Audit tests | Most deletions unaudited | **verified (risk)** | `core/audit.py`; `DELETION_INVENTORY` §5 |
| DL-07 | `entrypoint.sh` | Runs `migrate --noinput` on container start | Freeze/gate per SEC decision | Deployment | SEC decision | None | Deploy test | Destructive migration can run unattended | **verified (risk)** | `DELETION_INVENTORY`; `HISTORICAL_DATA_LOSS_REVIEW` |
| DL-08 | `.github/workflows/deploy.yml` | Builds/pushes image; no deploy step | Require green CI/manual approval | Release | SEC decision | None | Workflow review | Image can ship with red tests | **verified (risk)** | Recovery report §4.7 |

---

## 8. Audit harness and evidence (P0)

| ID | File / symbol | Current behaviour | Proposed change | Direct consumers / downstream | Prerequisites | Migration / backfill | Tests / acceptance | Risk | Status | Evidence |
|---|---|---|---|---|---|---|---|---|---|---|
| AU-01 | `scripts/audit/phase0_queries.py` | Query catalogue Q-01…Q-10 + IC-8/9/10; draft/executed contract | Keep; run against authorized copy later | Evidence | DA-01 | None | 25 harness tests | Queries unexecuted on production | **verified (draft)** | `READINESS_REPORT` |
| AU-02 | `scripts/audit/schema_validator.py` | Validates identifiers against synthetic and local schema | Keep | Query safety | None | None | Validator tests | Proves identifiers, not semantics | **verified** | `READINESS_REPORT` |
| AU-03 | `scripts/audit/run_dialect_matrix.py` | SQLite matrix; PostgreSQL NOT RUN | Run on PostgreSQL in non-prod | Engine compatibility | PostgreSQL access | None | 13/13 SQLite; PostgreSQL pending | SQLite pass is not PostgreSQL proof | **partially verified** | `DIALECT_MATRIX.md` |
| AU-04 | `scripts/audit/synthetic_fixtures.py` | Deterministic 16-table/112-row fixture | Keep; expand for stage/offering when schema exists | Query tests | None | None | Fixture determinism tests | Synthetic schema has no FKs | **verified** | `SYNTHETIC_FIXTURES.md` |
| AU-05 | `docs/audit/DELETION_INVENTORY.md` | Static deletion inventory | Keep current; add runtime tests later | P7 | None | None | Review sign-off | Static only | **verified (static)** | Document |
| AU-06 | `docs/audit/RECOVERY_EVIDENCE_INVESTIGATION.md` | Read-only forensic report | Treat as evidence; do not execute incident response | Roadmap §10 | Owner authorization for actions | None | N/A | Findings include unverified production impact | **verified (evidence)** | Document |
| AU-07 | `docs/audit/HISTORICAL_DATA_LOSS_REVIEW.md` | Code-proven destructive migration analysis | Keep; use reconciliation SQL only on restored copy | P0/P8 | Authorized copy | None | N/A | Actual loss unverified | **verified (code)** | Document |

---

## 9. Phase 1 change log (this task)

| File | Change | Attribution | Test evidence |
|---|---|---|---|
| `students/models.py` | Added `Lower`/`Trim` import; `AcademicStage.normalize_name`, `clean()` super call + normalization, `save()` normalization, normalized `UniqueConstraint`; `SchoolClass._validate_academic_stage_school()` + `save()` guard | This task, on top of pre-existing AcademicStage work | 14 targeted tests; `students` 91 tests |
| `students/admin.py` | Restored `level` filter; added `list_select_related` | This task | `school_admin` suite passes (117 tests after closure review) |
| `students/tests.py` | Strengthened duplicate test; added case/whitespace/ORM tests; added cross-school `create()` test; renamed inactive test; imported `IntegrityError`/`transaction` | This task | 14 targeted tests |
| `students/migrations/0009_academicstage_normalized_unique.py` | New additive functional unique constraint | This task | Applied in SQLite test DB; `makemigrations --check` |
| `docs/IMPLEMENTATION_ROADMAP.md` | New authoritative roadmap | This task | Documentation |
| `docs/IMPLEMENTATION_DEPENDENCY_REGISTER.md` | New register | This task | Documentation |

**2026-10-26 single-convergence task (roadmap §2.6); same branch, separate commits:**

| File | Change | Attribution | Test evidence |
|---|---|---|---|
| `school_admin/views/classes.py` | `_school_has_active_stages`, `_apply_class_level`, `_stage_assignments_differ`; create/edit require a stage whenever active stages exist; legacy `level` derived on create and on stage assignment-change; POST `level` no longer read | 2026-10-26 convergence task | Updated `SchoolClassStageSelectorTests` |
| `school_admin/views/search.py` | Class autocomplete subtitle prefers the stage, falls back to the legacy level for unclassified classes | Same | Selector/search tests |
| `school_admin/templates/school_admin/class_form.html`, `class_list.html`, `class_detail.html`, `class_confirm_delete.html`, `_review_results.html` | Level input/column/row removed; one "Academic Stage" field/column with Unclassified state | Same | Template assertions in selector tests |
| `students/admin.py` | `SchoolClassAdminForm` (stage-only fields, level derivation), stage-only list/filter/search | Same | `SchoolClassStageOnlyAdminFormTests` |
| `students/tests.py` | New stage-only admin-form tests incl. `test_admission_header_uses_stage_derived_level` | Same | See §5.2 record |
| `data_import/importers.py` | `ClassImporter` links an existing stage by normalized-name identity; unknown sections stay unclassified; no stage creation | Same | New `data_import` tests |
| `data_import/tests.py` | Identity-reuse, no-match, and school-scoping tests | Same | See §5.2 record |
| `students/templates/admin/students/promote_students.html`, `lessons/templates/lessons/admin/class_form.html`, `inventory/templates/school_admin/inventory/item_form.html` | Display labels prefer the stage, fall back to the legacy level | Same | Rendered in respective suites |
| `docs/IMPLEMENTATION_ROADMAP.md`, `docs/IMPLEMENTATION_DEPENDENCY_REGISTER.md` | §2.6 replacement sequence, removal gate, owner decisions; refreshed Git-state statements; register rows AS-10/AS-15/AS-19/AS-20/AS-21/AS-22/AS-23/AS-24 | Same | Documentation |

**Pre-existing, not authored by this task:** `docs/FEE_REDESIGN_PLAN.md` modification; `students/models.py`, `students/admin.py`, `students/tests.py` AcademicStage work; `students/migrations/0008_add_academic_stage.py`; `docs/FINAL_GO_NOGO_CORRECTIONS.md`; `docs/PHASE0_READINESS_PLAN.md`; `docs/audit/*`; `fee_redesign.md`; `scripts/audit/*`.

---

## 10. Register maintenance rule

For every future implementation task:

1. Add or update the affected rows in the same change.
2. Record newly discovered consumers and changed prerequisites.
3. Record the exact tests run and their result; do not mark a row `complete` without execution.
4. Record migration implications, including whether the migration was applied anywhere.
5. If the change invalidates a roadmap assumption, update the roadmap and explain the correction.
6. Never delete a row merely because a symbol was renamed; mark it superseded and link the replacement.
