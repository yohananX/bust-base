# BUST-BASE fee-system redesign

Target schema and migration decision record · 22 October 2026

The decision record is now grounded in a fresh read of the repository at commit `8a1bdcc287826253ee51bf9d2e3619706ee15546` on `main`. The files inspected include `fees/models.py`, `fees/pricing.py`, `fees/generation.py`, `fees/utils.py`, `fees/visibility.py`, `students/models.py`, and `core/models.py`.

Scope: this is a code-backed schema proposal, not a production-data audit. I have not inspected the live database, run migrations, or changed the repository.

## 1. Finalized decisions

| Area                   | Decision                                                                                                                                                                                       |
| ---------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Academic structure     | Introduce school-managed `AcademicStage`; link each class to a stage.                                                                                                                          |
| Enrollment             | Extend `ClassEnrollment` if the existing one-class-per-session model can safely represent the first enrolled term; do not add a separate term-enrollment table without demonstrating the need. |
| Fee configuration      | Separate scoped fee-item applicability from group-specific prices.                                                                                                                             |
| Pricing inheritance    | School-wide → Academic Stage → Class, resolved independently for each fee item and student group.                                                                                              |
| Student classification | Explicit New intake checkbox; never inferred from fee payment or category name.                                                                                                                |
| Legacy classification  | Flag ambiguous students for review and block their invoice generation until resolved.                                                                                                          |
| Invoice generation     | Explicit administrator action; no generation as a side effect of registration or price configuration.                                                                                          |
| Notifications          | No automatic email or SMS during invoice generation.                                                                                                                                           |
| Existing invoices      | Immutable to fee-configuration changes; generation skips existing invoices.                                                                                                                    |
| Financial models       | Preserve existing invoice, line-item, payment, receipt and provider-reference records.                                                                                                         |
| Legacy columns         | Retain `Student.student_type` and `registration_paid_term` during the transition.                                                                                                              |
| Historical data        | No resets, destructive migration shortcuts, rewritten migrations or silent historical reclassification.                                                                                        |

One decision remains explicitly open: the intended meaning of a one-time fee. The implementation must not silently settle that policy based on the current code's behavior.

# 2. Target schema

## 2.1 Academic structure

School

Tenant boundary for every academic and fee configuration record.

AcademicStage

School-defined stage name, ordering and active status.

SchoolClass

Belongs to one AcademicStage; class identity remains stable across sessions.

Student + ClassEnrollment

Student profile, class for the session, and the term in which that enrollment begins.

### `AcademicStage` — new model

| Field           | Type / rule                         |
| --------------- | ----------------------------------- |
| `id`            | Primary key                         |
| `school_id`     | Required FK to School               |
| `name`          | Required stage name                 |
| `display_order` | Integer for ordering                |
| `is_active`     | Boolean, default true               |
| timestamps      | Follow existing project conventions |

Constraints

- Unique stage name within a school, using a defined case/whitespace normalization policy.
- A stage and its classes must belong to the same school.
- Referenced stages cannot be physically deleted without a separate, safe archival policy.
- Renaming a stage must not alter historical financial records.
- Default stages are setup defaults, not mandatory universal labels.

### `SchoolClass` — extend existing model

The current class model has `name`, a free-text `level`, and `is_active`; it is unique by `(school, name)`.

Target changes:

- Add a required `academic_stage` FK after a staged backfill.
- Replace `level` as the source of truth for stage membership.
- Keep the existing `level` field during migration; remove it only after all consumers have been migrated and data reconciled.
- Do not change class names or historical enrollment records as part of stage migration.

**Status update (2026-10-26 — `AcademicStage` replaces `Level`, one concept).** The staged sequence above is now governed in `docs/IMPLEMENTATION_ROADMAP.md` §2.6, which is the authoritative execution order. In brief: the class form and Django admin now present **only** the academic stage (stage required whenever the school has active stages configured); `level` survives solely as a derived transitional snapshot written on stage assignment/change, never a second editable field. The design (not yet implemented) migration `students.0010` makes the existing level values authoritative as stages 1:1 with the same names and granularity — no grouping or reinterpretation. `SchoolClass.level` may be removed only when the roadmap §2.6 gate is met: LEVEL fee scope converted with row-by-row review, an explicit admission-header policy on stage names, CSV import/export via stages, and remaining `order_by('level')` orderings converted.

The stage selector in class creation must list stages belonging to the current school. New stages are managed through the school's academic-structure settings.

## 2.2 Enrollment and admission classification

### `Student` — extend existing model

Add:

| Field                            | Type / rule                             |
| -------------------------------- | --------------------------------------- |
| `is_new_intake_at_admission`     | Boolean, default `False`                |
| `classification_review_required` | Boolean, default `False`                |
| `classification_review_reason`   | Nullable text or structured reason code |
| `classification_reviewed_at`     | Nullable timestamp                      |
| `classification_reviewed_by`     | Nullable FK to the reviewing user       |

The registration form's New intake checkbox writes `is_new_intake_at_admission`. The two legacy fields `student_type` and `registration_paid_term` remain temporarily but are not inputs to the new resolver.

The review fields allow a migration to distinguish a verified returning student from a legacy student whose status is not yet trustworthy. The review flag must not be cleared merely because a payment was recorded.

### `ClassEnrollment` — extend only where safe

The current model is unique by `(student, session)`, links to one `SchoolClass`, and has no term field. This means it currently represents one class assignment per student per session, not a complete term-by-term enrollment history.

Recommended minimal extension: add a nullable `enrolled_from_term` FK to `core.Term`, with validation that its session and school match the enrollment. It records the first term in which the student is enrolled for that session.

This supports the required first-enrolled-term classification while preserving the existing session-level model, provided the school maintains one class assignment per student per session.

If inspection of the registration, transfer, promotion and withdrawal workflows shows that students may have different class assignments within one session and those assignments must drive historical invoices, this extension alone is insufficient. In that case, a separate term-level enrollment model is required. Do not simulate term history by overwriting the existing enrollment.

### Classification function

The new resolver should conceptually take:

`student + target term + validated enrollment history`

and return `NEW`, `RETURNING`, or a classification error requiring review.

Rules:

1. If the student is marked for review, resolution fails until an authorized review resolves the ambiguity.
2. If the admission checkbox is false, use returning-student pricing by default.
3. If the checkbox is true and the target term is the first enrolled term, use new-intake pricing.
4. For subsequent enrolled terms, use returning-student pricing.
5. A student's first enrolled term can be Term 2 or Term 3.
6. Payment records and category names never alter classification.

For existing students, migration must not assume the admission checkbox's historical value from `student_type` or Registration Form payment. Where reliable evidence is missing, set the review flag.

## 2.3 Fee catalog, scoped applicability and prices

The current `FeeCategory` and `FeePrice` models combine several concepts. In the target design, a category remains the stable identity of a fee item, while separate records express where the item applies and what it costs.

### `FeeCategory` — retain

Keep the existing model and primary keys. Continue using it as the school-owned fee-item catalog, with fields such as `name`, `is_compulsory` and existing optional/compulsory behavior.

Requirements:

- Category names are display labels, not business rules.
- Renaming a category must not change applicability, classification or billing-cycle semantics.
- Retire categories by deactivating them rather than deleting referenced historical records.
- Review the existing `InvoiceLineItem.category` cascade behavior before enabling catalog deletion or changing its foreign-key policy.

### `TermFeeItem` — new model

This represents an item configured for a particular term and scope.

| Field                   | Type / rule                                 |
| ----------------------- | ------------------------------------------- |
| `id`                    | Primary key                                 |
| `school_id`             | Required tenant FK                          |
| `term_id`               | Required FK to the exact term               |
| `category_id`           | Required FK to `FeeCategory`                |
| `scope`                 | `SCHOOL_WIDE`, `ACADEMIC_STAGE`, or `CLASS` |
| `academic_stage_id`     | Nullable FK; populated only for stage scope |
| `school_class_id`       | Nullable FK; populated only for class scope |
| `applies_to_returning`  | Boolean                                     |
| `applies_to_new_intake` | Boolean                                     |
| `is_active`             | Boolean, default true                       |

`scope` and its target fields must satisfy a check constraint or equivalent database-enforced rule:

- `SCHOOL_WIDE`: no stage or class target.
- `ACADEMIC_STAGE`: exactly one stage target and no class target.
- `CLASS`: exactly one class target and no stage target.

The item must be associated with the same school as its term, category and scope target. These cross-table tenant checks also require service/model validation because an ordinary SQL check constraint cannot validate arbitrary related rows.

Applicability invariant: an item can apply to either student group, both groups, or neither group at that scope. An explicit configuration that applies to neither group should be rejected or deactivated, not silently treated as a billable item.

### `FeePrice` — adapt the existing model

The current model stores the amount, category, term, student type and scope/target fields. The target model makes the price a child of a scoped item:

| Field              | Type / rule                                  |
| ------------------ | -------------------------------------------- |
| `id`               | Primary key                                  |
| `term_fee_item_id` | Required FK to `TermFeeItem`                 |
| `student_group`    | `RETURNING` or `NEW_INTAKE`                  |
| `amount`           | Decimal, `max_digits=10`, `decimal_places=2` |
| `is_active`        | Boolean, default true                        |

This is the target shape. During migration, the existing `FeePrice` rows and fields remain available until data is mapped and the new resolver is verified. We should not simply drop `scope`, `level`, `school_class`, `term` or `student_type` in the first schema migration.

Why this separation matters: an item can apply to both groups while having different prices for each group, and a class can override one group's amount without accidentally overriding the other group's price.

### Effective-price resolution

For each target term, class, category and student group:

1. Determine whether the item is applicable at school, stage or class scope.
2. Consider only configuration for the exact target term.
3. Resolve the amount independently for the requested student group.
4. Use the most specific configured price for that item and group: class, then stage, then school-wide.
5. Preserve unrelated inherited items.
6. Add lower-scope items that do not exist at higher scopes.
7. Report an error if an item is applicable but no amount can be resolved.

A class-level returning price does not suppress an inherited new-intake price. An item defined only at class scope is not automatically applicable to every student group.

### Price uniqueness and validation

Target uniqueness:

- At most one active scoped item per `(school, term, category, scope, scope target)`.
- At most one active price per `(term_fee_item, student_group)`.

If historical rows or business requirements need multiple effective-date versions, the uniqueness design must account for non-overlapping date ranges. The current `FeePrice` model has `effective_from` and `effective_to`; the implementation must not silently discard that capability without determining whether administrators actually use it.

The UI must distinguish:

- Same-scope replacement: the administrator is replacing an existing amount for the same item and group at the same scope.
- Inherited override: the administrator is defining a more-specific amount that intentionally supersedes a higher-level price.

Before saving a replacement, show the term, fee item, scope/target, group and old/new amounts. Do not describe a valid class override as a duplicate configuration.

### Existing student-specific price overrides

`FeePriceOverride` currently provides student-specific amounts by category and date range. It is not part of the school → stage → class hierarchy, but the current resolver uses it.

The safe transition is to preserve this capability rather than silently break existing pricing. Treat it as an explicit exceptional layer above class-level resolution, validate tenant ownership and applicability, and retain the existing reason/date-range information. If the school no longer wants individual-student overrides, that is a separate product decision—not something to remove incidentally during this schema migration.

## 2.4 Financial records — preserve

Retain the existing models and identifiers for:

- `Invoice`
- `InvoiceLineItem`
- `Payment`
- `PaymentLineItem`
- `FeeReceipt`
- `WebhookLog`
- `InvoiceResetLog`
- `FeeValidationError`

Keep the existing uniqueness rule on invoices:

`UNIQUE(school, student, term)`

Do not redesign payment processing or receipts as part of the configuration migration.

`InvoiceLineItem` already stores a denormalized item name and amount. Preserve that snapshot behavior. A future configuration change must not change a previously issued invoice's total or its line items.

The current `InvoiceLineItem.category` uses `on_delete=models.CASCADE`; this is a material historical-risk finding. Before the redesign is released, verify whether any existing workflows can delete a fee category and thereby cascade into financial history. The migration must not delete categories or alter historical rows as a shortcut.

# 3. Constraints and invariants to enforce

These constraints are release requirements, not optional cleanup.

| Area                   | Enforced rule                                                                                                                  |
| ---------------------- | ------------------------------------------------------------------------------------------------------------------------------ |
| Tenant isolation       | A price, category, term, stage, class and student referenced by one configuration must belong to the same school.              |
| Academic structure     | Every active class has one valid stage from its own school.                                                                    |
| Scope integrity        | Every scoped item has exactly one valid scope target.                                                                          |
| Item identity          | A category's display name never drives pricing or eligibility.                                                                 |
| Price integrity        | At most one effective amount exists for each scoped item and student group.                                                    |
| Monetary values        | Amounts are valid non-negative decimals; explicit zero, if supported, is distinct from a missing price.                        |
| Term integrity         | New term-specific configuration belongs to the exact target term; no fallback to another term.                                 |
| Classification         | New-intake status derives from the explicit admission decision and enrollment history, not payment history.                    |
| Legacy ambiguity       | A student flagged for classification review cannot receive an automatically generated invoice until the ambiguity is resolved. |
| Configuration edits    | Saving a price never generates or reprices invoices.                                                                           |
| Invoice uniqueness     | The existing `(school, student, term)` uniqueness constraint remains.                                                          |
| Generation atomicity   | Invoice and line items are written in one transaction per student.                                                             |
| Existing invoices      | A generation retry skips existing invoices, regardless of payment status.                                                      |
| Notifications          | Generation sends no email/SMS.                                                                                                 |
| Financial preservation | Invoices, line items, payments, receipts, provider references and balances survive the migration unchanged.                    |

For generation, a preflight validation should identify the exact students/items with missing or conflicting prices. It must block affected generation rather than silently issuing an underpriced invoice. Existing invoices should be reported as skipped, not treated as errors and not rewritten.

The batch result should distinguish generated, skipped, and failed/blocked records. Concurrency safety must rely on the database uniqueness constraint and transaction handling, not only on a prior `exists()` check.

# 4. Remaining policy decision: one-time billing

This cannot safely be finalized from the model names alone. The current code has a concrete inconsistency between its stated intent and its behavior.

In `fees/models.py`, `FeeCategory.billing_cycle` has `ONE_TIME` and `PER_TERM`. The current `FeePrice.clean()` also requires one-time prices to have no term. In `fees/generation.py`, `_is_one_time_already_billed()` only looks for a matching line item in an earlier academic session. Therefore, it does not establish a universal once-ever rule, and it may allow the same one-time category to be billed again in another term of the same session. Separately, `fees/pricing.py` uses that helper during resolution and includes a hard-coded party-fee gate that must be removed.

The target schema should make the one-time policy explicit instead of preserving this ambiguity.

## Recommended target billing-cycle policy

Keep `PER_TERM` as a supported billing cycle. For `ONE_TIME`, introduce an explicit scope such as:

- `ONCE_PER_STUDENT` — once across the student's entire school history.
- `ONCE_PER_SESSION` — once per student per academic session.

The allowed scope must be selected intentionally for each one-time item. It must not be inferred from the category name.

Before choosing the default for existing items, inspect the current fee catalog, all historical invoice line items, and the school's intended treatment of registration and other one-time charges. Do not bulk-convert every existing `ONE_TIME` category to `ONCE_PER_STUDENT` based only on the label or current code.

For one-time items, invoice generation must check historical billed records within the configured scope. The resolver may identify a candidate item, but it should not be the sole enforcement point: the generation service must enforce the policy transactionally to prevent duplicate billing under concurrent requests.

This policy remains a release blocker for affected one-time items until the intended scope and historical treatment are verified. Per-term fees can proceed independently.

# 5. Migration plan

The migration should be additive first, with a controlled switch to the new resolver. The phases below preserve the financial baseline and keep legacy fields until the new workflow is proven.

1. Phase 0 — Establish the baseline
   - Capture the exact production/staging database identity and backup/restore procedure.
   - Record invoice counts and totals by term and status; line-item totals; payment counts and statuses; receipt counts and relationships; outstanding balances; fee configuration counts and conflicts.
   - Identify ambiguous student classifications, one-time fee usage, orphaned references, duplicate prices and missing term configurations.
   - Reconcile invoice totals against line items and balances against confirmed payments, accounting for the existing payment allocation model.
   - Do not alter production data during this audit.
2. Phase 1 — Add academic structure
   - Add `AcademicStage`.
   - Add nullable `SchoolClass.academic_stage_id`.
   - Backfill stages from existing class `level` values only where a reliable mapping exists. (2026-10-26: the reliable mapping is name identity — each distinct non-empty level value becomes/reuses a stage of the same name and granularity, per roadmap §2.6 the design is recorded but implementation was deferred by owner decision.)
   - Flag ambiguous mappings for review. (2026-10-26: empty or blank levels stay unclassified and are reported, never guessed.)
   - Keep `level` and existing enrollment fields intact.
   - Validate school ownership and class/stage consistency. (2026-10-26: done on ordinary ORM writes; portal and admin workflow converge on the stage field — see §2.1 status update.)
3. Phase 2 — Add classification support
   - Add the New intake admission indicator and review fields.
   - Add `ClassEnrollment.enrolled_from_term` if the enrollment workflow confirms the session-level model is sufficient.
   - Backfill enrollment start terms only where evidence is reliable.
   - Mark ambiguous legacy students for review.
   - Do not infer classification from Registration Form payments or category names.
4. Phase 3 — Add scoped configuration
   - Create `TermFeeItem` and the group-specific price relationship.
   - Map existing `FeePrice` rows into the new structure while preserving primary keys or a durable mapping for traceability.
   - Detect and resolve collisions, invalid scope targets, date-range conflicts and cross-school references.
   - Preserve existing `FeePriceOverride` behavior during the transition.
   - Keep legacy price fields and resolver available until reconciliation passes.
5. Phase 4 — Replace pricing and generation workflows
   - Implement one canonical resolver shared by previews, validation and generation.
   - Remove cross-term fallback and category-name-based party/onboarding rules.
   - Remove invoice generation from student registration/class changes and fee-price create/edit.
   - Remove configuration-triggered invoice sync/repricing paths from normal workflows.
   - Disable automatic generation notifications.
   - Add preflight validation, idempotent generation and per-student atomic writes.
6. Phase 5 — Verify and cut over
   - Run migrations and tests against a staging copy of real data.
   - Compare financial baselines before and after migration.
   - Test existing invoices and payment workflows end to end.
   - Keep the legacy columns until the new resolver has been verified in real workflows.
   - Do not release if unexplained financial differences or unresolved affected one-time billing policies remain.

### Migration safety rules

- Never rewrite or squash existing migrations as a shortcut.
- Never run invoice-reset or payment-history-clearing utilities to make the new schema fit.
- Do not bulk-delete or reprice existing invoices.
- Do not change payment, receipt or provider-reference records as part of the fee configuration migration.
- Use database transactions for data backfills where appropriate, and make large backfills restartable.
- Capture pre-migration and post-migration counts, totals and reconciliation differences.
- A failed migration or reconciliation must stop the rollout; it must not be “fixed” by resetting financial data.

# 6. Acceptance criteria

The implementation is ready for release only when these tests pass.

## Academic structure and classification

- A school can create, rename, reorder and deactivate custom academic stages.
- Classes select a stage belonging to their own school.
- Classes with existing records cannot be detached from their historical context through deletion.
- The New intake checkbox is unchecked by default and persists correctly.
- A student joining in Term 2 receives new-intake pricing for Term 2 only when the admission indicator is selected.
- Registration Form payments never change classification.
- An ambiguous legacy student's invoice generation is blocked until classification review is completed.
- Changing class or stage does not alter an issued invoice.

## Pricing and configuration

- School-wide, stage and class configuration resolve in the correct order.
- Returning and new-intake prices inherit independently.
- Class-specific items are added without suppressing unrelated inherited items.
- An item applicable to a group but missing its price causes a validation error.
- Another term's price is never used as a fallback.
- Same-scope replacement warnings show the relevant item, scope, group and old/new amounts.
- Category renames do not change fee eligibility or billing logic.
- Saving configuration creates no invoice, sends no notification and changes no existing invoice.
- Student-specific overrides continue to work during the transition.
- One-time items cannot be duplicated within their explicitly configured billing scope.

## Invoice generation and financial integrity

- Generation is an explicit administrator action with term and optional class/student selection.
- Incomplete required configuration blocks affected generation.
- Re-running generation does not duplicate or reprice existing invoices.
- Concurrent generation preserves invoice uniqueness and atomic invoice/line-item writes.
- Generated, skipped and failed records are reported separately.
- Manual payments, Paystack verification, payment allocations, receipts and outstanding balances continue to work.
- Invoice totals reconcile with their line items.
- Existing financial records and relationships match the pre-migration baseline, except for documented pre-existing inconsistencies that are not changed by this redesign.
- Tenant isolation is tested for configuration, preview, validation and generation.

# 7. What still requires repository or database evidence

The target direction is finalized, but these items cannot be responsibly marked as settled without further inspection.

| Open item                       | Evidence required                                                                    | Release impact                                                                             |
| ------------------------------- | ------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------ |
| One-time billing scope          | Historical line items, category configuration and school policy                      | Blocks affected one-time items                                                             |
| Enrollment extension safety     | Registration, promotion, transfer, withdrawal and class-change workflows             | Determines whether `ClassEnrollment` can be extended or a new term-level model is required |
| Existing pricing data           | Actual database rows, duplicates, effective-date ranges and term coverage            | Must be reconciled before configuration cutover                                            |
| Legacy classification           | Admission records, enrollment history and ambiguous student cases                    | Affected students blocked pending review                                                   |
| Historical deletion risk        | Category deletion workflows, foreign-key behavior and existing references            | Must be addressed before release                                                           |
| Existing payment reconciliation | Payment allocation and receipt relationships, including pre-existing inconsistencies | Financial baseline must reconcile                                                          |

Final implementation decision: proceed with the additive academic-structure and classification changes, then introduce scoped fee-item applicability and group-specific prices. Keep the existing financial ledger intact, and do not switch invoice generation until the new resolver, legacy-data reconciliation and one-time billing policy have passed their required checks.

The next engineering deliverable should be a file-by-file implementation plan and migration/test matrix, followed by small, independently verifiable code changes. No production migration or financial-data mutation should occur as part of finalizing this specification.