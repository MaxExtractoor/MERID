from __future__ import annotations

# Stage 2 State: shared UI ticker, user connections, and personalization filters.

import asyncio
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Deque, Dict, List, Optional

from core.time_authority import current_time


@dataclass
class TopPick:
    energy_id: str
    payload: str
    consensus: float
    approved_at: str
    source: str
    curator: List[str] = field(default_factory=list)


class MeridState:
    """Thread-safe, in-memory state for UI hydration and automation hooks."""

    def __init__(self, max_top_picks: int = 20) -> None:
        self._top_picks: Deque[TopPick] = deque(maxlen=max_top_picks)
        self._connections: Dict[str, Dict[str, str]] = {}
        self._user_filters: Dict[str, Dict[str, str]] = {}
        self._validation_results: Dict[str, Dict[str, Any]] = {}
        self._validation_feed: Deque[Dict[str, Any]] = deque(maxlen=50)
        self._audit_feed: Deque[Dict[str, Any]] = deque(maxlen=50)
        self._automation_feed: Deque[Dict[str, Any]] = deque(maxlen=50)
        self._lock = asyncio.Lock()

        self._help_sections: List[Dict[str, str]] = [
            {
                "title": "Getting Started",
                "body": "Submit a signal with clear context. MERID will research, debate, and stream consensus live.",
            },
            {
                "title": "Voice Commands",
                "body": "Tap the mic and say things like 'scan Polymarket again' or 'connect my wallet'.",
            },
            {
                "title": "Automation Agent",
                "body": "Queue trusted workstation actions (e.g., open dashboards, tail logs) via the Automation panel.",
            },
        ]

        self._legal_block = (
            "© MERID — All Rights Reserved. Nothing herein is financial advice. "
            "Signals are experimental consensus intelligence. Verify independently."
        )

    async def record_top_pick(
        self,
        *,
        energy_id: str,
        payload: str,
        consensus: float,
        source: str,
        curator: Optional[List[str]] = None,
    ) -> None:
        async with self._lock:
            self._top_picks.appendleft(
                TopPick(
                    energy_id=energy_id,
                    payload=payload,
                    consensus=consensus,
                    approved_at=current_time()["utc_iso"],
                    source=source,
                    curator=curator or [],
                )
            )

    async def get_top_picks(self) -> List[Dict[str, str]]:
        async with self._lock:
            return [
                {
                    "energy_id": pick.energy_id,
                    "payload": pick.payload,
                    "consensus": f"{pick.consensus:.1%}",
                    "approved_at": pick.approved_at,
                    "source": pick.source,
                    "curator": pick.curator,
                }
                for pick in list(self._top_picks)
            ]

    async def record_validation(
        self,
        energy: Dict[str, Any],
        verdict: Dict[str, Any],
        vote_result: Dict[str, Any],
    ) -> None:
        energy_id = energy["energy_id"]
        async with self._lock:
            entry = {
                "energy_id": energy_id,
                "energy": {
                    "payload": energy.get("payload", ""),
                    "source": energy.get("source"),
                    "metadata": energy.get("metadata", {}),
                },
                "verdict": verdict,
                "vote_result": vote_result,
                "recorded_at": current_time()["utc_iso"],
            }
            self._validation_results[energy_id] = entry
            self._validation_feed.appendleft(entry)

    async def get_validation(self, energy_id: str) -> Dict[str, Any]:
        async with self._lock:
            return self._validation_results.get(energy_id, {})

    async def list_validations(self, limit: int = 20) -> List[Dict[str, Any]]:
        async with self._lock:
            entries = list(self._validation_feed)
        return entries[:limit]

    async def record_audit(self, report: Dict[str, Any]) -> None:
        async with self._lock:
            self._audit_feed.appendleft(
                {
                    "report": report,
                    "recorded_at": current_time()["utc_iso"],
                }
            )

    async def list_audits(self, limit: int = 20) -> List[Dict[str, Any]]:
        async with self._lock:
            return list(self._audit_feed)[:limit]

    async def record_automation_event(
        self,
        *,
        channel: str,
        status: str,
        message: str,
        energy_id: str | None = None,
    ) -> None:
        async with self._lock:
            self._automation_feed.appendleft(
                {
                    "channel": channel,
                    "status": status,
                    "message": message,
                    "energy_id": energy_id,
                    "recorded_at": current_time()["utc_iso"],
                }
            )

    async def list_automation_events(self, limit: int = 30) -> List[Dict[str, Any]]:
        async with self._lock:
            return list(self._automation_feed)[:limit]

    async def register_connection(
        self,
        user_handle: str,
        *,
        x_handle: Optional[str] = None,
        telegram_handle: Optional[str] = None,
        wallet_address: Optional[str] = None,
        email: Optional[str] = None,
        verification: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "x_handle": x_handle,
            "telegram_handle": telegram_handle,
            "wallet_address": wallet_address,
            "email": email,
            "updated_at": current_time()["utc_iso"],
        }
        if verification:
            payload["verification"] = verification
        async with self._lock:
            self._connections[user_handle] = payload
        return payload

    async def get_connections(self, user_handle: Optional[str] = None) -> Dict[str, Dict[str, Any]]:
        async with self._lock:
            if user_handle:
                return {user_handle: self._connections.get(user_handle, {})}
            return dict(self._connections)

    async def set_filters(self, user_handle: str, filters: Dict[str, str]) -> None:
        async with self._lock:
            self._user_filters[user_handle] = filters

    async def get_filters(self, user_handle: str) -> Dict[str, str]:
        async with self._lock:
            return self._user_filters.get(user_handle, {})

    def help_sections(self) -> List[Dict[str, str]]:
        return list(self._help_sections)

    def legal_notice(self) -> str:
        return self._legal_block


state = MeridState()
