"""KalshiTradingAgent — Per-(asset, timeframe) trading agent.

Each agent instance:
- Subscribes to a filtered set of Kalshi markets (resolved from config)
- Reads MERID's internal crypto price feed for model features
- Executes only via typed Kalshi tools
- Runs a decision loop keyed to contract expiry windows
- Enforces per-agent risk limits

Reuses:
- KalshiStrategy (merid.prediction.strategy) for edge/sizing decisions
- PredictionMarketRisk (merid.prediction.risk) for pre-trade checks
- PredictionMarketModel (merid.prediction.model) for implied probs
- SessionGuard for trading hours
- VenueGate for mode gating
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional

from merid.prediction.agent_grid_config import AgentConfig, EntryWindowConfig
from merid.prediction.session_guard import get_session_guard
from merid.prediction.venue_gate import get_venue_gate
from merid.prediction.model import PredictionMarketModel, MarketSnapshot, ContractState, ImpliedProbability
from merid.prediction.strategy import KalshiStrategy, StrategySignal, SignalAction, StrategyConfig
from merid.prediction.risk import PredictionMarketRisk, PredictionRiskConfig, PreTradeCheck
from merid.event_venues.base import EventMarket
from utils.logger import get_logger


_MAX_LOG_ENTRIES = 200


@dataclass
class AgentState:
    """Runtime state for a single trading agent."""
    name: str
    enabled: bool = True
    running: bool = False
    last_cycle_at: Optional[datetime] = None
    cycles_run: int = 0
    orders_placed: int = 0
    orders_this_window: int = 0
    window_start: Optional[datetime] = None
    active_tickers: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    last_error: Optional[str] = None
    signal_log: List[Dict[str, Any]] = field(default_factory=list)
    order_log: List[Dict[str, Any]] = field(default_factory=list)
    fill_log: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "enabled": self.enabled,
            "running": self.running,
            "last_cycle_at": self.last_cycle_at.isoformat() if self.last_cycle_at else None,
            "cycles_run": self.cycles_run,
            "orders_placed": self.orders_placed,
            "orders_this_window": self.orders_this_window,
            "active_tickers": self.active_tickers,
            "last_error": self.last_error,
            "signal_count": len(self.signal_log),
            "order_count": len(self.order_log),
            "fill_count": len(self.fill_log),
        }


class KalshiTradingAgent:
    """Trades a specific (asset, timeframe) cell on Kalshi.

    Lifecycle:
        agent = KalshiTradingAgent(config)
        await agent.start()       # begins decision loop
        await agent.stop()        # graceful shutdown

    The decision loop:
        1. Resolve config market_filter → live Kalshi tickers
        2. For each market in entry window: evaluate strategy signal
        3. If signal is actionable: run pre-trade risk check
        4. If allowed: place order via kalshi_place_order tool
        5. Sleep until next cycle
    """

    def __init__(self, config: AgentConfig):
        self.config = config
        self.logger = get_logger(f"merid.prediction.agent.{config.name}")
        self.state = AgentState(name=config.name)

        # Reuse existing subsystems
        self._model = PredictionMarketModel()
        self._strategy = KalshiStrategy(StrategyConfig(
            max_contracts_per_order=config.risk_limits.max_orders_per_window,
        ))
        self._risk = PredictionMarketRisk(PredictionRiskConfig(
            max_notional_per_market_usd=config.risk_limits.max_notional_usd,
            max_contracts_per_order=min(50, config.risk_limits.max_orders_per_window),
        ))
        self._session_guard = get_session_guard()
        self._venue_gate = get_venue_gate()

        # Internal
        self._task: Optional[asyncio.Task] = None
        self._shutdown = asyncio.Event()
        self._resolved_markets: List[EventMarket] = []

    @property
    def agent_id(self) -> str:
        return self.config.agent_id

    # ── Lifecycle ──────────────────────────────────────────────────────

    async def start(self) -> None:
        """Start the agent decision loop."""
        if self.state.running:
            self.logger.warning(f"{self.config.name} already running")
            return
        self._shutdown.clear()
        self.state.running = True
        self.state.enabled = True
        self._task = asyncio.create_task(self._run_loop(), name=f"kalshi-agent-{self.config.name}")
        self.logger.info(
            f"Started {self.config.name}: assets={self.config.assets}, "
            f"timeframes={self.config.timeframes}"
        )

    async def stop(self) -> None:
        """Gracefully stop the agent."""
        self._shutdown.set()
        self.state.running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self.logger.info(f"Stopped {self.config.name}")

    def pause(self) -> None:
        """Pause trading (agent stays alive but skips cycles)."""
        self.state.enabled = False
        self.logger.info(f"Paused {self.config.name}")

    def resume(self) -> None:
        """Resume trading."""
        self.state.enabled = True
        self.logger.info(f"Resumed {self.config.name}")

    # ── Decision loop ──────────────────────────────────────────────────

    async def _run_loop(self) -> None:
        """Main decision loop — runs until shutdown."""
        cycle_interval = self._compute_cycle_interval()

        while not self._shutdown.is_set():
            try:
                if self.state.enabled:
                    await self._run_cycle()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                self.state.last_error = str(exc)
                self.state.errors.append(str(exc))
                if len(self.state.errors) > 50:
                    self.state.errors = self.state.errors[-50:]
                self.logger.error(f"Cycle error: {exc}")

            # Wait for next cycle or shutdown
            try:
                await asyncio.wait_for(
                    self._shutdown.wait(), timeout=cycle_interval
                )
                break  # shutdown was set
            except asyncio.TimeoutError:
                pass  # normal — time for next cycle

    async def _run_cycle(self) -> None:
        """Single decision cycle."""
        now = datetime.now(timezone.utc)
        self.state.last_cycle_at = now
        self.state.cycles_run += 1

        # 1. Session guard
        if not self._session_guard.is_trading_allowed(now):
            return

        # 2. Resolve markets
        await self._resolve_markets()
        if not self._resolved_markets:
            return

        # 3. Reset per-window order count if window rolled
        self._maybe_reset_window(now)

        # 4. Filter for the "most active" contract per asset/timeframe slot
        # Requirement: at most one active Kalshi contract at a time per slot.
        active_markets = self._filter_active_contracts(self._resolved_markets, now)

        # 5. Evaluate each filtered market
        for market in active_markets:
            if self._shutdown.is_set():
                break

            # Check entry window (already mostly handled by filter but good to be explicit)
            if not self._in_entry_window(market, now):
                continue

            # Check per-window order limit
            if self.state.orders_this_window >= self.config.risk_limits.max_orders_per_window:
                self.logger.debug(f"Order limit reached for window ({self.state.orders_this_window})")
                break

            # Build snapshot and evaluate
            try:
                snapshot = self._build_snapshot(market, now)
                signal = self._strategy.evaluate(snapshot, archetype=self.config.archetype)

                # Record every signal (including NO_ACTION) for audit
                self._record_signal(market, signal, snapshot, now)

                # Submit actionable signals to consensus engine via event bus
                if signal.action not in (SignalAction.NO_ACTION, SignalAction.HOLD):
                    try:
                        from merid.prediction.consensus_bridge import get_kalshi_consensus_adapter
                        from core.streaming_bus import get_event_bus, EventChannel, StreamEvent
                        adapter = get_kalshi_consensus_adapter()
                        energy = adapter.signal_to_energy(signal, market, self.agent_id)
                        # Publish as price_signal so ConsensusEngine._process_event picks it up
                        direction = energy["metadata"].get("direction", "neutral")
                        confidence = energy["metadata"].get("confidence", 0.5)
                        bus = get_event_bus()
                        await bus.publish(StreamEvent(
                            event_type="price_signal",
                            source=self.agent_id,
                            channel=EventChannel.AGENT_OUTPUT,
                            data={
                                "signal": "bullish" if direction == "long" else "bearish" if direction == "short" else "neutral",
                                "confidence": confidence,
                                "ticker": market.market_id,
                                "edge_pct": energy["metadata"].get("edge_pct", 0),
                                "action": energy["metadata"].get("action", ""),
                                "venue": "kalshi",
                            },
                        ))
                        self.logger.debug(f"Consensus vote published: {market.market_id} {signal.action} conf={confidence:.2f}")
                    except Exception as exc:
                        self.logger.debug(f"Consensus submission error (ignored): {exc}")

                if signal.action == SignalAction.NO_ACTION or signal.action == SignalAction.HOLD:
                    continue

                # Pre-trade risk check
                side_str = "yes" if signal.action in (SignalAction.BUY_YES, SignalAction.SELL_YES) else "no"
                price_cents = Decimal(str(signal.limit_price_cents)) if signal.limit_price_cents else Decimal("50")
                event_id = market.market_id.rsplit("-", 1)[0] if "-" in market.market_id else market.market_id
                
                # If it's a quote, we skip individual check_order here and handle in _execute_signal
                # or just use best available price for the check
                check_price = price_cents
                if signal.action == SignalAction.QUOTE:
                    check_price = Decimal(str(signal.bid_price_cents or 50))

                check = self._risk.check_order(
                    market_id=market.market_id,
                    event_id=event_id,
                    side=side_str,
                    contracts=signal.contracts,
                    price_cents=check_price,
                    edge=signal.edge.net_edge if signal.edge else Decimal("0"),
                )

                if not check.allowed:
                    self._record_explainability_decision(
                        market=market,
                        signal=signal,
                        snapshot=snapshot,
                        check=check,
                        now=now,
                        allowed=False,
                    )
                    self.logger.info(f"Risk blocked {market.market_id}: {check.reason}")
                    continue

                self._record_explainability_decision(
                    market=market,
                    signal=signal,
                    snapshot=snapshot,
                    check=check,
                    now=now,
                    allowed=True,
                )

                # Place order via tool
                await self._execute_signal(market, signal, check, snapshot)

            except Exception as exc:
                self.logger.warning(f"Error evaluating {market.market_id}: {exc}")

    def _filter_active_contracts(self, markets: List[EventMarket], now: datetime) -> List[EventMarket]:
        """Filter resolved markets to ensure only the most relevant contract(s) are traded.
        
        Rule: At most one active contract per asset/timeframe slot.
        If agent has a specific asset list, return best for each.
        If agent is category-wide, group by inferred asset and return best for each.
        """
        if not markets:
            return []

        # Group by asset
        by_asset: Dict[str, List[EventMarket]] = {}
        for m in markets:
            asset = "OTHER"
            # Try to infer asset from ticker or tags
            ticker_upper = m.market_id.upper()
            found = False
            for a in ["BTC", "ETH", "SOL", "XRP", "DOGE", "PEPE", "WIF"]:
                if a in ticker_upper:
                    asset = a
                    found = True
                    break
            
            if not found and m.category:
                asset = m.category.upper()

            if asset not in by_asset:
                by_asset[asset] = []
            by_asset[asset].append(m)

        active_selection = []
        for asset, asset_markets in by_asset.items():
            # Sort by end_date (closest to expiry first)
            sorted_m = sorted(
                [m for m in asset_markets if m.end_date and m.end_date > now],
                key=lambda m: m.end_date
            )
            
            if not sorted_m:
                continue

            # Find the first one in the entry window
            best_for_asset = None
            for m in sorted_m:
                if self._in_entry_window(m, now):
                    best_for_asset = m
                    break
            
            # Fallback to the closest one if none in window
            if not best_for_asset:
                best_for_asset = sorted_m[0]
            
            active_selection.append(best_for_asset)

        return active_selection

    # ── Market resolution ──────────────────────────────────────────────

    async def _resolve_markets(self) -> None:
        """Resolve config filters into live Kalshi market tickers."""
        try:
            from merid.prediction.kalshi_tools import _kalshi_list_markets

            # Use parameters from config
            category = self.config.category
            asset = self.config.assets[0] if self.config.assets else ""
            timeframe = self.config.timeframes[0] if self.config.timeframes else ""

            result = await _kalshi_list_markets(
                category=category,
                timeframe=timeframe,
                asset=asset,
                limit=self.config.risk_limits.max_orders_per_window * 3,
            )

            if not result.success:
                self.logger.debug(f"Market resolution failed: {result.error_message}")
                return

            # Convert tool result back to EventMarket-like objects for strategy
            self._resolved_markets = []
            for m in result.payload.get("markets", []):
                from merid.event_venues.base import EventMarket, EventOutcome
                outcomes = [
                    EventOutcome(
                        outcome_id=o["id"],
                        outcome_name=o["name"],
                        price=Decimal(o["price"]),
                        probability=Decimal(o["probability"]) if o.get("probability") else None,
                    )
                    for o in m.get("outcomes", [])
                ]
                em = EventMarket(
                    market_id=m["ticker"],
                    venue="kalshi",
                    question=m.get("question", ""),
                    description="",
                    outcomes=outcomes,
                    category=m.get("category"),
                    tags=m.get("tags", []),
                    end_date=datetime.fromisoformat(m["end_date"]) if m.get("end_date") else None,
                    active=m.get("active", True),
                    volume=Decimal(m.get("volume", "0")),
                    open_interest=Decimal(m.get("open_interest", "0")),
                )
                self._resolved_markets.append(em)

            tickers = [m.market_id for m in self._resolved_markets]
            self.state.active_tickers = tickers[:20]

        except Exception as exc:
            self.logger.warning(f"Market resolution error: {exc}")

    # ── Helpers ────────────────────────────────────────────────────────

    def _in_entry_window(self, market: EventMarket, now: datetime) -> bool:
        """Check if now is within the agent's entry window for this market."""
        if not market.end_date:
            return True  # No expiry info — allow

        ew = self.config.entry_window
        window_open = market.end_date - timedelta(minutes=ew.minutes_before_expiry)
        window_close = market.end_date - timedelta(minutes=ew.cutoff_minutes_before_expiry)

        return window_open <= now <= window_close

    def _build_snapshot(self, market: EventMarket, now: datetime) -> MarketSnapshot:
        """Build a MarketSnapshot from an EventMarket for strategy consumption."""
        yes_price = Decimal("50")
        no_price = Decimal("50")
        for o in market.outcomes:
            if o.outcome_id == "yes":
                yes_price = o.price * 100  # Convert back to cents
            elif o.outcome_id == "no":
                no_price = o.price * 100

        # Compute time to expiry
        tte_hours = None
        if market.end_date:
            delta = market.end_date - now
            tte_hours = Decimal(str(max(delta.total_seconds() / 3600, 0)))

        implied = self._model.implied_probabilities(
            yes_bid=max(yes_price - 1, Decimal("1")),
            yes_ask=yes_price,
            no_bid=max(no_price - 1, Decimal("1")),
            no_ask=no_price,
        )

        state = ContractState.TRADING if market.active else ContractState.CLOSED

        snapshot = MarketSnapshot(
            market_id=market.market_id,
            event_id=market.market_id.rsplit("-", 1)[0] if "-" in market.market_id else market.market_id,
            title=market.question,
            state=state,
            implied=implied,
            volume=market.volume or Decimal("0"),
            open_interest=market.open_interest or Decimal("0"),
            time_to_expiry_hours=tte_hours,
            close_time=market.end_date,
            category=market.category,
            timestamp=now,
        )

        # Inject fear/greed sentiment scores
        try:
            from merid.event_venues.kalshi.sentiment import get_sentiment_service
            svc = get_sentiment_service()
            # Feed latest data point so the service stays current
            svc.update_market(
                market.market_id,
                prob=float(implied.yes_prob),
                volume=float(market.volume or 0),
                category=(market.category or "unknown").lower(),
            )
            local_s = svc.market_score(market.market_id)
            cat_s   = svc.category_score((market.category or "unknown").lower())
            glob_s  = svc.global_score()
            snapshot.sentiment_local    = local_s.score if local_s else None
            snapshot.sentiment_category = cat_s.score
            snapshot.sentiment_global   = glob_s.score
            snapshot.sentiment_regime   = local_s.regime if local_s else glob_s.regime
        except Exception:
            pass

        # Compute edges for both sides using the model
        asset = self.config.assets[0] if self.config.assets else None
        strike = None
        try:
            from merid.event_venues.kalshi.market_catalog import get_market_catalog
            catalog = get_market_catalog()
            m = catalog.get_market(market.market_id)
            if m:
                strike = m.strike_price
        except Exception:
            pass

        snapshot.edges = [
            self._model.compute_edge(
                market_id=market.market_id, 
                implied=implied, 
                side="yes", 
                action="buy",
                asset=asset,
                strike_price=strike
            ),
            self._model.compute_edge(
                market_id=market.market_id, 
                implied=implied, 
                side="no", 
                action="buy",
                asset=asset,
                strike_price=strike
            ),
        ]

        return snapshot

    def _compute_cycle_interval(self) -> float:
        """Compute sleep between cycles based on timeframe."""
        tf = self.config.timeframes[0] if self.config.timeframes else "1h"
        intervals = {
            "15m": 30.0,       # Check every 30s for 15m markets
            "1h": 60.0,        # Every 60s for hourly
            "daily": 300.0,    # Every 5min for daily
            "weekly": 600.0,   # Every 10min for weekly
            "pre-market": 60.0,
        }
        return intervals.get(tf, 60.0)

    def _maybe_reset_window(self, now: datetime) -> None:
        """Reset per-window order count when a new window starts."""
        tf = self.config.timeframes[0] if self.config.timeframes else "1h"
        window_minutes = {"15m": 15, "1h": 60, "daily": 1440, "weekly": 10080, "pre-market": 120}
        window_dur = timedelta(minutes=window_minutes.get(tf, 60))

        if self.state.window_start is None or (now - self.state.window_start) >= window_dur:
            self.state.window_start = now
            self.state.orders_this_window = 0

    def _record_signal(
        self, market: EventMarket, signal: StrategySignal,
        snapshot: MarketSnapshot, now: datetime,
    ) -> None:
        """Persist a strategy signal to the agent's signal log."""
        entry = {
            "ts": now.isoformat(),
            "market_id": market.market_id,
            "question": market.question[:120] if market.question else "",
            "action": signal.action.value if hasattr(signal.action, "value") else str(signal.action),
            "contracts": signal.contracts,
            "limit_price_cents": signal.limit_price_cents,
            "edge": float(signal.edge.net_edge) if (signal.edge and hasattr(signal.edge, 'net_edge')) else None,
            "confidence": float(signal.edge.confidence) if (signal.edge and hasattr(signal.edge, 'confidence')) else None,
            "implied_yes": float(snapshot.implied.yes_prob) if snapshot.implied else None,
            "implied_no": float(snapshot.implied.no_prob) if snapshot.implied else None,
            "expiry_phase": str(signal.phase) if signal.phase else None,
        }
        self.state.signal_log.append(entry)
        if len(self.state.signal_log) > _MAX_LOG_ENTRIES:
            self.state.signal_log = self.state.signal_log[-_MAX_LOG_ENTRIES:]

    def _record_explainability_decision(
        self,
        *,
        market: EventMarket,
        signal: StrategySignal,
        snapshot: MarketSnapshot,
        check: PreTradeCheck,
        now: datetime,
        allowed: bool,
    ) -> None:
        """Record a structured decision rationale in the global explainability tracker."""
        try:
            from agents.explainability import DecisionType, create_reasoning_builder, get_explainability_tracker

            action_value = signal.action.value if hasattr(signal.action, "value") else str(signal.action)
            confidence = float(signal.edge.confidence) if signal.edge and hasattr(signal.edge, "confidence") else 0.0
            edge_value = float(signal.edge.net_edge) if signal.edge and hasattr(signal.edge, "net_edge") else 0.0

            builder = create_reasoning_builder(self.config.name, DecisionType.ACTION)
            builder.set_decision(f"{action_value} {signal.contracts}x {market.market_id}", confidence)
            builder.set_primary_reason(
                f"{action_value} decision for {market.market_id} with edge={edge_value:.4f}"
            )
            builder.add_supporting_factor(f"edge={edge_value:.4f}")
            builder.add_supporting_factor(f"allowed={allowed}")
            if check.adjusted_size and check.adjusted_size != signal.contracts:
                builder.add_contrary_factor(
                    f"risk downsize from {signal.contracts} to {check.adjusted_size}"
                )
            if not allowed:
                builder.add_contrary_factor(f"risk blocked: {check.reason}")

            for source in ("kalshi_market_catalog", "kalshi_order_router", "prediction_risk"):
                builder.add_data_source(source)

            builder.set_market_context(
                {
                    "market_id": market.market_id,
                    "question": market.question,
                    "timestamp": now.isoformat(),
                    "implied_yes": float(snapshot.implied.yes_prob) if snapshot.implied else None,
                    "implied_no": float(snapshot.implied.no_prob) if snapshot.implied else None,
                    "volume": float(snapshot.volume) if snapshot.volume is not None else 0.0,
                    "open_interest": float(snapshot.open_interest) if snapshot.open_interest is not None else 0.0,
                }
            )
            builder.set_risk_assessment(
                {
                    "allowed": allowed,
                    "reason": check.reason,
                    "adjusted_size": check.adjusted_size,
                    "estimated_fee": str(check.estimated_fee) if hasattr(check, "estimated_fee") else None,
                }
            )

            reasoning = builder.build()
            get_explainability_tracker().record_decision(reasoning)
        except Exception as exc:
            self.logger.debug(f"Explainability decision record skipped: {exc}")

    async def _execute_signal(
        self, market: EventMarket, signal: StrategySignal, check: PreTradeCheck,
        snapshot: Optional[MarketSnapshot] = None,
    ) -> None:
        """Execute a strategy signal by placing an order."""
        from merid.prediction.kalshi_tools import _kalshi_place_order
        from merid.prediction.agent_performance_tracker import get_agent_performance_tracker

        action_map = {
            SignalAction.BUY_YES: ("yes", "buy"),
            SignalAction.BUY_NO: ("no", "buy"),
            SignalAction.SELL_YES: ("yes", "sell"),
            SignalAction.SELL_NO: ("no", "sell"),
            SignalAction.QUOTE: ("yes", "quote"), # Special handling for quotes
        }

        if signal.action not in action_map:
            return

        side, action = action_map[signal.action]
        size = check.adjusted_size if check.adjusted_size else signal.contracts
        
        if action == "quote":
            # For quotes, we might place two limit orders or use a special tool
            # For now, let's place a buy and sell if prices are provided
            if signal.bid_price_cents:
                await _kalshi_place_order(
                    ticker=market.market_id,
                    side="yes",
                    action="buy",
                    price_cents=signal.bid_price_cents,
                    count=size,
                )
            if signal.ask_price_cents:
                await _kalshi_place_order(
                    ticker=market.market_id,
                    side="yes",
                    action="sell",
                    price_cents=signal.ask_price_cents,
                    count=size,
                )
            # Record as a single "quote" event in logs
            result_success = True
            result_payload = {
                "simulated": self._venue_gate.should_simulate_fill(), 
                "order_id": "quote_group"
            }
            result_error = None
        else:
            price_cents = signal.limit_price_cents or 0
            result = await _kalshi_place_order(
                ticker=market.market_id,
                side=side,
                action=action,
                price_cents=price_cents,
                count=size,
            )
            result_success = result.success
            result_payload = result.payload
            result_error = result.error_message

        now_ts = datetime.now(timezone.utc)
        ref_bid = float(snapshot.implied.yes_bid) if snapshot and snapshot.implied.yes_bid else None
        ref_ask = float(snapshot.implied.yes_ask) if snapshot and snapshot.implied.yes_ask else None
        ref_mid = (ref_bid + ref_ask) / 2 if ref_bid and ref_ask else None

        # Record order
        order_entry = {
            "ts": now_ts.isoformat(),
            "market_id": market.market_id,
            "question": market.question[:120] if market.question else "",
            "side": side,
            "action": action,
            "price_cents": signal.limit_price_cents if action != "quote" else None,
            "bid_price": signal.bid_price_cents,
            "ask_price": signal.ask_price_cents,
            "contracts": size,
            "ref_bid": ref_bid,
            "ref_ask": ref_ask,
            "ref_mid": ref_mid,
            "success": result_success,
            "simulated": result_payload.get("simulated", False) if result_success else None,
            "error": result_error if not result_success else None,
        }
        self.state.order_log.append(order_entry)
        if len(self.state.order_log) > _MAX_LOG_ENTRIES:
            self.state.order_log = self.state.order_log[-_MAX_LOG_ENTRIES:]

        if result_success:
            self.state.orders_placed += 1
            self.state.orders_this_window += 1

            # Record fill (assume immediate for now in MM/Arb)
            fill_entry = {
                "ts": now_ts.isoformat(),
                "market_id": market.market_id,
                "side": side,
                "action": action,
                "price_cents": signal.limit_price_cents if action != "quote" else None,
                "contracts": size,
                "ref_bid": ref_bid,
                "ref_ask": ref_ask,
                "ref_mid": ref_mid,
                "simulated": result_payload.get("simulated", False),
                "fill_id": result_payload.get("order_id") or result_payload.get("fill_id"),
                "agent": self.config.name,
            }
            self.state.fill_log.append(fill_entry)
            if len(self.state.fill_log) > _MAX_LOG_ENTRIES:
                self.state.fill_log = self.state.fill_log[-_MAX_LOG_ENTRIES:]

            # Emit event bus event
            try:
                from core.event_bus import event_stream
                await event_stream.publish("kalshi:order_filled", fill_entry)
            except Exception as exc:
                self.logger.debug(f"Event bus publish error (ignored): {exc}")

            # Record fill in performance tracker
            try:
                tracker = get_agent_performance_tracker()
                tracker.record_fill(
                    agent_id=self.agent_id,
                    market_id=market.market_id,
                    side=side,
                    price_cents=signal.limit_price_cents or 50,
                    contracts=size,
                    predicted_edge=float(signal.edge.net_edge) if signal.edge else 0.0,
                    confidence=float(signal.confidence) if hasattr(signal, 'confidence') else 0.5,
                )
            except Exception as exc:
                self.logger.debug(f"Performance tracker record error (ignored): {exc}")

            # Wire fill into KalshiRiskManager so risk/sizing endpoints see live flow
            try:
                from merid.event_venues.kalshi.kalshi_risk import get_kalshi_risk
                risk_mgr = get_kalshi_risk()
                price_cents = signal.limit_price_cents or 50
                category = getattr(self.config, 'category', None)
                risk_mgr.record_order(category=category, contracts=size, price_cents=price_cents)
                # Estimate immediate PnL from edge (realized on fill for market-making)
                if signal.edge and hasattr(signal.edge, 'net_edge'):
                    pnl_usd = float(signal.edge.net_edge) * size * (price_cents / 100.0)
                    risk_mgr.record_pnl(pnl_usd)
            except Exception as exc:
                self.logger.debug(f"KalshiRiskManager record error (ignored): {exc}")

            # Record fill in paper session for per-interval PnL tracking
            try:
                from merid.prediction.paper_session import get_paper_session
                session = get_paper_session()
                if session.is_active:
                    edge_cents = float(signal.edge.net_edge * 100) if signal.edge else 0.0
                    fee_cents = float(check.estimated_fee * 100) if hasattr(check, 'estimated_fee') and check.estimated_fee else 0.0
                    session.record_fill(
                        agent_name=self.config.name,
                        pnl_cents=edge_cents * size,
                        fees_cents=fee_cents * size,
                    )
            except Exception as exc:
                self.logger.debug(f"Paper session record error (ignored): {exc}")

            # Record decision in ReflectionSystem for learning/persistence
            try:
                from agents.reflection.integration import get_reflection_system
                reflection_sys = get_reflection_system()
                action_str = signal.action.value if hasattr(signal.action, "value") else str(signal.action)
                confidence = float(signal.edge.confidence) if signal.edge and hasattr(signal.edge, "confidence") else 0.5
                edge_val = float(signal.edge.net_edge) if signal.edge and hasattr(signal.edge, "net_edge") else 0.0
                reflection_sys.record_decision(
                    agent_id=self.agent_id,
                    energy_id=f"{market.market_id}:{now_ts.isoformat()}",
                    decision="accept",
                    confidence=confidence,
                    reasoning=f"{action_str} {size}x {market.market_id} edge={edge_val:.4f}",
                    market_context={
                        "market_id": market.market_id,
                        "question": market.question[:120] if market.question else "",
                        "side": side,
                        "action": action,
                        "price_cents": signal.limit_price_cents,
                        "contracts": size,
                        "edge": edge_val,
                        "implied_yes": float(snapshot.implied.yes_prob) if snapshot and snapshot.implied else None,
                        "implied_no": float(snapshot.implied.no_prob) if snapshot and snapshot.implied else None,
                        "simulated": result_payload.get("simulated", False),
                    },
                    agent_state=self.state.to_dict(),
                )
            except Exception as exc:
                self.logger.debug(f"ReflectionSystem record error (ignored): {exc}")

            self.logger.info(
                f"Order placed: {action} {size}x {side} {market.market_id} "
                f"@{price_cents}c (sim={result_payload.get('simulated', False)})"
            )
        else:
            # Record error in paper session
            try:
                from merid.prediction.paper_session import get_paper_session
                session = get_paper_session()
                if session.is_active:
                    session.record_error(self.config.name)
            except Exception:
                pass
            self.logger.warning(
                f"Order failed for {market.market_id}: {result_error}"
            )

    def summary(self) -> Dict[str, Any]:
        """JSON-serialisable agent summary."""
        return {
            **self.state.to_dict(),
            "config": {
                "assets": self.config.assets,
                "timeframes": self.config.timeframes,
                "risk_limits": {
                    "max_yes_position": self.config.risk_limits.max_yes_position,
                    "max_no_position": self.config.risk_limits.max_no_position,
                    "max_orders_per_window": self.config.risk_limits.max_orders_per_window,
                    "max_notional_usd": str(self.config.risk_limits.max_notional_usd),
                },
                "entry_window": {
                    "minutes_before_expiry": self.config.entry_window.minutes_before_expiry,
                    "cutoff_minutes_before_expiry": self.config.entry_window.cutoff_minutes_before_expiry,
                },
            },
        }

    def get_signals(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Return recent strategy signals."""
        return self.state.signal_log[-limit:]

    def get_orders(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Return recent orders."""
        return self.state.order_log[-limit:]

    def get_fills(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Return recent fills."""
        return self.state.fill_log[-limit:]
