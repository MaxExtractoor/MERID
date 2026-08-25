"""KalshiUniversalAgent — Market-agnostic swarm agent for all Kalshi categories.

Unlike KalshiTradingAgent (which is hardcoded to specific assets/timeframes),
this agent:
  - Pulls its market pool dynamically from KalshiUniverse each cycle.
  - Is category-aware: respects per-category paper/live mode from env config.
  - Enforces a configurable max-simultaneous-markets cap (max_per_agent).
  - Routes orders through the standard route_order path with the category
    mode injected into each OrderIntent.

Lifecycle::

    agent = KalshiUniversalAgent(UniversalAgentConfig(
        name="sweep-all",
        categories=["crypto", "politics", "economics"],
        max_markets=30,
    ))
    await agent.start()
    await agent.stop()
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional

from merid.event_venues.kalshi.market_catalog import CatalogMarket
from merid.event_venues.kalshi.universe import (
    KNOWN_CATEGORIES,
    KalshiUniverse,
    UniverseConfig,
    get_category_mode,
    get_kalshi_universe,
)
from merid.prediction.venue_gate import get_venue_gate
from merid.prediction.trading_mode import TradingMode
from utils.logger import get_logger


# ── Config ────────────────────────────────────────────────────────────────

@dataclass
class UniversalAgentConfig:
    """Configuration for a KalshiUniversalAgent instance.

    Attributes:
        name:           Human-readable agent identifier.
        categories:     Category list to sweep (empty = all allowed by universe).
        max_markets:    Hard cap on markets evaluated per cycle.
        cycle_secs:     Seconds between decision cycles.
        min_edge:       Minimum edge estimate required to attempt an order (0-1).
        max_contracts:  Max contracts per single order.
        max_notional:   Max USD notional per single order.
        dry_run:        If True, evaluate signals but never place orders.
    """
    name: str = "universal-agent"
    categories: List[str] = field(default_factory=list)
    max_markets: int = 50
    cycle_secs: float = 60.0
    min_edge: float = 0.02  # ALIGNED TO 2026 INDUSTRY STANDARD: 2% minimum edge (was 5%)
    # CRITICAL FIX: 0 = derive from live bankroll (was 50/$500 - dangerous for micro bankrolls)
    max_contracts: int = 0  # 0 = derive: 1% of bankroll / price
    max_notional: float = 0.0  # 0 = derive: 1% of bankroll
    dry_run: bool = False


# ── State ─────────────────────────────────────────────────────────────────

@dataclass
class UniversalAgentState:
    name: str
    running: bool = False
    enabled: bool = True
    cycles_run: int = 0
    markets_evaluated: int = 0
    orders_placed: int = 0
    orders_rejected: int = 0
    orders_unfilled: int = 0
    last_cycle_at: Optional[datetime] = None
    last_error: Optional[str] = None
    errors: List[str] = field(default_factory=list)
    category_counts: Dict[str, int] = field(default_factory=dict)
    order_log: List[Dict[str, Any]] = field(default_factory=list)
    fill_log: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "running": self.running,
            "enabled": self.enabled,
            "cycles_run": self.cycles_run,
            "markets_evaluated": self.markets_evaluated,
            "orders_placed": self.orders_placed,
            "orders_rejected": self.orders_rejected,
            "orders_unfilled": self.orders_unfilled,
            "last_cycle_at": self.last_cycle_at.isoformat() if self.last_cycle_at else None,
            "last_error": self.last_error,
            "category_counts": dict(self.category_counts),
            "order_log_count": len(self.order_log),
            "fill_log_count": len(self.fill_log),
        }


_MAX_LOG_ENTRIES = 200


# ── Agent ──────────────────────────────────────────────────────────────────

class KalshiUniversalAgent:
    """Sweeps the full Kalshi universe each cycle, one market at a time.

    Signal generation delegates to the existing KalshiStrategy + model stack.
    Order placement goes through route_order with the per-category mode set.
    """

    def __init__(self, config: Optional[UniversalAgentConfig] = None) -> None:
        self.config = config or UniversalAgentConfig()
        self.state = UniversalAgentState(name=self.config.name)
        self.logger = get_logger(f"merid.prediction.universal_agent.{self.config.name}")

        self._universe: Optional[KalshiUniverse] = None
        self._task: Optional[asyncio.Task] = None
        self._shutdown = asyncio.Event()

        # Lazy-import heavy subsystems to keep module import fast
        self._model: Any = None
        self._strategy: Any = None
        self._risk: Any = None

    # ── Lazy subsystem init ───────────────────────────────────────────────

    def _init_subsystems(self) -> None:
        if self._model is not None:
            return
        try:
            from merid.prediction.model import PredictionMarketModel
            from merid.prediction.strategy import KalshiStrategy, StrategyConfig
            from merid.prediction.risk import PredictionMarketRisk, PredictionRiskConfig
            self._model = PredictionMarketModel()
            self._strategy = KalshiStrategy(
                StrategyConfig(max_contracts_per_order=self.config.max_contracts),
                agent_name=getattr(self.config, "name", "universal"),
            )
            self._risk = PredictionMarketRisk(PredictionRiskConfig(
                max_notional_per_market_usd=self.config.max_notional,
                max_contracts_per_order=self.config.max_contracts,
            ))
        except Exception as exc:
            self.logger.warning("Subsystem init partial: %s", exc)

    # ── Universe ──────────────────────────────────────────────────────────

    def _get_universe(self) -> KalshiUniverse:
        if self._universe is None:
            uconf = UniverseConfig(
                max_per_agent=self.config.max_markets,
                allowed_categories=list(self.config.categories),
            )
            self._universe = get_kalshi_universe(uconf)
        return self._universe

    # ── Lifecycle ─────────────────────────────────────────────────────────

    async def start(self) -> None:
        if self.state.running:
            self.logger.warning("%s already running", self.config.name)
            return
        self._init_subsystems()
        self._shutdown.clear()
        self.state.running = True
        self.state.enabled = True
        self._task = asyncio.create_task(
            self._run_loop(), name=f"universal-agent-{self.config.name}"
        )
        cats = self.config.categories or list(KNOWN_CATEGORIES)
        self.logger.info(
            "Started %s: categories=%s, max_markets=%d, dry_run=%s",
            self.config.name, cats, self.config.max_markets, self.config.dry_run,
        )

    async def stop(self) -> None:
        self._shutdown.set()
        self.state.running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            finally:
                self._task = None
        self.logger.info("Stopped %s", self.config.name)

    def pause(self) -> None:
        self.state.enabled = False

    def resume(self) -> None:
        self.state.enabled = True

    # ── Decision loop ─────────────────────────────────────────────────────

    async def _run_loop(self) -> None:
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
                self.logger.error("Cycle error: %s", exc)

            try:
                await asyncio.wait_for(
                    self._shutdown.wait(), timeout=self.config.cycle_secs
                )
                break
            except asyncio.TimeoutError:
                pass

    async def _run_cycle(self) -> None:
        now = datetime.now(timezone.utc)
        self.state.last_cycle_at = now
        self.state.cycles_run += 1

        universe = self._get_universe()

        evaluated = 0
        for cat, mode, pool in universe.iter_categories():
            if self._shutdown.is_set():
                break

            for cm in pool:
                if self._shutdown.is_set():
                    break
                evaluated += 1
                self.state.category_counts[cat] = (
                    self.state.category_counts.get(cat, 0) + 1
                )
                try:
                    await self._evaluate_market(cm, mode)
                except Exception as exc:
                    self.logger.warning(
                        "Error evaluating %s: %s", cm.market.market_id, exc
                    )

        self.state.markets_evaluated += evaluated
        self.logger.debug(
            "[%s] cycle=%d evaluated=%d",
            self.config.name, self.state.cycles_run, evaluated,
        )

    # ── Market evaluation ─────────────────────────────────────────────────

    async def _evaluate_market(self, cm: CatalogMarket, mode: str) -> None:
        """Evaluate a single market and place an order if signal is strong enough."""
        mkt = cm.market
        ticker = mkt.market_id

        if not self._strategy:
            return

        # BUG-01 fix: enforce category_config block/read-only at the agent level so
        # the universe mode ("paper"/"live") can never bypass a "blocked" category.
        try:
            from merid_core.kalshi.category_config import is_trading_allowed
            if not is_trading_allowed(cm.category):
                self.logger.debug(
                    "Skipping %s: category '%s' is blocked in category_config",
                    ticker, cm.category,
                )
                return
        except ImportError:
            pass

        try:
            snapshot = self._build_snapshot(cm)
            signal = self._strategy.evaluate(snapshot)
        except Exception as exc:
            self.logger.debug("Signal error %s: %s", ticker, exc)
            return

        from merid.prediction.strategy import SignalAction
        if signal.action in (SignalAction.NO_ACTION, SignalAction.HOLD):
            return

        # Edge gate
        net_edge = float(signal.edge.net_edge) if signal.edge else 0.0
        if net_edge < self.config.min_edge:
            return

        # CRITICAL FIX (2026-07-21): Use ThesisSide enum for canonical direction mapping
        # Signal action determines the outcome_side (which outcome we're long on)
        # BUY_YES, SELL_NO → outcome_side=yes (long YES exposure)
        # BUY_NO, SELL_YES → outcome_side=no (long NO exposure)
        from merid.event_venues.kalshi.strategy_positions import ThesisSide
        
        # DIRECTION POLICY (2026-08-07): Enforce canonical long-only contract handling
        # Entry orders must use BUY actions only. Cross-leg equivalence is prohibited.
        # - BUY YES → long YES
        # - BUY NO → long NO
        # SELL actions are ONLY for exits (same-leg close)
        if signal.action in (SignalAction.BUY_YES,):
            outcome_side = "yes"
            thesis_side = ThesisSide.YES
            action = "buy"
        elif signal.action in (SignalAction.BUY_NO,):
            outcome_side = "no"
            thesis_side = ThesisSide.NO
            action = "buy"
        elif signal.action in (SignalAction.SELL_YES, SignalAction.SELL_NO):
            # SELL actions are only for exits - reject as entry
            self.logger.error(
                "[DIRECTION-POLICY-BREACH] signal.action=%s is a SELL action, which is only allowed for exits. "
                "Entry orders must use BUY actions (BUY_YES or BUY_NO). Rejecting candidate.",
                signal.action
            )
            return None
        else:
            # Fallback for unexpected actions
            self.logger.warning(
                "[SIGNAL-LAYER-THESIS] Unexpected signal action=%s, rejecting candidate",
                signal.action
            )
            return None

        price_cents = int(signal.limit_price_cents or 50)
        contracts = max(1, min(int(signal.contracts or 1), self.config.max_contracts))

        # DIRECTION POLICY (2026-08-07): Convert to Kalshi format using canonical mapping
        # Entry orders are always BUY actions with thesis_side determining the leg
        side_upper = thesis_side.value.upper()
        if side_upper == "YES":
            kalshi_side = "BUY_YES"
        elif side_upper == "NO":
            kalshi_side = "BUY_NO"
        else:
            # Fallback for unexpected combinations
            self.logger.warning(
                "[SIGNAL-LAYER-THESIS] Unexpected thesis_side=%s, defaulting to BUY_YES",
                side_upper
            )
            kalshi_side = "BUY_YES"

        # Risk check
        if self._risk:
            try:
                event_id = ticker.rsplit("-", 1)[0] if "-" in ticker else ticker
                check = self._risk.check_order(
                    market_id=ticker,
                    event_id=event_id,
                    side=side,
                    contracts=contracts,
                    price_cents=Decimal(str(price_cents)),
                    edge=Decimal(str(net_edge)),
                )
                if not check.allowed:
                    self.state.orders_rejected += 1
                    self.logger.debug("Risk block %s: %s", ticker, check.reason)
                    return
            except Exception as exc:
                self.logger.debug("Risk check error %s: %s", ticker, exc)

        # Resolve TradingMode from category mode string.
        # BUG-10 fix: unknown mode strings must not silently degrade to paper
        # — a misconfigured live category would paper-trade undetected.
        _VALID_MODES = {v.value for v in TradingMode}
        if mode not in _VALID_MODES:
            self.logger.error(
                "[universal-agent] Unknown trading mode %r for category %r "
                "(valid: %s) — skipping market %s",
                mode, cm.category, sorted(_VALID_MODES), ticker,
            )
            self.state.orders_rejected += 1
            return
        trading_mode = TradingMode(mode)

        log_entry = {
            "ticker": ticker,
            "category": cm.category,
            "mode": mode,
            "side": side,
            "action": action,
            "price_cents": price_cents,
            "contracts": contracts,
            "edge": round(net_edge, 4),
            "ts": datetime.now(timezone.utc).isoformat(),
            "dry_run": self.config.dry_run,
        }

        if self.config.dry_run:
            self.logger.info(f"[DRY-RUN] Would place {ticker} {mode} {side} {contracts}x@{price_cents}c")
            self._append_log(self.state.order_log, log_entry)
            return

        # Route through the standard order router with category mode
        try:
            from merid.event_venues.kalshi.decision_trace import new_decision_trace_id
            from merid.event_venues.kalshi.order_router import OrderIntent, route_order_async
            intent = OrderIntent(
                ticker=ticker,
                side=kalshi_side,  # CRITICAL FIX: Use Kalshi-formatted side (BUY_YES, SELL_YES, etc.)
                action=action,
                price_cents=price_cents,
                count=contracts,
                mode=trading_mode,
                edge_pct=net_edge,
                source=self.config.name,
                decision_trace_id=new_decision_trace_id("ua"),
                sentiment_driven=False,
            )
            # CRITICAL FIX (2026-07-19): Set client_tag to enable TP target registration
            # order_router only registers TP targets if client_tag is set AND TP/SL values exist
            intent.client_tag = intent.intent_id
            result = await route_order_async(intent)
            log_entry["result_status"] = result.status
            log_entry["latency_ms"] = result.latency_ms

            # Only actual fills count as placed trades.
            # unfilled_ioc is a completed request with zero execution and must not
            # be counted as a rejection or a strategy trade.
            if result.has_execution:
                self.state.orders_placed += 1
                self._append_log(self.state.fill_log, {**log_entry, "fill": result.fill})
                self.logger.info(
                    "[%s] %s %s %s %dx@%dc -> %s (%.1fms)",
                    self.config.name, mode.upper(), ticker, side, contracts,
                    price_cents, result.status, result.latency_ms,
                )
            elif result.status == "unfilled_ioc":
                self.state.orders_unfilled += 1
                log_entry["unfilled_reason"] = result.reason
                self.logger.debug("Order unfilled IOC %s: %s", ticker, result.reason)
            elif result.status == "rejected":
                self.state.orders_rejected += 1
                log_entry["reject_reason"] = result.reason
                self.logger.debug("Order rejected %s: %s", ticker, result.reason)

            self._append_log(self.state.order_log, log_entry)

        except Exception as exc:
            self.logger.error("Route error %s: %s", ticker, exc)

    # ── Snapshot builder ──────────────────────────────────────────────────

    def _build_snapshot(self, cm: CatalogMarket) -> Any:
        """Build a MarketSnapshot from a CatalogMarket for the strategy."""
        from merid.prediction.model import (
            MarketSnapshot, ContractState, ImpliedProbability, PredictionMarketModel,
        )
        from decimal import Decimal
        mkt = cm.market
        # CRITICAL FIX: CatalogMarket wraps EventMarket, so raw_data is on nested market.market
        if hasattr(mkt, "raw_data"):
            raw = mkt.raw_data or {}
        else:
            raw = {}

        bid = int(raw.get("yes_bid", 0) or 0)
        ask = int(raw.get("yes_ask", 0) or 0)
        last = int(raw.get("last_price", 0) or raw.get("yes_bid", 50) or 50)
        volume = int(mkt.volume or 0)
        open_interest = int(mkt.open_interest or 0)

        mid = ((bid + ask) // 2) if (bid > 0 and ask > 0) else last or 50

        # BUG-02 fix: resolve the market lifecycle state from the raw API status
        # field and close_time so the strategy state-filter does not see LISTED
        # (the dataclass default) for every market and return NO_ACTION.
        status_str = raw.get("status", "") or getattr(mkt, "status", "") or "active"
        close_time = cm.expires_at  # datetime or None
        model = PredictionMarketModel()
        resolved_state = model.determine_state(str(status_str), close_time=close_time)

        hours_left = None
        if close_time:
            from datetime import datetime, timezone
            now_utc = datetime.now(timezone.utc)
            if close_time > now_utc:
                hours_left = Decimal(str(
                    (close_time - now_utc).total_seconds() / 3600
                )).quantize(Decimal("0.01"))

        implied = ImpliedProbability(
            yes_prob=Decimal(str(mid)) / Decimal("100"),
            no_prob=Decimal(str(100 - mid)) / Decimal("100"),
            yes_bid=Decimal(bid) if bid else None,
            yes_ask=Decimal(ask) if ask else None,
            spread_cents=Decimal(ask - bid) if (bid > 0 and ask > 0) else None,
        )

        # CRITICAL FIX: 2026-07-24 - Prevent IndexError if rsplit returns empty list
        # Use safe fallback for event_id extraction
        event_id = raw.get("event_ticker")
        if not event_id:
            parts = mkt.market_id.rsplit("-", 1)
            event_id = parts[0] if parts else mkt.market_id

        return MarketSnapshot(
            market_id=mkt.market_id,
            event_id=event_id,
            title=mkt.question or mkt.market_id,
            state=resolved_state,
            implied=implied,
            volume=Decimal(volume),
            open_interest=Decimal(open_interest),
            time_to_expiry_hours=hours_left,
            close_time=close_time,
            category=cm.category or "other",
        )

    @staticmethod
    def _append_log(log: List[Dict], entry: Dict) -> None:
        log.append(entry)
        if len(log) > _MAX_LOG_ENTRIES:
            del log[: len(log) - _MAX_LOG_ENTRIES]

    async def collect_order_candidate(self, tick: int) -> Optional[Any]:
        """
        Bridge method for AgentGrid15m compatibility.
        
        This method adapts the UniversalAgent's evaluation logic to the expected
        AgentGrid15m interface that calls collect_order_candidate().
        
        Returns:
            OrderCandidate if a trading signal is generated, None otherwise
        """
        # CRITICAL DIAGNOSTIC: Log every call to confirm method is being invoked
        self.logger.info("[COLLECT-CANDIDATE] ENTER tick=%d agent=%s", tick, self.config.name)
        
        # Initialize pipeline metrics for agent grid tracking
        markets_seen = 0
        markets_with_md = 0
        markets_with_spot = 0
        markets_passing_shouldtrade = 0
        signal_calls = 0
        
        # 2026-07-11: Candidate breakdown tracking
        filtered_by_no_signal = 0
        filtered_by_edge_threshold = 0
        filtered_by_risk = 0
        filtered_by_mode = 0
        filtered_by_no_snapshot = 0
        
        try:
            # Initialize subsystems if needed
            self._init_subsystems()
            if not self._strategy or not self._universe:
                self.logger.info("[COLLECT-CANDIDATE] No strategy/universe available tick=%d agent=%s", tick, self.config.name)
                self._last_pipeline_metrics = {
                    'markets_seen': 0,
                    'markets_with_md': 0,
                    'markets_with_spot': 0,
                    'markets_passing_shouldtrade': 0,
                    'signal_calls': 0,
                }
                return None
            
            # Get first available market for simple signal generation
            markets = list(self._universe.get_markets().values())[:5]  # Check first 5 markets
            if not markets:
                self.logger.info("[COLLECT-CANDIDATE] No markets available tick=%d agent=%s", tick, self.config.name)
                self._last_pipeline_metrics = {
                    'markets_seen': 0,
                    'markets_with_md': 0,
                    'markets_with_spot': 0,
                    'markets_passing_shouldtrade': 0,
                    'signal_calls': 0,
                }
                return None
            
            # Evaluate markets until we find a trading signal
            for cm in markets:
                markets_seen += 1
                signal_calls += 1
                
                try:
                    # Get category mode for this market
                    mode = get_category_mode(cm.category)
                    if mode not in ["paper", "shadow", "live"]:
                        filtered_by_mode += 1
                        continue  # Skip invalid modes
                    
                    # Check if market has market data (bid/ask)
                    if hasattr(cm, 'market') and hasattr(cm.market, 'raw_data'):
                        raw = cm.market.raw_data or {}
                        if raw.get('yes_bid') and raw.get('yes_ask'):
                            markets_with_md += 1
                    
                    # Build snapshot and evaluate signal
                    snapshot = self._build_snapshot(cm)
                    if not snapshot:
                        filtered_by_no_snapshot += 1
                        continue  # Skip if no snapshot available
                    
                    markets_passing_shouldtrade += 1
                    
                    signal = self._strategy.evaluate(snapshot)
                    if not signal:
                        filtered_by_no_signal += 1
                        continue  # Skip if no signal
                    
                    # Check if signal indicates a trade
                    from merid.prediction.strategy import SignalAction
                    if signal.action in (SignalAction.NO_ACTION, SignalAction.HOLD):
                        continue  # Skip non-trading signals
                    
                    # Check edge threshold
                    net_edge = float(signal.edge.net_edge) if signal.edge else 0.0
                    if net_edge < self.config.min_edge:
                        filtered_by_edge_threshold += 1
                        self.logger.debug("[COLLECT-CANDIDATE] Edge too low %s < %s for %s", net_edge, self.config.min_edge, cm.market.market_id)
                        continue  # Skip if edge too low
                    
                    # Risk check
                    if self._risk:
                        try:
                            # CRITICAL FIX (2026-07-21): Use ThesisSide enum for canonical direction
                            from merid.event_venues.kalshi.strategy_positions import ThesisSide
                            
                            # DIRECTION POLICY (2026-08-07): Enforce canonical long-only contract handling
                            # Entry orders must use BUY actions only. Cross-leg equivalence is prohibited.
                            if signal.action in (SignalAction.BUY_YES,):
                                side = "yes"
                                thesis_side = ThesisSide.YES
                                action = "buy"
                            elif signal.action in (SignalAction.BUY_NO,):
                                side = "no"
                                thesis_side = ThesisSide.NO
                                action = "buy"
                            elif signal.action in (SignalAction.SELL_YES, SignalAction.SELL_NO):
                                # SELL actions are only for exits - reject as entry
                                self.logger.error(
                                    "[DIRECTION-POLICY-BREACH] signal.action=%s is a SELL action, which is only allowed for exits. "
                                    "Entry orders must use BUY actions (BUY_YES or BUY_NO). Rejecting candidate.",
                                    signal.action
                                )
                                continue
                            else:
                                # Fallback for unexpected actions
                                self.logger.warning(
                                    "[SIGNAL-LAYER-THESIS] Unexpected signal action=%s, rejecting candidate",
                                    signal.action
                                )
                                continue
                            
                            contracts = max(1, min(int(signal.contracts or 1), self.config.max_contracts))
                            price_cents = int(signal.limit_price_cents or 50)
                            
                            check = self._risk.check_order(
                                market_id=cm.market.market_id,
                                event_id=cm.market.market_id.rsplit("-", 1)[0] if "-" in cm.market.market_id else cm.market.market_id,
                                side=side,
                                contracts=contracts,
                                price_cents=Decimal(str(price_cents)),
                                edge=Decimal(str(net_edge)),
                            )
                            if not check.allowed:
                                filtered_by_risk += 1
                                self.logger.debug("[COLLECT-CANDIDATE] Risk blocked %s: %s", cm.market.market_id, check.reason)
                                continue  # Skip if risk blocks
                        except Exception as exc:
                            self.logger.debug("[COLLECT-CANDIDATE] Risk check error %s: %s", cm.market.market_id, exc)
                            continue
                    
                    # Create OrderCandidate from signal
                    from merid.prediction.trading_agent import OrderCandidate
                    # DIRECTION POLICY (2026-08-07): Entry orders are always BUY actions
                    action = "buy"
                    side = side  # Use the side determined from thesis_side above
                    
                    candidate = OrderCandidate(
                        market_id=cm.market.market_id,
                        side=side,
                        action=action,
                        price_cents=int(signal.limit_price_cents or 50),
                        contracts=max(1, min(int(signal.contracts or 1), self.config.max_contracts)),
                        edge=net_edge,
                        confidence=float(signal.confidence or 0.5),
                        timestamp=datetime.now(timezone.utc),
                        agent_name=self.config.name,
                    )
                    
                    self.logger.info(
                        "[COLLECT-CANDIDATE] CREATED side=%s size=%s price=%s edge=%.3f market=%s tick=%d agent=%s",
                        candidate.side, candidate.contracts, candidate.price_cents, candidate.edge,
                        candidate.market_id, tick, self.config.name
                    )
                    
                    # Store pipeline metrics before returning
                    self._last_pipeline_metrics = {
                        'markets_seen': markets_seen,
                        'markets_with_md': markets_with_md,
                        'markets_with_spot': markets_with_spot,
                        'markets_passing_shouldtrade': markets_passing_shouldtrade,
                        'signal_calls': signal_calls,
                    }
                    
                    return candidate
                    
                except Exception as exc:
                    self.logger.debug("[COLLECT-CANDIDATE] Error evaluating %s: %s", cm.market.market_id, exc)
                    continue
            
            # No trading signals found
            self.logger.info(
                "[COLLECT-CANDIDATE] No trading signals found tick=%d agent=%s (checked %d markets) "
                "breakdown: no_snapshot=%d no_signal=%d edge_threshold=%d risk=%d mode=%d",
                tick, self.config.name, len(markets),
                filtered_by_no_snapshot, filtered_by_no_signal, filtered_by_edge_threshold,
                filtered_by_risk, filtered_by_mode
            )
            
            # Store pipeline metrics even when no candidate found
            self._last_pipeline_metrics = {
                'markets_seen': markets_seen,
                'markets_with_md': markets_with_md,
                'markets_with_spot': markets_with_spot,
                'markets_passing_shouldtrade': markets_passing_shouldtrade,
                'signal_calls': signal_calls,
                'filtered_by_no_snapshot': filtered_by_no_snapshot,
                'filtered_by_no_signal': filtered_by_no_signal,
                'filtered_by_edge_threshold': filtered_by_edge_threshold,
                'filtered_by_risk': filtered_by_risk,
                'filtered_by_mode': filtered_by_mode,
            }
            
            return None
            
        except Exception as exc:
            self.logger.error("[COLLECT-CANDIDATE] FAILED: %s", exc, exc_info=True)
            
            # Store pipeline metrics even on exception
            self._last_pipeline_metrics = {
                'markets_seen': markets_seen,
                'markets_with_md': markets_with_md,
                'markets_with_spot': markets_with_spot,
                'markets_passing_shouldtrade': markets_passing_shouldtrade,
                'signal_calls': signal_calls,
                'filtered_by_no_snapshot': filtered_by_no_snapshot,
                'filtered_by_no_signal': filtered_by_no_signal,
                'filtered_by_edge_threshold': filtered_by_edge_threshold,
                'filtered_by_risk': filtered_by_risk,
                'filtered_by_mode': filtered_by_mode,
            }
            
            return None


# ── Singleton registry ─────────────────────────────────────────────────────

import threading as _threading

_agents: Dict[str, KalshiUniversalAgent] = {}


def register_universal_agent(agent: KalshiUniversalAgent) -> None:
    """Register a KalshiUniversalAgent with the global registry."""
    global _agents
    _agents[agent.config.name] = agent




def get_universal_agent(name: str, config: Optional[UniversalAgentConfig] = None) -> KalshiUniversalAgent:
    """Get a KalshiUniversalAgent by name, creating it if needed."""
    global _agents
    if name not in _agents:
        cfg = config or UniversalAgentConfig(name=name)
        _agents[name] = KalshiUniversalAgent(cfg)
    return _agents[name]
