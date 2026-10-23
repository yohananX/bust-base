"""Deterministic synthetic fixtures for the Phase 0 audit harness (R-04).

SAFETY
------
* Fabricated data only.  No production personal or financial information is
  present; e-mail addresses use the reserved ``.invalid`` TLD.
* The builder refuses to write inside the repository, refuses the project's
  ``db.sqlite3``, and only accepts paths under a temporary directory or a path
  whose filename contains ``synthetic``.
* The schema is deliberately permissive (no foreign-key constraints) so the
  seed can create the orphan and cross-school rows the audit must detect.
  Identifier validation cares about names, not constraints.

The fixture is deterministic: rebuilding into the same path produces the same
table counts and fingerprint.  It is intended for SQLite only.  PostgreSQL
compatibility must be proven against a real PostgreSQL instance, not assumed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import tempfile
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Tuple

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PATH = Path("/tmp/opencode/bust_audit_synthetic.sqlite3")

#: table -> ((column, sqlite_type), ...)
SCHEMA: Mapping[str, Tuple[Tuple[str, str], ...]] = {
    "core_school": (
        ("id", "INTEGER"),
        ("name", "TEXT"),
        ("short_code", "TEXT"),
        ("is_active", "INTEGER"),
        ("created_at", "TEXT"),
    ),
    "core_academicsession": (
        ("id", "INTEGER"),
        ("school_id", "INTEGER"),
        ("name", "TEXT"),
        ("start_date", "TEXT"),
        ("end_date", "TEXT"),
        ("is_current", "INTEGER"),
    ),
    "core_term": (
        ("id", "INTEGER"),
        ("school_id", "INTEGER"),
        ("session_id", "INTEGER"),
        ("name", "TEXT"),
        ("start_date", "TEXT"),
        ("end_date", "TEXT"),
        ("is_current", "INTEGER"),
        ("results_published", "INTEGER"),
    ),
    "accounts_user": (
        ("id", "INTEGER"),
        ("school_id", "INTEGER"),
        ("username", "TEXT"),
        ("email", "TEXT"),
        ("role", "TEXT"),
        ("first_name", "TEXT"),
        ("last_name", "TEXT"),
        ("is_active", "INTEGER"),
    ),
    "students_student": (
        ("id", "INTEGER"),
        ("school_id", "INTEGER"),
        ("user_id", "INTEGER"),
        ("admission_number", "TEXT"),
        ("date_of_birth", "TEXT"),
        ("gender", "TEXT"),
        ("admission_date", "TEXT"),
        ("status", "TEXT"),
        ("registration_paid_term_id", "INTEGER"),
        ("student_type", "TEXT"),
        ("updated_at", "TEXT"),
    ),
    "students_schoolclass": (
        ("id", "INTEGER"),
        ("school_id", "INTEGER"),
        ("name", "TEXT"),
        ("level", "TEXT"),
        ("academic_stage_id", "INTEGER"),
        ("is_active", "INTEGER"),
    ),
    "students_classenrollment": (
        ("id", "INTEGER"),
        ("school_id", "INTEGER"),
        ("student_id", "INTEGER"),
        ("school_class_id", "INTEGER"),
        ("session_id", "INTEGER"),
        ("enrolled_on", "TEXT"),
        ("is_current", "INTEGER"),
    ),
    "fees_feecategory": (
        ("id", "INTEGER"),
        ("school_id", "INTEGER"),
        ("name", "TEXT"),
        ("is_compulsory", "INTEGER"),
        ("billing_cycle", "TEXT"),
        ("student_type", "TEXT"),
    ),
    "fees_feeprice": (
        ("id", "INTEGER"),
        ("school_id", "INTEGER"),
        ("category_id", "INTEGER"),
        ("name", "TEXT"),
        ("amount", "INTEGER"),
        ("term_id", "INTEGER"),
        ("student_type", "TEXT"),
        ("scope", "TEXT"),
        ("school_class_id", "INTEGER"),
        ("level", "TEXT"),
        ("is_active", "INTEGER"),
        ("effective_from", "TEXT"),
        ("effective_to", "TEXT"),
    ),
    "fees_feepriceoverride": (
        ("id", "INTEGER"),
        ("school_id", "INTEGER"),
        ("student_id", "INTEGER"),
        ("category_id", "INTEGER"),
        ("amount", "INTEGER"),
        ("reason", "TEXT"),
        ("valid_from", "TEXT"),
        ("valid_to", "TEXT"),
        ("is_active", "INTEGER"),
    ),
    "fees_invoice": (
        ("id", "INTEGER"),
        ("school_id", "INTEGER"),
        ("student_id", "INTEGER"),
        ("term_id", "INTEGER"),
        ("generated_on", "TEXT"),
        ("total_amount", "INTEGER"),
    ),
    "fees_invoicelineitem": (
        ("id", "INTEGER"),
        ("school_id", "INTEGER"),
        ("invoice_id", "INTEGER"),
        ("category_id", "INTEGER"),
        ("item_name", "TEXT"),
        ("amount", "INTEGER"),
        ("term_id", "INTEGER"),
        ("session_id", "INTEGER"),
        ("billing_cycle", "TEXT"),
    ),
    "fees_payment": (
        ("id", "INTEGER"),
        ("school_id", "INTEGER"),
        ("invoice_id", "INTEGER"),
        ("student_id", "INTEGER"),
        ("description", "TEXT"),
        ("amount", "INTEGER"),
        ("method", "TEXT"),
        ("reference", "TEXT"),
        ("status", "TEXT"),
        ("paid_on", "TEXT"),
        ("recorded_by_id", "INTEGER"),
        ("confirmed_by_id", "INTEGER"),
    ),
    "fees_feereceipt": (
        ("id", "INTEGER"),
        ("school_id", "INTEGER"),
        ("receipt_number", "TEXT"),
        ("payment_id", "INTEGER"),
        ("issued_at", "TEXT"),
    ),
    "fees_paymentlineitem": (
        ("id", "INTEGER"),
        ("payment_id", "INTEGER"),
        ("school_id", "INTEGER"),
        ("kind", "TEXT"),
        ("label", "TEXT"),
        ("amount", "INTEGER"),
        ("source_key", "TEXT"),
        ("category_id", "INTEGER"),
        ("term_id", "INTEGER"),
        ("session_id", "INTEGER"),
        ("invoice_id", "INTEGER"),
    ),
    "academics_score": (
        ("id", "INTEGER"),
        ("school_id", "INTEGER"),
        ("student_id", "INTEGER"),
        ("subject_id", "INTEGER"),
        ("term_id", "INTEGER"),
        ("entered_by_id", "INTEGER"),
        ("exam_score", "INTEGER"),
    ),
}


def _rows() -> Dict[str, List[Dict[str, Any]]]:
    """Return all synthetic rows, keyed by table."""
    return {
        "core_school": [
            {"id": 1, "name": "Synthetic Alpha", "short_code": "syn-alpha", "is_active": 1, "created_at": "2024-01-01T00:00:00"},
            {"id": 2, "name": "Synthetic Beta", "short_code": "syn-beta", "is_active": 1, "created_at": "2024-01-01T00:00:00"},
        ],
        "core_academicsession": [
            {"id": 1, "school_id": 1, "name": "2024/2025", "start_date": "2024-09-01", "end_date": "2025-07-31", "is_current": 0},
            {"id": 2, "school_id": 1, "name": "2025/2026", "start_date": "2025-09-01", "end_date": "2026-07-31", "is_current": 1},
            {"id": 3, "school_id": 2, "name": "2025/2026", "start_date": "2025-09-01", "end_date": "2026-07-31", "is_current": 1},
        ],
        "core_term": [
            {"id": 1, "school_id": 1, "session_id": 1, "name": "First Term", "start_date": "2024-09-01", "end_date": "2024-12-20", "is_current": 0, "results_published": 1},
            {"id": 2, "school_id": 1, "session_id": 1, "name": "Second Term", "start_date": "2025-01-06", "end_date": "2025-04-11", "is_current": 0, "results_published": 1},
            {"id": 3, "school_id": 1, "session_id": 2, "name": "First Term", "start_date": "2025-09-01", "end_date": "2025-12-19", "is_current": 1, "results_published": 0},
            {"id": 4, "school_id": 2, "session_id": 3, "name": "First Term", "start_date": "2025-09-01", "end_date": "2025-12-19", "is_current": 1, "results_published": 0},
            # No active FeePrice references this term: exercises IC-8.
            {"id": 5, "school_id": 1, "session_id": 2, "name": "Third Term", "start_date": "2026-04-13", "end_date": "2026-07-31", "is_current": 0, "results_published": 0},
        ],
        "accounts_user": [
            {"id": 1, "school_id": 1, "username": "alpha.admin", "email": "alpha.admin@example.invalid", "role": "ADMIN", "first_name": "Ada", "last_name": "Alpha", "is_active": 1},
            {"id": 2, "school_id": 1, "username": "alpha.teacher", "email": "alpha.teacher@example.invalid", "role": "TEACHER", "first_name": "Tunde", "last_name": "Teacher", "is_active": 1},
            {"id": 3, "school_id": 2, "username": "beta.admin", "email": "beta.admin@example.invalid", "role": "ADMIN", "first_name": "Bisi", "last_name": "Beta", "is_active": 1},
            {"id": 4, "school_id": 1, "username": "alpha.student1", "email": "alpha.student1@example.invalid", "role": "STUDENT", "first_name": "Sade", "last_name": "One", "is_active": 1},
            {"id": 5, "school_id": 1, "username": "alpha.student2", "email": "alpha.student2@example.invalid", "role": "STUDENT", "first_name": "Sam", "last_name": "Two", "is_active": 1},
            {"id": 6, "school_id": 1, "username": "alpha.student3", "email": "alpha.student3@example.invalid", "role": "STUDENT", "first_name": "Sola", "last_name": "Three", "is_active": 1},
            {"id": 7, "school_id": 2, "username": "beta.student4", "email": "beta.student4@example.invalid", "role": "STUDENT", "first_name": "Bola", "last_name": "Four", "is_active": 1},
            {"id": 8, "school_id": 1, "username": "alpha.student5", "email": "alpha.student5@example.invalid", "role": "STUDENT", "first_name": "Femi", "last_name": "Five", "is_active": 1},
        ],
        "students_student": [
            {"id": 1, "school_id": 1, "user_id": 4, "admission_number": "SYN-001", "date_of_birth": "2012-01-01", "gender": "F", "admission_date": "2024-09-01", "status": "ACTIVE", "registration_paid_term_id": None, "student_type": "NEW", "updated_at": "2024-09-01T00:00:00"},
            {"id": 2, "school_id": 1, "user_id": 5, "admission_number": "SYN-002", "date_of_birth": "2011-02-02", "gender": "M", "admission_date": "2023-09-01", "status": "ACTIVE", "registration_paid_term_id": 1, "student_type": "RETURNING", "updated_at": "2024-09-01T00:00:00"},
            {"id": 3, "school_id": 1, "user_id": 6, "admission_number": "SYN-003", "date_of_birth": "2010-03-03", "gender": "F", "admission_date": "2022-09-01", "status": "ACTIVE", "registration_paid_term_id": None, "student_type": "RETURNING", "updated_at": "2024-09-01T00:00:00"},
            {"id": 4, "school_id": 2, "user_id": 7, "admission_number": "SYN-004", "date_of_birth": "2015-04-04", "gender": "M", "admission_date": "2025-09-01", "status": "ACTIVE", "registration_paid_term_id": 4, "student_type": "NEW", "updated_at": "2025-09-01T00:00:00"},
            {"id": 5, "school_id": 1, "user_id": 8, "admission_number": "SYN-005", "date_of_birth": "2013-05-05", "gender": "F", "admission_date": "2024-09-01", "status": "ACTIVE", "registration_paid_term_id": None, "student_type": "NEW", "updated_at": "2024-09-01T00:00:00"},
        ],
        "students_schoolclass": [
            {"id": 1, "school_id": 1, "name": "JSS1A", "level": "JSS1", "academic_stage_id": None, "is_active": 1},
            {"id": 2, "school_id": 1, "name": "JSS2A", "level": "JSS2", "academic_stage_id": None, "is_active": 1},
            {"id": 3, "school_id": 2, "name": "P1", "level": "Primary 1", "academic_stage_id": None, "is_active": 1},
            {"id": 4, "school_id": 1, "name": "JSS1B", "level": "JSS1", "academic_stage_id": None, "is_active": 1},
        ],
        "students_classenrollment": [
            {"id": 1, "school_id": 1, "student_id": 1, "school_class_id": 1, "session_id": 1, "enrolled_on": "2024-09-01", "is_current": 1},
            {"id": 2, "school_id": 1, "student_id": 2, "school_class_id": 2, "session_id": 1, "enrolled_on": "2024-09-01", "is_current": 1},
            {"id": 3, "school_id": 1, "student_id": 3, "school_class_id": 1, "session_id": 2, "enrolled_on": "2025-09-01", "is_current": 1},
            {"id": 4, "school_id": 2, "student_id": 4, "school_class_id": 3, "session_id": 3, "enrolled_on": "2025-09-01", "is_current": 1},
            {"id": 5, "school_id": 1, "student_id": 5, "school_class_id": 1, "session_id": 1, "enrolled_on": "2024-09-01", "is_current": 1},
        ],
        "fees_feecategory": [
            {"id": 1, "school_id": 1, "name": "Tuition", "is_compulsory": 1, "billing_cycle": "PER_TERM", "student_type": "ALL"},
            {"id": 2, "school_id": 1, "name": "Registration Form", "is_compulsory": 1, "billing_cycle": "ONE_TIME", "student_type": "NEW"},
            {"id": 3, "school_id": 1, "name": "Books", "is_compulsory": 0, "billing_cycle": "PER_TERM", "student_type": "ALL"},
            {"id": 4, "school_id": 2, "name": "Tuition", "is_compulsory": 1, "billing_cycle": "PER_TERM", "student_type": "ALL"},
            {"id": 5, "school_id": 1, "name": "Christmas Fee", "is_compulsory": 1, "billing_cycle": "ONE_TIME", "student_type": "ALL"},
            {"id": 6, "school_id": 1, "name": "Uniform", "is_compulsory": 0, "billing_cycle": "ONE_TIME", "student_type": "ALL"},
        ],
        "fees_feeprice": [
            {"id": 1, "school_id": 1, "category_id": 1, "name": "Tuition JSS1A", "amount": 50000, "term_id": 1, "student_type": "ALL", "scope": "CLASS", "school_class_id": 1, "level": "", "is_active": 1, "effective_from": "2024-09-01", "effective_to": "2024-12-31"},
            {"id": 2, "school_id": 1, "category_id": 1, "name": "Tuition JSS1 level", "amount": 55000, "term_id": 1, "student_type": "ALL", "scope": "LEVEL", "school_class_id": None, "level": "JSS1", "is_active": 1, "effective_from": None, "effective_to": None},
            {"id": 3, "school_id": 1, "category_id": 2, "name": "Registration", "amount": 10000, "term_id": None, "student_type": "NEW", "scope": "SCHOOL_WIDE", "school_class_id": None, "level": "", "is_active": 1, "effective_from": None, "effective_to": None},
            {"id": 4, "school_id": 1, "category_id": 2, "name": "Registration", "amount": 10000, "term_id": None, "student_type": "NEW", "scope": "SCHOOL_WIDE", "school_class_id": None, "level": "", "is_active": 1, "effective_from": None, "effective_to": None},
            {"id": 5, "school_id": 1, "category_id": 1, "name": "Tuition JSS2A T2", "amount": 60000, "term_id": 2, "student_type": "ALL", "scope": "CLASS", "school_class_id": 2, "level": "", "is_active": 1, "effective_from": "2025-01-01", "effective_to": "2025-04-30"},
            {"id": 6, "school_id": 1, "category_id": 1, "name": "Tuition JSS1 level T2", "amount": 55000, "term_id": 2, "student_type": "ALL", "scope": "LEVEL", "school_class_id": None, "level": "JSS1", "is_active": 1, "effective_from": None, "effective_to": None},
            {"id": 7, "school_id": 1, "category_id": 3, "name": "Books blank level", "amount": 7000, "term_id": 2, "student_type": "ALL", "scope": "LEVEL", "school_class_id": None, "level": "", "is_active": 1, "effective_from": None, "effective_to": None},
            {"id": 8, "school_id": 2, "category_id": 4, "name": "Tuition P1", "amount": 45000, "term_id": 4, "student_type": "ALL", "scope": "CLASS", "school_class_id": 3, "level": "", "is_active": 1, "effective_from": None, "effective_to": None},
            {"id": 9, "school_id": 1, "category_id": 5, "name": "Christmas", "amount": 5000, "term_id": None, "student_type": "ALL", "scope": "SCHOOL_WIDE", "school_class_id": None, "level": "", "is_active": 1, "effective_from": None, "effective_to": None},
            {"id": 10, "school_id": 1, "category_id": 1, "name": "Tuition JSS1A T3", "amount": 65000, "term_id": 3, "student_type": "ALL", "scope": "CLASS", "school_class_id": 1, "level": "", "is_active": 1, "effective_from": None, "effective_to": None},
            {"id": 11, "school_id": 1, "category_id": 1, "name": "Tuition JSS1A Returning", "amount": 50000, "term_id": 1, "student_type": "RETURNING", "scope": "CLASS", "school_class_id": 1, "level": "", "is_active": 1, "effective_from": None, "effective_to": None},
            {"id": 12, "school_id": 1, "category_id": 4, "name": "Cross-school category", "amount": 1234, "term_id": 1, "student_type": "ALL", "scope": "CLASS", "school_class_id": 1, "level": "", "is_active": 1, "effective_from": None, "effective_to": None},
            {"id": 13, "school_id": 2, "category_id": 1, "name": "Cross-school category", "amount": 1234, "term_id": 4, "student_type": "ALL", "scope": "CLASS", "school_class_id": 3, "level": "", "is_active": 1, "effective_from": None, "effective_to": None},
            {"id": 14, "school_id": 1, "category_id": 999, "name": "Orphan category", "amount": 999, "term_id": 1, "student_type": "ALL", "scope": "CLASS", "school_class_id": 1, "level": "", "is_active": 1, "effective_from": None, "effective_to": None},
            {"id": 15, "school_id": 1, "category_id": 6, "name": "Uniform", "amount": 8000, "term_id": None, "student_type": "ALL", "scope": "SCHOOL_WIDE", "school_class_id": None, "level": "", "is_active": 1, "effective_from": None, "effective_to": None},
            {"id": 16, "school_id": 1, "category_id": 1, "name": "Tuition JSS1A duplicate", "amount": 50000, "term_id": 1, "student_type": "ALL", "scope": "CLASS", "school_class_id": 1, "level": "", "is_active": 1, "effective_from": None, "effective_to": None},
            {"id": 17, "school_id": 1, "category_id": 1, "name": "Tuition JSS2 level new", "amount": 56000, "term_id": 1, "student_type": "NEW", "scope": "LEVEL", "school_class_id": None, "level": "JSS2", "is_active": 1, "effective_from": None, "effective_to": None},
        ],
        "fees_feepriceoverride": [
            {"id": 1, "school_id": 1, "student_id": 1, "category_id": 1, "amount": 40000, "reason": "Synthetic scholarship", "valid_from": "2024-09-01", "valid_to": "2025-07-31", "is_active": 1},
            {"id": 2, "school_id": 1, "student_id": 3, "category_id": 3, "amount": 5000, "reason": "Synthetic hardship", "valid_from": "2025-01-01", "valid_to": "2025-04-30", "is_active": 1},
            {"id": 3, "school_id": 1, "student_id": 4, "category_id": 1, "amount": 30000, "reason": "Cross-school student", "valid_from": "2024-09-01", "valid_to": "2025-07-31", "is_active": 1},
            {"id": 4, "school_id": 1, "student_id": 1, "category_id": 4, "amount": 30000, "reason": "Cross-school category", "valid_from": "2024-09-01", "valid_to": "2025-07-31", "is_active": 1},
            {"id": 5, "school_id": 1, "student_id": 999, "category_id": 1, "amount": 20000, "reason": "Orphan student", "valid_from": "2024-09-01", "valid_to": "2025-07-31", "is_active": 1},
            {"id": 6, "school_id": 1, "student_id": 1, "category_id": 999, "amount": 20000, "reason": "Orphan category", "valid_from": "2024-09-01", "valid_to": "2025-07-31", "is_active": 1},
        ],
        "fees_invoice": [
            {"id": 1, "school_id": 1, "student_id": 1, "term_id": 1, "generated_on": "2024-09-05T10:00:00", "total_amount": 60000},
            {"id": 2, "school_id": 1, "student_id": 2, "term_id": 1, "generated_on": "2024-09-05T10:01:00", "total_amount": 55000},
            {"id": 3, "school_id": 1, "student_id": 3, "term_id": 2, "generated_on": "2025-01-10T10:00:00", "total_amount": 65000},
            {"id": 4, "school_id": 2, "student_id": 4, "term_id": 4, "generated_on": "2025-09-05T10:00:00", "total_amount": 45000},
            {"id": 5, "school_id": 1, "student_id": 1, "term_id": 3, "generated_on": "2025-09-05T10:00:00", "total_amount": 80000},
            {"id": 7, "school_id": 1, "student_id": 5, "term_id": 3, "generated_on": "2025-09-06T10:00:00", "total_amount": 1000},
            {"id": 8, "school_id": 1, "student_id": 3, "term_id": 1, "generated_on": "2024-09-07T10:00:00", "total_amount": 2000},
            {"id": 9, "school_id": 1, "student_id": 5, "term_id": 2, "generated_on": "2025-01-11T10:00:00", "total_amount": 500},
            {"id": 10, "school_id": 1, "student_id": 2, "term_id": 3, "generated_on": "2025-09-08T10:00:00", "total_amount": 1000},
        ],
        "fees_invoicelineitem": [
            {"id": 1, "school_id": 1, "invoice_id": 1, "category_id": 1, "item_name": "Tuition", "amount": 50000, "term_id": 1, "session_id": 1, "billing_cycle": "PER_TERM"},
            {"id": 2, "school_id": 1, "invoice_id": 1, "category_id": 2, "item_name": "", "amount": 10000, "term_id": 1, "session_id": 1, "billing_cycle": "ONE_TIME"},
            {"id": 3, "school_id": 1, "invoice_id": 2, "category_id": 1, "item_name": "Tuition Fee \u2014 JSS2", "amount": 55000, "term_id": 1, "session_id": 1, "billing_cycle": "PER_TERM"},
            {"id": 4, "school_id": 1, "invoice_id": 3, "category_id": 1, "item_name": "Tuition", "amount": 60000, "term_id": 2, "session_id": 1, "billing_cycle": "PER_TERM"},
            {"id": 5, "school_id": 2, "invoice_id": 4, "category_id": 4, "item_name": "Tuition", "amount": 45000, "term_id": 4, "session_id": 3, "billing_cycle": "PER_TERM"},
            {"id": 6, "school_id": 1, "invoice_id": 5, "category_id": 1, "item_name": "Tuition (legacy)", "amount": 65000, "term_id": 3, "session_id": 2, "billing_cycle": "PER_TERM"},
            {"id": 7, "school_id": 1, "invoice_id": 5, "category_id": 5, "item_name": "Christmas Fee", "amount": 5000, "term_id": 3, "session_id": 2, "billing_cycle": "ONE_TIME"},
            {"id": 8, "school_id": 1, "invoice_id": 5, "category_id": 2, "item_name": "Registration Form", "amount": 10000, "term_id": 3, "session_id": 2, "billing_cycle": "ONE_TIME"},
            {"id": 9, "school_id": 2, "invoice_id": 7, "category_id": 1, "item_name": "Cross-school line", "amount": 1000, "term_id": 1, "session_id": 1, "billing_cycle": "PER_TERM"},
            {"id": 10, "school_id": 1, "invoice_id": 8, "category_id": 4, "item_name": "Cross-school category", "amount": 2000, "term_id": 1, "session_id": 1, "billing_cycle": "PER_TERM"},
            {"id": 11, "school_id": None, "invoice_id": 9, "category_id": 1, "item_name": None, "amount": 500, "term_id": 2, "session_id": 1, "billing_cycle": "PER_TERM"},
            {"id": 900, "school_id": 1, "invoice_id": 999, "category_id": 1, "item_name": "Orphan invoice", "amount": 100, "term_id": 1, "session_id": 1, "billing_cycle": "PER_TERM"},
            {"id": 901, "school_id": 1, "invoice_id": 999, "category_id": 999, "item_name": "Orphan category", "amount": 200, "term_id": 1, "session_id": 1, "billing_cycle": "PER_TERM"},
        ],
        "fees_payment": [
            {"id": 1, "school_id": 1, "invoice_id": 1, "student_id": 1, "description": "Full payment", "amount": 60000, "method": "CASH", "reference": "REF-001", "status": "CONFIRMED", "paid_on": "2024-09-06T09:00:00", "recorded_by_id": 1, "confirmed_by_id": 1},
            {"id": 2, "school_id": 1, "invoice_id": 2, "student_id": 2, "description": "Part payment", "amount": 30000, "method": "BANK_TRANSFER", "reference": "REF-002", "status": "CONFIRMED", "paid_on": "2024-09-06T09:10:00", "recorded_by_id": 1, "confirmed_by_id": 1},
            {"id": 3, "school_id": 1, "invoice_id": 2, "student_id": 2, "description": "Pending balance", "amount": 25000, "method": "BANK_TRANSFER", "reference": "REF-003", "status": "PENDING", "paid_on": "2024-09-06T09:11:00", "recorded_by_id": 1, "confirmed_by_id": None},
            {"id": 4, "school_id": 1, "invoice_id": 3, "student_id": 3, "description": "Part payment", "amount": 10000, "method": "CASH", "reference": "REF-004", "status": "CONFIRMED", "paid_on": "2025-01-12T09:00:00", "recorded_by_id": 2, "confirmed_by_id": 1},
            {"id": 5, "school_id": 2, "invoice_id": 4, "student_id": 4, "description": "Full payment", "amount": 45000, "method": "CASH", "reference": "REF-005", "status": "CONFIRMED", "paid_on": "2025-09-06T09:00:00", "recorded_by_id": 3, "confirmed_by_id": 3},
            {"id": 6, "school_id": 1, "invoice_id": 5, "student_id": 1, "description": "Full payment", "amount": 65000, "method": "CASH", "reference": "REF-006", "status": "CONFIRMED", "paid_on": "2025-09-06T09:00:00", "recorded_by_id": 1, "confirmed_by_id": 1},
            {"id": 7, "school_id": 1, "invoice_id": None, "student_id": 5, "description": "No invoice payment", "amount": 5000, "method": "CASH", "reference": "REF-007", "status": "CONFIRMED", "paid_on": "2024-09-07T09:00:00", "recorded_by_id": 1, "confirmed_by_id": 1},
            {"id": 8, "school_id": 2, "invoice_id": 1, "student_id": 1, "description": "Cross-school payment", "amount": 1000, "method": "CARD", "reference": "REF-008", "status": "PENDING", "paid_on": "2024-09-08T09:00:00", "recorded_by_id": 3, "confirmed_by_id": None},
            {"id": 9, "school_id": 1, "invoice_id": 3, "student_id": 3, "description": "Failed attempt", "amount": 5000, "method": "CARD", "reference": "REF-009", "status": "FAILED", "paid_on": "2025-01-13T09:00:00", "recorded_by_id": 1, "confirmed_by_id": None},
            {"id": 10, "school_id": 1, "invoice_id": 999, "student_id": 5, "description": "Orphan invoice payment", "amount": 1, "method": "CASH", "reference": "REF-010", "status": "CONFIRMED", "paid_on": "2024-09-09T09:00:00", "recorded_by_id": 1, "confirmed_by_id": 1},
            {"id": 11, "school_id": 1, "invoice_id": 1, "student_id": 999, "description": "Orphan student payment", "amount": 1, "method": "CASH", "reference": "REF-011", "status": "CONFIRMED", "paid_on": "2024-09-10T09:00:00", "recorded_by_id": 1, "confirmed_by_id": 1},
        ],
        "fees_feereceipt": [
            {"id": 1, "school_id": 1, "receipt_number": "RCPT-001", "payment_id": 1, "issued_at": "2024-09-06T09:05:00"},
            {"id": 2, "school_id": 1, "receipt_number": "RCPT-002", "payment_id": 2, "issued_at": "2024-09-06T09:15:00"},
            {"id": 3, "school_id": 1, "receipt_number": "RCPT-003", "payment_id": 4, "issued_at": "2025-01-12T09:05:00"},
            {"id": 4, "school_id": 1, "receipt_number": "RCPT-004", "payment_id": 6, "issued_at": "2025-09-06T09:05:00"},
            {"id": 5, "school_id": 1, "receipt_number": "RCPT-005", "payment_id": 999, "issued_at": "2024-09-06T09:20:00"},
            {"id": 6, "school_id": 1, "receipt_number": "RCPT-006", "payment_id": 1, "issued_at": "2024-09-06T09:06:00"},
        ],
        "fees_paymentlineitem": [
            {"id": 1, "payment_id": 1, "school_id": 1, "kind": "outstanding", "label": "Tuition", "amount": 60000, "source_key": "inv1-cat1", "category_id": 1, "term_id": 1, "session_id": 1, "invoice_id": 1},
            {"id": 2, "payment_id": 2, "school_id": 1, "kind": "outstanding", "label": "Tuition", "amount": 30000, "source_key": "inv2-cat1", "category_id": 1, "term_id": 1, "session_id": 1, "invoice_id": 2},
            {"id": 3, "payment_id": 4, "school_id": 1, "kind": "outstanding", "label": "Tuition", "amount": 10000, "source_key": "inv3-cat1", "category_id": 1, "term_id": 2, "session_id": 1, "invoice_id": 3},
            {"id": 4, "payment_id": 5, "school_id": 2, "kind": "outstanding", "label": "Tuition", "amount": 45000, "source_key": "inv4-cat4", "category_id": 4, "term_id": 4, "session_id": 3, "invoice_id": 4},
            {"id": 5, "payment_id": 6, "school_id": 1, "kind": "outstanding", "label": "Tuition", "amount": 65000, "source_key": "inv5-cat1", "category_id": 1, "term_id": 3, "session_id": 2, "invoice_id": 5},
            {"id": 6, "payment_id": 1, "school_id": 2, "kind": "extra", "label": "Cross-school allocation", "amount": 60000, "source_key": "inv1-cat1", "category_id": 1, "term_id": 1, "session_id": 1, "invoice_id": 1},
            {"id": 7, "payment_id": 999, "school_id": 1, "kind": "outstanding", "label": "Orphan payment", "amount": 100, "source_key": "orphan", "category_id": 1, "term_id": 1, "session_id": 1, "invoice_id": 1},
            {"id": 8, "payment_id": 1, "school_id": 1, "kind": "extra", "label": "Extra allocation", "amount": 0, "source_key": "extra", "category_id": 1, "term_id": 1, "session_id": 1, "invoice_id": 1},
        ],
        "academics_score": [
            {"id": 1, "school_id": 1, "student_id": 1, "subject_id": 1, "term_id": 1, "entered_by_id": 2, "exam_score": 80},
            {"id": 2, "school_id": 1, "student_id": 3, "subject_id": 1, "term_id": 2, "entered_by_id": 1, "exam_score": 70},
            {"id": 3, "school_id": 2, "student_id": 4, "subject_id": 1, "term_id": 4, "entered_by_id": 3, "exam_score": 90},
            {"id": 4, "school_id": 1, "student_id": 2, "subject_id": 1, "term_id": 1, "entered_by_id": 2, "exam_score": 60},
        ],
    }


#: Exact expected values for checks that prove a specific anomaly exists.
EXPECTED_CHECK_COUNTS: Mapping[str, Mapping[str, int]] = {
    "Q-04": {
        "confirmed_payment_without_receipt": 4,
        "receipt_without_payment": 1,
        "duplicate_receipts_per_payment": 1,
    },
    "Q-09": {
        "feeprice_category_cross_school": 2,
        "feeprice_category_orphan": 1,
        "lineitem_invoice_cross_school": 1,
        "lineitem_invoice_orphan": 2,
        "lineitem_category_cross_school": 2,
        "lineitem_category_orphan": 1,
        "lineitem_school_null": 1,
        "payment_invoice_cross_school": 1,
        "payment_invoice_orphan": 1,
        "payment_student_cross_school": 1,
        "payment_student_orphan": 1,
        "paymentlineitem_payment_cross_school": 1,
        "paymentlineitem_payment_orphan": 1,
        "paymentlineitem_invoice_cross_school": 1,
        "override_student_cross_school": 1,
        "override_student_orphan": 1,
        "override_category_cross_school": 1,
        "override_category_orphan": 1,
    },
    "IC-8": {
        "invoice_total_mismatch": 2,
        "invoice_without_line_items": 1,
        "line_item_without_category": 1,
        "term_without_active_price": 1,
    },
    "IC-9": {
        "missing_item_name": 2,
        "item_name_equals_current_category": 5,
    },
    "IC-10": {
        "category_delete_line_items": 13,
        "payment_delete_receipts": 6,
        "student_delete_invoices": 9,
        "student_delete_payments": 11,
        "invoice_delete_line_items": 13,
        "student_delete_scores": 4,
        "staff_delete_payments": 11,
        "staff_delete_scores": 4,
    },
}

#: Exact expected result-row counts for every catalogue query.
EXPECTED_ROW_COUNTS: Mapping[str, int] = {
    "Q-01": 8,
    "Q-02": 9,
    "Q-03": 6,
    "Q-04": 3,
    "Q-05": 7,
    "Q-06": 2,
    "Q-07": 4,
    "Q-08": 2,
    "Q-09": 18,
    "Q-10": 6,
    "IC-8": 4,
    "IC-9": 2,
    "IC-10": 8,
}


def schema_description() -> Dict[str, Any]:
    """Return an explicit schema description suitable for the validator."""
    return {
        "tables": {
            table: {
                "columns": [name for name, _ in columns],
                "types": {name: sql_type for name, sql_type in columns},
            }
            for table, columns in SCHEMA.items()
        }
    }


def _quote_ident(name: str) -> str:
    if not name.replace("_", "").isalnum() or not name[0].isalpha():
        raise ValueError(f"Unsafe SQL identifier in synthetic schema: {name!r}")
    return '"' + name.replace('"', '""') + '"'


def assert_synthetic_path(path: str | Path) -> Path:
    """Refuse unsafe database paths.

    The harness must never touch the project database or any path inside the
    repository.  This is a safety guard, not a substitute for review.
    """
    resolved = Path(path).expanduser().resolve()
    project_db = (REPO_ROOT / "db.sqlite3").resolve()
    if resolved == project_db:
        raise ValueError("Refusing to use the project db.sqlite3")
    if resolved == REPO_ROOT or REPO_ROOT in resolved.parents:
        raise ValueError("Refusing to write a synthetic database inside the repository")
    allowed_roots = {
        Path("/tmp").resolve(),
        Path("/tmp/opencode").resolve(),
        Path("/var/tmp").resolve(),
        Path(tempfile.gettempdir()).resolve(),
    }
    if not any(resolved == root or root in resolved.parents for root in allowed_roots):
        if "synthetic" not in resolved.name.lower():
            raise ValueError(
                "Synthetic database path must be under a temporary directory or "
                "contain 'synthetic' in its filename"
            )
    return resolved


def _create_schema(conn: sqlite3.Connection) -> None:
    for table, columns in SCHEMA.items():
        column_sql = ", ".join(
            f"{_quote_ident(name)} {sql_type}" for name, sql_type in columns
        )
        conn.execute(f"CREATE TABLE {_quote_ident(table)} ({column_sql})")


def _insert_rows(conn: sqlite3.Connection, table: str, rows: Iterable[Dict[str, Any]]) -> None:
    rows = list(rows)
    if not rows:
        return
    columns = list(rows[0].keys())
    placeholders = ", ".join("?" for _ in columns)
    sql = (
        f"INSERT INTO {_quote_ident(table)} "
        f"({', '.join(_quote_ident(c) for c in columns)}) "
        f"VALUES ({placeholders})"
    )
    conn.executemany(sql, [tuple(row[column] for column in columns) for row in rows])


def build_synthetic_database(path: str | Path = DEFAULT_PATH, *, reset: bool = True) -> Dict[str, Any]:
    """Create the synthetic SQLite database and return a manifest.

    Parameters
    ----------
    path:
        Destination.  Must pass :func:`assert_synthetic_path`.
    reset:
        When the file exists, replace it.  When false, refuse to overwrite.
    """
    resolved = assert_synthetic_path(path)
    if resolved.exists():
        if not reset:
            raise FileExistsError(
                f"{resolved} already exists; pass reset=True to rebuild it"
            )
        resolved.unlink()

    resolved.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(resolved)
    try:
        conn.execute("PRAGMA foreign_keys = OFF")
        conn.execute("PRAGMA journal_mode = DELETE")
        _create_schema(conn)
        data = _rows()
        for table in SCHEMA:
            _insert_rows(conn, table, data.get(table, []))
        conn.commit()
        counts = {}
        for table in SCHEMA:
            counts[table] = conn.execute(
                f"SELECT COUNT(*) FROM {_quote_ident(table)}"
            ).fetchone()[0]
        fingerprint = _fingerprint(conn)
    finally:
        conn.close()

    return {
        "path": str(resolved),
        "engine": "sqlite",
        "engine_version": sqlite3.sqlite_version,
        "tables": len(SCHEMA),
        "row_counts": counts,
        "total_rows": sum(counts.values()),
        "fingerprint_sha256": fingerprint,
        "expected_row_counts": dict(EXPECTED_ROW_COUNTS),
        "expected_check_counts": {
            query_id: dict(checks)
            for query_id, checks in EXPECTED_CHECK_COUNTS.items()
        },
        "synthetic": True,
        "fabricated_data_only": True,
    }


def _fingerprint(conn: sqlite3.Connection) -> str:
    digest = hashlib.sha256()
    for table in sorted(SCHEMA):
        digest.update(table.encode("utf-8"))
        cursor = conn.execute(f"SELECT * FROM {_quote_ident(table)} ORDER BY id")
        columns = [description[0] for description in cursor.description]
        digest.update(json.dumps(columns, separators=(",", ":")).encode("utf-8"))
        for row in cursor.fetchall():
            digest.update(
                json.dumps(row, default=str, separators=(",", ":")).encode("utf-8")
            )
    return digest.hexdigest()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build the deterministic Phase 0 synthetic SQLite database."
    )
    parser.add_argument(
        "path",
        nargs="?",
        default=str(DEFAULT_PATH),
        help=f"destination (default: {DEFAULT_PATH})",
    )
    parser.add_argument(
        "--no-reset",
        action="store_true",
        help="refuse to replace an existing file",
    )
    parser.add_argument(
        "--dump-schema",
        metavar="PATH",
        help="write the explicit schema description as JSON",
    )
    parser.add_argument("--json", action="store_true", help="print the manifest as JSON")
    args = parser.parse_args(argv)

    manifest = build_synthetic_database(args.path, reset=not args.no_reset)
    if args.dump_schema:
        schema_path = Path(args.dump_schema).expanduser().resolve()
        schema_path.parent.mkdir(parents=True, exist_ok=True)
        schema_path.write_text(
            json.dumps(schema_description(), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        manifest["schema_description_path"] = str(schema_path)

    if args.json:
        print(json.dumps(manifest, indent=2, sort_keys=True))
    else:
        print(f"Synthetic database: {manifest['path']}")
        print(f"SQLite version:     {manifest['engine_version']}")
        print(f"Tables:             {manifest['tables']}")
        print(f"Total rows:         {manifest['total_rows']}")
        print(f"Fingerprint:        {manifest['fingerprint_sha256']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
