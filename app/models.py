import json
from datetime import datetime
from typing import Optional

from sqlmodel import Field, SQLModel, create_engine

DB_URL = "sqlite:///./ringback.db"
engine = create_engine(DB_URL, connect_args={"check_same_thread": False})


class Case(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    tenant_id: str = "nust"
    student_number: Optional[str] = None
    phone: str
    original_query: str
    created_at: datetime = Field(default_factory=datetime.utcnow)

    intent: Optional[str] = None
    intent_confidence: Optional[float] = None
    category: Optional[str] = None

    status: str = "received"  # received | classified | calling | resolved | routed | failed
    call_attempts: int = 0
    run_id: Optional[str] = None
    call_status: Optional[str] = None

    structured_result_json: Optional[str] = None
    transcript_json: Optional[str] = None
    completion_confidence: Optional[float] = None

    routed_office: Optional[str] = None
    routed_contact: Optional[str] = None
    routed_reason: Optional[str] = None

    retrieved_sources_json: Optional[str] = None
    no_kb_coverage: Optional[bool] = None


def get_structured_result(case: Case) -> Optional[dict]:
    return json.loads(case.structured_result_json) if case.structured_result_json else None


def set_structured_result(case: Case, value: Optional[dict]) -> None:
    case.structured_result_json = json.dumps(value) if value is not None else None


def get_transcript(case: Case) -> Optional[str]:
    if not case.transcript_json:
        return None
    value = json.loads(case.transcript_json)
    # Defensive against pre-migration rows stored under the old list-of-turns
    # shape: render as text instead of raising, so one old case can't 500 the
    # whole /api/cases list the way it did during today's schema change.
    return value if isinstance(value, str) else json.dumps(value)


def set_transcript(case: Case, value: Optional[str]) -> None:
    case.transcript_json = json.dumps(value) if value is not None else None


def get_retrieved_sources(case: Case) -> Optional[list]:
    return json.loads(case.retrieved_sources_json) if case.retrieved_sources_json else None


def set_retrieved_sources(case: Case, value: Optional[list]) -> None:
    case.retrieved_sources_json = json.dumps(value) if value else None


def init_db() -> None:
    SQLModel.metadata.create_all(engine)
