"""The only file in this codebase that imports or talks to CALL-E.

Every other module calls CalleClient.dispatch() / .get_result() and knows
nothing about the transport underneath. Set CALLE_API_KEY (see .env.example)
to switch from the local mock transport to real calls against the CALL-E
REST API — nothing else in the app needs to change.
"""

import os
import time
import uuid
from dataclasses import dataclass
from typing import Optional

import httpx


@dataclass
class CallResult:
    status: str  # in_progress | completed | no_answer | voicemail | failed
    structured_result: Optional[dict] = None
    transcript: Optional[list] = None
    completion_confidence: Optional[float] = None
    task_completed: Optional[bool] = None
    evidence: Optional[str] = None


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

    def get_result(self, run_id: str) -> CallResult:
        response = self._client.get(f"/v1/calls/{run_id}")
        response.raise_for_status()
        data = response.json()
        status = data.get("status")

        if status in ("queued", "planning", "calling", "in_progress"):
            return CallResult(status="in_progress")

        if status == "completed":
            return CallResult(
                status="completed",
                structured_result=data.get("structured_result"),
                transcript=data.get("transcript"),
                completion_confidence=data.get("completion_confidence"),
                task_completed=data.get("task_completed"),
                evidence=data.get("evidence"),
            )

        return CallResult(status=status or "failed")


class _MockTransport:
    """Stands in until a live CALLE_API_KEY is configured (see the Day 1
    checklist in README.md). Outcomes are deterministic per phone number so
    the dashboard demos sensibly before the CALL-E account is wired in —
    delete this class once real calls work.
    """

    _SCENARIOS = {
        "+264811234567": {
            "delay": 6,
            "terminal": "completed",
            "fields": {
                "resolved": False,
                "identity_confirmed": True,
                "blocker": "fee_balance",
                "student_next_action": "Pay the outstanding balance at the Cashier's Office or by EFT.",
                "wants_escalation": True,
            },
        },
        "+264812345678": {
            "delay": 5,
            "terminal": "completed",
            "fields": {
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
            "terminal": "completed",
            "fields": {
                "identity_confirmed": True,
                "category": "accommodation",
                "summary": "Accommodation deposit deducted twice in July; needs finance reconciliation.",
                "urgency": "deadline_driven",
                "student_callback_preference": "Same number, afternoons",
            },
        },
        "+264814567890": {"delay": 4, "terminal": "no_answer", "fields": {}},
    }
    _DEFAULT = {
        "delay": 5,
        "terminal": "completed",
        "fields": {"resolved": True, "identity_confirmed": True},
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
            return CallResult(status="failed")

        elapsed = time.monotonic() - run["started"]
        if elapsed < run["scenario"]["delay"]:
            return CallResult(status="in_progress")

        terminal = run["scenario"]["terminal"]
        if terminal != "completed":
            return CallResult(status=terminal)

        fields = dict(run["scenario"]["fields"])
        for name in run["schema"].get("required", []):
            fields.setdefault(name, True)

        return CallResult(
            status="completed",
            structured_result=fields,
            transcript=_mock_transcript(),
            completion_confidence=0.87,
            task_completed=True,
            evidence="Simulated locally — no live CALL-E call was placed.",
        )


def _mock_transcript() -> list:
    return [
        {
            "speaker": "CALL-E",
            "text": "Hi, I'm calling on behalf of the Registrar's Office. Is now an okay time to talk?",
            "time": "00:04",
        },
        {"speaker": "STUDENT", "text": "Yes, go ahead.", "time": "00:08"},
        {
            "speaker": "CALL-E",
            "text": "Great — could you confirm your student number for me first?",
            "time": "00:11",
        },
        {"speaker": "STUDENT", "text": "Sure, one second, let me find it.", "time": "00:15"},
    ]


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
