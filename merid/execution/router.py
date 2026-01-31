"""ExecutionRouter coordinating guards, explainability, and venue dispatch."""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, List, Optional

from merid.execution.base import TradeExecutor, TradeResult, TradeSideLiteral, Position
from merid.execution.portfolio import PortfolioAggregator, PortfolioSnapshot
from trading.adapters.base import TradeRequest, TradeSide
from trading.config.runtime_config import TradingRuntimeConfig, get_runtime_config
from trading.guards.trading_guard import (
    GuardDecision,
    GuardDecisionStatus,
    get_solana_anti_rug_guard,
    get_trading_guard,
)
from core.explainability import (
    DecisionRationale,
    ExplanationContext,
    ExplanationType,
    FeatureAttribution,
    get_explainability_service,
)
from observability.event_stream import publish_event
from trading.spectator import get_spectator_log


@dataclass(slots=True)
class TraderIdentity:
    trader_type: str  # "human" | "agent"
    trader_id: str
    strategy: Optional[str] = None


@dataclass(slots=True)
class TradeIntent:
    intent_id: str
    trader: TraderIdentity
    venue_id: str
    symbol: str
    side: TradeSideLiteral
    size: float
    price: Optional[float] = None
    params: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)
    guard_decision: Optional[GuardDecision] = None
    explanation_id: Optional[str] = None
    timestamp: float = field(default_factory=time.time)


class ExecutionRouter:
    """Unified entrypoint for all MERID trade intents."""

    def __init__(
        self,
        *,
        executors: Optional[Dict[str, TradeExecutor]] = None,
        executor_factory: Optional[Callable[[str], Optional[TradeExecutor]]] = None,
        runtime_config: Optional[TradingRuntimeConfig] = None,
        trading_guard=None,
        explainability_service=None,
        spectator_logger=None,
    ) -> None:
        self._executors: Dict[str, TradeExecutor] = executors or {}
        self._executor_factory = executor_factory
        self._listeners: List[Callable[[str, Any], Awaitable[None] | None]] = []
        self._runtime_config = runtime_config or get_runtime_config()
        self._trading_guard = trading_guard or get_trading_guard()
        self._solana_guard = get_solana_anti_rug_guard()
        self._explainability = explainability_service or get_explainability_service()
        self._spectator = spectator_logger or get_spectator_log()
        self._portfolio_aggregator = PortfolioAggregator()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def register_executor(self, venue: str, executor: TradeExecutor) -> None:
        self._executors[venue] = executor

    def register_listener(self, callback: Callable[[str, Any], Awaitable[None] | None]) -> None:
        self._listeners.append(callback)

    async def submit_trade(
        self,
        *,
        trader: TraderIdentity,
        venue_id: str,
        symbol: str,
        side: TradeSideLiteral,
        size: float,
        price: Optional[float] = None,
        params: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> TradeResult:
        intent = TradeIntent(
            intent_id=f"intent_{uuid.uuid4()}",
            trader=trader,
            venue_id=venue_id,
            symbol=symbol,
            side=side,
            size=size,
            price=price,
            params=params or {},
            metadata=metadata or {},
        )
        return await self.execute(intent)

    async def execute(self, intent: TradeIntent) -> TradeResult:
        executor = self._executors.get(intent.venue_id)
        if executor is None and self._executor_factory is not None:
            executor = self._executor_factory(intent.venue_id)
            if executor is not None:
                self._executors[intent.venue_id] = executor
        if executor is None:
            raise RuntimeError(f"No executor registered for venue {intent.venue_id}")

        trade_request = self._build_trade_request(intent)
        guard_decision = self._evaluate_guards(trade_request, intent.metadata)
        intent.guard_decision = guard_decision
        intent.explanation_id = self._record_explanation(intent, guard_decision)

        await self._notify("order_intent", intent)
        self._spectator.ingest_event("order_intent", intent)
        self._publish_event(
            "trading.intent",
            {
                "intent_id": intent.intent_id,
                "trader_id": intent.trader.trader_id,
                "trader_type": intent.trader.trader_type,
                "venue": intent.venue_id,
                "symbol": intent.symbol,
                "side": intent.side,
                "size": intent.size,
                "guard_status": guard_decision.status.value,
                "explanation_id": intent.explanation_id,
            },
        )

        if guard_decision.status == GuardDecisionStatus.BLOCK:
            return self._blocked_result(intent, "Guard blocked trade", guard_decision)
        if guard_decision.status == GuardDecisionStatus.REQUIRE_CONFIRMATION:
            return self._blocked_result(intent, "Requires human confirmation", guard_decision)
        if guard_decision.status == GuardDecisionStatus.SIMULATE:
            return self._simulated_result(intent, guard_decision)

        executor_result = await executor.execute_trade(
            symbol=intent.symbol,
            side=intent.side,
            amount=intent.size,
            order_type=intent.params.get("order_type", "market"),
            price=intent.price,
            metadata=intent.metadata,
        )

        await self._notify("order_result", executor_result)
        self._spectator.ingest_event("order_result", executor_result)
        self._publish_event(
            "trading.result",
            {
                "intent_id": intent.intent_id,
                "venue": executor_result.venue,
                "symbol": executor_result.symbol,
                "side": executor_result.side,
                "size": executor_result.size,
                "price": executor_result.price,
                "success": executor_result.success,
                "error": executor_result.error,
                "explanation_id": executor_result.explanation_id or intent.explanation_id,
            },
        )
        return executor_result

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _build_trade_request(self, intent: TradeIntent) -> TradeRequest:
        should_live = self._should_request_live(intent.trader)
        return TradeRequest(
            venue=intent.venue_id,
            symbol=intent.symbol,
            side=TradeSide(intent.side.upper()),
            quantity=intent.size,
            price=intent.price,
            metadata={**intent.metadata, "trader_id": intent.trader.trader_id},
            client_reference=intent.intent_id,
            live=should_live,
        )

    def _should_request_live(self, trader: TraderIdentity) -> bool:
        state = self._runtime_config.snapshot()
        trader_cfg = self._runtime_config.get_trader(trader.trader_id)

        if trader_cfg:
            if trader_cfg.get("spectator_only"):
                return False
            mode = trader_cfg.get("mode")
            if mode == "live":
                return True
            if mode in {"sim", "paper"}:
                return False

        if trader.trader_type == "human" and state.get("spectator_mode"):
            return False

        return bool(state.get("allow_live_trades", False))

    def _evaluate_guards(self, request: TradeRequest, metadata: Dict[str, Any]) -> GuardDecision:
        decision = self._trading_guard.evaluate(request)
        if metadata.get("category") == "memecoin":
            anti_rug = self._solana_guard.evaluate(metadata.get("token_context", {}))
            if anti_rug.status != GuardDecisionStatus.ALLOW:
                return anti_rug
        return decision

    def _record_explanation(self, intent: TradeIntent, guard_decision: GuardDecision) -> Optional[str]:
        try:
            inputs = {
                "symbol": intent.symbol,
                "venue": intent.venue_id,
                "size": intent.size,
                "side": intent.side,
                "metadata": intent.metadata,
            }
            rationale = DecisionRationale(
                reason=guard_decision.reason,
                inputs=inputs,
                features=[FeatureAttribution(name="notional", value=intent.metadata.get("notional_usd"))],
            )
            context = ExplanationContext(
                inputs=inputs,
                agent_id=intent.trader.trader_id,
                strategy=intent.trader.strategy,
                constraints={"guard_status": guard_decision.status.value},
                expected_effect={"mode": guard_decision.status.value},
                environment_flags={"trader_type": intent.trader.trader_type},
            )
            record = self._explainability.record_explanation(
                ExplanationType.ORDER,
                summary=guard_decision.reason,
                context=context,
                domain="trading",
                decision_id=str(uuid.uuid4()),
                rationale=rationale,
                guardrail_decision=guard_decision.status.value,
            )
            return record.record_id
        except Exception:
            return None

    def _blocked_result(self, intent: TradeIntent, reason: str, guard_decision: GuardDecision) -> TradeResult:
        return TradeResult(
            success=False,
            venue=intent.venue_id,
            symbol=intent.symbol,
            side=intent.side,
            size=intent.size,
            price=intent.price or 0.0,
            error=reason,
            explanation_id=intent.explanation_id,
            metadata={"guard": guard_decision.reason, "status": guard_decision.status.value},
        )

    def _simulated_result(self, intent: TradeIntent, guard_decision: GuardDecision) -> TradeResult:
        return TradeResult(
            success=True,
            venue=intent.venue_id,
            symbol=intent.symbol,
            side=intent.side,
            size=intent.size,
            price=intent.price or 0.0,
            tx_id=None,
            error=None,
            explanation_id=intent.explanation_id,
            metadata={"simulated": True, "guard": guard_decision.reason},
        )

    async def _notify(self, event_type: str, payload: Any) -> None:
        for callback in list(self._listeners):
            result = callback(event_type, payload)
            if asyncio.iscoroutine(result):
                await result

    async def get_portfolio_snapshot(self) -> PortfolioSnapshot:
        """Fetch positions from all executors and return an aggregated portfolio."""
        venue_positions: Dict[str, List[Position]] = {}
        for venue, executor in self._executors.items():
            try:
                venue_positions[venue] = await executor.get_positions()
            except Exception:
                venue_positions[venue] = []
        return await self._portfolio_aggregator.aggregate(venue_positions)

    def _publish_event(self, event_type: str, payload: Dict[str, Any]) -> None:
        try:
            publish_event(event_type, payload)
        except Exception:
            pass


# Global singleton instance
_execution_router: Optional[ExecutionRouter] = None


def get_execution_router() -> ExecutionRouter:
    """Get the global ExecutionRouter singleton instance."""
    global _execution_router
    if _execution_router is None:
        _execution_router = ExecutionRouter()
    return _execution_router
