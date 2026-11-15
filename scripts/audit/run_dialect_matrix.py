"""SQLite/PostgreSQL dialect-matrix runner (R-03).

READ-ONLY AND SYNTHETIC-ONLY
----------------------------
* SQLite is opened with ``mode=ro`` and ``PRAGMA query_only=ON``.
* PostgreSQL is opened read-only with a statement timeout.
* SQLite paths must pass :func:`synthetic_fixtures.assert_synthetic_path`.
* PostgreSQL database names must start with ``test_``, ``bust_audit_`` or
  ``bust_synthetic_``.  A production database name is refused.
* No fixture is written by this module.  Seed the synthetic PostgreSQL
  database separately before running the matrix.

The runner records column names, row counts and a SHA-256 of the ordered rows.
It does not print row contents.  A dialect is only reported as genuinely tested
when every query executed successfully against it.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import sys
import time
from dataclasses import dataclass, field
from datetime import date, datetime, time as datetime_time, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Sequence

try:  # package import
    from .phase0_queries import QUERIES, QuerySpec
    from .schema_validator import (
        load_sqlite_schema,
        sanitize_dsn,
        validate_catalogue,
    )
    from .synthetic_fixtures import assert_synthetic_path
    from .evidence import redact_rows
except ImportError:  # direct script execution
    from phase0_queries import QUERIES, QuerySpec  # type: ignore
    from schema_validator import (  # type: ignore
        load_sqlite_schema,
        sanitize_dsn,
        validate_catalogue,
    )
    from synthetic_fixtures import assert_synthetic_path  # type: ignore
    from evidence import redact_rows  # type: ignore

POSTGRES_SAFE_DB_RE = re.compile(r"^(test_|bust_audit_|bust_synthetic_)", re.IGNORECASE)


@dataclass
class QueryResult:
    query_id: str
    version: str
    dialect: str
    status: str
    columns: List[str] = field(default_factory=list)
    row_count: int = 0
    rows_sha256: str | None = None
    duration_ms: float = 0.0
    exception: str | None = None
    rows: List[tuple] = field(default_factory=list, repr=False)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "query_id": self.query_id,
            "version": self.version,
            "dialect": self.dialect,
            "status": self.status,
            "columns": list(self.columns),
            "row_count": self.row_count,
            "rows_sha256": self.rows_sha256,
            "duration_ms": round(self.duration_ms, 3),
            "exception": self.exception,
            "preview": redact_rows(self.columns, self.rows, max_rows=5),
        }


@dataclass
class DialectRun:
    dialect: str
    engine_version: str
    status: str
    results: List[QueryResult] = field(default_factory=list)
    reason: str | None = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "dialect": self.dialect,
            "engine_version": self.engine_version,
            "status": self.status,
            "reason": self.reason,
            "results": [result.to_dict() for result in self.results],
        }


def _json_default(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (datetime, date, datetime_time)):
        return value.isoformat()
    if isinstance(value, bytes):
        return value.hex()
    return str(value)


def hash_rows(rows: Iterable[Sequence[Any]]) -> str:
    digest = hashlib.sha256()
    for row in rows:
        digest.update(
            json.dumps(list(row), default=_json_default, separators=(",", ":")).encode(
                "utf-8"
            )
        )
    return digest.hexdigest()


def _result_from_cursor(
    spec: QuerySpec,
    dialect: str,
    cursor: Any,
    *,
    max_rows: int,
    duration_ms: float,
) -> QueryResult:
    columns = [description[0] for description in cursor.description or ()]
    rows = cursor.fetchmany(max_rows + 1)
    truncated = len(rows) > max_rows
    if truncated:
        rows = rows[:max_rows]
    return QueryResult(
        query_id=spec.id,
        version=spec.version,
        dialect=dialect,
        status="PASS",
        columns=columns,
        row_count=len(rows),
        rows_sha256=hash_rows(rows),
        duration_ms=duration_ms,
        exception=(
            f"result truncated at --max-rows={max_rows}" if truncated else None
        ),
        rows=list(rows),
    )


def _execute_sqlite(
    path: str | Path,
    specs: Sequence[QuerySpec],
    *,
    max_rows: int,
) -> DialectRun:
    resolved = assert_synthetic_path(path)
    if not resolved.exists():
        return DialectRun(
            dialect="sqlite",
            engine_version=sqlite3.sqlite_version,
            status="ERROR",
            reason=f"synthetic SQLite database not found: {resolved}",
        )
    conn = sqlite3.connect(f"file:{resolved}?mode=ro", uri=True)
    try:
        conn.execute("PRAGMA query_only = ON")
        results: List[QueryResult] = []
        for spec in specs:
            started = time.perf_counter()
            try:
                cursor = conn.execute(spec.sql_for("sqlite"))
                result = _result_from_cursor(
                    spec,
                    "sqlite",
                    cursor,
                    max_rows=max_rows,
                    duration_ms=(time.perf_counter() - started) * 1000,
                )
            except Exception as exc:  # noqa: BLE001 - reported per query
                result = QueryResult(
                    query_id=spec.id,
                    version=spec.version,
                    dialect="sqlite",
                    status="FAIL",
                    duration_ms=(time.perf_counter() - started) * 1000,
                    exception=f"{type(exc).__name__}: {exc}",
                )
            results.append(result)
        status = "PASS" if all(r.status == "PASS" for r in results) else "FAIL"
        return DialectRun(
            dialect="sqlite",
            engine_version=sqlite3.sqlite_version,
            status=status,
            results=results,
        )
    finally:
        conn.close()


def _postgres_dbname(dsn: str) -> str:
    try:
        import psycopg2.extensions as ext  # type: ignore

        return str(ext.parse_dsn(dsn).get("dbname", ""))
    except Exception:  # noqa: BLE001 - never leak DSN
        return ""


def _execute_postgres(
    dsn: str,
    specs: Sequence[QuerySpec],
    *,
    max_rows: int,
) -> DialectRun:
    dbname = _postgres_dbname(dsn)
    if not dbname or not POSTGRES_SAFE_DB_RE.match(dbname):
        return DialectRun(
            dialect="postgres",
            engine_version="unknown",
            status="REFUSED",
            reason=(
                "database name is not a synthetic/test name "
                "(expected test_*, bust_audit_* or bust_synthetic_*)"
            ),
        )

    try:
        import psycopg2  # type: ignore
    except ImportError:
        return DialectRun(
            dialect="postgres",
            engine_version="unknown",
            status="NOT_RUN",
            reason="psycopg2 is not installed",
        )

    try:
        conn = psycopg2.connect(dsn, connect_timeout=5)
    except Exception as exc:  # noqa: BLE001 - sanitize the message
        return DialectRun(
            dialect="postgres",
            engine_version="unknown",
            status="ERROR",
            reason=(
                f"connection failed ({type(exc).__name__}); "
                f"target={sanitize_dsn(dsn)}"
            ),
        )

    try:
        conn.set_session(readonly=True, autocommit=False)
        engine_version = "unknown"
        with conn.cursor() as cursor:
            cursor.execute("SET LOCAL statement_timeout = 30000")
            cursor.execute("SHOW server_version")
            engine_version = str(cursor.fetchone()[0])
        conn.rollback()
        results: List[QueryResult] = []
        for spec in specs:
            started = time.perf_counter()
            try:
                with conn.cursor() as cursor:
                    cursor.execute("SET LOCAL statement_timeout = 30000")
                    cursor.execute(spec.sql_for("postgres"))
                    result = _result_from_cursor(
                        spec,
                        "postgres",
                        cursor,
                        max_rows=max_rows,
                        duration_ms=(time.perf_counter() - started) * 1000,
                    )
                conn.rollback()
                results.append(result)
            except Exception as exc:  # noqa: BLE001 - reported per query
                conn.rollback()
                results.append(
                    QueryResult(
                        query_id=spec.id,
                        version=spec.version,
                        dialect="postgres",
                        status="FAIL",
                        duration_ms=(time.perf_counter() - started) * 1000,
                        exception=f"{type(exc).__name__}: {exc}",
                    )
                )
        status = "PASS" if all(r.status == "PASS" for r in results) else "FAIL"
        return DialectRun(
            dialect="postgres",
            engine_version=engine_version,
            status=status,
            results=results,
        )
    finally:
        conn.close()


def compare_dialects(sqlite_run: DialectRun, postgres_run: DialectRun) -> List[Dict[str, Any]]:
    """Compare columns and row counts per query id."""
    sqlite_by_id = {r.query_id: r for r in sqlite_run.results}
    differences: List[Dict[str, Any]] = []
    for pg_result in postgres_run.results:
        lite_result = sqlite_by_id.get(pg_result.query_id)
        if lite_result is None:
            differences.append(
                {
                    "query_id": pg_result.query_id,
                    "difference": "missing from SQLite run",
                }
            )
            continue
        if lite_result.status != pg_result.status:
            differences.append(
                {
                    "query_id": pg_result.query_id,
                    "difference": "status",
                    "sqlite": lite_result.status,
                    "postgres": pg_result.status,
                }
            )
        if [c.lower() for c in lite_result.columns] != [
            c.lower() for c in pg_result.columns
        ]:
            differences.append(
                {
                    "query_id": pg_result.query_id,
                    "difference": "columns",
                    "sqlite": lite_result.columns,
                    "postgres": pg_result.columns,
                }
            )
        if lite_result.row_count != pg_result.row_count:
            differences.append(
                {
                    "query_id": pg_result.query_id,
                    "difference": "row_count",
                    "sqlite": lite_result.row_count,
                    "postgres": pg_result.row_count,
                }
            )
    return differences


def run_matrix(
    sqlite_path: str | Path,
    *,
    postgres_dsn: str | None = None,
    query_ids: Iterable[str] | None = None,
    max_rows: int = 100000,
    validate_schema: bool = True,
) -> Dict[str, Any]:
    """Run the catalogue on SQLite and, when supplied, PostgreSQL."""
    specs = _select_queries(query_ids)
    sqlite_run = _execute_sqlite(sqlite_path, specs, max_rows=max_rows)

    schema_validation: Dict[str, Any] | None = None
    if validate_schema:
        try:
            schema = load_sqlite_schema(sqlite_path)
            report = validate_catalogue(schema, specs, dialect="sqlite")
            schema_validation = report.to_dict()
        except Exception as exc:  # noqa: BLE001 - reported, not fatal to execution
            schema_validation = {
                "ok": False,
                "errors": [f"{type(exc).__name__}: {exc}"],
            }

    if postgres_dsn:
        postgres_run = _execute_postgres(postgres_dsn, specs, max_rows=max_rows)
    else:
        postgres_run = DialectRun(
            dialect="postgres",
            engine_version="unknown",
            status="NOT_RUN",
            reason="no --postgres-dsn supplied; no PostgreSQL instance was contacted",
        )

    differences: List[Dict[str, Any]] = []
    if postgres_run.status in {"PASS", "FAIL"}:
        differences = compare_dialects(sqlite_run, postgres_run)

    dialects_tested = []
    if sqlite_run.status == "PASS":
        dialects_tested.append("sqlite")
    if postgres_run.status == "PASS" and not differences:
        dialects_tested.append("postgres")

    if postgres_run.status == "NOT_RUN":
        overall = "PASS_WITH_POSTGRES_NOT_RUN"
    elif postgres_run.status == "REFUSED":
        overall = "REFUSED_POSTGRES"
    elif sqlite_run.status != "PASS":
        overall = "FAIL_SQLITE"
    elif postgres_run.status == "PASS" and not differences:
        overall = "PASS_BOTH_DIALECTS"
    else:
        overall = "MISMATCH_OR_POSTGRES_FAILURE"

    return {
        "run_type": "phase0_dialect_matrix",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "synthetic_only": True,
        "production_claimed": False,
        "overall_status": overall,
        "dialects_genuinely_tested": dialects_tested,
        "postgres_claimed": "postgres" in dialects_tested,
        "sqlite": sqlite_run.to_dict(),
        "postgres": postgres_run.to_dict(),
        "differences": differences,
        "schema_validation": schema_validation,
    }


def _select_queries(query_ids: Iterable[str] | None) -> Sequence[QuerySpec]:
    if not query_ids:
        return QUERIES
    wanted = set(query_ids)
    selected = [q for q in QUERIES if q.id in wanted]
    missing = wanted - {q.id for q in selected}
    if missing:
        raise KeyError(f"Unknown query ids: {', '.join(sorted(missing))}")
    return selected


def _summary(payload: Mapping[str, Any]) -> str:
    lines = [
        f"overall: {payload['overall_status']}",
        f"dialects genuinely tested: {', '.join(payload['dialects_genuinely_tested']) or 'none'}",
        f"postgres claimed: {payload['postgres_claimed']}",
    ]
    schema = payload.get("schema_validation")
    if schema is not None:
        lines.append(f"schema validation: {'PASS' if schema.get('ok') else 'FAIL'}")
    for dialect in ("sqlite", "postgres"):
        block = payload[dialect]
        lines.append(
            f"{dialect}: {block['status']} "
            f"(version={block['engine_version']}, reason={block.get('reason')})"
        )
        for result in block.get("results", []):
            suffix = f" error={result['exception']}" if result.get("exception") else ""
            lines.append(
                f"  {result['query_id']} v{result['version']}: "
                f"{result['status']} rows={result['row_count']} "
                f"cols={len(result['columns'])}{suffix}"
            )
    if payload["differences"]:
        lines.append("differences:")
        for difference in payload["differences"]:
            lines.append(f"  - {difference}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the Phase 0 audit queries against synthetic SQLite/PostgreSQL."
    )
    parser.add_argument(
        "--sqlite",
        required=True,
        help="synthetic SQLite database built by synthetic_fixtures.py",
    )
    parser.add_argument(
        "--postgres-dsn",
        default=os.environ.get("AUDIT_POSTGRES_DSN"),
        help=(
            "read-only DSN for a synthetic PostgreSQL database. Can also be set "
            "with AUDIT_POSTGRES_DSN. Never passed on the command line in shared logs."
        ),
    )
    parser.add_argument(
        "--query",
        action="append",
        dest="queries",
        help="limit execution to one or more query ids",
    )
    parser.add_argument(
        "--max-rows",
        type=int,
        default=100000,
        help="maximum rows fetched per query (default: 100000)",
    )
    parser.add_argument("--json", action="store_true", help="emit JSON")
    parser.add_argument("--json-out", help="write JSON report to this path")
    args = parser.parse_args(argv)

    try:
        payload = run_matrix(
            args.sqlite,
            postgres_dsn=args.postgres_dsn,
            query_ids=args.queries,
            max_rows=args.max_rows,
        )
    except (KeyError, ValueError) as exc:
        print(f"matrix could not run: {exc}", file=sys.stderr)
        return 1

    text = json.dumps(payload, indent=2, sort_keys=True, default=str)
    if args.json:
        print(text)
    else:
        print(_summary(payload))
    if args.json_out:
        out = Path(args.json_out).expanduser()
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text + "\n", encoding="utf-8")
        if not args.json:
            print(f"JSON report: {out}")

    if payload["overall_status"] in {"PASS_WITH_POSTGRES_NOT_RUN"}:
        return 0
    if payload["overall_status"] == "PASS_BOTH_DIALECTS":
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
