"""Slice 5 T3 — dedicated tests for ``compute_streak_calendar``.

These tests cover the five scenarios called out in the slice plan:

1. Empty user (no events, no freezes) → all ``broken`` past + ``grace`` today.
2. 7-day streak (MAINTAINED ×7) → every tile is ``maintained``.
3. Mid-streak freeze (MAINTAINED, FREEZE, MAINTAINED, ...) → the freeze
   tile is classified as ``freeze`` even though the surrounding days have
   real events.
4. Today-only-active (1 GRACE-equivalent ``maintained`` today + N
   ``broken`` before) — verifies a single fresh event today does not
   bleed into the past tiles.
5. Cross-week boundary — anchor the window so it spans two ISO weeks
   (Mon..Sun bucket boundary) and confirm tile classification is
   independent of which week the day belongs to.

The harness mirrors ``test_streak_service.py`` (same SQLite fixture +
seed helpers) so the calendar tests use the same XP/freeze date
classification path the streak walker uses. We co-locate the helpers
here rather than importing from the sibling test module to keep this
file self-contained.
"""

from __future__ import annotations

import os
import tempfile
import uuid
from collections.abc import AsyncIterator
from datetime import datetime, time, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from database import Base
from models.freeze_token import FreezeToken
from models.user import User
from models.xp_event import XpEvent  # registers xp_events table on Base.metadata
from services import streak_service


# Wednesday 2026-04-22 — well inside an ISO week so streak walks don't
# accidentally span week boundaries unless a test asks for it (case 5).
_ANCHOR_WED = datetime(2026, 4, 22, 12, 0, 0, tzinfo=timezone.utc).date()


# ── Fixtures ────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def db_session() -> AsyncIterator[AsyncSession]:
    """Per-test SQLite session with the same relaxed-constraint posture
    as ``test_streak_service.py`` (Phase 16c T5 migration not yet
    landed). The calendar helper itself is read-only, but we keep the
    relaxed schema for parity in case future tests seed streak-saver
    freezes (problem_id NULL).
    """

    fd, db_path = tempfile.mkstemp(prefix="opentutor-streak-cal-", suffix=".db")
    os.close(fd)

    engine = create_async_engine(
        f"sqlite+aiosqlite:///{db_path}",
        echo=False,
        connect_args={"check_same_thread": False},
        pool_pre_ping=False,
        poolclass=NullPool,
    )
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # Mirror test_streak_service.py — relax NOT NULL on
        # freeze_tokens.problem_id so streak-saver tokens (NULL
        # problem_id) can land if a test wants them.
        await conn.execute(text("PRAGMA writable_schema = 1"))
        await conn.execute(
            text(
                "UPDATE sqlite_master SET sql = replace(sql, 'NOT NULL', '') "
                "WHERE name = 'freeze_tokens'"
            )
        )
        await conn.execute(text("PRAGMA writable_schema = 0"))

    async with factory() as session:
        yield session

    await engine.dispose()
    try:
        os.unlink(db_path)
    except OSError:
        pass


@pytest_asyncio.fixture
async def seeded_user(db_session: AsyncSession) -> uuid.UUID:
    """Create one ``User`` row and return its id."""

    user = User(name="Calendar Tester")
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user.id


# ── Helpers ─────────────────────────────────────────────────────────


def _utc_at(d, hour: int = 9) -> datetime:
    """Return tz-aware UTC datetime at ``hour`` on date ``d``."""

    return datetime.combine(d, time(hour=hour), tzinfo=timezone.utc)


async def _add_event(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    day,
    amount: int = 5,
) -> None:
    """Insert one ``XpEvent`` row anchored at 09:00 UTC on ``day``."""

    db.add(
        XpEvent(
            user_id=user_id,
            amount=amount,
            source="test_seed",
            source_id=uuid.uuid4(),
            earned_at=_utc_at(day),
        )
    )
    await db.commit()


async def _add_freeze(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    day,
) -> None:
    """Insert one card-style freeze covering exactly ``day``."""

    start = datetime.combine(day, time.min, tzinfo=timezone.utc)
    db.add(
        FreezeToken(
            user_id=user_id,
            problem_id=uuid.uuid4(),  # card freeze keeps a problem_id
            frozen_at=start,
            expires_at=start + timedelta(hours=24),
        )
    )
    await db.commit()


# ── Case 1 — empty user → broken + grace ────────────────────────────


@pytest.mark.asyncio
async def test_empty_user_all_broken_with_today_grace(db_session, seeded_user) -> None:
    """No events, no freezes → past tiles ``broken``, today ``grace``.

    Slice 5 T3 case 1. A new account must surface "you didn't show up"
    on past days but keep today open ("still time today").
    """

    result = await streak_service.compute_streak_calendar(
        db_session, user_id=seeded_user, days=10, today_utc=_ANCHOR_WED
    )

    assert len(result.days) == 10
    assert result.current_streak == 0
    # Today is the rightmost tile and reads grace.
    assert result.days[-1].date == _ANCHOR_WED
    assert result.days[-1].status == "grace"
    # Every preceding day is broken.
    assert [t.status for t in result.days[:-1]] == ["broken"] * 9


# ── Case 2 — 7-day MAINTAINED streak ────────────────────────────────


@pytest.mark.asyncio
async def test_seven_day_maintained_streak(db_session, seeded_user) -> None:
    """Events on every day in a 7-day window → every tile ``maintained``.

    Slice 5 T3 case 2. The walker counts today (with a real event) +
    six prior days = 7 maintained, so the calendar tile labels and the
    aggregate streak number must agree.
    """

    for offset in range(7):
        await _add_event(
            db_session,
            user_id=seeded_user,
            day=_ANCHOR_WED - timedelta(days=offset),
        )

    result = await streak_service.compute_streak_calendar(
        db_session, user_id=seeded_user, days=7, today_utc=_ANCHOR_WED
    )

    assert len(result.days) == 7
    assert result.current_streak == 7
    assert all(tile.status == "maintained" for tile in result.days)


# ── Case 3 — mid-streak freeze ──────────────────────────────────────


@pytest.mark.asyncio
async def test_mid_streak_freeze_classified_as_freeze(db_session, seeded_user) -> None:
    """Freeze on day-2 between two events reads as ``freeze`` (not maintained).

    Slice 5 T3 case 3. Pattern: today=event, day-1=event, day-2=freeze
    (no event), day-3=event. The freeze-covered day must classify as
    ``freeze`` rather than fall through to ``maintained``, because the
    UI renders a different glyph for "saved by freeze".
    """

    today = _ANCHOR_WED
    day_1 = today - timedelta(days=1)
    day_2 = today - timedelta(days=2)
    day_3 = today - timedelta(days=3)

    await _add_event(db_session, user_id=seeded_user, day=today)
    await _add_event(db_session, user_id=seeded_user, day=day_1)
    await _add_freeze(db_session, user_id=seeded_user, day=day_2)
    await _add_event(db_session, user_id=seeded_user, day=day_3)

    result = await streak_service.compute_streak_calendar(
        db_session, user_id=seeded_user, days=4, today_utc=today
    )

    by_date = {tile.date: tile.status for tile in result.days}
    assert by_date[today] == "maintained"
    assert by_date[day_1] == "maintained"
    assert by_date[day_2] == "freeze"
    assert by_date[day_3] == "maintained"
    # Walker treats freeze-covered days as maintaining; full 4-day run.
    assert result.current_streak == 4


# ── Case 4 — today-only-active ──────────────────────────────────────


@pytest.mark.asyncio
async def test_today_only_active(db_session, seeded_user) -> None:
    """One event today + N quiet past days → today ``maintained``, past ``broken``.

    Slice 5 T3 case 4. The user just earned XP for the first time. The
    calendar must show today as ``maintained`` (not ``grace`` — a real
    event takes precedence) and every prior tile as ``broken`` so the
    user can see "this is day one".
    """

    await _add_event(db_session, user_id=seeded_user, day=_ANCHOR_WED)

    result = await streak_service.compute_streak_calendar(
        db_session, user_id=seeded_user, days=5, today_utc=_ANCHOR_WED
    )

    assert len(result.days) == 5
    # Today is the rightmost tile; classified as maintained, not grace.
    assert result.days[-1].date == _ANCHOR_WED
    assert result.days[-1].status == "maintained"
    # Every preceding day is broken.
    assert [t.status for t in result.days[:-1]] == ["broken"] * 4
    assert result.current_streak == 1


# ── Case 5 — cross-week boundary ────────────────────────────────────


@pytest.mark.asyncio
async def test_cross_week_boundary_anchor(db_session, seeded_user) -> None:
    """Window straddling Mon..Sun classifies tiles independent of week.

    Slice 5 T3 case 5. Anchor today on Monday so a 14-day window walks
    back into the previous ISO week. We seed events on the Friday and
    the Monday of the previous week (week boundary days), and verify
    the calendar renders them as ``maintained`` regardless of bucket.

    2026-04-20 is a Monday. ``today=2026-04-20`` with ``days=14`` covers
    [2026-04-07 .. 2026-04-20]. Events at:
      * 2026-04-13 (Mon, week-15 start) — classified maintained
      * 2026-04-17 (Fri, week-15)       — classified maintained
      * 2026-04-20 (Mon, week-16 start, "today") — classified maintained
    Everything else is broken.
    """

    today_mon = datetime(2026, 4, 20, 12, 0, 0, tzinfo=timezone.utc).date()
    week15_mon = datetime(2026, 4, 13, tzinfo=timezone.utc).date()
    week15_fri = datetime(2026, 4, 17, tzinfo=timezone.utc).date()

    await _add_event(db_session, user_id=seeded_user, day=week15_mon)
    await _add_event(db_session, user_id=seeded_user, day=week15_fri)
    await _add_event(db_session, user_id=seeded_user, day=today_mon)

    result = await streak_service.compute_streak_calendar(
        db_session, user_id=seeded_user, days=14, today_utc=today_mon
    )

    by_date = {tile.date: tile.status for tile in result.days}
    assert by_date[week15_mon] == "maintained"
    assert by_date[week15_fri] == "maintained"
    assert by_date[today_mon] == "maintained"

    # Tiles either side of the seeded events are broken — confirms the
    # walker doesn't smear a maintained day across the week bucket.
    assert by_date[today_mon - timedelta(days=1)] == "broken"  # Sunday
    assert by_date[week15_fri - timedelta(days=1)] == "broken"  # Thursday
    # Window extends 13 days into the past — earliest tile is broken.
    assert result.days[0].date == today_mon - timedelta(days=13)
    assert result.days[0].status == "broken"
