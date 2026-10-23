# Historical Data Loss Review

**Status:** Read-only forensic review — no application code, migrations, models, tests, databases, or Git state were modified.
**Repository:** `https://github.com/yohananX/bust-base.git`
**Baseline commit:** `8a1bdcc287826253ee51bf9d2e3619706ee15546` (`main`)
**Reviewed:** `2026-10-23`
**Scope:** `fees/0017`, `fees/0018`, `fees/0022`; adjacent `fees/0013`, `fees/0015`, `fees/0016`, `fees/0020`; application and Django-admin deletion paths that can remove financial or academic history.

---

## 0. Method and evidence standard

This review distinguishes four different kinds of claim. They are labelled throughout:

| Label | Meaning |
|---|---|
| **PROVEN (code)** | Demonstrated by reading the migration/view/model source, or by compiling historical model state with Django's `MigrationLoader` without touching a database. |
| **PROVEN (local DB)** | Observed by read-only queries against the local `db.sqlite3`. This is *not* production evidence. |
| **UNVERIFIED** | Plausible and consistent with the code, but depends on deployment history, production data, or runtime database behaviour that is unavailable here. |
| **NOT RUN** | A test or query that was deliberately not executed. |

**Critical evidence limitation:** the local `db.sqlite3` was created fresh on `2026-10-22` and all 23 `fees` migrations were applied to an empty database at `2026-10-22 16:19`. It contains 1 school and **zero** fee categories, fee prices, invoices, payments, receipts, scores, and audit logs. It therefore contains **no evidence either way** about historical production loss. No production database, production backup, or restored copy was available. Actual loss to real schools remains **unquantified**.

No destructive operation was executed to test cascade behaviour. Cascade conclusions below come from model metadata and migration state, not from deleting rows.

---

## 1. Executive findings and severity

### 1.1 Summary

Three data migrations in the fee redesign are destructive and effectively irreversible at the data level:

1. **`0017_cleanup_duplicate_one_time_prices`** deletes `FeePrice` rows with no reverse path. It deletes (a) every class-scoped `ONE_TIME` price in favour of one arbitrary school-wide row, and (b) every price not belonging to the **current** term — including term-less (`term_id IS NULL`) one-time prices, because of Django `.exclude()` NULL semantics.
2. **`0018_delete_school_fees_categories`** deletes every `FeeCategory` whose name ends with `School Fees`, across all schools, and its reverse is an explicit `pass`. Because `InvoiceLineItem.category` was a non-null `CASCADE` at that migration state, it cascade-deletes historical invoice line items for those categories. Invoices, payments, and receipts survive; invoice totals are not adjusted, so historical invoices can end up with totals larger than the sum of their surviving line items.
3. **`0022_backfill_fee_price_and_line_item_names`** does not restore anything. It overwrites blank `FeePrice.name` and `InvoiceLineItem.item_name` with the **current** category name, destroying the distinction between "name was always blank" and "name is a post-hoc reconstruction", and it cannot recover names for rows already deleted.

In addition, the application still exposes multiple hard-delete paths that destroy financial and academic history **after** the migrations ran: fee category deletion (guarded only by `FeePrice`, not invoice line items), fee price deletion, payment deletion, student deletion, staff-user deletion, class deletion, subject deletion, bulk reset services, and destructive management commands. Django admin exposes default delete for `Invoice`, `Payment`, `FeePrice`, `FeeCategory`, `Term`, `School`, and `User`.

### 1.2 Severity assessment

| Finding | Severity | Why |
|---|---|---|
| `0017` deletes all non-current-term and term-less one-time prices | **Critical** | Historical and future pricing evidence is destroyed; reverse is `noop`. |
| `0018` cascades deletion into `InvoiceLineItem` | **Critical** | Breaks the audit trail between invoice totals and billed items; reverse is `pass`. |
| `0017`/`0018`/`0022` reverses are `noop`/`pass` | **Critical** | `migrate fees 0016` cannot restore data; it only moves schema backwards. |
| `0020` drops `FeeStructure` after a one-time `0013` copy | **High** | Legacy structures are gone; rollback recreates empty tables. |
| `0022` backfills with current names | **High** | Creates silent, unmarked provenance corruption of historical labels. |
| `InvoiceLineItem.category = CASCADE` | **High** | Live deletion of a category destroys historical line items. |
| `Payment.recorded_by = CASCADE` | **High** | Deleting a staff user deletes payments they recorded. |
| `Score.entered_by = CASCADE` | **High** | Deleting a staff user deletes academic scores. |
| Payment/student/class/subject hard deletes with no reversal record | **High** | Billing and results history is removed without an immutable reversal trail. |
| `AuditLog` coverage gaps | **Medium–High** | The models most affected by cascade are not audited; deleting `School` cascades the audit log itself. |
| Deployment auto-runs migrations | **High** | `entrypoint.sh` runs `migrate --noinput` on every container start, so a deploy can apply destructive migrations with no prompt. |
| Actual production impact | **Unknown** | No production data or backup was available; occurrence is UNVERIFIED. |

### 1.3 Bottom line

The code **provably can** destroy historical fee pricing and invoice line-item history. Whether it **did** in production is **unverified**. The review therefore cannot state a loss figure, and must not be read as confirming or denying that schools lost data. The correct posture is: assume loss is possible, preserve every remaining artefact, and do not run further destructive migrations until the evidence in §5 is gathered.

---

## 2. Migration-by-migration analysis

### 2.1 `fees/0017_cleanup_duplicate_one_time_prices`

**Dependency:** `fees.0016`
**Operations:** two `RunPython` calls; the reverse for both is `migrations.RunPython.noop`.

#### Function 1 — `remove_duplicate_one_time_prices`

```python
for cat in FeeCategory.objects.filter(billing_cycle='ONE_TIME'):
    class_rows = FeePrice.objects.filter(
        category=cat, scope='CLASS', school_class__isnull=False,
    )
    if class_rows.exists():
        school_wide = FeePrice.objects.filter(
            category=cat, scope='SCHOOL_WIDE', school_class__isnull=True, level='',
        ).first()
        if not school_wide:
            first = class_rows.first()
            FeePrice.objects.create(
                school=first.school, scope='SCHOOL_WIDE', school_class=None,
                level='', term=first.term, category=cat,
                student_type=first.student_type, amount=first.amount,
                is_active=first.is_active,
            )
        class_rows.delete()
```

**PROVEN (code):**

- All `FeePrice` rows with `scope='CLASS'` for a `ONE_TIME` category are deleted.
- If no school-wide row exists, **one arbitrary row** (`class_rows.first()`, unordered) is copied to a school-wide row.
- The copy preserves only `school`, `scope`, `school_class=None`, `level=''`, `term`, `category`, `student_type`, `amount`, `is_active`. It **does not** preserve `effective_from`, `effective_to`, `name`, or any other per-row field.
- **Per-class amount differences are lost.** If JSS1 paid 5,000 and JSS2 paid 6,000 for the same one-time category, both collapse to whichever class row was returned first.
- If a school-wide row already exists, no copy is made at all, and the class rows are simply deleted.
- The loop runs for **every** `ONE_TIME` category in **every** school, because `FeeCategory` is tenant-scoped but the queryset is not filtered by school. Copying uses `first.school`, so cross-school leakage is avoided, but the deletion itself is global.

#### Function 2 — `remove_old_term_prices`

```python
for school in School.objects.all():
    current_term = Term.objects.filter(school=school, is_current=True).first()
    if not current_term:
        continue
    FeePrice.objects.filter(school=school).exclude(term=current_term).delete()
```

**PROVEN (code + compiled SQL):** historical model state was compiled with `MigrationLoader(None)` and the queryset inspected without executing it. `.exclude(term=current_term)` compiles to:

```sql
NOT ("term_id" = <current_term_id> AND "term_id" IS NOT NULL)
```

This is the Django NULL-semantics trap: a row with `term_id IS NULL` makes `("term_id" = X AND "term_id" IS NOT NULL)` evaluate to `NULL`, and `NOT NULL` is `NULL`, which SQL `WHERE` treats as not-true — so the row **matches the exclusion** and is deleted.

**Consequences (PROVEN):**

- Every price belonging to a **past** term is deleted.
- Every price belonging to a **future** term is deleted.
- Every **term-less (`term_id IS NULL`) price is deleted**, including one-time prices such as PTA, registration, and uniforms that were *just consolidated* by function 1 in the same migration. Function 1 often creates a school-wide row with `term=first.term`; if that term is non-current or NULL, function 2 immediately deletes it.
- Schools **without** a current term are skipped entirely, so their rows survive. This makes the outcome dependent on `Term.is_current` configuration at migration time — a hidden data-dependent side effect.

**Net effect:** after `0017`, in any school with a current term, only `FeePrice` rows attached to the current term survive. All historical pricing and all term-less one-time pricing is gone. Reverse is `noop`, so `migrate fees 0016` restores nothing.

#### What `0017` does **not** do

- It does not touch `InvoiceLineItem`, `Invoice`, `Payment`, or `FeeReceipt`.
- It does not re-seed prices.
- It does not create an audit record.

### 2.2 `fees/0018_delete_school_fees_categories`

**Dependency:** `fees.0017`
**Operations:** one `RunPython`; reverse is a function whose body is `pass` with a docstring saying data must be re-seeded.

```python
school_fees_cats = FeeCategory.objects.filter(name__regex=r'School Fees$')
FeePrice.objects.filter(category__in=school_fees_cats).delete()
FeeStructure.objects.filter(category__in=school_fees_cats).delete()
school_fees_cats.delete()
```

**PROVEN (code):**

- The regex `School Fees$` is **case-sensitive** and **suffix-anchored** on SQLite (`__regex` is not supported on all backends identically; on PostgreSQL it maps to `~`, which is also case-sensitive). It matches `School Fees`, `JSS1 School Fees`, `Pre-Nursery School Fees`, and `Primary 4 School Fees`. It does **not** match `school fees`, `SCHOOL FEES`, or `School Fees Extra`.
- Matching is global across all schools; there is no `school=` filter.
- It explicitly deletes `FeePrice` and legacy `FeeStructure` rows for matching categories, then deletes the categories themselves.
- Because the deletion of `FeeCategory` is a normal model `.delete()`, Django collects related objects. At historical migration state `0018`, `InvoiceLineItem.category` was a **non-null `CASCADE`**. Therefore **historical invoice line items for every matching category are cascade-deleted**, even though the migration only names `FeePrice` and `FeeStructure`.

**Verified related-object delete behaviour at `0018` (PROVEN from historical model state):**

| Model | Field | `on_delete` at `0018` | Effect of deleting a category |
|---|---|---|---|
| `fees.InvoiceLineItem` | `category` | `CASCADE` (non-null) | **Line items deleted.** |
| `fees.FeePrice` | `category` | `CASCADE` | Prices deleted (also explicitly deleted). |
| `fees.FeePriceOverride` | `category` | `CASCADE` | Scholarship/discount overrides deleted. |
| `fees.FeeStructure` | `category` | `CASCADE` | Legacy structures deleted (also explicitly deleted). |
| `fees.FeeCategoryGroupAssignment` | `category` | `CASCADE` | Group assignments deleted. |
| `fees.PaymentLineItem` | `category` | `SET_NULL` | Payment allocations survive but lose category linkage. |

**What survives:** `Invoice` rows, `Payment` rows, `FeeReceipt` rows, `PaymentLineItem` rows. **What is broken:**

- `Invoice.total_amount` is **not** recomputed. A historical invoice whose total was built from `JSS1 School Fees` plus other items now has a total that no longer equals the sum of its line items.
- Payments may still sum to the old total while the surviving line items sum lower (or to zero), so reconciliation reports can show overpayment, under-billing, or phantom balances.
- `PaymentLineItem` rows may point at a now-deleted category (`SET_NULL`), losing the ability to explain what was paid for.

**Provenance note:** the migration's docstring claims the `X School Fees` categories were duplicates of `Tuition Fee` and "both have the same amount". That is an assertion, not a verified invariant. Nothing in the migration checks that a corresponding `Tuition Fee` price exists, that amounts match, or that the historical invoice line items were genuinely duplicates. If any school used `School Fees` as the canonical category, its billing history is simply gone.

### 2.3 `fees/0022_backfill_fee_price_and_line_item_names`

**Dependency:** `fees.0021` (which added `FeePrice.name` and `InvoiceLineItem.item_name`)
**Operations:** two `RunPython` calls; reverse is `noop`.

```python
for price in FeePrice.objects.filter(name='').select_related('category'):
    price.name = price.category.name
    price.save(update_fields=['name'])

for item in InvoiceLineItem.objects.filter(item_name='').select_related('category'):
    item.item_name = item.category.name
    item.save(update_fields=['item_name'])
```

**PROVEN (code):**

- Only **blank** (`=''`) names are filled. Non-blank names are left alone.
- The value written is the **current** `category.name`, not a historical snapshot. If a category was renamed between the invoice date and `0022`, the "historical" item name becomes the modern name.
- The migration cannot restore anything deleted by `0017` or `0018`; it only operates on rows that still exist and have a live category.
- `InvoiceLineItem.item_name` is a denormalized display-name field *intended* to preserve historical wording (its model help text says so). Backfilling it from the current category defeats that intent for pre-existing rows.
- Because there is no marker (no `name_source`, no timestamp, no provenance column), it is now **impossible to distinguish** a genuinely historical name from a post-hoc reconstruction.

**Interaction with `0018`:** `0018` deletes line items whose category matched `School Fees`. Remaining line items keep whatever category they had. `0022` then stamps blank names with current category names. The combination produces a dataset that looks complete but is partly reconstructed — the worst outcome for later forensic or legal use.

**Reverse:** `noop`. Reversing `0021` drops both columns entirely, so even the reconstructed names disappear.

### 2.4 Adjacent migrations that compound the loss

| Migration | Behaviour | Data consequence |
|---|---|---|
| `0013` | Copies all `FeeStructure` rows into `FeePrice` once, marks originals deprecated. Reverse is `noop`. | One-time snapshot only. Later edits to `FeeStructure` are not reflected. |
| `0015` | Empty migration. | None. |
| `0016` | Schema alterations on `FeeStructure`. | None by itself. |
| `0020` | Deletes `FeeStructure`, `FeeCategoryGroup`, `FeeCategoryGroupAssignment`. | The legacy `FeeStructure` evidence is dropped entirely; rollback recreates empty tables. It relies on the `0013` copy, which cannot be re-run to recover post-`0013` changes. |

**Chain conclusion (PROVEN):** once `0020` runs, the original `FeeStructure` table is gone. `0013`'s copy is the only surviving representation, and `0013`'s reverse is a no-op. Rolling back to before `0013` does **not** restore legacy fee structures.

### 2.5 Migration dependency chain

```
0013 (copy FeeStructure → FeePrice, noop reverse)
  → 0014
  → 0015 (empty)
  → 0016 (schema)
  → 0017 (delete class ONE_TIME + all non-current-term prices, noop reverse)
  → 0018 (delete * School Fees categories → cascade line items, pass reverse)
  → 0019
  → 0020 (drop FeeStructure / groups, data copy already done)
  → 0021 (add name columns)
  → 0022 (backfill names from current category, noop reverse)
```

Every destructive step is one-way at the data level. A schema rollback is not a data rollback.

---

## 3. Financial and academic deletion dependency map

### 3.1 Configured `on_delete` relationships (current model state)

**PROVEN by Django model introspection.** "Configured" is not the same as "reachable from the UI"; see §3.2.

#### Financial

| Source model | Field | Target | `on_delete` | Consequence of target deletion |
|---|---|---|---|---|
| `fees.InvoiceLineItem` | `category` | `FeeCategory` | **CASCADE** | Line item deleted. |
| `fees.InvoiceLineItem` | `invoice` | `Invoice` | CASCADE | Line item deleted with invoice. |
| `fees.InvoiceLineItem` | `school` | `School` | CASCADE | Line item deleted with school. |
| `fees.FeePrice` | `category` / `school_class` / `term` / `school` | various | CASCADE | Price deleted. |
| `fees.FeePriceOverride` | `category` / `student` | `FeeCategory` / `Student` | CASCADE | Override deleted. |
| `fees.Invoice` | `student` / `term` / `school` | various | CASCADE | Invoice deleted, and its line items. |
| `fees.Payment` | `invoice` / `student` / `school` | various | CASCADE | Payment deleted. |
| `fees.Payment` | `recorded_by` | `User` | **CASCADE** | **Deleting a staff user deletes payments they recorded.** |
| `fees.Payment` | `confirmed_by` | `User` | SET_NULL | Payment survives, confirmer unknown. |
| `fees.FeeReceipt` | `payment` | `Payment` | CASCADE | Receipt deleted with payment. |
| `fees.PaymentLineItem` | `category` / `term` / `session` / `invoice` | various | **SET_NULL** | Allocation survives, linkage lost. |
| `fees.FeeStructure` | `category` | `FeeCategory` | CASCADE | Legacy structure deleted (table later dropped by `0020`). |
| `fees.FeeCategoryGroupAssignment` | `category` | `FeeCategory` | CASCADE | Assignment deleted. |
| `payroll.Payslip` / `SalaryDisbursement` | `school` / user links | various | CASCADE / SET_NULL | Payroll history affected by user/school deletion. |

#### Academic

| Source model | Field | Target | `on_delete` | Consequence |
|---|---|---|---|---|
| `academics.Score` | `entered_by` | `User` | **CASCADE** | **Deleting a staff user deletes scores they entered.** |
| `academics.Score` | `moderated_by` | `User` | SET_NULL | Score survives, moderator unknown. |
| `academics.Score` | `student` / `subject` / `term` | various | CASCADE | Score deleted with student/subject/term. |
| `students.ClassEnrollment` | `student` / `school_class` | various | CASCADE | Historical enrollment deleted. |
| `students.Student` | `user` | `User` | CASCADE | Student profile deleted with user. |
| `students.StudentGuardianLink` | `student` / `guardian` | various | CASCADE | Guardian link deleted. |
| `academics.TermResult` | `student` / `term` | various | CASCADE | Result deleted. |
| `core.Term` | `school` | `School` | CASCADE | Terms, and everything hanging off them, deleted. |

### 3.2 Application entry points that can reach these cascades

**PROVEN (code).** These are the live paths, independent of migrations. None of them requires a database superuser except where noted.

| # | Entry point | File / lines | Guard | What can be destroyed |
|---|---|---|---|---|
| 1 | **Fee category delete** | `school_admin/views/fee_categories.py:76-99` | Blocks only if `FeePrice` exists. Does **not** block on `InvoiceLineItem`, even though it counts them. | Category with only harness line-item references deletes → **cascades historical `InvoiceLineItem` rows**. This is the same destructive path as `0018`, still open. |
| 2 | **Fee price delete** | `school_admin/views/fee_pricing.py:676-697` | Any ADMIN; no invoice guard, no confirmation of historical impact. | `FeePrice` row and cascaded overrides. |
| 3 | **Staff hard delete** | `school_admin/views/staff.py:198-255` | Superuser only. Warning counts teacher assignments, scores, notifications, procurements, inventory transactions — **omits `Payment.recorded_by`, payroll, and receipts**. | `User.delete()` cascades **payments recorded by that user**, **scores entered by that user**, and payroll links. Confirmation screen understates the blast radius. |
| 4 | **Student delete** | `school_admin/views/students.py:472-508` | Any ADMIN. Warning counts only enrollments, guardians, invoices. | Cascades invoices, payments, receipts, scores, term results, guardian links. |
| 5 | **Payment delete** | `school_admin/views/invoices.py:493-507` | Any ADMIN. No reversal record, no audit requirement. | Payment, its receipt, and payment allocations. No immutable reversal entry. |
| 6 | **Class delete** | `school_admin/views/classes.py:163-202` | Warns current enrollments only. | Historical `ClassEnrollment`, class-scoped `FeePrice`, `TeacherAssignment`, subjects. |
| 7 | **Subject delete** | `school_admin/views/academics.py:164-204` | Warns but allows. | `Score`, `TeacherAssignment` for that subject. |
| 8 | **Bulk invoice/payment reset** | `fees/reset.py` | Admin actions enforce superuser; `reset_school` requires `force=True`; writes `InvoiceResetLog`. | All invoices/payments for a scope. The reset log is the only trail, and it records the operation, not the full row contents. |
| 9 | **`sync_class_invoices`** | `fees/generation.py:157-202` | Deletes and rewrites all line items on **unpaid** invoices. | Can erase evidence of the `0018` total-vs-line-item mismatch before anyone reconciles it. |
| 10 | **`clear_student_data` command** | `core/management/commands/clear_student_data.py` | Optional dry-run; **no confirmation flag**. | Student data across the app. |
| 11 | **`clear_student_payment_history` command** | `fees/management/commands/clear_student_payment_history.py` | **No dry-run, no confirmation flag.** | Payment history. |
| 12 | **`scripts/reset_student_data.sql`** | `scripts/reset_student_data.sql` | Raw SQL. | Direct destructive reset, bypassing Django signals and audit. |
| 13 | **Django admin default delete** | registered `ModelAdmin`s | Django's default confirmation page. | `School`, `AcademicSession`, `Term`, `User`, `FeeCategory`, `FeePrice`, `Invoice`, `Payment`, etc. No project-wide `has_delete_permission` override was found. |

### 3.3 Audit coverage gaps

`core/audit.py` registers `post_delete` handlers only for `Payment`, `Invoice`, `Score`, `Payslip`, and `SalaryDisbursement`.

**PROVEN gaps:**

- `InvoiceLineItem` deletions — including the `0018` cascade and the live category-delete cascade — are **not audited**.
- `FeeReceipt` deletion is **not audited**.
- `FeeCategory` and `FeePrice` deletion are **not audited**.
- `Student`, `Term`, `ClassEnrollment`, `TermResult` deletion are **not audited**.
- Deleting a `School` cascades `AuditLog` rows themselves, so the audit trail disappears with the tenant.
- Raw SQL resets (`scripts/reset_student_data.sql`) bypass signals entirely.

This means that even where an operator did delete data, there may be **no surviving in-app record** of what was removed.

### 3.4 Engine enforcement caveat

The `on_delete` behaviour above is Django's **ORM-level** cascade. Whether the production database enforces additional `ON DELETE` rules depends on the actual schema. **NOT RUN:** no runtime test was performed against PostgreSQL, and no production schema was inspected. The conclusions are about configured Django behaviour, not about observed database constraint behaviour.

---

## 4. Proven facts vs unverified hypotheses

### 4.1 Proven facts (code)

1. `0017` deletes every class-scoped `ONE_TIME` `FeePrice` and keeps at most one school-wide row, copied from an arbitrary first row.
2. `0017` deletes every `FeePrice` for a school with a current term that is not attached to that current term.
3. `.exclude(term=current_term)` compiles to `NOT ("term_id" = X AND "term_id" IS NOT NULL)`, so `term_id IS NULL` rows **are deleted**.
4. `0017`'s reverse is `noop`.
5. `0018` deletes every `FeeCategory` whose name ends with the case-sensitive suffix `School Fees`, across all schools.
6. `0018`'s reverse is a function whose body is `pass`.
7. At `0018`, `InvoiceLineItem.category` is a non-null `CASCADE`, so deleting a matching category cascade-deletes historical invoice line items.
8. `0018` leaves `Invoice`, `Payment`, and `FeeReceipt` rows in place and does not adjust `Invoice.total_amount`.
9. `0022` backfills only blank `FeePrice.name` and `InvoiceLineItem.item_name`, using the **current** category name.
10. `0022`'s reverse is `noop`; reversing `0021` drops the columns.
11. `0020` drops `FeeStructure` after the one-time `0013` copy; rollback recreates empty tables.
12. Current `InvoiceLineItem.category` is still `CASCADE`.
13. Current `Payment.recorded_by` and `Score.entered_by` are `CASCADE`.
14. The live fee-category delete view blocks only on `FeePrice`, not `InvoiceLineItem`.
15. The staff delete warning omits payment, payroll, and receipt cascades.
16. `core/audit.py` does not audit `InvoiceLineItem`, `FeeReceipt`, `FeeCategory`, `FeePrice`, `Student`, or `Term`.
17. `entrypoint.sh` runs `python manage.py migrate --noinput` on every container start.

### 4.2 Proven facts (local DB only — not production evidence)

18. All 23 `fees` migrations are recorded as applied in the local `django_migrations` at `2026-10-22 16:19`.
19. The local DB contains 1 school and **0** fee categories, fee prices, invoices, payments, receipts, scores, and audit logs.
20. There is no `backups/` directory and no `*.sql.gz` in the working tree.
21. `docs/AUDIT_STATUS.md` references a local `backup_20260922_082845.sql.gz` that is **absent** now.

### 4.3 Unverified hypotheses

22. **UNVERIFIED:** that the image containing `0017`/`0018` was ever deployed to a production environment with populated data. The deploy workflow builds and pushes on push to `main`; the entrypoint migrates on container start. Deployment history and container logs were not available.
23. **UNVERIFIED:** that `0017`/`0018` therefore ran against real school data. They may have run only against an empty or seed-only database.
24. **UNVERIFIED:** the number of affected schools, categories, prices, invoices, and line items. No production aggregate exists in this environment.
25. **UNVERIFIED:** whether schools that used `School Fees` as their canonical billing category lost their only pricing record.
26. **UNVERIFIED:** whether any historical invoice now has `total_amount != SUM(line_items.amount)`. This is a **predicted** consequence of `0018`, not an observed one.
27. **UNVERIFIED:** whether `sync_class_invoices` has already rewritten unpaid invoices and erased the mismatch.
28. **UNVERIFIED:** whether operators used the live hard-delete paths (staff, student, payment, category, price) against real data.
29. **UNVERIFIED:** whether PostgreSQL enforced any additional `ON DELETE` behaviour beyond Django's cascade.
30. **UNVERIFIED:** whether backups exist outside the repository (object storage, provider snapshots, DBA copies). None were accessible.

### 4.4 What cannot be claimed

- This review **cannot** state that data was lost in production.
- It **cannot** state that data was *not* lost.
- It **cannot** quantify affected rows, schools, invoices, or amounts.
- It **cannot** certify PostgreSQL parity for any of the above, because no PostgreSQL run was performed.

---

## 5. Evidence required to quantify historical loss

The following artefacts would move the question from "possible" to "measured". They are listed in priority order. None were available in this environment.

### 5.1 Deployment and migration history

| Evidence | Why it matters | Where to obtain |
|---|---|---|
| `django_migrations` rows for `fees.0017`, `0018`, `0022` per environment | Proves whether the destructive migrations actually ran, and when. | Production DB read-only query. |
| Deployed image tag / commit SHA per environment | Maps a running container to a code state. | Container registry, deploy logs, orchestrator. |
| `entrypoint.sh` / container start logs around the deploy | Confirms `migrate --noinput` executed. | Log aggregation (stdout of app container). |
| CI/CD deploy history on `main` | Establishes the window in which the migrations could have run. | GitHub Actions run history. |
| Any migration output (`Backfilled N ...`) | `0022` prints counts; `0017`/`0018` print nothing, but `0022`'s count bounds surviving blanks. | Container logs. |

### 5.2 Backups and restored copies

| Evidence | Why it matters |
|---|---|
| Pre-`0017` and pre-`0018` database dumps | The only way to compute a true before/after diff. |
| Any provider-level snapshot or PITR window covering the deploy | Same, if dumps are absent. |
| The referenced `backup_20260922_082845.sql.gz` | Documented as existing once; currently absent. Locate it before it is lost. |
| Any restored copy in a scratch environment | Allows safe querying without touching production. |

### 5.3 Reconciliation queries (run against a **restored** copy, read-only)

These are the concrete measurements. They should be run on a non-production restore, never against production during business hours.

1. **Migration presence**
   ```sql
   SELECT app, name, applied FROM django_migrations
   WHERE app = 'fees' AND name IN (
     '0013_copy_fee_structure_to_fee_price', -- verify exact name
     '0017_cleanup_duplicate_one_time_prices',
     '0018_delete_school_fees_categories',
     '0020_...', '0022_backfill_fee_price_and_line_item_names'
   ) ORDER BY applied;
   ```

2. **Invoice total vs surviving line items**
   ```sql
   SELECT i.id, i.total_amount, COALESCE(SUM(li.amount), 0) AS line_sum,
          i.total_amount - COALESCE(SUM(li.amount), 0) AS delta
   FROM fees_invoice i
   LEFT JOIN fees_invoicelineitem li ON li.invoice_id = i.id
   GROUP BY i.id, i.total_amount
   HAVING i.total_amount <> COALESCE(SUM(li.amount), 0)
   ORDER BY ABS(i.total_amount - COALESCE(SUM(li.amount), 0)) DESC;
   ```
   Any non-zero `delta` is direct evidence of `0018` (or live category deletion) having removed line items.

3. **Invoices with no line items at all**
   ```sql
   SELECT i.id, i.total_amount, i.student_id, i.term_id
   FROM fees_invoice i
   LEFT JOIN fees_invoicelineitem li ON li.invoice_id = i.id
   WHERE li.id IS NULL AND i.total_amount <> 0;
   ```

4. **Orphaned payment allocations**
   ```sql
   SELECT id, payment_id, invoice_id, amount
   FROM fees_paymentlineitem
   WHERE category_id IS NULL AND invoice_id IS NOT NULL;
   ```

5. **Category and price history**
   ```sql
   SELECT id, name, billing_cycle, is_active FROM fees_feecategory ORDER BY name;
   SELECT id, category_id, scope, school_class_id, term_id, amount, name
   FROM fees_feeprice ORDER BY category_id, term_id;
   ```
   Compare against any surviving export or provider records.

6. **Prices with no term (the `0017` NULL trap survivors)**
   ```sql
   SELECT COUNT(*) FROM fees_feeprice WHERE term_id IS NULL;
   ```
   In a school with a current term, a count of zero is consistent with `0017` having deleted them.

7. **Reset and audit trails**
   ```sql
   SELECT * FROM fees_invoiceresetlog ORDER BY id;
   SELECT * FROM core_auditlog ORDER BY id;
   ```
   Establishes whether operators also deleted data after the migrations.

8. **Provider-side records**
   - Paystack transaction exports (charges, references, amounts, dates).
   - Provider dashboard reconciliation against `fees_payment`.
   - Email/Brevo delivery logs for receipts and payment confirmations.

9. **Receipts and documents**
   - `fees_feereceipt` rows.
   - Any PDF/printed receipts retained by schools, which can prove what was billed even if line items are gone.

10. **Existing audit harness**
    - `scripts/audit/phase0_queries.py` already defines Q-01…Q-10 and IC-8/9/10 for historical-loss evidence.
    - It has been executed only against SQLite synthetic fixtures (`PASS_WITH_POSTGRES_NOT_RUN`), not against a production restore.

### 5.4 Minimum evidence set for a quantified answer

At minimum, a defensible quantification needs:

1. A **pre-migration** database copy (or PITR restore) from before `0017`.
2. A **post-migration** copy, or read-only access to current production.
3. Confirmation from `django_migrations` that the migrations ran in that environment.
4. The reconciliation queries in §5.3, run against both copies.
5. Provider-side payment records to cross-check what was actually charged.

Without items 1–3, any loss figure is an estimate, not a measurement.

---

## 6. Prioritized remediation recommendations (no implementation)

These are recommendations only. **Nothing in this section has been implemented.** Each item is marked with priority and the reason.

### P0 — Stop the bleeding (containment)

1. **Freeze destructive migrations.**
   Remove `migrate --noinput` from container start-up, or gate it behind an explicit, reviewed release step. A destructive `RunPython` must never be able to run unattended. *(Addresses the deploy-path risk directly.)*

2. **Disable or guard live hard-delete paths.**
   - Fee category delete: block when **either** `FeePrice` **or** `InvoiceLineItem` exists (not just `FeePrice`).
   - Fee price delete: replace with deactivate/version; block if referenced by any invoice line item.
   - Payment delete: replace with a reversal record; never hard-delete a confirmed payment.
   - Student delete: archive/deactivate; block hard delete when invoices, payments, or results exist.
   - Staff user delete: block when `Payment.recorded_by` or `Score.entered_by` exists, or convert those to `SET_NULL` first.
   - Class and subject delete: block when historical enrollments/scores exist.
   - Django admin: add project-wide `has_delete_permission` defaults for financial and academic models.

3. **Add confirmation and dry-run gates to management commands.**
   `clear_student_data`, `clear_student_payment_history`, and `scripts/reset_student_data.sql` need an explicit `--confirm`/typed confirmation, mandatory dry-run output, and an audit entry.

4. **Preserve the missing backup.**
   Locate and copy `backup_20260922_082845.sql.gz` (or its equivalent) to durable, access-controlled storage before any further migration work. Do not rely on Git history for backups.

### P1 — Stop future data-model loss

5. **Change `InvoiceLineItem.category` from `CASCADE` to `PROTECT` (preferred) or `SET_NULL`.**
   Line items are historical financial facts. Deleting a category must never delete them. Pair with a denormalized `category_name` snapshot captured at generation time.

6. **Change `Payment.recorded_by` and `Score.entered_by` from `CASCADE` to `SET_NULL` (or `PROTECT`).**
   Deleting a staff account must not delete money or marks. Keep the historical actor where possible; otherwise null it explicitly and record why.

7. **Add snapshot fields to financial line items.**
   At minimum: `category_name_snapshot`, `amount_snapshot`, and a `pricing_source` marker. This makes `0022`-style reconstruction unnecessary and auditable.

8. **Replace hard deletes with archive/deactivate/reversal records.**
   Use `is_active`, `archived_at`, or an explicit reversal model. Financial and academic records should be append-only.

9. **Reconcile invoice totals.**
   Add a preflight check and a repair path that recomputes or explains `Invoice.total_amount` against surviving line items. Do not silently rewrite unpaid invoices before the mismatch is documented.

### P2 — Migration safety rules

10. **No destructive `RunPython` without all of:**
    - a verified pre-migration backup,
    - a dry-run/count report,
    - an audit record,
    - a tested, data-restoring reverse (or an explicit, approved "irreversible" designation).

11. **Ban `.exclude(fk=value)` for nullable foreign keys in data migrations.**
    Use `Q(fk=value) | Q(fk__isnull=True)` / explicit `isnull` handling. Document the NULL-semantics trap in the migration guide.

12. **Make reverse functions real or fail loudly.**
    `noop` and `pass` reverses silently pretend rollback succeeded. Prefer `migrations.RunPython.noop` only when explicitly justified, and document it in the migration docstring and release notes.

13. **Add migration-level provenance.**
    When backfilling historical values, write a source marker (e.g. `name_source='backfill_0022'`) so reconstructed data is never mistaken for original data.

14. **Add a pre-deploy migration impact check.**
    A CI step that flags destructive `RunPython`, `CASCADE` on financial models, and migrations with no-op reverses.

### P3 — Audit and observability

15. **Extend `core/audit.py`** to cover `InvoiceLineItem`, `FeeReceipt`, `FeeCategory`, `FeePrice`, `Student`, `Term`, `ClassEnrollment`, and `TermResult`.

16. **Make `AuditLog` survive tenant deletion.**
    Do not cascade audit rows when a `School` is deleted; archive them to a separate store or detach the FK.

17. **Record full row snapshots on destructive operations, not just the fact of deletion.**

18. **Add a reconciliation report** (invoice total vs line items, orphan allocations, zero-line invoices) to the admin portal and to CI.

### Priority summary

| Priority | Items | Rationale |
|---|---|---|
| P0 | 1–4 | Prevent further loss; recover the missing backup. |
| P1 | 5–9 | Fix the data model so future deletes cannot destroy history. |
| P2 | 10–14 | Ensure no future migration repeats `0017`/`0018`/`0022`. |
| P3 | 15–18 | Make future loss detectable. |

---

## 7. PostgreSQL test-environment options and prerequisites

No PostgreSQL run was performed. Local environment check: `psql`, `pg_ctl`, `initdb`, and `postgres` are **not installed**; the Docker client is present but the socket permission is denied. All options below require an explicit decision and, in most cases, human authorization.

### 7.1 Options compared

| Option | What it gives | Prerequisites | Effort | Data-risk | Notes |
|---|---|---|---|---|---|
| **A. Existing GitHub Actions PostgreSQL 16 CI** | Real PostgreSQL 16 run of migrations and app tests, already configured in `.github/workflows/test.yml`. | A workflow change/push to run the audit harness; currently it runs app tests, not `scripts/audit/run_dialect_matrix.py`. | Low–Medium | None to production | Best first step. No credentials needed beyond the repo. Would require modifying CI, which is a code change and needs approval. |
| **B. Local Docker Compose `postgres:16-alpine`** | Full local PostgreSQL matching `docker-compose.yml`. | Docker socket access (currently denied); image pull. | Low | None to production | Fastest local parity if Docker access is granted. |
| **C. Local PostgreSQL install** | Native Postgres server/client. | Package installation and admin rights. | Medium | None to production | No container dependency, but modifies the machine. |
| **D. Ephemeral/managed PostgreSQL (cloud)** | Isolated instance for testing. | External resource, credentials, cost, data-handling review. | Medium–High | Low if synthetic-only | Only justified if A/B/C are unavailable. Must never receive production data. |
| **E. Django test database on PostgreSQL with fixtures** | Runs the audit queries inside `manage.py test` against a throwaway DB. | Postgres instance (A/B/C/D) plus a Postgres-compatible seeding path. | Medium | None | `scripts/audit/synthetic_fixtures.py` is SQLite-only, so parity requires a reviewed fixture loader. |
| **F. Production restore into a scratch environment** | The only option that measures **actual** loss. | A backup/PITR copy, an isolated environment, access controls, and explicit authorization. | High | High if mishandled | This is the only path to quantification, not just compatibility testing. Must be read-only and access-controlled. |

### 7.2 Recommended sequence

1. **Option A** to establish PostgreSQL compatibility of migrations and audit queries, using synthetic data only.
2. **Option B or C** for fast local iteration if A is too slow.
3. **Option F**, under strict controls, only when the goal shifts from "is the code safe?" to "how much did we actually lose?".

### 7.3 Prerequisites and constraints

- **PostgreSQL 16** to match CI and `docker-compose.yml`.
- `psycopg2-binary` is already in `requirements.txt`.
- The synthetic fixture loader (`scripts/audit/synthetic_fixtures.py`) is **SQLite-only**; PostgreSQL parity requires a reviewed seeding path or a Django-fixture equivalent. Do not assume the SQLite results transfer.
- `scripts/audit/run_dialect_matrix.py` already has a PostgreSQL branch but reports `NOT_RUN`. It must be executed, not assumed.
- Any production restore must be **read-only**, access-controlled, and destroyed after the analysis, with the destruction recorded.
- No production credentials should be requested or stored as part of this review.

### 7.4 What PostgreSQL testing would and would not prove

**Would prove:** migrations run on PostgreSQL; the audit queries execute; cascade/constraint behaviour matches Django's configuration; `__regex` behaves as expected on PostgreSQL (`~`, case-sensitive).

**Would not prove:** that production data was lost, or how much. Only Option F, against a real pre-migration copy, can answer that.

---

## 8. Go/no-go conclusions

### 8.1 Go/no-go by question

| Question | Verdict | Basis |
|---|---|---|
| Is the migration chain safe to re-run on a populated database? | **NO-GO** | `0017`, `0018`, `0020`, `0022` are destructive with `noop`/`pass` reverses. |
| Can the loss be quantified from the current environment? | **NO-GO** | No production data, no backup, no restored copy. |
| Is the current codebase safe from further historical loss? | **NO-GO** | Live hard-delete paths and `CASCADE` on financial/academic models remain. |
| Is PostgreSQL compatibility proven? | **NO-GO** | PostgreSQL was `NOT_RUN`; only SQLite synthetic runs exist. |
| Is there enough evidence to say data *was* lost? | **NO-GO (unproven)** | Code-proven capability, but no production occurrence evidence. |
| Is there enough evidence to say data was *not* lost? | **NO-GO (unproven)** | Absence of evidence, not evidence of absence. |
| Can development continue on non-destructive features? | **CONDITIONAL GO** | Allowed only if P0 containment is respected and no destructive migration is run. |
| Can the remaining audit work proceed read-only? | **GO** | The harness and queries are read-only by design. |

### 8.2 Overall verdict

**NO-GO for any further destructive migration, bulk reset, or hard-delete operation against a populated environment.**

**NO-GO for declaring the historical data loss question resolved.** The code proves the capability; the environment cannot prove the occurrence.

**CONDITIONAL GO for read-only investigation and for non-destructive development**, provided:

1. The missing backup is located and preserved first.
2. `migrate --noinput` is not allowed to run unattended against populated data.
3. No one runs `0017`/`0018`/`0020`/`0022` forward on a database whose history matters.
4. No one uses the live hard-delete paths in §3.2 against real data.

### 8.3 Conditions to move to GO

The verdict can move to **GO** for remediation only when all of the following are true:

1. A pre-migration backup or PITR restore exists and is verified restorable.
2. `django_migrations` confirms which destructive migrations actually ran, per environment.
3. The §5.3 reconciliation queries have been run against a restored copy, read-only.
4. P0 containment is in place (or an explicit, documented risk acceptance is signed).
5. PostgreSQL parity has been demonstrated by an actual run, not assumed.

### 8.4 Human approval decisions required

The following require an explicit human decision and are **not** made by this review:

| Decision | Options | Why it needs a human |
|---|---|---|
| Whether to treat loss as having occurred | Assume possible / await evidence | Affects school communication and remediation scope. |
| Whether to attempt a production restore | Yes / no / defer | Involves data handling, access, and cost. |
| Whether to change `on_delete` behaviour | `PROTECT` vs `SET_NULL` | Affects deletion workflows and retention policy. |
| Whether to disable admin hard deletes | Immediately / staged | Affects operations. |
| Whether to modify CI to run the PostgreSQL audit harness | Yes / no | CI is code and affects the shared pipeline. |
| Whether to retain or purge the referenced backup | Retain / purge | Retention and privacy obligations. |
| Whether to notify affected schools | Yes / no / pending evidence | Legal and reputational. |

---

## Appendix A — Evidence collected in this review

| Artefact | Location | Nature |
|---|---|---|
| Baseline `git status` | `/tmp/opencode/git_status_initial.txt` | Outside repo. |
| Baseline HEAD | `/tmp/opencode/git_head_initial.txt` | `8a1bdcc…`. |
| Unstaged diff snapshot | `/tmp/opencode/git_diff_unstaged_initial.patch` | Read-only copy. |
| Tree hashes | `/tmp/opencode/tree_hashes_initial.txt` | Integrity baseline. |
| Migration source | `fees/migrations/0017…`, `0018…`, `0022…` | Read-only. |
| Deletion inventory | `docs/audit/DELETION_INVENTORY.md` | Prior user work, cited, not modified. |
| Readiness report | `docs/audit/READINESS_REPORT.md` | Prior user work, cited, not modified. |
| Dialect matrix | `docs/audit/DIALECT_MATRIX.md` | PostgreSQL `NOT_RUN`. |
| Audit harness | `scripts/audit/phase0_queries.py`, `run_dialect_matrix.py` | Read-only; not executed against PostgreSQL. |
| CI definition | `.github/workflows/test.yml` | PostgreSQL 16 service. |
| Deploy definition | `.github/workflows/deploy.yml`, `entrypoint.sh` | Auto-migrate on start. |

## Appendix B — Integrity statement

This review was conducted read-only. No application code, migration, model, test, database, or Git object was modified, staged, committed, reverted, or cleaned. No migration was run. No record was deleted. No production system was contacted. Temporary artefacts were written under `/tmp/opencode` only. The only repository change is the addition of this document at `docs/audit/HISTORICAL_DATA_LOSS_REVIEW.md`.
