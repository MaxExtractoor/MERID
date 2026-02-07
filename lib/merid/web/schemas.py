from __future__ import annotations

from typing import Literal, Optional
from pydantic import BaseModel, constr


class SubmitRequest(BaseModel):
    source: constr(min_length=1)
    payload: constr(min_length=1)


class MeridUpdate(BaseModel):
    status: Literal["started", "processing", "done"]
    # Optional fields depending on status
    energy: Optional[dict] = None
    progress: Optional[int] = None
    result: Optional[dict] = None


class AuditEntry(BaseModel):
    id: int
    timestamp: int
    actor: Optional[str] = None
    action: str
    details: Optional[dict] = None
