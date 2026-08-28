import logging
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from dotenv import load_dotenv

# Must run before `from . import dispatcher` - dispatcher.py builds its
# module-level CalleClient() at import time, reading CALLE_API_KEY from
# os.environ once. Loading .env any later would silently leave that client
# on the mock transport for the process's whole lifetime.
load_dotenv()

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlmodel import Session, select

from . import dispatcher
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
from .tenants import TENANTS_ROOT

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")

directory = JSONDirectory()


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    for tenant_file in TENANTS_ROOT.glob("*.json"):
        get_retriever(tenant_file.stem)
    yield


app = FastAPI(title="Ringback", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
)


def get_session():
    with Session(engine) as session:
        yield session


class IntakeRequest(BaseModel):
    phone: str
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
    if not payload.query.strip():
        raise HTTPException(400, "Question cannot be empty.")
    if not payload.caller_name.strip():
        raise HTTPException(400, "Please tell us your name.")

    student = directory.lookup(payload.student_number) if payload.student_number else None
    if payload.student_number and student is None:
        raise HTTPException(
            404, "We couldn't find that student number. Leave it blank if you're not sure."
        )

    case = Case(
        tenant_id=payload.tenant_id,
        student_number=payload.student_number,
        caller_name=payload.caller_name.strip(),
        phone=payload.phone,
        original_query=payload.query.strip(),
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


WEB_DIST = Path(__file__).resolve().parent.parent / "web" / "dist"
if WEB_DIST.exists():
    app.mount("/assets", StaticFiles(directory=WEB_DIST / "assets"), name="assets")

    @app.get("/{full_path:path}")
    def serve_frontend(full_path: str):
        candidate = WEB_DIST / full_path
        if candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(WEB_DIST / "index.html")
