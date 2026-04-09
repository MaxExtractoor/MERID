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
from merid.prediction.no_trade_reasons import get_no_trade_tracker, NoTradeReason
from merid.event_venues.base import EventMarket
from merid.event_venues.kalshi.stop_loss import StopLossRules, TrackedPosition
import os

from utils.logger import get_logger


_MAX_LOG_ENTRIES = 200

# ── Swarm degraded-mode limits (AUDIT-10) ────────────────────────────────────
# When the swarm consensus has been unavailable for longer than _MAX_SOLO_SECONDS
# the agent is allowed to trade on its own signal without waiting for quorum.
# _MAX_SOLO_TRADES_DEGRADED caps how many such degraded-mode trades are allowed
# before the agent pauses and waits for the swarm to recover.
#
# Both values are env-overridable so operators can tune per deployment without
# a code change.
#   MERID_AGENT_MAX_SOLO_SECONDS   — seconds of swarm silence before solo trading
#   MERID_AGENT_MAX_SOLO_TRADES    — max consecutive solo trades while degraded
_MAX_SOLO_SECONDS: float = float(
    os.getenv("MERID_AGENT_MAX_SOLO_SECONDS", "300")
)  # default: 5 minutes
_MAX_SOLO_TRADES_DEGRADED: int = int(
    os.getenv("MERID_AGENT_MAX_SOLO_TRADES", "3")
)


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
        _strategy_config = StrategyConfig(
            max_contracts_per_order=config.risk_limits.max_orders_per_window,
        )
        # Apply crypto-specific edge thresholds when this is a crypto agent
        try:
            from merid.prediction.crypto_thresholds import apply_crypto_strategy_thresholds_to_config
            apply_crypto_strategy_thresholds_to_config(
                _strategy_config,
                agent_name=config.name,
                assets=config.assets,
            )
        except Exception as _cte:
            self.logger.debug("crypto_threshold_apply skipped: %s", _cte)
        self._strategy = KalshiStrategy(_strategy_config)
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

        # Per-agent singleton risk manager — instantiated once so daily state
        # and open-exposure tracking persist across _execute_signal calls.
        self._btc15m_risk: Optional[Any] = None

        # Stop-loss rules engine — monitors open positions every cycle
        self._stop_loss = StopLossRules()
        # position_id -> TrackedPosition for open fills awaiting settlement
        self._tracked_positions: Dict[str, TrackedPosition] = {}

        # ── Swarm degraded-mode tracking (AUDIT-10) ──────────────────────────
        # Timestamp of the last time consensus was successfully obtained.
        self._last_consensus_at: Optional[float] = None
        # Reserved slot: consensus coordinator reference (used in tests / future wiring).
        self._consensus_coordinator: Optional[Any] = None
        # Count of consecutive solo trades taken while swarm was degraded.
        self._solo_trades_taken: int = 0

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
        # D14: Defensive clear on (re)start — ensures no stale positions
        # from a previous run survive into the new session.
        if self._tracked_positions:
            self.logger.debug(
                "start: clearing %d residual tracked positions from previous run",
                len(self._tracked_positions),
            )
            self._tracked_positions.clear()
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
        # D14 / W9: Clear tracked positions so stale entries don't trigger
        # spurious stop-loss closes if the agent is restarted.
        # Warn if any positions have in-flight (pending/partial) fills so
        # operators know orders may still be working on the venue.
        stale_count = len(self._tracked_positions)
        if stale_count:
            in_flight = [
                pos.ticker for pos in self._tracked_positions.values()
                if getattr(pos, "fill_status", "filled") in ("pending", "partial")
            ]
            if in_flight:
                self.logger.warning(
                    "stop: %d in-flight positions cleared — orders may still be "
                    "working on venue: %s",
                    len(in_flight), in_flight,
                )
            self._tracked_positions.clear()
            self.logger.debug(
                "stop: cleared %d stale tracked positions (%d in-flight)",
                stale_count, len(in_flight) if stale_count else 0,
            )
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
        # FIX-1: Yield to event loop scheduler at start of each cycle to prevent starvation
        # when cycle completes quickly (agent paused, session guard blocked, no markets, etc.)
        # Reference: https://til.simonwillison.net/python/yielding-in-asyncio
        await asyncio.sleep(0)

        now = datetime.now(timezone.utc)
        self.state.last_cycle_at = now
        self.state.cycles_run += 1

        # Cycle veto/action counters for INFO summary at end
        cycle_stats = {
            "candidates_total": 0,
            "veto_session_guard": 0,
            "veto_no_markets": 0,
            "veto_entry_window": 0,
            "veto_order_limit": 0,
            "veto_no_action": 0,
            "veto_consensus_conflicted": 0,
            "veto_consensus_forming": 0,
            "veto_degraded_pause": 0,
            "veto_risk": 0,
            "orders_attempted": 0,
            "orders_succeeded": 0,
        }

        # 0. Stop-loss sweep — check all open positions before new signals
        await self._check_stop_losses()

        # 1. Session guard
        if not self._session_guard.is_trading_allowed(now):
            reason = self._session_guard.block_reason(now)
            self.logger.info(
                "[AGENT-VETO] session_guard | agent=%s reason=%s",
                self.config.name, reason
            )
            cycle_stats["veto_session_guard"] = 1
            self._log_cycle_summary(cycle_stats)
            return

        # 2. Resolve markets
        await self._resolve_markets()
        if not self._resolved_markets:
            self.logger.info(
                "[AGENT-VETO] no_markets | agent=%s resolved=0",
                self.config.name
            )
            cycle_stats["veto_no_markets"] = 1
            self._log_cycle_summary(cycle_stats)
            return

        # 3. Reset per-window order count if window rolled
        self._maybe_reset_window(now)

        # 4. Filter for the "most active" contract per asset/timeframe slot
        # Requirement: at most one active Kalshi contract at a time per slot.
        active_markets = self._filter_active_contracts(self._resolved_markets, now)
        cycle_stats["candidates_total"] = len(active_markets)

        if not active_markets:
            self.logger.debug(
                "[AGENT-VETO] no_active_markets | agent=%s resolved=%d "
                "all markets expired or have no end_date",
                self.config.name, len(self._resolved_markets),
            )
            cycle_stats["veto_no_markets"] = 1
            self._log_cycle_summary(cycle_stats)
            return

        # 5. Evaluate each filtered market
        for market in active_markets:
            # FIX-1: Yield between market evaluations to prevent long bursts
            # when processing many markets without giving other tasks a chance to run.
            await asyncio.sleep(0)

            if self._shutdown.is_set():
                break

            # Check entry window (already mostly handled by filter but good to be explicit)
            if not self._in_entry_window(market, now):
                cycle_stats["veto_entry_window"] += 1
                # Debug: show how long until the window opens so operators can diagnose blackouts
                if market.end_date:
                    ew = self.config.entry_window
                    window_open = market.end_date - timedelta(minutes=ew.minutes_before_expiry)
                    if now < window_open:
                        wait = window_open - now
                        self.logger.debug(
                            "[AGENT-VETO] entry_window | agent=%s market=%s "
                            "window_opens_in=%dm%ds (entry_window=%dmin cutoff=%dmin)",
                            self.config.name, market.market_id,
                            int(wait.total_seconds() // 60),
                            int(wait.total_seconds() % 60),
                            ew.minutes_before_expiry,
                            ew.cutoff_minutes_before_expiry,
                        )
                continue

            # Check per-window order limit
            if self.state.orders_this_window >= self.config.risk_limits.max_orders_per_window:
                self.logger.info(
                    "[AGENT-VETO] order_limit | agent=%s limit=%d current=%d",
                    self.config.name,
                    self.config.risk_limits.max_orders_per_window,
                    self.state.orders_this_window
                )
                cycle_stats["veto_order_limit"] += 1
                break

            # Build snapshot and evaluate
            try:
                snapshot = self._build_snapshot(market, now)
                
                # === Market Mood Bus Integration ===
                # Get unified context from the mood bus
                asset = self.config.assets[0] if self.config.assets else ""
                timeframe = self.config.timeframes[0] if self.config.timeframes else ""
                mood_context = self._get_mood_context(asset, timeframe)
                
                # Inject mood context into snapshot
                if mood_context:
                    snapshot.sentiment_global = mood_context.fg_index / 100.0  # Normalize 0-1
                    snapshot.sentiment_regime = mood_context.volatility_regime.value
                    self.logger.debug(
                        f"Mood context: FG={mood_context.fg_index}, "
                        f"vol={mood_context.volatility_regime.value}, "
                        f"tags={mood_context.tags}"
                    )
                
                signal = self._strategy.evaluate(snapshot, archetype=self.config.archetype)

                # Record every signal (including NO_ACTION) for audit
                self._record_signal(market, signal, snapshot, now)

                # === Submit to SwarmConsensusAggregator ===
                # Only actionable signals go to consensus
                if signal.action not in (SignalAction.NO_ACTION, SignalAction.HOLD):
                    self._submit_to_consensus(market, signal, snapshot, mood_context)

                    # Check if we have consensus before acting
                    # For MM agents, use specialized MM consensus resolution
                    if self.config.archetype == "market_maker":
                        mm_mode = getattr(self._strategy.config, 'mm_consensus_mode', 'full')
                        consensus = self._resolve_consensus_for_mm(asset, timeframe, mm_mode)
                    else:
                        consensus = self._get_consensus(asset, timeframe, wait_for_ready=False)

                    if consensus and consensus.status.value == "ready":
                        # Record last successful consensus time for degraded-mode tracking
                        self._last_consensus_at = time.monotonic()
                        self._solo_trades_taken = 0  # reset solo counter on swarm recovery

                        # Check if consensus direction matches our signal
                        signal_dir = "yes" if signal.action in (SignalAction.BUY_YES, SignalAction.SELL_YES) else "no"
                        if consensus.consensus_direction != signal_dir:
                            tracker = get_no_trade_tracker()
                            tracker.record(
                                agent_name=self.config.name,
                                market_id=market.market_id,
                                asset=asset,
                                timeframe=timeframe,
                                reason=NoTradeReason.CONSENSUS_MISMATCH,
                                net_edge=float(signal.edge.net_edge) if signal.edge else None,
                                consensus_status="ready",
                                additional_context={
                                    "signal_dir": signal_dir,
                                    "consensus_dir": consensus.consensus_direction,
                                },
                            )

                            self.logger.info(
                                "[AGENT-VETO] consensus_mismatch | agent=%s market=%s signal=%s consensus=%s",
                                self.config.name, market.market_id, signal_dir, consensus.consensus_direction
                            )
                            cycle_stats["veto_consensus_conflicted"] += 1
                            continue

                        # Use consensus confidence for sizing
                        if signal.edge and hasattr(signal.edge, 'confidence'):
                            signal.edge.confidence = consensus.consensus_confidence

                        self.logger.info(
                            f"Consensus aligned: {consensus.consensus_direction} @ "
                            f"{consensus.consensus_probability:.1%} "
                            f"(size={consensus.size_band})"
                        )
                    elif consensus and consensus.status.value == "conflicted":
                        tracker = get_no_trade_tracker()
                        tracker.record(
                            agent_name=self.config.name,
                            market_id=market.market_id,
                            asset=asset,
                            timeframe=timeframe,
                            reason=NoTradeReason.CONSENSUS_CONFLICTED,
                            net_edge=float(signal.edge.net_edge) if signal.edge else None,
                            consensus_status="conflicted",
                            additional_context={
                                "disagreement_flags": consensus.disagreement_flags,
                            },
                        )

                        self.logger.info(
                            "[AGENT-VETO] consensus_conflicted | agent=%s market=%s flags=%s",
                            self.config.name, market.market_id, consensus.disagreement_flags
                        )
                        cycle_stats["veto_consensus_conflicted"] += 1
                        continue
                    elif not consensus:
                        # ── AUDIT-10: Swarm degraded-mode check ─────────────────
                        # If the swarm has been silent for longer than _MAX_SOLO_SECONDS
                        # allow the agent to trade on its own signal, up to
                        # _MAX_SOLO_TRADES_DEGRADED trades, then pause.
                        # EXCEPTION: MM agents in soft/bypass mode skip this check
                        if self.config.archetype == "market_maker":
                            mm_mode = getattr(self._strategy.config, 'mm_consensus_mode', 'full')
                            if mm_mode in ("soft", "bypass"):
                                # MM in soft/bypass: consensus=None is expected, proceed
                                pass
                            else:
                                # MM in full mode: apply standard degraded logic
                                now_mono = time.monotonic()
                                swarm_silence = (
                                    now_mono - self._last_consensus_at
                                    if self._last_consensus_at is not None
                                    else float("inf")
                                )
                                if swarm_silence >= _MAX_SOLO_SECONDS:
                                    if self._solo_trades_taken < _MAX_SOLO_TRADES_DEGRADED:
                                        self.logger.warning(
                                            "DEGRADED_MODE market=%s swarm_silence=%.0fs "
                                            "solo_trade=%d/%d — proceeding without consensus",
                                            market.market_id,
                                            swarm_silence,
                                            self._solo_trades_taken + 1,
                                            _MAX_SOLO_TRADES_DEGRADED,
                                        )
                                        # Allow the signal through; increment solo counter
                                        # after a successful order attempt (below)
                                    else:
                                        self.logger.info(
                                            "[AGENT-VETO] degraded_mode_paused | agent=%s market=%s solo_limit=%d",
                                            self.config.name, market.market_id, _MAX_SOLO_TRADES_DEGRADED
                                        )
                                        cycle_stats["veto_degraded_pause"] += 1
                                        continue
                                else:
                                    tracker = get_no_trade_tracker()
                                    tracker.record(
                                        agent_name=self.config.name,
                                        market_id=market.market_id,
                                        asset=asset,
                                        timeframe=timeframe,
                                        reason=NoTradeReason.CONSENSUS_FORMING,
                                        net_edge=float(signal.edge.net_edge) if signal.edge else None,
                                        consensus_status="forming",
                                    )

                                    self.logger.info(
                                        "[AGENT-VETO] consensus_forming | agent=%s market=%s",
                                        self.config.name, market.market_id
                                    )
                                    cycle_stats["veto_consensus_forming"] += 1
                                    continue
                        else:
                            # Non-MM agent: standard degraded-mode logic
                            now_mono = time.monotonic()
                            swarm_silence = (
                                now_mono - self._last_consensus_at
                                if self._last_consensus_at is not None
                                else float("inf")
                            )
                            if swarm_silence >= _MAX_SOLO_SECONDS:
                                if self._solo_trades_taken < _MAX_SOLO_TRADES_DEGRADED:
                                    self.logger.warning(
                                        "DEGRADED_MODE market=%s swarm_silence=%.0fs "
                                        "solo_trade=%d/%d — proceeding without consensus",
                                        market.market_id,
                                        swarm_silence,
                                        self._solo_trades_taken + 1,
                                        _MAX_SOLO_TRADES_DEGRADED,
                                    )
                                    # Allow the signal through; increment solo counter
                                    # after a successful order attempt (below)
                                else:
                                    self.logger.info(
                                        "[AGENT-VETO] degraded_mode_paused | agent=%s market=%s solo_limit=%d",
                                        self.config.name, market.market_id, _MAX_SOLO_TRADES_DEGRADED
                                    )
                                    cycle_stats["veto_degraded_pause"] += 1
                                    continue
                            else:
                                tracker = get_no_trade_tracker()
                                tracker.record(
                                    agent_name=self.config.name,
                                    market_id=market.market_id,
                                    asset=asset,
                                    timeframe=timeframe,
                                    reason=NoTradeReason.CONSENSUS_FORMING,
                                    net_edge=float(signal.edge.net_edge) if signal.edge else None,
                                    consensus_status="forming",
                                )

                                self.logger.info(
                                    "[AGENT-VETO] consensus_forming | agent=%s market=%s",
                                    self.config.name, market.market_id
                                )
                                cycle_stats["veto_consensus_forming"] += 1
                                continue
            except Exception as exc:
                self.logger.warning(f"Error evaluating {market.market_id}: {exc}")
                continue

            if signal.action == SignalAction.NO_ACTION or signal.action == SignalAction.HOLD:
                # Track reason for no-action
                tracker = get_no_trade_tracker()

                # Determine specific reason from signal.reason field
                reason_text = signal.reason.lower() if hasattr(signal, 'reason') else ""
                if "edge" in reason_text and "below" in reason_text:
                    reason_enum = NoTradeReason.EDGE_BELOW_THRESHOLD
                elif "confidence" in reason_text:
                    reason_enum = NoTradeReason.CONFIDENCE_BELOW_THRESHOLD
                elif "kelly" in reason_text:
                    reason_enum = NoTradeReason.KELLY_SIZE_ZERO
                elif "liquidity" in reason_text or "volume" in reason_text or "oi" in reason_text:
                    reason_enum = NoTradeReason.LIQUIDITY_INSUFFICIENT
                elif "state" in reason_text or "tradeable" in reason_text:
                    reason_enum = NoTradeReason.MARKET_NOT_TRADEABLE
                else:
                    reason_enum = NoTradeReason.NO_ACTIONABLE_EDGE

                tracker.record(
                    agent_name=self.config.name,
                    market_id=market.market_id,
                    asset=asset,
                    timeframe=timeframe,
                    reason=reason_enum,
                    net_edge=float(signal.edge.net_edge) if signal.edge else None,
                    additional_context={"signal_reason": signal.reason},
                )

                cycle_stats["veto_no_action"] += 1
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

            try:
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
                    self.logger.info(
                        "[AGENT-VETO] risk | agent=%s market=%s reason=%s",
                        self.config.name, market.market_id, check.reason
                    )
                    cycle_stats["veto_risk"] += 1
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
                cycle_stats["orders_attempted"] += 1
                await self._execute_signal(market, signal, check, snapshot)
                cycle_stats["orders_succeeded"] += 1

            except Exception as exc:
                self.logger.warning(f"Error executing {market.market_id}: {exc}")
                continue

        # Log cycle summary after processing all markets
        self._log_cycle_summary(cycle_stats)

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

    # ── Stop-loss sweep ────────────────────────────────────────────────

    async def _check_stop_losses(self) -> None:
        """Sweep all tracked open positions against stop-loss rules.

        For each position that breaches a rule, place a market-sell order to
        close it and remove it from the tracking registry.
        """
        if not self._tracked_positions:
            return

        from merid.prediction.kalshi_tools import _kalshi_place_order

        to_remove: List[str] = []
        for pos_id, pos in list(self._tracked_positions.items()):
            try:
                action = self._stop_loss.check_position(pos)
                if not action.should_close:
                    continue

                self.logger.warning(
                    "stop_loss TRIGGERED %s: rule=%s reason=%s urgency=%s",
                    pos.ticker, action.rule, action.reason, action.urgency,
                )

                # Place closing order (sell the side we hold).
                # PATCH-4: price_cents=0 is rejected by _check_intent_risk
                # as "invalid_price".  Use price_cents=1 (1¢) as a
                # market-proxy sell — worst-case fill but always submittable.
                close_action = "sell"
                result = await _kalshi_place_order(
                    ticker=pos.ticker,
                    side=pos.side,
                    action=close_action,
                    price_cents=1,
                    count=pos.contracts,
                )

                if result.success:
                    self.logger.info(
                        "stop_loss CLOSED %s %s x%d: %s",
                        pos.ticker, pos.side, pos.contracts, action.reason,
                    )
                    self._stop_loss.record_close(
                        position_id=pos_id,
                        action=action,
                        pnl_cents=pos.unrealized_pnl_cents,
                    )
                    # Feed realised loss into session cap tracker
                    if pos.unrealized_pnl_cents < 0:
                        self._stop_loss.record_session_loss(abs(pos.unrealized_pnl_cents))
                else:
                    self.logger.warning(
                        "stop_loss close order failed for %s: %s",
                        pos.ticker, result.error_message,
                    )

                to_remove.append(pos_id)

            except Exception as exc:
                self.logger.debug("stop_loss check error for %s: %s", pos_id, exc)

        for pos_id in to_remove:
            self._tracked_positions.pop(pos_id, None)

        # If session cap breached, halt the agent
        if self._stop_loss.session_halted and self.state.enabled:
            self.logger.warning("stop_loss session cap breached — pausing agent %s", self.config.name)
            self.pause()

    # ── Market resolution ──────────────────────────────────────────────

    async def _resolve_markets(self) -> None:
        """Resolve config filters into live Kalshi market tickers."""
        try:
            from merid.prediction.kalshi_tools import _kalshi_list_markets

            # Use parameters from config
            category = self.config.resolve_category()
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
            # PATCH-6 / EGG-5: Apply MarketFilter distance/spread/volume checks
            # using USD spot before accepting any market for strategy evaluation.
            try:
                from merid.event_venues.kalshi.market_filter import MarketFilter, MarketCandidate
                from data.live_price_feed import get_live_price_feed as _lpf, KALSHI_ASSETS as _KALSHI_ASSETS
                _mf = MarketFilter()
                _spot_feed = _lpf()
                _asset_up = asset.upper() if asset else ""
                _spot_usd_val = None
                if _asset_up:
                    _spd = _spot_feed.get_spot_usd(_asset_up)
                    if _spd and _spd.price_usd:
                        _spot_usd_val = _spd.price_usd
                # Fail-closed on cold start: if this is a Kalshi crypto asset and
                # we have no USD spot yet, skip the entire cycle for this agent
                # rather than allowing trades through without distance enforcement.
                if _asset_up in _KALSHI_ASSETS and _spot_usd_val is None:
                    self.logger.warning(
                        "[MARKET_FILTER] cycle skipped for asset=%s reason=missing_spot"
                        " — no USD spot price available; deferring until feed warms up",
                        _asset_up,
                    )
                    return
            except Exception as _mfe:
                _mf = None
                _spot_usd_val = None
                self.logger.debug("MarketFilter init skipped: %s", _mfe)

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

                # ── PATCH-6: MarketFilter quality gate ────────────────────
                if _mf is not None:
                    # Derive mid-price from YES/NO outcomes
                    _mid = 50
                    _bid = 0
                    _ask = 100
                    for _o in outcomes:
                        if _o.outcome_id == "yes":
                            _mid = int(float(_o.price) * 100)
                            _bid = max(1, _mid - 1)
                            _ask = min(99, _mid + 1)
                            break
                    # Attempt strike lookup from catalog
                    _strike_val = None
                    try:
                        from merid.event_venues.kalshi.market_catalog import get_market_catalog
                        _cat = get_market_catalog()
                        _cm = _cat.get_market(m["ticker"])
                        if _cm and _cm.strike_price:
                            _strike_val = float(_cm.strike_price)
                    except Exception:
                        pass

                    _candidate = MarketCandidate(
                        ticker=m["ticker"],
                        underlying=asset.upper() if asset else m.get("category", ""),
                        timeframe=timeframe,
                        volume=int(float(m.get("volume", "0"))),
                        open_interest=int(float(m.get("open_interest", "0"))),
                        best_bid_cents=_bid,
                        best_ask_cents=_ask,
                        mid_price_cents=_mid,
                        spot_price=_spot_usd_val,
                        strike_price=_strike_val,
                    )
                    _passed, _reason = _mf.evaluate(_candidate)
                    if not _passed:
                        self.logger.debug(
                            "MarketFilter VETO ticker=%s reason=%s",
                            m["ticker"], _reason,
                        )
                        continue

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
        except Exception as _se:
            self.logger.debug("sentiment enrichment skipped: %s", _se)

        # Compute edges for both sides using the model
        asset = self.config.assets[0] if self.config.assets else None
        strike = None
        try:
            from merid.event_venues.kalshi.market_catalog import get_market_catalog
            catalog = get_market_catalog()
            m = catalog.get_market(market.market_id)
            if m:
                strike = m.strike_price
        except Exception as _ce:
            self.logger.debug("catalog strike lookup skipped: %s", _ce)

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

        # ── Spot/strike basis enrichment ─────────────────────────────────────
        # Compute the fractional distance between the current spot price and the
        # contract strike.  This drives [PM_SIGNAL] logging and is available to
        # downstream consumers (risk, sizing, logging) via snapshot fields.
        # PATCH-1 / EGG-1: Use get_spot_usd() for a clean USD-only price; the
        # old get_price("BTC/USDT") path introduced USDT drift against Kalshi's
        # USD-settled contracts.
        snapshot.strike_price = float(strike) if strike is not None else None
        _basis_note: str = "ok"
        _spot_source: str = "unknown"
        _snapshot_age_s: Optional[float] = None
        try:
            if asset is None:
                _basis_note = "missing_asset_for_spot"
            elif strike is None:
                _basis_note = "missing_strike"
            elif strike == 0:
                _basis_note = "invalid_strike_zero"
            else:
                from data.live_price_feed import get_live_price_feed
                _feed = get_live_price_feed()
                _spot_data = _feed.get_spot_usd(asset)
                if _spot_data is None:
                    _basis_note = "missing_spot"
                elif _spot_data.spot_source == "usdt_depegged":
                    _basis_note = "missing_spot"
                    _spot_source = "usdt_depegged"
                    self.logger.warning(
                        "[SPOT_DEPEG] agent=%s market=%s asset=%s — USDT depegged, "
                        "no safe USD price available; veto_reason=usdt_depegged",
                        self.config.name, market.market_id, asset,
                    )
                elif _spot_data.price_usd is None:
                    # Stale or otherwise unavailable
                    _basis_note = "missing_spot"
                    _spot_source = _spot_data.spot_source
                else:
                    _spot = _spot_data.price_usd
                    _spot_source = _spot_data.spot_source
                    _snapshot_age_s = time.time() - _spot_data.timestamp
                    snapshot.spot_price = _spot
                    snapshot.dist_frac = (_spot - strike) / strike
                    # PATCH-7: StrikeSpotTracker staleness check
                    try:
                        from merid.event_venues.kalshi.strike_spot_tracker import (
                            get_strike_spot_tracker,
                        )
                        _sst = get_strike_spot_tracker()
                        _asset_up = asset.upper()
                        _tf = self.config.timeframes[0] if self.config.timeframes else ""
                        from merid.event_venues.kalshi.market_filter import get_spot_band
                        _max_dev = get_spot_band(_asset_up, _tf, default=30.0)
                        _is_stale, _stale_reason = _sst.check_staleness(
                            _spot, float(strike), max_pct_deviation=_max_dev,
                        )
                        if _is_stale:
                            _basis_note = "stale_distance"
                            self.logger.warning(
                                "[STALE_DISTANCE] agent=%s market=%s asset=%s "
                                "spot=%.2f strike=%.2f reason=%s; veto_reason=distance_violation",
                                self.config.name, market.market_id, _asset_up,
                                _spot, float(strike), _stale_reason,
                            )
                    except Exception as _sst_e:
                        self.logger.debug("StrikeSpotTracker check skipped: %s", _sst_e)
        except Exception as _be:
            self.logger.debug("spot_strike_basis enrichment skipped: %s", _be)
            _basis_note = "missing_spot"
        snapshot.spot_strike_basis = _basis_note
        snapshot.spot_source = _spot_source

        # ── [PM_SIGNAL] structured log ────────────────────────────────────────
        _tte_h = float(snapshot.time_to_expiry_hours) if snapshot.time_to_expiry_hours else None
        self.logger.info(
            "[PM_SIGNAL] agent=%s market=%s snapshot_ts=%.0f "
            "yes_prob=%.3f tte_h=%s spot=%s strike=%s dist_pct=%s basis=%s "
            "spot_source=%s snapshot_age_s=%s "
            "sentiment_global=%s sentiment_regime=%s vol=%.0f oi=%.0f",
            self.config.name,
            market.market_id,
            snapshot.snapshot_timestamp_utc_epoch_seconds,
            float(implied.yes_prob) if implied else 0.0,
            f"{_tte_h:.2f}" if _tte_h is not None else "N/A",
            f"{snapshot.spot_price:.2f}" if snapshot.spot_price is not None else "N/A",
            f"{snapshot.strike_price:.2f}" if snapshot.strike_price is not None else "N/A",
            f"{snapshot.dist_frac * 100:.2f}%" if snapshot.dist_frac is not None else "N/A",
            _basis_note,
            _spot_source,
            f"{_snapshot_age_s:.1f}" if _snapshot_age_s is not None else "N/A",
            f"{snapshot.sentiment_global:.1f}" if snapshot.sentiment_global is not None else "N/A",
            snapshot.sentiment_regime or "N/A",
            float(snapshot.volume),
            float(snapshot.open_interest),
        )

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

    def _log_cycle_summary(self, stats: Dict[str, int]) -> None:
        """Log a concise INFO-level summary of this cycle's vetoes and actions.

        Purpose: Allow operators to diagnose "10-12 hours, zero trades" issues
        by eyeballing a single log line per cycle showing dominant veto reason.

        Args:
            stats: Dictionary with veto counts and order counts from this cycle
        """
        # Only log if there were candidates or vetoes
        if stats["candidates_total"] == 0 and all(v == 0 for v in stats.values()):
            return

        total_vetoes = sum(
            stats[k] for k in stats
            if k.startswith("veto_") and k != "veto_no_action"
        )

        # Build compact summary
        self.logger.info(
            "[AGENT-CYCLE] agent=%s candidates=%d orders=%d vetoes=%d "
            "(session_guard=%d no_markets=%d entry_window=%d order_limit=%d "
            "no_action=%d consensus=%d risk=%d degraded=%d)",
            self.config.name,
            stats["candidates_total"],
            stats["orders_succeeded"],
            total_vetoes,
            stats["veto_session_guard"],
            stats["veto_no_markets"],
            stats["veto_entry_window"],
            stats["veto_order_limit"],
            stats["veto_no_action"],
            stats["veto_consensus_conflicted"] + stats["veto_consensus_forming"],
            stats["veto_risk"],
            stats["veto_degraded_pause"],
        )

        # NOTE: calibration (record_forecast) and forecaster registry (predict_all)
        # are called inline in _run_cycle after each signal evaluation, where the
        # required local variables (signal, market, snapshot, now) are in scope.

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
        """Execute a strategy signal by placing an order.
        
        Integrates with CryptoSwarmRiskBTC15m for single-lane risk management.
        BTC 15m proposals are evaluated for live vs paper routing.
        """
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
        price_cents = signal.limit_price_cents or 0

        # === Vol-band size adjustment ===
        # For crypto agents apply the vol-band size multiplier before sizing is
        # finalised.  The multiplier is 1.0 for mid vol (no change), <1 for low
        # and high vol (risk reduction in illiquid / highly volatile conditions).
        asset = self.config.assets[0] if self.config.assets else ""
        timeframe = self.config.timeframes[0] if self.config.timeframes else ""
        _vol_band_label = "N/A"
        _vol_mult = 1.0
        try:
            from merid.prediction.crypto_thresholds import (
                classify_vol_band,
                vol_band_size_multiplier,
                is_crypto_agent,
            )
            if is_crypto_agent(agent_name=self.config.name, assets=self.config.assets):
                # Derive a short-window realised vol proxy from the spread/OI
                # (0 = unavailable → mid-band assumed).
                _rv = 0.0
                if snapshot and snapshot.implied:
                    _yes_bid = float(snapshot.implied.yes_bid or 0)
                    _yes_ask = float(snapshot.implied.yes_ask or 0)
                    if _yes_ask > 0 and _yes_bid >= 0:
                        _rv = (_yes_ask - _yes_bid) / max(_yes_ask, 1.0)
                _band = classify_vol_band(_rv)
                _vol_band_label = _band.value
                _vol_mult = vol_band_size_multiplier(_band)
                if _vol_mult != 1.0:
                    _pre_mult_size = size
                    size = max(1, int(size * _vol_mult))
                    self.logger.debug(
                        "[PM_SIZE] vol_band=%s mult=%.2f size %d→%d",
                        _vol_band_label, _vol_mult, _pre_mult_size, size,
                    )
        except Exception as _vbe:
            self.logger.debug("vol_band_size_adjustment skipped: %s", _vbe)

        # === [PM_SIZE] structured log ===
        self.logger.info(
            "[PM_SIZE] agent=%s market=%s action=%s side=%s contracts=%d "
            "price_cents=%d vol_band=%s vol_mult=%.2f dist_pct=%s basis=%s "
            "spot_source=%s order_mode=%s",
            self.config.name,
            market.market_id,
            action,
            side,
            size,
            price_cents,
            _vol_band_label,
            _vol_mult,
            (f"{snapshot.dist_frac * 100:.2f}%"
             if snapshot and snapshot.dist_frac is not None else "N/A"),
            (snapshot.spot_strike_basis or "N/A") if snapshot else "N/A",
            (snapshot.spot_source or "N/A") if snapshot else "N/A",
            "paper" if force_paper else "live",
        )
        
        # === BTC 15m Risk Layer Integration ===
        # Evaluate proposal through single-lane risk manager
        is_btc_15m = asset.upper() == "BTC" and timeframe == "15m"
        
        if is_btc_15m:
            try:
                from merid.risk.crypto_swarm_risk_btc15m import (
                    CryptoSwarmRiskBTC15m,
                    TradeProposal,
                    TradeMode,
                    RiskPhase,
                )
                
                # PATCH-5 / EGG-7: convert raw contract volume to USD notional
                # before passing to CryptoSwarmRiskBTC15m.  The BTC-15m USD
                # thresholds compare against dollar amounts; passing raw
                # contract counts would undercount by ~price_cents/100.
                _vol_usd = (
                    float(market.volume) * (price_cents / 100.0)
                    if (market.volume and price_cents > 0)
                    else None
                )
                proposal = TradeProposal(
                    asset=asset,
                    timeframe=timeframe,
                    side=side,
                    price_cents=price_cents,
                    intent_risk=float(size) * (price_cents / 100.0),  # Dollar amount
                    tags=list(self.config.archetype_tags) if hasattr(self.config, 'archetype_tags') else [],
                    fear_greed=int(getattr(snapshot, 'sentiment_global', 0.5) * 100)
                    if getattr(snapshot, 'sentiment_global', None) is not None else None,
                    spread_ticks=self._estimate_spread_ticks(snapshot),
                    volume_24h=_vol_usd,
                    minutes_to_expiry=int(snapshot.time_to_expiry_hours * 60) if snapshot.time_to_expiry_hours else None,
                    session_stable=getattr(snapshot, 'sentiment_regime', 'normal') != 'extreme_volatility',
                )
                
                # Use per-agent singleton so daily PnL and open-exposure
                # state persist across calls (not zeroed on every signal).
                # _init_equity is resolved here (before the init-branch) so that
                # update_from_phase() can use it on every cycle, not just the first.
                _init_equity = 0.0
                try:
                    from merid.event_venues.kalshi.kalshi_risk import get_kalshi_risk as _gkr_ta
                    _init_equity = float(getattr(_gkr_ta().state, 'current_equity_usd', 0) or 0)
                except Exception as _e:
                    self.logger.debug("equity_lookup_kalshi_risk: %s", _e)
                if _init_equity <= 0:
                    try:
                        from merid.settings import settings as _s_ta
                        _init_equity = float(getattr(_s_ta, 'PAPER_STARTING_BALANCE', 0) or 0)
                    except Exception as _e:
                        self.logger.debug("equity_lookup_settings: %s", _e)

                if self._btc15m_risk is None:
                    # Bootstrap phase from PromotionEngine if available
                    _init_phase = RiskPhase.PHASE_0
                    try:
                        from merid.risk.promotion_engine import get_promotion_engine
                        _pe = get_promotion_engine()
                        _caps = _pe.get_caps(_init_equity)
                        if _caps:
                            _init_equity = _caps.get("per_trade", _init_equity) or _init_equity
                        _phase_name = _pe.get_status().get("current_phase", "PHASE_0")
                        _init_phase = RiskPhase[_phase_name] if _phase_name in RiskPhase.__members__ else RiskPhase.PHASE_0
                    except Exception as _e:
                        self.logger.debug("phase_lookup_promotion_engine: %s", _e)
                    self._btc15m_risk = CryptoSwarmRiskBTC15m(
                        current_equity=_init_equity,
                        phase=_init_phase,
                    )
                risk_manager = self._btc15m_risk
                # Keep phase caps in sync with PromotionEngine on every call
                try:
                    risk_manager.update_from_phase(_init_equity)
                except Exception as _e:
                    self.logger.debug("update_from_phase: %s", _e)

                # Sync live exposure from KalshiRiskManager each call
                try:
                    risk_manager.open_exposure_total = self._get_current_open_exposure()
                    risk_manager.open_positions = self._get_open_positions_dict()
                except Exception as _e:
                    self.logger.debug("sync_open_exposure: %s", _e)

                decision = risk_manager.evaluate_proposal(proposal)
                
                # Log the decision
                self.logger.info(
                    f"BTC 15m risk decision: {decision.mode.value} | "
                    f"size=${decision.final_size:.2f} | {decision.reason}"
                )
                
                # Route based on decision
                if decision.mode == TradeMode.BLOCKED:
                    self.logger.info(f"BTC 15m risk BLOCKED: {decision.blocked_reason}")
                    await self._record_risk_blocked_order(market, signal, decision, snapshot)
                    return
                
                # Adjust size based on risk decision
                if decision.final_size < proposal.intent_risk:
                    original_contracts = size
                    if decision.final_size <= 0.0:
                        # Risk approved $0.00 — skip order entirely rather than
                        # forcing 1 contract which would fail min_notional checks.
                        self.logger.info(
                            "BTC 15m risk size=$0.00 (adjustments: %s) — suppressing order",
                            list(decision.adjustments.keys()),
                        )
                        return
                    # Recalculate contracts based on final dollar size
                    if price_cents > 0:
                        size = max(1, int(decision.final_size / (price_cents / 100.0)))
                    self.logger.info(
                        f"BTC 15m size adjusted: {original_contracts} → {size} contracts "
                        f"(${decision.final_size:.2f})"
                    )
                
                # For paper mode, force simulation
                force_paper = decision.mode == TradeMode.PAPER
                
            except Exception as exc:
                # PATCH-2: Risk layer exception must be FAIL-CLOSED.
                # Never silently route to live when risk evaluation failed.
                # Force paper mode so the order is simulated, not executed live.
                self.logger.error(
                    "BTC 15m risk evaluation FAILED (forced paper): %s", exc,
                    exc_info=True,
                )
                force_paper = True
        else:
            # Non-BTC-15m: route through existing paper/live gate
            force_paper = False
        
        # ── Pre-execution notional floor check ────────────────────────────────
        # Suppress orders whose dollar notional is below the $1 minimum rather
        # than sending them to the exchange (or order router) and counting them
        # as errors toward the circuit-breaker budget.
        _MIN_NOTIONAL_USD = 1.0
        if action == "quote":
            # For a two-sided quote use the lower of bid/ask to be conservative.
            _check_price_cents = signal.bid_price_cents or signal.ask_price_cents or price_cents
        else:
            _check_price_cents = price_cents
        if _check_price_cents > 0:
            _notional = size * (_check_price_cents / 100.0)
            if _notional < _MIN_NOTIONAL_USD:
                # Round up to the minimum contract count that meets the floor.
                import math as _math
                _min_size = max(1, _math.ceil(_MIN_NOTIONAL_USD / (_check_price_cents / 100.0)))
                self.logger.debug(
                    "[MM_NOTIONAL] agent=%s market=%s size=%d price=%dc notional=$%.2f "
                    "< floor=$%.2f — rounding up to %d contracts",
                    self.config.name, market.market_id, size, _check_price_cents,
                    _notional, _MIN_NOTIONAL_USD, _min_size,
                )
                size = _min_size

        if action == "quote":
            # For quotes, place a buy and sell limit order pair
            _q_bid_result = None
            _q_ask_result = None
            if signal.bid_price_cents:
                _q_bid_result = await _kalshi_place_order(
                    ticker=market.market_id,
                    side="yes",
                    action="buy",
                    price_cents=signal.bid_price_cents,
                    count=size,
                    agent_name=self.agent_id,
                    snapshot_ts=(
                        snapshot.snapshot_timestamp_utc_epoch_seconds
                        if snapshot else None
                    ),  # PATCH-3: staleness gate applies to quote legs too
                )
            if signal.ask_price_cents:
                _q_ask_result = await _kalshi_place_order(
                    ticker=market.market_id,
                    side="yes",
                    action="sell",
                    price_cents=signal.ask_price_cents,
                    count=size,
                    agent_name=self.agent_id,
                    snapshot_ts=(
                        snapshot.snapshot_timestamp_utc_epoch_seconds
                        if snapshot else None
                    ),  # PATCH-3: staleness gate applies to quote legs too
                )
            # Record as a single "quote" event in logs
            _q_ok = ((_q_bid_result is None or _q_bid_result.success) and
                     (_q_ask_result is None or _q_ask_result.success))
            result_success = _q_ok
            result_payload = {
                "simulated": self._venue_gate.should_simulate_fill(),
                "order_id": "quote_group",
            }
            result_error = None if _q_ok else "One or both quote legs failed"
        else:
            price_cents = signal.limit_price_cents or 0
            # Use force_paper flag from risk layer evaluation
            if force_paper:
                # Force paper simulation by using the paper tool
                from merid.prediction.kalshi_tools import _kalshi_place_paper_order
                _fp_reason = (
                    "btc15m_risk_paper" if is_btc_15m else "risk_layer_paper"
                )
                result = await _kalshi_place_paper_order(
                    ticker=market.market_id,
                    side=side,
                    action=action,
                    price_cents=price_cents,
                    count=size,
                    forced_paper_reason=_fp_reason,  # PATCH-9: audit trail
                )
            else:
                result = await _kalshi_place_order(
                    ticker=market.market_id,
                    side=side,
                    action=action,
                    price_cents=price_cents,
                    count=size,
                    agent_name=self.agent_id,
                    snapshot_ts=(
                        snapshot.snapshot_timestamp_utc_epoch_seconds
                        if snapshot else None
                    ),  # PATCH-3: staleness enforcement in order router
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

        # Publish order_placed event regardless of fill outcome
        try:
            from core.event_bus import event_stream as _event_bus
            await _event_bus.publish("kalshi:order_placed", order_entry)
        except Exception as _ep:
            self.logger.debug(f"Event bus order_placed publish error (ignored): {_ep}")

        if result_success:
            self.state.orders_placed += 1
            self.state.orders_this_window += 1

            # Track solo-mode trades (AUDIT-10): increment degraded counter only
            # when the last consensus was absent (swarm was unavailable).
            if self._last_consensus_at is None or (
                time.monotonic() - self._last_consensus_at >= _MAX_SOLO_SECONDS
            ):
                self._solo_trades_taken += 1

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

            # ── Realized edge: log trade entry for later settlement comparison ──
            try:
                from merid.metrics.realized_edge import get_realized_edge_store
                from merid.event_venues.kalshi.kalshi_risk import kalshi_fee_cents
                edge_store = get_realized_edge_store()
                _trade_id = result_payload.get("order_id") or f"{market.market_id}:{now_ts.isoformat()}"
                _price_c = signal.limit_price_cents or 50
                _p_implied = _price_c / 100.0
                _p_model = _p_implied
                if signal.edge and hasattr(signal.edge, 'net_edge'):
                    _p_model = max(0.01, min(0.99, _p_implied + float(signal.edge.net_edge)))
                _fee_c = kalshi_fee_cents(_price_c, size)
                _bucket = (market.category or "unknown").lower()
                edge_store.record_trade_entry(
                    trade_id=_trade_id,
                    forecaster_id=self.config.name,
                    bucket=_bucket,
                    market_id=market.market_id,
                    side=side,
                    price_cents=_price_c,
                    p_model=_p_model,
                    p_implied=_p_implied,
                    contracts=size,
                    fee_cents=_fee_c,
                    timestamp=now_ts.timestamp(),
                )
            except Exception as _edge_exc:
                self.logger.debug("realized_edge record_trade_entry skipped: %s", _edge_exc)

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

            # Register fill with stop-loss engine
            try:
                pos_id = result_payload.get("order_id") or market.market_id
                expiry_ts = market.end_date.timestamp() if market.end_date else 0.0
                tp = TrackedPosition(
                    position_id=pos_id,
                    ticker=market.market_id,
                    side=side,
                    entry_price_cents=signal.limit_price_cents or 50,
                    contracts=size,
                    entry_ts=time.time(),
                    contract_expiry_ts=expiry_ts,
                    current_price_cents=signal.limit_price_cents or 50,
                )
                self._tracked_positions[pos_id] = tp
                self.logger.debug("stop_loss: tracking position %s %s@%dc", pos_id, side, tp.entry_price_cents)
            except Exception as exc:
                self.logger.debug("stop_loss register skipped: %s", exc)

            # Wire fill into KalshiRiskManager so risk/sizing endpoints see live flow
            # G3: Only record into live risk manager for real (non-simulated) fills.
            # Paper/sim fills must not skew live drawdown, rate-limit, or PnL state.
            _is_live_fill = not bool(result_payload.get("simulated", True)) if result_payload else False
            try:
                from merid.event_venues.kalshi.kalshi_risk import get_kalshi_risk
                risk_mgr = get_kalshi_risk()
                price_cents = signal.limit_price_cents or 50
                category = getattr(self.config, 'category', None)
                if _is_live_fill:
                    risk_mgr.record_order(category=category, contracts=size, price_cents=price_cents)
                    # Estimate immediate PnL from edge (realized on fill for market-making)
                    if signal.edge and hasattr(signal.edge, 'net_edge'):
                        pnl_usd = float(signal.edge.net_edge) * size * (price_cents / 100.0)
                        risk_mgr.record_pnl(pnl_usd)
                else:
                    # Still track rate-limit counters for paper orders (prevents thundering herd
                    # if mode switches to live mid-session), but skip PnL recording.
                    risk_mgr.record_order(category=category, contracts=size, price_cents=price_cents)
            except Exception as exc:
                self.logger.debug(f"KalshiRiskManager record error (ignored): {exc}")

            # Record fill in paper session for per-interval PnL tracking
            # G1: Only record in PaperSession when the fill was actually simulated
            # (PAPER/MOCK mode). Live and Shadow fills must NOT pollute paper stats.
            _is_simulated_fill = bool(result_payload.get("simulated", False)) if result_payload else False
            try:
                from merid.prediction.paper_session import get_paper_session
                import random as _random
                session = get_paper_session()
                if session.is_active and _is_simulated_fill:
                    # Proper Kalshi binary payoff simulation (Bernoulli draw)
                    # Win prob ≈ implied YES probability; YES bet wins (1-price)*size, loses price*size
                    p_cents = float(signal.limit_price_cents or 50)
                    win_prob = float(snapshot.implied.yes_prob) if (snapshot and snapshot.implied) else p_cents / 100.0
                    won = _random.random() < win_prob
                    if won:
                        pnl_cents = (100.0 - p_cents) * size
                    else:
                        pnl_cents = -p_cents * size
                    fee_cents = float(check.estimated_fee * 100) if hasattr(check, 'estimated_fee') and check.estimated_fee else 0.0
                    session.record_fill(
                        agent_name=self.config.name,
                        pnl_cents=pnl_cents,
                        fees_cents=fee_cents * size,
                        won=won,
                    )
            except Exception as exc:
                self.logger.debug(f"Paper session record error (ignored): {exc}")

            # Trigger portfolio rebalancer after fill
            # G4: Only execute real rebalance orders when NOT in simulated mode
            try:
                from merid.event_venues.kalshi.rebalancer import get_portfolio_rebalancer
                from merid.event_venues.kalshi.client import get_kalshi_client as _get_rb_client
                _rebalancer = get_portfolio_rebalancer()
                if _rebalancer.get_targets():  # only run if targets are configured
                    _rb_client = _get_rb_client()
                    _rb_actions = await _rebalancer.analyze_rebalance_needed(_rb_client)
                    if _rb_actions:
                        self.logger.info(
                            "rebalancer: %d actions needed after fill on %s",
                            len(_rb_actions), market.market_id,
                        )
                        # G4: Gate real rebalance orders on VenueGate — skip in paper/sim mode
                        if not _is_simulated_fill:
                            await _rebalancer.execute_rebalance(_rb_client, actions=_rb_actions)
                        else:
                            self.logger.debug(
                                "rebalancer: skipping execute in paper/sim mode (%d actions)",
                                len(_rb_actions),
                            )
            except Exception as exc:
                self.logger.debug("rebalancer post-fill skipped: %s", exc)

            # Feed PnL into CryptoSwarmRiskBTC15m daily tracker
            # G2: Use actual agent deployment mode, not hardcoded PAPER
            if self._btc15m_risk is not None:
                try:
                    from merid.risk.crypto_swarm_risk_btc15m import TradeMode as _TM
                    p_c = float(signal.limit_price_cents or 50)
                    _win_prob = float(snapshot.implied.yes_prob) if (snapshot and snapshot.implied) else p_c / 100.0
                    _won = __import__('random').random() < _win_prob
                    _pnl = ((100.0 - p_c) * size / 100.0) if _won else -(p_c * size / 100.0)
                    # Resolve actual trade mode from deployment controller
                    _btc_mode = _TM.PAPER
                    try:
                        from merid.event_venues.kalshi.deployment import get_deployment_controller, AgentMode as _AM
                        _dep_mode = get_deployment_controller()._agents.get(self.agent_id)
                        if _dep_mode and _dep_mode.mode == _AM.LIVE:
                            _btc_mode = _TM.LIVE
                        elif _dep_mode and _dep_mode.mode == _AM.SHADOW:
                            _btc_mode = _TM.LIVE  # shadow counts as live for risk tracking
                    except Exception:
                        pass
                    self._btc15m_risk.record_trade_result(
                        ticker=market.market_id,
                        realized_pnl=_pnl,
                        mode=_btc_mode,
                    )
                except Exception as _rte:
                    self.logger.debug("btc15m risk record_trade_result skipped: %s", _rte)

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

            # Emit ForecastEvent into RewardEngine so fills flow into reputation pipeline
            try:
                from merid.rewards.engine import get_reward_engine
                from merid.rewards.events import ForecastEvent
                _engine = get_reward_engine()
                _engine.process_event(ForecastEvent(
                    agent_id=self.agent_id,
                    venue="kalshi",
                    symbol=market.market_id,
                    probability=float(signal.limit_price_cents or 50) / 100.0,
                    confidence=float(signal.edge.confidence) if signal.edge and hasattr(signal.edge, "confidence") else 0.5,
                    metadata={
                        "action": action,
                        "side": side,
                        "contracts": size,
                        "price_cents": price_cents,
                        "simulated": result_payload.get("simulated", False),
                    },
                ))
            except Exception as exc:
                self.logger.debug("RewardEngine ForecastEvent skipped: %s", exc)

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
            except Exception as _pse:
                self.logger.debug("paper session record_error skipped: %s", _pse)
            # Wire into global error-threshold kill switch
            try:
                from merid.risk.kill_switches import risk_controller as _rc
                # Classify the error so benign repeating failures (e.g., min_notional
                # misconfig, WS reconnects) do not exhaust the error budget.
                _err_class = "generic"
                if result_error and "notional" in str(result_error).lower():
                    _err_class = "min_notional"
                elif result_error and ("reconnect" in str(result_error).lower()
                                       or "ws_disconnect" in str(result_error).lower()):
                    _err_class = "ws_reconnect"
                _rc.record_error(error_class=_err_class)
            except Exception as _kse:
                self.logger.debug("kill_switch record_error skipped: %s", _kse)
            # Record PM_AGENT_EXECUTION error in NoTradeDecisionTracker so the
            # failure is visible in the /api/no-trade and metrics endpoints.
            try:
                from merid.event_venues.kalshi.order_errors import KalshiOrderErrorCode
                _asset = self.config.assets[0] if self.config.assets else ""
                _tf = self.config.timeframes[0] if self.config.timeframes else ""
                _tracker = get_no_trade_tracker()
                _tracker.observe(
                    agent_name=self.config.name,
                    market_id=market.market_id,
                    asset=_asset,
                    timeframe=_tf,
                    reason=NoTradeReason.INFRA_BACKOFF,
                    additional_context={
                        "error_code": KalshiOrderErrorCode.PM_AGENT_EXECUTION.value,
                        "error_message": result_error or "order_failed",
                    },
                )
            except Exception as _nte:
                self.logger.debug("no_trade pm_agent_execution record skipped: %s", _nte)
            self.logger.warning(
                "[PM_AGENT_EXECUTION] agent=%s market=%s error=%s",
                self.config.name,
                market.market_id,
                result_error,
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

    # ── BTC 15m Risk Layer Helpers ────────────────────────────────────────

    def _estimate_spread_ticks(self, snapshot: Optional[MarketSnapshot]) -> Optional[int]:
        """Estimate spread in ticks from snapshot."""
        if not snapshot or not snapshot.implied:
            return None
        yes_bid = float(snapshot.implied.yes_bid) if snapshot.implied.yes_bid else 0
        yes_ask = float(snapshot.implied.yes_ask) if snapshot.implied.yes_ask else 0
        if yes_bid > 0 and yes_ask > 0:
            # Each tick is 1 cent
            return int(round(yes_ask - yes_bid))
        return None

    def _get_current_open_exposure(self) -> float:
        """Get total dollar exposure of open positions."""
        try:
            # Try to get from KalshiRiskManager
            from merid.event_venues.kalshi.kalshi_risk import get_kalshi_risk
            risk_mgr = get_kalshi_risk()
            total_notional = risk_mgr.state.total_notional_usd if hasattr(risk_mgr, 'state') else 0.0
            return total_notional
        except Exception as _rme:
            self.logger.debug("kalshi_risk notional lookup skipped, using fill log: %s", _rme)
            # Fallback: estimate from fill log
            total = 0.0
            for fill in self.state.fill_log[-100:]:  # Last 100 fills
                if fill.get("action") == "buy":
                    price = fill.get("price_cents", 50)
                    contracts = fill.get("contracts", 0)
                    total += contracts * (price / 100.0)
            return total

    def _get_open_positions_dict(self) -> Dict[str, float]:
        """Get open positions as ticker -> exposure dict."""
        positions: Dict[str, float] = {}
        for fill in self.state.fill_log[-50:]:
            ticker = fill.get("market_id", "")
            contracts = fill.get("contracts", 0)
            price = fill.get("price_cents", 50)
            exposure = contracts * (price / 100.0)
            if fill.get("action") == "buy":
                positions[ticker] = positions.get(ticker, 0) + exposure
            elif fill.get("action") == "sell":
                positions[ticker] = positions.get(ticker, 0) - exposure
        # Remove zero/negative positions
        return {k: v for k, v in positions.items() if v > 0}

    async def _record_risk_blocked_order(
        self,
        market: EventMarket,
        signal: StrategySignal,
        decision: Any,
        snapshot: Optional[MarketSnapshot],
    ) -> None:
        """Record a risk-blocked order in logs and explainability."""
        now = datetime.now(timezone.utc)
        
        # Add to order log as blocked
        entry = {
            "ts": now.isoformat(),
            "market_id": market.market_id,
            "question": market.question[:120] if market.question else "",
            "side": "yes" if signal.action in (SignalAction.BUY_YES, SignalAction.SELL_YES) else "no",
            "action": str(signal.action),
            "contracts": signal.contracts,
            "success": False,
            "error": f"Risk blocked: {decision.blocked_reason}",
            "risk_decision": {
                "mode": decision.mode.value,
                "reason": decision.reason,
                "adjustments": decision.adjustments,
            },
        }
        self.state.order_log.append(entry)
        if len(self.state.order_log) > _MAX_LOG_ENTRIES:
            self.state.order_log = self.state.order_log[-_MAX_LOG_ENTRIES:]
        
        # Record in explainability
        try:
            from agents.explainability import DecisionType, create_reasoning_builder, get_explainability_tracker
            
            action_value = signal.action.value if hasattr(signal.action, "value") else str(signal.action)
            
            builder = create_reasoning_builder(self.config.name, DecisionType.ACTION)
            builder.set_decision(f"BLOCKED: {action_value} {market.market_id}", 0.0)
            builder.set_primary_reason(f"BTC 15m risk layer blocked: {decision.blocked_reason}")
            builder.add_contrary_factor(f"risk decision: {decision.reason}")
            
            for adj_name, adj_value in decision.adjustments.items():
                builder.add_contrary_factor(f"adjustment: {adj_name}={adj_value}")
            
            builder.set_risk_assessment(
                {
                    "allowed": False,
                    "reason": decision.blocked_reason,
                    "btc_15m_risk_layer": True,
                    "adjustments": decision.adjustments,
                }
            )
            
            reasoning = builder.build()
            get_explainability_tracker().record_decision(reasoning)
        except Exception as exc:
            self.logger.debug(f"Explainability blocked order record skipped: {exc}")

    # ── Market Mood Bus Integration ────────────────────────────────────────

    def _get_mood_context(
        self,
        asset: str,
        timeframe: str,
    ) -> Optional[Any]:
        """Get unified market context from the Market Mood Bus."""
        try:
            from merid.swarm.market_mood_bus import get_market_mood_bus
            bus = get_market_mood_bus()
            return bus.get_context(asset, timeframe)
        except Exception as exc:
            self.logger.debug(f"MarketMoodBus fetch error: {exc}")
            return None

    def _submit_to_consensus(
        self,
        market: EventMarket,
        signal: StrategySignal,
        snapshot: MarketSnapshot,
        mood_context: Optional[Any],
    ) -> None:
        """Submit agent proposal to SwarmConsensusAggregator."""
        try:
            from merid.swarm.consensus_aggregator import (
                get_consensus_aggregator,
                AgentProposal,
            )
            from datetime import datetime

            # Determine direction from signal action
            # BUY_YES and BUY_NO represent betting that the outcome WILL / WON'T happen.
            # SELL_YES means we're selling the YES side (effectively a NO/bearish view).
            # SELL_NO means we're selling the NO side (effectively a YES/bullish view).
            direction_map = {
                SignalAction.BUY_YES: "yes",
                SignalAction.SELL_YES: "no",
                SignalAction.BUY_NO: "no",
                SignalAction.SELL_NO: "yes",
            }
            direction = direction_map.get(signal.action, "neutral")

            # Get probability from signal edge or snapshot
            prob = 0.5
            if signal.edge and hasattr(signal.edge, 'yes_prob'):
                prob = float(signal.edge.yes_prob)
            elif snapshot.implied:
                prob = float(snapshot.implied.yes_prob)

            # Get confidence
            conf = 0.5
            if signal.edge and hasattr(signal.edge, 'confidence'):
                conf = float(signal.edge.confidence)

            # Determine size preference
            size_pref = "base"
            if mood_context and hasattr(mood_context, 'should_reduce_size'):
                if mood_context.should_reduce_size():
                    size_pref = "reduced"

            # Get track record if available
            track_record = None
            try:
                from merid.prediction.agent_performance_tracker import get_agent_performance_tracker
                tracker = get_agent_performance_tracker()
                metrics = tracker.get_agent_metrics(self.agent_id)
                if metrics:
                    track_record = {
                        "win_rate": metrics.get("win_rate", 0.5),
                        "sharpe_ratio": metrics.get("sharpe_ratio", 1.0),
                    }
            except Exception as _tre:
                self.logger.debug("track_record lookup skipped: %s", _tre)

            # Build proposal
            asset = self.config.assets[0] if self.config.assets else ""
            timeframe = self.config.timeframes[0] if self.config.timeframes else ""
            proposal_mode = "SIM" if self._venue_gate.should_simulate_fill() else "LIVE"

            proposal = AgentProposal(
                agent_id=self.agent_id,
                asset=asset,
                timeframe=timeframe,
                direction=direction,
                probability=prob,
                confidence=conf,
                size_preference=size_pref,
                rationale=str(signal.action),
                edge_estimate=float(signal.edge.net_edge * 100) if signal.edge else 0.0,
                timestamp=datetime.now(timezone.utc),
                agent_archetype=self.config.archetype,
                agent_track_record=track_record,
                mode=proposal_mode,
            )

            # Submit to aggregator
            aggregator = get_consensus_aggregator()
            aggregator.submit_proposal(proposal)

            self.logger.debug(
                f"Submitted proposal to consensus: {direction} @ {prob:.1%} "
                f"(conf={conf:.2f})"
            )

        except Exception as exc:
            self.logger.debug(f"Consensus submission error: {exc}")

    def _get_consensus(
        self,
        asset: str,
        timeframe: str,
        wait_for_ready: bool = False,
        timeout_ms: int = 500,
    ) -> Optional[Any]:
        """Get current consensus view from SwarmConsensusAggregator.

        Args:
            asset: Asset symbol (BTC, ETH, etc.)
            timeframe: Timeframe string (15m, 1h, etc.)
            wait_for_ready: If True, wait up to timeout_ms for FORMING → READY
            timeout_ms: Maximum milliseconds to wait for transition

        Returns:
            ConsensusView or None
        """
        try:
            from merid.swarm.consensus_aggregator import get_consensus_aggregator, ConsensusStatus
            aggregator = get_consensus_aggregator()

            consensus = aggregator.get_consensus(asset, timeframe)

            # If wait requested and status is FORMING, poll for up to timeout_ms
            if wait_for_ready and consensus and consensus.status == ConsensusStatus.FORMING:
                import time
                start_ms = time.time() * 1000
                poll_interval_ms = 50  # Poll every 50ms

                while (time.time() * 1000 - start_ms) < timeout_ms:
                    time.sleep(poll_interval_ms / 1000)
                    consensus = aggregator.get_consensus(asset, timeframe)

                    if consensus and consensus.status == ConsensusStatus.READY:
                        self.logger.debug(
                            "Consensus transitioned FORMING→READY for %s:%s in %.0fms",
                            asset, timeframe, time.time() * 1000 - start_ms
                        )
                        break
                    elif not consensus or consensus.status != ConsensusStatus.FORMING:
                        break

            return consensus
        except Exception as exc:
            self.logger.debug(f"Consensus fetch error: {exc}")
            return None

    def _resolve_consensus_for_mm(
        self,
        asset: str,
        timeframe: str,
        mm_consensus_mode: str,
    ) -> Optional[Any]:
        """Resolve consensus for market making with special handling based on mm_consensus_mode.

        Modes:
        - full: Standard consensus requirement (FORMING blocks)
        - soft: FORMING treated as no_consensus, fall back to MM-only decision
        - bypass: Never consult consensus, always proceed on MM signal alone

        Args:
            asset: Asset symbol
            timeframe: Timeframe string
            mm_consensus_mode: One of "full", "soft", "bypass"

        Returns:
            ConsensusView or None (None means "proceed without consensus")
        """
        if mm_consensus_mode == "bypass":
            # Never consult consensus in bypass mode
            return None

        # Get consensus (with wait-for-ready if configured)
        consensus = self._get_consensus(asset, timeframe, wait_for_ready=True, timeout_ms=500)

        if mm_consensus_mode == "soft" and consensus:
            from merid.swarm.consensus_aggregator import ConsensusStatus
            if consensus.status == ConsensusStatus.FORMING:
                # Soft mode: treat FORMING as no_consensus
                self.logger.info(
                    "[MM-SOFT] Consensus FORMING for %s:%s, proceeding with MM-only decision",
                    asset, timeframe
                )
                return None  # Signals to caller: proceed without consensus

        # Full mode (or soft mode with READY/CONFLICTED): return consensus as-is
        return consensus
