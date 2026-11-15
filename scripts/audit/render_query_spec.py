"""Render docs/audit/QUERY_SPEC.md from the query catalogue.

Keeping the specification generated from the same objects the validator and
runner use prevents documentation drift.  This script only writes Markdown; it
never touches a database.
"""

from __future__ import annotations

import argparse
from pathlib import Path

try:
    from .phase0_queries import (
        CATALOGUE_VERSION,
        QUERIES,
        REQUIRED_QUERY_IDS,
        SUPPLEMENTARY_QUERY_IDS,
    )
except ImportError:  # direct script execution
    from phase0_queries import (  # type: ignore
        CATALOGUE_VERSION,
        QUERIES,
        REQUIRED_QUERY_IDS,
        SUPPLEMENTARY_QUERY_IDS,
    )

HEADER = f"""# Phase 0 Audit Query Specification

**Catalogue version:** `{CATALOGUE_VERSION}`
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

- Core audit: {", ".join(REQUIRED_QUERY_IDS)}
- Supplementary readiness checks: {", ".join(SUPPLEMENTARY_QUERY_IDS)}

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
"""


def render() -> str:
    chunks = [HEADER]
    for query in QUERIES:
        chunks.append(
            f"| `{query.id}` | `{query.version}` | {query.title} | "
            f"{query.result_grain} | `{query.status}` |\n"
        )

    chunks.append(
        "\n---\n\n## Query details\n\n"
        "Each section lists the exact identifiers the validator checks. "
        "`schema_refs` is authoritative for table/column existence; the SQL "
        "text is additionally scanned for table references by the validator. "
        "Identifier validation is not semantic proof.\n\n"
    )

    for query in QUERIES:
        chunks.append(f"### `{query.id}` — {query.title}\n\n")
        chunks.append(f"- **Version:** `{query.version}`\n")
        chunks.append(f"- **Status:** `{query.status}`\n")
        chunks.append(f"- **Requirement:** {query.requirement}\n")
        chunks.append(f"- **Result grain:** {query.result_grain}\n")
        chunks.append(f"- **Purpose:** {query.purpose}\n\n")

        chunks.append("**Required tables and columns**\n\n")
        chunks.append("| Table | Columns |\n|---|---|\n")
        for table, columns in query.schema_refs.items():
            chunks.append(f"| `{table}` | {', '.join(f'`{c}`' for c in columns)} |\n")
        chunks.append("\n")

        chunks.append("**Expected output columns**\n\n")
        chunks.append(", ".join(f"`{column}`" for column in query.expected_columns))
        chunks.append("\n\n")

        chunks.append("**SQL (portable/SQLite form)**\n\n")
        chunks.append("```sql\n")
        chunks.append(query.sql_for("sqlite").strip())
        chunks.append("\n```\n\n")

        chunks.append(f"**Dialect considerations.** {query.dialect_notes}\n\n")
        chunks.append(f"**Interpretation.** {query.interpretation}\n\n")
        if query.deviations:
            chunks.append(f"**Deviation from the written requirement.** {query.deviations}\n\n")
        chunks.append("---\n\n")

    chunks.append(
        """## Known gaps in the original written requirements

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
"""
    )
    return "".join(chunks)


def main() -> int:
    parser = argparse.ArgumentParser(description="Render the Phase 0 query specification.")
    parser.add_argument(
        "--out",
        default=str(Path(__file__).resolve().parents[2] / "docs" / "audit" / "QUERY_SPEC.md"),
        help="output Markdown path",
    )
    args = parser.parse_args()
    out = Path(args.out).expanduser()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render(), encoding="utf-8")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
