import asyncio
from datetime import datetime

from sqlmodel import Session

from .calle_client import CalleClient
from .directory import SqlDirectory
from .models import (
    Case,
    engine,
    set_retrieved_sources,
    set_structured_result,
    set_transcript,
)
from .prepare import CallPlan, prepare_call
from .router import route_case
from .schemas import PROOF_OF_REG, SUBJECT_CANCELLATION, TRIAGE
from .tenants import load_tenant

# Real calls: wait ~60s before the first poll, then every 5-10s, per the CALL-E
# docs. The mock transport resolves in a few seconds, so it uses a tighter
# rhythm purely so local demos don't sit idle.
POLL_WAIT_FIRST_LIVE = 60
POLL_INTERVAL_LIVE = 8
POLL_WAIT_FIRST_MOCK = 6
POLL_INTERVAL_MOCK = 2
MAX_ATTEMPTS = 3

SCHEMAS = {
    "proof_of_registration": PROOF_OF_REG,
    "subject_cancellation": SUBJECT_CANCELLATION,
    "other": TRIAGE,
}

client = CalleClient()
directory = SqlDirectory()

WAIT_FIRST = POLL_WAIT_FIRST_LIVE if client.is_live else POLL_WAIT_FIRST_MOCK
POLL_INTERVAL = POLL_INTERVAL_LIVE if client.is_live else POLL_INTERVAL_MOCK


def _schema_for(intent: str) -> dict:
    return SCHEMAS.get(intent, TRIAGE)


def _apply_plan(case: Case, plan: CallPlan) -> None:
    """Records prepare_call()'s decision on the case as a side effect, so
    the reasoning behind a call - or a route without one - is visible on
    the dashboard rather than acted on invisibly. Runs once per dispatch
    attempt, before the call - CALL-E has no hook to query anything
    mid-call, so everything has to be decided up front.
    """
    case.intent = plan.intent
    case.category = plan.category
    case.reasoning = plan.reasoning
    case.plan_confidence = plan.confidence
    case.preparer_used = plan.preparer_used
    case.should_call = plan.should_call
    if plan.sources_used:
        set_retrieved_sources(case, plan.sources_used)
    case.no_kb_coverage = not plan.sources_used and plan.intent == "other"


def _route_without_calling(case: Case, tenant: dict, plan: CallPlan) -> None:
    """should_call=False means prepare_call() judged this needs a human who
    can see the account directly - route it with the reasoning as the
    escalation reason instead of spending a call on a question nothing can
    resolve over the phone.
    """
    offices = tenant["offices"]
    office = offices.get(plan.route_to) or offices["registrar"]
    case.routed_office = office["name"]
    case.routed_contact = f"{office['contact']} · {office['email']}"
    case.routed_reason = plan.reasoning
    case.channel = "route"
    case.channel_reason = plan.reasoning
    case.status = "routed"


def _disclosure_and_channel_instructions(tenant: dict) -> str:
    """Shared across every intent, appended once per task. Two separate
    concerns bundled together because they're both about what must never
    happen on a call: disclosing something to the wrong person, and
    concluding something that isn't actually finished. The office
    directory is built from tenant config rather than hardcoded, since
    which office is relevant depends on what comes up mid-call - not
    knowable when the task string is written.
    """
    offices = tenant["offices"]
    directory = "; ".join(
        f"{o['name']}: {o['email']}, {o['location']}" for o in offices.values()
    )
    return (
        "If the caller is a parent, sponsor, or anyone other than the student, "
        "disclose nothing about the account and say the student must contact the "
        "office directly themselves. Never state the student's ID number, "
        "birthdate, disability status, marital status, or full address out loud - "
        "you may confirm a detail back to them only if they state it first.\n\n"
        "Some requests cannot be completed on this call: payment arrangements, "
        "appeals, deferrals, registration cancellation, name or ID corrections, "
        "student number recovery, transcript requests, and disability "
        "accommodations. When one of these comes up, say so, explain why briefly, "
        "and give the exact next step - the office name, its email, and its "
        "location. Office directory: "
        f"{directory}. Set channel to email, in_person, or route accordingly, and "
        "channel_reason to a short explanation. Only set channel to phone if this "
        "is genuinely finished by the end of the call.\n\n"
        "Documents and statements go only to the email address already on file. "
        "If the caller asks for something to be sent elsewhere, explain that "
        "changing the address on file is a separate process at the office. You "
        "may state a balance amount once identity is confirmed, but never read a "
        "full statement line by line - offer to email it instead."
    )


def build_task(case: Case, student, tenant: dict, briefing: str = "") -> str:
    minutes = max(1, int((datetime.utcnow() - case.created_at).total_seconds() // 60))
    # The student record's name is verified by the student_number lookup;
    # caller_name is just what they typed into the form. Use the record's
    # name once it's confirmed, and the self-reported one only to greet
    # them beforehand - never as a substitute for the confirmation step.
    name = student.name if student else (case.caller_name or "the caller")

    lines = [
        tenant["agent_intro"],
        f'You are speaking to {name}, who submitted a question {minutes} minute(s) ago. '
        f'Their exact words were: "{case.original_query}".',
    ]

    if student:
        lines.append(
            f"First confirm you're speaking to {name} by asking them to confirm their "
            f"student number ({student.student_number}). Do not discuss account details "
            f"before they confirm."
        )
    else:
        lines.append(
            f"This caller gave their name as {name} but has not provided a student "
            "number. Do not assume they are a currently registered student, and do "
            "not guess at their record."
        )

    if case.intent == "proof_of_registration" and student:
        if student.fee_balance > 0:
            lines.append(
                f"Their proof of registration cannot be issued because they have an "
                f"outstanding balance of N${student.fee_balance:.2f}. Explain this warmly "
                f"and without blame. Tell them it can be settled at the Cashier's Office "
                f"or by EFT, and that the document is issued automatically within 24 "
                f"hours of payment clearing. Ask whether they'd like the Fees Office to "
                f"call them about a payment arrangement."
            )
        elif student.registration_status != "registered":
            lines.append(
                "Their registration is not yet complete, so a proof of registration "
                "cannot be issued yet. Explain that the Registrar's Office needs to "
                "finish reviewing their file, and that you'll have that office follow up."
            )
        else:
            lines.append(
                "Their registration is complete and there is no outstanding balance, so "
                "their proof of registration is ready. Tell them it will appear in the "
                "student portal shortly, or can be collected in person from the "
                "Registrar's Office."
            )
        if briefing:
            lines.append(briefing)
    elif case.intent == "subject_cancellation" and student:
        subject = student.subjects[0] if student.subjects else None
        if subject:
            lines.append(
                f"They want to cancel {subject.code} ({subject.name}). The drop deadline "
                f"for this subject is {subject.drop_deadline}. Confirm whether today's "
                f"date is before that deadline before agreeing to process the "
                f"cancellation, and explain any fee implication of dropping this late in "
                f"the term."
            )
        else:
            lines.append(
                "They want to cancel a subject, but no matching subject was found on "
                "their record. Ask them to confirm the exact subject code before "
                "proceeding."
            )
        if briefing:
            lines.append(briefing)
    else:
        if briefing:
            lines.append(briefing)
            lines.append(
                "Before ending the call, confirm out loud whether this answered what "
                "they needed - e.g. ask 'does that answer your question?' Only report "
                "resolved as true if they confirm it. If they're unsure, still have "
                "something outstanding, or the reference didn't actually cover what "
                "they asked, report resolved as false so the right office follows up."
            )
        else:
            lines.append(
                "This question does not match a resolvable process, and no reference "
                "material covers it either. Listen carefully, ask clarifying questions, "
                "and let them know you'll have the right office follow up with exactly "
                "what they asked. Do not guess at an answer. Report resolved as false."
            )

    lines.append(_disclosure_and_channel_instructions(tenant))

    lines.append(
        f"{tenant['tone_instruction']} Do not discuss any other student's information. "
        f"If they ask about anything you don't know, say you'll have the right office "
        f"follow up, and note what they asked."
    )
    return "\n\n".join(lines)


def _mark_errored(case_id: int, message: str) -> None:
    """Last-resort handler so a malformed or failing CALL-E response ends a
    case visibly on the dashboard instead of leaving it stuck on "calling"
    forever with a background task that silently died.
    """
    with Session(engine) as session:
        case = session.get(Case, case_id)
        if case is None:
            return
        case.status = "failed"
        case.call_status = f"error: {message[:200]}"
        session.add(case)
        session.commit()


async def handle_case(case_id: int) -> None:
    try:
        with Session(engine) as session:
            case = session.get(Case, case_id)
            tenant = load_tenant(case.tenant_id)
            student = directory.lookup(case.student_number) if case.student_number else None

            plan = prepare_call(case.original_query, student, tenant)
            _apply_plan(case, plan)
            case.status = "classified"

            if not plan.should_call:
                _route_without_calling(case, tenant, plan)
                session.add(case)
                session.commit()
                return

            # Commit the plan before attempting dispatch. If dispatch below
            # raises, this session would otherwise roll back with it - and
            # prepare_call()'s reasoning, already done, would disappear from
            # a case left showing "failed" with nothing to explain why.
            session.add(case)
            session.commit()
    except Exception as exc:
        _mark_errored(case_id, str(exc))
        return

    try:
        with Session(engine) as session:
            case = session.get(Case, case_id)
            tenant = load_tenant(case.tenant_id)
            student = directory.lookup(case.student_number) if case.student_number else None
            task = build_task(case, student, tenant, plan.briefing)
            case.run_id = client.dispatch(
                task=task, phone=case.phone, result_schema=_schema_for(case.intent)
            )
            case.call_attempts = 1
            case.status = "calling"
            session.add(case)
            session.commit()
    except Exception as exc:
        _mark_errored(case_id, str(exc))
        return

    await asyncio.sleep(WAIT_FIRST)
    await _poll_case(case_id)


async def resume_case(case_id: int) -> None:
    """Resumes polling a case that was already "calling" with a run_id when
    the process last stopped - a Render free-tier spin-down or a plain
    restart must not stop the app from ever hearing back about a call that
    got placed for real. Called once per such case at startup (see
    main.py's lifespan). Polls immediately rather than sleeping WAIT_FIRST
    first, since the call has been in flight for however long the process
    was down, not freshly dispatched.
    """
    await _poll_case(case_id)


async def _poll_case(case_id: int) -> None:
    while True:
        next_sleep = POLL_INTERVAL
        try:
            with Session(engine) as session:
                case = session.get(Case, case_id)
                if case is None or case.status in ("resolved", "routed", "failed"):
                    return
                if not case.run_id:
                    # Nothing to poll - shouldn't happen for a "calling" case,
                    # but bail cleanly rather than crashing the loop on None.
                    return

                result = client.get_result(case.run_id)
                # CALL-E's next_step.poll_after_seconds, when present, is more
                # current than our fixed interval — honour it (see calle_client.py).
                if result.poll_after_seconds is not None:
                    next_sleep = result.poll_after_seconds

                if result.status == "in_progress":
                    pass
                elif result.status == "completed":
                    structured = result.structured_result
                    if not isinstance(structured, dict):
                        structured = {}
                    set_structured_result(case, structured)
                    set_transcript(case, result.transcript)
                    case.completion_confidence = result.completion_confidence
                    case.call_status = "completed"
                    case.channel = structured.get("channel")
                    case.channel_reason = structured.get("channel_reason")

                    tenant = load_tenant(case.tenant_id)
                    if structured.get("resolved") is True and case.channel == "phone":
                        case.status = "resolved"
                    else:
                        route_case(case, tenant)
                        case.status = "routed"
                    session.add(case)
                    session.commit()
                    return
                else:
                    case.call_status = result.status
                    if case.call_attempts >= MAX_ATTEMPTS:
                        case.status = "failed"
                        session.add(case)
                        session.commit()
                        return

                    tenant = load_tenant(case.tenant_id)
                    student = (
                        directory.lookup(case.student_number) if case.student_number else None
                    )
                    # Re-runs the reasoning step on every retry, same as the
                    # retrieval-only version this replaced re-ran retrieval on
                    # every retry. A retry only happens after a no-answer or
                    # failed call (max 3 attempts total), so the extra model
                    # call is rare, not per-poll - and it means a transient
                    # model failure on attempt 1 can still resolve for real
                    # on attempt 2 instead of being stuck on the fallback.
                    plan = prepare_call(case.original_query, student, tenant)
                    _apply_plan(case, plan)
                    # Same as the first attempt: commit the plan before
                    # dispatch, so a dispatch failure doesn't roll back the
                    # reasoning behind it along with the exception.
                    session.add(case)
                    session.commit()
                    task = build_task(case, student, tenant, plan.briefing)
                    case.run_id = client.dispatch(
                        task=task, phone=case.phone, result_schema=_schema_for(case.intent)
                    )
                    case.call_attempts += 1
                    case.status = "calling"
                    session.add(case)
                    session.commit()
                    await asyncio.sleep(WAIT_FIRST)
                    continue
        except Exception as exc:
            _mark_errored(case_id, str(exc))
            return

        await asyncio.sleep(next_sleep)
