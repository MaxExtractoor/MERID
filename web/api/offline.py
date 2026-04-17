"""
Offline Mode API Endpoints.

Provides API access to offline/air-gapped operation features.
"""

from __future__ import annotations

from typing import Dict, Any, List, Optional

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from pydantic import BaseModel

from offline import (
    get_local_data_cache,
    get_replay_engine,
    get_data_importer,
    get_qr_transfer,
    get_offline_mode_manager,
)
from offline.data_cache import CacheType
from offline.replay_engine import ReplaySpeed
from offline.data_import import ImportFormat
from offline.offline_mode import OperationMode
from offline.qr_transfer import SignedIntent
from web.api.auth import get_current_session
from utils.logger import get_logger

router = APIRouter(prefix="/api/v1/offline", tags=["offline"], dependencies=[Depends(get_current_session)]  # ZT6-01
)
logger = get_logger("web.api.offline")


# ============================================
# REQUEST MODELS
# ============================================

class CacheDataRequest(BaseModel):
    cache_type: str
    key: str
    data: Dict[str, Any]
    ttl_seconds: Optional[float] = None


class ReplaySessionRequest(BaseModel):
    start_time: float
    end_time: float
    speed: float = 1.0


class ImportJobRequest(BaseModel):
    source_path: str
    import_format: str


class SignedIntentRequest(BaseModel):
    intent_id: str
    intent_type: str
    symbol: str = ""
    side: str = ""
    quantity: float = 0.0
    price: Optional[float] = None
    max_slippage_pct: float = 1.0
    expires_at: float = 0.0
    signer_address: str = ""
    signature: str = ""


class QueueIntentRequest(BaseModel):
    intent_type: str
    symbol: str
    side: str
    quantity: float
    price: Optional[float] = None


# ============================================
# OFFLINE MODE ENDPOINTS
# ============================================

@router.get("/status")
async def get_offline_status() -> Dict[str, Any]:
    """Get comprehensive offline mode status."""
    return get_offline_mode_manager().get_status()


@router.get("/state")
async def get_offline_state() -> Dict[str, Any]:
    """Get current offline state."""
    return get_offline_mode_manager().get_state()


@router.post("/start")
async def start_offline_manager(background_tasks: BackgroundTasks) -> Dict[str, Any]:
    """Start offline mode manager."""
    manager = get_offline_mode_manager()
    background_tasks.add_task(manager.start)
    return {"status": "starting"}


@router.post("/stop")
async def stop_offline_manager() -> Dict[str, Any]:
    """Stop offline mode manager."""
    await get_offline_mode_manager().stop()
    return {"status": "stopped"}


@router.post("/mode/{mode}")
async def switch_mode(mode: str) -> Dict[str, Any]:
    """Switch operation mode."""
    try:
        op_mode = OperationMode(mode)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid mode: {mode}")
    
    success = await get_offline_mode_manager().switch_mode(op_mode)
    if success:
        return {"status": "switched", "mode": mode}
    raise HTTPException(status_code=400, detail="Mode switch failed")


@router.post("/force-offline")
async def force_offline() -> Dict[str, Any]:
    """Force offline mode."""
    get_offline_mode_manager().force_offline()
    return {"status": "forced_offline"}


@router.post("/force-online")
async def force_online() -> Dict[str, Any]:
    """Force online mode."""
    get_offline_mode_manager().force_online()
    return {"status": "forced_online"}


@router.post("/auto-switch/{enabled}")
async def set_auto_switch(enabled: bool) -> Dict[str, Any]:
    """Enable/disable automatic mode switching."""
    get_offline_mode_manager().set_auto_switch(enabled)
    return {"status": "updated", "auto_switch": enabled}


# ============================================
# CACHE ENDPOINTS
# ============================================

@router.get("/cache/status")
async def get_cache_status() -> Dict[str, Any]:
    """Get cache statistics."""
    return get_local_data_cache().get_stats()


@router.post("/cache/set")
async def cache_data(request: CacheDataRequest) -> Dict[str, Any]:
    """Set a cache entry."""
    try:
        cache_type = CacheType(request.cache_type)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid cache type: {request.cache_type}")
    
    cache_id = get_local_data_cache().set(
        cache_type,
        request.key,
        request.data,
        request.ttl_seconds,
    )
    return {"status": "cached", "cache_id": cache_id}


@router.get("/cache/get/{cache_type}/{key}")
async def get_cached_data(cache_type: str, key: str) -> Dict[str, Any]:
    """Get a cache entry."""
    try:
        ct = CacheType(cache_type)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid cache type: {cache_type}")
    
    data = get_local_data_cache().get(ct, key)
    if data is not None:
        return {"found": True, "data": data}
    return {"found": False}


@router.delete("/cache/{cache_type}/{key}")
async def delete_cached_data(cache_type: str, key: str) -> Dict[str, Any]:
    """Delete a cache entry."""
    try:
        ct = CacheType(cache_type)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid cache type: {cache_type}")
    
    get_local_data_cache().delete(ct, key)
    return {"status": "deleted"}


@router.post("/cache/clear-expired")
async def clear_expired_cache() -> Dict[str, Any]:
    """Clear expired cache entries."""
    count = get_local_data_cache().clear_expired()
    return {"status": "cleared", "expired_count": count}


@router.post("/cache/clear-all")
async def clear_all_cache() -> Dict[str, Any]:
    """Clear all cache data."""
    get_local_data_cache().clear_all()
    return {"status": "cleared"}


@router.get("/cache/prices/{symbol}")
async def get_cached_prices(symbol: str, limit: int = 100) -> Dict[str, Any]:
    """Get cached prices for a symbol."""
    prices = get_local_data_cache().get_cached_prices(symbol, limit)
    return {"count": len(prices), "prices": prices}


@router.get("/cache/ohlcv/{symbol}/{timeframe}")
async def get_cached_ohlcv(symbol: str, timeframe: str) -> Dict[str, Any]:
    """Get cached OHLCV data."""
    candles = get_local_data_cache().get_cached_ohlcv(symbol, timeframe)
    if candles:
        return {"found": True, "count": len(candles), "candles": candles}
    return {"found": False}


# ============================================
# REPLAY ENDPOINTS
# ============================================

@router.get("/replay/status")
async def get_replay_status() -> Dict[str, Any]:
    """Get replay engine status."""
    return get_replay_engine().get_status()


@router.post("/replay/session")
async def create_replay_session(request: ReplaySessionRequest) -> Dict[str, Any]:
    """Create a replay session."""
    speed = ReplaySpeed.REALTIME
    for s in ReplaySpeed:
        if s.value == request.speed:
            speed = s
            break
    
    session = get_replay_engine().create_session(
        request.start_time,
        request.end_time,
        speed,
    )
    return {"status": "created", "session": session.to_dict()}


@router.post("/replay/{replay_sid}/load")
async def load_replay_session(replay_sid: str) -> Dict[str, Any]:
    """Load events for a replay session."""
    success = await get_replay_engine().load_session(replay_sid)
    if success:
        return {"status": "loaded"}
    raise HTTPException(status_code=400, detail="Load failed")


@router.post("/replay/{replay_sid}/start")
async def start_replay(replay_sid: str) -> Dict[str, Any]:
    """Start replay."""
    success = await get_replay_engine().start(replay_sid)
    if success:
        return {"status": "started"}
    raise HTTPException(status_code=400, detail="Start failed")


@router.post("/replay/{replay_sid}/pause")
async def pause_replay(replay_sid: str) -> Dict[str, Any]:
    """Pause replay."""
    success = get_replay_engine().pause(replay_sid)
    if success:
        return {"status": "paused"}
    raise HTTPException(status_code=404, detail="Session not found")


@router.post("/replay/{replay_sid}/resume")
async def resume_replay(replay_sid: str) -> Dict[str, Any]:
    """Resume replay."""
    success = get_replay_engine().resume(replay_sid)
    if success:
        return {"status": "resumed"}
    raise HTTPException(status_code=404, detail="Session not found")


@router.post("/replay/{replay_sid}/stop")
async def stop_replay(replay_sid: str) -> Dict[str, Any]:
    """Stop replay."""
    success = await get_replay_engine().stop(replay_sid)
    if success:
        return {"status": "stopped"}
    raise HTTPException(status_code=404, detail="Session not found")


@router.post("/replay/{replay_sid}/seek")
async def seek_replay(replay_sid: str, timestamp: float) -> Dict[str, Any]:
    """Seek to timestamp."""
    success = get_replay_engine().seek(replay_sid, timestamp)
    if success:
        return {"status": "seeked", "timestamp": timestamp}
    raise HTTPException(status_code=404, detail="Session not found")


@router.post("/replay/{replay_sid}/speed")
async def set_replay_speed(replay_sid: str, speed: float) -> Dict[str, Any]:
    """Set replay speed."""
    replay_speed = ReplaySpeed.REALTIME
    for s in ReplaySpeed:
        if s.value == speed:
            replay_speed = s
            break
    
    success = get_replay_engine().set_speed(replay_sid, replay_speed)
    if success:
        return {"status": "updated", "speed": speed}
    raise HTTPException(status_code=404, detail="Session not found")


# ============================================
# IMPORT ENDPOINTS
# ============================================

@router.get("/import/status")
async def get_import_status() -> Dict[str, Any]:
    """Get importer status."""
    return get_data_importer().get_status()


@router.post("/import/job")
async def create_import_job(request: ImportJobRequest) -> Dict[str, Any]:
    """Create an import job."""
    try:
        import_format = ImportFormat(request.import_format)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid format: {request.import_format}")
    
    job = get_data_importer().create_import_job(request.source_path, import_format)
    return {"status": "created", "job": job.to_dict()}


@router.post("/import/{job_id}/run")
async def run_import_job(job_id: str) -> Dict[str, Any]:
    """Run an import job."""
    success = await get_data_importer().run_import(job_id)
    job = get_data_importer().get_job(job_id)
    
    if success:
        return {"status": "completed", "job": job.to_dict() if job else None}
    return {"status": "failed", "job": job.to_dict() if job else None}


@router.get("/import/{job_id}")
async def get_import_job(job_id: str) -> Dict[str, Any]:
    """Get import job status."""
    job = get_data_importer().get_job(job_id)
    if job:
        return job.to_dict()
    raise HTTPException(status_code=404, detail="Job not found")


@router.get("/import/usb")
async def scan_usb_drives() -> Dict[str, Any]:
    """Scan for USB drives with importable data."""
    drives = get_data_importer().scan_usb_drives()
    return {"count": len(drives), "drives": drives}


@router.get("/import/files")
async def list_importable_files(directory: str) -> Dict[str, Any]:
    """List importable files in a directory."""
    files = get_data_importer().list_importable_files(directory)
    return {"count": len(files), "files": files}


# ============================================
# QR TRANSFER ENDPOINTS
# ============================================

@router.get("/qr/status")
async def get_qr_status() -> Dict[str, Any]:
    """Get QR transfer status."""
    return get_qr_transfer().get_status()


@router.post("/qr/generate/intent")
async def generate_intent_qr(request: SignedIntentRequest) -> Dict[str, Any]:
    """Generate QR code for a signed intent."""
    intent = SignedIntent(
        intent_id=request.intent_id,
        intent_type=request.intent_type,
        symbol=request.symbol,
        side=request.side,
        quantity=request.quantity,
        price=request.price,
        max_slippage_pct=request.max_slippage_pct,
        expires_at=request.expires_at,
        signer_address=request.signer_address,
        signature=request.signature,
    )
    
    qr_codes = get_qr_transfer().generate_intent_qr(intent)
    return {
        "status": "generated",
        "qr_count": len(qr_codes),
        "qr_codes": qr_codes,
    }


@router.post("/qr/scan")
async def scan_qr_code(qr_data: str) -> Dict[str, Any]:
    """Process scanned QR code."""
    result = get_qr_transfer().scan_qr(qr_data)
    if result:
        return result
    raise HTTPException(status_code=400, detail="Invalid QR code")


@router.get("/qr/pending")
async def get_pending_transfers() -> Dict[str, Any]:
    """Get pending QR transfers."""
    transfers = get_qr_transfer().get_pending_transfers()
    return {"count": len(transfers), "transfers": transfers}


@router.get("/qr/received")
async def get_received_transfers() -> Dict[str, Any]:
    """Get received QR transfers."""
    transfers = get_qr_transfer().get_received_transfers()
    return {"count": len(transfers), "transfers": transfers}


@router.post("/qr/clear-expired")
async def clear_expired_transfers() -> Dict[str, Any]:
    """Clear expired QR transfers."""
    count = get_qr_transfer().clear_expired()
    return {"status": "cleared", "expired_count": count}


# ============================================
# INTENT QUEUE ENDPOINTS
# ============================================

@router.post("/queue/intent")
async def queue_intent(request: QueueIntentRequest) -> Dict[str, Any]:
    """Queue an intent for later execution."""
    intent = {
        "intent_type": request.intent_type,
        "symbol": request.symbol,
        "side": request.side,
        "quantity": request.quantity,
        "price": request.price,
    }
    
    intent_id = get_offline_mode_manager().queue_intent(intent)
    return {"status": "queued", "intent_id": intent_id}


@router.get("/queue/intents")
async def get_queued_intents() -> Dict[str, Any]:
    """Get queued intents."""
    intents = get_offline_mode_manager().get_pending_intents()
    return {"count": len(intents), "intents": intents}


@router.get("/queue/executions")
async def get_queued_executions() -> Dict[str, Any]:
    """Get queued executions."""
    executions = get_offline_mode_manager().get_pending_executions()
    return {"count": len(executions), "executions": executions}
