"""User-aggregate FSRS recall forecast (Slice 5 T4).

Surfaces the per-user "what's coming back today / this week / next week"
forecast from FSRS state on ``LearningProgress``. Path-room missions
carry NO FSRS state (per ``models/practice.py``), so this metric covers
flashcard reviews only — the ``scope`` field on the response makes that
explicit.

The bucket boundaries are exclusive on the upper edge:
- ``today_due``    : ``next_review_at <= now + 24h``
- ``this_week_due``: ``now + 24h < next_review_at <= now + 7d``
- ``next_week_due``: ``now + 7d  < next_review_at <= now + 14d``

``expected_forgotten`` and ``urgency`` come from the existing
``estimate_session_urgency`` primitive — we build a synthetic
``list[FSRSCard]`` from progress rows so we can reuse the exact same
math the proactive scheduler uses.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from libs.datetime_utils import as_utc
from models.progress import LearningProgress
from services.spaced_repetition.fsrs import FSRSCard, estimate_session_urgency


@dataclass(frozen=True)
class RecallForecast:
    """Aggregate forecast for one user, one horizon."""

    today_due: int
    this_week_due: int
    next_week_due: int
    expected_forgotten: float
    urgency: str  # none | low | normal | high | critical
    recommendation: str
    scope: str = "flashcards"


def _build_fsrs_cards(rows: list[LearningProgress]) -> list[FSRSCard]:
    """Project ``LearningProgress`` rows into the ``FSRSCard`` shape that
    ``estimate_session_urgency`` consumes.

    Slim helper (~10 lines) — duplicates what T1 (``recall-health``)
    will likely want. If T1 ships first with a shared helper, this can
    be replaced with one import; until then we own the construction.
    """
    cards: list[FSRSCard] = []
    for row in rows:
        if row.fsrs_reps <= 0 or row.fsrs_stability <= 0:
            # estimate_forgetting_cost already skips stability<=0, but
            # bailing here keeps ``total_cards`` honest.
            continue
        cards.append(
            FSRSCard(
                difficulty=row.fsrs_difficulty,
                stability=row.fsrs_stability,
                reps=row.fsrs_reps,
                lapses=row.fsrs_lapses,
                last_review=row.last_studied_at,
                due=row.next_review_at,
                state=row.fsrs_state,
            )
        )
    return cards


async def compute_recall_forecast(
    db: AsyncSession,
    user_id: uuid.UUID,
    horizon_days: int = 7,
    now: datetime | None = None,
) -> RecallForecast:
    """Aggregate FSRS due-buckets + urgency for one user.

    ``horizon_days`` is the size of the "this week" window (default 7).
    The "next week" bucket runs ``[horizon_days, 2*horizon_days]`` so a
    custom horizon scales both sides consistently.
    """
    current = as_utc(now or datetime.now(timezone.utc))

    result = await db.execute(
        select(LearningProgress).where(
            LearningProgress.user_id == user_id,
            LearningProgress.fsrs_reps > 0,
        )
    )
    rows = list(result.scalars().all())

    if not rows:
        return RecallForecast(
            today_due=0,
            this_week_due=0,
            next_week_due=0,
            expected_forgotten=0.0,
            urgency="none",
            recommendation="No review needed right now",
        )

    today_edge = current + timedelta(hours=24)
    this_week_edge = current + timedelta(days=horizon_days)
    next_week_edge = current + timedelta(days=2 * horizon_days)

    today_due = 0
    this_week_due = 0
    next_week_due = 0

    for row in rows:
        if row.next_review_at is None:
            continue
        due = as_utc(row.next_review_at)
        if due <= today_edge:
            today_due += 1
        elif due <= this_week_edge:
            this_week_due += 1
        elif due <= next_week_edge:
            next_week_due += 1

    cards = _build_fsrs_cards(rows)
    urgency_info = estimate_session_urgency(cards, current)

    return RecallForecast(
        today_due=today_due,
        this_week_due=this_week_due,
        next_week_due=next_week_due,
        expected_forgotten=float(urgency_info["forgetting_cost"]),
        urgency=str(urgency_info["urgency"]),
        recommendation=str(urgency_info["recommendation"]),
    )
