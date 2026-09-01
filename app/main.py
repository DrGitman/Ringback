import logging
import os
import time
from contextlib import asynccontextmanager
from datetime import datetime
from typing import List, Optional

from dotenv import load_dotenv

# Must run before `from . import dispatcher` - dispatcher.py builds its
# module-level CalleClient() at import time, reading CALLE_API_KEY from
# os.environ once. Loading .env any later would silently leave that client
# on the mock transport for the process's whole lifetime.
load_dotenv()

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlmodel import Session, select

from . import dispatcher
from .countries import country_by_code, load_countries
from .directory import SqlDirectory
from .models import (
    Case,
    engine,
    get_retrieved_sources,
    get_structured_result,
    get_transcript,
    init_db,
)
from .retrieval import get_retriever
from .tenants import TENANTS_ROOT, load_tenant

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
logger = logging.getLogger(__name__)

directory = SqlDirectory()

_STARTUP_STATE = {"started_at": None, "index_build_seconds": None}


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()

    index_start = time.monotonic()
    for tenant_file in TENANTS_ROOT.glob("*.json"):
        get_retriever(tenant_file.stem)
    _STARTUP_STATE["index_build_seconds"] = round(time.monotonic() - index_start, 3)
    _STARTUP_STATE["started_at"] = datetime.utcnow()

    # Resume polling for any case a prior process left "calling" - a Render
    # free-tier spin-down or a plain restart must not strand a real call
    # nobody's listening for the result of anymore.
    with Session(engine) as session:
        stuck = session.exec(select(Case).where(Case.status == "calling")).all()
        stuck_ids = [c.id for c in stuck]
    for case_id in stuck_ids:
        import asyncio

        asyncio.create_task(dispatcher.resume_case(case_id))
    if stuck_ids:
        logger.info("main: resuming polling for %d case(s) left calling: %s", len(stuck_ids), stuck_ids)

    yield


app = FastAPI(title="Ringback", lifespan=lifespan)

# ALLOWED_ORIGINS is a comma-separated list - deliberately not "*", since a
# real deployment has real cookies/headers worth restricting to known
# origins. max_age caches the preflight so the dashboard's 2-second poll
# doesn't trigger a fresh OPTIONS request on every single call.
_allowed_origins = [
    o.strip()
    for o in os.environ.get("ALLOWED_ORIGINS", "http://localhost:5173").split(",")
    if o.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_methods=["*"],
    allow_headers=["*"],
    max_age=600,
)


@app.get("/health")
def health():
    """Bare 200, nothing else - a keep-alive target for an uptime monitor,
    not a diagnostic. No DB call, no retriever call, no logic, so it can't
    itself become the thing that's slow or broken.
    """
    return {"ok": True}


@app.get("/status")
def status(session: Session = Depends(lambda: Session(engine))):
    """The actual diagnostic endpoint - checks the things /health
    deliberately doesn't: DB reachability, retriever load state, chunk
    count, how long the index took to build at startup.
    """
    db_ok = True
    try:
        session.exec(select(Case).limit(1)).first()
    except Exception:
        db_ok = False
    finally:
        session.close()

    tenant_ids = [f.stem for f in TENANTS_ROOT.glob("*.json")]
    retrievers = {}
    for tenant_id in tenant_ids:
        r = get_retriever(tenant_id)
        retrievers[tenant_id] = len(r.chunks)

    return {
        "db_reachable": db_ok,
        "tenants": retrievers,
        "index_build_seconds": _STARTUP_STATE["index_build_seconds"],
        "started_at": _STARTUP_STATE["started_at"],
    }


def get_session():
    with Session(engine) as session:
        yield session


class IntakeRequest(BaseModel):
    phone: str
    country_code: str = "NA"  # ISO alpha-2 - defaults to the reference deployment
    query: str
    caller_name: str
    student_number: Optional[str] = None
    tenant_id: str = "nust"


class CaseOut(BaseModel):
    id: int
    tenant_id: str
    student_number: Optional[str]
    student_name: Optional[str]
    caller_name: Optional[str]
    phone: str
    country_code: str
    original_query: str
    created_at: datetime
    intent: Optional[str]
    category: Optional[str]
    reasoning: Optional[str]
    plan_confidence: Optional[str]
    preparer_used: Optional[str]
    should_call: Optional[bool]
    status: str
    call_attempts: int
    call_status: Optional[str]
    structured_result: Optional[dict]
    transcript: Optional[str]
    completion_confidence: Optional[float]
    channel: Optional[str]
    channel_reason: Optional[str]
    routed_office: Optional[str]
    routed_contact: Optional[str]
    routed_reason: Optional[str]
    retrieved_sources: Optional[list]
    no_kb_coverage: Optional[bool]

    @classmethod
    def from_case(cls, case: Case) -> "CaseOut":
        student = directory.lookup(case.student_number) if case.student_number else None
        return cls(
            id=case.id,
            tenant_id=case.tenant_id,
            student_number=case.student_number,
            student_name=student.name if student else None,
            caller_name=case.caller_name,
            phone=case.phone,
            country_code=case.country_code,
            original_query=case.original_query,
            created_at=case.created_at,
            intent=case.intent,
            category=case.category,
            reasoning=case.reasoning,
            plan_confidence=case.plan_confidence,
            preparer_used=case.preparer_used,
            should_call=case.should_call,
            status=case.status,
            call_attempts=case.call_attempts,
            call_status=case.call_status,
            structured_result=get_structured_result(case),
            transcript=get_transcript(case),
            completion_confidence=case.completion_confidence,
            channel=case.channel,
            channel_reason=case.channel_reason,
            routed_office=case.routed_office,
            routed_contact=case.routed_contact,
            routed_reason=case.routed_reason,
            retrieved_sources=get_retrieved_sources(case),
            no_kb_coverage=case.no_kb_coverage,
        )


@app.post("/api/cases", response_model=CaseOut)
def create_case(
    payload: IntakeRequest,
    background_tasks: BackgroundTasks,
    session: Session = Depends(get_session),
):
    if not payload.phone.startswith("+"):
        raise HTTPException(
            400, "Phone number must be in international format, e.g. +264811234567."
        )
    try:
        country_by_code(payload.country_code)
    except KeyError:
        raise HTTPException(400, f"Unknown country code: {payload.country_code!r}.")
    if not payload.query.strip():
        raise HTTPException(400, "Question cannot be empty.")
    if not payload.caller_name.strip():
        raise HTTPException(400, "Please tell us your name.")

    student = directory.lookup(payload.student_number) if payload.student_number else None
    if payload.student_number and student is None:
        raise HTTPException(
            404, "We couldn't find that student number. Leave it blank if you're not sure."
        )

    normalized_query = payload.query.strip()

    # Same caller, same exact question, still in flight (not resolved/
    # routed/failed) - reuse it instead of dispatching a second call for
    # what's almost certainly the same double-click or resubmit-after-
    # reload, not a genuinely new request. A case that's already reached a
    # terminal status is fair game for a fresh one - asking the same
    # question again after being helped is a new request, not a duplicate.
    existing = session.exec(
        select(Case).where(
            Case.tenant_id == payload.tenant_id,
            Case.phone == payload.phone,
            Case.original_query == normalized_query,
            Case.status.not_in(["resolved", "routed", "failed"]),
        )
    ).first()
    if existing:
        return CaseOut.from_case(existing)

    case = Case(
        tenant_id=payload.tenant_id,
        student_number=payload.student_number,
        caller_name=payload.caller_name.strip(),
        phone=payload.phone,
        country_code=payload.country_code,
        original_query=normalized_query,
        status="received",
    )
    session.add(case)
    session.commit()
    session.refresh(case)

    background_tasks.add_task(dispatcher.handle_case, case.id)
    return CaseOut.from_case(case)


@app.get("/api/cases", response_model=List[CaseOut])
def list_cases(tenant_id: str = "nust", session: Session = Depends(get_session)):
    cases = session.exec(
        select(Case).where(Case.tenant_id == tenant_id).order_by(Case.created_at.desc())
    ).all()
    return [CaseOut.from_case(c) for c in cases]


@app.get("/api/cases/{case_id}", response_model=CaseOut)
def get_case(case_id: int, session: Session = Depends(get_session)):
    case = session.get(Case, case_id)
    if not case:
        raise HTTPException(404, "Case not found")
    return CaseOut.from_case(case)


@app.get("/api/countries")
def list_countries():
    """Drives the intake form's country dropdown - dial code, CALL-E region/
    locale, and whether the line is local or international, all backend-
    owned (app/data/countries.json) rather than hardcoded in the component,
    since CALL-E has already expanded this list once and will again.
    """
    return load_countries()


@app.get("/api/tenants/{tenant_id}/offices")
def list_offices(tenant_id: str):
    """So the dashboard's manual-route picker can list real office choices
    instead of a hardcoded frontend list - tenant config is backend-owned
    (tenants/*.json), same reasoning as everything else in that file.
    """
    try:
        tenant = load_tenant(tenant_id)
    except FileNotFoundError:
        raise HTTPException(404, "Unknown tenant")
    return tenant["offices"]


_TERMINAL_STATUSES = ("resolved", "routed", "failed")


class RouteRequest(BaseModel):
    office_key: str
    reason: Optional[str] = None


@app.post("/api/cases/{case_id}/route", response_model=CaseOut)
def route_case_manually(
    case_id: int, payload: RouteRequest, session: Session = Depends(get_session)
):
    """Staff-triggered override, distinct from router.route_case() (which
    fires automatically once a completed call comes back unresolved). This
    can happen from any of dashboard, so a case still "calling" can be
    diverted before its call ever completes.

    This does not hang up an in-flight CALL-E call - there's no cancel
    endpoint for that (see calle_client.py). It stops Ringback's own
    tracking of the case: _poll_case()'s loop checks case.status at the top
    of every iteration and returns once it sees "routed", so the background
    poll for this case_id ends on its next tick. A call already ringing may
    still complete on CALL-E's side; its result is simply no longer waited
    on or acted upon here.
    """
    case = session.get(Case, case_id)
    if not case:
        raise HTTPException(404, "Case not found")
    if case.status in _TERMINAL_STATUSES:
        raise HTTPException(409, f"Case is already {case.status}, nothing to route.")

    tenant = load_tenant(case.tenant_id)
    offices = tenant["offices"]
    office = offices.get(payload.office_key)
    if office is None:
        raise HTTPException(400, f"Unknown office '{payload.office_key}' for this tenant.")

    case.routed_office = office["name"]
    case.routed_contact = f"{office['contact']} · {office['email']}"
    case.routed_reason = payload.reason or "Routed to a person by staff."
    case.channel = "route"
    case.channel_reason = case.routed_reason
    case.status = "routed"
    session.add(case)
    session.commit()
    session.refresh(case)
    return CaseOut.from_case(case)


class MarkHandledRequest(BaseModel):
    note: Optional[str] = None


@app.post("/api/cases/{case_id}/mark-handled", response_model=CaseOut)
def mark_case_handled(
    case_id: int, payload: MarkHandledRequest, session: Session = Depends(get_session)
):
    """For a case that exhausted its 3 call attempts with no answer (the
    "manual callback" state) - a staff member who dealt with it some other
    way (a manual phone call, walking over to the person) marks it resolved
    themselves. Deliberately restricted to "failed" - a case still calling
    or already routed has its own path to resolution and shouldn't be
    silently closed out from under it.
    """
    case = session.get(Case, case_id)
    if not case:
        raise HTTPException(404, "Case not found")
    if case.status != "failed":
        raise HTTPException(409, f"Only a failed case can be marked handled (this one is {case.status}).")

    case.status = "resolved"
    case.call_status = payload.note or "Marked resolved manually by staff."
    session.add(case)
    session.commit()
    session.refresh(case)
    return CaseOut.from_case(case)
