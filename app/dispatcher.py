import asyncio
from datetime import datetime

from sqlmodel import Session

from .calle_client import CalleClient
from .directory import JSONDirectory
from .kb import KnowledgeBase
from .models import Case, engine, set_structured_result, set_transcript
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
directory = JSONDirectory()

WAIT_FIRST = POLL_WAIT_FIRST_LIVE if client.is_live else POLL_WAIT_FIRST_MOCK
POLL_INTERVAL = POLL_INTERVAL_LIVE if client.is_live else POLL_INTERVAL_MOCK


def _schema_for(intent: str) -> dict:
    return SCHEMAS.get(intent, TRIAGE)


def build_task(case: Case, student, tenant: dict) -> str:
    minutes = max(1, int((datetime.utcnow() - case.created_at).total_seconds() // 60))
    name = student.name if student else "the caller"

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
            "This caller has not provided a student number. Do not assume they are a "
            "currently registered student, and do not guess at their record."
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
    else:
        kb_text = KnowledgeBase(case.tenant_id).select(case.intent, case.category)
        if kb_text:
            lines.append(
                f"Reference information you may use:\n---\n{kb_text}\n---\nAnswer only "
                f"from this reference and the student's record. If the answer isn't "
                f"there, say you'll have the right office follow up, and note exactly "
                f"what they asked."
            )
        else:
            lines.append(
                "This question does not match a resolvable process. Listen carefully, "
                "ask clarifying questions, and let them know you'll have the right "
                "office follow up with exactly what they asked."
            )

    lines.append(
        f"{tenant['tone_instruction']} Do not discuss any other student's information. "
        f"If they ask about anything you don't know, say you'll have the right office "
        f"follow up, and note what they asked."
    )
    return "\n\n".join(lines)


async def handle_case(case_id: int) -> None:
    with Session(engine) as session:
        case = session.get(Case, case_id)
        tenant = load_tenant(case.tenant_id)
        student = directory.lookup(case.student_number) if case.student_number else None
        schema = _schema_for(case.intent)

        task = build_task(case, student, tenant)
        case.run_id = client.dispatch(task=task, phone=case.phone, result_schema=schema)
        case.call_attempts = 1
        case.status = "calling"
        session.add(case)
        session.commit()

    await asyncio.sleep(WAIT_FIRST)

    while True:
        with Session(engine) as session:
            case = session.get(Case, case_id)
            if case is None or case.status in ("resolved", "routed", "failed"):
                return

            result = client.get_result(case.run_id)

            if result.status == "in_progress":
                pass
            elif result.status == "completed":
                structured = result.structured_result or {}
                set_structured_result(case, structured)
                set_transcript(case, result.transcript)
                case.completion_confidence = result.completion_confidence
                case.call_status = "completed"

                tenant = load_tenant(case.tenant_id)
                if structured.get("resolved") is True:
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
                student = directory.lookup(case.student_number) if case.student_number else None
                task = build_task(case, student, tenant)
                case.run_id = client.dispatch(
                    task=task, phone=case.phone, result_schema=_schema_for(case.intent)
                )
                case.call_attempts += 1
                case.status = "calling"
                session.add(case)
                session.commit()
                await asyncio.sleep(WAIT_FIRST)
                continue

        await asyncio.sleep(POLL_INTERVAL)
