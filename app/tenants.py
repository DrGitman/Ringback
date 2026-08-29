import json
from functools import lru_cache
from pathlib import Path

TENANTS_ROOT = Path(__file__).resolve().parent.parent / "tenants"

# tenants/nust.json's short_name and agent_intro deliberately write "Nuhst",
# not "NUST" or "Nust". This text is read aloud by CALL-E's TTS. All-caps
# got spelled out letter by letter as an acronym ("N. U. S. T."). Mixed
# case ("Nust") fixed that but came out with the wrong vowel ("Nist",
# rhyming with "wrist" instead of "must"). "Nuhst" - confirmed against the
# real pronunciation (rhymes with must/dust/trust) - fixed it for real.
# Don't "correct" the spelling back to NUST or Nust; JSON has no comment
# syntax, hence this note living here instead.


@lru_cache
def load_tenant(tenant_id: str) -> dict:
    path = TENANTS_ROOT / f"{tenant_id}.json"
    return json.loads(path.read_text(encoding="utf-8"))
