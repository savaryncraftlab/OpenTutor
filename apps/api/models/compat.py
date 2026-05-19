"""SQLite-only model type aliases.

`Compat*` names are kept for backwards compatibility with existing model code.
"""

import json as _json
import uuid as _uuid

from sqlalchemy import JSON, String, Text
from sqlalchemy.ext.mutable import MutableDict, MutableList
from sqlalchemy.types import TypeDecorator


class CompatUUID(TypeDecorator):
    """Store UUIDs as 36-char strings in SQLite."""

    impl = String(36)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is not None:
            return str(value)
        return value

    def process_result_value(self, value, dialect):
        if value is not None:
            return _uuid.UUID(value)
        return value


# ── Mutation-tracking JSON (BUG-FSRS-001 schema-wide fix) ─────────────
#
# Plain SQLAlchemy ``JSON`` does NOT flag in-place container mutation:
# ``obj.col["k"] = v`` / ``obj.col.append(x)`` leave SA's attribute
# history empty, so ``flush()`` emits no UPDATE and the write is
# silently dropped. ``Mutable*.as_mutable`` wraps the loaded value so
# top-level in-place mutation marks the parent row dirty.
#
# Two public aliases, both over plain ``JSON``:
#   * ``CompatJSONB``      — object-valued columns (dict / NULL).
#   * ``CompatJSONBList``  — array-valued columns (list / NULL).
#
# Pick the alias that matches the column's RUNTIME root container, NOT
# its Python annotation (several annotations in the model layer are
# wrong — see the inventory + ALIAS DECISION RULE in
# plan/compatjsonb_pr2_spec.md).
#
# CAVEAT — TOP LEVEL ONLY. ``MutableDict``/``MutableList`` track only
# the OUTERMOST container. Nested mutation is NOT tracked:
#     row.col["a"]["b"] = 1        # NOT detected
#     row.col[0]["k"] = 1          # NOT detected
#     row.col.append({"x": 1})     # detected (top-level list op)
#     row.col["a"] = {"b": 1}      # detected (top-level dict op)
# For nested writes, either reassign the whole attribute
# (``row.col = {**row.col, ...}`` — a ``set``, always tracked) or call
# ``sqlalchemy.orm.attributes.flag_modified(row, "col")`` at that site.
#
# A whole-attribute REASSIGN (``row.col = newdict``) is a normal ``set``
# and is tracked even by plain ``JSON`` — Mutable* only adds the
# *in-place* path.
CompatJSONB = MutableDict.as_mutable(JSON)
CompatJSONBList = MutableList.as_mutable(JSON)

CompatTSVECTOR = Text


class _VectorType(TypeDecorator):
    """Store float vectors as JSON text in SQLite, auto-serialize/deserialize."""

    impl = Text
    cache_ok = True

    def __init__(self, dim: int = 1536):
        super().__init__()
        self.dim = dim

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if isinstance(value, str):
            return value
        return _json.dumps(value)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        if isinstance(value, list):
            return value
        return _json.loads(value)


class _TextVectorFactory:
    """Keep CompatVector(1536) call-shape while returning proper TypeDecorator."""

    def __call__(self, dim: int = 1536):
        return _VectorType(dim)


CompatVector = _TextVectorFactory()
