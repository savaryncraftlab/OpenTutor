"""Unit tests for True/False (``question_type='tf'``) grading in
``routers.quiz_submission.submit_answer``.

Regression-fence for Grader Bug #5 (2026-05-05):
The python-foundations seed stores TF canonical answers as English
"True" / "False" but Ukrainian learners type "правда" / "неправда" (and
the UI placeholder "true or false" gets ignored). The pre-fix grader
applied ``.strip().lower()`` to both sides — which kept English-to-English
matches working but never bridged the language gap, so valid Ukrainian
answers were marked wrong and triggered a lapse.

These tests pin the contract: TF answers are normalised to a canonical
bool via ``_normalize_tf_token`` before comparison, so any of
{True, true, T, Y, Yes, 1, Правда, правда, Так, т} on either side match
the same bool. Garbage falls through to strict string-compare and stays
rejected.

All tests stub the DB / collaborators (no Groq, no SQLite) — same fixture
pattern as ``test_drill_styles.py``.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from models.practice import PracticeProblem, PracticeResult
from routers.quiz_submission import _normalize_tf_token
from schemas.quiz import SubmitAnswerRequest


# ── direct unit tests for the normalizer ──────────────────────


@pytest.mark.parametrize(
    "raw,expected",
    [
        # English canonical + case variants
        ("True", True),
        ("true", True),
        ("TRUE", True),
        ("False", False),
        ("false", False),
        # English shorthand
        ("t", True),
        ("F", False),
        ("yes", True),
        ("No", False),
        ("y", True),
        ("n", False),
        ("1", True),
        ("0", False),
        # Ukrainian
        ("правда", True),
        ("Правда", True),
        ("ПРАВДА", True),
        ("неправда", False),
        ("Неправда", False),
        ("так", True),
        ("Так", True),
        ("ні", False),
        ("Ні", False),
        ("т", True),
        ("н", False),
        # Whitespace tolerance
        ("  правда  ", True),
        ("\tTrue\n", True),
        # Garbage → None (caller falls through to strict compare)
        ("asdf", None),
        ("maybe", None),
        ("", None),
        ("   ", None),
        (None, None),
    ],
)
def test_normalize_tf_token(raw: str | None, expected: bool | None) -> None:
    assert _normalize_tf_token(raw) is expected


# ── end-to-end submit_answer tests ────────────────────────────


def _user() -> SimpleNamespace:
    return SimpleNamespace(id=uuid.uuid4())


def _tf_problem(*, correct_answer: str) -> PracticeProblem:
    """Minimal TF PracticeProblem — only fields the submit branch reads."""
    return PracticeProblem(
        id=uuid.uuid4(),
        course_id=uuid.uuid4(),
        question_type="tf",
        question="The expression (50 - 5 * 6) / 4 evaluates to 5.0 in Python.",
        correct_answer=correct_answer,
        explanation="Reference explanation.",
        order_index=0,
        difficulty_layer=2,
    )


def _db_returning(problem: PracticeProblem) -> AsyncMock:
    result_proxy = MagicMock()
    result_proxy.scalar_one_or_none.return_value = problem

    db = AsyncMock()
    db.execute = AsyncMock(return_value=result_proxy)
    db.add = MagicMock()
    db.commit = AsyncMock()
    return db


@pytest.fixture(autouse=True)
def _patch_collaborators(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stub the post-grading collaborators (FSRS tracker / analytics /
    error classifier / XP / LOOM mastery) so the test exercises only the
    grading branch.

    NOTE: ``test_drill_styles.py`` (the sister test file) under-stubs and
    its tests crash on FSRS / XP attribute access in the current state of
    the repo. We over-stub here on purpose so the regression-fence for the
    Bug #5 fix is robust against further router-side bit-rot.
    """
    from services.progress import tracker as tracker_mod

    fake_progress = SimpleNamespace(
        fsrs_reps=0,
        mastery=0.0,
        last_correct=None,
        interval_days=None,
        next_review_at=None,
    )
    monkeypatch.setattr(
        tracker_mod, "get_or_create_progress", AsyncMock(return_value=fake_progress)
    )
    monkeypatch.setattr(
        tracker_mod, "update_quiz_result", AsyncMock(return_value=fake_progress)
    )

    import services.analytics.events as events_mod

    monkeypatch.setattr(events_mod, "emit_quiz_answered", AsyncMock(return_value=None))

    import services.diagnosis.classifier as classifier_mod

    monkeypatch.setattr(
        classifier_mod,
        "classify_error",
        AsyncMock(return_value={"category": "conceptual"}),
    )

    import services.xp_service as xp_mod

    monkeypatch.setattr(xp_mod, "award_card_xp", AsyncMock(return_value=None))

    import services.loom_mastery as loom_mod

    monkeypatch.setattr(
        loom_mod, "update_concept_mastery", AsyncMock(return_value=None)
    )


def _extract_practice_result(db: AsyncMock) -> PracticeResult | None:
    for call in db.add.call_args_list:
        obj = call.args[0]
        if isinstance(obj, PracticeResult):
            return obj
    return None


async def _call_submit(*, problem: PracticeProblem, user_answer: str) -> Any:
    from fastapi import BackgroundTasks

    from routers.quiz_submission import submit_answer

    db = _db_returning(problem)
    body = SubmitAnswerRequest(
        problem_id=problem.id,
        user_answer=user_answer,
        answer_time_ms=120,
    )
    bg = BackgroundTasks()
    response = await submit_answer(body=body, background_tasks=bg, user=_user(), db=db)
    return response, db


@pytest.mark.asyncio
async def test_tf_ukrainian_pravda_matches_english_true() -> None:
    """The exact bug from the report: canonical 'True', user types 'правда'."""
    problem = _tf_problem(correct_answer="True")
    response, db = await _call_submit(problem=problem, user_answer="правда")

    assert response.is_correct is True
    pr = _extract_practice_result(db)
    assert pr is not None
    assert pr.is_correct is True


@pytest.mark.asyncio
async def test_tf_ukrainian_nepravda_against_true_grades_wrong() -> None:
    """User typed Ukrainian 'неправда' against canonical 'True' → wrong."""
    problem = _tf_problem(correct_answer="True")
    response, _ = await _call_submit(problem=problem, user_answer="неправда")

    assert response.is_correct is False


@pytest.mark.asyncio
async def test_tf_english_capitalized_matches_lowercase_canonical() -> None:
    """Mixed case across sides — case-insensitive bool match."""
    problem = _tf_problem(correct_answer="false")
    response, _ = await _call_submit(problem=problem, user_answer="False")

    assert response.is_correct is True


@pytest.mark.asyncio
async def test_tf_ukrainian_tak_matches_english_true() -> None:
    """Common Ukrainian yes/no shorthand."""
    problem = _tf_problem(correct_answer="True")
    response, _ = await _call_submit(problem=problem, user_answer="так")

    assert response.is_correct is True


@pytest.mark.asyncio
async def test_tf_canonical_pravda_matches_english_true_input() -> None:
    """Symmetry: if a row ever stores canonical Ukrainian, English input still works."""
    problem = _tf_problem(correct_answer="Правда")
    response, _ = await _call_submit(problem=problem, user_answer="True")

    assert response.is_correct is True


@pytest.mark.asyncio
async def test_tf_garbage_answer_falls_through_and_grades_wrong() -> None:
    """Unrecognised tokens don't normalize → strict string compare → wrong."""
    problem = _tf_problem(correct_answer="True")
    response, _ = await _call_submit(problem=problem, user_answer="asdf")

    assert response.is_correct is False


@pytest.mark.asyncio
async def test_tf_garbage_equal_strings_still_match_via_fallback() -> None:
    """Belt-and-suspenders: if BOTH sides fail to normalize but the strings
    are identical (modulo case), strict compare keeps them matching. Defends
    against future seed rows that store something exotic in correct_answer."""
    problem = _tf_problem(correct_answer="MAYBE")
    response, _ = await _call_submit(problem=problem, user_answer="maybe")

    assert response.is_correct is True
