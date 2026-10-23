# BUST-BASE Fee-System Redesign — Implementation Prompt

You are working in the `yohananX/bust-base` repository, a Django-based school management platform used by a real school.

The authoritative redesign specification is in `FEE_REDESIGN_PLAN.md` at the repository root. Read that file completely before doing anything else. Treat it as the source of truth for the agreed business rules, target schema, constraints, migration strategy, financial invariants, and acceptance criteria.

Your task is to implement the fee-system redesign safely, incrementally, and with evidence from the actual codebase. This is not permission to perform a broad rewrite or to make assumptions about historical financial data.

## 1. Non-negotiable rules

1. **Preserve financial history.** Existing invoices, invoice line items, payments, receipts, payment allocations, provider references, statuses, balances, and relationships must not be deleted, reset, or silently rewritten.
2. Do not use destructive management commands or reset utilities as migration shortcuts.
3. Do not rewrite, squash, or delete existing migrations.
4. Do not modify production data during code inspection, planning, or testing.
5. Do not generate invoices automatically when students are created, classes change, or fee configurations are created or edited.
6. Saving fee configuration must never reprice existing invoices.
7. Invoice generation must be explicit, idempotent, concurrency-safe, and atomic per student invoice.
8. Invoice generation must not automatically send email or SMS notifications.
9. Do not use fee category names such as `Registration Form`, `Tuition Fee`, or `Christmas/End of Term Party Fee` to determine classification, applicability, pricing, or billing behavior.
10. Do not use payment history to determine whether a student is new intake.
11. Do not silently classify ambiguous legacy students. Flag them for review and block their invoice generation until resolved.
12. Do not silently borrow a price from another term.
13. Maintain tenant isolation across all models, queries, services, forms, views, and administrative actions.
14. Do not claim a test passed unless you actually ran it and observed the result.

If any requested change conflicts with an existing invariant or the current data model, stop and document the conflict before making a risky change.

## 2. Stage 0 — Repository reconnaissance and safety audit

Before modifying code:

- Read `FEE_REDESIGN_PLAN.md` completely.
- Read `AGENTS.md`, relevant project instructions, and applicable contributor documentation.
- Check `git status`, current branch, HEAD commit, and uncommitted changes. Do not discard or overwrite user work.
- Inspect the current model definitions, migrations, forms, views, services, templates, admin actions, management commands, API endpoints, signals, tasks, notifications, and tests involved in fee configuration, student enrollment, invoice generation, payment processing, and receipts.
- Trace every caller of the existing pricing resolver and invoice-generation functions.
- Search for all invoice repricing/synchronization paths and every automatic invoice-generation trigger.
- Search for hard-coded category-name rules and any remaining legacy pricing implementation.
- Inspect `ClassEnrollment`, `AcademicSession`, `Term`, `SchoolClass`, `Student`, `FeeCategory`, `FeePrice`, `FeePriceOverride`, `Invoice`, `InvoiceLineItem`, `Payment`, `PaymentLineItem`, and `FeeReceipt`.
- Inspect actual relationship deletion policies, database constraints, and effective-date semantics.
- Verify whether the existing session-level `ClassEnrollment` model can safely represent the first enrolled term. Examine registration, promotion, transfer, withdrawal, reenrollment, and class-change workflows. Do not assume that adding a nullable term FK is sufficient without checking these workflows.
- Inspect existing tests and test configuration before choosing how to run them.

First produce a concise but evidence-backed implementation assessment containing:

1. Existing behavior and relevant code locations.
2. A dependency map of the affected models, services, views, and callers.
3. Risks to historical financial records.
4. Data conflicts or ambiguities that cannot be resolved from code alone.
5. The proposed implementation sequence.
6. Tests required for each phase.
7. Any decisions that need human approval.

Do not stop after producing this assessment if the safe implementation path is clear. Continue with the first implementation phase below. If a critical ambiguity makes a change unsafe, implement only the independent safe work and explain the blocker.

## 3. Stage 1 — Establish the existing behavior

Before changing implementation:

- Run the narrow, relevant existing test suites first.
- Record their results, including failures that existed before your changes.
- Inspect migration state and identify the supported database engines.
- Determine how test data is created and whether tests can run without a production database.
- Inspect invoice, payment, receipt, and line-item relationships for destructive cascades or implicit mutation.
- Identify existing inconsistencies without correcting historical financial data as part of this redesign.

Do not run destructive data-clearing commands. Do not connect to or mutate the production database.

## 4. Stage 2 — Implement the academic structure

Implement the `AcademicStage` model and class relationship as specified in `FEE_REDESIGN_PLAN.md`.

Requirements:

- Each stage belongs to a school.
- Stage names are unique within a school according to a documented normalization policy.
- Classes reference a valid stage belonging to the same school.
- Schools can manage stage names, display order, and active status.
- Classes use a stage selector rather than relying on free-text level values.
- Existing class records and enrollment history are preserved.
- Keep the legacy `level` field during migration until all dependent consumers are migrated and data is reconciled.
- Backfill only mappings supported by existing data. Report ambiguous mappings rather than guessing.
- Prevent unsafe deletion of stages that have dependent records.

Add migrations and tests. Do not yet remove legacy fields or unrelated fee functionality.

## 5. Stage 3 — Implement student classification safely

Implement the explicit New intake admission indicator and legacy review workflow.

Requirements:

- The registration checkbox is unchecked by default.
- New intake is a classification decision, not a fee-payment event.
- A selected New intake indicator applies to the student's first enrolled term only.
- Later enrolled terms use returning-student classification.
- Students first enrolled in Term 2 or Term 3 are handled correctly.
- Registration Form payments do not change classification.
- Remove the old automatic student-type flip based on fee category names.
- Retain `Student.student_type` and `registration_paid_term` during the transition.
- Ambiguous legacy classifications require review and block affected invoice generation.
- Review completion must be explicit, authorized, and auditable.

Use the existing enrollment model if it can represent the necessary history safely. If the current one-class-per-session uniqueness rule prevents accurate term-level history for real workflows, stop and document the evidence before introducing a separate enrollment model. Do not silently overwrite or reinterpret historical enrollment records.

Add tests for new intake, returning students, mid-session admission, reenrollment, ambiguous legacy students, and payment events that must not affect classification.

## 6. Stage 4 — Implement scoped fee-item applicability and group-specific prices

Follow the target schema in `FEE_REDESIGN_PLAN.md`.

The target design separates:

- Fee-item identity (`FeeCategory`).
- Term- and scope-specific applicability (`TermFeeItem` or the exact approved equivalent).
- Group-specific prices (`FeePrice` adapted to reference the scoped item).

Pricing inheritance must be resolved independently for each item and student group:

`School-wide → Academic Stage → Class`

Requirements:

- Only the exact target term is eligible.
- No cross-term fallback.
- Class-level prices override matching inherited prices without suppressing unrelated inherited items.
- New class-level items can be added.
- Returning and new-intake prices inherit independently.
- Applicability and price existence are separate concepts.
- Missing prices for applicable items produce explicit validation errors.
- Same-scope conflicts are rejected rather than resolved by arbitrary primary-key ordering.
- Price replacement warnings identify the item, scope, group, and old/new amounts.
- Existing student-specific `FeePriceOverride` behavior must not be silently broken.
- Preserve relevant effective-date semantics after inspecting actual use.
- Do not drop legacy fields or historical price rows in the initial migration.

Use one canonical resolver shared by previews, validation, and invoice generation. Remove duplicated resolution behavior only after all callers are identified and migrated.

Add database constraints where practical, plus service-level validation for cross-table tenant consistency. Verify compatibility with the project's supported database engines.

## 7. Stage 5 — Resolve billing-cycle semantics before changing affected behavior

The meaning of existing `ONE_TIME` charges is not settled by the redesign document alone.

Inspect the current implementation, all callers, existing categories, and historical invoice line items. Determine what the school intends for each affected fee item.

Do not assume that all one-time items mean “once per student ever” or “once per session.” Do not preserve a faulty implementation simply because it already exists.

Propose and document the explicit billing-scope representation needed, such as:

- Once per student.
- Once per academic session.

Do not assign a scope to existing categories solely from their names. Do not remove the general `ONE_TIME` capability.

If the intended historical treatment cannot be established from repository evidence and available non-production data, leave affected one-time billing behavior gated or unchanged until approval. Continue implementing independent per-term fee behavior where safe.

The final one-time implementation must prevent duplicate charges within the chosen scope, including concurrent generation attempts.

## 8. Stage 6 — Replace invoice-generation workflows

Implement the generation behavior specified in `FEE_REDESIGN_PLAN.md`.

Requirements:

- An authorized administrator explicitly selects the target term and, optionally, classes or students.
- Validate target-term configuration, active enrollment, classification, and price completeness before generation.
- Block affected generation for unresolved student classification or missing required prices.
- Existing invoices are skipped regardless of whether they are unpaid, partially paid, paid, or pending.
- Never modify or recreate an existing invoice during ordinary generation.
- Preserve the existing uniqueness rule for `(school, student, term)`.
- Handle concurrent requests safely using database constraints, transactions, and appropriate integrity-conflict handling.
- Create each invoice and its line items atomically.
- A batch reports generated, skipped, and failed/blocked records distinctly, with actionable reasons.
- Invoice generation does not create payments or receipts.
- Invoice generation sends no email or SMS.
- Enforce tenant isolation for previews, validation, and generation.

Remove automatic invoice-generation triggers from student creation, class changes, and fee configuration saves. Remove or disconnect normal configuration workflows from invoice-repricing/synchronization functions.

Do not delete legacy functions until all callers have been traced and migrated. If a legacy function must remain for compatibility, make its behavior safe and clearly document its status.

## 9. Stage 7 — Preserve the financial ledger

Do not redesign financial models unless inspection proves a change is necessary for correctness or referential integrity.

Preserve:

- Existing invoice identities, terms, totals, and statuses.
- Existing line items, historical item names, amounts, billing-cycle values, and relationships.
- Payments, payment allocations, references, provider statuses, and receipts.
- Existing balances and the ability to reconcile them.
- Paystack verification and webhook idempotency.
- Manual payment recording.
- Tenant isolation.

Inspect the current `InvoiceLineItem.category` deletion behavior and every code path that can delete fee categories. Prevent a catalog-management operation from accidentally cascading into historical financial records.

Do not “fix” pre-existing financial discrepancies by rewriting history. Record the discrepancy, isolate it from migration-induced changes, and require approval for any separate remediation.

## 10. Stage 8 — Testing requirements

Add or update tests covering at least the following:

### Academic structure
- Stage creation and uniqueness within a school.
- Cross-school stage/class rejection.
- Class stage selection and historical safety.
- Stage archival/deletion restrictions.
- Legacy level backfill and ambiguous mappings.

### Classification
- New intake checkbox behavior and default.
- First enrollment in Term 1, Term 2, and Term 3.
- Subsequent-term returning classification.
- Registration Form payment does not flip student type.
- Ambiguous legacy students are blocked.
- Review completion is explicit and authorized.
- Promotion, transfer, withdrawal, and reenrollment behavior.

### Pricing
- School-wide, stage, and class precedence.
- Independent inheritance for returning and new-intake prices.
- Class-level item addition.
- Missing applicable prices.
- Exact-term-only resolution.
- Duplicate and conflicting configurations.
- Effective-date behavior.
- Student-specific override compatibility.
- Category rename independence.
- Same-scope replacement warning and inherited override distinction.
- Tenant isolation.

### Generation
- Explicit generation action.
- Configuration save does not generate or reprice invoices.
- Registration/class change does not generate invoices.
- Existing invoices are skipped and never repriced.
- Repeat generation is idempotent.
- Concurrent generation cannot create duplicates.
- Invoice/line-item atomicity on failure.
- Preflight errors and batch outcome reporting.
- No automatic notifications.
- Manual payment and Paystack workflows still work.
- Receipt and balance relationships remain valid.

### Migration and financial reconciliation
- Migrations apply to a realistic non-production copy.
- Historical records survive.
- Invoice totals match line-item totals.
- Payment allocation and outstanding-balance reconciliations remain consistent with the captured baseline.
- No unexpected deletions, reclassifications, or price mutations occur.

Run focused tests after each phase, then the broader relevant suite. Report exact commands and actual results. Do not claim complete test coverage if the full suite was not run.

## 11. Engineering standards

- Follow existing project conventions unless they conflict with the approved invariants.
- Keep changes focused and reviewable.
- Prefer explicit service functions over duplicated logic in views.
- Use transactions and database constraints for financial correctness.
- Avoid swallowing exceptions or silently falling back to arbitrary prices.
- Use clear, actionable validation messages.
- Add tests alongside each behavioral change.
- Do not introduce unrelated features, redesign unrelated screens, or perform opportunistic cleanup.
- Do not commit or push unless explicitly requested.
- Do not change the authoritative plan file to conceal unresolved decisions. If implementation evidence requires a plan revision, propose the exact change and explain why.

## 12. Final report

At the end of each implementation phase, report:

1. What changed, with file paths.
2. Migrations added and their safety characteristics.
3. Tests run and exact results.
4. Invariants verified.
5. Remaining blockers, ambiguities, and risks.
6. Whether financial history was touched (the expected answer is no, except for approved additive metadata/backfills that preserve all financial records).
7. The next safe phase.

Begin with Stage 0 reconnaissance, then proceed with the first safe implementation phase. Do not attempt the entire redesign in one large, unreviewable patch.