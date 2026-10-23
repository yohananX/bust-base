"""Evidence-pack records for Phase 0 audit runs (R-11).

Each record is self-contained and captures the environment, database engine and
version, schema revision, query id + version, execution timestamp, row count,
a hash of the ordered result, a small redacted preview, exceptions, reviewer and
approval status.

NO SECRETS, NO UNNECESSARY PERSONAL DATA
----------------------------------------
* DSNs and credentials are never accepted as evidence fields.
* Known personal/financial columns are replaced with a redaction marker.
* E-mail addresses and telephone-like values are redacted even in free text.
* The full result is represented by a SHA-256 hash, not by copying rows.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Sequence

EVIDENCE_PACK_VERSION = "1.0.0"
APPROVAL_STATUSES = ("PENDING", "APPROVED", "REJECTED")

#: Column-name fragments that trigger redaction.
SENSITIVE_COLUMN_TOKENS = (
    "email",
    "phone",
    "address",
    "admission_number",
    "passport",
    "guardian",
    "paid_by",
    "reference",
    "account_number",
    "bank",
    "token",
    "secret",
    "password",
)

_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_PHONE_RE = re.compile(r"(?<!\d)(?:\+?\d[\d\s().-]{7,}\d)(?!\d)")
_DSN_RE = re.compile(r"\b(?:postgres(?:ql)?|mysql|mariadb|mssql)://\S+", re.IGNORECASE)
_REDACTED = "[REDACTED]"


class EvidenceError(ValueError):
    """Raised for an invalid evidence record."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_scalar(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return value
    return str(value)


def is_sensitive_column(column: str) -> bool:
    lowered = column.lower()
    return any(token in lowered for token in SENSITIVE_COLUMN_TOKENS)


def redact_text(value: str) -> str:
    redacted = _DSN_RE.sub("[REDACTED_DSN]", value)
    redacted = _EMAIL_RE.sub("[REDACTED_EMAIL]", redacted)
    redacted = _PHONE_RE.sub("[REDACTED_PHONE]", redacted)
    return redacted


def redact_value(column: str, value: Any) -> Any:
    if value is None:
        return None
    if is_sensitive_column(column):
        return _REDACTED
    if isinstance(value, str):
        return redact_text(value)
    return _safe_scalar(value)


def redact_rows(
    columns: Sequence[str],
    rows: Iterable[Sequence[Any]],
    *,
    max_rows: int = 25,
) -> Dict[str, Any]:
    """Return a small, redacted preview and a truncation flag."""
    preview: List[Dict[str, Any]] = []
    total = 0
    for row in rows:
        total += 1
        if len(preview) < max_rows:
            preview.append(
                {
                    column: redact_value(column, value)
                    for column, value in zip(columns, row)
                }
            )
    return {"rows": preview, "truncated": total > max_rows, "preview_row_count": len(preview)}


def _validate_hex_digest(value: str | None) -> None:
    if value is None:
        return
    if not re.fullmatch(r"[0-9a-f]{64}", value):
        raise EvidenceError("result_sha256 must be a 64-character lowercase hex digest")


def _validate_no_secret_text(label: str, value: str | None) -> None:
    if value is None:
        return
    if _DSN_RE.search(value):
        raise EvidenceError(f"{label} must not contain a connection string or DSN")
    lowered = value.lower()
    for marker in ("password=", "secret=", "token=", "api_key="):
        if marker in lowered:
            raise EvidenceError(f"{label} must not contain credential material ({marker})")


@dataclass
class EvidenceRecord:
    environment: str
    database_engine: str
    database_version: str
    schema_revision: str
    query_id: str
    query_version: str
    executed_at: str
    row_count: int
    result_sha256: str | None
    reviewer: str | None
    approval_status: str
    redacted_results: Dict[str, Any] = field(default_factory=dict)
    exceptions: List[str] = field(default_factory=list)
    notes: str = ""
    run_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    source: str = "synthetic"

    def validate(self) -> None:
        for label, value in (
            ("environment", self.environment),
            ("database_engine", self.database_engine),
            ("database_version", self.database_version),
            ("schema_revision", self.schema_revision),
            ("query_id", self.query_id),
            ("query_version", self.query_version),
            ("executed_at", self.executed_at),
            ("source", self.source),
        ):
            if not value or not str(value).strip():
                raise EvidenceError(f"{label} is required")
            _validate_no_secret_text(label, str(value))

        if self.approval_status not in APPROVAL_STATUSES:
            raise EvidenceError(
                f"approval_status must be one of {APPROVAL_STATUSES}, "
                f"got {self.approval_status!r}"
            )
        if self.approval_status in {"APPROVED", "REJECTED"} and not (
            self.reviewer and self.reviewer.strip()
        ):
            raise EvidenceError(
                f"reviewer is required when approval_status is {self.approval_status}"
            )
        if self.row_count < 0:
            raise EvidenceError("row_count must be non-negative")
        _validate_hex_digest(self.result_sha256)
        try:
            datetime.fromisoformat(self.executed_at.replace("Z", "+00:00"))
        except ValueError as exc:
            raise EvidenceError("executed_at must be ISO-8601") from exc
        if self.reviewer:
            _validate_no_secret_text("reviewer", self.reviewer)
        if self.notes:
            _validate_no_secret_text("notes", self.notes)

    def to_dict(self) -> Dict[str, Any]:
        self.validate()
        return {
            "evidence_pack_version": EVIDENCE_PACK_VERSION,
            "run_id": self.run_id,
            "environment": self.environment,
            "database_engine": self.database_engine,
            "database_version": self.database_version,
            "schema_revision": self.schema_revision,
            "query_id": self.query_id,
            "query_version": self.query_version,
            "executed_at": self.executed_at,
            "row_count": self.row_count,
            "result_sha256": self.result_sha256,
            "redacted_results": self.redacted_results,
            "exceptions": list(self.exceptions),
            "reviewer": self.reviewer,
            "approval_status": self.approval_status,
            "notes": self.notes,
            "source": self.source,
        }


def build_evidence_pack(
    matrix_payload: Mapping[str, Any],
    *,
    environment: str,
    schema_revision: str,
    reviewer: str | None = None,
    approval_status: str = "PENDING",
    dialect: str = "sqlite",
    redaction_max_rows: int = 25,
    notes: str = "",
) -> Dict[str, Any]:
    """Build an evidence pack from a ``run_dialect_matrix`` JSON payload."""
    if dialect not in {"sqlite", "postgres"}:
        raise EvidenceError("dialect must be 'sqlite' or 'postgres'")
    block = matrix_payload.get(dialect)
    if not isinstance(block, Mapping):
        raise EvidenceError(f"matrix payload has no {dialect!r} block")
    if block.get("status") in {None, "NOT_RUN", "REFUSED", "ERROR"}:
        raise EvidenceError(
            f"{dialect} was not genuinely tested (status={block.get('status')!r}); "
            "refusing to create evidence that implies execution"
        )

    records: List[Dict[str, Any]] = []
    for result in block.get("results", []):
        exceptions = []
        if result.get("exception"):
            exceptions.append(str(result["exception"]))
        record = EvidenceRecord(
            environment=environment,
            database_engine=str(block.get("dialect", dialect)),
            database_version=str(block.get("engine_version", "unknown")),
            schema_revision=schema_revision,
            query_id=str(result["query_id"]),
            query_version=str(result["version"]),
            executed_at=str(matrix_payload.get("generated_at") or _utc_now()),
            row_count=int(result.get("row_count", 0)),
            result_sha256=result.get("rows_sha256"),
            reviewer=reviewer,
            approval_status=approval_status,
            redacted_results={
                "columns": list(result.get("columns", [])),
                "preview": list(result.get("preview", {}).get("rows", [])),
                "preview_row_count": int(
                    result.get("preview", {}).get("preview_row_count", 0)
                ),
                "truncated": bool(result.get("preview", {}).get("truncated", False)),
            },
            exceptions=exceptions,
            notes=notes,
            source="synthetic",
        )
        records.append(record.to_dict())

    reviewer_value = reviewer if reviewer else None
    return {
        "evidence_pack_version": EVIDENCE_PACK_VERSION,
        "run_id": uuid.uuid4().hex[:12],
        "environment": environment,
        "database_engine": str(block.get("dialect", dialect)),
        "database_version": str(block.get("engine_version", "unknown")),
        "schema_revision": schema_revision,
        "executed_at": str(matrix_payload.get("generated_at") or _utc_now()),
        "reviewer": reviewer_value,
        "approval_status": approval_status,
        "source": "synthetic",
        "records": records,
    }


def git_revision() -> str:
    """Return ``<commit>[-dirty]`` using read-only git commands."""
    try:
        commit = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=Path(__file__).resolve().parents[2],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
        status = subprocess.check_output(
            ["git", "status", "--porcelain"],
            cwd=Path(__file__).resolve().parents[2],
            text=True,
            stderr=subprocess.DEVNULL,
        )
        return f"{commit}{'-dirty' if status.strip() else ''}"
    except Exception:  # noqa: BLE001 - evidence generation must not fail on git
        return "unknown"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Create a redacted Phase 0 evidence pack from a dialect matrix."
    )
    parser.add_argument("--from-matrix", required=True, help="matrix JSON report")
    parser.add_argument("--out", required=True, help="evidence JSON output path")
    parser.add_argument("--environment", required=True, help="e.g. local-synthetic")
    parser.add_argument(
        "--schema-revision",
        default=None,
        help="schema revision string (default: git commit, dirty-marked)",
    )
    parser.add_argument("--reviewer", default=None)
    parser.add_argument(
        "--approval-status",
        default="PENDING",
        choices=APPROVAL_STATUSES,
    )
    parser.add_argument(
        "--dialect",
        default="sqlite",
        choices=("sqlite", "postgres"),
    )
    parser.add_argument("--notes", default="")
    args = parser.parse_args(argv)

    try:
        matrix_payload = json.loads(Path(args.from_matrix).read_text(encoding="utf-8"))
        pack = build_evidence_pack(
            matrix_payload,
            environment=args.environment,
            schema_revision=args.schema_revision or git_revision(),
            reviewer=args.reviewer,
            approval_status=args.approval_status,
            dialect=args.dialect,
            notes=args.notes,
        )
    except (EvidenceError, OSError, json.JSONDecodeError) as exc:
        print(f"evidence pack not created: {exc}", file=sys.stderr)
        return 1

    out = Path(args.out).expanduser()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(pack, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"evidence pack: {out}")
    print(f"records: {len(pack['records'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
