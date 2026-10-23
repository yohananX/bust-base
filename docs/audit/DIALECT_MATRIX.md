# SQLite / PostgreSQL Dialect Matrix (R-03)

**Matrix version:** 1.0.0
**Run date:** 2026-10-23
**Dataset:** deterministic synthetic fixture `scripts/audit/synthetic_fixtures.py`
**Runner:** `scripts/audit/run_dialect_matrix.py`

## 1. What was genuinely tested

| Dialect | Engine version | Status | Basis |
|---|---|---|---|
| SQLite | 3.45.1 | **PASS** | 13/13 queries executed read-only against `/tmp/opencode/bust_audit_synthetic.sqlite3` (fabricated data, 16 tables, 112 rows). |
| PostgreSQL | — | **NOT RUN** | No PostgreSQL server is installed or reachable in this environment. `psql`, `pg_ctl`, and `initdb` are absent; the Docker socket is not accessible to this user. No PostgreSQL instance was contacted. |

> **No PostgreSQL compatibility is claimed.** The runner reports
> `PASS_WITH_POSTGRES_NOT_RUN`, `postgres_claimed: false`, and
> `dialects_genuinely_tested: ["sqlite"]`. A PostgreSQL PASS is only valid
> after the fixture has been loaded into a real PostgreSQL database and all 13
> queries have executed there.

### SQLite result matrix

| Query | Version | Status | Rows | Columns |
|---|---|---|---|---|
| Q-01 | 1.0.0 | PASS | 8 | 9 |
| Q-02 | 1.0.0 | PASS | 9 | 8 |
| Q-03 | 1.0.0 | PASS | 6 | 5 |
| Q-04 | 1.0.0 | PASS | 3 | 2 |
| Q-05 | 1.0.0 | PASS | 7 | 9 |
| Q-06 | 1.0.0 | PASS | 2 | 10 |
| Q-07 | 1.0.0 | PASS | 4 | 5 |
| Q-08 | 1.0.0 | PASS | 2 | 9 |
| Q-09 | 1.0.0 | PASS | 18 | 3 |
| Q-10 | 1.0.0 | PASS | 6 | 9 |
| IC-8 | 1.0.0 | PASS | 4 | 3 |
| IC-9 | 1.0.0 | PASS | 2 | 3 |
| IC-10 | 1.0.0 | PASS | 8 | 3 |

Schema validation against the synthetic schema and against the real local
`db.sqlite3` **schema metadata** also passed (177 identifiers, 13 queries).
Only `sqlite_master` and `PRAGMA table_info` were read from the project
database; no application rows were selected.

## 2. Compatibility matrix

| Area | SQLite | PostgreSQL | Effect on this catalogue |
|---|---|---|---|
| Identifier quoting | Double quotes accepted; unquoted identifiers are case-insensitive. | Double quotes exact; unquoted names fold to lower case. | All catalogue identifiers are lower-case snake_case and unquoted. |
| Joins | `INNER`/`LEFT` joins; a `LEFT JOIN` may not appear after `WHERE`. | Same grammar rule. | All joins precede `WHERE`; orphan checks use `LEFT JOIN ... WHERE parent.id IS NULL`. |
| `GROUP BY` output alias | Supported. | Supported (PostgreSQL extension to strict SQL). | Q-01, Q-02, Q-07 group by derived aliases. |
| `HAVING` output alias | Supported. | Not relied upon. | Q-10 wraps the aggregate in a derived table instead of using an alias in `HAVING`. |
| `UNION ALL` type resolution | Dynamic typing; values may mix types per row. | Strict: each column must have a compatible type across branches. | Every `UNION ALL` branch emits the same name/type positions (`check_name` text, count integer, `sample_id` integer/NULL). |
| NULL equality | NULL = NULL is unknown; `GROUP BY` groups NULLs together. | Same. | Q-06 duplicate detection groups NULL class/level/term together. |
| NULL in unique indexes | NULLs are distinct, so a `UNIQUE` constraint does not block duplicate nullable scope rows. | Same. | Q-06 must count duplicates; the existing `unique_together` is not a guarantee. |
| NULL ordering | `ORDER BY col ASC` places NULLs first. | `ORDER BY col ASC` places NULLs last by default. | No query orders by a nullable column; ordering is by ids/status/check name. Avoid adding `ORDER BY` on nullable scope columns without `NULLS FIRST/LAST`. |
| Boolean storage | `INTEGER` 0/1; `TRUE`/`FALSE` keywords accepted since 3.23. | Native `boolean`; `boolean = 1` is invalid. | IC-8 uses `p.is_active = TRUE`, valid on both SQLite 3.45 and PostgreSQL. |
| Decimal / numeric | Decimal fields are stored with numeric affinity; aggregates may surface as REAL. | Exact `numeric`. | Compare rounded monetary values in evidence; do not assert raw float equality across engines. |
| `ROUND(numeric, n)` | Supported; returns REAL. | Supported for `numeric`. | IC-8 uses `ROUND(..., 2)`. |
| Integer division | `5/2 = 2`. | `5/2 = 2` for integers; numeric division if either side is numeric. | No query divides; comparisons use subtraction. |
| String concatenation | `||` supported. | `||` supported. | Not used. |
| `GROUP_CONCAT` / `STRING_AGG` | `GROUP_CONCAT` only. | `STRING_AGG` only. | Avoided; Q-06 uses `MIN`/`MAX` ids. |
| Regex | No native regex operator by default. | `~`, `~*`. | Not used. |
| JSON functions | JSON1 extension, operator set differs. | `jsonb` operators and functions. | Not used. |
| Date/time types | Text/numeric; no strict date type. | `date`, `timestamp`, `timestamptz`. | Queries do not filter or order by dates; effective dating is not yet in SQL. |
| Foreign keys | Off by default per connection unless `PRAGMA foreign_keys=ON`. | Always enforced. | The synthetic fixture deliberately disables FKs to seed orphans. Production orphan counts on PostgreSQL may be zero unless constraints were historically disabled. |
| Cascades | Django's collector usually deletes dependants in Python; database `ON DELETE` behaviour depends on schema. | Database-enforced FKs and cascades. | IC-10 counts at-risk rows only; it does not execute a cascade. R-07 distinguishes code-verified from untested database behaviour. |
| Collation | Default `BINARY`; case-sensitive text comparison. | Database/column collation, often locale-aware. | IC-9 equality counts can differ if names differ only by case or locale rules. Q-09 uses integer keys only. |
| Read-only enforcement | `PRAGMA query_only=ON` plus `mode=ro`. | `SET SESSION ... READ ONLY` via psycopg2 `readonly=True`, `SET LOCAL statement_timeout`. | Runner enforces both. |
| Statement timeout | No built-in statement timeout; bounded by `--max-rows`. | `statement_timeout` set per transaction. | Runner uses 30 s for PostgreSQL. |
| `SELECT ... FOR UPDATE` | Not used. | Not used. | Validator rejects `FOR UPDATE` as a locking statement. |

## 3. How to run the PostgreSQL half later

1. Provision a **synthetic** PostgreSQL database whose name starts with
   `test_`, `bust_audit_`, or `bust_synthetic_`. The runner refuses any other
   database name before connecting.
2. Create the same tables/columns as `scripts/audit/synthetic_fixtures.py`
   and load the same rows. This fixture seeder is SQLite-only today; a
   PostgreSQL seeding path must be added and reviewed before claiming parity.
3. Run:
   ```bash
   AUDIT_POSTGRES_DSN='postgresql://.../bust_audit_phase0' \
     python scripts/audit/run_dialect_matrix.py \
       --sqlite /tmp/opencode/bust_audit_synthetic.sqlite3 \
       --json-out /tmp/opencode/matrix-postgres.json
   ```
4. Accept PostgreSQL only if:
   - `postgres.status == "PASS"`,
   - `differences == []`,
   - `dialects_genuinely_tested` contains `postgres`.
5. Record the exact server version in the evidence pack. Do not reuse a
   PostgreSQL result across versions or collations.

## 4. Known differences that could produce legitimate mismatches

- **Collation-sensitive counts.** IC-9 text equality and any future text
  ordering may differ under a locale collation.
- **NULL ordering.** Any added `ORDER BY` on nullable `school_class_id`,
  `level`, or `term_id` must specify `NULLS FIRST/LAST`.
- **Decimal rendering.** SQLite may return REAL for an aggregate where
  PostgreSQL returns `Decimal`. The runner hashes the driver's values, so a
  cross-engine hash comparison is not meaningful; compare columns and row
  counts, then compare rounded monetary totals explicitly.
- **Orphan rows.** PostgreSQL cannot hold orphan rows with enforced FKs. The
  synthetic PostgreSQL dataset must either disable/constraint-drop for the
  seed or use a schema without FKs, exactly as the SQLite fixture does. Record
  which choice was used.

## 5. Limitations

- PostgreSQL is **NOT RUN**. No statement in this document should be read as a
  PostgreSQL compatibility claim.
- The SQLite test proves execution and stable output on one SQLite version
  (3.45.1). It does not prove behaviour on older SQLite builds, especially
  before 3.23 (`TRUE` keyword) or 3.30 (`NULLS LAST`).
- The runner fetches at most `--max-rows` rows per query. A truncated result is
  flagged in the result's `exception` field and must not be treated as a
  complete baseline.
- The validator checks identifiers, not query semantics. Execution and human
  review are still required.
