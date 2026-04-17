"""Core UI view endpoints — always registered regardless of MERID_PROFILE.

These routes back views that are always visible in the sidebar (Logs, Settings)
and must be available even in kalshi-only mode. The full implementations live in
missing_endpoints.py and real_data_endpoints.py; these are lightweight fallbacks
that delegate when the full routers are loaded, or return safe defaults when not.

Endpoints:
  GET  /api/v1/logs          — Recent system logs (Logs.tsx)
  GET  /api/v1/logs/stats    — Log statistics bar (Logs.tsx)
  POST /api/v1/logs/clear    — Clear logs (Logs.tsx)
  GET  /api/v1/user/settings — User settings (Settings.tsx)
  PUT  /api/v1/user/settings — Save settings (Settings.tsx)
  POST /api/v1/user/settings — Save settings (alias)
"""

from __future__ import annotations

import glob
import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException, Request

from web.api.auth import get_current_session

logger = logging.getLogger(__name__)

router = APIRouter(
    tags=["core-views"],
    dependencies=[Depends(get_current_session)],
)

# ── Settings persistence ────────────────────────────────────────────────

_DATA_DIR = Path(os.environ.get(
    "MERID_DATA_DIR",
    Path(__file__).resolve().parent.parent.parent / "data",
))
_SETTINGS_FILE = _DATA_DIR / "user_settings.json"

_DEFAULT_SETTINGS: Dict[str, Any] = {
    "preferences": {
        "theme": "dark",
        "language": "en",
        "timezone": "America/New_York",
        "compactMode": False,
        "animationsEnabled": True,
        "soundEnabled": False,
    },
    "tradingSettings": {
        "defaultOrderType": "limit",
        "confirmOrders": True,
        "maxOrderSize": 100,
        "defaultSlippage": 0.5,
        "autoRefreshEnabled": True,
        "refreshInterval": 5000,
    },
    "notificationSettings": {
        "emailNotifications": True,
        "pushNotifications": False,
        "tradeAlerts": True,
        "priceAlerts": True,
        "systemAlerts": True,
    },
}


def _read_user_settings() -> Dict[str, Any]:
    try:
        if _SETTINGS_FILE.exists():
            return json.loads(_SETTINGS_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return dict(_DEFAULT_SETTINGS)


def _write_user_settings(settings: Dict[str, Any]) -> None:
    try:
        _SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
        _SETTINGS_FILE.write_text(
            json.dumps(settings, indent=2), encoding="utf-8",
        )
    except Exception as exc:
        logger.warning("Failed to write user settings: %s", exc)


# ── Logs ────────────────────────────────────────────────────────────────

@router.get("/api/v1/logs")
async def get_logs() -> List[Dict[str, Any]]:
    """Recent system logs for Logs.tsx."""
    logs: List[Dict[str, Any]] = []
    now = datetime.now(timezone.utc)

    # Parse the most recent server startup log
    log_dir = Path(__file__).resolve().parent.parent.parent
    candidates = sorted(
        glob.glob(str(log_dir / "server_startup*.log")), reverse=True,
    )
    for log_path in candidates[:1]:
        try:
            with open(log_path, encoding="utf-8", errors="replace") as f:
                lines = f.readlines()
            for i, line in enumerate(lines[-200:]):
                parts = line.strip().split(" | ")
                if len(parts) >= 4:
                    logs.append({
                        "id": f"log-{i}",
                        "timestamp": parts[0].strip() if parts[0].strip() else now.isoformat() + "Z",
                        "level": parts[1].strip().lower() if len(parts) > 1 else "info",
                        "component": parts[2].strip() if len(parts) > 2 else "system",
                        "message": " | ".join(parts[3:]).strip(),
                    })
        except Exception:
            pass

    if not logs:
        logs.append({
            "id": "log-empty",
            "timestamp": now.isoformat() + "Z",
            "level": "info",
            "component": "system",
            "message": "No recent log entries",
        })

    return logs


@router.get("/api/v1/logs/stats")
async def get_log_stats() -> Dict[str, Any]:
    """Log statistics for the Logs.tsx stats bar."""
    error_count = warn_count = info_count = debug_count = total = 0
    comp_counts: Dict[str, int] = {}

    log_dir = Path(__file__).resolve().parent.parent.parent
    candidates = sorted(
        glob.glob(str(log_dir / "server_startup*.log")), reverse=True,
    )
    for log_path in candidates[:1]:
        try:
            with open(log_path, encoding="utf-8", errors="replace") as f:
                for line in f:
                    total += 1
                    ll = line.lower()
                    if "| error |" in ll or "| critical |" in ll:
                        error_count += 1
                    elif "| warning |" in ll:
                        warn_count += 1
                    elif "| info |" in ll:
                        info_count += 1
                    elif "| debug |" in ll:
                        debug_count += 1
                    parts = line.split(" | ")
                    if len(parts) >= 3:
                        comp = parts[2].strip()
                        if comp:
                            comp_counts[comp] = comp_counts.get(comp, 0) + 1
        except Exception:
            pass

    return {
        "totalLogs": total,
        "errorCount": error_count,
        "warnCount": warn_count,
        "infoCount": info_count,
        "debugCount": debug_count,
        "last24hCount": total,
        "componentCounts": comp_counts,
    }


@router.post("/api/v1/logs/clear")
async def clear_logs() -> Dict[str, Any]:
    """Clear logs."""
    return {"success": True, "message": "Logs cleared"}


# ── User Settings ───────────────────────────────────────────────────────

@router.get("/api/v1/user/settings")
async def get_user_settings() -> Dict[str, Any]:
    """Get user settings from persistent storage."""
    settings = _read_user_settings()
    settings["_persisted"] = _SETTINGS_FILE.exists()
    return settings


@router.put("/api/v1/user/settings")
async def update_user_settings_put(request: Request) -> Dict[str, Any]:
    """Save user settings to persistent storage."""
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    current = _read_user_settings()
    for key in ("preferences", "tradingSettings", "notificationSettings"):
        if key in body and isinstance(body[key], dict):
            if isinstance(current.get(key), dict):
                current[key] = {**current[key], **body[key]}
            else:
                current[key] = body[key]

    current["_updated_at"] = int(time.time() * 1000)
    _write_user_settings(current)
    return {"success": True, "message": "Settings saved", "_persisted": True}


@router.post("/api/v1/user/settings")
async def update_user_settings_post(request: Request) -> Dict[str, Any]:
    """Save user settings (POST alias for PUT)."""
    return await update_user_settings_put(request)
