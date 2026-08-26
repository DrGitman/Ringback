"""Plain-assertion tests for parse_call_response — no pytest dependency.

Run directly: python tests/test_parse_call_response.py

Confirms the parser matches CALL-E's real output shape (uppercase, spaced
statuses; result.extracted; result.outcome.{task_completed,
completion_confidence, evidence}; result.transcript as a plain string) and,
per today's fix list, that a minimal {run_id, status: "NO ANSWER"} response
produces a clean failure rather than an exception.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.calle_client import parse_call_response  # noqa: E402


def test_minimal_no_answer_does_not_raise():
    result = parse_call_response({"run_id": "call_1", "status": "NO ANSWER"})
    assert result.status == "no_answer"
    assert result.structured_result is None
    assert result.transcript is None
    assert result.completion_confidence is None


def test_in_progress_statuses():
    for raw in ("PREPARING", "SCHEDULED"):
        result = parse_call_response({"run_id": "call_1", "status": raw})
        assert result.status == "in_progress", raw


def test_missing_status_treated_as_in_progress_not_a_crash():
    result = parse_call_response({"run_id": "call_1"})
    assert result.status == "in_progress"


def test_completed_with_full_envelope():
    raw = {
        "run_id": "call_1",
        "status": "COMPLETED",
        "result": {
            "extracted": {"resolved": True, "identity_confirmed": True},
            "outcome": {
                "task_completed": True,
                "completion_confidence": {"score": 0.91, "label": "high"},
                "evidence": ["Student confirmed student number."],
            },
            "transcript": "CALL-E: Hi...\nSTUDENT: Hello.",
            "summary": "Call resolved cleanly.",
            "post_summary": "No follow-up needed.",
        },
    }
    result = parse_call_response(raw)
    assert result.status == "completed"
    assert result.structured_result == {"resolved": True, "identity_confirmed": True}
    assert result.completion_confidence == 0.91
    assert result.task_completed is True
    assert result.evidence == ["Student confirmed student number."]
    assert result.transcript == "CALL-E: Hi...\nSTUDENT: Hello."
    assert result.summary == "Call resolved cleanly."
    assert result.post_summary == "No follow-up needed."


def test_declined_and_failed():
    assert parse_call_response({"status": "DECLINED"}).status == "declined"
    assert parse_call_response({"status": "FAILED"}).status == "failed"


def test_unknown_status_normalises_instead_of_crashing():
    result = parse_call_response({"status": "CANCELED BY CALLER"})
    assert result.status == "canceled_by_caller"


def test_completed_with_result_entirely_missing():
    result = parse_call_response({"run_id": "call_1", "status": "COMPLETED"})
    assert result.status == "completed"
    assert result.structured_result is None
    assert result.transcript is None
    assert result.completion_confidence is None
    assert result.task_completed is None
    assert result.evidence is None


def test_completion_confidence_as_bare_number_still_works():
    raw = {
        "status": "COMPLETED",
        "result": {"outcome": {"completion_confidence": 0.5}},
    }
    result = parse_call_response(raw)
    assert result.completion_confidence == 0.5


def test_next_step_poll_after_seconds_is_honoured():
    result = parse_call_response(
        {"status": "PREPARING", "next_step": {"poll_after_seconds": 2}}
    )
    assert result.poll_after_seconds == 2.0


def test_poll_after_seconds_clamped_to_at_least_one():
    result = parse_call_response(
        {"status": "PREPARING", "next_step": {"poll_after_seconds": 0}}
    )
    assert result.poll_after_seconds == 1.0


def main() -> None:
    tests = [obj for name, obj in sorted(globals().items()) if name.startswith("test_")]
    failures = 0
    for test in tests:
        try:
            test()
            print(f"PASS  {test.__name__}")
        except AssertionError as exc:
            failures += 1
            print(f"FAIL  {test.__name__}: {exc}")
    if failures:
        print(f"\n{failures} of {len(tests)} tests failed")
        raise SystemExit(1)
    print(f"\nAll {len(tests)} tests passed")


if __name__ == "__main__":
    main()
