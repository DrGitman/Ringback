import json
from pathlib import Path
from typing import List, Optional, Protocol

from pydantic import BaseModel

DATA_PATH = Path(__file__).parent / "data" / "students.json"


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


# Future connectors — same interface, so swapping the mock JSON file for a real
# student information system is a new class, not a rewrite:
# class PostgresDirectory(StudentDirectory): ...
# class RESTDirectory(StudentDirectory): ...
