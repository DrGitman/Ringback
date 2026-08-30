import json
from datetime import date as date_
from pathlib import Path
from typing import List, Optional, Protocol

from pydantic import BaseModel
from sqlmodel import Session, select

DATA_PATH = Path(__file__).parent / "data" / "students.json"

# Every N$ amount that reaches a task string or a model prompt goes through
# this, so "2340.0", "N$4100.00", and "850.0" never show up side by side in
# the same call again - one format, applied once, everywhere money is used.
def format_currency(amount: float) -> str:
    return f"N${amount:,.2f}"


class Subject(BaseModel):
    code: str
    name: str
    drop_deadline: str


class Student(BaseModel):
    student_number: str
    name: str
    phone: str
    registration_status: str
    fee_balance: float
    subjects: List[Subject] = []


class StudentDirectory(Protocol):
    def lookup(self, student_number: str) -> Optional[Student]: ...


class JSONDirectory:
    def __init__(self, path: Path = DATA_PATH):
        records = json.loads(path.read_text(encoding="utf-8"))
        self._students = {r["student_number"]: Student(**r) for r in records}

    def lookup(self, student_number: str) -> Optional[Student]:
        return self._students.get(student_number)


# --- Richer record for SqlDirectory -----------------------------------
#
# The seven-table schema (app/models_student.py) carries far more than the
# original mock ever did - applications, per-subject exam/mark detail, fee
# line items, age-analysis buckets, bursaries. StudentRecord extends
# Student rather than replacing it, so every existing .name / .fee_balance
# / .subjects[].drop_deadline access in dispatcher.py and prepare.py keeps
# working unchanged; the new fields are additive, for code that wants them
# (channel-handling logic, a future richer prepare_call() prompt).
#
# disability is deliberately present here (it exists on the table, and a
# caller may legitimately need it looked up for internal routing) but must
# never be written into a task string - that boundary lives entirely in
# build_task(), not in the data model, since the model's job is to make
# the field available, not to police who reads it.


class ApplicationInfo(BaseModel):
    academic_year: Optional[int] = None
    qualification: Optional[str] = None
    description: Optional[str] = None
    academic_preference: Optional[int] = None
    wrs_score: Optional[int] = None
    contract_code: Optional[str] = None
    quote_number: Optional[str] = None
    quote_total: Optional[float] = None
    admission_status: Optional[str] = None
    cancel_date: Optional[date_] = None
    cancel_reason: Optional[str] = None
    faculty: Optional[str] = None
    department: Optional[str] = None


class RegistrationInfo(BaseModel):
    qualification: Optional[str] = None
    registration_year: Optional[int] = None
    academic_block: Optional[str] = None
    offering_type: Optional[str] = None
    period_of_study: Optional[str] = None
    registration_date: Optional[date_] = None
    faculty: Optional[str] = None
    department: Optional[str] = None
    has_bursary: bool = False


class SubjectDetail(BaseModel):
    subject_code: str
    description: Optional[str] = None
    academic_block: Optional[str] = None
    class_group: Optional[str] = None
    prac_group: Optional[str] = None
    tut_group: Optional[str] = None
    attendance: Optional[str] = None
    cancel_date: Optional[date_] = None
    drop_deadline: Optional[date_] = None
    att_proj: Optional[float] = None
    exam_granted: Optional[bool] = None
    exam_month: Optional[str] = None
    final_mark: Optional[float] = None
    result: Optional[str] = None
    withheld_reasons: Optional[str] = None


class FeeLineInfo(BaseModel):
    date: Optional[date_] = None
    reference: Optional[str] = None
    description: Optional[str] = None
    debit: Optional[float] = None
    credit: Optional[float] = None
    balance: Optional[float] = None


class AgeAnalysisInfo(BaseModel):
    days_160: float = 0.0
    days_90: float = 0.0
    days_60: float = 0.0
    days_30: float = 0.0
    current: float = 0.0
    credit: float = 0.0
    future: float = 0.0
    unallocated: float = 0.0
    balance: float = 0.0
    date_of_balance: Optional[date_] = None


class BursaryInfo(BaseModel):
    year: Optional[int] = None
    bursary_code: Optional[str] = None
    description: Optional[str] = None
    is_nsfas: bool = False
    awarded: Optional[float] = None
    allocated: Optional[float] = None
    unallocated: Optional[float] = None


class StudentRecord(Student):
    full_name: str
    gender: Optional[str] = None
    birthdate: Optional[date_] = None
    id_number: Optional[str] = None
    marital_status: Optional[str] = None
    home_language: Optional[str] = None
    citizenship: Optional[str] = None
    email: Optional[str] = None
    postal_address: Optional[str] = None
    study_address: Optional[str] = None
    disability: Optional[str] = None

    applications: List[ApplicationInfo] = []
    registrations: List[RegistrationInfo] = []
    subject_details: List[SubjectDetail] = []
    fee_lines: List[FeeLineInfo] = []
    age_analysis: Optional[AgeAnalysisInfo] = None
    bursaries: List[BursaryInfo] = []


class SqlDirectory:
    """Reads the same student data JSONDirectory used to read from a mock
    JSON file, but from the real (still fictional-data) database tables in
    app/models_student.py. Same StudentDirectory protocol, so nothing that
    calls directory.lookup() needs to know which one it's talking to.
    """

    def __init__(self, engine=None):
        if engine is None:
            from .models import engine as default_engine

            engine = default_engine
        self._engine = engine

    def lookup(self, student_number: str) -> Optional[StudentRecord]:
        from . import models_student as m

        with Session(self._engine) as session:
            row = session.get(m.Student, student_number)
            if row is None:
                return None

            registrations = session.exec(
                select(m.Registration).where(m.Registration.student_number == student_number)
            ).all()
            applications = session.exec(
                select(m.Application).where(m.Application.student_number == student_number)
            ).all()
            subject_rows = session.exec(
                select(m.SubjectEnrolment).where(
                    m.SubjectEnrolment.student_number == student_number
                )
            ).all()
            fee_rows = session.exec(
                select(m.FeeLine).where(m.FeeLine.student_number == student_number)
            ).all()
            age_row = session.exec(
                select(m.AgeAnalysis).where(m.AgeAnalysis.student_number == student_number)
            ).first()
            bursary_rows = session.exec(
                select(m.Bursary).where(m.Bursary.student_number == student_number)
            ).all()

            subjects = [
                Subject(
                    code=s.subject_code,
                    name=s.description or s.subject_code,
                    drop_deadline=str(s.drop_deadline) if s.drop_deadline else "",
                )
                for s in subject_rows
            ]

            return StudentRecord(
                student_number=row.student_number,
                name=row.full_name,
                full_name=row.full_name,
                phone=row.cellphone or "",
                registration_status="registered" if registrations else "not_registered",
                fee_balance=row.current_balance,
                subjects=subjects,
                gender=row.gender,
                birthdate=row.birthdate,
                id_number=row.id_number,
                marital_status=row.marital_status,
                home_language=row.home_language,
                citizenship=row.citizenship,
                email=row.email,
                postal_address=row.postal_address,
                study_address=row.study_address,
                disability=row.disability,
                applications=[ApplicationInfo(**a.model_dump()) for a in applications],
                registrations=[RegistrationInfo(**r.model_dump()) for r in registrations],
                subject_details=[
                    SubjectDetail(**s.model_dump(exclude={"id", "student_number"}))
                    for s in subject_rows
                ],
                fee_lines=[
                    FeeLineInfo(**f.model_dump(exclude={"id", "student_number"}))
                    for f in fee_rows
                ],
                age_analysis=(
                    AgeAnalysisInfo(**age_row.model_dump(exclude={"id", "student_number"}))
                    if age_row
                    else None
                ),
                bursaries=[
                    BursaryInfo(**b.model_dump(exclude={"id", "student_number"}))
                    for b in bursary_rows
                ],
            )


# Future connectors — same interface, so swapping the mock JSON file for a real
# student information system is a new class, not a rewrite:
# class RESTDirectory(StudentDirectory): ...
