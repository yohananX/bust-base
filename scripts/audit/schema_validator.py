"""Schema-identifier validator for the Phase 0 audit catalogue (R-02).

WHAT THIS PROVES
----------------
It proves that every table and column the catalogue *declares* exists in a
supplied schema description, and that every table the SQL text appears to read
is declared.  It rejects unknown tables/columns and any non-read-only
statement.

WHAT THIS DOES **NOT** PROVE
----------------------------
It does not prove SQL semantics.  It never executes query text.  String
extraction of table names is a conservative cross-check, not a parser.  A query
still has to be executed on the dialect matrix (R-03) and reviewed by a human.

SAFE BY CONSTRUCTION
--------------------
* SQLite is opened with ``mode=ro`` and ``PRAGMA query_only=ON``; only
  ``sqlite_master`` and ``PRAGMA table_info`` are read.
* PostgreSQL is opened read-only with a statement timeout and only
  ``information_schema.columns`` is read.
* DSNs are never printed with a password.
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, MutableMapping, Sequence, Set, Tuple

try:  # package import
    from .phase0_queries import QUERIES, QuerySpec
except ImportError:  # direct script execution
    from phase0_queries import QUERIES, QuerySpec  # type: ignore

FORBIDDEN_KEYWORDS = (
    "INSERT",
    "UPDATE",
    "DELETE",
    "MERGE",
    "UPSERT",
    "REPLACE",
    "DROP",
    "ALTER",
    "CREATE",
    "TRUNCATE",
    "GRANT",
    "REVOKE",
    "ATTACH",
    "DETACH",
    "PRAGMA",
    "VACUUM",
    "REINDEX",
    "ANALYZE",
)

_IDENTIFIER = r"[A-Za-z_][A-Za-z0-9_]*"
_TABLE_REF_RE = re.compile(
    rf"\b(?:FROM|JOIN)\s+(\"(?:[^\"]|\"\")*\"|{_IDENTIFIER})",
    re.IGNORECASE,
)
_COMMENT_RE = re.compile(r"--[^\n]*|/\*.*?\*/", re.DOTALL)
_STRING_RE = re.compile(r"'(?:[^']|'')*'", re.DOTALL)
_SEMICOLON_RE = re.compile(r";")


class SchemaSourceError(RuntimeError):
    """Raised when a schema source cannot be read safely."""


@dataclass
class ValidationReport:
    dialect: str
    checked_queries: int = 0
    checked_identifiers: int = 0
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    def to_dict(self) -> Dict[str, Any]:
        return {
            "dialect": self.dialect,
            "ok": self.ok,
            "checked_queries": self.checked_queries,
            "checked_identifiers": self.checked_identifiers,
            "errors": list(self.errors),
            "warnings": list(self.warnings),
        }


# ---------------------------------------------------------------------------
# Schema sources
# ---------------------------------------------------------------------------


def _normalize_schema(raw: Mapping[str, Any]) -> Dict[str, Dict[str, str]]:
    """Accept ``{table: [cols]}``, ``{table: {col: type}}`` or
    ``{"tables": {...}}`` and return ``table -> {column: type}``.
    """
    if "tables" in raw and isinstance(raw["tables"], Mapping):
        raw = raw["tables"]
    normalized: Dict[str, Dict[str, str]] = {}
    for table, columns in raw.items():
        if not isinstance(table, str) or not re.fullmatch(_IDENTIFIER, table):
            raise ValueError(f"Invalid table name in schema description: {table!r}")
        if isinstance(columns, Mapping) and "columns" in columns:
            # ``{table: {"columns": [...], "types": {...}}}`` form.
            column_list = columns["columns"]
            types = columns.get("types", {})
            if not isinstance(column_list, (list, tuple, set)):
                raise ValueError(
                    f"'columns' for table {table!r} must be a list, got "
                    f"{type(column_list)!r}"
                )
            column_map = {str(column): str(types.get(column, "")) for column in column_list}
        elif isinstance(columns, Mapping):
            # ``{table: {column: type}}`` form.
            column_map = {str(k): str(v) for k, v in columns.items()}
        elif isinstance(columns, (list, tuple, set)):
            column_map = {str(column): "" for column in columns}
        else:
            raise ValueError(f"Invalid columns for table {table!r}: {type(columns)!r}")
        for column in column_map:
            if not re.fullmatch(_IDENTIFIER, column):
                raise ValueError(f"Invalid column name {column!r} on {table!r}")
        normalized[table] = column_map
    if not normalized:
        raise ValueError("Schema description is empty")
    return normalized


def load_schema_json(path: str | Path) -> Dict[str, Dict[str, str]]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise ValueError("Schema JSON must be an object")
    return _normalize_schema(payload)


def load_sqlite_schema(path: str | Path) -> Dict[str, Dict[str, str]]:
    """Read only table/column metadata from a SQLite database."""
    resolved = Path(path).expanduser().resolve()
    if not resolved.exists():
        raise SchemaSourceError(f"SQLite database not found: {resolved}")
    try:
        conn = sqlite3.connect(f"file:{resolved}?mode=ro", uri=True)
    except sqlite3.Error as exc:  # pragma: no cover - environment dependent
        raise SchemaSourceError(f"Cannot open SQLite database read-only: {exc}") from exc
    try:
        conn.execute("PRAGMA query_only = ON")
        tables = [
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
            )
        ]
        schema: Dict[str, Dict[str, str]] = {}
        for table in tables:
            quoted = '"' + table.replace('"', '""') + '"'
            columns = conn.execute(f"PRAGMA table_info({quoted})").fetchall()
            schema[table] = {
                row[1]: (row[2] or "") for row in columns
            }
        return schema
    except sqlite3.Error as exc:  # pragma: no cover - environment dependent
        raise SchemaSourceError(f"SQLite introspection failed: {exc}") from exc
    finally:
        conn.close()


def sanitize_dsn(dsn: str) -> str:
    """Return a DSN safe to print: no password, no query string values."""
    try:
        import psycopg2.extensions as ext  # type: ignore

        parsed = ext.parse_dsn(dsn)
    except Exception:  # noqa: BLE001 - never leak the raw DSN
        return "<unparseable-dsn>"
    host = parsed.get("host", "<unknown-host>")
    dbname = parsed.get("dbname", "<unknown-db>")
    user = parsed.get("user", "<unknown-user>")
    return f"postgresql://{user}@{host}/{dbname}"


def load_postgres_schema(dsn: str) -> Dict[str, Dict[str, str]]:
    """Read only table/column metadata from PostgreSQL.

    The session is read-only and time-limited.  No application table rows are
    selected.
    """
    try:
        import psycopg2  # type: ignore
    except ImportError as exc:  # pragma: no cover - psycopg2 is a project dependency
        raise SchemaSourceError("psycopg2 is not installed") from exc

    try:
        conn = psycopg2.connect(dsn, connect_timeout=5)
    except Exception as exc:  # noqa: BLE001 - sanitize the message
        raise SchemaSourceError(
            f"PostgreSQL connection failed ({type(exc).__name__}); "
            f"target={sanitize_dsn(dsn)}"
        ) from exc

    try:
        conn.set_session(readonly=True, autocommit=False)
        with conn.cursor() as cursor:
            cursor.execute("SET LOCAL statement_timeout = 15000")
            cursor.execute(
                """
                SELECT table_schema, table_name, column_name, data_type
                FROM information_schema.columns
                WHERE table_schema NOT IN ('pg_catalog', 'information_schema')
                ORDER BY table_schema, table_name, ordinal_position
                """
            )
            schema: Dict[str, Dict[str, str]] = {}
            for table_schema, table_name, column_name, data_type in cursor.fetchall():
                # Use unqualified names; audit queries use the default search path.
                schema.setdefault(table_name, {})[column_name] = data_type
        conn.rollback()
        return schema
    except Exception as exc:  # noqa: BLE001 - sanitize the message
        raise SchemaSourceError(
            f"PostgreSQL introspection failed ({type(exc).__name__}); "
            f"target={sanitize_dsn(dsn)}"
        ) from exc
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# SQL text checks
# ---------------------------------------------------------------------------


def strip_comments_and_literals(sql: str) -> str:
    """Remove comments and single-quoted literals for conservative scanning."""
    without_comments = _COMMENT_RE.sub(" ", sql)
    return _STRING_RE.sub("''", without_comments)


def check_read_only(sql: str) -> list[str]:
    """Return errors if *sql* is not a single read-only statement."""
    errors: list[str] = []
    stripped = strip_comments_and_literals(sql).strip()
    statements = [part.strip() for part in _SEMICOLON_RE.split(stripped) if part.strip()]
    if len(statements) != 1:
        errors.append(
            f"expected exactly one SQL statement, found {len(statements)}"
        )
    statement = statements[0] if statements else ""
    if not re.match(r"^(SELECT|WITH)\b", statement, re.IGNORECASE):
        errors.append("statement must begin with SELECT or WITH")
    for keyword in FORBIDDEN_KEYWORDS:
        if re.search(rf"\b{keyword}\b", statement, re.IGNORECASE):
            errors.append(f"forbidden write/DDL keyword detected: {keyword}")
    if re.search(r"\bFOR\s+UPDATE\b", statement, re.IGNORECASE):
        errors.append("SELECT ... FOR UPDATE takes locks and is not allowed")
    if re.search(r"\bINTO\s+\w", statement, re.IGNORECASE):
        errors.append("SELECT INTO creates a table and is not allowed")
    return errors


def extract_table_references(sql: str) -> Set[str]:
    """Conservatively extract table names following FROM/JOIN."""
    stripped = strip_comments_and_literals(sql)
    tables: Set[str] = set()
    for match in _TABLE_REF_RE.finditer(stripped):
        name = match.group(1)
        if name.startswith('"') and name.endswith('"'):
            name = name[1:-1].replace('""', '"')
        tables.add(name)
    return tables


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def validate_catalogue(
    schema: Mapping[str, Any],
    queries: Sequence[QuerySpec] = QUERIES,
    *,
    dialect: str = "sqlite",
) -> ValidationReport:
    """Validate all declared identifiers and read-only SQL for *dialect*."""
    report = ValidationReport(dialect=dialect)
    normalized = _normalize_schema(schema)

    seen_ids: Set[str] = set()
    for spec in queries:
        report.checked_queries += 1
        prefix = f"{spec.id}: "

        if spec.id in seen_ids:
            report.errors.append(prefix + "duplicate query id")
        seen_ids.add(spec.id)
        if not spec.expected_columns:
            report.errors.append(prefix + "expected_columns is empty")
        if spec.status not in {"DRAFT", "EXECUTED"}:
            report.errors.append(prefix + f"invalid status {spec.status!r}")

        try:
            sql = spec.sql_for(dialect)
        except KeyError as exc:
            report.errors.append(prefix + str(exc))
            continue

        for error in check_read_only(sql):
            report.errors.append(prefix + error)

        declared_tables = set(spec.schema_refs)
        extracted_tables = extract_table_references(sql)

        for table in sorted(declared_tables - set(normalized)):
            report.errors.append(prefix + f"unknown table: {table}")
        for table in sorted(extracted_tables - declared_tables):
            report.errors.append(
                prefix + f"SQL reads table not declared in schema_refs: {table}"
            )
        for table in sorted(declared_tables - extracted_tables):
            report.warnings.append(
                prefix + f"declared table not detected in SQL text: {table}"
            )

        for table, columns in spec.schema_refs.items():
            report.checked_identifiers += 1
            if table not in normalized:
                continue  # already reported
            schema_columns = normalized[table]
            for column in columns:
                report.checked_identifiers += 1
                if column not in schema_columns:
                    report.errors.append(
                        prefix + f"unknown column: {table}.{column}"
                    )

        if len(set(spec.expected_columns)) != len(spec.expected_columns):
            report.errors.append(prefix + "expected_columns contains duplicates")

    return report


def format_report(report: ValidationReport) -> str:
    lines = [
        f"dialect: {report.dialect}",
        f"queries checked: {report.checked_queries}",
        f"identifiers checked: {report.checked_identifiers}",
        f"result: {'PASS' if report.ok else 'FAIL'}",
    ]
    if report.errors:
        lines.append("errors:")
        lines.extend(f"  - {error}" for error in report.errors)
    if report.warnings:
        lines.append("warnings:")
        lines.extend(f"  - {warning}" for warning in report.warnings)
    return "\n".join(lines)


def _select_queries(query_ids: Iterable[str] | None) -> Sequence[QuerySpec]:
    if not query_ids:
        return QUERIES
    wanted = set(query_ids)
    selected = [q for q in QUERIES if q.id in wanted]
    missing = wanted - {q.id for q in selected}
    if missing:
        raise KeyError(f"Unknown query ids: {', '.join(sorted(missing))}")
    return selected


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate audit-query identifiers against a schema."
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--schema-json", help="explicit schema description JSON")
    source.add_argument("--sqlite", help="SQLite database to introspect read-only")
    source.add_argument("--postgres-dsn", help="PostgreSQL DSN to introspect read-only")
    source.add_argument(
        "--synthetic-schema",
        action="store_true",
        help="use the schema declared by synthetic_fixtures.py (no DB connection)",
    )
    parser.add_argument(
        "--dialect",
        default="sqlite",
        choices=("sqlite", "postgres"),
        help="SQL variant to validate (default: sqlite)",
    )
    parser.add_argument(
        "--query",
        action="append",
        dest="queries",
        help="limit validation to one or more query ids",
    )
    parser.add_argument("--json", action="store_true", help="emit JSON")
    args = parser.parse_args(argv)

    try:
        if args.schema_json:
            schema = load_schema_json(args.schema_json)
            source_label = f"json:{args.schema_json}"
        elif args.sqlite:
            schema = load_sqlite_schema(args.sqlite)
            source_label = f"sqlite:{args.sqlite}"
        elif args.postgres_dsn:
            schema = load_postgres_schema(args.postgres_dsn)
            source_label = sanitize_dsn(args.postgres_dsn)
        else:
            try:
                from .synthetic_fixtures import schema_description
            except ImportError:
                from synthetic_fixtures import schema_description  # type: ignore
            schema = _normalize_schema(schema_description())
            source_label = "synthetic_fixtures.SCHEMA"

        queries = _select_queries(args.queries)
        report = validate_catalogue(schema, queries, dialect=args.dialect)
    except (ValueError, KeyError, SchemaSourceError) as exc:
        print(f"validation could not run: {exc}", file=sys.stderr)
        return 2

    if args.json:
        payload = report.to_dict()
        payload["source"] = source_label
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(f"source: {source_label}")
        print(format_report(report))
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
