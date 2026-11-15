# Audit Evidence Template (R-11)

**Template version:** 1.0.0
**Applies to:** Phase 0 audit queries Q-01…Q-10 and supplementary checks IC-8…IC-10
**Producer:** `scripts/audit/evidence.py` (from a `run_dialect_matrix.py` report)
**Storage:** append-only evidence directory approved by the engineering lead and security. Never overwrite a prior run.

## 1. Rules

1. **One record per query execution.** A record names the query id and version;
   an evidence pack groups the records from one run.
2. **No credentials, DSNs, API keys, or tokens.** The builder rejects strings
   containing a connection URL or credential markers.
3. **No unnecessary personal data.** Known personal/financial columns
   (`admission_number`, e-mail, phone, address, guardian, `paid_by_*`,
   `reference`, bank/account fields) are replaced with `[REDACTED]`. Free text
   is scrubbed for e-mail and phone patterns.
4. **The full result is hashed, not copied.** `result_sha256` is SHA-256 over
   the ordered row values as returned by the driver. The preview is capped at
   five rows and is supplementary.
5. **Never claim an engine that did not run.** A record for PostgreSQL is only
   valid when the matrix block status is `PASS` or `FAIL` (not `NOT_RUN` /
   `REFUSED` / `ERROR`).
6. **Approval is separate from execution.** `approval_status` starts at
   `PENDING`. `APPROVED` or `REJECTED` requires a named reviewer.
7. **A re-run creates a new pack.** Do not edit an old pack to add a new query
   version or a different engine.

## 2. Required fields

| Field | Type | Required | Meaning |
|---|---|---|---|
| `evidence_pack_version` | string | yes | Template/schema version. |
| `run_id` | string | yes | Unique run identifier; never reused. |
| `environment` | string | yes | `local-synthetic`, `staging-restored-copy`, etc. No DSNs. |
| `database_engine` | string | yes | `sqlite` or `postgres`. |
| `database_version` | string | yes | Exact engine version reported by the engine. |
| `schema_revision` | string | yes | Git commit (dirty-marked) plus migration identifier if relevant. |
| `query_id` | string | yes | `Q-01`…`Q-10`, `IC-8`…`IC-10`. |
| `query_version` | string | yes | Per-query version from the catalogue. |
| `executed_at` | ISO-8601 string | yes | UTC timestamp of execution. |
| `row_count` | integer | yes | Rows returned (after any documented truncation). |
| `result_sha256` | 64-char hex / null | yes | Hash of ordered result rows; null only if execution failed before a result. |
| `redacted_results.columns` | array | yes | Output column names. |
| `redacted_results.preview` | array | yes | Up to five redacted row objects. |
| `redacted_results.preview_row_count` | integer | yes | Number of preview rows included. |
| `redacted_results.truncated` | boolean | yes | Whether the preview was truncated. |
| `exceptions` | array | yes | Execution exceptions or truncation notes; empty when none. |
| `reviewer` | string / null | conditional | Required for `APPROVED`/`REJECTED`. |
| `approval_status` | enum | yes | `PENDING`, `APPROVED`, `REJECTED`. |
| `notes` | string | no | Review notes. No secrets or personal data. |
| `source` | string | yes | `synthetic` for this readiness batch. |

## 3. JSON record template

```json
{
  "evidence_pack_version": "1.0.0",
  "run_id": "REPLACE_WITH_UNIQUE_RUN_ID",
  "environment": "local-synthetic",
  "database_engine": "sqlite",
  "database_version": "REPLACE_WITH_EXACT_ENGINE_VERSION",
  "schema_revision": "REPLACE_WITH_GIT_COMMIT_AND_DIRTY_MARKER",
  "query_id": "Q-01",
  "query_version": "1.0.0",
  "executed_at": "2026-01-01T00:00:00+00:00",
  "row_count": 0,
  "result_sha256": "0000000000000000000000000000000000000000000000000000000000000000",
  "redacted_results": {
    "columns": ["column_a", "column_b"],
    "preview": [
      {"column_a": "value", "column_b": 0}
    ],
    "preview_row_count": 1,
    "truncated": false
  },
  "exceptions": [],
  "reviewer": null,
  "approval_status": "PENDING",
  "notes": "",
  "source": "synthetic"
}
```

## 4. Example (fabricated and redacted)

This example is illustrative only. It is not a claim that production data was
read.

```json
{
  "evidence_pack_version": "1.0.0",
  "run_id": "synthetic-demo-001",
  "environment": "local-synthetic",
  "database_engine": "sqlite",
  "database_version": "3.45.1",
  "schema_revision": "8a1bdcc-dirty",
  "query_id": "Q-05",
  "query_version": "1.0.0",
  "executed_at": "2026-10-23T00:00:00+00:00",
  "row_count": 2,
  "result_sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "redacted_results": {
    "columns": [
      "invoice_id",
      "school_id",
      "student_id",
      "admission_number",
      "term_name",
      "total_amount",
      "amount_paid",
      "balance"
    ],
    "preview": [
      {
        "invoice_id": 3,
        "school_id": 1,
        "student_id": 3,
        "admission_number": "[REDACTED]",
        "term_name": "Second Term",
        "total_amount": 65000,
        "amount_paid": 10000,
        "balance": 55000
      }
    ],
    "preview_row_count": 1,
    "truncated": false
  },
  "exceptions": [],
  "reviewer": "Synthetic Reviewer",
  "approval_status": "APPROVED",
  "notes": "Fabricated fixture; demonstrates the record shape only.",
  "source": "synthetic"
}
```

## 5. Pack envelope

`evidence.py` writes one pack per matrix report:

```json
{
  "evidence_pack_version": "1.0.0",
  "run_id": "unique-pack-id",
  "environment": "local-synthetic",
  "database_engine": "sqlite",
  "database_version": "3.45.1",
  "schema_revision": "8a1bdcc-dirty",
  "executed_at": "2026-10-23T00:00:00+00:00",
  "reviewer": "Synthetic Reviewer",
  "approval_status": "PENDING",
  "source": "synthetic",
  "records": []
}
```

## 6. Creation workflow

```bash
# 1. Build a synthetic database (never the project db.sqlite3).
python scripts/audit/synthetic_fixtures.py /tmp/opencode/bust_audit_synthetic.sqlite3

# 2. Run the matrix. PostgreSQL is only contacted if a synthetic DSN is supplied.
python scripts/audit/run_dialect_matrix.py \
  --sqlite /tmp/opencode/bust_audit_synthetic.sqlite3 \
  --json-out /tmp/opencode/matrix.json

# 3. Create the evidence pack.
python scripts/audit/evidence.py \
  --from-matrix /tmp/opencode/matrix.json \
  --out /tmp/opencode/evidence-phase0.json \
  --environment local-synthetic \
  --schema-revision "$(git rev-parse HEAD)-dirty" \
  --reviewer "Reviewer Name" \
  --approval-status PENDING
```

For a PostgreSQL run, add `--dialect postgres` and a synthetic DSN via
`AUDIT_POSTGRES_DSN`. The builder refuses a pack if the PostgreSQL block is
`NOT_RUN`, `REFUSED`, or `ERROR`.

## 7. Review and approval

| Step | Who | Action |
|---|---|---|
| 1 | Operator | Produce the pack from a named engine, version, schema revision, and query versions. |
| 2 | Reviewer | Compare `row_count`, `result_sha256`, preview, and exceptions against the expected fixture manifest or the restored-copy run sheet. |
| 3 | Reviewer | Record `reviewer` and set `approval_status` to `APPROVED` or `REJECTED`; add notes. |
| 4 | Engineering lead | Accept the pack for Gate 0 only if every required query has a record with captured output. |

## 8. Retention and access

- **Retention:** at least until Gate 5 closes; longer if required by the school's
  data-retention policy.
- **Access:** engineering lead, product owner, security/DBA. No wider
  distribution of student-level previews.
- **Integrity:** store the pack immutably (write-once/append-only or a hash
  manifest). A new run gets a new `run_id`; never edit or overwrite a prior pack.
- **Redaction review:** a human must still inspect previews before external
  sharing. Automated redaction reduces risk; it does not prove anonymisation.

## 9. What this template does not cover

- Consent or legal basis for processing personal data.
- Backup/restore evidence.
- Production access authorization (AP-03).
- Query correctness beyond identifier validation and synthetic execution.
- A PostgreSQL result when no PostgreSQL instance was contacted.
