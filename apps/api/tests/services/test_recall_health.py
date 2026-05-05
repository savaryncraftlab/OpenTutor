"""Service tests for ``services.recall_health`` — Slice 5 T1.

Covers:
1. Empty case: 0 LearningProgress rows → ``total_tracked=0``,
   ``average_retrievability=0.0`` (div-by-zero guard, Юрій's case).
2. All-fresh: rows reviewed seconds ago → retrievability ≈ 1.0,
   ``well_known_count == total_tracked``.
3. Some-overdue: mix of fresh and stale rows → at_risk + well_known
   counts split correctly.
4. fsrs_reps == 0 rows skipped (matches `predict_forgetting` filter).
5. Scope honesty: response always includes ``scope: "flashcards"``.

Mirrors the harness from ``test_xp_service.py`` (in-memory SQLite +
StaticPool + ``Base.metadata.create_all``).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from database import Base
from models.course import Course
from models.progress import LearningProgress  # noqa: F401  — register table
from models.user import User
from services.recall_health import compute_recall_health


@pytest_asyncio.fixture
async def session_factory():
    """Fresh in-memory SQLite per test (StaticPool keeps it alive)."""
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
async def user_and_course(session_factory):
    """Seed one user + one course, return ``(user_id, course_id)``."""
    uid = uuid.uuid4()
    cid = uuid.uuid4()
    async with session_factory() as db:
        db.add(User(id=uid, name="Recall Tester"))
        db.add(Course(id=cid, user_id=uid, name="Demo Course"))
        await db.commit()
    return uid, cid


def _row(
    user_id: uuid.UUID,
    course_id: uuid.UUID,
    *,
    fsrs_reps: int,
    fsrs_stability: float,
    last_studied_at: datetime | None,
) -> LearningProgress:
    """Helper for terse seed data in tests."""
    return LearningProgress(
        user_id=user_id,
        course_id=course_id,
        fsrs_reps=fsrs_reps,
        fsrs_stability=fsrs_stability,
        last_studied_at=last_studied_at,
    )


# ── 1. Empty case (Юрій's case) ──────────────────────────────────────


@pytest.mark.asyncio
async def test_empty_no_rows(session_factory, user_and_course):
    """0 LearningProgress rows → all zeros + scope=flashcards."""
    uid, _ = user_and_course
    async with session_factory() as db:
        result = await compute_recall_health(db, uid)

    assert result == {
        "total_tracked": 0,
        "average_retrievability": 0.0,
        "at_risk_count": 0,
        "well_known_count": 0,
        "scope": "flashcards",
    }


# ── 2. All fresh — high retrievability ───────────────────────────────


@pytest.mark.asyncio
async def test_all_fresh_high_retrievability(session_factory, user_and_course):
    """Rows reviewed seconds ago with healthy stability → all well-known."""
    uid, cid = user_and_course
    now = datetime.now(timezone.utc)
    async with session_factory() as db:
        for _ in range(3):
            db.add(
                _row(uid, cid, fsrs_reps=2, fsrs_stability=10.0, last_studied_at=now)
            )
        await db.commit()

        result = await compute_recall_health(db, uid)

    assert result["total_tracked"] == 3
    assert result["scope"] == "flashcards"
    # Just-reviewed at full stability → r ≈ 1.0; well above 0.85 threshold.
    assert result["average_retrievability"] >= 0.99
    assert result["well_known_count"] == 3
    assert result["at_risk_count"] == 0


# ── 3. Mixed — some overdue, some fresh ──────────────────────────────


@pytest.mark.asyncio
async def test_mixed_overdue_and_fresh(session_factory, user_and_course):
    """Mix of fresh + stale → at-risk and well-known counts split correctly."""
    uid, cid = user_and_course
    now = datetime.now(timezone.utc)
    async with session_factory() as db:
        # Two fresh, healthy rows.
        db.add(_row(uid, cid, fsrs_reps=3, fsrs_stability=20.0, last_studied_at=now))
        db.add(_row(uid, cid, fsrs_reps=3, fsrs_stability=20.0, last_studied_at=now))
        # Two heavily-overdue rows: elapsed >> stability ⇒ r drops
        # well below 0.5. Stability=2 days, elapsed=60 days ⇒
        # r = (1 + 60/(9*2))^-1 ≈ 0.231.
        long_ago = now - timedelta(days=60)
        for _ in range(2):
            db.add(
                _row(
                    uid,
                    cid,
                    fsrs_reps=2,
                    fsrs_stability=2.0,
                    last_studied_at=long_ago,
                )
            )
        await db.commit()

        result = await compute_recall_health(db, uid)

    assert result["total_tracked"] == 4
    assert result["well_known_count"] == 2
    assert result["at_risk_count"] == 2
    # Average is ~ (1.0 + 1.0 + 0.23 + 0.23) / 4 ≈ 0.62.
    assert 0.5 <= result["average_retrievability"] <= 0.75


# ── 4. fsrs_reps == 0 rows are skipped ───────────────────────────────


@pytest.mark.asyncio
async def test_zero_reps_rows_skipped(session_factory, user_and_course):
    """Rows with ``fsrs_reps == 0`` (never reviewed) must NOT be counted."""
    uid, cid = user_and_course
    now = datetime.now(timezone.utc)
    async with session_factory() as db:
        # 1 reviewed row + 5 unreviewed rows (the unreviewed ones must
        # not show up in `total_tracked`).
        db.add(_row(uid, cid, fsrs_reps=1, fsrs_stability=5.0, last_studied_at=now))
        for _ in range(5):
            db.add(
                _row(
                    uid,
                    cid,
                    fsrs_reps=0,
                    fsrs_stability=0.0,
                    last_studied_at=None,
                )
            )
        await db.commit()

        result = await compute_recall_health(db, uid)

    assert result["total_tracked"] == 1
    assert result["well_known_count"] == 1


# ── 5. last_studied_at NULL or stability <= 0 are skipped ────────────


@pytest.mark.asyncio
async def test_null_last_studied_skipped(session_factory, user_and_course):
    """``fsrs_reps > 0`` but ``last_studied_at`` NULL → skipped (matches
    forecast service behavior)."""
    uid, cid = user_and_course
    async with session_factory() as db:
        db.add(_row(uid, cid, fsrs_reps=3, fsrs_stability=5.0, last_studied_at=None))
        db.add(
            _row(
                uid,
                cid,
                fsrs_reps=3,
                fsrs_stability=0.0,
                last_studied_at=datetime.now(timezone.utc),
            )
        )
        await db.commit()

        result = await compute_recall_health(db, uid)

    # Both rows skipped → empty-state response.
    assert result["total_tracked"] == 0
    assert result["average_retrievability"] == 0.0
    assert result["scope"] == "flashcards"
