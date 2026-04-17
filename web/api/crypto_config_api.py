"""Effective crypto threshold matrix API."""

from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Depends

from web.api.auth import get_current_session
from utils.logger import get_logger

router = APIRouter(prefix="/api/v1/config", tags=["config"], dependencies=[Depends(get_current_session)])
logger = get_logger("web.api.crypto_config")


@router.get("/crypto-matrix")
def get_crypto_matrix_effective() -> Dict[str, Any]:
    """Return merged ``crypto_threshold_matrix.yaml`` + per-grid-agent resolved rows."""
    from merid.prediction.crypto_threshold_matrix import effective_matrix_payload

    return effective_matrix_payload()
