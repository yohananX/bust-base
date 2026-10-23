# Phase 0 Audit Documentation

Readiness artefacts only. No application model, migration, schema, or behaviour
change is included.

| Document | Task | Contents |
|---|---|---|
| [QUERY_SPEC.md](QUERY_SPEC.md) | R-01 | Q-01…Q-10 + IC-8/9/10: purpose, tables/columns, output, dialect notes, interpretation, draft/executed status. |
| [DIALECT_MATRIX.md](DIALECT_MATRIX.md) | R-03 | SQLite/PostgreSQL compatibility matrix and actual test status. PostgreSQL is **NOT RUN**. |
| [SYNTHETIC_FIXTURES.md](SYNTHETIC_FIXTURES.md) | R-04 | Deterministic synthetic dataset, deliberate anomalies, expected counts, limitations. |
| [DELETION_INVENTORY.md](DELETION_INVENTORY.md) | R-07 | Model-level `on_delete` policies, application deletion entry points, cascade traces, verified vs assumed vs untested. |
| [EVIDENCE_TEMPLATE.md](EVIDENCE_TEMPLATE.md) | R-11 | Required evidence fields, JSON template, redaction rules, approval and retention. |
| [READINESS_REPORT.md](READINESS_REPORT.md) | Batch report | Files, exact test results, dialects tested, limitations, working-tree integrity, GO/NO-GO. |

## Tooling

The runnable harness is in `scripts/audit/`. Start with
`scripts/audit/README.md`.

## Ground rules

- All queries are **DRAFT**; none has run against production.
- PostgreSQL is **NOT RUN** in this environment.
- Synthetic data only. Fabricated values only.
- No deletion was executed; cascade conclusions are static.
- Acceptance of this batch does not authorize implementation or migration.
