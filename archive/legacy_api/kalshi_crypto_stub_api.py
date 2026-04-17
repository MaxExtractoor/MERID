"""Stub Kalshi crypto signals router used when consensus module is unavailable."""
from fastapi import APIRouter, HTTPException

router = APIRouter(
    prefix="/api/v1/kalshi-grid/crypto",
    tags=["Kalshi Crypto Signals"])

_UNAVAILABLE_DETAIL = {
    "detail": "crypto signals temporarily unavailable; consensus module missing",
}


def _raise_unavailable():
    raise HTTPException(status_code=503, detail=_UNAVAILABLE_DETAIL["detail"])


@router.get("/edge")
async def get_crypto_edge_stub():
    _raise_unavailable()


@router.get("/consensus")
async def get_crypto_consensus_stub():
    _raise_unavailable()


@router.get("/rti")
async def get_crypto_rti_stub():
    """Stub RTI endpoint — returns empty data structure for useKalshiCryptoRti."""
    return {"data": {}, "timestamp": 0, "source": "stub", "error": "RTI data unavailable"}


@router.get("/paper-vs-shadow")
async def get_paper_vs_shadow_stub():
    """Stub paper-vs-shadow comparison for useKalshiPaperVsShadow."""
    return {"comparison": {}, "paper_summary": {}, "error": "paper portfolio module unavailable"}
