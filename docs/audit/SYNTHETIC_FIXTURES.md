# Synthetic Audit Fixtures (R-04)

**Module:** `scripts/audit/synthetic_fixtures.py`
**Engine:** SQLite only
**Default path:** `/tmp/opencode/bust_audit_synthetic.sqlite3`
**Schema:** 16 tables, 112 rows, deterministic fingerprint
`730787b067420e29ea106d5b6f7677a5b433066d8230d9575a7268695729d859`

## 1. Safety and scope

- **Fabricated data only.** Names are generic, e-mail addresses use the
  reserved `.invalid` TLD, and monetary values are invented round numbers.
- No production personal or financial information is present or copied.
- The builder refuses:
  - the project `db.sqlite3`,
  - any path inside the repository,
  - any non-temporary path whose filename does not contain `synthetic`.
- The schema is deliberately **permissive** (no foreign-key constraints) so the
  seed can create orphan and cross-school rows. This is a fixture for detecting
  corruption, not a copy of the production schema.
- It is **not** a PostgreSQL seeder. PostgreSQL parity requires a separate,
  reviewed seeding path against a synthetic PostgreSQL database.

## 2. Dataset shape

Two schools (`Synthetic Alpha`, `Synthetic Beta`), three academic sessions,
five terms (one with no active price), eight users (two admins, one teacher,
five students), five students, four classes, five enrollments, six fee
categories, seventeen fee prices, six overrides, nine invoices, thirteen line
items, eleven payments, six receipts, eight payment allocations, and four
scores.

### Coverage

| Dimension | Values exercised |
|---|---|
| Schools | 2 (tenant isolation) |
| Sessions | 3 (two for school 1, one for school 2) |
| Terms | 5 (including one with no active price) |
| Student types | `NEW`, `RETURNING` |
| Billing cycles | `PER_TERM`, `ONE_TIME` |
| Fee scopes | `SCHOOL_WIDE`, `LEVEL`, `CLASS` |
| Effective dating | Present on some prices (`2024-09-01`…`2024-12-31`, `2025-01-01`…`2025-04-30`), absent on others |
| Payment statuses | `PENDING`, `CONFIRMED`, `FAILED` |
| Snapshot states | Captured name, empty name, NULL name |
| Tenant integrity | Clean rows plus cross-school and orphan rows |
| Historical integrity | Matching invoices, total mismatch, invoice with no lines, term with no price |

## 3. Deliberate anomalies

| Anomaly | Where | Query that exposes it |
|---|---|---|
| Duplicate school-wide one-time price with NULL term/class/level | prices 3 and 4 | Q-06 |
| Duplicate class/term/student-type price | prices 1 and 16 | Q-06 |
| LEVEL price with an empty level string | price 7 | Q-02/Q-06 context |
| Price whose category belongs to another school | prices 12, 13 | Q-09 |
| Price whose category is missing | price 14 | Q-09 |
| Override whose student belongs to another school | override 3 | Q-09 |
| Override whose category belongs to another school | override 4 | Q-09 |
| Override whose student/category is missing | overrides 5, 6 | Q-09 |
| Line item whose invoice is missing | line items 900, 901 | Q-09 |
| Line item whose category is missing | line item 901 | Q-09 |
| Line item whose school differs from its invoice/category | line items 9, 10 | Q-09 |
| Line item with NULL school | line item 11 | Q-09 |
| Payment whose invoice is missing | payment 10 | Q-09 |
| Payment whose student is missing | payment 11 | Q-09 |
| Payment whose school differs from its invoice/student | payment 8 | Q-09 |
| Allocation whose school differs from its payment/invoice | allocation 6 | Q-09 |
| Allocation whose payment is missing | allocation 7 | Q-09 |
| Receipt whose payment is missing | receipt 5 | Q-04 |
| Duplicate receipt for one payment | receipts 1 and 6 | Q-04 |
| Confirmed payments without receipts | payments 5, 7, 10, 11 | Q-04 |
| Invoice total ≠ sum of line items | invoices 3 and 10 | IC-8 |
| Invoice with no line items | invoice 10 | IC-8 |
| Term with no active price | term 5 | IC-8 |
| Missing historical snapshot | line items 2 and 11 | IC-9 |
| Name equal to current category name | line items 1, 4, 5, 7, 8 | IC-9 |
| One-time fee billed in more than one session | category 2 | Q-08 |
| Category with history / price / override / allocation | categories 1–6 | Q-10 / IC-10 |
| Staff-linked payments and scores | all payments and four scores | IC-10 |

## 4. Expected result sizes

| Query | Expected rows |
|---|---|
| Q-01 | 8 |
| Q-02 | 9 |
| Q-03 | 6 |
| Q-04 | 3 |
| Q-05 | 7 |
| Q-06 | 2 |
| Q-07 | 4 |
| Q-08 | 2 |
| Q-09 | 18 |
| Q-10 | 6 |
| IC-8 | 4 |
| IC-9 | 2 |
| IC-10 | 8 |

### Expected check counts

| Query | Check | Count |
|---|---|---|
| Q-04 | confirmed payment without receipt | 4 |
| Q-04 | receipt without payment | 1 |
| Q-04 | duplicate receipts per payment | 1 |
| Q-06 | duplicated scope keys | 2 groups |
| Q-08 | billed ONE_TIME categories | 2 |
| Q-09 | cross-school fee-price/category | 2 |
| Q-09 | orphan fee-price/category | 1 |
| Q-09 | cross-school line-item/invoice | 1 |
| Q-09 | orphan line-item/invoice | 2 |
| Q-09 | cross-school line-item/category | 2 |
| Q-09 | orphan line-item/category | 1 |
| Q-09 | NULL-school line items | 1 |
| Q-09 | cross-school payment/invoice | 1 |
| Q-09 | orphan payment/invoice | 1 |
| Q-09 | cross-school payment/student | 1 |
| Q-09 | orphan payment/student | 1 |
| Q-09 | cross-school allocation/payment | 1 |
| Q-09 | orphan allocation/payment | 1 |
| Q-09 | cross-school allocation/invoice | 1 |
| Q-09 | cross-school override/student | 1 |
| Q-09 | orphan override/student | 1 |
| Q-09 | cross-school override/category | 1 |
| Q-09 | orphan override/category | 1 |
| IC-8 | invoice total mismatch | 2 |
| IC-8 | invoice without line items | 1 |
| IC-8 | line item without category | 1 |
| IC-8 | term without active price | 1 |
| IC-9 | missing item name | 2 |
| IC-9 | name equals current category | 5 |
| IC-10 | category-delete line items | 13 |
| IC-10 | payment-delete receipts | 6 |
| IC-10 | student-delete invoices | 9 |
| IC-10 | student-delete payments | 11 |
| IC-10 | invoice-delete line items | 13 |
| IC-10 | student-delete scores | 4 |
| IC-10 | staff-delete payments | 11 |
| IC-10 | staff-delete scores | 4 |

These values are asserted by
`scripts/audit/tests/test_phase0_harness.py::FixtureTests`.

## 5. Usage

```bash
# Build (replaces an existing file under /tmp by default).
python scripts/audit/synthetic_fixtures.py

# Build to a named temporary path and dump the explicit schema description.
python scripts/audit/synthetic_fixtures.py /tmp/opencode/bust_audit_synthetic.sqlite3 \
  --dump-schema /tmp/opencode/synthetic_schema.json

# Refuse to replace an existing file.
python scripts/audit/synthetic_fixtures.py /tmp/opencode/bust_audit_synthetic.sqlite3 --no-reset
```

The manifest prints table counts, total rows, and the fingerprint. Rebuilding
twice produces the same fingerprint; the regression suite asserts this.

## 6. Limitations

- **SQLite only.** No PostgreSQL seed is provided. Do not claim PostgreSQL
  parity until the same rows are loaded into a real PostgreSQL instance and the
  matrix is run there.
- **Permissive schema.** Missing constraints are intentional. Identifier
  validation cares about names, not constraint parity with production.
- **Fabricated values are not representative of production distributions.**
  They prove query behaviour, not production magnitudes.
- **No delete is executed.** The fixture can count at-risk rows but cannot prove
  cascade behaviour. See `docs/audit/DELETION_INVENTORY.md`.
- **No concurrency or locking scenarios.** The fixture is single-connection and
  static.
- **Not a backup/restore test.** It does not exercise migration history,
  PostgreSQL collations, or deployment topology.
