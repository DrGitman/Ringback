"""The only file in this codebase that imports or talks to CALL-E.

Every other module calls CalleClient.dispatch() / .get_result() and knows
nothing about the transport underneath. Set CALLE_API_KEY (see .env.example)
to switch from the local mock transport to real calls against the CALL-E
REST API — nothing else in the app needs to change.

parse_call_response() is written against a real get_call_run payload
captured on 2026-08-26, not against the API docs' shorthand example — the
two disagree in several places (see git history / feedback-log.md). Only
`status` is guaranteed present on the raw payload; everything under
`result` may be entirely absent, so every access below is defensive.
"""

import os
import time
import uuid
from dataclasses import dataclass
from typing import List, Optional

import httpx


@dataclass
class CallResult:
    status: str  # in_progress | completed | no_answer | declined | failed | <other>
    structured_result: Optional[dict] = None
    transcript: Optional[str] = None
    completion_confidence: Optional[float] = None
    task_completed: Optional[bool] = None
    evidence: Optional[List[str]] = None
    summary: Optional[str] = None
    post_summary: Optional[str] = None
    poll_after_seconds: Optional[float] = None


# Real statuses are uppercase and may contain spaces. PREPARING/SCHEDULED are
# non-terminal; everything else maps to a terminal outcome. Anything unknown
# falls through to a lowercased/underscored version of itself rather than
# crashing, and dispatcher.py treats "unknown terminal status" the same as
# any other non-completed terminal: retry, then fail after 3 attempts.
_IN_PROGRESS_STATUSES = {"PREPARING", "SCHEDULED"}
_TERMINAL_STATUS_MAP = {
    "COMPLETED": "completed",
    "NO ANSWER": "no_answer",
    "DECLINED": "declined",
    "FAILED": "failed",
}


def _poll_after_seconds(data: dict) -> Optional[float]:
    next_step = data.get("next_step") or {}
    value = next_step.get("poll_after_seconds")
    if isinstance(value, (int, float)):
        return max(1.0, float(value))
    return None


def parse_call_response(data: dict) -> CallResult:
    """Maps a raw call-status payload (get_call_run / GET /v1/calls/{id}) to
    a CallResult. See tests/test_parse_call_response.py for the shape this is
    verified against, and tests/replay_fixture.py to replay a saved real
    response through this exact function without spending another call.
    """
    raw_status = str(data.get("status") or "").strip().upper()
    poll_after = _poll_after_seconds(data)

    if not raw_status or raw_status in _IN_PROGRESS_STATUSES:
        return CallResult(status="in_progress", poll_after_seconds=poll_after)

    status = _TERMINAL_STATUS_MAP.get(raw_status, raw_status.lower().replace(" ", "_"))

    result = data.get("result") or {}
    outcome = result.get("outcome") or {}

    confidence = outcome.get("completion_confidence")
    confidence_score = confidence.get("score") if isinstance(confidence, dict) else confidence

    return CallResult(
        status=status,
        structured_result=result.get("extracted"),
        transcript=result.get("transcript"),
        completion_confidence=confidence_score,
        task_completed=outcome.get("task_completed"),
        evidence=outcome.get("evidence"),
        summary=result.get("summary"),
        post_summary=result.get("post_summary"),
        poll_after_seconds=poll_after,
    )


# "fetch failed" from a high-latency region (see feedback-log.md, 2026-08-26)
# is a transport-level blip, not a call outcome — it must not be treated the
# same as a real terminal failure. Retry the HTTP request itself a few times
# before letting it bubble up to dispatcher's exception handler.
_TRANSIENT_ATTEMPTS = 3
_TRANSIENT_BACKOFF_SECONDS = 1.5


def _with_retry(fn):
    last_exc: Optional[Exception] = None
    for attempt in range(_TRANSIENT_ATTEMPTS):
        try:
            return fn()
        except httpx.TransportError as exc:
            last_exc = exc
            if attempt < _TRANSIENT_ATTEMPTS - 1:
                time.sleep(_TRANSIENT_BACKOFF_SECONDS * (attempt + 1))
    raise last_exc


class _RealTransport:
    """Wraps the CALL-E Developer API directly (POST /v1/calls, GET /v1/calls/{id})
    rather than the SDK, per the plan's own reasoning: creating and polling a call
    is a handful of httpx calls, which is safer than depending on a beta SDK.
    """

    def __init__(self, api_key: str, base_url: str):
        self._client = httpx.Client(
            base_url=base_url,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=30,
        )

    def dispatch(self, task: str, phone: str, result_schema: dict) -> str:
        def _do():
            response = self._client.post(
                "/v1/calls",
                json={
                    "task": task,
                    "recipients": [{"phones": [phone]}],
                    "recipient_result_schema": result_schema,
                },
            )
            response.raise_for_status()
            return response.json()["id"]

        return _with_retry(_do)

    def get_result(self, run_id: str) -> CallResult:
        def _do():
            response = self._client.get(f"/v1/calls/{run_id}")
            response.raise_for_status()
            return response.json()

        return parse_call_response(_with_retry(_do))


class _MockTransport:
    """Stands in until a live CALLE_API_KEY is configured (see the Day 1
    checklist in README.md). Outcomes are deterministic per phone number so
    the dashboard demos sensibly before the CALL-E account is wired in.

    Builds the same raw envelope shape a real call returns and routes it
    through parse_call_response, same as _RealTransport — so the mock can't
    quietly drift from what real responses look like again.
    """

    _SCENARIOS = {
        "+264811234567": {
            "delay": 6,
            "status": "COMPLETED",
            "extracted": {
                "resolved": False,
                "identity_confirmed": True,
                "blocker": "fee_balance",
                "student_next_action": "Pay the outstanding balance at the Cashier's Office or by EFT.",
                "wants_escalation": True,
            },
        },
        "+264812345678": {
            "delay": 5,
            "status": "COMPLETED",
            "extracted": {
                "resolved": True,
                "identity_confirmed": True,
                "subject_code": "MAT621S",
                "within_deadline": True,
                "student_confirmed_drop": True,
                "fee_implication_explained": True,
                "wants_escalation": False,
            },
        },
        "+264813456789": {
            "delay": 6,
            "status": "COMPLETED",
            "extracted": {
                "identity_confirmed": True,
                "category": "accommodation",
                "summary": "Accommodation deposit deducted twice in July; needs finance reconciliation.",
                "urgency": "deadline_driven",
                "student_callback_preference": "Same number, afternoons",
            },
        },
        "+264814567890": {"delay": 4, "status": "NO ANSWER", "extracted": None},
    }
    _DEFAULT = {
        "delay": 5,
        "status": "COMPLETED",
        "extracted": {"resolved": True, "identity_confirmed": True},
    }

    def __init__(self):
        self._runs: dict = {}

    def dispatch(self, task: str, phone: str, result_schema: dict) -> str:
        run_id = f"mock_{uuid.uuid4().hex[:10]}"
        self._runs[run_id] = {
            "started": time.monotonic(),
            "scenario": self._SCENARIOS.get(phone, self._DEFAULT),
            "schema": result_schema,
        }
        return run_id

    def get_result(self, run_id: str) -> CallResult:
        run = self._runs.get(run_id)
        if run is None:
            return parse_call_response({"status": "FAILED"})

        elapsed = time.monotonic() - run["started"]
        if elapsed < run["scenario"]["delay"]:
            return parse_call_response(
                {"status": "PREPARING", "next_step": {"poll_after_seconds": 2}}
            )

        scenario = run["scenario"]
        if scenario["status"] != "COMPLETED":
            return parse_call_response({"status": scenario["status"]})

        extracted = dict(scenario["extracted"] or {})
        for name in run["schema"].get("required", []):
            extracted.setdefault(name, True)

        return parse_call_response(
            {
                "status": "COMPLETED",
                "result": {
                    "extracted": extracted,
                    "outcome": {
                        "task_completed": True,
                        "completion_confidence": {"score": 0.87, "label": "high"},
                        "evidence": ["Simulated locally - no live CALL-E call was placed."],
                    },
                    "transcript": _mock_transcript_text(),
                    "summary": "Simulated call for local development.",
                    "post_summary": "No live call was placed; this is mock data.",
                },
            }
        )


def _mock_transcript_text() -> str:
    return (
        "CALL-E: Hi, I'm calling on behalf of the Registrar's Office. Is now an "
        "okay time to talk?\n"
        "STUDENT: Yes, go ahead.\n"
        "CALL-E: Great - could you confirm your student number for me first?\n"
        "STUDENT: Sure, one second, let me find it."
    )


class CalleClient:
    def __init__(self):
        api_key = os.environ.get("CALLE_API_KEY")
        base_url = os.environ.get("CALLE_BASE_URL", "https://api.heycall-e.com")
        if api_key:
            self._transport = _RealTransport(api_key, base_url)
            self.is_live = True
        else:
            self._transport = _MockTransport()
            self.is_live = False

    def dispatch(self, task: str, phone: str, result_schema: dict) -> str:
        return self._transport.dispatch(task, phone, result_schema)

    def get_result(self, run_id: str) -> CallResult:
        return self._transport.get_result(run_id)
