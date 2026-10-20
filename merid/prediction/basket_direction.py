"""Shared per-asset directional read for the basket-leader veto.

2026-10-20: the BTC-leader veto (window_quota.quota_basket_leader_side)
only binds when BTC has *emitted* a quota side this window.  When BTC is
silent — its own gates blocked, or a sibling evaluates before BTC's
first emission — siblings fall back to independent direction reads and
can trade AGAINST the basket leader's live signal (the repeat-loss
pattern the veto was built for).

All five 15m agents evaluate in-process each tick (BTC first), so a
module-level registry is the freshest, cheapest channel: each agent
stamps its effective directional read (dir_pref else argmax — the same
inputs the quota lane uses); siblings consult the leader's freshest
read when no emitted record exists.

Precedence (agent_grid_15m quota block):
    emitted record (committed trade, binds the whole window)
        -> live read (uncommitted signal, binds while fresh)
        -> none (independent emission)

The live read carries its own freshness bound
(MERID_BASKET_LEADER_LIVE_MAX_AGE_S, default 90s) — a stale read must
not veto; unlike an emitted record it is not a committed position.
"""

import os
import threading
import time
from typing import Any, Dict, Optional

_REGISTRY: Dict[str, Dict[str, Any]] = {}
_LOCK = threading.Lock()


def record_direction(
    asset: str,
    side: Optional[str],
    *,
    now: Optional[float] = None,
    source: str = "agent",
) -> None:
    """Stamp this asset's effective directional read for siblings.

    ``side`` is ``"yes"``/``"no"`` (dir_pref, else argmax) or None when
    the asset has no directional read — a None entry is still recorded
    so consumers can distinguish "fresh but undirected" from "stale".
    """
    now = time.time() if now is None else float(now)
    a = str(asset or "").upper()
    if not a:
        return
    s = side if side in ("yes", "no") else None
    with _LOCK:
        _REGISTRY[a] = {"ts": now, "side": s, "source": source}


def leader_direction(
    asset: str,
    *,
    leader_asset: Optional[str] = None,
    max_age_s: Optional[float] = None,
    now: Optional[float] = None,
) -> Optional[str]:
    """The basket leader's freshest directional read, or None.

    Returns None when this asset IS the leader, when the leader has no
    read, or when the read is undirected/stale — the veto fails open to
    independence exactly like the emitted-record path.
    """
    a = str(asset or "").upper()
    leader = (
        leader_asset
        if leader_asset is not None
        else os.environ.get("MERID_BASKET_LEADER_ASSET", "BTC")
    ).strip().upper()
    if not a or not leader or a == leader:
        return None
    if max_age_s is None:
        try:
            max_age_s = float(
                os.environ.get("MERID_BASKET_LEADER_LIVE_MAX_AGE_S", "90")
            )
        except (TypeError, ValueError):
            max_age_s = 90.0
    now = time.time() if now is None else float(now)
    with _LOCK:
        rec = _REGISTRY.get(leader)
        if rec is None:
            return None
        ts = float(rec.get("ts") or 0.0)
        side = rec.get("side")
    if max_age_s > 0 and (now - ts) > max_age_s:
        return None
    return side if side in ("yes", "no") else None


def clear() -> None:
    """Test seam."""
    with _LOCK:
        _REGISTRY.clear()
