# Phase 0 Audit Query Specification

**Catalogue version:** `phase0-r01-1.0.0`
**Owner:** Backend engineering (readiness workstream R-01)
**Status:** All queries are **DRAFT** in source. None has been executed against production.

> **Draft vs executed.** `DRAFT` means authored, identifier-validated, and kept
> read-only. It does not mean "run against real data". The only executions
> recorded for this batch are against the deterministic synthetic SQLite
> database; they are recorded in `docs/audit/READINESS_REPORT.md` and in an
> evidence pack created with `scripts/audit/evidence.py`. PostgreSQL was **not**
> available in this environment and is marked **NOT RUN**. No production
> connection was made.

## Status legend

| Status | Meaning |
|---|---|
| `DRAFT` | Authored and reviewed for read-only syntax; not production-executed. |
| `EXECUTED` | Reserved for a query with a matching evidence record naming id + version + environment. The source catalogue never sets this itself. |

## Required identifiers

- Core audit: Q-01, Q-02, Q-03, Q-04, Q-05, Q-06, Q-07, Q-08, Q-09, Q-10
- Supplementary readiness checks: IC-8, IC-9, IC-10

Supplementary checks are deliberately named `IC-*` so they are never confused
with the ten core audit queries.

## Execution status in this batch

| Query set | Authored | Identifier-validated | Synthetic SQLite | PostgreSQL | Production |
|---|---|---|---|---|---|
| Q-01 … Q-10 | Yes | Yes | Yes (2026-10-23) | **NOT RUN** | **No** |
| IC-8 … IC-10 | Yes | Yes | Yes (2026-10-23) | **NOT RUN** | **No** |

## Summary

| ID | Version | Title | Result grain | Status |
|---|---|---|---|---|
| `Q-01` | `1.0.0` | Invoice counts and totals by term and derived status | one row per (session, term, derived status) | `DRAFT` |
| `Q-02` | `1.0.0` | Line-item totals by category and term | one row per (term, category, billing cycle) | `DRAFT` |
| `Q-03` | `1.0.0` | Payment counts and totals by term and status | one row per (term, payment status) | `DRAFT` |
| `Q-04` | `1.0.0` | Receipt coverage and orphan receipts | one row per receipt-integrity check | `DRAFT` |
| `Q-05` | `1.0.0` | Outstanding balances per invoice | one row per invoice with a positive outstanding balance | `DRAFT` |
| `Q-06` | `1.0.0` | Duplicate fee-price scopes | one row per duplicated scope key | `DRAFT` |
| `Q-07` | `1.0.0` | Ambiguous student classification | one row per (school, student_type, registration-link state) | `DRAFT` |
| `Q-08` | `1.0.0` | One-time fee usage across sessions | one row per billed ONE_TIME category | `DRAFT` |
| `Q-09` | `1.0.0` | Cross-school and orphan references | one row per cross-school/orphan check, always present | `DRAFT` |
| `Q-10` | `1.0.0` | Fee-category deletion exposure | one row per deletion-exposed fee category | `DRAFT` |
| `IC-8` | `1.0.0` | Historical loss indicators from migrations 0017/0018 | one row per historical-loss indicator, always present | `DRAFT` |
| `IC-9` | `1.0.0` | Historical snapshot provenance indicators | one row per snapshot indicator, always present | `DRAFT` |
| `IC-10` | `1.0.0` | Live deletion exposure counts | one row per deletion-exposure check, always present | `DRAFT` |

---

## Query details

Each section lists the exact identifiers the validator checks. `schema_refs` is authoritative for table/column existence; the SQL text is additionally scanned for table references by the validator. Identifier validation is not semantic proof.

### `Q-01` — Invoice counts and totals by term and derived status

- **Version:** `1.0.0`
- **Status:** `DRAFT`
- **Requirement:** FINAL_GO_NOGO_CORRECTIONS.md §3, Q-01
- **Result grain:** one row per (session, term, derived status)
- **Purpose:** Establish the invoice baseline per term and per derived payment status, including balances.

**Required tables and columns**

| Table | Columns |
|---|---|
| `fees_invoice` | `id`, `term_id`, `total_amount` |
| `core_term` | `id`, `name`, `session_id` |
| `core_academicsession` | `id`, `name` |
| `fees_payment` | `invoice_id`, `status`, `amount` |

**Expected output columns**

`term_id`, `term_name`, `session_id`, `session_name`, `derived_status`, `invoice_count`, `invoice_total`, `paid_total`, `balance_total`

**SQL (portable/SQLite form)**

```sql
SELECT
                t.id AS term_id,
                t.name AS term_name,
                s.id AS session_id,
                s.name AS session_name,
                CASE
                    WHEN COALESCE(p.paid, 0) >= i.total_amount AND i.total_amount > 0 THEN 'PAID'
                    WHEN COALESCE(p.paid, 0) > 0 THEN 'PARTIAL'
                    ELSE 'UNPAID'
                END AS derived_status,
                COUNT(*) AS invoice_count,
                SUM(i.total_amount) AS invoice_total,
                SUM(COALESCE(p.paid, 0)) AS paid_total,
                SUM(i.total_amount - COALESCE(p.paid, 0)) AS balance_total
            FROM fees_invoice i
            JOIN core_term t ON t.id = i.term_id
            JOIN core_academicsession s ON s.id = t.session_id
            LEFT JOIN (
                SELECT invoice_id, SUM(amount) AS paid
                FROM fees_payment
                WHERE status = 'CONFIRMED'
                GROUP BY invoice_id
            ) p ON p.invoice_id = i.id
            GROUP BY t.id, t.name, s.id, s.name, derived_status
            ORDER BY s.id, t.id, derived_status
```

**Dialect considerations.** GROUP BY an output alias is supported by both SQLite and PostgreSQL. Aggregates over DECIMAL return numeric on PostgreSQL and may return REAL on SQLite; compare rounded values, not raw floats.

**Interpretation.** `Invoice.status` is a Python property, not a database column. The query therefore derives PAID/PARTIAL/UNPAID from CONFIRMED payments. PENDING and FAILED payments are excluded, matching `Invoice.amount_paid`. A negative `balance_total` is an overpayment and must be investigated, not clamped.

**Deviation from the written requirement.** The source draft grouped by `Invoice.status`. No such column exists; the query derives it instead of silently dropping the dimension.

---

### `Q-02` — Line-item totals by category and term

- **Version:** `1.0.0`
- **Status:** `DRAFT`
- **Requirement:** FINAL_GO_NOGO_CORRECTIONS.md §3, Q-02
- **Result grain:** one row per (term, category, billing cycle)
- **Purpose:** Establish the line-item baseline and count historical rows whose denormalised `item_name` snapshot is missing.

**Required tables and columns**

| Table | Columns |
|---|---|
| `fees_invoicelineitem` | `id`, `invoice_id`, `term_id`, `category_id`, `amount`, `item_name` |
| `core_term` | `id`, `name` |
| `fees_feecategory` | `id`, `name`, `billing_cycle` |

**Expected output columns**

`term_id`, `term_name`, `category_id`, `category_name`, `billing_cycle`, `line_item_count`, `line_item_total`, `missing_snapshot_count`

**SQL (portable/SQLite form)**

```sql
SELECT
                t.id AS term_id,
                t.name AS term_name,
                c.id AS category_id,
                c.name AS category_name,
                c.billing_cycle,
                COUNT(li.id) AS line_item_count,
                SUM(li.amount) AS line_item_total,
                SUM(CASE WHEN li.item_name IS NULL OR li.item_name = '' THEN 1 ELSE 0 END)
                    AS missing_snapshot_count
            FROM fees_invoicelineitem li
            LEFT JOIN core_term t ON t.id = li.term_id
            LEFT JOIN fees_feecategory c ON c.id = li.category_id
            GROUP BY t.id, t.name, c.id, c.name, c.billing_cycle
            ORDER BY t.id, c.id
```

**Dialect considerations.** LEFT JOIN is used deliberately: an orphan category or term must not remove the line item from the baseline. There is no join to fees_invoice, so line items whose invoice row is missing are still counted here; Q-09 reports them as orphans. NULL grouping is identical for GROUP BY on both engines (NULLs group together), unlike unique indexes (NULLs are distinct on PostgreSQL).

**Interpretation.** `missing_snapshot_count` counts rows with NULL or empty `item_name`. A non-zero value feeds PD-04; it does not by itself prove the row predates migration 0022. `term_id` is nullable on line items, so NULL appears as its own group.

**Deviation from the written requirement.** The initial draft inner-joined fees_invoice, which silently dropped line items with a missing invoice. The join was removed so the baseline cannot hide orphan rows.

---

### `Q-03` — Payment counts and totals by term and status

- **Version:** `1.0.0`
- **Status:** `DRAFT`
- **Requirement:** FINAL_GO_NOGO_CORRECTIONS.md §3, Q-03
- **Result grain:** one row per (term, payment status)
- **Purpose:** Establish the payment baseline, including PENDING and FAILED.

**Required tables and columns**

| Table | Columns |
|---|---|
| `fees_payment` | `id`, `invoice_id`, `status`, `amount` |
| `fees_invoice` | `id`, `term_id` |
| `core_term` | `id`, `name` |

**Expected output columns**

`term_id`, `term_name`, `status`, `payment_count`, `payment_total`

**SQL (portable/SQLite form)**

```sql
SELECT
                t.id AS term_id,
                t.name AS term_name,
                p.status,
                COUNT(*) AS payment_count,
                SUM(p.amount) AS payment_total
            FROM fees_payment p
            JOIN fees_invoice i ON i.id = p.invoice_id
            JOIN core_term t ON t.id = i.term_id
            GROUP BY t.id, t.name, p.status
            ORDER BY t.id, p.status
```

**Dialect considerations.** No dialect-specific syntax. `status` is a text column.

**Interpretation.** Payments without an invoice are intentionally excluded here; Q-09 counts them as orphans. Compare with Q-01 paid totals to detect allocation or status drift.

---

### `Q-04` — Receipt coverage and orphan receipts

- **Version:** `1.0.0`
- **Status:** `DRAFT`
- **Requirement:** FINAL_GO_NOGO_CORRECTIONS.md §3, Q-04
- **Result grain:** one row per receipt-integrity check
- **Purpose:** Count confirmed payments without a receipt, receipts without a payment, and duplicate receipts per payment.

**Required tables and columns**

| Table | Columns |
|---|---|
| `fees_payment` | `id`, `status` |
| `fees_feereceipt` | `id`, `payment_id` |

**Expected output columns**

`check_name`, `record_count`

**SQL (portable/SQLite form)**

```sql
SELECT 'confirmed_payment_without_receipt' AS check_name,
                   COUNT(*) AS record_count
            FROM fees_payment p
            LEFT JOIN fees_feereceipt r ON r.payment_id = p.id
            WHERE p.status = 'CONFIRMED' AND r.id IS NULL
            UNION ALL
            SELECT 'receipt_without_payment', COUNT(*)
            FROM fees_feereceipt r
            LEFT JOIN fees_payment p ON p.id = r.payment_id
            WHERE p.id IS NULL
            UNION ALL
            SELECT 'duplicate_receipts_per_payment', COUNT(*)
            FROM (
                SELECT payment_id
                FROM fees_feereceipt
                GROUP BY payment_id
                HAVING COUNT(*) > 1
            ) duplicates
            ORDER BY check_name
```

**Dialect considerations.** The derived table alias is required by PostgreSQL. `UNION ALL` preserves duplicate check names, though names are constructed to be unique.

**Interpretation.** `FeeReceipt.payment` is a non-null OneToOneField, so `receipt_without_payment` can only be non-zero if the database lost referential integrity (or was seeded with corruption). `duplicate_receipts_per_payment` counts payments with more than one receipt, which the ORM constraint should prevent.

---

### `Q-05` — Outstanding balances per invoice

- **Version:** `1.0.0`
- **Status:** `DRAFT`
- **Requirement:** FINAL_GO_NOGO_CORRECTIONS.md §3, Q-05
- **Result grain:** one row per invoice with a positive outstanding balance
- **Purpose:** List invoices whose total exceeds the sum of CONFIRMED payments, with school, student and term context.

**Required tables and columns**

| Table | Columns |
|---|---|
| `fees_invoice` | `id`, `school_id`, `student_id`, `term_id`, `total_amount` |
| `students_student` | `id`, `admission_number` |
| `core_term` | `id`, `name` |
| `fees_payment` | `invoice_id`, `status`, `amount` |

**Expected output columns**

`invoice_id`, `school_id`, `student_id`, `admission_number`, `term_id`, `term_name`, `total_amount`, `amount_paid`, `balance`

**SQL (portable/SQLite form)**

```sql
SELECT
                i.id AS invoice_id,
                i.school_id,
                i.student_id,
                st.admission_number,
                t.id AS term_id,
                t.name AS term_name,
                i.total_amount,
                COALESCE(p.paid, 0) AS amount_paid,
                i.total_amount - COALESCE(p.paid, 0) AS balance
            FROM fees_invoice i
            JOIN students_student st ON st.id = i.student_id
            JOIN core_term t ON t.id = i.term_id
            LEFT JOIN (
                SELECT invoice_id, SUM(amount) AS paid
                FROM fees_payment
                WHERE status = 'CONFIRMED'
                GROUP BY invoice_id
            ) p ON p.invoice_id = i.id
            WHERE i.total_amount - COALESCE(p.paid, 0) > 0
            ORDER BY balance DESC, i.id
```

**Dialect considerations.** ORDER BY an output alias is supported by both engines. Decimal arithmetic follows the column type; SQLite may surface REAL.

**Interpretation.** A row is outstanding by the same definition used by `Invoice.amount_paid`: only CONFIRMED payments count. This query returns student admission numbers, so evidence output must be redacted before storage.

---

### `Q-06` — Duplicate fee-price scopes

- **Version:** `1.0.0`
- **Status:** `DRAFT`
- **Requirement:** FINAL_GO_NOGO_CORRECTIONS.md §3, Q-06; PHASE0_READINESS_PLAN V19
- **Result grain:** one row per duplicated scope key
- **Purpose:** Find FeePrice rows that share every scope key, including nullable class/level/term values.

**Required tables and columns**

| Table | Columns |
|---|---|
| `fees_feeprice` | `id`, `school_id`, `scope`, `category_id`, `student_type`, `school_class_id`, `level`, `term_id` |

**Expected output columns**

`school_id`, `scope`, `category_id`, `student_type`, `school_class_id`, `level`, `term_id`, `duplicate_count`, `min_price_id`, `max_price_id`

**SQL (portable/SQLite form)**

```sql
SELECT
                p.school_id,
                p.scope,
                p.category_id,
                p.student_type,
                p.school_class_id,
                p.level,
                p.term_id,
                COUNT(*) AS duplicate_count,
                MIN(p.id) AS min_price_id,
                MAX(p.id) AS max_price_id
            FROM fees_feeprice p
            GROUP BY
                p.school_id,
                p.scope,
                p.category_id,
                p.student_type,
                p.school_class_id,
                p.level,
                p.term_id
            HAVING COUNT(*) > 1
            ORDER BY duplicate_count DESC, p.school_id, p.category_id
```

**Dialect considerations.** Both engines group NULLs together. On PostgreSQL the existing `unique_together` does not prevent these rows because nullable columns make the index entries distinct. `MIN`/`MAX` are used instead of `GROUP_CONCAT`/`STRING_AGG` to keep one portable query.

**Interpretation.** GROUP BY treats NULLs as equal, so a school-wide or one-time price with NULL class/level/term is compared correctly. This is exactly where the database unique constraint does **not** protect PostgreSQL: NULLs are distinct in a unique index. Any row is a resolution ambiguity and blocks cutover.

---

### `Q-07` — Ambiguous student classification

- **Version:** `1.0.0`
- **Status:** `DRAFT`
- **Requirement:** FINAL_GO_NOGO_CORRECTIONS.md §3, Q-07
- **Result grain:** one row per (school, student_type, registration-link state)
- **Purpose:** Break students down by student_type and whether a registration term is linked, exposing classification ambiguity.

**Required tables and columns**

| Table | Columns |
|---|---|
| `students_student` | `id`, `school_id`, `student_type`, `registration_paid_term_id` |

**Expected output columns**

`school_id`, `student_type`, `registration_link`, `student_count`, `returning_without_registration_term`

**SQL (portable/SQLite form)**

```sql
SELECT
                st.school_id,
                st.student_type,
                CASE
                    WHEN st.registration_paid_term_id IS NULL THEN 'no_registration_term'
                    ELSE 'has_registration_term'
                END AS registration_link,
                COUNT(*) AS student_count,
                SUM(
                    CASE
                        WHEN st.student_type = 'RETURNING'
                             AND st.registration_paid_term_id IS NULL THEN 1
                        ELSE 0
                    END
                ) AS returning_without_registration_term
            FROM students_student st
            GROUP BY st.school_id, st.student_type, registration_link
            ORDER BY st.school_id, st.student_type, registration_link
```

**Dialect considerations.** No dialect-specific syntax; GROUP BY an output alias is portable.

**Interpretation.** `returning_without_registration_term > 0` is a review candidate, not automatically an error. Pair this with payment evidence before changing any classification (PD-02).

**Deviation from the written requirement.** The source draft referenced `Student.classification_review_required`, which does not exist in the working tree. This query uses only the real columns `student_type` and `registration_paid_term_id`; it must not be read as a check for a review flag that is not modelled.

---

### `Q-08` — One-time fee usage across sessions

- **Version:** `1.0.0`
- **Status:** `DRAFT`
- **Requirement:** FINAL_GO_NOGO_CORRECTIONS.md §3, Q-08
- **Result grain:** one row per billed ONE_TIME category
- **Purpose:** Show which ONE_TIME categories have been billed, how many invoices and sessions they touch, and the total amount.

**Required tables and columns**

| Table | Columns |
|---|---|
| `fees_feecategory` | `id`, `school_id`, `name`, `billing_cycle` |
| `fees_invoicelineitem` | `id`, `invoice_id`, `category_id`, `session_id`, `amount` |

**Expected output columns**

`category_id`, `school_id`, `category_name`, `invoice_count`, `line_item_count`, `session_count`, `first_session_id`, `last_session_id`, `total_billed`

**SQL (portable/SQLite form)**

```sql
SELECT
                c.id AS category_id,
                c.school_id,
                c.name AS category_name,
                COUNT(DISTINCT li.invoice_id) AS invoice_count,
                COUNT(li.id) AS line_item_count,
                COUNT(DISTINCT li.session_id) AS session_count,
                MIN(li.session_id) AS first_session_id,
                MAX(li.session_id) AS last_session_id,
                COALESCE(SUM(li.amount), 0) AS total_billed
            FROM fees_feecategory c
            LEFT JOIN fees_invoicelineitem li ON li.category_id = c.id
            WHERE c.billing_cycle = 'ONE_TIME'
            GROUP BY c.id, c.school_id, c.name
            HAVING COUNT(li.id) > 0
            ORDER BY c.school_id, c.id
```

**Dialect considerations.** `COUNT(DISTINCT ...)` ignores NULLs on both engines. `COALESCE` returns 0 for an unaggregated SUM.

**Interpretation.** `session_count > 1` is direct evidence that a supposedly one-time fee was billed in more than one session. It informs PD-01 but does not decide the policy.

---

### `Q-09` — Cross-school and orphan references

- **Version:** `1.0.0`
- **Status:** `DRAFT`
- **Requirement:** FINAL_GO_NOGO_CORRECTIONS.md §3, Q-09; PHASE0_READINESS_PLAN C.2
- **Result grain:** one row per cross-school/orphan check, always present
- **Purpose:** Count tenant-integrity violations and orphan foreign keys across the fee graph, including explicit NULL-school line items.

**Required tables and columns**

| Table | Columns |
|---|---|
| `fees_feeprice` | `id`, `school_id`, `category_id` |
| `fees_feecategory` | `id`, `school_id` |
| `fees_invoicelineitem` | `id`, `school_id`, `invoice_id`, `category_id` |
| `fees_invoice` | `id`, `school_id` |
| `fees_payment` | `id`, `school_id`, `invoice_id`, `student_id` |
| `students_student` | `id`, `school_id` |
| `fees_paymentlineitem` | `id`, `payment_id`, `school_id`, `invoice_id` |
| `fees_feepriceoverride` | `id`, `school_id`, `student_id`, `category_id` |

**Expected output columns**

`check_name`, `violation_count`, `sample_id`

**SQL (portable/SQLite form)**

```sql
SELECT 'feeprice_category_cross_school' AS check_name,
                   COUNT(*) AS violation_count,
                   MIN(p.id) AS sample_id
            FROM fees_feeprice p
            JOIN fees_feecategory c ON c.id = p.category_id
            WHERE p.school_id <> c.school_id
            UNION ALL
            SELECT 'feeprice_category_orphan', COUNT(*), MIN(p.id)
            FROM fees_feeprice p
            LEFT JOIN fees_feecategory c ON c.id = p.category_id
            WHERE c.id IS NULL
            UNION ALL
            SELECT 'lineitem_invoice_cross_school', COUNT(*), MIN(li.id)
            FROM fees_invoicelineitem li
            JOIN fees_invoice i ON i.id = li.invoice_id
            WHERE li.school_id IS NOT NULL AND li.school_id <> i.school_id
            UNION ALL
            SELECT 'lineitem_invoice_orphan', COUNT(*), MIN(li.id)
            FROM fees_invoicelineitem li
            LEFT JOIN fees_invoice i ON i.id = li.invoice_id
            WHERE i.id IS NULL
            UNION ALL
            SELECT 'lineitem_category_cross_school', COUNT(*), MIN(li.id)
            FROM fees_invoicelineitem li
            JOIN fees_feecategory c ON c.id = li.category_id
            WHERE li.school_id IS NOT NULL AND li.school_id <> c.school_id
            UNION ALL
            SELECT 'lineitem_category_orphan', COUNT(*), MIN(li.id)
            FROM fees_invoicelineitem li
            LEFT JOIN fees_feecategory c ON c.id = li.category_id
            WHERE c.id IS NULL
            UNION ALL
            SELECT 'lineitem_school_null', COUNT(*), MIN(li.id)
            FROM fees_invoicelineitem li
            WHERE li.school_id IS NULL
            UNION ALL
            SELECT 'payment_invoice_cross_school', COUNT(*), MIN(p.id)
            FROM fees_payment p
            JOIN fees_invoice i ON i.id = p.invoice_id
            WHERE p.school_id <> i.school_id
            UNION ALL
            SELECT 'payment_invoice_orphan', COUNT(*), MIN(p.id)
            FROM fees_payment p
            LEFT JOIN fees_invoice i ON i.id = p.invoice_id
            WHERE p.invoice_id IS NOT NULL AND i.id IS NULL
            UNION ALL
            SELECT 'payment_student_cross_school', COUNT(*), MIN(p.id)
            FROM fees_payment p
            JOIN students_student s ON s.id = p.student_id
            WHERE p.school_id <> s.school_id
            UNION ALL
            SELECT 'payment_student_orphan', COUNT(*), MIN(p.id)
            FROM fees_payment p
            LEFT JOIN students_student s ON s.id = p.student_id
            WHERE p.student_id IS NOT NULL AND s.id IS NULL
            UNION ALL
            SELECT 'paymentlineitem_payment_cross_school', COUNT(*), MIN(pli.id)
            FROM fees_paymentlineitem pli
            JOIN fees_payment p ON p.id = pli.payment_id
            WHERE pli.school_id IS NOT NULL AND pli.school_id <> p.school_id
            UNION ALL
            SELECT 'paymentlineitem_payment_orphan', COUNT(*), MIN(pli.id)
            FROM fees_paymentlineitem pli
            LEFT JOIN fees_payment p ON p.id = pli.payment_id
            WHERE p.id IS NULL
            UNION ALL
            SELECT 'paymentlineitem_invoice_cross_school', COUNT(*), MIN(pli.id)
            FROM fees_paymentlineitem pli
            JOIN fees_invoice i ON i.id = pli.invoice_id
            WHERE pli.school_id IS NOT NULL AND pli.school_id <> i.school_id
            UNION ALL
            SELECT 'override_student_cross_school', COUNT(*), MIN(o.id)
            FROM fees_feepriceoverride o
            JOIN students_student s ON s.id = o.student_id
            WHERE o.school_id <> s.school_id
            UNION ALL
            SELECT 'override_student_orphan', COUNT(*), MIN(o.id)
            FROM fees_feepriceoverride o
            LEFT JOIN students_student s ON s.id = o.student_id
            WHERE s.id IS NULL
            UNION ALL
            SELECT 'override_category_cross_school', COUNT(*), MIN(o.id)
            FROM fees_feepriceoverride o
            JOIN fees_feecategory c ON c.id = o.category_id
            WHERE o.school_id <> c.school_id
            UNION ALL
            SELECT 'override_category_orphan', COUNT(*), MIN(o.id)
            FROM fees_feepriceoverride o
            LEFT JOIN fees_feecategory c ON c.id = o.category_id
            WHERE c.id IS NULL
            ORDER BY check_name
```

**Dialect considerations.** All comparisons are against the parent's `school_id`, never a constant. Nullable child `school_id` has an explicit `IS NOT NULL` guard, with NULL counted separately. Orphan checks use LEFT JOIN with an `IS NULL` branch. Types in every UNION ALL branch match.

**Interpretation.** Every branch returns exactly one row, even when the count is zero, so absence of a row is itself a query defect. `lineitem_school_null` is expected for application-created line items (PHASE0_READINESS_PLAN V11) and is a classification input, not automatically corruption. `sample_id` is an internal row id and must not be interpreted as a business key.

---

### `Q-10` — Fee-category deletion exposure

- **Version:** `1.0.0`
- **Status:** `DRAFT`
- **Requirement:** FINAL_GO_NOGO_CORRECTIONS.md §3, Q-10; PHASE0_READINESS_PLAN V8
- **Result grain:** one row per deletion-exposed fee category
- **Purpose:** Quantify the records that would be destroyed or orphaned if a fee category were deleted through the current CASCADE path.

**Required tables and columns**

| Table | Columns |
|---|---|
| `fees_feecategory` | `id`, `school_id`, `name` |
| `fees_invoicelineitem` | `id`, `category_id`, `invoice_id`, `amount` |
| `fees_feeprice` | `id`, `category_id` |
| `fees_feepriceoverride` | `id`, `category_id` |
| `fees_paymentlineitem` | `id`, `category_id` |

**Expected output columns**

`category_id`, `school_id`, `category_name`, `line_item_count`, `invoice_count`, `line_item_total`, `price_count`, `override_count`, `payment_allocation_count`

**SQL (portable/SQLite form)**

```sql
SELECT risk.*
            FROM (
                SELECT
                    c.id AS category_id,
                    c.school_id,
                    c.name AS category_name,
                    COUNT(li.id) AS line_item_count,
                    COUNT(DISTINCT li.invoice_id) AS invoice_count,
                    COALESCE(SUM(li.amount), 0) AS line_item_total,
                    (SELECT COUNT(*) FROM fees_feeprice p
                     WHERE p.category_id = c.id) AS price_count,
                    (SELECT COUNT(*) FROM fees_feepriceoverride o
                     WHERE o.category_id = c.id) AS override_count,
                    (SELECT COUNT(*) FROM fees_paymentlineitem pli
                     WHERE pli.category_id = c.id) AS payment_allocation_count
                FROM fees_feecategory c
                LEFT JOIN fees_invoicelineitem li ON li.category_id = c.id
                GROUP BY c.id, c.school_id, c.name
            ) risk
            WHERE risk.line_item_count > 0
               OR risk.price_count > 0
               OR risk.override_count > 0
               OR risk.payment_allocation_count > 0
            ORDER BY risk.line_item_count DESC, risk.category_id
```

**Dialect considerations.** The outer SELECT avoids aliases in HAVING, which is not portable. Correlated scalar subqueries are standard SQL. `LIMIT` is not used so a reviewer sees every exposed category.

**Interpretation.** Any row with `line_item_count > 0` is historical financial data. The current `FeeCategoryDeleteView` only blocks deletion when a FeePrice exists, so a category with line items but no price can be deleted and cascade-delete those lines. This query must never be followed by a delete.

---

### `IC-8` — Historical loss indicators from migrations 0017/0018

- **Version:** `1.0.0`
- **Status:** `DRAFT`
- **Requirement:** PHASE0_READINESS_PLAN §C.4, IC-8
- **Result grain:** one row per historical-loss indicator, always present
- **Purpose:** Surface invoice/line-item mismatches, invoices with no lines, orphan categories, and terms with no active price.

**Required tables and columns**

| Table | Columns |
|---|---|
| `fees_invoice` | `id`, `total_amount` |
| `fees_invoicelineitem` | `id`, `invoice_id`, `amount`, `category_id` |
| `fees_feecategory` | `id` |
| `core_term` | `id` |
| `fees_feeprice` | `id`, `term_id`, `is_active` |

**Expected output columns**

`check_name`, `record_count`, `sample_id`

**SQL (portable/SQLite form)**

```sql
SELECT 'invoice_total_mismatch' AS check_name,
                   COUNT(*) AS record_count,
                   MIN(x.invoice_id) AS sample_id
            FROM (
                SELECT i.id AS invoice_id
                FROM fees_invoice i
                LEFT JOIN fees_invoicelineitem li ON li.invoice_id = i.id
                GROUP BY i.id, i.total_amount
                HAVING ROUND(i.total_amount - COALESCE(SUM(li.amount), 0), 2) <> 0
            ) x
            UNION ALL
            SELECT 'invoice_without_line_items', COUNT(*), MIN(i.id)
            FROM fees_invoice i
            LEFT JOIN fees_invoicelineitem li ON li.invoice_id = i.id
            WHERE li.id IS NULL
            UNION ALL
            SELECT 'line_item_without_category', COUNT(*), MIN(li.id)
            FROM fees_invoicelineitem li
            LEFT JOIN fees_feecategory c ON c.id = li.category_id
            WHERE c.id IS NULL
            UNION ALL
            SELECT 'term_without_active_price', COUNT(*), MIN(t.id)
            FROM core_term t
            WHERE NOT EXISTS (
                SELECT 1
                FROM fees_feeprice p
                WHERE p.term_id = t.id AND p.is_active = TRUE
            )
            ORDER BY check_name
```

**Dialect considerations.** `ROUND(numeric, 2)` works on both engines; SQLite treats the value as REAL. `is_active = TRUE` is valid on SQLite >= 3.23 and on PostgreSQL. Boolean storage differs (0/1 vs true/false) but the comparison is portable.

**Interpretation.** `invoice_total_mismatch` includes invoices with no lines. Migration 0018 may have cascade-deleted lines, so a mismatch is consistent with historical loss but is not proof of cause. `term_without_active_price` may be legitimate for a future term.

---

### `IC-9` — Historical snapshot provenance indicators

- **Version:** `1.0.0`
- **Status:** `DRAFT`
- **Requirement:** PHASE0_READINESS_PLAN §C.4, IC-9
- **Result grain:** one row per snapshot indicator, always present
- **Purpose:** Count line items with no captured name and line items whose name is identical to the current category name.

**Required tables and columns**

| Table | Columns |
|---|---|
| `fees_invoicelineitem` | `id`, `item_name`, `category_id` |
| `fees_feecategory` | `id`, `name` |

**Expected output columns**

`check_name`, `record_count`, `sample_id`

**SQL (portable/SQLite form)**

```sql
SELECT 'missing_item_name' AS check_name,
                   COUNT(*) AS record_count,
                   MIN(li.id) AS sample_id
            FROM fees_invoicelineitem li
            WHERE li.item_name IS NULL OR li.item_name = ''
            UNION ALL
            SELECT 'item_name_equals_current_category', COUNT(*), MIN(li.id)
            FROM fees_invoicelineitem li
            JOIN fees_feecategory c ON c.id = li.category_id
            WHERE li.item_name <> '' AND li.item_name = c.name
            ORDER BY check_name
```

**Dialect considerations.** Text equality uses the database collation. PostgreSQL may use a locale collation while SQLite defaults to BINARY, so case/space variants can classify differently.

**Interpretation.** `item_name_equals_current_category` does **not** prove the value was written by migration 0022; without a provenance marker the two cases are indistinguishable. This is evidence for PD-04, not a verdict.

---

### `IC-10` — Live deletion exposure counts

- **Version:** `1.0.0`
- **Status:** `DRAFT`
- **Requirement:** PHASE0_READINESS_PLAN §C.4, IC-10; V6–V8
- **Result grain:** one row per deletion-exposure check, always present
- **Purpose:** Count records that current application delete paths would destroy through cascades.

**Required tables and columns**

| Table | Columns |
|---|---|
| `fees_invoicelineitem` | `id`, `invoice_id` |
| `fees_feereceipt` | `id` |
| `fees_invoice` | `id`, `student_id` |
| `fees_payment` | `id`, `student_id`, `recorded_by_id` |
| `academics_score` | `id`, `student_id`, `entered_by_id` |

**Expected output columns**

`check_name`, `record_count`, `sample_id`

**SQL (portable/SQLite form)**

```sql
SELECT 'category_delete_line_items' AS check_name,
                   COUNT(*) AS record_count,
                   MIN(li.id) AS sample_id
            FROM fees_invoicelineitem li
            UNION ALL
            SELECT 'payment_delete_receipts', COUNT(*), MIN(r.id)
            FROM fees_feereceipt r
            UNION ALL
            SELECT 'student_delete_invoices', COUNT(*), MIN(i.id)
            FROM fees_invoice i
            WHERE i.student_id IS NOT NULL
            UNION ALL
            SELECT 'student_delete_payments', COUNT(*), MIN(p.id)
            FROM fees_payment p
            WHERE p.student_id IS NOT NULL
            UNION ALL
            SELECT 'invoice_delete_line_items', COUNT(*), MIN(li.id)
            FROM fees_invoicelineitem li
            WHERE li.invoice_id IS NOT NULL
            UNION ALL
            SELECT 'student_delete_scores', COUNT(*), MIN(sc.id)
            FROM academics_score sc
            WHERE sc.student_id IS NOT NULL
            UNION ALL
            SELECT 'staff_delete_payments', COUNT(*), MIN(p.id)
            FROM fees_payment p
            WHERE p.recorded_by_id IS NOT NULL
            UNION ALL
            SELECT 'staff_delete_scores', COUNT(*), MIN(sc.id)
            FROM academics_score sc
            WHERE sc.entered_by_id IS NOT NULL
            ORDER BY check_name
```

**Dialect considerations.** No dialect-specific syntax. Actual cascade execution differs by engine and by whether Django's collector or the database performs the delete; this query only counts at-risk rows.

**Interpretation.** These are **counts only**; the query does not delete anything. The student and staff counts reflect CASCADE foreign keys verified in the working tree (see docs/audit/DELETION_INVENTORY.md). Database-level cascade behaviour is not exercised by this query.

---

## Known gaps in the original written requirements

1. **Q-01 status is derived.** `Invoice.status` is a Python property, not a
   database column. The query derives PAID/PARTIAL/UNPAID from CONFIRMED
   payments and documents the deviation rather than dropping the dimension.
2. **Q-07 references a field that does not exist.** The draft asked for
   `Student.classification_review_required`; the working tree has no such
   column. Q-07 uses `student_type` and `registration_paid_term_id` instead.
   It must not be read as evidence that a review flag is modelled.
3. **Q-02 includes orphan line items.** An inner join to `fees_invoice` would
   silently hide line items with a missing invoice. The join was removed.
4. **`InvoiceLineItem.school` may be NULL.** Q-09 counts NULL separately and
   does not treat it as automatic corruption.
5. **No PostgreSQL claim.** The matrix runner reports
   `PASS_WITH_POSTGRES_NOT_RUN` when no DSN is supplied. A PostgreSQL result is
   only valid after a real instance has been seeded and the queries executed.
