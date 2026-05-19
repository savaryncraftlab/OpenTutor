"""PR-1 proof: ``CompatJSONBMutable`` tracks top-level in-place mutation.

Contract under test: for the three columns swapped to
``CompatJSONBMutable`` in PR-1, a TOP-LEVEL in-place subscript write
(``obj.col["newkey"] = value``) followed by ``commit()`` must persist —
re-reading the row in a fresh session shows the new key.

This is the BUG-FSRS-001 mechanism (``models/compat.py``): plain
SQLAlchemy ``JSON`` does not flag in-place dict mutation, so the UPDATE
is silently skipped. ``MutableDict.as_mutable(JSON)`` fixes it for
top-level keys.

Columns covered (one case each):
- ``GeneratedAsset.content``     — the FSRS-001 site
- ``AgentKV.value_json``         — highest-frequency JSON write path
- ``Assignment.metadata_json``   — deadline-extractor latent write

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
            "— CompatJSONBMutable not applied?"
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
            "— CompatJSONBMutable not applied?"
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
            await s.execute(
                sa.select(Assignment).where(Assignment.id == assignment_id)
            )
        ).scalar_one()
        assignment.metadata_json["extraction_confidence"] = 0.91
        await s.commit()

    async with session_factory() as s:
        reloaded = (
            await s.execute(
                sa.select(Assignment).where(Assignment.id == assignment_id)
            )
        ).scalar_one()
        assert reloaded.metadata_json.get("extraction_confidence") == 0.91, (
            "top-level mutation on Assignment.metadata_json did not persist "
            "— CompatJSONBMutable not applied?"
        )
