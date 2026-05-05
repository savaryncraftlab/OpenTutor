"""Tests for ``services.recall_forecast`` (Slice 5 T4).

Covers the four exit cases from the brief:

1. ``test_no_cards_returns_zeros`` — empty user.
2. ``test_all_due_today_buckets_correctly`` — every card lands in
   ``today_due``.
3. ``test_all_far_future_keeps_buckets_empty`` — far-future due dates
   fall outside the 14-day window.
4. ``test_mixed_buckets`` — exercise today + this-week + next-week + past
   horizon split, plus the urgency wiring.

Plus a fifth case asserting the helper skips ``fsrs_reps == 0`` rows
(invariant for predict_forgetting parity).
"""

from __future__ import annotations

import os
import tempfile
import uuid
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from database import Base
from models.course import Course
from models.progress import LearningProgress
from models.user import User
from services.recall_forecast import compute_recall_forecast


_NOW = datetime(2026, 5, 1, 12, 0, 0, tzinfo=timezone.utc)


@pytest_asyncio.fixture
async def db_session() -> AsyncSession:
    """Per-test SQLite AsyncSession — same harness shape as test_freeze."""
    fd, db_path = tempfile.mkstemp(prefix="opentutor-recall-", suffix=".db")
    os.close(fd)

    engine = create_async_engine(
        f"sqlite+aiosqlite:///{db_path}",
        echo=False,
        connect_args={"check_same_thread": False},
        pool_pre_ping=False,
        poolclass=NullPool,
    )
    session_factory = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        yield session

    await engine.dispose()
    try:
        os.unlink(db_path)
    except OSError:
        pass


async def _seed_user_and_course(db: AsyncSession) -> tuple[User, Course]:
    user = User(name="Recall Tester")
    db.add(user)
    await db.flush()
    course = Course(name="Recall Course", description="x", user_id=user.id)
    db.add(course)
    await db.commit()
    await db.refresh(user)
    await db.refresh(course)
    return user, course


def _make_progress(
    *,
    user_id: uuid.UUID,
    course_id: uuid.UUID,
    next_review_at: datetime | None,
    fsrs_stability: float = 5.0,
    fsrs_reps: int = 1,
    last_studied_at: datetime | None = None,
) -> LearningProgress:
    return LearningProgress(
        user_id=user_id,
        course_id=course_id,
        content_node_id=None,
        status="reviewed",
        mastery_score=0.5,
        next_review_at=next_review_at,
        fsrs_difficulty=5.0,
        fsrs_stability=fsrs_stability,
        fsrs_reps=fsrs_reps,
        fsrs_lapses=0,
        fsrs_state="review",
        last_studied_at=last_studied_at or (_NOW - timedelta(days=1)),
    )


# ── 1. No cards ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_no_cards_returns_zeros(db_session: AsyncSession) -> None:
    """Empty user → all buckets 0, urgency 'none', scope flashcards."""
    user, _course = await _seed_user_and_course(db_session)

    forecast = await compute_recall_forecast(db_session, user.id, now=_NOW)

    assert forecast.today_due == 0
    assert forecast.this_week_due == 0
    assert forecast.next_week_due == 0
    assert forecast.expected_forgotten == 0.0
    assert forecast.urgency == "none"
    assert forecast.scope == "flashcards"


# ── 2. All due today ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_all_due_today_buckets_correctly(db_session: AsyncSession) -> None:
    """Three cards due within +24h all land in today_due.

    Urgency wiring is exercised on overdue cards specifically — see
    ``test_overdue_cards_drive_urgency`` below — because
    ``estimate_session_urgency`` only counts ``due <= now``. Here we
    only assert the bucket math.
    """
    user, course = await _seed_user_and_course(db_session)

    for offset_h in (-2, 1, 23):
        db_session.add(
            _make_progress(
                user_id=user.id,
                course_id=course.id,
                next_review_at=_NOW + timedelta(hours=offset_h),
            )
        )
    await db_session.commit()

    forecast = await compute_recall_forecast(db_session, user.id, now=_NOW)

    assert forecast.today_due == 3
    assert forecast.this_week_due == 0
    assert forecast.next_week_due == 0
    # Recommendation copy must always be a non-empty string.
    assert forecast.recommendation


# ── 2b. Overdue cards drive urgency ────────────────────────────────


@pytest.mark.asyncio
async def test_overdue_cards_drive_urgency(db_session: AsyncSession) -> None:
    """Five cards overdue by 5 days each → urgency escalates above 'none'.

    With stability=5.0 + elapsed=5d past due, retrievability drops well
    below 1.0; expected-forgotten sums >= ~2.0 → 'high'/'critical' band.
    """
    user, course = await _seed_user_and_course(db_session)
    overdue_at = _NOW - timedelta(days=5)
    last_studied = _NOW - timedelta(days=10)
    for _ in range(5):
        db_session.add(
            _make_progress(
                user_id=user.id,
                course_id=course.id,
                next_review_at=overdue_at,
                last_studied_at=last_studied,
                fsrs_stability=5.0,
            )
        )
    await db_session.commit()

    forecast = await compute_recall_forecast(db_session, user.id, now=_NOW)

    assert forecast.today_due == 5
    assert forecast.urgency != "none"
    assert forecast.expected_forgotten > 0.0


# ── 3. All far-future ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_all_far_future_keeps_buckets_empty(db_session: AsyncSession) -> None:
    """Cards due > 14d out land in NO bucket (window ends at 2*horizon)."""
    user, course = await _seed_user_and_course(db_session)

    for offset_d in (20, 30, 60):
        db_session.add(
            _make_progress(
                user_id=user.id,
                course_id=course.id,
                next_review_at=_NOW + timedelta(days=offset_d),
            )
        )
    await db_session.commit()

    forecast = await compute_recall_forecast(db_session, user.id, now=_NOW)

    assert forecast.today_due == 0
    assert forecast.this_week_due == 0
    assert forecast.next_week_due == 0
    # No overdue → forgetting cost is 0 → urgency 'none'.
    assert forecast.urgency == "none"


# ── 4. Mixed buckets ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_mixed_buckets(db_session: AsyncSession) -> None:
    """One card per bucket + one beyond 14d → exact 1/1/1, last excluded."""
    user, course = await _seed_user_and_course(db_session)

    db_session.add(
        _make_progress(
            user_id=user.id,
            course_id=course.id,
            next_review_at=_NOW + timedelta(hours=6),  # today
        )
    )
    db_session.add(
        _make_progress(
            user_id=user.id,
            course_id=course.id,
            next_review_at=_NOW + timedelta(days=3),  # this week
        )
    )
    db_session.add(
        _make_progress(
            user_id=user.id,
            course_id=course.id,
            next_review_at=_NOW + timedelta(days=10),  # next week
        )
    )
    db_session.add(
        _make_progress(
            user_id=user.id,
            course_id=course.id,
            next_review_at=_NOW + timedelta(days=21),  # outside window
        )
    )
    await db_session.commit()

    forecast = await compute_recall_forecast(db_session, user.id, now=_NOW)

    assert forecast.today_due == 1
    assert forecast.this_week_due == 1
    assert forecast.next_week_due == 1
    # Recommendation comes from estimate_session_urgency — must be a
    # non-empty string regardless of which urgency band we land in.
    assert isinstance(forecast.recommendation, str) and forecast.recommendation


# ── 5. fsrs_reps == 0 rows are skipped ─────────────────────────────


@pytest.mark.asyncio
async def test_skips_unreviewed_rows(db_session: AsyncSession) -> None:
    """A LearningProgress row with fsrs_reps == 0 must NOT count, even if
    next_review_at is set (matches predict_forgetting filter)."""
    user, course = await _seed_user_and_course(db_session)

    db_session.add(
        _make_progress(
            user_id=user.id,
            course_id=course.id,
            next_review_at=_NOW + timedelta(hours=1),
            fsrs_reps=0,  # never reviewed
        )
    )
    await db_session.commit()

    forecast = await compute_recall_forecast(db_session, user.id, now=_NOW)

    assert forecast.today_due == 0
    assert forecast.this_week_due == 0
    assert forecast.next_week_due == 0
