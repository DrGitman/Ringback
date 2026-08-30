"""prepare_call(): the one reasoning step in Ringback.

Reads the caller's raw query and, if known, their record. Decides the
intent, decides what to look up, judges whether what came back actually
answers the question - including how a KB rule and the student's own
record interact (a fee balance can block a subject drop regardless of the
deadline) - and produces a CallPlan: intent, a briefing written in its own
words, and whether the case should be dialled at all or routed straight to
a person instead.

CALL-E is still the only thing reasoning *during* a call. Nothing here
talks to CALL-E, and nothing runs once dispatch happens - this is a single
pre-call step, same as the retrieval-only version it replaces. Behind a
Preparer protocol so a model outage, timeout, or rate limit degrades to
DeterministicPreparer (the original keyword classifier + single-pass
TF-IDF) rather than failing the case.
"""

import datetime
import json
import logging
import os
import time
from dataclasses import dataclass, field
from functools import lru_cache
from typing import List, Optional, Protocol

from google import genai
from google.genai import types

from .classifier import classify
from .directory import Student, format_currency
from .retrieval import _blocks, _search, build_briefing, build_supplementary_briefing, get_retriever

logger = logging.getLogger(__name__)

# gemini-2.5-flash's free tier is 20 requests/day and 5/minute - verified
# empirically (the 429 body states the exact quotaValue), not assumed.
# That's unworkable for development or a live demo. Quota is scoped
# per-model (confirmed the same way), so a different model has separate,
# unexhausted quota. gemini-2.5-flash-lite and gemini-2.0-flash - both
# named in earlier advice - are already 404 for this key ("no longer
# available to new users"); gemini-3.5-flash-lite is the current
# equivalent and works today. Pinned to an explicit version rather than
# the "-latest" alias, since an alias can change behavior out from under
# a near-final demo without any code change to notice.
MODEL_NAME = "gemini-3.5-flash-lite"
MAX_ITERATIONS = 4
_MODEL_ATTEMPTS = 2
_MODEL_BACKOFF_SECONDS = 1.5

INTENTS = ("proof_of_registration", "subject_cancellation", "other")
CATEGORIES = (
    "fees",
    "academic_records",
    "faculty",
    "accommodation",
    "exams",
    "it_support",
    "unclear",
)


@dataclass
class CallPlan:
    intent: str
    reasoning: str
    briefing: str
    should_call: bool
    preparer_used: str  # "model" | "deterministic"
    category: Optional[str] = None  # only meaningful when intent == "other"
    route_to: Optional[str] = None  # tenant office key, required when should_call is False
    sources_used: List[dict] = field(default_factory=list)
    confidence: str = "medium"  # low | medium | high


class Preparer(Protocol):
    def prepare(self, query: str, student: Optional[Student], tenant: dict) -> CallPlan: ...


class DeterministicPreparer:
    """The original pipeline, unchanged in behavior: keyword classify plus
    single-pass TF-IDF retrieval. This is the fallback, so it must never
    itself raise in a way that blocks dispatch, and it never routes without
    calling - that judgment call belongs to the model; the deterministic
    path always dials, same as before this reasoning step existed.
    """

    def prepare(self, query: str, student: Optional[Student], tenant: dict) -> CallPlan:
        classification = classify(query)
        retriever = get_retriever(tenant["id"])
        record_backed = classification.intent in (
            "proof_of_registration",
            "subject_cancellation",
        ) and student is not None

        if record_backed:
            briefing, sources, _ = build_supplementary_briefing(query, retriever, tenant)
        else:
            briefing, sources, _ = build_briefing(query, retriever, tenant)

        return CallPlan(
            intent=classification.intent,
            category=classification.category,
            reasoning="Deterministic fallback: keyword-matched intent, single-pass retrieval.",
            briefing=briefing,
            should_call=True,
            route_to=None,
            sources_used=sources,
            confidence="medium" if classification.confidence >= 0.7 else "low",
            preparer_used="deterministic",
        )


_SEARCH_KB_DECL = types.FunctionDeclaration(
    name="search_kb",
    description=(
        "Search the official knowledge base for passages relevant to a query. "
        "Call this one to three times with different phrasing if the first pass "
        "doesn't cover every part of a compound question."
    ),
    parameters={
        "type": "object",
        "properties": {"query_text": {"type": "string", "description": "Search phrase."}},
        "required": ["query_text"],
    },
)


def _submit_plan_decl(office_keys: List[str]) -> types.FunctionDeclaration:
    return types.FunctionDeclaration(
        name="submit_plan",
        description="Submit your final call plan. Call this exactly once, when ready.",
        parameters={
            "type": "object",
            "properties": {
                "intent": {"type": "string", "enum": list(INTENTS)},
                "category": {
                    "type": "string",
                    "enum": list(CATEGORIES),
                    "description": "Only meaningful when intent is 'other'.",
                },
                "reasoning": {
                    "type": "string",
                    "description": (
                        "Short note on what you worked out and why - especially any "
                        "interaction between a KB rule and this caller's own record, "
                        "or why nothing in either covers the question."
                    ),
                },
                "briefing": {
                    "type": "string",
                    "description": (
                        "The paragraph that gets read into the call task, in your own "
                        "words - never pasted chunks. Ground it only in what search_kb "
                        "returned and the caller's own record. Never invent a date, "
                        "amount, or requirement that isn't in one of those two places. "
                        "If something isn't covered, say so plainly rather than guessing."
                    ),
                },
                "should_call": {
                    "type": "boolean",
                    "description": (
                        "False only when this needs a human who can see the account "
                        "directly - route it instead of spending a call on it."
                    ),
                },
                "route_to": {
                    "type": "string",
                    "enum": office_keys,
                    "description": "Required when should_call is false.",
                },
                "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
            },
            "required": ["intent", "reasoning", "briefing", "should_call", "confidence"],
        },
    )


# Fields the disclosure rules say must never be spoken to anyone, or used to
# confirm identity only - not reasoned about or repeated in a briefing. Scrubbed
# from the model's input entirely rather than merely prompted against, so a
# leak (e.g. an invented honorific inferred from gender) can't happen even if
# the model ignores an instruction. See _disclosure_and_channel_instructions()
# in dispatcher.py for the parallel rule enforced during the call itself.
_NEVER_DISCLOSED_FIELDS = {"gender", "marital_status", "disability", "id_number", "birthdate"}

# Keys anywhere in the student record whose value is money, so every amount
# reaches the model already formatted - the model is not asked to format
# currency itself, only to use the string it's given.
_CURRENCY_FIELDS = {
    "fee_balance", "quote_total", "debit", "credit", "balance", "awarded",
    "allocated", "unallocated", "days_160", "days_90", "days_60", "days_30",
    "current", "future",
}


def _sanitize_for_model(value):
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            if k in _NEVER_DISCLOSED_FIELDS:
                continue
            if k in _CURRENCY_FIELDS and isinstance(v, (int, float)):
                out[k] = format_currency(v)
            else:
                out[k] = _sanitize_for_model(v)
        return out
    if isinstance(value, list):
        return [_sanitize_for_model(v) for v in value]
    return value


def _system_instruction(query: str, student: Optional[Student], tenant: dict, office_keys: List[str]) -> str:
    if student:
        sanitized = _sanitize_for_model(student.model_dump(mode="json"))
        record_text = json.dumps(sanitized, indent=2, default=str)
    else:
        record_text = "No student record - caller has not provided a student number, or none matched."
    today = datetime.date.today().isoformat()
    return (
        f"You are the reasoning step for {tenant['short_name']}'s callback system, "
        f"{tenant['calling_office']}. A student submitted a question through an intake "
        "form; nobody has spoken to them yet. You are NOT answering them yourself - you "
        "are preparing a briefing for a separate calling agent (CALL-E) that will phone "
        "them shortly. You never speak to the caller.\n\n"
        f"Today's date is {today}. Use it to judge whether any deadline in the record or "
        "the knowledge base has already passed - never just recite a deadline, say "
        "explicitly whether it's still open or has passed.\n\n"
        f"Valid intents: {', '.join(INTENTS)}.\n\n"
        "Work out what the caller actually needs, including how a KB rule and their own "
        "record interact if both apply (e.g. a fee balance can block a subject drop "
        "regardless of the deadline). Use search_kb to look up anything you need - call "
        "it more than once with different phrasing if the first pass misses part of a "
        "compound question.\n\n"
        "If the record plus what you retrieve still doesn't clearly answer the question, "
        "or the question needs a person who can see the account directly, set "
        f"should_call to false and pick the right office from: {', '.join(office_keys)}. "
        "Otherwise write the briefing paragraph yourself, grounded only in what "
        "search_kb returned and the record below - never invent a date, amount, or "
        "requirement that isn't in one of those two places.\n\n"
        "Write the briefing in second person, addressed directly to the caller ('you', "
        "'your') - never third person ('the student', 'they'), never a name plus title. "
        "Any currency amount you use is already formatted in the record below (e.g. "
        "\"N$2,340.00\") - copy it exactly, never reformat or recompute it. Never invent "
        "an honorific, gender, or title for the caller - fields that would reveal those "
        "have been deliberately withheld from you, so refer to them only by name or "
        "'you'.\n\n"
        f'Caller\'s exact words: "{query}"\n\n'
        f"Caller's record:\n{record_text}\n\n"
        "When ready, call submit_plan exactly once."
    )


class ModelPreparer:
    def __init__(self, client: genai.Client, model: str = MODEL_NAME):
        self._client = client
        self._model = model

    def prepare(self, query: str, student: Optional[Student], tenant: dict) -> CallPlan:
        retriever = get_retriever(tenant["id"])
        office_keys = list(tenant["offices"].keys())
        tools = [types.Tool(function_declarations=[_SEARCH_KB_DECL, _submit_plan_decl(office_keys)])]
        config = types.GenerateContentConfig(tools=tools)

        contents = [
            types.Content(
                role="user",
                parts=[types.Part(text=_system_instruction(query, student, tenant, office_keys))],
            )
        ]
        chunks_seen: dict = {}

        for _ in range(MAX_ITERATIONS):
            resp = self._client.models.generate_content(model=self._model, contents=contents, config=config)
            candidate = resp.candidates[0] if resp.candidates else None
            part = candidate.content.parts[0] if candidate and candidate.content.parts else None
            call = part.function_call if part else None

            if call is None:
                raise RuntimeError("Model responded without calling a tool.")

            contents.append(candidate.content)
            args = dict(call.args)

            if call.name == "submit_plan":
                return CallPlan(
                    intent=args["intent"],
                    category=args.get("category"),
                    reasoning=args["reasoning"],
                    briefing=args["briefing"],
                    should_call=args["should_call"],
                    route_to=args.get("route_to"),
                    sources_used=list(chunks_seen.values()),
                    confidence=args.get("confidence", "medium"),
                    preparer_used="model",
                )

            if call.name == "search_kb":
                hits, provenance = _search(args.get("query_text", query), retriever)
                for p in provenance:
                    chunks_seen[p["chunk_id"]] = p
                result_text = _blocks(hits) if hits else "No results above the relevance threshold."
                contents.append(
                    types.Content(
                        role="user",
                        parts=[
                            types.Part(
                                function_response=types.FunctionResponse(
                                    name="search_kb", response={"result": result_text}
                                )
                            )
                        ],
                    )
                )
                continue

            raise RuntimeError(f"Model called unknown tool: {call.name}")

        raise RuntimeError("Model did not converge on a plan within the iteration budget.")


@lru_cache
def _client() -> Optional[genai.Client]:
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return None
    return genai.Client(api_key=api_key)


def prepare_call(query: str, student: Optional[Student], tenant: dict) -> CallPlan:
    client = _client()
    if client is not None:
        for attempt in range(_MODEL_ATTEMPTS):
            try:
                return ModelPreparer(client).prepare(query, student, tenant)
            except Exception as exc:
                logger.warning(
                    "prepare: model preparer attempt %d/%d failed (%s)",
                    attempt + 1,
                    _MODEL_ATTEMPTS,
                    exc,
                )
                if attempt < _MODEL_ATTEMPTS - 1:
                    time.sleep(_MODEL_BACKOFF_SECONDS)
        logger.warning("prepare: model preparer exhausted retries, falling back to deterministic")

    return DeterministicPreparer().prepare(query, student, tenant)
