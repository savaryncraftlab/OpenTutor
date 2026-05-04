"""Phase C extended T4 — FSRS double-write regression test.

Architect plan (`plan/phase_c_lesson_practice_recall_design.md` §5) flagged a
risk: when ``submit_answer`` reads ``progress.interval_days`` after
``_apply_fsrs_review`` mutates the ``LearningProgress`` row, two failure
modes are theoretically possible:

1. **Double-write** — the router accidentally re-triggers
   ``_apply_fsrs_review`` (e.g. via a re-query that fires a SQLAlchemy event
   handler), so the wire value reflects N+1 reps but the DB persists N+2.
2. **Stale read / drift** — the router reads BEFORE
   ``_apply_fsrs_review`` runs OR re-queries the row from the DB after a
   commit that hasn't yet happened, so the wire value disagrees with the
   row that lands.

This test pins both invariants:

* ``interval_days`` strictly grows across two consecutive correct submits
  (FSRS stability expansion, e.g. ~2.4d → ~7d on default params).
* The wire ``response.interval_days`` matches the persisted DB column
  byte-for-byte after each submit.
* A wrong submit drops the card into ``relearning`` with
  ``interval_days == 1`` (FSRS-5 lapse contract).

Same in-memory SQLite + StaticPool harness as ``test_quiz_submission.py``.

Important: the autouse ``_stub_collaborators`` fixture in
``test_quiz_submission.py`` stubs ``update_quiz_result`` to a no-op AsyncMock
to keep the XP-tier tests fast — that stub would defeat THIS test's purpose
(we ARE testing the real tracker path). To avoid colliding with that
fixture, this file lives in its own module so its own autouse fixture
stubs the OTHER best-effort collaborators (analytics, classifier) and
crucially leaves ``update_quiz_result`` un-patched.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
import sqlalchemy as sa
from fastapi import BackgroundTasks
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from database import Base
from models.course import Course
from models.practice import PracticeProblem, PracticeResult  # noqa: F401
from models.progress import LearningProgress
from models.user import User
from models.user_badge import UserBadge  # noqa: F401 — register table
from models.xp_event import XpEvent  # noqa: F401 — register table
from schemas.quiz import SubmitAnswerRequest


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
    """Seed one user + one course + one fill-blank problem.

    Returns ``(user, course_id, problem_id)``. The problem grades via the
    default exact-match branch so a matching ``user_answer`` is correct
    without any LLM/Pyodide stubs.
    """
    user_id = uuid.uuid4()
    course_id = uuid.uuid4()
    problem_id = uuid.uuid4()
    async with session_factory() as s:
        s.add(User(id=user_id, name="Owner"))
        s.add(Course(id=course_id, name="Python", description="t", user_id=user_id))
        s.add(
            PracticeProblem(
                id=problem_id,
                course_id=course_id,
                question_type="fill_blank",
                question="2 + 2 = ?",
                correct_answer="4",
                difficulty_layer=2,
                order_index=0,
            )
        )
        await s.commit()
    async with session_factory() as s:
        user = (await s.execute(sa.select(User).where(User.id == user_id))).scalar_one()
    return user, course_id, problem_id


@pytest.fixture(autouse=True)
def _stub_non_fsrs_collaborators(monkeypatch: pytest.MonkeyPatch) -> None:
    """Quiet down everything OTHER THAN the FSRS path under test.

    Crucially this does NOT stub ``update_quiz_result`` — that's the
    function we're verifying. Analytics, classifier, mastery snapshots
    are all best-effort and unrelated to the wire-vs-DB contract.
    """
    import services.analytics.events as events_mod

    monkeypatch.setattr(events_mod, "emit_quiz_answered", AsyncMock(return_value=None))

    import services.diagnosis.classifier as classifier_mod

    monkeypatch.setattr(
        classifier_mod,
        "classify_error",
        AsyncMock(return_value={"category": "conceptual"}),
    )


# ── Helpers ──────────────────────────────────────────────────────────


async def _call_submit(
    *,
    db,
    user: User,
    problem_id: uuid.UUID,
    user_answer: str,
    answer_time_ms: int = 1234,
) -> Any:
    """Drive ``submit_answer`` against a real ``AsyncSession``."""
    from routers.quiz_submission import submit_answer

    body = SubmitAnswerRequest(
        problem_id=problem_id,
        user_answer=user_answer,
        answer_time_ms=answer_time_ms,
    )
    return await submit_answer(
        body=body, background_tasks=BackgroundTasks(), user=user, db=db
    )


async def _fetch_progress(
    session_factory, user_id: uuid.UUID, course_id: uuid.UUID
) -> LearningProgress:
    """Re-query the LearningProgress row from the DB after a commit.

    This is the read-after-write probe — if ``progress.interval_days`` on
    the wire diverges from this fetched value, we have the bug.
    """
    async with session_factory() as s:
        return (
            (
                await s.execute(
                    sa.select(LearningProgress).where(
                        LearningProgress.user_id == user_id,
                        LearningProgress.course_id == course_id,
                    )
                )
            )
            .scalars()
            .one()
        )


# ── Tests ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_first_correct_submit_persists_interval_matching_wire(
    session_factory, seeded
) -> None:
    """First correct submit: wire response carries ``interval_days``
    derived from FSRS initial stability (rating=3 → w[2]=2.4 →
    ``round(2.4) = 2``), and the persisted DB row carries the SAME
    integer.

    This pins the read-after-write contract: the router reads from the
    in-memory ``LearningProgress`` instance returned by the tracker
    (NOT a re-query post-commit), so the wire and DB values cannot drift.
    """
    user, course_id, problem_id = seeded

    async with session_factory() as db:
        response = await _call_submit(
            db=db, user=user, problem_id=problem_id, user_answer="4"
        )

    assert response.is_correct is True
    assert response.interval_days is not None
    assert response.interval_days >= 1, (
        f"first FSRS rep should have interval >= 1, got {response.interval_days}"
    )
    assert response.next_review_at is not None
    # next_review_at must be in the future (cards are due tomorrow at
    # earliest after a successful first review).
    assert response.next_review_at > datetime.now(timezone.utc)

    # Re-query the persisted row and assert wire == DB.
    persisted = await _fetch_progress(session_factory, user.id, course_id)
    assert persisted.interval_days == response.interval_days, (
        "wire interval_days must equal persisted DB value "
        f"(wire={response.interval_days}, db={persisted.interval_days})"
    )
    assert persisted.fsrs_reps == 1, (
        f"after first submit fsrs_reps must be 1, got {persisted.fsrs_reps}"
    )
    # Persisted next_review_at must match the wire value within microsecond
    # precision (SQLAlchemy preserves the datetime as-stored).
    assert persisted.next_review_at == response.next_review_at, (
        f"wire next_review_at must equal persisted "
        f"(wire={response.next_review_at}, db={persisted.next_review_at})"
    )


@pytest.mark.asyncio
async def test_consecutive_correct_submits_grow_interval(
    session_factory, seeded, monkeypatch
) -> None:
    """Two consecutive correct submits → second ``interval_days`` is
    strictly greater than the first.

    FSRS-5 same-day reviews would normally clamp stability via
    ``_same_day_stability`` (DEFAULT_W has w17=w18=w19=0 so this
    short-circuits to ``return s``), so we have to spoof the clock to
    simulate a real-world gap (>= 1 day) for the second submit. The
    cleanest way is to monkeypatch ``services.progress.tracker._utcnow``
    — that's the timestamp the tracker hands to ``_apply_fsrs_review``
    and onward into ``review_card``.

    Wire-vs-DB invariant is asserted on EACH submit (no drift on either
    rep), proving the in-memory mutation by ``_apply_fsrs_review`` does
    not get clobbered or re-applied between read and commit.
    """
    user, course_id, problem_id = seeded

    # First submit at T=now.
    async with session_factory() as db:
        first = await _call_submit(
            db=db, user=user, problem_id=problem_id, user_answer="4"
        )
    assert first.is_correct is True
    assert first.interval_days is not None
    persisted_after_first = await _fetch_progress(session_factory, user.id, course_id)
    assert persisted_after_first.interval_days == first.interval_days
    assert persisted_after_first.fsrs_reps == 1

    # Spoof the clock 7 days forward so the second review is NOT a
    # same-day review (FSRS-5 same-day branch would otherwise clamp the
    # stability and the interval wouldn't grow under default params).
    fake_now = datetime.now(timezone.utc) + timedelta(days=7)

    def _spoof_now():
        return fake_now

    import services.progress.tracker as tracker_mod

    monkeypatch.setattr(tracker_mod, "_utcnow", _spoof_now)

    # Second submit at T=now+7d.
    async with session_factory() as db:
        second = await _call_submit(
            db=db, user=user, problem_id=problem_id, user_answer="4"
        )
    assert second.is_correct is True
    assert second.interval_days is not None

    # FSRS expansion — second interval STRICTLY exceeds the first, and
    # next_review_at also moves forward.
    assert second.interval_days > first.interval_days, (
        f"expected FSRS to grow interval after second correct submit; "
        f"first={first.interval_days}, second={second.interval_days}"
    )
    assert second.next_review_at > first.next_review_at, (
        "next_review_at must also advance with stability growth"
    )

    # The smoking-gun assertion: wire value equals persisted DB value
    # after the second commit.  If the router re-queried post-commit
    # AND the re-query somehow re-fired ``_apply_fsrs_review``, fsrs_reps
    # would be 3 not 2; if the router read BEFORE the commit and the
    # commit silently rolled back, the persisted interval would be
    # something else.  Both failures are caught here.
    persisted_after_second = await _fetch_progress(session_factory, user.id, course_id)
    assert persisted_after_second.interval_days == second.interval_days, (
        "wire interval_days must equal persisted DB value after second submit "
        f"(wire={second.interval_days}, db={persisted_after_second.interval_days})"
    )
    assert persisted_after_second.fsrs_reps == 2, (
        f"after second correct submit fsrs_reps must be 2, "
        f"got {persisted_after_second.fsrs_reps} (smoking gun for double-write)"
    )
    assert persisted_after_second.next_review_at == second.next_review_at


@pytest.mark.asyncio
async def test_wrong_submit_relearning_resets_interval_to_one(
    session_factory, seeded, monkeypatch
) -> None:
    """A wrong submit after a successful rep drops the card into
    ``relearning`` with ``interval_days = 1`` (FSRS contract: rating=1
    schedules a re-test tomorrow regardless of prior stability).

    Pins the wire-vs-DB contract on the lapse path too — the chip's
    "Returns in 1d" message must reflect the row that was actually
    written.
    """
    user, course_id, problem_id = seeded

    # First submit correct.
    async with session_factory() as db:
        first = await _call_submit(
            db=db, user=user, problem_id=problem_id, user_answer="4"
        )
    assert first.is_correct is True

    # Spoof the clock 3 days forward so the wrong-answer review elapses
    # past the same-day window (so FSRS hits the proper lapse path).
    fake_now = datetime.now(timezone.utc) + timedelta(days=3)

    def _spoof_now():
        return fake_now

    import services.progress.tracker as tracker_mod

    monkeypatch.setattr(tracker_mod, "_utcnow", _spoof_now)

    # Second submit wrong → lapse → relearning state, interval=1.
    async with session_factory() as db:
        second = await _call_submit(
            db=db, user=user, problem_id=problem_id, user_answer="42"
        )
    assert second.is_correct is False
    assert second.interval_days == 1, (
        f"FSRS lapse must set interval to 1, got {second.interval_days}"
    )
    # next_review_at ≈ fake_now + 1 day — we don't pin the exact value
    # but it must be in the future and within the next 2 days.
    assert second.next_review_at is not None
    assert second.next_review_at > fake_now
    assert second.next_review_at < fake_now + timedelta(days=2)

    # Wire-vs-DB invariant on the lapse row.
    persisted = await _fetch_progress(session_factory, user.id, course_id)
    assert persisted.interval_days == 1
    assert persisted.fsrs_lapses == 1, (
        f"lapse counter must increment to 1, got {persisted.fsrs_lapses}"
    )
    assert persisted.fsrs_state == "relearning", (
        f"state must transition to relearning, got {persisted.fsrs_state}"
    )
    assert persisted.next_review_at == second.next_review_at
