# Phase 0 Audit Harness

Readiness tooling for R-01, R-02, R-03, R-04, R-07, and R-11. It contains no
application models, no migrations, and no schema changes. It does not modify
application behaviour.

## Files

| File | Purpose |
|---|---|
| `phase0_queries.py` | Q-01…Q-10 + IC-8/9/10 catalogue. **No execution path.** |
| `schema_validator.py` | Validates declared tables/columns against an explicit schema, SQLite, or PostgreSQL metadata. |
| `synthetic_fixtures.py` | Deterministic synthetic SQLite database and expected-finding manifest. |
| `run_dialect_matrix.py` | Executes the catalogue read-only against synthetic SQLite and, optionally, synthetic PostgreSQL. |
| `evidence.py` | Builds redacted evidence records/packs with hashes. |
| `render_query_spec.py` | Regenerates `docs/audit/QUERY_SPEC.md` from the catalogue. |
| `tests/test_phase0_harness.py` | 25 regression tests using synthetic SQLite only. |

Documentation lives in `docs/audit/`.

## Quick start

```bash
# 1. Build the synthetic database.
python scripts/audit/synthetic_fixtures.py

# 2. Validate identifiers against the synthetic schema.
python scripts/audit/schema_validator.py --synthetic-schema

# 3. Also validate against the local project schema (metadata only, read-only).
python scripts/audit/schema_validator.py --sqlite db.sqlite3

# 4. Run the matrix. No PostgreSQL claim without a synthetic DSN.
python scripts/audit/run_dialect_matrix.py \
  --sqlite /tmp/opencode/bust_audit_synthetic.sqlite3

# 5. Create an evidence pack from the JSON report.
python scripts/audit/run_dialect_matrix.py \
  --sqlite /tmp/opencode/bust_audit_synthetic.sqlite3 \
  --json-out /tmp/opencode/matrix.json
python scripts/audit/evidence.py \
  --from-matrix /tmp/opencode/matrix.json \
  --out /tmp/opencode/evidence-phase0.json \
  --environment local-synthetic \
  --approval-status PENDING

# 6. Run the regression tests.
python -m unittest discover -s scripts/audit/tests -v
```

## Safety guarantees

- The catalogue module never opens a database connection.
- Every SQL statement is validated as a single `SELECT`/`WITH`; write and DDL
  keywords, `SELECT INTO`, and `FOR UPDATE` are rejected.
- SQLite execution uses `mode=ro` and `PRAGMA query_only=ON`.
- PostgreSQL execution uses a read-only session and a statement timeout.
- SQLite paths inside the repository and the project `db.sqlite3` are refused.
- PostgreSQL database names must start with `test_`, `bust_audit_`, or
  `bust_synthetic_`.
- Evidence redacts known personal/financial columns and rejects DSNs and
  credential markers.

## Exit codes

| Tool | Code | Meaning |
|---|---|---|
| `schema_validator.py` | 0 | Validation passed. |
| | 1 | Unknown identifier or unsafe SQL. |
| | 2 | Could not read the schema source. |
| `run_dialect_matrix.py` | 0 | SQLite passed; PostgreSQL skipped or both passed. |
| | 2 | SQLite failed, PostgreSQL failed, a mismatch was found, or PostgreSQL was refused. |
| `evidence.py` | 0 | Pack written. |
| | 1 | Invalid input or an engine that was not genuinely tested. |

## PostgreSQL

PostgreSQL was **not available** in the environment used for this batch. The
runner reports `PASS_WITH_POSTGRES_NOT_RUN` and `postgres_claimed: false`. Do
not claim PostgreSQL compatibility until the fixture has been loaded into a
real synthetic PostgreSQL database and `dialects_genuinely_tested` contains
`postgres`.

## Known limitations

- The SQLite fixture schema is deliberately permissive and is not a production
  schema clone.
- Identifier validation is not semantic proof; execution and human review are
  still required.
- Cascade behaviour is documented statically; no delete is executed.
- `--max-rows` truncation is flagged but still requires reviewer attention.
