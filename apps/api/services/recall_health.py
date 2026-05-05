"""Recall health aggregate metric — Slice 5 T1.

Computes a single user-level aggregate of FSRS retrievability across
**flashcard reviews** (rows in ``learning_progress`` with ``fsrs_reps > 0``).

Scope honesty:
    FSRS state lives ONLY on ``LearningProgress`` (course flashcards).
    ``PracticeProblem`` / ``PracticeResult`` (path-room missions) carry
    ``difficulty_layer`` but no FSRS columns. So this metric is a
    flashcard-only metric — the response includes a ``scope: "flashcards"``
    literal so the API itself surfaces the limitation; the dashboard card
    repeats the same caveat in its subline.

Out of scope (deferred): adding FSRS columns to ``PracticeProblem`` /
``PracticeResult`` (separate Phase work — see `plan/slice_5_progress_model_plan.md`
§T1 risks).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from libs.datetime_utils import as_utc
from models.progress import LearningProgress
from services.spaced_repetition.fsrs import _retrievability


# Thresholds chosen to match the existing FSRS-derived semantics elsewhere
# in the codebase: 0.85+ is "well known" (above the default 90% retention
# target with a small safety band), <0.5 is "at risk" (substantial chance
# the user will fail recall on next attempt).
_AT_RISK_THRESHOLD = 0.5
_WELL_KNOWN_THRESHOLD = 0.85


async def compute_recall_health(
    db: AsyncSession,
    user_id: uuid.UUID,
) -> dict:
    """Aggregate FSRS retrievability across the user's flashcard reviews.

    Returns:
        dict matching the ``GET /api/progress/recall-health`` shape:
            - total_tracked: count of ``LearningProgress`` rows with
              ``fsrs_reps > 0`` (across all courses).
            - average_retrievability: mean of FSRS retrievability for those
              rows. ``0.0`` when ``total_tracked == 0`` (div-by-zero guard).
            - at_risk_count: rows with retrievability < 0.5.
            - well_known_count: rows with retrievability >= 0.85.
            - scope: literal ``"flashcards"`` — surfaces in JSON so the
              frontend / curl smoke / API consumers all know this metric
              does NOT cover path-room missions.

    Юрій's case (0 active flashcard reviews): all counts return 0,
    ``average_retrievability`` is 0.0 (NOT NaN — explicit div-by-zero
    guard). Card renders empty state.
    """
    # Match `forgetting_forecast.predict_forgetting` filter at line 76 —
    # only count rows the user has actually reviewed at least once.
    result = await db.execute(
        select(LearningProgress).where(
            LearningProgress.user_id == user_id,
            LearningProgress.fsrs_reps > 0,
        )
    )
    rows = list(result.scalars().all())

    if not rows:
        return {
            "total_tracked": 0,
            "average_retrievability": 0.0,
            "at_risk_count": 0,
            "well_known_count": 0,
            "scope": "flashcards",
        }

    now = datetime.now(timezone.utc)
    retrievabilities: list[float] = []
    at_risk = 0
    well_known = 0

    for row in rows:
        # Without a last_studied_at we can't compute elapsed time — skip
        # rather than guess. (Mirrors `predict_forgetting` line 89.)
        if row.last_studied_at is None or row.fsrs_stability <= 0:
            continue
        elapsed_days = max(
            (now - as_utc(row.last_studied_at)).total_seconds() / 86400.0,
            0.0,
        )
        r = _retrievability(elapsed_days, row.fsrs_stability)
        retrievabilities.append(r)
        if r < _AT_RISK_THRESHOLD:
            at_risk += 1
        elif r >= _WELL_KNOWN_THRESHOLD:
            well_known += 1

    if not retrievabilities:
        # Edge case: had `fsrs_reps > 0` rows but every one was missing
        # `last_studied_at` / had non-positive stability. Treat as 0.
        return {
            "total_tracked": 0,
            "average_retrievability": 0.0,
            "at_risk_count": 0,
            "well_known_count": 0,
            "scope": "flashcards",
        }

    avg_r = sum(retrievabilities) / len(retrievabilities)

    return {
        "total_tracked": len(retrievabilities),
        "average_retrievability": round(avg_r, 4),
        "at_risk_count": at_risk,
        "well_known_count": well_known,
        "scope": "flashcards",
    }
