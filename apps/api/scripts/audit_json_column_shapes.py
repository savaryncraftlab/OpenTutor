"""READ-ONLY audit: prove every JSON column holds its expected shape.

Prerequisite gate for the schema-wide ``CompatJSONB -> MutableDict /
MutableList`` swap (see ``plan/compatjsonb_mutable_swap_plan.md`` §B and
RISK #1). ``MutableDict.as_mutable`` / ``MutableList.as_mutable`` raise at
load time on a row whose stored JSON is the wrong container type (a scalar
or the opposite of dict/list). This script scans the on-disk SQLite DB and
fails (exit 1) if any non-NULL row in a target column does not match the
shape the swap will assume. It never writes, never imports the ORM, and
opens the DB strictly read-only.

Supported invocations
----------------------
(a) In-container (preferred — audits the live file directly)::

        docker exec -i opentutor-api python3 \
            apps/api/scripts/audit_json_column_shapes.py

(b) Host (copy the DB out first, then audit the copy)::

        docker cp opentutor-api:/app/data/opentutor.db ./_auditcopy.db && \
            python apps/api/scripts/audit_json_column_shapes.py \
                --db ./_auditcopy.db

Pure standard library only (``sqlite3``, ``json``, ``argparse``, ``sys``).
No SQLAlchemy, no ORM, no project imports — runs in a minimal container
or on a bare host.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys

# ---------------------------------------------------------------------------
# CONTRACT — the (table, column, expected-shape) inventory.
#
# This list IS the contract the MutableDict/MutableList swap will rely on.
# Each entry: (table_name, column_name, "object" | "array") where
#   "object" -> JSON must be a dict   (wrapped by MutableDict)
#   "array"  -> JSON must be a list   (wrapped by MutableList)
#
# Seeded from `plan/compatjsonb_mutable_swap_plan.md` §B and reconciled
# against the model files (DB column names differ from Python attrs in two
# places: courses/generated_assets expose `metadata`, not `metadata_`).
#
# IMPORTANT: this list must be reconciled with the architect's definitive
# JSON-column inventory before a green run here is trusted as the gate.
# A green result only proves the columns LISTED HERE are shape-clean; a
# column the swap touches but that is missing from this list is NOT
# covered. Treat additions to the swap's scope as requiring an edit here.
# ---------------------------------------------------------------------------
AUDIT_TARGETS: list[tuple[str, str, str]] = [
    # --- object (dict) columns ---
    ("assignments", "metadata_json", "object"),
    ("courses", "metadata", "object"),
    ("agent_kv", "value_json", "object"),
    ("generated_assets", "content", "object"),
    ("generated_assets", "metadata", "object"),
    ("practice_problems", "problem_metadata", "object"),
    ("agent_tasks", "input_json", "object"),
    ("agent_tasks", "result_json", "object"),
    ("agent_tasks", "checkpoint_json", "object"),
    ("study_goals", "metadata_json", "object"),
    ("study_plans", "tasks", "object"),
    # --- array (list) columns ---
    ("agent_tasks", "step_results_json", "array"),
    ("drills", "hints", "array"),
    ("drills", "skill_tags", "array"),
    ("integration_credentials", "scopes", "array"),
    ("auth_sessions", "login_actions", "array"),
]

# Default in-container path to the live SQLite DB.
DEFAULT_DB_PATH = "/app/data/opentutor.db"

# Exit codes (CI-gate semantics).
EXIT_OK = 0  # zero violations across all existing targets
EXIT_VIOLATION = 1  # at least one shape violation found
EXIT_USAGE = 2  # usage / IO / connection error


class TargetResult:
    """Tally of value shapes observed in one (table, column) target."""

    def __init__(self, table: str, column: str, expected: str) -> None:
        """Initialise an all-zero tally for ``table.column``."""
        self.table = table
        self.column = column
        self.expected = expected
        self.skipped = False
        self.nulls = 0
        self.objects = 0
        self.arrays = 0
        self.scalars = 0  # valid JSON that is neither object nor array
        self.invalid = 0  # not parseable as JSON at all
        self.violations = 0

    @property
    def label(self) -> str:
        """Return the ``table.column`` identifier for display."""
        return f"{self.table}.{self.column}"


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    """Return True if ``table`` is a real table in the SQLite schema."""
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1",
        (table,),
    ).fetchone()
    return row is not None


def _column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    """Return True if ``column`` exists on ``table`` (via PRAGMA)."""
    # PRAGMA table_info row layout: (cid, name, type, notnull, dflt, pk).
    rows = conn.execute(f"PRAGMA table_info('{table}')").fetchall()
    return any(r[1] == column for r in rows)


def _has_json1(conn: sqlite3.Connection) -> bool:
    """Return True if this SQLite build exposes the JSON1 functions."""
    try:
        conn.execute("SELECT json_valid('null'), json_type('null')")
        return True
    except sqlite3.OperationalError:
        return False


def _classify_python(raw: object) -> str:
    """Classify one raw cell value using Python json.

    Returns one of: ``"null"``, ``"object"``, ``"array"``,
    ``"scalar"`` (valid JSON but not a container), ``"invalid"``.
    """
    if raw is None:
        return "null"
    if not isinstance(raw, (str, bytes, bytearray)):
        # Non-text storage class in a JSON column — treat as a scalar
        # that the Mutable* wrappers would reject.
        return "scalar"
    try:
        parsed = json.loads(raw)
    except (ValueError, TypeError):
        return "invalid"
    if parsed is None:
        # JSON `null` -> Python None; Mutable* .coerce(None) is safe.
        return "null"
    if isinstance(parsed, dict):
        return "object"
    if isinstance(parsed, list):
        return "array"
    return "scalar"


def _audit_target_json1(
    conn: sqlite3.Connection, result: TargetResult
) -> None:
    """Tally shapes for one target using SQLite JSON1 functions."""
    quoted = f'"{result.column}"'
    sql = (
        f"SELECT {quoted} AS v, "
        f"CASE WHEN {quoted} IS NULL THEN 1 ELSE 0 END AS is_null, "
        f"json_valid({quoted}) AS is_valid, "
        f"CASE WHEN json_valid({quoted}) "
        f"THEN json_type({quoted}) ELSE NULL END AS jtype "
        f'FROM "{result.table}"'
    )
    for _v, is_null, is_valid, jtype in conn.execute(sql):
        if is_null:
            result.nulls += 1
            continue
        if not is_valid:
            result.invalid += 1
            result.violations += 1
            continue
        if jtype == "null":
            # JSON `null` deserialises to Python None; Mutable{Dict,List}
            # .coerce(None) returns None without raising — safe like SQL
            # NULL. Verified empirically against SQLAlchemy 2.0.x.
            result.nulls += 1
            continue
        if jtype == "object":
            result.objects += 1
        elif jtype == "array":
            result.arrays += 1
        else:
            result.scalars += 1
        actual = jtype if jtype in ("object", "array") else "scalar"
        if actual != result.expected:
            result.violations += 1


def _audit_target_python(
    conn: sqlite3.Connection, result: TargetResult
) -> None:
    """Tally shapes for one target by parsing each cell in Python.

    Fallback path for SQLite builds without the JSON1 extension.
    """
    quoted = f'"{result.column}"'
    sql = f'SELECT {quoted} FROM "{result.table}"'
    for (raw,) in conn.execute(sql):
        kind = _classify_python(raw)
        if kind == "null":
            result.nulls += 1
            continue
        if kind == "object":
            result.objects += 1
        elif kind == "array":
            result.arrays += 1
        elif kind == "scalar":
            result.scalars += 1
        else:  # invalid
            result.invalid += 1
            result.violations += 1
            continue
        if kind != result.expected:
            result.violations += 1


def audit_database(db_path: str) -> tuple[list[TargetResult], int]:
    """Audit every AUDIT_TARGETS entry in the read-only SQLite DB.

    Returns the per-target results and the total violation count. Raises
    no exceptions for missing tables/columns (those are SKIPped); only an
    unopenable DB propagates as ``sqlite3.Error``.
    """
    results: list[TargetResult] = []
    total_violations = 0
    # Strictly read-only connection — fails loudly if the file is absent
    # rather than creating an empty DB.
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        json1 = _has_json1(conn)
        for table, column, expected in AUDIT_TARGETS:
            res = TargetResult(table, column, expected)
            if not _table_exists(conn, table) or not _column_exists(
                conn, table, column
            ):
                res.skipped = True
                results.append(res)
                continue
            if json1:
                _audit_target_json1(conn, res)
            else:
                _audit_target_python(conn, res)
            total_violations += res.violations
            results.append(res)
    finally:
        conn.close()
    return results, total_violations


def _print_report(
    results: list[TargetResult], db_path: str, json1: bool
) -> None:
    """Print the per-target table and a one-line summary."""
    engine = "json1" if json1 else "python-fallback"
    print(f"# JSON column shape audit — db={db_path} engine={engine}")
    header = (
        f"{'table.column':<40} {'expected':<8} {'nulls':>6} "
        f"{'objects':>8} {'arrays':>7} {'scalars':>8} {'invalid':>8} "
        f"{'VIOLATIONS':>11}"
    )
    print(header)
    print("-" * len(header))
    skipped = 0
    audited = 0
    for r in results:
        if r.skipped:
            skipped += 1
            print(
                f"{r.label:<40} {r.expected:<8} "
                f"{'SKIP (table/column absent)':>60}"
            )
            continue
        audited += 1
        print(
            f"{r.label:<40} {r.expected:<8} {r.nulls:>6} "
            f"{r.objects:>8} {r.arrays:>7} {r.scalars:>8} "
            f"{r.invalid:>8} {r.violations:>11}"
        )
    total_violations = sum(r.violations for r in results if not r.skipped)
    print("-" * len(header))
    print(
        f"# SUMMARY: {audited} audited, {skipped} skipped, "
        f"{total_violations} total violations"
    )
    if total_violations == 0:
        print("# RESULT: GREEN — all audited columns match expected shapes.")
    else:
        print(
            "# RESULT: RED — shape violations present; the MutableDict/"
            "MutableList swap is NOT safe until these rows are fixed."
        )


def _parse_args(argv: list[str]) -> argparse.Namespace:
    """Parse CLI arguments (only ``--db``)."""
    parser = argparse.ArgumentParser(
        prog="audit_json_column_shapes.py",
        description=(
            "READ-ONLY audit of JSON column shapes ahead of the "
            "schema-wide Mutable* swap. Exit 0 = clean, 1 = violations, "
            "2 = usage/IO error."
        ),
    )
    parser.add_argument(
        "--db",
        default=DEFAULT_DB_PATH,
        help=f"Path to the SQLite DB (default: {DEFAULT_DB_PATH})",
    )
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    """Entry point — returns the process exit code (0 / 1 / 2)."""
    args = _parse_args(argv)
    try:
        results, total_violations = audit_database(args.db)
    except sqlite3.Error as exc:
        print(
            f"ERROR: cannot open SQLite DB read-only at "
            f"'{args.db}': {exc}",
            file=sys.stderr,
        )
        return EXIT_USAGE
    except OSError as exc:
        print(f"ERROR: IO error for '{args.db}': {exc}", file=sys.stderr)
        return EXIT_USAGE

    # Re-derive engine label for the report header without reopening for
    # writes (read-only reconnect is cheap and side-effect free).
    json1 = False
    try:
        probe = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
        try:
            json1 = _has_json1(probe)
        finally:
            probe.close()
    except sqlite3.Error:
        json1 = False

    _print_report(results, args.db, json1)
    return EXIT_OK if total_violations == 0 else EXIT_VIOLATION


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
