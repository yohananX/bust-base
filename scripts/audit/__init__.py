"""Phase 0 audit harness (readiness tooling only).

This package contains no application code and makes no schema or behaviour
changes.  Every module is safe to import: database connections are only opened
by explicit CLI entry points, and those entry points refuse non-synthetic
targets.
"""

__all__ = [
    "phase0_queries",
    "schema_validator",
    "synthetic_fixtures",
    "run_dialect_matrix",
    "evidence",
]
