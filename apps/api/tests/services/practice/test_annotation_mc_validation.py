"""Unit tests for the multiple-choice distinctness guard in
``services.practice.annotation.validate_question_payload``.

Regression-fence for the MC-option-quality fix (2026-05-19):
Auto-generated MC practice problems could persist with duplicate option
VALUES (e.g. ``{A:"break", B:"continue", C:"break", D:"stop"}``) — the
extraction prompt never required distinct options and the validator never
rejected duplicates (1 bad row of 427 confirmed live).

These tests pin the new ``elif`` in the MC branch: 4 option values must be
distinct after ``strip().casefold()``. The check slots between the
"exactly 4 options" count check and the ``correct_answer`` membership
check, preserving the one-MC-structural-error-per-payload style.

``validate_question_payload`` is a pure function — no DB / LLM stubs
needed (unlike the router-level sister tests ``test_tf_grading.py`` /
``test_drill_styles.py``).
"""

from __future__ import annotations

from typing import Any

from services.practice.annotation import validate_question_payload

_DUP_ERROR = "options: multiple-choice option values must all be distinct"
_COUNT_ERROR = "options: multiple-choice questions require exactly 4 options"
_LABEL_ERROR = "correct_answer: must match one of the multiple-choice option labels"


def _mc_payload(**overrides: Any) -> dict[str, Any]:
    """Minimal MC payload that passes ``QuizQuestionContract`` and every
    non-MC branch check, so ``validate_question_payload`` exercises the MC
    branch cleanly. ``bloom_level="apply"`` is valid for ``difficulty_layer=2``.
    """
    payload: dict[str, Any] = {
        "question_type": "mc",
        "question": "Which Python keyword exits the nearest enclosing loop?",
        "options": {"A": "break", "B": "continue", "C": "pass", "D": "return"},
        "correct_answer": "A",
        "explanation": "`break` terminates the nearest enclosing loop immediately.",
        "difficulty_layer": 2,
        "problem_metadata": {
            "core_concept": "loop control flow",
            "bloom_level": "apply",
            "potential_traps": [],
            "layer_justification": "Standard application of loop control keywords.",
            "skill_focus": "control flow",
            "source_section": "Loops and iteration",
            "question_type": "mc",
        },
    }
    payload.update(overrides)
    return payload


def _validate(payload: dict[str, Any]):
    return validate_question_payload(payload, title="Python Foundations")


def test_distinct_options_pass() -> None:
    """Baseline valid MC with 4 distinct options → no errors, is_valid.

    Guards against the new rule false-positiving on good input.
    """
    validation = _validate(_mc_payload())

    assert validation.errors == []
    assert validation.is_valid


def test_duplicate_option_values_rejected() -> None:
    """The exact bug: options A and C both ``"break"`` → distinctness error."""
    validation = _validate(
        _mc_payload(options={"A": "break", "B": "continue", "C": "break", "D": "stop"})
    )

    assert _DUP_ERROR in validation.errors
    assert not validation.is_valid


def test_case_insensitive_duplicate_rejected() -> None:
    """``"Break"`` vs ``"break"`` count as a duplicate (pins the casefold
    decision — two options differing only in case are the same answer)."""
    validation = _validate(
        _mc_payload(options={"A": "Break", "B": "continue", "C": "break", "D": "stop"})
    )

    assert _DUP_ERROR in validation.errors


def test_exactly_four_still_enforced() -> None:
    """3 options → the count check fires and the ``elif`` short-circuits, so
    the distinctness error is NOT also raised (one MC error per payload)."""
    validation = _validate(
        _mc_payload(options={"A": "break", "B": "continue", "C": "pass"})
    )

    assert _COUNT_ERROR in validation.errors
    assert _DUP_ERROR not in validation.errors


def test_correct_answer_label_membership_still_enforced() -> None:
    """4 distinct options but ``correct_answer="Z"`` (not a valid label) →
    the pre-existing membership check still fires after the ``elif``
    insertion."""
    validation = _validate(_mc_payload(correct_answer="Z"))

    assert _LABEL_ERROR in validation.errors


def test_dup_error_takes_priority_over_bad_label() -> None:
    """Duplicate AND ``correct_answer="Z"`` → only the distinctness error
    appears; the ``elif`` ordering keeps exactly one MC structural error."""
    validation = _validate(
        _mc_payload(
            options={"A": "break", "B": "continue", "C": "break", "D": "stop"},
            correct_answer="Z",
        )
    )

    assert _DUP_ERROR in validation.errors
    assert _LABEL_ERROR not in validation.errors
