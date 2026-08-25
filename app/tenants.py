import json
from functools import lru_cache
from pathlib import Path

TENANTS_ROOT = Path(__file__).resolve().parent.parent / "tenants"


@lru_cache
def load_tenant(tenant_id: str) -> dict:
    path = TENANTS_ROOT / f"{tenant_id}.json"
    return json.loads(path.read_text(encoding="utf-8"))
