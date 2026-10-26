"""Regression tests for the Phase 0 audit harness.

Run with:
    python -m unittest discover -s scripts/audit/tests -v

These tests use synthetic SQLite databases only.  They never touch the project
``db.sqlite3`` and never require PostgreSQL.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

AUDIT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(AUDIT_DIR))

from evidence import (  # noqa: E402
    EvidenceError,
    EvidenceRecord,
    build_evidence_pack,
    redact_rows,
)
from phase0_queries import (  # noqa: E402
    QUERIES,
    REQUIRED_QUERY_IDS,
    SUPPLEMENTARY_QUERY_IDS,
    get_query,
)
from run_dialect_matrix import (  # noqa: E402
    _execute_postgres,
    _postgres_dbname,
    run_matrix,
)
from schema_validator import (  # noqa: E402
    check_read_only,
    extract_table_references,
    load_sqlite_schema,
    sanitize_dsn,
    validate_catalogue,
)
from synthetic_fixtures import (  # noqa: E402
    DEFAULT_PATH,
    EXPECTED_CHECK_COUNTS,
    EXPECTED_ROW_COUNTS,
    REPO_ROOT,
    assert_synthetic_path,
    build_synthetic_database,
    schema_description,
)


class CatalogueTests(unittest.TestCase):
    def test_required_query_ids_are_present_and_unique(self):
        ids = [query.id for query in QUERIES]
        self.assertEqual(len(ids), len(set(ids)))
        for query_id in REQUIRED_QUERY_IDS:
            self.assertIn(query_id, ids)
        for query_id in SUPPLEMENTARY_QUERY_IDS:
            self.assertIn(query_id, ids)

    def test_every_query_is_a_draft_read_only_select(self):
        for query in QUERIES:
            with self.subTest(query=query.id):
                self.assertEqual(query.status, "DRAFT")
                self.assertEqual(check_read_only(query.sql_for("sqlite")), [])
                self.assertEqual(check_read_only(query.sql_for("postgres")), [])
                self.assertTrue(query.purpose)
                self.assertTrue(query.interpretation)
                self.assertTrue(query.expected_columns)
                self.assertTrue(query.schema_refs)

    def test_catalogue_status_never_claims_execution(self):
        self.assertTrue(all(query.status == "DRAFT" for query in QUERIES))

    def test_unknown_query_id_raises(self):
        with self.assertRaises(KeyError):
            get_query("Q-99")

    def test_unknown_dialect_raises(self):
        with self.assertRaises(KeyError):
            get_query("Q-01").sql_for("oracle")


class SchemaValidatorTests(unittest.TestCase):
    def test_synthetic_schema_passes(self):
        report = validate_catalogue(schema_description(), QUERIES, dialect="sqlite")
        self.assertTrue(report.ok, report.errors)
        self.assertEqual(report.checked_queries, len(QUERIES))
        self.assertGreater(report.checked_identifiers, 100)

    def test_unknown_table_is_rejected(self):
        schema = json.loads(json.dumps(schema_description()))
        del schema["tables"]["fees_payment"]
        report = validate_catalogue(schema, [get_query("Q-01")], dialect="sqlite")
        self.assertFalse(report.ok)
        self.assertTrue(any("unknown table: fees_payment" in e for e in report.errors))

    def test_unknown_column_is_rejected(self):
        schema = json.loads(json.dumps(schema_description()))
        schema["tables"]["fees_invoice"]["columns"].remove("total_amount")
        report = validate_catalogue(schema, [get_query("Q-01")], dialect="sqlite")
        self.assertFalse(report.ok)
        self.assertTrue(
            any("unknown column: fees_invoice.total_amount" in e for e in report.errors)
        )

    def test_write_statement_is_rejected(self):
        spec = dataclasses.replace(
            get_query("Q-01"),
            sql={"default": "DELETE FROM fees_invoice"},
        )
        report = validate_catalogue(schema_description(), [spec], dialect="sqlite")
        self.assertFalse(report.ok)
        self.assertTrue(any("forbidden" in e.lower() for e in report.errors))

    def test_multiple_statements_are_rejected(self):
        spec = dataclasses.replace(
            get_query("Q-01"),
            sql={"default": "SELECT 1; DROP TABLE fees_invoice"},
        )
        report = validate_catalogue(schema_description(), [spec], dialect="sqlite")
        self.assertFalse(report.ok)
        self.assertTrue(any("exactly one" in e for e in report.errors))

    def test_table_extraction_finds_all_q09_tables(self):
        tables = extract_table_references(get_query("Q-09").sql_for("sqlite"))
        self.assertEqual(
            tables,
            {
                "fees_feeprice",
                "fees_feecategory",
                "fees_invoicelineitem",
                "fees_invoice",
                "fees_payment",
                "students_student",
                "fees_paymentlineitem",
                "fees_feepriceoverride",
            },
        )

    def test_sqlite_introspection_matches_explicit_schema(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "synthetic_schema_check.sqlite3"
            build_synthetic_database(path)
            introspected = load_sqlite_schema(path)
            explicit = {
                table: set(info["columns"])
                for table, info in schema_description()["tables"].items()
            }
            self.assertEqual(set(introspected), set(explicit))
            for table, columns in explicit.items():
                self.assertEqual(set(introspected[table]), columns)

    def test_sanitize_dsn_never_leaks_password(self):
        sanitized = sanitize_dsn("postgresql://audit:supersecret@db.example/bust_audit_x")
        self.assertNotIn("supersecret", sanitized)
        self.assertIn("bust_audit_x", sanitized)


class FixtureTests(unittest.TestCase):
    def test_fixture_is_deterministic_and_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "synthetic_deterministic.sqlite3"
            first = build_synthetic_database(path)
            second = build_synthetic_database(path)
            self.assertEqual(first["fingerprint_sha256"], second["fingerprint_sha256"])
            self.assertEqual(first["row_counts"], second["row_counts"])
            self.assertEqual(first["total_rows"], 115)

    def test_fixture_refuses_project_database_and_repo_paths(self):
        with self.assertRaises(ValueError):
            assert_synthetic_path(REPO_ROOT / "db.sqlite3")
        with self.assertRaises(ValueError):
            assert_synthetic_path(REPO_ROOT / "synthetic_inside_repo.sqlite3")

    def test_fixture_contains_expected_anomalies(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "synthetic_anomalies.sqlite3"
            build_synthetic_database(path)
            import sqlite3

            conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
            try:
                for query_id, checks in EXPECTED_CHECK_COUNTS.items():
                    spec = get_query(query_id)
                    rows = conn.execute(spec.sql_for("sqlite")).fetchall()
                    actual = {row[0]: row[1] for row in rows}
                    for check_name, expected in checks.items():
                        self.assertEqual(
                            actual.get(check_name),
                            expected,
                            f"{query_id}.{check_name}",
                        )
            finally:
                conn.close()


class MatrixTests(unittest.TestCase):
    def test_sqlite_matrix_passes_and_never_claims_postgres(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "synthetic_matrix.sqlite3"
            build_synthetic_database(path)
            payload = run_matrix(path)
            self.assertEqual(payload["overall_status"], "PASS_WITH_POSTGRES_NOT_RUN")
            self.assertEqual(payload["sqlite"]["status"], "PASS")
            self.assertEqual(payload["postgres"]["status"], "NOT_RUN")
            self.assertFalse(payload["postgres_claimed"])
            self.assertEqual(payload["dialects_genuinely_tested"], ["sqlite"])
            self.assertTrue(payload["schema_validation"]["ok"])
            self.assertEqual(len(payload["sqlite"]["results"]), len(QUERIES))
            for result in payload["sqlite"]["results"]:
                self.assertEqual(result["status"], "PASS", result)
                self.assertIsNone(result["exception"])
                self.assertEqual(result["row_count"], EXPECTED_ROW_COUNTS[result["query_id"]])

    def test_matrix_is_read_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "synthetic_readonly.sqlite3"
            build_synthetic_database(path)
            before = hashlib.sha256(path.read_bytes()).hexdigest()
            run_matrix(path)
            after = hashlib.sha256(path.read_bytes()).hexdigest()
            self.assertEqual(before, after)

    def test_postgres_guard_refuses_non_synthetic_database_without_connecting(self):
        dsn = "postgresql://audit:secret@127.0.0.1:5432/production_school"
        self.assertEqual(_postgres_dbname(dsn), "production_school")
        result = _execute_postgres(dsn, [get_query("Q-01")], max_rows=10)
        self.assertEqual(result.status, "REFUSED")
        self.assertIn("synthetic/test", result.reason)
        self.assertNotIn("secret", result.reason)

    def test_evidence_builder_refuses_not_run_postgres(self):
        payload = {
            "generated_at": "2026-10-23T00:00:00+00:00",
            "sqlite": {"dialect": "sqlite", "engine_version": "3.45.1", "status": "PASS", "results": []},
            "postgres": {
                "dialect": "postgres",
                "engine_version": "unknown",
                "status": "NOT_RUN",
                "results": [],
            },
        }
        with self.assertRaises(EvidenceError):
            build_evidence_pack(
                payload,
                environment="local-synthetic",
                schema_revision="test",
                dialect="postgres",
            )


class EvidenceTests(unittest.TestCase):
    def test_redaction_removes_personal_columns_and_text_patterns(self):
        preview = redact_rows(
            ["admission_number", "note", "amount"],
            [("SYN-001", "email me at parent@example.invalid or 0803 123 4567", 100)],
        )
        row = preview["rows"][0]
        self.assertEqual(row["admission_number"], "[REDACTED]")
        self.assertNotIn("parent@example.invalid", row["note"])
        self.assertNotIn("0803 123 4567", row["note"])
        self.assertEqual(row["amount"], 100)

    def test_record_requires_reviewer_for_approved_status(self):
        record = EvidenceRecord(
            environment="local-synthetic",
            database_engine="sqlite",
            database_version="3.45.1",
            schema_revision="test",
            query_id="Q-01",
            query_version="1.0.0",
            executed_at="2026-10-23T00:00:00+00:00",
            row_count=1,
            result_sha256="a" * 64,
            reviewer=None,
            approval_status="APPROVED",
        )
        with self.assertRaises(EvidenceError):
            record.validate()

    def test_record_rejects_dsn_in_environment(self):
        record = EvidenceRecord(
            environment="postgresql://user:pass@host/db",
            database_engine="sqlite",
            database_version="3.45.1",
            schema_revision="test",
            query_id="Q-01",
            query_version="1.0.0",
            executed_at="2026-10-23T00:00:00+00:00",
            row_count=1,
            result_sha256="a" * 64,
            reviewer=None,
            approval_status="PENDING",
        )
        with self.assertRaises(EvidenceError):
            record.validate()

    def test_record_rejects_invalid_hash(self):
        record = EvidenceRecord(
            environment="local-synthetic",
            database_engine="sqlite",
            database_version="3.45.1",
            schema_revision="test",
            query_id="Q-01",
            query_version="1.0.0",
            executed_at="2026-10-23T00:00:00+00:00",
            row_count=1,
            result_sha256="not-a-hash",
            reviewer=None,
            approval_status="PENDING",
        )
        with self.assertRaises(EvidenceError):
            record.validate()

    def test_evidence_pack_from_real_matrix_redacts_q05(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "synthetic_evidence.sqlite3"
            build_synthetic_database(path)
            payload = run_matrix(path)
            pack = build_evidence_pack(
                payload,
                environment="local-synthetic",
                schema_revision="test-revision",
                reviewer="Synthetic Reviewer",
                approval_status="PENDING",
            )
            self.assertEqual(len(pack["records"]), len(QUERIES))
            self.assertTrue(all(r["approval_status"] == "PENDING" for r in pack["records"]))
            q05 = next(r for r in pack["records"] if r["query_id"] == "Q-05")
            self.assertGreater(q05["row_count"], 0)
            self.assertEqual(len(q05["result_sha256"]), 64)
            for row in q05["redacted_results"]["preview"]:
                self.assertEqual(row["admission_number"], "[REDACTED]")
            serialized = json.dumps(pack)
            self.assertNotIn("SYN-001", serialized)
            self.assertNotIn("postgresql://", serialized)


if __name__ == "__main__":
    unittest.main()
