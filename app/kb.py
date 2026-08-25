from pathlib import Path
from typing import Optional

KB_ROOT = Path(__file__).resolve().parent.parent / "kb"

TOPIC_BY_INTENT = {
    "proof_of_registration": "proof-of-registration",
    "subject_cancellation": "subject-cancellation",
}
TOPIC_BY_CATEGORY = {
    "fees": "fees-and-payment",
    "academic_records": "academic-calendar",
    "exams": "academic-calendar",
}


class KnowledgeBase:
    def __init__(self, tenant_id: str = "nust"):
        folder = KB_ROOT / tenant_id
        self._files = (
            {p.stem: p.read_text(encoding="utf-8") for p in folder.glob("*.md")}
            if folder.exists()
            else {}
        )

    def select(self, intent: str, category: Optional[str] = None) -> Optional[str]:
        topic = TOPIC_BY_INTENT.get(intent) or TOPIC_BY_CATEGORY.get(category or "")
        return self._files.get(topic) if topic else None
