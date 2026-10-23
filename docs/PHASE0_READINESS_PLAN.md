# BUST-BASE — Phase 0 Readiness Plan

**Date:** 2026-10-22
**Repository:** `bust-base`, branch `main`, HEAD `8a1bdcc` — **working tree is dirty** (uncommitted changes in `students/models.py`, `students/admin.py`, `students/tests.py`, `docs/FEE_REDESIGN_PLAN.md`; untracked `students/migrations/0008_add_academic_stage.py`)
**Mode:** Read-only planning. No code, migration, schema, or database change was made.
**Supersedes:** the execution ordering in `docs/FINAL_GO_NOGO_CORRECTIONS.md` only where stated. Architecture decisions in `docs/FEE_REDESIGN_PLAN.md` are preserved.

> **Repository-state warning.** All code references in this plan are verified against the **working tree**, not against a clean commit. `AcademicStage` and its migration exist only as uncommitted/untracked work. They must not be assumed merged, deployed, or present in production. Any task that touches these files must preserve the existing uncommitted work.

---

## 0. Scope, sources, and reconciliation

### 0.1 Documents located and read

| Requested | Actual file | Role |
|---|---|---|
| `go/nogo.corrections.md` | **Not present.** Closest match: `docs/FINAL_GO_NOGO_CORRECTIONS.md` | Corrected migration constraints |
| "original migration audit report" | `docs/FEE_REDESIGN_PLAN.md` (target schema + migration decision record) | Architecture source of truth |
| Implementation prompt | `fee_redesign.md` (repository root) | Binding stage rules, non-negotiable invariants |
| Related | `docs/AUDIT_STATUS.md` (cites stale commit `ae56339`; treat claims as **[A]** until re-run), `docs/CONTEXT.md` | Current-state claims; live product behaviour |

No file named `go/nogo.corrections.md` exists in the repository. This plan treats `docs/FINAL_GO_NOGO_CORRECTIONS.md` as that document.

**Stage-number mapping.** `fee_redesign.md` uses Stage 0–8; `FEE_REDESIGN_PLAN.md` uses Phase 0–5. They do not align. This plan uses gates G0–G6 and refers to the `FEE_REDESIGN_PLAN.md` phase names. Where `fee_redesign.md` is cited, its stage number is written explicitly (e.g. "prompt Stage 3"). Do not assume the numbers match.

### 0.2 Evidence legend

Every statement below is tagged:

- **[V]** Verified in code or migrations at this commit.
- **[A]** Assumption — plausible but not verified against production.
- **[D]** Product/architecture decision required.
- **[R]** Recommendation by engineering.

### 0.3 Verified facts that change the plan

These are new findings from inspecting the repository. They are not a re-audit; they are corrections that affect task ordering.

| # | Finding | Evidence | Impact |
|---|---|---|---|
| V0 | Repository state is dirty: HEAD is `8a1bdcc`, but `students/models.py`, `students/admin.py`, `students/tests.py` and `docs/FEE_REDESIGN_PLAN.md` are modified, and `students/migrations/0008_add_academic_stage.py` is untracked. `AUDIT_STATUS.md` cites commit `ae56339`, which is not HEAD. | `git log -1`; `git status --short`; `git diff --stat` | No code state may be treated as merged or deployed. `AUDIT_STATUS.md` claims must be re-verified at the actual deployed commit. The untracked migration may not exist in any environment. |
| V1 | `AcademicStage` and `SchoolClass.academic_stage` **exist in the working tree**, but only as uncommitted/untracked work. | `students/models.py:9-52`; untracked `students/migrations/0008_add_academic_stage.py` | Phase 1 is partially drafted, not greenfield and not merged. "Rollback by dropping the table" is safe only while nothing is deployed or written. `fee_redesign.md` prompt Stage 2 still instructs implementation of this model. |
| V2 | `Student.student_type` and `registration_paid_term` **already exist and are live**. | `students/models.py:127-148`; migrations `0006`, `0007` | The legacy classification behaviour is already in production; it is not a future change. |
| V3 | `InvoiceLineItem.item_name` was **already backfilled from current category names** for all historical rows. | `fees/migrations/0022_...py:16-23` | Directly contradicts the "historical snapshots stay NULL" correction. Cannot be silently re-nulled. |
| V4 | `fees/migrations/0018` **deleted categories matching `School Fees$`**. `InvoiceLineItem.category` is `CASCADE`. | `0018_delete_school_fees_categories.py:18-22`; `fees/models.py:337-341` | Any historical line item that referenced those categories **would have been cascade-deleted**. Invoice totals may no longer equal the sum of line items. **Must be measured, not assumed.** |
| V5 | `fees/migrations/0017` deleted **all `FeePrice` rows outside the current term** and converted arbitrary per-class `ONE_TIME` rows into one school-wide row. | `0017_cleanup_duplicate_one_time_prices.py:26-59` | Historical pricing configuration has already been discarded; past prices may be unreconstructable. |
| V6 | Live admin views permit `Student.delete()` and `Payment.delete()`. | `school_admin/views/students.py:496-506`; `school_admin/views/invoices.py:493-507` | Deleting a student cascades invoices, payments, receipts, scores and results. This is a live historical-destruction path. |
| V7 | `Payment.recorded_by` and `Score.entered_by` are `on_delete=CASCADE`, not `SET_NULL`. | `fees/models.py:460-466`; `academics/models.py:196-201` | Deleting a staff user deletes payments and scores they recorded. The prior FK graph in `FINAL_GO_NOGO_CORRECTIONS.md` stated `SET_NULL` for `recorded_by`; that was incorrect. |
| V8 | `FeeCategoryDeleteView` blocks only when `FeePrice` exists, **not** when `InvoiceLineItem` exists. | `school_admin/views/fee_categories.py:89-95` | A category with historical line items but no current price can be deleted, cascading into financial history. |
| V9 | `fees/generation.py:186` deletes and rewrites all line items on unpaid invoices (`sync_class_invoices`). | `fees/generation.py:157-202` | Contradicts "existing invoices are immutable" and "do not reprice". |
| V10 | `fees/reset.py` and `clear_student_payment_history` bulk-delete payments, receipts, invoices and notifications. | `fees/reset.py:44-47`; `fees/management/commands/clear_student_payment_history.py:77-101` | Destructive utilities exist in-tree and must be gated before any migration. |
| V11 | `InvoiceLineItem.school` is nullable. Migration 0012 backfilled existing rows, but `generate_invoice_for_student` and `sync_class_invoices` still create new line items **without** `school`. | `fees/models.py:323-330`; `fees/generation.py:81-90, 189-197`; `fees/migrations/0012_backfill_invoice_payment_school.py:6-15` | Newer line items may have NULL school; tenant-integrity and cross-school audit queries must not treat NULL as automatically corrupt, but must count it. |
| V12 | `fees/visibility._is_first_term_of_session()` returns `True` whenever any term exists; it never compares term IDs. | `fees/visibility.py:46-51` | Christmas fee visibility and billing use different gates. Display/billing divergence. |
| V13 | The resolver still performs **cross-term fallback**, category-name gating, and a one-time guard that only inspects prior sessions. | `fees/pricing.py:128-201`; `fees/generation.py:10-19` | The target "no cross-term fallback" is a behaviour change that will alter prices unless equivalence is measured. |
| V14 | `FeePrice.clean()` forbids a term on `ONE_TIME` prices, but the proposed `TermFeeItem.term_id` is required. | `fees/models.py:166-170`; `FEE_REDESIGN_PLAN.md:150` | Schema-level incompatibility for one-time items. Blocks Gate 3 until decided. |
| V15 | `CONTEXT.md` states that paying Registration Form **flips** `student_type` to RETURNING, while `FEE_REDESIGN_PLAN.md` rule 6 and `fee_redesign.md` prompt Stage 3 require the flip to be removed. | `CONTEXT.md:172-180`; `FEE_REDESIGN_PLAN.md:123`; `fee_redesign.md:98-99` | Two approved-looking documents disagree. This is a product decision, not an engineering fix. |
| V16 | `CONTEXT.md` states one-time fees are "for life", while `FEE_REDESIGN_PLAN.md` leaves one-time scope explicitly open. | `CONTEXT.md:188-190`; `FEE_REDESIGN_PLAN.md:26, 270-291` | The one-time policy is partly pre-decided in prose but not in schema. Must be ratified. |
| V17 | No `ClassOffering` symbol exists anywhere in the repository or docs. | `grep -r ClassOffering` → no matches | Deletion behaviour for "new ClassOffering relationships" cannot be specified. Must be defined before Gate 3. |
| V18 | `AuditLog` watches only `Payment`, `Invoice`, `Score`, `Payslip`, `SalaryDisbursement`; it requires a non-null `school`. | `core/audit.py:26-32, 77-90` | A snapshot-correction audit cannot reuse `AuditLog` as-is for fee-configuration models, and cannot watch `InvoiceLineItem` while `school` is NULL. |
| V19 | `FeePrice.unique_together` includes nullable `school_class`, `level` and `term`. | `fees/models.py:141` | On PostgreSQL, `NULL` values are distinct in unique indexes, so this does not prevent duplicate school-wide/stage/one-time rows. Q-06 must count duplicates, not assume the constraint. |

### 0.4 Contradictions that are flagged, not resolved

1. **Snapshot policy vs. applied migration 0022** (V3). The corrected policy says historical snapshots stay NULL; the repository already contains a migration that filled them with current names. Do not "fix" this by nulling rows — that would erase the only remaining evidence of the backfill. Needs PD-04.
2. **Classification policy vs. live behaviour** (V15). Needs PD-02.
3. **One-time policy vs. prose** (V16). Needs PD-01.
4. **`ClassOffering` vs. repository** (V17). Needs PD-03.
5. **Invoice immutability vs. `sync_class_invoices`** (V9). Needs PD-07 and implementation approval.
6. **Document path drift.** `fee_redesign.md` names the specification as `FEE_REDESIGN_PLAN.md` "at the repository root"; the file is actually `docs/FEE_REDESIGN_PLAN.md`. The content is the same, but any automation that resolves the root path will fail. Correct the reference rather than duplicating the file.
7. **Stale commit reference.** `docs/AUDIT_STATUS.md` cites commit `ae56339` and a 708-test result, but HEAD is `8a1bdcc` and the working tree has uncommitted changes. Treat the 708-test claim and the "all resolved" table as unverified until re-run at the deployed commit.

---

## A. Dependency-ordered task matrix

Ordering rule: no task may begin before every task in its `Depends on` column is complete. "Now?" answers only one question: *can this start today without production access and without implementation authorization?*

### A.1 Workstream R — Readiness artefacts (no production access)

| ID | Task | Class | Depends on | Evidence / deliverable | Acceptance criteria | Owner | Blocks | Now? |
|---|---|---|---|---|---|---|---|---|
| R-01 | Author the Phase 0 query catalogue: every Q-01…Q-10 plus IC-8/IC-9/IC-10 in both ORM and raw SQL form, in a read-only command with `--print-sql` and no execution path | Readiness | — | `scripts/audit/phase0_queries.py` + `docs/audit/QUERY_SPEC.md` | Each query has a named ID, purpose, expected grain, and expected output columns; the module contains no `INSERT/UPDATE/DELETE`; a CI check rejects writes | Backend engineer | Gate 0 | **Yes** |
| R-02 | Build schema-identifier validator: introspect tables/columns at the target commit and fail on any unknown identifier used by R-01 | Readiness | R-01 | Validator module + report | Every table/column resolves; unknown identifiers produce a non-zero exit and a printed diff; runs against SQLite and PostgreSQL | Backend engineer | Gate 0 | **Yes** |
| R-03 | Build dialect matrix runner: SQLite (dev) + ephemeral PostgreSQL at a pinned, documented version; re-run at the DA-00-confirmed version later | Readiness | R-02 | CI job + result matrix | Same query returns same columns and row counts on both engines for the synthetic dataset; documented engine-specific differences (NULL ordering, regex, JSON, `NULLS FIRST`) | Backend engineer | Gate 0 | **Yes** |
| R-04 | Build deterministic synthetic dataset covering 3 scopes × 3 student types × per-term/one-time × effective dates × cross-school × NULL snapshots | Readiness | — | Fixture/seed module + expected-row manifest | Seed is idempotent; expected counts documented; covers every acceptance criterion in FEE_REDESIGN_PLAN §6 | Backend engineer | R-06, R-10 | **Yes** |
| R-05 | Specify the snapshot policy, including a provenance marker for data already written by migration 0022 | Readiness + decision input | PD-04 | `docs/SNAPSHOT_POLICY.md` | Defines new-row capture, legacy NULL policy, fallback rendering, correction workflow, and handling of 0022 rows; reviewed by school admin | Backend engineer + PO | IM-01, IM-10 | Draft **yes**; final **no** |
| R-06 | Build resolver-equivalence harness: compare legacy `resolve_prices` against the proposed resolver per `(school, student, class, term, category, group)` | Readiness | R-04, IM-04 design | Comparison report format + runner | Deterministic diff report; classifies each difference as expected/regression; no production execution | Backend engineer | Gate 3, Gate 4 | **Yes** (against synthetic data) |
| R-07 | Produce a deletion-path inventory: every `.delete()` reachable from a view or command, with cascade impact | Readiness | — | `docs/DELETION_INVENTORY.md` + a regression test list | Every path in `fees`, `students`, `academics`, `school_admin`, `payroll` enumerated with affected models; V4–V10 confirmed or refuted | Backend engineer | IM-06, Gate 0 | **Yes** |
| R-08 | Specify containment for destructive utilities (`fees/reset.py`, `clear_student_payment_history`) | Readiness | R-07 | Containment spec | Defines removal vs. hard-gate (environment check, explicit flag, secondary confirmation, audit row); no implementation yet | Engineering lead | IM-06, Gate 4 | **Yes** |
| R-09 | Write the `ClassOffering` / enrollment specification request | Readiness | PD-03 | One-page decision brief | States whether the term means `TermFeeItem`, a new class×session offering, or nothing; defines FK and deletion semantics | Engineering lead | Gate 3 | Draft **yes**; closure **no** |
| R-10 | Produce the file-by-file migration/test matrix | Readiness | PD-01, PD-02, PD-03, R-05 | Matrix table: file, change, migration, test, rollback | Every changed file mapped to at least one test and one rollback step; reviewed by engineering lead | Backend engineer | IM-01…IM-10 | **Partially** |
| R-11 | Define the evidence-pack format: query text, engine/version, row counts, checksums, operator, timestamp, PII handling | Readiness | — | Template + storage location | Reproducible pack; hashes; retention period; access list | Engineering lead + Security | DA-05 | **Yes** |
| R-12 | Confirm deployment topology and database engine from configuration (not production) | Readiness | — | Short note: engine, version, hosting, backup tooling | Cites `requirements.txt`, `settings.py`, `Dockerfile`, `docker-compose.yml`, `docs/DEPLOYMENT.md`; marks anything unconfirmed as **[A]** | Backend engineer | DA-00 | **Yes** |
| R-13 | Reconcile the uncommitted academic-stage work: review the diff, confirm model/migration consistency, and decide keep/amend/revert **without discarding user work** | Readiness | — | Diff review note + migration-state check | `makemigrations --check` reports no missing migration; the untracked migration matches the model; the decision is recorded; no file is overwritten | Engineering lead | G1 | **Yes** (review only; commit needs AP-01) |

### A.2 Workstream DA — Data audit (requires read-only production-derived access)

| ID | Task | Class | Depends on | Evidence / deliverable | Acceptance criteria | Owner | Blocks | Now? |
|---|---|---|---|---|---|---|---|---|
| DA-00 | Confirm production engine, major/minor version, collation, and timezone | Data audit | R-12 | Signed engine-confirmation note | Version recorded; dialect matrix (R-03) re-run at that version | DBA / ops | DA-02, DA-03 | **No** |
| DA-01 | Provision read-only access to a restored production copy (replica or snapshot), least-privilege role, statement timeout, no write grants | Data audit | DA-00, AP-03 | Access record + role grant list | Role has `SELECT` only; `default_transaction_read_only=on`; timeout set; access logged | DBA / Security | DA-03 | **No** |
| DA-02 | Dry-run every query on a schema-only clone at the deployed commit | Data audit | R-01, R-02, R-03, DA-01 | Dry-run report | Every query parses and executes; zero unknown identifiers; all runtime < timeout | Backend engineer | DA-03 | **No** |
| DA-03 | Execute Q-01…Q-10 and capture results | Data audit | DA-02 | Evidence pack per R-11 | Every query ID present; results hashed; anomalies recorded; no query marked passed without its output | Backend engineer + reviewer | Gate 0 | **No** |
| DA-04 | Execute the seven integrity checks (§C.3) | Data audit | DA-02 | Evidence pack | Each check returns a pass/fail with counts and sample IDs | Backend engineer | Gate 0 | **No** |
| DA-05 | Execute the three newly required checks: IC-8 (historical loss from migrations 0017/0018), IC-9 (snapshot provenance), and IC-10 (live deletion exposure) | Data audit | DA-02 | Evidence pack | Impact quantified per school, term, and category; unexplained gaps listed | Backend engineer | Gate 0, PD-07 | **No** |
| DA-06 | Triage discrepancies into: pre-existing, migration-caused, or measurement error | Data audit | DA-03, DA-04, DA-05 | Triage register | Every discrepancy has an owner, a category, and a decision reference; none silently accepted | Engineering lead + PO | Gate 0 | **No** |

### A.3 Workstream PD — Product and architecture decisions

| ID | Task | Class | Depends on | Evidence / deliverable | Acceptance criteria | Owner | Blocks | Now? |
|---|---|---|---|---|---|---|---|---|
| PD-01 | Decide one-time billing semantics and its interaction with term/session invoicing | Product decision | DA-03, DA-04 | Signed decision record | Explicit scope per category; explicit `TermFeeItem.term` nullability consequence; supersedes the CONTEXT/PLAN conflict | Product owner | IM-02, IM-04, Gate 3 | **No** (needs audit evidence) |
| PD-02 | Decide the classification source of truth and the fate of the live auto-flip | Product decision | DA-03, DA-04 | Signed decision record | States whether Registration payment may change classification; defines review queue and blocking rule | Product owner + school admin | IM-07, Gate 2 | **No** |
| PD-03 | Define enrollment and "class offering" semantics | Product decision / architecture | R-09, DA-03 | Signed decision record + FK specification | Names the model, its grain, and its delete behaviour; resolves V17 | Product owner + engineering lead | IM-08, Gate 3 | **No** |
| PD-04 | Decide treatment of historical snapshots, including rows already backfilled by migration 0022 | Product decision | DA-03, DA-05 | Signed decision record | Chooses NULL-with-fallback, provenance-marked values, or admin verification; defines booklet wording | Product owner + school admin | IM-01, IM-10 | **No** |
| PD-05 | Approve the LEVEL-scope mapping workflow and per-row approval rule | Product decision | DA-03, DA-04 | Signed decision record | No bulk approval; evidence requirements; who may approve | Product owner + school admin | IM-03, Gate 3 | **No** |
| PD-06 | Decide whether `effective_from`/`effective_to` remain supported | Product decision | DA-03 | Signed decision record | If retained, uniqueness and resolver rules updated; if retired, migration of existing date ranges defined | Product owner | IM-02, IM-04 | **No** |
| PD-07 | Decide category and record lifecycle: deactivate-only vs. delete | Product decision | R-07, DA-05 | Signed decision record | Defines permitted deletion for category, class, student, payment, user; aligns with V6–V8 | Product owner + school admin | IM-05, IM-06 | **No** |
| PD-08 | Decide payment reversal and invoice correction policy | Product decision | R-07, DA-04 | Signed decision record | Reversal record vs. delete; credit-note rule; receipt treatment | Product owner + finance | IM-06, Gate 4 | **No** |

### A.4 Workstream IM — Implementation (requires Gate approval)

| ID | Task | Class | Depends on | Evidence / deliverable | Acceptance criteria | Owner | Blocks | Now? |
|---|---|---|---|---|---|---|---|---|
| IM-01 | Snapshot columns and safe rendering: nullable historical snapshots, capture at creation, `COALESCE` fallback in booklets | Implementation | PD-04, R-05, AP-02 | Migration + templates + tests | New rows capture names; historical rows may be NULL; booklet renders without error and labels fallback | Backend engineer | Gate 4 | **No** |
| IM-02 | `TermFeeItem` + child price schema, including one-time term nullability per PD-01 | Implementation | PD-01, PD-06, AP-02 | Migration + model tests | Scope check constraint enforced; cross-school validation; one-time model matches PD-01 | Backend engineer | Gate 3 | **No** |
| IM-03 | LEVEL mapping review queue and per-row approval UI | Implementation | PD-05, DA-04 | Model + admin views + tests | One review item per legacy LEVEL row; no bulk approve; approval writes an audit record | Backend engineer | Gate 3 | **No** |
| IM-04 | Dual resolver behind a feature flag, with equivalence reporting | Implementation | R-06, PD-01, PD-06, AP-02 | Resolver + flag + report endpoint | Legacy remains default; new resolver selectable per school; diff report available; no silent fallback | Backend engineer | Gate 4 | **No** |
| IM-05 | Change `InvoiceLineItem.category` to `PROTECT` and add pre-flight guard | Implementation | PD-07, DA-05, AP-04 | Migration + guard test | Deletion of a referenced category raises `ProtectedError`; pre-flight counts reported | Backend engineer | Gate 4 | **No** |
| IM-06 | Gate destructive paths: student delete, payment delete, staff delete, category delete, reset utilities | Implementation | R-07, R-08, PD-07, PD-08, AP-04 | View/command changes + tests | Referenced records cannot be deleted; deactivation replaces deletion; destructive commands refuse to run outside an explicit maintenance mode | Backend engineer | Gate 4 | **No** |
| IM-07 | Classification fields and review queue | Implementation | PD-02, AP-01 | Migration + resolver + tests | Review flag blocks generation; payment does not clear the flag; checkbox persists | Backend engineer | Gate 3 | **No** |
| IM-08 | Enrollment term field or replacement model per PD-03 | Implementation | PD-03, AP-01 | Migration + validation tests | Session/school consistency enforced; no overwriting of history | Backend engineer | Gate 3 | **No** |
| IM-09 | Generation workflow: explicit action, preflight, idempotency, atomicity, no notifications | Implementation | IM-02, IM-04, IM-07, AP-04 | Service + views + tests | Re-run skips existing invoices; blocked students reported; one transaction per student; no email/SMS | Backend engineer | Gate 5 | **No** |
| IM-10 | Snapshot correction workflow and audit | Implementation | PD-04, R-05, AP-04 | Model/view + audit tests | Correction requires admin role, reason, old/new values; immutable audit row; no signal or command can bypass | Backend engineer | Gate 5 | **No** |
| IM-11 | Full regression suite and financial-baseline assertion tests | Implementation | IM-01…IM-10 | Test run + baseline report | All existing tests pass; new tests cover every FEE_REDESIGN_PLAN §6 criterion; baseline diff = 0 or documented | Backend engineer | Gate 5 | **No** |

### A.5 Workstream AP — Approvals

| ID | Task | Class | Depends on | Evidence / deliverable | Acceptance criteria | Owner | Blocks | Now? |
|---|---|---|---|---|---|---|---|---|
| AP-01 | Approve implementation of academic-structure and classification work | Approval | PD-02, PD-03, R-10 | Written approval | Named approver, date, scope, explicit exclusions | Product owner + engineering lead | IM-07, IM-08 | **No** |
| AP-02 | Approve implementation of scoped fee configuration and dual resolver | Approval | PD-01, PD-05, PD-06, R-10 | Written approval | Scope limited to schema + flag-off resolver; no production data change | Product owner + engineering lead | IM-01…IM-04 | **No** |
| AP-03 | Authorize read-only production-derived audit access | Approval | DA-00, R-11 | Written authorization | Names environment, role, time window, data-handling rules | Product owner + Security | DA-01 | **No** |
| AP-04 | Authorize production data migration | Approval | Gate 0 complete, PD-01…PD-08, IM-11 | Written authorization | Separate from AP-02; names migration window, backup, rollback owner | Product owner + engineering lead + DBA | Gate 5 | **No** |
| AP-05 | Authorize resolver cutover in production | Approval | Gate 4 evidence, IM-11 | Written authorization | Separate from AP-04; names observation window and abort threshold | Product owner + engineering lead | Gate 5 | **No** |

### A.6 Critical path

```
R-01 → R-02 → R-03 ─┐
R-04 ───────────────┼→ R-06 ──────────────┐
R-07 → R-08 ────────┘                    │
R-12 → DA-00 → AP-03 → DA-01 → DA-02 → DA-03/04/05 → DA-06 → Gate 0
                                              │
                        PD-01/02/03/04/05/06/07/08
                                              │
                        AP-01 / AP-02 → IM-01…IM-08 → Gate 3/4
                                              │
                        IM-09/10/11 → AP-04 → production migration → AP-05
```

### A.7 Genuinely independent tasks (can start today)

These require **no** product decision and **no** production-data audit:

| Task | Why independent |
|---|---|
| R-01 | Writes query definitions; does not execute them |
| R-02 | Compares identifiers to the local schema |
| R-03 | Uses synthetic data and a pinned engine |
| R-04 | Synthetic fixtures only |
| R-07 | Static and local-runtime deletion inventory |
| R-08 | Containment specification |
| R-11 | Evidence-template design |
| R-12 | Reads repository configuration, not production |
| R-13 | Reviews existing uncommitted work read-only |

**Not independent:** R-05 (needs PD-04), R-06 (needs the IM-04 design and R-04), R-09 (needs PD-03), R-10 (needs PD-01/02/03 and R-05).

---

## B. Product decisions

### PD-01 — One-time billing and session/term invoicing

**Why it is unresolved.** The code treats `ONE_TIME` inconsistently:

- `FeePrice.clean()` forbids a term on a one-time price [V14].
- `_is_one_time_already_billed()` only checks **earlier sessions**, so a one-time fee can be billed again in another term of the same session [V13].
- `CONTEXT.md` says onboarding one-time fees are "for life" [V16].
- `FEE_REDESIGN_PLAN.md` says the scope is open [V16].
- The Christmas fee behaves as once-per-session, first-term-only — a third pattern.

**Alternatives**

| Option | Meaning | Schema consequence |
|---|---|---|
| A. `ONCE_PER_STUDENT` | Billed at most once across all history | One-time item needs no term; enforcement queries all prior line items |
| B. `ONCE_PER_SESSION` | Billed at most once per session | Item needs session semantics; first-term rule separate |
| C. `ONCE_PER_TERM` (explicit) | Billed once in a named term | `TermFeeItem.term` required; conflicts with current `FeePrice.clean()` |
| D. Per-item configurable scope (recommended target) | Each one-time category declares its scope | Requires a new field and a migration of existing categories |

**Affected models/workflows.** `FeeCategory.billing_cycle`, `FeePrice.term`, proposed `TermFeeItem.term`, `fees/generation._is_one_time_already_billed`, `fees/pricing`, invoice generation, Apply-Payment UI, Christmas fee gate.

**Consequence of postponing.** `TermFeeItem` cannot be finalised because its `term_id` nullability depends on this decision. Generation cutover and one-time fee correctness remain blocked. Per-term fees can proceed independently.

**Do not decide by inference.** The current code's prior-session-only behaviour is not evidence of intended policy.

---

### PD-02 — Classification source of truth

**Why it is unresolved.** `CONTEXT.md` documents an auto-flip from Registration Form payment; `FEE_REDESIGN_PLAN.md` rule 6 forbids payment-driven classification [V15]. Both are presented as decisions.

**Alternatives**

| Option | Behaviour | Risk |
|---|---|---|
| A. Explicit admission flag only | Classification never changes from payment | Changes current onboarding behaviour; may overcharge/undercharge students who paid Registration |
| B. Keep auto-flip | Payment flips to RETURNING | Contradicts the target invariant; makes classification depend on financial history |
| C. Hybrid: explicit flag + review queue | Ambiguous legacy students blocked | Requires admin review capacity; safest for historical data |
| D. Freeze all unverified students to RETURNING | Conservative billing | Undercharges new-intake families; needs reconciliation |

**Affected models/workflows.** `Student.student_type`, `Student.registration_paid_term`, `fees/utils.resolve_student_type`, payment recording, checkout, generation, Apply-Payment UI.

**Consequence of postponing.** Phase 2 backfill cannot run; the new resolver cannot be authoritative; every invoice generated in the meantime entrenches the current behaviour.

---

### PD-03 — Enrollment and class-offering relationships

**Why it is unresolved.** `ClassEnrollment` is unique per `(student, session)` with no term field. The plan proposes `enrolled_from_term`. Separately, the assignment refers to "new ClassOffering relationships", but **no `ClassOffering` model exists** in the repository or documents [V17].

**Alternatives**

| Option | Grain | Consequence |
|---|---|---|
| A. Extend `ClassEnrollment` with `enrolled_from_term` | One class per student per session | Cheapest; cannot represent mid-session class changes |
| B. Term-level enrollment table | One class per student per term | Represents transfers; larger migration and UI change |
| C. Class-offering model | Class × session × term (and possibly subject) | Needed if offerings are sold or staffed per term; largest change |
| D. Leave as-is | Session-level only | Blocks first-enrolled-term classification for Term 2/3 joiners |

**Affected models/workflows.** `ClassEnrollment.unique_together`, promotion, transfer, withdrawal, class change, invoice generation, score lookup, booklets.

**Deletion implication.** If a class-offering model is introduced, its FK to `SchoolClass` and `Term` must be specified before any deletion analysis can be completed. The prior report's FK graph does not cover it because the model does not exist.

**Consequence of postponing.** Gate 3 cannot open; `TermFeeItem` class scope remains session-agnostic; historical "which class in which term" remains unanswerable.

---

### PD-04 — Historical snapshot treatment

**Why it is unresolved.** Migration 0022 already filled historical `InvoiceLineItem.item_name` with current category names [V3]. That is the exact practice the corrected policy forbids, and it has already happened.

**Alternatives**

| Option | Behaviour | Consequence |
|---|---|---|
| A. NULL for unverified, fallback at render | Never claims historical accuracy | Booklets show a neutral fallback; some historical labels lost |
| B. Provenance marker (`item_name_source`) | Keeps 0022 values but marks them unverified | Preserves display while disclosing provenance; requires new column |
| C. Admin verification workflow | Admin confirms names per record | Highest accuracy; highest effort |
| D. Re-run backfill | Copy current names again | Rejected — repeats the defect |

**Affected models/workflows.** `InvoiceLineItem.item_name`, `FeePrice.name`, proposed booklet snapshots, `SnapshotCorrection`/audit, report rendering.

**Consequence of postponing.** Booklet sign-off cannot occur; any report may silently present a current name as a historical fact.

---

### PD-05 — LEVEL fee-price mapping and administrator approval

**Why it is unresolved.** Legacy `LEVEL` matching is exact string equality against `SchoolClass.level` [V13]. There is no normalisation, no stage FK, and no evidence that the strings correspond to intended stages.

**Alternatives**

| Option | Behaviour | Risk |
|---|---|---|
| A. Per-row admin approval queue (recommended) | Each LEVEL row explicitly mapped or discarded | Slow; auditable |
| B. Evidence-based auto-map only where a 1:1 unique match exists | Faster | Still infers intent; must be reviewed |
| C. Bulk map by name similarity | Fastest | Repeats the defect the correction forbids |
| D. Leave LEVEL operational indefinitely | No data migration | Legacy resolver must remain forever; target schema incomplete |

**Affected models/workflows.** `FeePrice.scope=LEVEL`, `FeePrice.level`, proposed `TermFeeItem`, resolver, invoice generation.

**Consequence of postponing.** Phase 3 cannot migrate configuration; the dual resolver remains permanent; price resolution for LEVEL classes stays string-dependent.

---

## C. Data-audit prerequisites

### C.1 Preconditions for Q-01…Q-10

| # | Prerequisite | Detail |
|---|---|---|
| 1 | Engine confirmation | PostgreSQL major/minor, collation, timezone; recorded by DBA (DA-00) |
| 2 | Representative data | Restored production copy, not a hand-built sample; same migration state as deployed commit |
| 3 | Read-only access | `SELECT`-only role, `default_transaction_read_only=on`, statement timeout, no DDL/DML grants (DA-01) |
| 4 | Schema validation | R-02 identifiers resolved against the clone; R-03 dialect matrix passed at the confirmed version |
| 5 | Query review | Every query has an ID, purpose, grain, expected columns, and a written expected magnitude |
| 6 | Execution isolation | No query runs against primary; no `EXPLAIN ANALYZE` on primary; no locks held |
| 7 | Evidence capture | R-11 template: SQL text, engine, row counts, checksums, operator, timestamp |
| 8 | Exception handling | Timeout, lock, permission error, and PII exposure procedures defined before execution |

### C.2 Query specification status

All ten queries are **specified but not executed**. None may be reported as passed. The corrected syntax rules:

- Joins precede `WHERE`; no `LEFT JOIN` after `WHERE`.
- Every nullable FK used in a join must have an explicit `IS NULL` branch where orphans are being counted.
- Cross-school checks compare the child's `school_id` to the parent's `school_id`, not to a constant.
- `NULL` school on `InvoiceLineItem` is expected for app-created rows [V11] and must be classified, not treated automatically as corruption.

### C.3 The seven integrity checks

| ID | Check | Expected output | Failure meaning |
|---|---|---|---|
| IC-1 | One-time billing history: for every `ONE_TIME` category, list student, session, term, line-item count | Duplicates per student/session and per student/lifetime | Confirms or refutes the current guard's behaviour |
| IC-2 | LEVEL enumeration: every `FeePrice.scope='LEVEL'` row with level string, term, category, type, amount, dates | Complete inventory; distinct level strings per school | Input to PD-05 |
| IC-3 | Stage mapping: distinct `SchoolClass.level` values vs. existing `AcademicStage` names and class counts | Mapping table with unmatched values | Input to Phase 1 backfill |
| IC-4 | Category deletion risk: categories with line items, prices, overrides | Counts per category | Confirms V4/V8 exposure |
| IC-5 | Cross-school references: every FK pair where child school ≠ parent school | Counts and sample IDs per relationship | Tenant-integrity breach |
| IC-6 | Payment allocation: `Payment.amount` vs. `SUM(PaymentLineItem.amount)` | Mismatch list | Allocation corruption or partial capture |
| IC-7 | Receipt integrity: confirmed payments without receipt; receipts without payment; duplicates | Counts and IDs | Financial-record integrity |

### C.4 Additional checks required by this review

| ID | Check | Why |
|---|---|---|
| IC-8 | Historical loss from migrations 0017/0018: invoices whose total ≠ sum of line items; categories deleted while line items existed; terms with no price history | V4/V5 |
| IC-9 | Snapshot provenance: `InvoiceLineItem.item_name` values that equal the current category name but predate the column | V3 |
| IC-10 | Live deletion exposure: counts of records that would be destroyed by `Student.delete()`, `Payment.delete()`, staff delete, category delete | V6–V8 |

### C.5 Evidence preservation

- Store query text, not only results.
- Hash each result set (SHA-256) and record row count.
- Record the exact database identity (host alias, snapshot timestamp) without credentials.
- Retention: at least until Gate 5 closes.
- Access: engineering lead, product owner, security; no wider distribution of student PII.
- Any re-run must produce a new evidence pack; never overwrite the original.

---

## D. Phase gates

### D.1 Gate summary

| Gate | Name | Entry criteria | Exit criteria | Sign-off |
|---|---|---|---|---|
| **G0** | Phase 0 readiness and evidence | R-01…R-04, R-07, R-11, R-12 complete; DA-00/01/02 complete | DA-03/04/05 executed; DA-06 triage complete; contradictions register has an owner per item; evidence pack accepted | Engineering lead + product owner |
| **G1** | Academic-structure completion | G0; R-13; PD-03 decided; AP-01 | Stage backfill plan approved; class/stage consistency validation defined; no unverified mapping auto-applied; uncommitted stage work reconciled and reviewed | Product owner + engineering lead |
| **G2** | Classification implementation | G1; PD-02 decided | Review queue implemented; generation blocking tested; payment no longer changes classification (or documented exception) | Product owner + school admin |
| **G3** | Scoped configuration (schema only) | G2; PD-01, PD-05, PD-06 decided; AP-02 | `TermFeeItem` + child price migrated in dev; dual resolver flag-off; equivalence harness green on synthetic data; no production data change | Engineering lead |
| **G4** | Resolver cutover readiness | G3; IM-05/06 complete; equivalence report reviewed | Legacy vs. new diff explained for every tuple; deletion protections active; rollback rehearsed | Engineering lead + product owner |
| **G5** | Production data migration | G4; PD-04, PD-07, PD-08 decided; IM-09/10/11 complete; AP-04 | Migration executed in window; baseline diff zero or documented; rollback owner named; observation period passed | Product owner + engineering lead + DBA |
| **G6** | Production cutover | G5; AP-05 | Resolver flag enabled per school; monitoring green for the agreed window; no unexplained invoice differences | Product owner + engineering lead |

### D.2 Separation of approvals

| Approval | Covers | Does **not** cover |
|---|---|---|
| AP-01 / AP-02 | Writing code, migrations, and tests in the repository | Running anything against production |
| AP-03 | Read-only audit access to a production-derived copy | Any schema or data change |
| AP-04 | Executing migrations/backfills in production | Enabling the new resolver for users |
| AP-05 | Switching invoice generation to the new resolver | Future schema changes |

**Implementation approval is not migration approval.** A merged migration is not an executed migration.

### D.3 Gate rules

- A gate cannot be passed by an additive migration alone [rule: do not mark safe merely because additive].
- Any unresolved contradiction in §0.4 blocks G0.
- Any query without captured output cannot satisfy G0.
- Any product decision without a named approver and date cannot satisfy its gate.
- A failed gate stops the rollout; it is never repaired by resetting financial data.

---

## E. Risks and recovery

| # | Risk | Impact | Prevention / detection | Recovery | Rollback possible after new writes? |
|---|---|---|---|---|---|
| E1 | Potential historical line-item loss from migration 0018 cascade (V4) — unquantified | Invoice totals ≠ line-item sums; booklets incomplete | IC-8; detect before any migration; do not "repair" by rewriting invoices | Document as pre-existing; reconstruct only from provider records or backups if available; disclose in reports | **No** — data is already gone unless a backup exists |
| E2 | Student deletion destroys invoices, payments, receipts, scores (V6) | Complete loss of a family's financial and academic history | IM-06; replace delete with archive/deactivate; regression test | Restore from backup; may lose intervening records | **No** — restore is point-in-time, not row rollback |
| E3 | Staff deletion cascades payments and scores (V7) | Financial and academic records disappear when a user is removed | IM-06; change to `SET_NULL` or block deletion; audit | Restore from backup | **No** |
| E4 | Category deletion cascades line items (V8) | Historical invoice lines vanish | IM-05 `PROTECT`; pre-flight guard; remove delete button | Restore from backup | **No** |
| E5 | Snapshot backfill 0022 already wrote current names into history (V3) | Reports may present current names as historical facts | PD-04; provenance marker; IC-9 | Mark unverified; do not re-null | **Partial** — marker can be added; original historical name may be unrecoverable |
| E6 | Pricing configuration history already purged (V5) | Cannot reconstruct why a past invoice had its amount | IC-8; treat line-item snapshots as the only record | Use line-item amounts as authoritative; do not infer from current config | **No** |
| E7 | Resolver divergence (legacy vs. new) | Wrong amounts on new invoices | R-06 equivalence harness; G4 diff review; flag-off default | Disable flag; legacy resolver resumes | **Yes for pricing, no for invoices already issued** |
| E8 | Removing cross-term fallback changes prices mid-year (V13) | Families billed differently without warning | Equivalence report; per-school rollout; preflight shows old/new | Flag off | **Yes before generation; no after** |
| E9 | One-time/session interaction double-bills or misses a fee | Financial and trust impact | PD-01; transactional enforcement; IC-1 | Correct via credit/reversal, never by editing history | **No** for issued invoices |
| E10 | `TermFeeItem.term` required vs. term-less one-time prices (V14) | Schema cannot represent current behaviour | PD-01 must settle nullability before IM-02 | Redesign migration before release | **Yes before data migration; no after** |
| E11 | Nullable `unique_together` does not prevent duplicates (V19) | Multiple active prices resolve unpredictably | Q-06; partial unique indexes with `condition`; application validation | Clean duplicates before cutover | **Yes before cutover** |
| E12 | `InvoiceLineItem.school` NULL on newly generated rows (V11) | Cross-school audit gives false negatives; tenant checks incomplete | IC-5 plus an explicit null-school count; backfill plan; resolver/validator requires explicit null branch | Backfill school from invoice | **Yes** — additive correction |
| E13 | Booklet renders NULL snapshot | Crash or blank report | IM-01 `COALESCE`; template test | Template fix | **Yes** |
| E14 | Deploy-order incompatibility (old code + new schema, or reverse) | Runtime errors during release | Expand/contract migrations; deploy schema before code; keep legacy fields | Roll back code; leave additive schema | **Yes** if no new writes to new tables; **no** once written |
| E15 | Destructive utilities still executable (V10) | Accidental wipe during migration | R-08; hard gate; remove from production image | Restore from backup | **No** |
| E16 | `sync_class_invoices` rewrites unpaid invoices (V9) | Historic invoice lines change silently | Disable path before migration; audit test | Restore from backup | **No** |
| E17 | Audit trail gap for fee-configuration changes (V18) | Corrections cannot be attributed | IM-10 dedicated audit; extend `WATCHED_MODELS` only after `school` nullability is handled | Add audit rows going forward; past changes remain unattributed | **Partial** |
| E18 | Christmas visibility/billing divergence (V12) | Fee shown but not billed, or vice versa | Fix visibility helper; regression test | Code fix | **Yes** |
| E19 | Production audit accidentally writes or locks | Operational incident | Read-only role; timeout; no `ANALYZE` on primary; review before run | Abort session; DBA review | **N/A** |

### E.1 Rollback truth table

| After… | Dropping new tables | Reverting code | Restoring backup |
|---|---|---|---|
| Schema added, no writes | Safe | Safe | Unnecessary |
| Backfill written to new tables | **Unsafe** — loses backfill evidence | Safe | Safe |
| App writes to new tables | **Unsafe** — orphans and data loss | Safe if legacy path intact | Safe |
| New invoices issued via new resolver | **Unsafe** | Only with legacy resolver restored | Point-in-time only; loses later records |
| Financial records mutated | **Never** | **Never** | Only recovery |

---

## F. Consolidated GO/NO-GO

| Scope | Decision | Basis |
|---|---|---|
| **Readiness work** (R-01…R-13, documentation, harnesses) | **GO** | No production access, no schema change, no implementation authorization required. All tasks are reversible and confined to the repository (R-13 is review-only). |
| **Implementation** (IM-01…IM-11) | **NO-GO** | PD-01, PD-02, PD-03, PD-04 are unresolved; Gate 0 evidence is absent; the repository already contradicts the snapshot and classification policies. |
| **Production data migration** | **NO-GO** | Gate 0 has not been passed; no query has been executed; AP-03 and AP-04 are not granted; IC-8 indicates historical loss may already exist and must be quantified first. |

### Next three concrete actions, in order

1. **Build the Phase 0 audit harness in the repository** — R-01, R-02, R-03, R-04, R-07, R-11. This is pure readiness work: query catalogue, identifier validator, dialect runner, synthetic fixtures, deletion inventory, evidence template. No production access, no schema change.
2. **Convene the decision session for PD-01, PD-02, PD-03, and PD-04** — one-time billing, classification source of truth, enrollment/ClassOffering semantics, and historical snapshot treatment. Record each outcome in a signed decision register with a named approver and date.
3. **Request read-only audit access and engine confirmation** — AP-03 plus DA-00/DA-01. Only after the harness is green locally and the decisions are recorded should DA-02 and then DA-03/DA-04/DA-05 run against the restored copy.

### Decisions or access that must come from a human

| Who | What |
|---|---|
| Product owner | PD-01 one-time billing; PD-02 classification; PD-03 enrollment/ClassOffering; PD-04 snapshots; PD-06 effective dating; PD-07 lifecycle; PD-08 reversals |
| School admin | PD-04 historical verification; PD-05 LEVEL approvals; PD-07 deletion policy |
| Engineering lead | Resolver architecture, flag strategy, rollback plan, evidence-pack acceptance |
| Security / DBA | Read-only role, engine/version confirmation, PII handling, backup and restore drill |
| Finance | PD-08 reversal and credit-note policy; IC-6/IC-7 acceptance |

### Access required

- Read-only credentials to a restored production copy (not the primary).
- Confirmed PostgreSQL version and collation.
- Backup/restore procedure and a tested restore.
- No write access is requested or authorized by this plan.

---

**Status of this document.** Planning only. No code, migration, schema, or database was modified. The architecture in `docs/FEE_REDESIGN_PLAN.md` is preserved; this plan governs execution order and authorization, not target design.
