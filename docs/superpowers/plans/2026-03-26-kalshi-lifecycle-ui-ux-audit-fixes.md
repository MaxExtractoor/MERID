# Kalshi Lifecycle UI/UX Audit Fixes — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix every gap and dead wire identified in the DISCOVER→ANALYZE→CONSENSUS→SIZE→EXECUTE→MONITOR→PROMOTE→PROTECT lifecycle audit, achieving full transparency between backend risk decisions and the operator UI.

**Architecture:** Backend-first (add endpoints / fix data), then frontend wires to new data. Each task is independently testable. No new abstractions — patch existing modules.

**Tech Stack:** FastAPI (Python 3.11), React + TypeScript + Tailwind, pytest

---

## File Map

### Modified — Backend
| File | Change |
|------|--------|
| `core/execution_gate.py` | Add `checks_downgraded` + `downgrade_mode` fields to `ExecutionGateStatus.to_dict()` |
| `web/api/kalshi_deployment.py` | Add `GET /auto-promoter/history` endpoint |
| `web/api/kalshi_api.py` | Add `GET /ws/subscription-health`, `GET /risk/drawdown-tier`, `GET /risk/category-caps`, `GET /debug/last-trade-sizing` |
| `web/api/swarm_bus_api.py` (or kalshi_grid_api.py) | Expose `disagreement_flags` + `status` in consensus/verdicts response |
| `merid/event_venues/kalshi/order_router.py` | Mark passive-upgrade NOT IMPLEMENTED, remove false stub reference, publish WS alert on order group trigger |
| `merid/event_venues/kalshi/fills_ledger.py` | Expose `null_action_fill_count` in metrics dict |

### Modified — Frontend
| File | Change |
|------|--------|
| `web/react/src/views/KalshiPortfolioView.tsx` | Remove debug fetch calls (lines 84–89, 154–156); add drawdown tier badge |
| `web/react/src/components/GlobalModeBanner.tsx` | Add LENIENT CHECKS badge when gate checks are downgraded |
| `web/react/src/components/SwarmVerdictFeed.tsx` | Show CONFLICTED/STALE rows with disagreement_flags reasons |
| `web/react/src/views/SwarmConsensusMatrix.tsx` | Show shadow stage badge |
| `web/react/src/views/KalshiGridView.tsx` | Show shadow stage badge in cell |
| `web/react/src/config/constants.ts` | Add new endpoint constants |

### New — Backend
| File | Purpose |
|------|---------|
| *(none — all endpoints added to existing routers)* | |

### New — Tests
| File | Covers |
|------|--------|
| `tests/core/test_execution_gate_leniency.py` | Gate leniency flag in to_dict |
| `tests/event_venues/kalshi/test_order_router_passive_stub.py` | Passive upgrade dead wire is documented |
| `tests/web/test_kalshi_drawdown_tier.py` | Drawdown tier endpoint |
| `tests/web/test_kalshi_category_caps.py` | Category caps endpoint |
| `tests/web/test_auto_promoter_history.py` | Promotion history endpoint |

---

## Task 1 — Remove debug agent-log fetch calls (CRITICAL BUG)

**Files:**
- Modify: `web/react/src/views/KalshiPortfolioView.tsx:84-89,154-156`

These are leftover Claude agent debug calls that fire to `http://127.0.0.1:7804/ingest/...` on every render cycle, leaking internal trading state to a local debug endpoint. Must be removed.

- [ ] **Step 1: Remove the reconciliation debug block (lines 84–89)**

Find and remove the entire `useEffect` block:
```tsx
  useEffect(() => {
    // #region agent log (debug-da21e4) H6
    const d = reconciliationResult.data as any;
    fetch('http://127.0.0.1:7804/ingest/f59b577e-2646-4493-af83-a157f274b6b6',{method:'POST',headers:{'Content-Type':'application/json','X-Debug-Session-Id':'da21e4'},body:JSON.stringify({sessionId:'da21e4',runId:'pre-fix',hypothesisId:'H6',location:'KalshiPortfolioView.tsx:reconciliationStatus',message:'Reconciliation status computed',data:{status:reconciliationStatus,hasData:!!reconciliationResult.data,keys:reconciliationResult.data&&typeof reconciliationResult.data==='object'?Object.keys(reconciliationResult.data as object).slice(0,10):null,ledgerTotalFills:d?.ledger?.total_fills??null},timestamp:Date.now()})}).catch(()=>{});
    // #endregion
  }, [reconciliationResult.data, reconciliationStatus]);
```

- [ ] **Step 2: Remove the WS-refetch debug line (inside the debounce useEffect)**

Inside the `wsRefetchTimerRef` useEffect, remove the agent log block:
```tsx
      // #region agent log (debug-da21e4) H4
      fetch('http://127.0.0.1:7804/ingest/f59b577e-2646-4493-af83-a157f274b6b6',{method:'POST',headers:{'Content-Type':'application/json','X-Debug-Session-Id':'da21e4'},body:JSON.stringify({sessionId:'da21e4',runId:'pre-fix',hypothesisId:'H4',location:'KalshiPortfolioView.tsx:wsRefetch',message:'WS-triggered refetch fired',data:{summaryReceivedAt,positionsCount:allPositions.length,ordersCount:allOrders.length},timestamp:Date.now()})}).catch(()=>{});
      // #endregion
```

- [ ] **Step 3: Verify no other debug agent-log fetches exist in the file**

Run: `grep -n "7804/ingest" web/react/src/views/KalshiPortfolioView.tsx`
Expected: no output (zero matches)

- [ ] **Step 4: Grep entire frontend for any other 7804 debug calls**

Run: `grep -rn "7804/ingest" web/react/src/`
Expected: no output

- [ ] **Step 5: Commit**
```bash
git add web/react/src/views/KalshiPortfolioView.tsx
git commit -m "fix(portfolio): remove debug agent-log fetch calls leaking trading state to localhost:7804"
```

---

## Task 2 — Gate leniency transparency: backend field + frontend badge (CRITICAL R1)

**Files:**
- Modify: `core/execution_gate.py`
- Modify: `web/react/src/components/GlobalModeBanner.tsx`
- Modify: `web/react/src/config/constants.ts`
- New test: `tests/core/test_execution_gate_leniency.py`

When `_is_kalshi_demo_mode()` is True, severity checks are downgraded from critical→warning. The frontend must surface this so the operator never sees a false "CLEAR" state.

- [ ] **Step 1: Write the failing test**

Create `tests/core/test_execution_gate_leniency.py`:
```python
"""Tests that gate leniency is surfaced in ExecutionGateStatus.to_dict()."""
import os
import pytest


def test_to_dict_includes_checks_downgraded_false_when_not_demo(monkeypatch):
    monkeypatch.setenv("MERID_PROFILE", "")
    monkeypatch.setenv("KALSHI_USE_DEMO", "false")
    from core.execution_gate import ExecutionGateStatus, GateState
    status = ExecutionGateStatus(blocked=False, safe_to_trade=True, gate_state=GateState.CLEAR.value)
    d = status.to_dict()
    assert "checks_downgraded" in d
    assert d["checks_downgraded"] is False
    assert "downgrade_mode" in d
    assert d["downgrade_mode"] is None


def test_to_dict_includes_checks_downgraded_true_when_demo(monkeypatch):
    monkeypatch.setenv("MERID_PROFILE", "kalshi-only")
    from core.execution_gate import ExecutionGateStatus, GateState
    status = ExecutionGateStatus(
        blocked=False, safe_to_trade=True, gate_state=GateState.CLEAR.value,
        checks_downgraded=True, downgrade_mode="kalshi-only",
    )
    d = status.to_dict()
    assert d["checks_downgraded"] is True
    assert d["downgrade_mode"] == "kalshi-only"


def test_check_execution_gate_sets_downgraded_flag_in_demo_mode(monkeypatch):
    monkeypatch.setenv("MERID_PROFILE", "kalshi-only")
    from core import execution_gate
    # Reload so the env var takes effect
    import importlib
    importlib.reload(execution_gate)
    status = execution_gate.check_execution_gate()
    d = status.to_dict()
    assert d["checks_downgraded"] is True
    assert d["downgrade_mode"] == "kalshi-only"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/core/test_execution_gate_leniency.py -v`
Expected: FAIL — `ExecutionGateStatus` has no `checks_downgraded` field

- [ ] **Step 3: Add `checks_downgraded` and `downgrade_mode` to `ExecutionGateStatus`**

In `core/execution_gate.py`, update the dataclass and `to_dict`:

```python
@dataclass
class ExecutionGateStatus:
    """Snapshot of the execution gate state."""
    blocked: bool
    safe_to_trade: bool
    gate_state: str = GateState.BLOCKED.value  # "clear" | "limited" | "blocked"
    reasons: List[BlockReason] = field(default_factory=list)
    timestamp: float = field(default_factory=time.time)
    # Leniency transparency (R1 fix)
    checks_downgraded: bool = False
    downgrade_mode: Optional[str] = None  # e.g. "kalshi-only" or "demo"

    # ... existing properties unchanged ...

    def to_dict(self) -> dict:
        return {
            "blocked": self.blocked,
            "safe_to_trade": self.safe_to_trade,
            "gate_state": self.gate_state,
            "reasons": [
                {
                    "source": r.source,
                    "severity": r.severity,
                    "message": r.message,
                    "details": r.details,
                    "hint": r.hint,
                }
                for r in self.reasons
            ],
            "timestamp": self.timestamp,
            "checks_downgraded": self.checks_downgraded,
            "downgrade_mode": self.downgrade_mode,
        }
```

- [ ] **Step 4: Set the flag in `check_execution_gate()`**

At the bottom of `check_execution_gate()`, before building the return value, add:

```python
    checks_downgraded = kalshi_demo
    downgrade_mode = "kalshi-only" if kalshi_demo else None

    return ExecutionGateStatus(
        blocked=blocked,
        safe_to_trade=not blocked,
        gate_state=gate_state,
        reasons=reasons,
        checks_downgraded=checks_downgraded,
        downgrade_mode=downgrade_mode,
    )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/core/test_execution_gate_leniency.py -v`
Expected: all 3 PASS

- [ ] **Step 6: Add `SYSTEM_EXECUTION_GATE_LENIENT` constant to constants.ts**

In `web/react/src/config/constants.ts`, the `SYSTEM_EXECUTION_GATE` constant already points to `/api/v1/system/execution-gate` which returns the gate status. No new endpoint needed — the existing response now includes `checks_downgraded`. Add a UI constant:

```typescript
  // ── Execution Gate Leniency (R1 fix) ─────────────────────────────────
  // (uses SYSTEM_EXECUTION_GATE — field checks_downgraded added to response)
```

- [ ] **Step 7: Add LENIENT CHECKS badge to GlobalModeBanner**

In `web/react/src/components/GlobalModeBanner.tsx`, add a fetch for the gate status and surface the leniency badge:

```tsx
  const gateResult = useApiData<{
    gate_state: string;
    checks_downgraded: boolean;
    downgrade_mode: string | null;
  }>(
    API_ENDPOINTS.SYSTEM_EXECUTION_GATE,
    { pollingInterval: DEFAULTS.POLLING_INTERVALS.STANDARD }
  );

  const checksDowngraded = gateResult.data?.checks_downgraded ?? false;
  const downgradeMode = gateResult.data?.downgrade_mode ?? null;
```

Then inside the right-side `<div className="flex items-center gap-3">`, after the existing badges, add:

```tsx
          {checksDowngraded && (
            <span
              className="px-2 py-0.5 rounded bg-yellow-500/20 border border-yellow-500/40 text-yellow-300 text-xs font-mono"
              title={`Gate checks are lenient (mode: ${downgradeMode}). Reconciliation/price-feed criticals downgraded to warnings.`}
            >
              LENIENT CHECKS ({downgradeMode})
            </span>
          )}
```

- [ ] **Step 8: Commit**
```bash
git add core/execution_gate.py web/react/src/components/GlobalModeBanner.tsx tests/core/test_execution_gate_leniency.py
git commit -m "fix(gate): surface check leniency flag in ExecutionGateStatus and GlobalModeBanner badge"
```

---

## Task 3 — Passive-upgrade dead wire: mark NOT IMPLEMENTED, wire order-group-triggered alert (CRITICAL E1/E3)

**Files:**
- Modify: `merid/event_venues/kalshi/order_router.py`
- Modify: `agents/telegram_agent.py` (remove misleading stub reference)
- New test: `tests/event_venues/kalshi/test_order_router_passive_stub.py`

The `_passive_upgrade_task` does not exist in order_router.py. The Telegram agent has a stub method that implies it does. Fix the record.

- [ ] **Step 1: Write the test**

Create `tests/event_venues/kalshi/test_order_router_passive_stub.py`:
```python
"""Verify the passive-upgrade stub is documented as NOT IMPLEMENTED."""
import inspect


def test_order_router_has_no_passive_upgrade_task():
    """Passive-first execution is not implemented; this test asserts that
    the function doesn't silently exist as a no-op."""
    from merid.event_venues.kalshi import order_router
    # Should not have a _passive_upgrade_task that pretends to work
    assert not hasattr(order_router, "_passive_upgrade_task"), (
        "_passive_upgrade_task must not exist in order_router — "
        "it is documented as NOT IMPLEMENTED. Remove it or implement it."
    )


def test_order_group_triggered_publishes_event():
    """handle_order_group_triggered must publish the triggered event to core.events."""
    import asyncio
    from unittest.mock import AsyncMock, patch, MagicMock

    published = []

    async def fake_publish(channel, payload):
        published.append((channel, payload))

    with patch("merid.event_venues.kalshi.order_router.get_kalshi_client") as mock_client:
        mock_client.return_value = MagicMock()
        mock_client.return_value.connect = AsyncMock()
        mock_client.return_value.get_open_orders_result = AsyncMock(
            return_value=MagicMock(success=True, data=[])
        )
        with patch("core.events.publish_event", side_effect=lambda ch, p: published.append((ch, p))):
            from merid.event_venues.kalshi.order_router import handle_order_group_triggered
            result = asyncio.run(handle_order_group_triggered("grp-001", {"name": "test"}))

    assert result.get("group_id") == "grp-001"
```

- [ ] **Step 2: Run test to verify order_router has no false passive_upgrade_task**

Run: `pytest tests/event_venues/kalshi/test_order_router_passive_stub.py -v`
Expected: PASS (already no such function) or fail if a broken stub exists

- [ ] **Step 3: Add a clear NOT_IMPLEMENTED docstring comment at the top of order_router.py passive-upgrade section**

In `merid/event_venues/kalshi/order_router.py`, after the channel constants block, add:

```python
# ── Passive-first execution ─────────────────────────────────────────────
# STATUS: NOT IMPLEMENTED
# Passive-first order placement (submit at passive/maker price, upgrade to
# aggressive if unfilled after N seconds) has NOT been implemented in this
# file. The `send_passive_upgrade_fired` method in agents/telegram_agent.py
# is a notification stub only — it does not wire to any execution logic here.
# Implementation requires: (1) submit at passive price, (2) asyncio.sleep(N),
# (3) check fill status, (4) re-submit aggressively if still open.
# Track in: docs/superpowers/plans/passive-first-execution.md (future sprint)
```

- [ ] **Step 4: Remove misleading `send_passive_upgrade_fired` call comment from telegram_agent.py**

Open `agents/telegram_agent.py` and find the `send_passive_upgrade_fired` method. Add a docstring clarifying it is a notification stub:
```python
    async def send_passive_upgrade_fired(self, ...):
        """Notification stub — passive-first execution is NOT yet implemented.

        This method sends a Telegram alert that would accompany a passive→aggressive
        upgrade. It does NOT trigger any order logic. See order_router.py comments.
        """
```

- [ ] **Step 5: Run tests**

Run: `pytest tests/event_venues/kalshi/test_order_router_passive_stub.py -v`
Expected: all PASS

- [ ] **Step 6: Commit**
```bash
git add merid/event_venues/kalshi/order_router.py agents/telegram_agent.py tests/event_venues/kalshi/test_order_router_passive_stub.py
git commit -m "fix(order-router): document passive-upgrade as NOT IMPLEMENTED, prevent false operator assumptions"
```

---

## Task 4 — Promotion history + rollback alert endpoint and frontend wire (HIGH P2/P3)

**Files:**
- Modify: `web/api/kalshi_deployment.py`
- Modify: `web/react/src/components/GlobalModeBanner.tsx`
- New test: `tests/web/test_auto_promoter_history.py`

`AutoPromoter` already stores `_eval_history` (500 entries) and exposes `recent_promotions()`. We need:
1. A dedicated API endpoint for history (all evaluations, not just promotions)
2. A rollback alert in GlobalModeBanner when an auto-rollback fires

- [ ] **Step 1: Write the failing test**

Create `tests/web/test_auto_promoter_history.py`:
```python
"""Tests for the auto-promoter history endpoint."""
import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from web.main import app
    with patch("web.api.auth.get_current_session", return_value={"user_id": "test"}):
        yield TestClient(app)


def test_auto_promoter_history_returns_200(client):
    mock_promoter = MagicMock()
    mock_promoter._eval_history = []
    mock_promoter._last_eval_ts = 0.0
    mock_promoter._eval_count = 0

    with patch(
        "merid.event_venues.kalshi.auto_promoter.get_auto_promoter",
        return_value=mock_promoter,
    ):
        resp = client.get("/api/v1/kalshi/deployment/auto-promoter/history")
    assert resp.status_code == 200
    data = resp.json()
    assert "evaluations" in data
    assert "rollbacks" in data
    assert "promotions" in data


def test_auto_promoter_history_separates_rollbacks(client):
    from merid.event_venues.kalshi.auto_promoter import PromotionEvaluation
    eval_promoted = PromotionEvaluation(
        agent_name="btc_15m", from_phase="PAPER", to_phase="SHADOW",
        timestamp="2026-03-26T10:00:00Z", promoted=True,
    )
    eval_rollback = PromotionEvaluation(
        agent_name="btc_15m", from_phase="LIVE", to_phase="PAPER",
        timestamp="2026-03-26T11:00:00Z", promoted=False,
        blocked_by="auto_rollback: max_drawdown_pct",
    )

    mock_promoter = MagicMock()
    mock_promoter._eval_history = [eval_promoted, eval_rollback]

    with patch(
        "merid.event_venues.kalshi.auto_promoter.get_auto_promoter",
        return_value=mock_promoter,
    ):
        resp = client.get("/api/v1/kalshi/deployment/auto-promoter/history?limit=50")
    data = resp.json()
    assert len(data["promotions"]) == 1
    assert data["promotions"][0]["agent"] == "btc_15m"
    # rollbacks = evaluations that are not promoted and blocked_by contains "rollback"
    assert len(data["rollbacks"]) >= 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/web/test_auto_promoter_history.py -v`
Expected: FAIL — endpoint does not exist

- [ ] **Step 3: Add the endpoint to `web/api/kalshi_deployment.py`**

After the existing `@router.get("/transitions")` endpoint, add:

```python
@router.get("/auto-promoter/history")
async def get_auto_promoter_history(limit: int = 100) -> Dict[str, Any]:
    """Full evaluation history from the auto-promoter.

    Returns all evaluations (promotions + blocks + rollbacks) up to `limit`.
    Separates into sub-lists for easier UI consumption:
      - evaluations: all entries, newest first
      - promotions: successful promotions only
      - rollbacks: auto-rollback decisions (blocked_by contains 'rollback' or from_phase in LIVE/SHADOW and not promoted)
    """
    try:
        from merid.event_venues.kalshi.auto_promoter import get_auto_promoter
        promoter = get_auto_promoter()
        history = list(promoter._eval_history)
        recent = history[-limit:]
        recent_dicts = [e.to_dict() for e in reversed(recent)]  # newest first

        promotions = [d for d in recent_dicts if d.get("promoted")]
        rollbacks = [
            d for d in recent_dicts
            if not d.get("promoted")
            and d.get("from_phase") in ("LIVE", "SHADOW")
            and (
                "rollback" in (d.get("blocked_by") or "").lower()
                or "metrics_unavailable" in (d.get("blocked_by") or "").lower()
            )
        ]

        return {
            "status": "ok",
            "total_evaluations": len(history),
            "evaluations": recent_dicts,
            "promotions": promotions,
            "rollbacks": rollbacks,
            "last_eval_ts": promoter._last_eval_ts,
            "eval_count": promoter._eval_count,
        }
    except Exception as exc:
        logger.error("auto_promoter history error: %s", exc)
        return {"status": "error", "detail": str(exc), "evaluations": [], "promotions": [], "rollbacks": []}


@router.get("/auto-promoter/status")
async def get_auto_promoter_status() -> Dict[str, Any]:
    """Current auto-promoter status — running, interval, counts."""
    try:
        from merid.event_venues.kalshi.auto_promoter import get_auto_promoter
        promoter = get_auto_promoter()
        return {"status": "ok", **promoter.status()}
    except Exception as exc:
        logger.error("auto_promoter status error: %s", exc)
        return {"status": "error", "detail": str(exc)}
```

- [ ] **Step 4: Add rollback alert to GlobalModeBanner**

The `AUTO_PROMOTER_PROMOTIONS` constant in constants.ts already points to `/api/v1/kalshi/deployment/auto-promoter/promotions`. The new history endpoint is at `/api/v1/kalshi/deployment/auto-promoter/history`.

Add to `web/react/src/config/constants.ts` inside `API_ENDPOINTS`:
```typescript
  AUTO_PROMOTER_HISTORY: "/api/v1/kalshi/deployment/auto-promoter/history",
```

In `GlobalModeBanner.tsx`, add a rollback detector:
```tsx
  const promoterResult = useApiData<{
    rollbacks: Array<{ agent: string; from_phase: string; blocked_by: string; timestamp: string }>;
  }>(
    API_ENDPOINTS.AUTO_PROMOTER_HISTORY + "?limit=5",
    { pollingInterval: DEFAULTS.POLLING_INTERVALS.SLOW }
  );

  const recentRollbacks = promoterResult.data?.rollbacks ?? [];
  const hasRecentRollback = recentRollbacks.length > 0;
```

Then in the right-side badges area:
```tsx
          {hasRecentRollback && (
            <span
              className="px-2 py-0.5 rounded bg-red-500/20 border border-red-500/40 text-red-300 text-xs font-mono"
              title={`Auto-rollback: ${recentRollbacks[0]?.agent} ${recentRollbacks[0]?.from_phase}→PAPER — ${recentRollbacks[0]?.blocked_by}`}
            >
              AUTO-ROLLBACK: {recentRollbacks[0]?.agent}
            </span>
          )}
```

- [ ] **Step 5: Run tests**

Run: `pytest tests/web/test_auto_promoter_history.py -v`
Expected: all PASS

- [ ] **Step 6: Commit**
```bash
git add web/api/kalshi_deployment.py web/react/src/components/GlobalModeBanner.tsx web/react/src/config/constants.ts tests/web/test_auto_promoter_history.py
git commit -m "feat(promote): add auto-promoter history endpoint + rollback alert badge in GlobalModeBanner"
```

---

## Task 5 — Expose CONFLICTED/STALE consensus with reason strings in verdict feed (HIGH C3)

**Files:**
- Modify: `web/api/swarm_bus_api.py` (or wherever verdicts/consensus are returned)
- Modify: `web/react/src/components/SwarmVerdictFeed.tsx`

The `ConsensusView` dataclass already has `status`, `disagreement_flags`, and `confidence_factors`. The verdicts feed only shows READY events. Fix the API response and the component.

- [ ] **Step 1: Find the verdicts/consensus API endpoint**

Run: `grep -n "verdicts\|consensus_all\|consensus/all" web/api/*.py`
Identify which router serves `GET /api/v1/kalshi/swarm/verdicts` or equivalent.

- [ ] **Step 2: Ensure the verdicts response includes status and disagreement_flags**

In the relevant router, update the serialization of ConsensusView to include:
```python
def _serialize_consensus_view(view) -> dict:
    return {
        "asset": view.asset,
        "timeframe": view.timeframe,
        "timestamp": view.timestamp.isoformat(),
        "status": view.status.value if hasattr(view.status, "value") else str(view.status),
        "consensus_direction": view.consensus_direction,
        "consensus_probability": round(view.consensus_probability, 4),
        "consensus_confidence": round(view.consensus_confidence, 4),
        "voting_agents": view.voting_agents,
        "direction_breakdown": view.direction_breakdown,
        "size_band": view.size_band,
        "confidence_factors": view.confidence_factors,
        "disagreement_flags": view.disagreement_flags,  # was missing
    }
```

- [ ] **Step 3: Update SwarmVerdictFeed.tsx to display non-READY rows**

In `web/react/src/components/SwarmVerdictFeed.tsx`, find where rows are filtered to only `READY` and remove the filter (or add explicit CONFLICTED/STALE rows with different styling):

```tsx
// Status badge color
const statusColor = (status: string) => {
  switch (status?.toUpperCase()) {
    case 'READY': return 'text-green-400 bg-green-500/20';
    case 'CONFLICTED': return 'text-yellow-400 bg-yellow-500/20';
    case 'STALE': return 'text-gray-400 bg-gray-500/20';
    case 'FORMING': return 'text-blue-400 bg-blue-500/20';
    default: return 'text-gray-400 bg-gray-500/20';
  }
};
```

For each verdict row that is CONFLICTED, show `disagreement_flags` inline:
```tsx
{item.status !== 'READY' && item.disagreement_flags?.length > 0 && (
  <div className="text-xs text-yellow-300/70 mt-0.5 truncate">
    {item.disagreement_flags.join(' · ')}
  </div>
)}
```

- [ ] **Step 4: Commit**
```bash
git add web/api/swarm_bus_api.py web/react/src/components/SwarmVerdictFeed.tsx
git commit -m "fix(consensus): expose CONFLICTED/STALE states and disagreement_flags in verdict feed"
```

---

## Task 6 — WS subscription health endpoint + operator dashboard lag badge (HIGH M2/R6)

**Files:**
- Modify: `web/api/kalshi_api.py`
- Modify: `web/react/src/config/constants.ts`
- Modify operator health panel (wherever WS health is displayed)

- [ ] **Step 1: Write failing test**

Create `tests/web/test_kalshi_ws_health.py`:
```python
"""Test WS subscription health endpoint."""
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
import pytest


@pytest.fixture
def client():
    from web.main import app
    with patch("web.api.auth.get_current_session", return_value={"user_id": "test"}):
        yield TestClient(app)


def test_ws_subscription_health_returns_200(client):
    mock_ws = MagicMock()
    mock_ws.get_subscription_health = MagicMock(return_value={
        "connected": True,
        "subscribed_tickers": 5,
        "desired_tickers": 5,
        "lag_ms_p50": 12.3,
        "lag_ms_p95": 45.1,
        "lag_threshold_ms": 50.0,
        "degraded": False,
    })
    with patch(
        "merid.event_venues.kalshi.websocket_service.get_kalshi_ws_service",
        return_value=MagicMock(ws=mock_ws),
    ):
        resp = client.get("/api/v1/kalshi/ws/subscription-health")
    assert resp.status_code == 200
    data = resp.json()
    assert "connected" in data
    assert "degraded" in data
    assert "lag_ms_p50" in data
```

- [ ] **Step 2: Add the endpoint to `web/api/kalshi_api.py`**

After the existing WS status endpoint, add:
```python
@router.get("/ws/subscription-health")
async def get_ws_subscription_health() -> Dict[str, Any]:
    """WebSocket subscription health — lag metrics and subscription coverage.

    Returns lag percentiles, connection state, and degraded flag.
    The operator dashboard should alert when degraded=True.
    """
    try:
        from merid.event_venues.kalshi.websocket_service import get_kalshi_ws_service
        svc = get_kalshi_ws_service()
        ws = getattr(svc, "ws", None) or getattr(svc, "_ws", None)
        if ws and hasattr(ws, "get_subscription_health"):
            health = ws.get_subscription_health()
        else:
            # Fallback: get status from bridge
            from merid.event_venues.kalshi.ws_bridge import get_kalshi_ws_status
            bridge_status = get_kalshi_ws_status() or {}
            ws_client = bridge_status.get("ws_client") or {}
            health = {
                "connected": bridge_status.get("connected", False),
                "subscribed_tickers": bridge_status.get("subscribed_tickers", 0),
                "desired_tickers": None,
                "lag_ms_p50": None,
                "lag_ms_p95": None,
                "lag_threshold_ms": 50.0,
                "degraded": not bridge_status.get("connected", False),
                "last_msg_ago_s": ws_client.get("last_msg_ago_s"),
            }
        return {"status": "ok", **health}
    except Exception as exc:
        logger.warning("ws subscription health check failed: %s", exc)
        return {"status": "error", "detail": str(exc), "connected": False, "degraded": True}
```

- [ ] **Step 3: Add constant to constants.ts**

```typescript
  KALSHI_WS_SUBSCRIPTION_HEALTH: "/api/v1/kalshi/ws/subscription-health",
```

- [ ] **Step 4: Add WS degraded badge to operator health panel**

Find where WS health is shown in the operator dashboard (likely `OperatorDashboard.tsx` or a health panel component). Add:

```tsx
const wsHealthResult = useApiData<{
  connected: boolean;
  degraded: boolean;
  lag_ms_p95: number | null;
  subscribed_tickers: number;
}>(API_ENDPOINTS.KALSHI_WS_SUBSCRIPTION_HEALTH, {
  pollingInterval: DEFAULTS.POLLING_INTERVALS.STANDARD,
});

const wsDegraded = wsHealthResult.data?.degraded ?? false;
const wsLagP95 = wsHealthResult.data?.lag_ms_p95 ?? null;
```

Show as a health badge:
```tsx
{wsDegraded && (
  <span className="px-2 py-0.5 rounded bg-red-500/20 text-red-400 text-xs font-mono border border-red-500/30">
    WS DEGRADED {wsLagP95 ? `(${wsLagP95.toFixed(0)}ms p95)` : ''}
  </span>
)}
```

- [ ] **Step 5: Run tests**

Run: `pytest tests/web/test_kalshi_ws_health.py -v`
Expected: PASS

- [ ] **Step 6: Commit**
```bash
git add web/api/kalshi_api.py web/react/src/config/constants.ts tests/web/test_kalshi_ws_health.py
git commit -m "feat(ws): add subscription-health endpoint + WS degraded badge in operator dashboard"
```

---

## Task 7 — Drawdown tier endpoint + KalshiPortfolioView rendering (HIGH R5)

**Files:**
- Modify: `web/api/kalshi_api.py`
- Modify: `web/react/src/views/KalshiPortfolioView.tsx`
- Modify: `web/react/src/config/constants.ts`
- New test: `tests/web/test_kalshi_drawdown_tier.py`

`DRAWDOWN_TIER_CONFIG` is defined in the frontend but never queried. Backend KalshiRiskManager tracks peak/current equity → drawdown pct.

- [ ] **Step 1: Write failing test**

Create `tests/web/test_kalshi_drawdown_tier.py`:
```python
"""Test drawdown tier endpoint."""
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
import pytest


@pytest.fixture
def client():
    from web.main import app
    with patch("web.api.auth.get_current_session", return_value={"user_id": "test"}):
        yield TestClient(app)


def test_drawdown_tier_returns_200(client):
    mock_risk = MagicMock()
    mock_risk.state.peak_equity_usd = 10000.0
    mock_risk.state.current_equity_usd = 9500.0
    mock_risk.state.daily_pnl_usd = -500.0

    with patch("web.api.kalshi_api._get_kalshi_risk", return_value=mock_risk):
        resp = client.get("/api/v1/kalshi/risk/drawdown-tier")
    assert resp.status_code == 200
    data = resp.json()
    assert "tier" in data
    assert "drawdown_pct" in data
    assert data["tier"] in ("normal", "warning", "downsize", "halt")


def test_drawdown_tier_normal_below_5pct(client):
    mock_risk = MagicMock()
    mock_risk.state.peak_equity_usd = 10000.0
    mock_risk.state.current_equity_usd = 9700.0
    mock_risk.state.daily_pnl_usd = -300.0

    with patch("web.api.kalshi_api._get_kalshi_risk", return_value=mock_risk):
        resp = client.get("/api/v1/kalshi/risk/drawdown-tier")
    assert resp.json()["tier"] == "normal"


def test_drawdown_tier_halt_above_15pct(client):
    mock_risk = MagicMock()
    mock_risk.state.peak_equity_usd = 10000.0
    mock_risk.state.current_equity_usd = 8300.0
    mock_risk.state.daily_pnl_usd = -1700.0

    with patch("web.api.kalshi_api._get_kalshi_risk", return_value=mock_risk):
        resp = client.get("/api/v1/kalshi/risk/drawdown-tier")
    assert resp.json()["tier"] == "halt"
```

- [ ] **Step 2: Add helper and endpoint to `web/api/kalshi_api.py`**

First, add a private helper near the top of `kalshi_api.py` (after the existing helpers):
```python
def _get_kalshi_risk():
    """Return KalshiRiskManager singleton or None."""
    try:
        from merid.event_venues.kalshi.kalshi_risk import get_kalshi_risk
        return get_kalshi_risk()
    except Exception:
        return None


def _compute_drawdown_tier(drawdown_pct: float) -> str:
    """Classify drawdown pct into a tier name matching DRAWDOWN_TIER_CONFIG."""
    if drawdown_pct >= 0.15:
        return "halt"
    if drawdown_pct >= 0.10:
        return "downsize"
    if drawdown_pct >= 0.05:
        return "warning"
    return "normal"
```

Then add the endpoint:
```python
@router.get("/risk/drawdown-tier")
async def get_drawdown_tier() -> Dict[str, Any]:
    """Current drawdown tier (normal / warning / downsize / halt).

    Computed from KalshiRiskManager state: (peak_equity - current) / peak_equity.
    Thresholds: 5% = warning, 10% = downsize, 15% = halt.
    """
    try:
        risk = _get_kalshi_risk()
        if risk is None:
            return {"tier": "normal", "drawdown_pct": 0.0, "source": "unavailable"}

        state = risk.state
        peak = float(getattr(state, "peak_equity_usd", 0) or 0)
        current = float(getattr(state, "current_equity_usd", 0) or peak)
        daily_pnl = float(getattr(state, "daily_pnl_usd", 0) or 0)

        drawdown_pct = (peak - current) / peak if peak > 0 else 0.0
        tier = _compute_drawdown_tier(drawdown_pct)

        return {
            "tier": tier,
            "drawdown_pct": round(drawdown_pct, 4),
            "drawdown_usd": round(peak - current, 2),
            "peak_equity_usd": round(peak, 2),
            "current_equity_usd": round(current, 2),
            "daily_pnl_usd": round(daily_pnl, 2),
            "thresholds": {"warning": 0.05, "downsize": 0.10, "halt": 0.15},
            "source": "kalshi_risk",
        }
    except Exception as exc:
        logger.warning("drawdown tier check failed: %s", exc)
        return {"tier": "normal", "drawdown_pct": 0.0, "source": "error", "detail": str(exc)}
```

- [ ] **Step 3: Add constant to constants.ts**

```typescript
  KALSHI_DRAWDOWN_TIER: "/api/v1/kalshi/risk/drawdown-tier",
```

- [ ] **Step 4: Wire to KalshiPortfolioView**

In `web/react/src/views/KalshiPortfolioView.tsx`, add:
```tsx
  const drawdownTierResult = useApiData<{
    tier: 'normal' | 'warning' | 'downsize' | 'halt';
    drawdown_pct: number;
    drawdown_usd: number;
    peak_equity_usd: number;
    daily_pnl_usd: number;
  }>(API_ENDPOINTS.KALSHI_DRAWDOWN_TIER, { pollingInterval: DEFAULTS.POLLING_INTERVALS.STANDARD });

  const drawdownTier = drawdownTierResult.data?.tier ?? 'normal';
  const drawdownPct = drawdownTierResult.data?.drawdown_pct ?? 0;
  const tierCfg = DRAWDOWN_TIER_CONFIG[drawdownTier] ?? DRAWDOWN_TIER_CONFIG.normal;
```

Then in the JSX, after the daily PnL display, add a drawdown tier badge:
```tsx
{drawdownTier !== 'normal' && (
  <div className={`flex items-center gap-2 px-3 py-1.5 rounded-md ${tierCfg.bg} border border-current/20`}>
    <span className={`text-xs font-bold ${tierCfg.color}`}>
      {tierCfg.label.toUpperCase()} — {(drawdownPct * 100).toFixed(1)}% DRAWDOWN
    </span>
    {drawdownTier === 'halt' && (
      <span className="text-xs text-red-300">Trading halted by risk manager</span>
    )}
  </div>
)}
```

- [ ] **Step 5: Run tests**

Run: `pytest tests/web/test_kalshi_drawdown_tier.py -v`
Expected: all PASS

- [ ] **Step 6: Commit**
```bash
git add web/api/kalshi_api.py web/react/src/views/KalshiPortfolioView.tsx web/react/src/config/constants.ts tests/web/test_kalshi_drawdown_tier.py
git commit -m "feat(risk): add drawdown-tier endpoint + display tier badge in KalshiPortfolioView"
```

---

## Task 8 — Last-trade-sizing debug endpoint + manual order pre-flight (HIGH S1/A2/E4)

**Files:**
- Modify: `web/api/kalshi_api.py`
- Modify: `web/react/src/config/constants.ts`

The sizing decision (Kelly fraction × debate multiplier × sentiment-vol multiplier) is invisible. Add an endpoint that exposes the last sizing context, and a pre-flight check for manual orders.

- [ ] **Step 1: Add sizing context store to position_sizer.py**

In `merid/event_venues/kalshi/position_sizer.py`, add a module-level last-sizing store:

```python
import threading as _threading

_last_sizing_context: dict = {}
_last_sizing_lock = _threading.Lock()


def record_sizing_context(context: dict) -> None:
    """Record the most recent sizing calculation for observability."""
    global _last_sizing_context
    with _last_sizing_lock:
        _last_sizing_context = {**context, "recorded_at": __import__("time").time()}


def get_last_sizing_context() -> dict:
    """Return the most recently recorded sizing context."""
    with _last_sizing_lock:
        return dict(_last_sizing_context)
```

Call `record_sizing_context(...)` inside the sizer's `compute()` method after the final size is determined, passing a dict with `kelly_fraction`, `base_contracts`, `sentiment_vol_multiplier`, `debate_multiplier`, `final_contracts`, `ticker`, `asset`.

- [ ] **Step 2: Add the endpoint to `web/api/kalshi_api.py`**

```python
@router.get("/debug/last-trade-sizing")
async def get_last_trade_sizing() -> Dict[str, Any]:
    """Last sizing context — Kelly fraction, debate multiplier, sentiment-vol multiplier.

    This is a debugging/observability endpoint. Shows what multipliers were
    applied to the most recent trade's position sizing calculation.
    """
    try:
        from merid.event_venues.kalshi.position_sizer import get_last_sizing_context
        ctx = get_last_sizing_context()
        if not ctx:
            return {"status": "no_data", "message": "No trades have been sized yet this session"}
        return {"status": "ok", **ctx}
    except Exception as exc:
        logger.warning("last trade sizing lookup failed: %s", exc)
        return {"status": "error", "detail": str(exc)}


@router.post("/orders/preflight")
async def preflight_order(body: Dict[str, Any]) -> Dict[str, Any]:
    """Pre-flight validation for a manual order intent.

    Runs the order through ExecutionGate + ExecutionGuard checks WITHOUT
    submitting it. Returns pass/fail with reasons for each check.

    Body: { ticker, side, action, price_cents, count, source? }
    """
    try:
        from core.execution_gate import check_execution_gate
        gate = check_execution_gate()

        from merid.execution_guard import get_execution_guard
        guard = get_execution_guard()

        # Build a minimal plan dict for the guard
        ticker = body.get("ticker", "")
        count = int(body.get("count", 0))
        price_cents = int(body.get("price_cents", 50))
        notional_usd = (count * price_cents) / 100.0

        class _FakePlan:
            size_usd = notional_usd
            domain = "kalshi"

        verdict = guard.pre_trade_check(_FakePlan(), domain="kalshi")

        checks = [
            {
                "name": "execution_gate",
                "passed": not gate.blocked,
                "gate_state": gate.gate_state,
                "reasons": [r.message for r in gate.reasons if r.severity == "critical"],
                "warnings": [r.message for r in gate.reasons if r.severity == "warning"],
                "checks_downgraded": gate.checks_downgraded,
            },
            {
                "name": "execution_guard",
                "passed": verdict.allowed,
                "reason": verdict.reason,
                "throttle_pct": verdict.throttle_pct,
                "adjusted_size_usd": verdict.adjusted_size_usd,
                "checks_passed": verdict.checks_passed,
                "checks_failed": verdict.checks_failed,
            },
        ]

        all_passed = not gate.blocked and verdict.allowed
        return {
            "status": "ok",
            "may_submit": all_passed,
            "checks": checks,
            "estimated_notional_usd": round(notional_usd, 2),
        }
    except Exception as exc:
        logger.warning("order preflight failed: %s", exc)
        return {"status": "error", "detail": str(exc), "may_submit": False, "checks": []}
```

- [ ] **Step 3: Add constants**

```typescript
  KALSHI_DEBUG_LAST_SIZING: "/api/v1/kalshi/debug/last-trade-sizing",
  KALSHI_ORDER_PREFLIGHT: "/api/v1/kalshi/orders/preflight",
```

- [ ] **Step 4: Commit**
```bash
git add web/api/kalshi_api.py merid/event_venues/kalshi/position_sizer.py web/react/src/config/constants.ts
git commit -m "feat(sizing): add last-trade-sizing debug endpoint and order preflight validation"
```

---

## Task 9 — Category exposure remaining-capacity endpoint (MEDIUM S2)

**Files:**
- Modify: `web/api/kalshi_api.py`
- Modify: `web/react/src/config/constants.ts`
- New test: `tests/web/test_kalshi_category_caps.py`

- [ ] **Step 1: Write failing test**

Create `tests/web/test_kalshi_category_caps.py`:
```python
"""Test category exposure caps endpoint."""
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
import pytest


@pytest.fixture
def client():
    from web.main import app
    with patch("web.api.auth.get_current_session", return_value={"user_id": "test"}):
        yield TestClient(app)


def test_category_caps_returns_200(client):
    resp = client.get("/api/v1/kalshi/risk/category-caps")
    assert resp.status_code == 200
    data = resp.json()
    assert "caps" in data


def test_category_caps_shape(client):
    mock_risk = MagicMock()
    mock_risk.state.category_notional = {"BTC": 1500.0, "ETH": 800.0}
    mock_risk.config.category_limits = {
        "BTC": MagicMock(max_notional_usd=5000.0),
        "ETH": MagicMock(max_notional_usd=3000.0),
    }

    with patch("web.api.kalshi_api._get_kalshi_risk", return_value=mock_risk):
        resp = client.get("/api/v1/kalshi/risk/category-caps")
    data = resp.json()
    assert "BTC" in data["caps"]
    assert data["caps"]["BTC"]["used_usd"] == 1500.0
    assert data["caps"]["BTC"]["limit_usd"] == 5000.0
    assert data["caps"]["BTC"]["remaining_usd"] == 3500.0
    assert data["caps"]["BTC"]["utilization_pct"] == pytest.approx(30.0)
```

- [ ] **Step 2: Add endpoint to `web/api/kalshi_api.py`**

```python
@router.get("/risk/category-caps")
async def get_category_caps() -> Dict[str, Any]:
    """Per-category (asset) exposure caps and current utilization.

    Shows used notional, limit, remaining capacity and utilization % per
    asset category (BTC, ETH, CRYPTO, etc.).
    """
    try:
        risk = _get_kalshi_risk()
        caps: Dict[str, Any] = {}

        if risk is not None:
            try:
                state = risk.state
                config = risk.config
                cat_notional = dict(getattr(state, "category_notional", {}) or {})
                cat_limits = dict(getattr(config, "category_limits", {}) or {})

                all_cats = set(cat_notional.keys()) | set(cat_limits.keys())
                for cat in all_cats:
                    used = float(cat_notional.get(cat, 0.0))
                    limit_obj = cat_limits.get(cat)
                    limit = float(getattr(limit_obj, "max_notional_usd", 0) or 0) if limit_obj else 0.0
                    remaining = max(0.0, limit - used)
                    util_pct = (used / limit * 100.0) if limit > 0 else 0.0
                    caps[cat] = {
                        "used_usd": round(used, 2),
                        "limit_usd": round(limit, 2),
                        "remaining_usd": round(remaining, 2),
                        "utilization_pct": round(util_pct, 1),
                        "kill": used >= limit if limit > 0 else False,
                    }
            except Exception as inner_exc:
                logger.debug("category caps inner error: %s", inner_exc)

        # Also pull per-asset limits from TraderConfig if available (Phase 16)
        try:
            from config.crypto_spot_kalshi_config import get_trader_config
            tc = get_trader_config()
            asset_limits = getattr(tc, "per_asset_exposure_limits", {}) or {}
            for asset, limit_val in asset_limits.items():
                if asset not in caps:
                    caps[asset] = {
                        "used_usd": 0.0,
                        "limit_usd": float(limit_val),
                        "remaining_usd": float(limit_val),
                        "utilization_pct": 0.0,
                        "kill": False,
                    }
        except Exception:
            pass

        return {"status": "ok", "caps": caps, "total_categories": len(caps)}
    except Exception as exc:
        logger.warning("category caps error: %s", exc)
        return {"status": "error", "detail": str(exc), "caps": {}}
```

- [ ] **Step 3: Add constant**

```typescript
  KALSHI_CATEGORY_CAPS: "/api/v1/kalshi/risk/category-caps",
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/web/test_kalshi_category_caps.py -v`
Expected: PASS

- [ ] **Step 5: Commit**
```bash
git add web/api/kalshi_api.py web/react/src/config/constants.ts tests/web/test_kalshi_category_caps.py
git commit -m "feat(risk): add category-caps exposure endpoint with per-asset utilization"
```

---

## Task 10 — Shadow stage in SwarmConsensusMatrix and KalshiGridView (MEDIUM P4)

**Files:**
- Modify: `web/react/src/views/SwarmConsensusMatrix.tsx`
- Modify: `web/react/src/views/KalshiGridView.tsx`

The `AgentMode.SHADOW` stage already exists in the backend (`merid/event_venues/kalshi/deployment.py`). The frontend `TradingMode` type in GlobalModeBanner has `SHADOW`. But the SwarmConsensusMatrix cell and grid cell don't render it distinctly.

- [ ] **Step 1: Find where promotion_stage is rendered in SwarmConsensusMatrix.tsx**

Run: `grep -n "promotion_stage\|paper\|shadow\|live" web/react/src/views/SwarmConsensusMatrix.tsx | head -30`

- [ ] **Step 2: Add SHADOW case to stage badge**

Find the stage badge JSX (usually a small pill showing "paper" / "live"). Add shadow:
```tsx
const stageBadge = (stage: string) => {
  switch ((stage || '').toUpperCase()) {
    case 'LIVE':
      return <span className="px-1 py-0.5 rounded text-[10px] bg-green-500/20 text-green-400 border border-green-500/30">LIVE</span>;
    case 'SHADOW':
      return <span className="px-1 py-0.5 rounded text-[10px] bg-cyan-500/20 text-cyan-400 border border-cyan-500/30">SHADOW</span>;
    case 'HALTED':
      return <span className="px-1 py-0.5 rounded text-[10px] bg-red-500/20 text-red-400 border border-red-500/30">HALT</span>;
    default:
      return <span className="px-1 py-0.5 rounded text-[10px] bg-blue-500/20 text-blue-400 border border-blue-500/30">PAPER</span>;
  }
};
```

- [ ] **Step 3: Apply same fix to KalshiGridView.tsx**

Run: `grep -n "promotion_stage\|paper\|PAPER\|LIVE\|SHADOW" web/react/src/views/KalshiGridView.tsx | head -20`

Apply the same `stageBadge` helper or equivalent inline style fix.

- [ ] **Step 4: Commit**
```bash
git add web/react/src/views/SwarmConsensusMatrix.tsx web/react/src/views/KalshiGridView.tsx
git commit -m "fix(ui): add SHADOW stage badge to SwarmConsensusMatrix and KalshiGridView cells"
```

---

## Task 11 — action=null fills data-quality warning (MEDIUM M1)

**Files:**
- Modify: `web/api/kalshi_api.py` (fills endpoint response)
- Modify: `web/react/src/views/KalshiPortfolioView.tsx`

- [ ] **Step 1: Expose null_action_fill_count in fills endpoint**

In the fills endpoint in `web/api/kalshi_api.py`, add to the response:
```python
# After collecting fills, compute quality metric
null_action_count = sum(1 for f in fills if not f.get("action"))
total_fills = len(fills)
data_quality = "degraded" if null_action_count > 0 else "ok"
```

Return this in the response payload:
```python
return {
    "fills": fills,
    "total": total_fills,
    "null_action_fills": null_action_count,
    "data_quality": data_quality,
}
```

- [ ] **Step 2: Show warning in KalshiPortfolioView fills tab**

In `KalshiPortfolioView.tsx`, when the fills tab is active:
```tsx
{fillsResult.data?.null_action_fills > 0 && (
  <div className="mb-2 px-3 py-1.5 rounded bg-yellow-500/10 border border-yellow-500/30 text-yellow-400 text-xs">
    Data quality warning: {fillsResult.data.null_action_fills} fill(s) have null action field — position aggregation may be incomplete.
  </div>
)}
```

- [ ] **Step 3: Commit**
```bash
git add web/api/kalshi_api.py web/react/src/views/KalshiPortfolioView.tsx
git commit -m "fix(fills): expose null_action fill count as data quality warning in portfolio view"
```

---

## Task 12 — Run all tests and fix any regressions

- [ ] **Step 1: Run the full test suite for touched modules**

```bash
pytest tests/core/test_execution_gate_leniency.py \
       tests/event_venues/kalshi/test_order_router_passive_stub.py \
       tests/web/test_auto_promoter_history.py \
       tests/web/test_kalshi_drawdown_tier.py \
       tests/web/test_kalshi_category_caps.py \
       -v --tb=short 2>&1 | tail -40
```
Expected: all PASS

- [ ] **Step 2: Run existing related tests to catch regressions**

```bash
pytest tests/core/test_execution_gate.py \
       tests/event_venues/kalshi/test_ws.py \
       tests/test_kalshi_reconciler.py \
       -v --tb=short 2>&1 | tail -40
```
Expected: all PASS (or pre-existing failures only)

- [ ] **Step 3: Final commit if any minor fixups needed**

```bash
git add -u
git commit -m "fix: address test regressions from lifecycle audit fixes"
```
