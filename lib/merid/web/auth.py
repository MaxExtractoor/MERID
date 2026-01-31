"""Simple token-based admin auth for MERID.

Development-only: validates Authorization header against ADMIN_TOKEN env var.
"""
from __future__ import annotations

import os
from fastapi import HTTPException, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

security = HTTPBearer(auto_error=False)

def _admin_token() -> str:
    return os.getenv("MERID_ADMIN_TOKEN", "local-admin-token")


def require_admin(credentials: HTTPAuthorizationCredentials = Security(security)) -> str:
    if not credentials or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=401, detail="Missing or invalid auth token")
    if credentials.credentials != _admin_token():
        raise HTTPException(status_code=403, detail="Forbidden")

    return credentials.credentials
