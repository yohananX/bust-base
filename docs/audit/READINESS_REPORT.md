# Phase 0 Audit Readiness Report

**Batch:** Phase 0 audit-readiness, tasks R-01, R-02, R-03, R-04, R-07, R-11
**Date:** 2026-10-23
**Status:** Readiness artefacts complete. **No implementation, migration, or behaviour change performed.**

---

## 1. Scope

Only the six authorised readiness tasks were delivered:

| Task | Deliverable | Status |
|---|---|---|
| R-01 | Query catalogue Q-01…Q-10 (+ supplementary IC-8/9/10) | Complete, all `DRAFT` |
| R-02 | Schema-identifier validator | Complete, 2 schema sources validated |
| R-03 | SQLite/PostgreSQL dialect matrix | SQLite complete; PostgreSQL **NOT RUN** |
| R-04 | Deterministic synthetic fixtures | Complete, 16 tables / 112 rows |
| R-07 | Deletion-path inventory | Complete, static + verified `on_delete` |
| R-11 | Evidence record template and generator | Complete |

Explicitly **not** done: academic migration, model/schema changes, production query
execution, database writes, commits, or edits to existing user work.

---

## 2. Environment

| Item | Value |
|---|---|
| Repository | `/home/yohananx/bust-base` |
| Branch / HEAD | `main` / `8a1bdcc` |
| Python | 3.12.3 (`.venv`) |
| Django | 6.0.7 |
| SQLite (engine used) | 3.45.1 |
| PostgreSQL | **Unavailable** — see §6 |
| Local DB schema revision | `students.0008_add_academic_stage` (already applied before this batch; not applied by it) |
| Local DB read access | Schema metadata only (`sqlite_master`, `PRAGMA table_info`); no rows read |

---

## 3. Files Added

All paths are new. No existing file was modified by this batch.

### Documentation — `docs/audit/`
- `README.md` — index and ground rules
- `QUERY_SPEC.md` — generated catalogue specification (13 queries)
- `DIALECT_MATRIX.md` — compatibility matrix and actual execution status
- `SYNTHETIC_FIXTURES.md` — dataset, deliberate anomalies, expected counts, limits
- `DELETION_INVENTORY.md` — `on_delete` policies, app entry points, cascade traces
- `EVIDENCE_TEMPLATE.md` — evidence schema, redaction, approval, retention
- `READINESS_REPORT.md` — this report

### Tooling — `scripts/audit/`
- `README.md` — usage and safety contract
- `__init__.py`
- `phase0_queries.py` — catalogue + draft/executed contract
- `render_query_spec.py` — regenerates `QUERY_SPEC.md`
- `schema_validator.py` — R-02 identifier validator
- `synthetic_fixtures.py` — R-04 deterministic fixture builder
- `run_dialect_matrix.py` — R-03 read-only matrix runner
- `evidence.py` — R-11 redacted evidence records and packs
- `tests/__init__.py`
- `tests/test_phase0_harness.py` — 25 regression tests

---

## 4. Exact Test Results

### 4.1 Regression suite

```
$ .venv/bin/python -m unittest discover -s scripts/audit/tests -v

Ran 25 tests in 19.939s

OK
```

25 passed, 0 failed, 0 skipped, 0 errors.

### 4.2 Schema validator (R-02)

Synthetic schema:

```
source: synthetic_fixtures.SCHEMA
dialect: sqlite
queries checked: 13
identifiers checked: 177
result: PASS
```

Real local DB, metadata only:

```
source: sqlite:db.sqlite3
dialect: sqlite
queries checked: 13
identifiers checked: 177
result: PASS
```

Negative paths are covered by tests: unknown table rejected, unknown column
rejected, write/DDL rejected, multi-statement rejected, DSN password never leaked.

### 4.3 Synthetic fixtures (R-04)

```
$ .venv/bin/python scripts/audit/synthetic_fixtures.py /tmp/opencode/bust_audit_synthetic.sqlite3

Synthetic database: /tmp/opencode/bust_audit_synthetic.sqlite3
SQLite version:     3.45.1
Tables:             16
Total rows:         112
Fingerprint:        730787b067420e29ea106d5b6f7677a5b433066d8230d9575a7268695729d859
```

Fingerprint is stable across rebuilds (verified by
`test_fixture_is_deterministic_and_idempotent`).

### 4.4 Dialect matrix (R-03)

```
overall: PASS_WITH_POSTGRES_NOT_RUN
dialects genuinely tested: sqlite
postgres claimed: False
schema validation: PASS
sqlite: PASS (version=3.45.1, reason=None)
  Q-01 v1.0.0: PASS rows=8  cols=9
  Q-02 v1.0.0: PASS rows=9  cols=8
  Q-03 v1.0.0: PASS rows=6  cols=5
  Q-04 v1.0.0: PASS rows=3  cols=2
  Q-05 v1.0.0: PASS rows=7  cols=9
  Q-06 v1.0.0: PASS rows=2  cols=10
  Q-07 v1.0.0: PASS rows=4  cols=5
  Q-08 v1.0.0: PASS rows=2  cols=9
  Q-09 v1.0.0: PASS rows=18 cols=3
  Q-10 v1.0.0: PASS rows=6  cols=9
  IC-8 v1.0.0: PASS rows=4  cols=3
  IC-9 v1.0.0: PASS rows=2  cols=3
  IC-10 v1.0.0: PASS rows=8 cols=3
postgres: NOT_RUN (version=unknown, reason=no --postgres-dsn supplied;
          no PostgreSQL instance was contacted)
```

SQLite: 13/13 PASS.

### 4.5 Evidence generator (R-11)

Evidence pack generated from the matrix output; `Q-05.admission_number` redacted
on output. Enforced by `test_evidence_pack_from_real_matrix_redacts_q05`,
`test_record_rejects_dsn_in_environment`, `test_record_rejects_invalid_hash`,
`test_record_requires_reviewer_for_approved_status`.

---

## 5. Dialects Genuinely Tested

| Dialect | Tested | Evidence |
|---|---|---|
| SQLite 3.45.1 | **Yes** | 13/13 queries executed against synthetic DB; 25 tests |
| PostgreSQL | **No** | No server, no client binaries, no container access |

**No PostgreSQL compatibility is claimed.** The matrix records
`PASS_WITH_POSTGRES_NOT_RUN` and the tool refuses to emit an approved
PostgreSQL evidence record when PostgreSQL was not executed
(`test_evidence_builder_refuses_not_run_postgres`).

`DIALECT_MATRIX.md` documents per-query expected PostgreSQL behaviour
(type casting, `NULLS FIRST`, date arithmetic, identifier quoting) as
**untested expectations**, not results.

---

## 6. Limitations

1. **PostgreSQL not executed.** Blockers observed in this environment:
   - `psql`, `pg_ctl`, `initdb`, `postgres`: not installed.
   - Docker client present, but `/var/run/docker.sock` is `root:docker` and the
     current user is not in the `docker` group:
     `permission denied while trying to connect to the docker API`.
   Consequence: dialect portability is unproven. A real PostgreSQL run is a
   prerequisite for any production claim.
2. **No production execution.** Every catalogue entry is `DRAFT`; none ran
   against production or against application data.
3. **Deletion behaviour is static.** No delete was executed. `Payment.recorded_by`
   and `Score.entered_by` are `CASCADE` per model introspection; runtime cascade
   effects and DB-level constraint enforcement were not observed. Documented as
   verified-static, not runtime-verified.
4. **Synthetic schema is permissive by design.** No foreign-key constraints, so
   orphan and cross-school inconsistencies can be seeded. It is not a copy of
   production DDL, and the synthetic DB is not a performance or planner proxy.
5. **Validator proves identifiers, not semantics.** R-02 confirms every referenced
   table/column exists in the declared or introspected schema. It does not prove a
   query is logically correct or returns intended business results.
6. **Supplementary checks.** IC-8, IC-9, IC-10 were added because the readiness
   plan requires them; they are kept separate from Q-01…Q-10 and are not counted
   as part of the ten-query contract.
7. **No production credentials or personal data** were used or stored. Synthetic
   values are fabricated.

---

## 7. Working-Tree Integrity

Starting state was recorded before work began and re-checked after all runs.

**Pre-existing modified files (untouched by this batch):**
- `docs/FEE_REDESIGN_PLAN.md`
- `students/admin.py`
- `students/models.py`
- `students/tests.py`

**Pre-existing untracked files (untouched):**
- `docs/FINAL_GO_NOGO_CORRECTIONS.md`
- `docs/PHASE0_READINESS_PLAN.md`
- `fee_redesign.md`
- `students/migrations/0008_add_academic_stage.py`

**Git facts at close:**
- Branch `main`, HEAD `8a1bdcc`, no stashes.
- `git diff --stat` reports only the four pre-existing modified files:
  ```
   docs/FEE_REDESIGN_PLAN.md | 1294 ++++++++++++++-------------------------------
   students/admin.py         |   19 +-
   students/models.py        |   44 +-
   students/tests.py         |  116 +++-
   4 files changed, 567 insertions(+), 906 deletions(-)
  ```
- All batch deliverables appear as untracked additions only.
- Nothing staged, nothing committed, nothing stashed, no user work reset or reverted.
- `db.sqlite3` was opened read-only for schema metadata; no write occurred.
- Only write outside the repo was `/tmp/opencode/bust_audit_synthetic.sqlite3`
  and `/tmp/opencode/bust_audit_matrix.json`.

---

## 8. Go / No-Go

### GO — next **readiness** batch (documentation and harness work)

Justification: all six deliverables exist, 25/25 tests pass, 13/13 SQLite queries
execute against fixtures, the validator passes on two schema sources, and no
existing work was disturbed.

### NO-GO — implementation or migration

Justification: PostgreSQL remains unexecuted, no production query has run, and
deletion/cascade behaviour is static analysis only. The academic migration is not
authorised and not started.

### Conditions for the next batch

1. Execute the 13 queries against a real, synthetic PostgreSQL instance and record
   evidence with R-11.
2. Human review and sign-off of `DELETION_INVENTORY.md`, especially the
   `CASCADE` findings on `Payment.recorded_by` and `Score.entered_by`.
3. Confirm fixture counts against a reviewed business-rule baseline.
4. Keep all queries `DRAFT` until reviewed evidence is approved.

---

## 9. Reproduction

```bash
.venv/bin/python -m unittest discover -s scripts/audit/tests -v
.venv/bin/python scripts/audit/schema_validator.py --synthetic-schema
.venv/bin/python scripts/audit/schema_validator.py --sqlite db.sqlite3
.venv/bin/python scripts/audit/synthetic_fixtures.py /tmp/opencode/bust_audit_synthetic.sqlite3
.venv/bin/python scripts/audit/run_dialect_matrix.py \
    --sqlite /tmp/opencode/bust_audit_synthetic.sqlite3 \
    --json-out /tmp/opencode/bust_audit_matrix.json
```

To add PostgreSQL once an instance exists:

```bash
export AUDIT_POSTGRES_DSN='postgresql://user:pass@host:5432/synthetic_db'
.venv/bin/python scripts/audit/run_dialect_matrix.py \
    --sqlite /tmp/opencode/bust_audit_synthetic.sqlite3
```

The runner refuses non-synthetic database targets and never prints the DSN.
