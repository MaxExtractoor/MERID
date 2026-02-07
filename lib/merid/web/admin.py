"""Admin endpoints for MERID (lockdown control)."""

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from typing import List

from core.lockdown import set_lockdown, is_lockdown
from web.auth import require_admin
from db.audit_store import append_audit, list_audit

router = APIRouter(prefix="/admin", tags=["admin"])


class LockdownPayload(BaseModel):
    lock: bool


@router.post("/lockdown", status_code=204)
def post_lockdown(payload: LockdownPayload, actor: str = Depends(require_admin)):
    set_lockdown(payload.lock)
    append_audit(actor, "lockdown.set", {"lock": payload.lock})
    return None


@router.get("/lockdown")
def get_lockdown():
    return {"lockdown": is_lockdown()}


class AuditPostPayload(BaseModel):
    action: str
    details: dict | None = None


@router.post("/audit", status_code=201)
def post_audit(payload: AuditPostPayload, actor: str = Depends(require_admin)):
    entry = append_audit(actor, payload.action, payload.details)
    return entry


@router.get("/audit")
def get_audit(limit: int = Query(100, ge=1, le=1000), offset: int = 0) -> List[dict]:
    return list_audit(limit=limit, offset=offset)
