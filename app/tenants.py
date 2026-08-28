import json
from functools import lru_cache
from pathlib import Path

TENANTS_ROOT = Path(__file__).resolve().parent.parent / "tenants"

# tenants/nust.json's short_name and agent_intro deliberately write "Nust"
# in mixed case, not "NUST". This text is read aloud by CALL-E's TTS - an
# all-caps short token gets spelled out letter by letter as an acronym
# ("N. U. S. T.") rather than pronounced as a word. Mixed case reads as an
# ordinary word instead. Don't "fix" the capitalization back to NUST; JSON
# has no comment syntax, hence this note living here instead.


@lru_cache
def load_tenant(tenant_id: str) -> dict:
    path = TENANTS_ROOT / f"{tenant_id}.json"
    return json.loads(path.read_text(encoding="utf-8"))
