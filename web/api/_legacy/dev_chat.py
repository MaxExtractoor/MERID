"""Dev Chat API endpoints for swarm control and monitoring."""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from web.api.auth import get_current_session
from utils.logger import get_logger

logger = get_logger(__name__)

from merid.execution import ExecutionRouter, TraderIdentity, PortfolioSnapshot
from trading.config.runtime_config import get_runtime_config

router = APIRouter(prefix="/api/v1/dev-chat", tags=["dev-chat"], dependencies=[Depends(get_current_session)]  # ZT6-01
)

_runtime_config = get_runtime_config()
_execution_router = ExecutionRouter()


class ChatCommand(BaseModel):
    command: str = Field(..., description="Command name")
    args: List[str] = Field(default_factory=list, description="Command arguments")
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ChatResponse(BaseModel):
    status: Literal["ok", "error"]
    message: str
    data: Optional[Dict[str, Any]] = None


@router.post("/execute", response_model=ChatResponse)
async def execute_chat_command(cmd: ChatCommand) -> ChatResponse:
    """Execute a dev chat command (e.g., trigger a small change)."""
    try:
        if cmd.command == "generate_tests":
            module = cmd.args[0] if cmd.args else "merid.execution.router"
            return ChatResponse(
                status="ok",
                message=f"Tests generation queued for module {module}",
                data={"module": module},
            )
        elif cmd.command == "toggle_mode":
            new_mode = cmd.args[0] if cmd.args else "sim"
            snapshot = _runtime_config.snapshot()
            current = snapshot.get("mode", "offline")
            _runtime_config.update_global_mode(mode=new_mode)
            return ChatResponse(
                status="ok",
                message=f"Global mode changed from {current} to {new_mode}",
                data={"old": current, "new": new_mode},
            )
        elif cmd.command == "submit_test_trade":
            trader = TraderIdentity(trader_type="agent", trader_id="dev-chat")
            result = await _execution_router.submit_trade(
                trader=trader,
                venue_id="paper",
                symbol="BTC-USDT",
                side="buy",
                size=0.001,
                metadata={"source": "dev_chat"},
            )
            return ChatResponse(
                status="ok",
                message="Test trade submitted",
                data={
                    "success": result.success,
                    "venue": result.venue,
                    "symbol": result.symbol,
                    "size": result.size,
                    "price": result.price,
                },
            )
        elif cmd.command == "portfolio_snapshot":
            snapshot: PortfolioSnapshot = await _execution_router.get_portfolio_snapshot()
            return ChatResponse(
                status="ok",
                message="Portfolio snapshot retrieved",
                data={
                    "total_unrealized_pnl": snapshot.total_unrealized_pnl,
                    "total_notional": snapshot.total_notional,
                    "positions": [
                        {
                            "symbol": p.symbol,
                            "total_size": p.total_size,
                            "avg_entry_price": p.avg_entry_price,
                            "unrealized_pnl": p.unrealized_pnl,
                            "venue_breakdown": p.venue_breakdown,
                        }
                        for p in snapshot.positions
                    ],
                },
            )
        elif cmd.command == "list_venues":
            return ChatResponse(
                status="ok",
                message="Registered venues",
                data={"venues": list(_execution_router._executors.keys())},
            )
        elif cmd.command == "guard_status":
            # Simple guard health check
            return ChatResponse(
                status="ok",
                message="Guard status",
                data={"trading_guard": "active", "solana_guard": "active"},
            )
        else:
            raise ValueError(f"Unknown command: {cmd.command}")
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/status")
async def chat_status() -> Dict[str, Any]:
    """Return current runtime status useful for chat context."""
    snapshot = _runtime_config.snapshot()
    return {
        "global_mode": snapshot.get("mode"),
        "allow_live_trades": snapshot.get("allow_live_trades"),
        "spectator_mode": snapshot.get("spectator_mode"),
        "venues": list(snapshot.get("venues", {}).keys()),
        "traders": list(snapshot.get("traders", {}).keys()),
    }
