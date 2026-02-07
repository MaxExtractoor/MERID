from __future__ import annotations

import os
import time
from typing import Dict, List, Optional

from .audit_backend import AuditBackend, FileAuditBackend


# default to in-memory list, but allow a file backend for persistence via
# MERID_AUDIT_FILE environment variable
_store: List[Dict] = []
_backend: Optional[AuditBackend] = None

_audit_file = os.getenv("MERID_AUDIT_FILE")
if _audit_file:
    _backend = FileAuditBackend(_audit_file)


def _next_id() -> int:
    if _backend:
        # count lines in the file
        items = list_audit(limit=1_000_000, offset=0)
        return len(items) + 1
    return len(_store) + 1


def append_audit(actor: Optional[str], action: str, details: Optional[Dict] = None) -> Dict:
    entry = {
        "id": _next_id(),
        "timestamp": int(time.time()),
        "actor": actor,
        "action": action,
        "details": details or {},
    }
    if _backend:
        _backend.append(entry)
    else:
        _store.append(entry)
    return entry


def list_audit(limit: int = 100, offset: int = 0) -> List[Dict]:
    if _backend:
        return list(_backend.list(limit=limit, offset=offset))
    return _store[offset : offset + limit]


def clear_store() -> None:
    global _store
    _store = []
    if _backend:
        _backend.clear()
