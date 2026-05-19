"""PR-2 proof: ``CompatJSONB`` / ``CompatJSONBList`` track top-level mutation.

Contract under test: for the JSON columns now bound to ``CompatJSONB``
(the collapsed MutableDict alias), a TOP-LEVEL in-place subscript write
(``obj.col["newkey"] = value``) followed by ``commit()`` must persist —
re-reading the row in a fresh session shows the new key. The list
analogue (``CompatJSONBList`` = ``MutableList.as_mutable(JSON)``) is
proven by the ``append`` case (8b).

This is the BUG-FSRS-001 mechanism (``models/compat.py``): plain
SQLAlchemy ``JSON`` does not flag in-place mutation, so the UPDATE is
silently skipped. ``MutableDict.as_mutable(JSON)`` /
``MutableList.as_mutable(JSON)`` fix it for the TOP LEVEL ONLY —
*nested* writes (``obj.col["a"]["b"] = v``) are still NOT auto-tracked
by design; that limitation is locked by the negative case (8c).

Columns covered:
- ``GeneratedAsset.content``     — the FSRS-001 site (top-level dict)
- ``AgentKV.value_json``         — highest-frequency JSON write path
- ``Assignment.metadata_json``   — deadline-extractor latent write
- ``PracticeProblem.knowledge_points`` — list column (8b positive)
- ``GeneratedAsset.content``     — nested-write negative (8c lock)

Harness mirrors ``tests/routers/test_flashcards.py`` /
``tests/models/test_xp_event_model.py`` — fresh in-memory SQLite per
test with ``StaticPool`` so the multiple connections in one test share
the same DB.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from database import Base
from models.agent_kv import AgentKV
from models.course import Course
from models.generated_asset import GeneratedAsset
from models.ingestion import Assignment
from models.practice import PracticeProblem
from models.user import User


# ── Fixtures ─────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def session_factory():
    """Fresh in-memory SQLite per test (``StaticPool`` keeps it alive)."""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        yield factory
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def seeded(session_factory):
    """Seed the FK parents (``User`` + ``Course``) the three target rows
    depend on. Returns ``(user_id, course_id)``."""
    user_id = uuid.uuid4()
    course_id = uuid.uuid4()
    async with session_factory() as s:
        s.add(User(id=user_id, name="Owner"))
        s.add(Course(id=course_id, name="Python", description="t", user_id=user_id))
        await s.commit()
    return user_id, course_id


# ── Tests — one top-level mutation per swapped column ─────────────────


@pytest.mark.asyncio
async def test_generated_asset_content_tracks_top_level_mutation(
    session_factory, seeded
) -> None:
    """``GeneratedAsset.content`` — the FSRS-001 site."""
    user_id, course_id = seeded
    asset_id = uuid.uuid4()

    async with session_factory() as s:
        s.add(
            GeneratedAsset(
                id=asset_id,
                user_id=user_id,
                course_id=course_id,
                asset_type="flashcards",
                title="Batch",
                content={"cards": []},
                batch_id=uuid.uuid4(),
                version=1,
                is_archived=False,
            )
        )
        await s.commit()

    # Top-level in-place subscript write — the operation plain JSON drops.
    async with session_factory() as s:
        asset = (
            await s.execute(
                sa.select(GeneratedAsset).where(GeneratedAsset.id == asset_id)
            )
        ).scalar_one()
        asset.content["reviewed"] = True
        await s.commit()

    async with session_factory() as s:
        reloaded = (
            await s.execute(
                sa.select(GeneratedAsset).where(GeneratedAsset.id == asset_id)
            )
        ).scalar_one()
        assert reloaded.content.get("reviewed") is True, (
            "top-level mutation on GeneratedAsset.content did not persist "
            "— CompatJSONB not mutation-tracking?"
        )


@pytest.mark.asyncio
async def test_agent_kv_value_json_tracks_top_level_mutation(
    session_factory, seeded
) -> None:
    """``AgentKV.value_json`` — highest-frequency JSON write path."""
    user_id, course_id = seeded
    kv_id = uuid.uuid4()

    async with session_factory() as s:
        s.add(
            AgentKV(
                id=kv_id,
                user_id=user_id,
                course_id=course_id,
                namespace="tutor_notes",
                key="k1",
                value_json={"a": 1},
                version=1,
            )
        )
        await s.commit()

    async with session_factory() as s:
        kv = (
            await s.execute(sa.select(AgentKV).where(AgentKV.id == kv_id))
        ).scalar_one()
        kv.value_json["b"] = 2
        await s.commit()

    async with session_factory() as s:
        reloaded = (
            await s.execute(sa.select(AgentKV).where(AgentKV.id == kv_id))
        ).scalar_one()
        assert reloaded.value_json.get("b") == 2, (
            "top-level mutation on AgentKV.value_json did not persist "
            "— CompatJSONB not mutation-tracking?"
        )


@pytest.mark.asyncio
async def test_assignment_metadata_json_tracks_top_level_mutation(
    session_factory, seeded
) -> None:
    """``Assignment.metadata_json`` — deadline-extractor latent write."""
    _user_id, course_id = seeded
    assignment_id = uuid.uuid4()

    async with session_factory() as s:
        s.add(
            Assignment(
                id=assignment_id,
                course_id=course_id,
                title="HW 1",
                status="active",
                metadata_json={"source": "manual"},
            )
        )
        await s.commit()

    async with session_factory() as s:
        assignment = (
            await s.execute(sa.select(Assignment).where(Assignment.id == assignment_id))
        ).scalar_one()
        assignment.metadata_json["extraction_confidence"] = 0.91
        await s.commit()

    async with session_factory() as s:
        reloaded = (
            await s.execute(sa.select(Assignment).where(Assignment.id == assignment_id))
        ).scalar_one()
        assert reloaded.metadata_json.get("extraction_confidence") == 0.91, (
            "top-level mutation on Assignment.metadata_json did not persist "
            "— CompatJSONB not mutation-tracking?"
        )


# ── 8b — CompatJSONBList positive case (top-level list mutation) ──────


@pytest.mark.asyncio
async def test_practice_problem_knowledge_points_tracks_top_level_list_mutation(
    session_factory, seeded
) -> None:
    """``PracticeProblem.knowledge_points`` (``CompatJSONBList``) — a
    top-level list op (``.append``) must persist.

    Column choice: ``PracticeProblem.knowledge_points``
    (``models/practice.py:85``, ``Mapped[Optional[list]]``,
    ``CompatJSONBList``) is picked over ``Drill.hints`` because its FK
    graph is lighter — it only needs the ``Course`` the shared
    ``seeded`` fixture already creates (one FK), whereas ``Drill``
    would require a 3-row ``DrillCourse`` → ``DrillModule`` → ``Drill``
    chain. This is the list analogue of the 3 dict proofs: it asserts
    ``MutableList.as_mutable(JSON)`` fires the UPDATE on a TOP-LEVEL
    list mutation.
    """
    _user_id, course_id = seeded
    problem_id = uuid.uuid4()

    async with session_factory() as s:
        s.add(
            PracticeProblem(
                id=problem_id,
                course_id=course_id,
                question_type="short_answer",
                question="What is a closure?",
                knowledge_points=["a"],
            )
        )
        await s.commit()

    # Top-level list op — the operation plain JSON drops.
    async with session_factory() as s:
        problem = (
            await s.execute(
                sa.select(PracticeProblem).where(PracticeProblem.id == problem_id)
            )
        ).scalar_one()
        problem.knowledge_points.append("b")
        await s.commit()

    async with session_factory() as s:
        reloaded = (
            await s.execute(
                sa.select(PracticeProblem).where(PracticeProblem.id == problem_id)
            )
        ).scalar_one()
        kp = reloaded.knowledge_points
        assert "b" in kp and len(kp) == 2, (
            "top-level append on PracticeProblem.knowledge_points did not "
            "persist — CompatJSONBList / MutableList not applied?"
        )


# ── 8c — nested-mutation NEGATIVE case (regression lock for R9) ───────


@pytest.mark.asyncio
async def test_nested_dict_mutation_is_NOT_autopersisted(
    session_factory, seeded
) -> None:
    """``GeneratedAsset.content`` — a PURELY NESTED in-place write with
    NO reassign and NO ``flag_modified`` must NOT auto-persist.

    This asserts a LIMITATION, not a bug. ``MutableDict.as_mutable(JSON)``
    tracks the OUTERMOST container only — a write that mutates an inner
    object (``content["cards"][0]["fsrs"]["reps"] = 99``) without
    touching a top-level key and without an explicit ``flag_modified``
    leaves SA's attribute history empty, so no UPDATE is emitted.

    This is the structural counterpart to Step 6 in
    ``routers/flashcards.py``: that handler does exactly this kind of
    nested write and therefore *must* call ``flag_modified(asset,
    "content")``. If this test ever starts FAILING (i.e. the nested
    write DID persist) someone introduced unintended deep-tracking —
    investigate; it would also mean the ``flag_modified`` in
    ``routers/flashcards.py`` is no longer load-bearing, which must be
    a deliberate, reviewed change. (BUG-FSRS-001 regression lock.)
    """
    user_id, course_id = seeded
    asset_id = uuid.uuid4()

    async with session_factory() as s:
        s.add(
            GeneratedAsset(
                id=asset_id,
                user_id=user_id,
                course_id=course_id,
                asset_type="flashcards",
                title="Batch",
                content={"cards": [{"fsrs": {"reps": 0}}]},
                batch_id=uuid.uuid4(),
                version=1,
                is_archived=False,
            )
        )
        await s.commit()

    # Purely NESTED in-place write — NO reassign, NO flag_modified.
    # MutableDict does not see this (top-level-only) so it must NOT
    # persist. (Do NOT add a reassign or flag_modified here — that
    # would defeat the regression lock.)
    async with session_factory() as s:
        asset = (
            await s.execute(
                sa.select(GeneratedAsset).where(GeneratedAsset.id == asset_id)
            )
        ).scalar_one()
        asset.content["cards"][0]["fsrs"]["reps"] = 99
        await s.commit()

    async with session_factory() as s:
        reloaded = (
            await s.execute(
                sa.select(GeneratedAsset).where(GeneratedAsset.id == asset_id)
            )
        ).scalar_one()
        assert reloaded.content["cards"][0]["fsrs"]["reps"] == 0, (
            "nested mutation must NOT auto-persist — MutableDict is "
            "top-level-only by design (see routers/flashcards.py flag_modified)"
        )
