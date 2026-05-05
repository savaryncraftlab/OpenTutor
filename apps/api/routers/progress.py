"""Progress tracking — core progress endpoints (CRUD, overview)."""

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models.course import Course
from models.ingestion import StudySession, WrongAnswer
from models.practice import PracticeProblem
from models.progress import LearningProgress
from models.user import User
from services.auth.dependency import get_current_user
from services.recall_forecast import compute_recall_forecast

from routers.progress_analytics import router as analytics_router
from routers.progress_knowledge import router as knowledge_router

router = APIRouter()

# Include sub-routers so all endpoints remain under /api/progress
router.include_router(analytics_router)
router.include_router(knowledge_router)


# ── Progress Endpoints ──


@router.get(
    "/courses/{course_id}",
    summary="Get course progress",
    description="Return learning progress overview for a specific course.",
)
async def get_course_progress(
    course_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get learning progress overview for a course."""
    from services.progress.analytics import (
        get_course_progress as get_course_progress_summary,
    )

    return await get_course_progress_summary(db, user.id, course_id)


@router.get(
    "/recall-health",
    summary="Get aggregate recall health",
    description=(
        "Return user-level FSRS aggregate across **flashcard** reviews. "
        "Scope is flashcards-only — path-room missions do NOT carry FSRS "
        "state today (see Slice 5 T1 plan for rationale). The `scope` "
        "field in the response surfaces this honestly."
    ),
)
async def get_recall_health(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Aggregate FSRS retrievability across flashcard reviews."""
    from services.recall_health import compute_recall_health

    return await compute_recall_health(db, user.id)


@router.get(
    "/overview",
    summary="Get learning overview",
    description="Return aggregate cross-course learning analytics for the current user.",
)
async def get_learning_overview(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Aggregate cross-course learning analytics for the current user."""
    course_result = await db.execute(
        select(Course)
        .where(Course.user_id == user.id)
        .order_by(Course.created_at.desc())
    )
    courses = course_result.scalars().all()
    course_ids = [course.id for course in courses]
    if not course_ids:
        return {
            "total_courses": 0,
            "total_study_minutes": 0,
            "average_mastery": 0.0,
            "gap_type_breakdown": {},
            "diagnosis_breakdown": {},
            "error_category_breakdown": {},
            "course_summaries": [],
        }

    progress_result = await db.execute(
        select(LearningProgress).where(
            LearningProgress.user_id == user.id,
            LearningProgress.course_id.in_(course_ids),
        )
    )
    progress_rows = progress_result.scalars().all()

    wrong_result = await db.execute(
        select(WrongAnswer, PracticeProblem)
        .join(PracticeProblem, WrongAnswer.problem_id == PracticeProblem.id)
        .where(
            WrongAnswer.user_id == user.id,
            WrongAnswer.course_id.in_(course_ids),
        )
    )
    wrong_rows = wrong_result.all()

    session_result = await db.execute(
        select(StudySession).where(
            StudySession.user_id == user.id,
            StudySession.course_id.in_(course_ids),
        )
    )
    sessions = session_result.scalars().all()

    gap_type_breakdown: dict[str, int] = {}
    diagnosis_breakdown: dict[str, int] = {}
    error_category_breakdown: dict[str, int] = {}
    progress_by_course: dict[uuid.UUID, list[LearningProgress]] = {
        course_id: [] for course_id in course_ids
    }
    wrong_by_course: dict[uuid.UUID, list[WrongAnswer]] = {
        course_id: [] for course_id in course_ids
    }
    session_by_course: dict[uuid.UUID, list[StudySession]] = {
        course_id: [] for course_id in course_ids
    }

    for progress in progress_rows:
        progress_by_course.setdefault(progress.course_id, []).append(progress)
        if progress.gap_type:
            gap_type_breakdown[progress.gap_type] = (
                gap_type_breakdown.get(progress.gap_type, 0) + 1
            )

    for wrong_answer, _problem in wrong_rows:
        wrong_by_course.setdefault(wrong_answer.course_id, []).append(wrong_answer)
        if wrong_answer.diagnosis:
            diagnosis_breakdown[wrong_answer.diagnosis] = (
                diagnosis_breakdown.get(wrong_answer.diagnosis, 0) + 1
            )
        if wrong_answer.error_category:
            error_category_breakdown[wrong_answer.error_category] = (
                error_category_breakdown.get(wrong_answer.error_category, 0) + 1
            )

    for session in sessions:
        session_by_course.setdefault(session.course_id, []).append(session)

    course_summaries = []
    all_mastery_scores = [row.mastery_score for row in progress_rows]
    total_study_minutes = sum(session.duration_minutes or 0 for session in sessions)

    for course in courses:
        course_progress = progress_by_course.get(course.id, [])
        course_wrong = wrong_by_course.get(course.id, [])
        course_sessions = session_by_course.get(course.id, [])
        avg_mastery = (
            sum(item.mastery_score for item in course_progress) / len(course_progress)
            if course_progress
            else 0.0
        )
        course_summaries.append(
            {
                "course_id": str(course.id),
                "course_name": course.name,
                "average_mastery": avg_mastery,
                "study_minutes": sum(
                    item.duration_minutes or 0 for item in course_sessions
                ),
                "wrong_answers": len(course_wrong),
                "diagnosed_count": sum(1 for item in course_wrong if item.diagnosis),
                "gap_types": {
                    gap: sum(1 for item in course_progress if item.gap_type == gap)
                    for gap in {
                        item.gap_type for item in course_progress if item.gap_type
                    }
                },
            }
        )

    return {
        "total_courses": len(courses),
        "total_study_minutes": total_study_minutes,
        "average_mastery": (
            sum(all_mastery_scores) / len(all_mastery_scores)
            if all_mastery_scores
            else 0.0
        ),
        "gap_type_breakdown": gap_type_breakdown,
        "diagnosis_breakdown": diagnosis_breakdown,
        "error_category_breakdown": error_category_breakdown,
        "course_summaries": course_summaries,
    }


# ── Recall Forecast (Slice 5 T4) ──


@router.get(
    "/recall-forecast",
    summary="Get recall forecast",
    description=(
        "User-aggregate FSRS forecast: how many flashcard reviews come back "
        "today / this week / next week + session urgency. Scope is "
        "flashcards only — path-room missions carry no FSRS state."
    ),
)
async def get_recall_forecast(
    days: int = Query(
        default=7,
        ge=1,
        le=30,
        description="Horizon in days for the 'this week' bucket.",
    ),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Aggregate FSRS due-buckets + session urgency for the current user."""
    forecast = await compute_recall_forecast(db, user.id, horizon_days=days)
    return {
        "today_due": forecast.today_due,
        "this_week_due": forecast.this_week_due,
        "next_week_due": forecast.next_week_due,
        "expected_forgotten": forecast.expected_forgotten,
        "urgency": forecast.urgency,
        "recommendation": forecast.recommendation,
        "scope": forecast.scope,
    }
