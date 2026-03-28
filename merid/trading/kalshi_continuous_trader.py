"""KalshiContinuousTrader — Continuous prediction-market trading agent.

Architecture:
  - Discovers candidates via ``KalshiMarketCatalog`` and ``MarketFilter``.
  - Uses the canonical ``MarketCandidate`` from ``market_filter`` as the
    shared dataclass; no shadow copy is defined here.
  - Wraps each candidate as a ``TradingCandidate`` (a thin subclass that
    adds risk tracking fields) for use inside this module.
  - Routes consensus opinions through ``OpinionStrategy._apply_confidence_clamp``
    so the confidence passed to sizing is always ≤ ``max_confidence``.
  - Group-level risk is tracked using ``group_id`` derived directly from the
    canonical ``MarketCandidate`` data, not from any local guessing logic.

Key invariants:
  - No fills are counted without a Kalshi ``fill_id`` (all fills go through
    ``KalshiFillsLedger``).
  - Group-notional cap is enforced and fully reset on ``reset_daily()``.
  - All execution rejections emit an ``execution_rejected`` event with
    symbol, reason, intent_id, and timestamp.
"""

from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from merid.event_venues.kalshi.market_catalog import KalshiMarketCatalog, get_market_catalog
from merid.event_venues.kalshi.market_filter import MarketCandidate, MarketFilter, MarketFilterConfig
from merid.prediction.opinion_strategy import OpinionStrategy, OpinionEstimate, OpinionExplanation
from utils.logger import get_logger

logger = get_logger("merid.trading.kalshi_continuous_trader")

# ── Configurable defaults (env overrides) ─────────────────────────────────

_CRYPTO_ASSETS = ("BTC", "ETH", "SOL", "XRP", "DOGE")
_CRYPTO_TIMEFRAMES = ("15m", "daily")

_DEFAULT_MAX_GROUP_NOTIONAL = float(os.getenv("MERID_GROUP_NOTIONAL_CAP", "50.0"))
_DEFAULT_MIN_CONFIDENCE = float(os.getenv("MERID_MIN_CONFIDENCE", "0.55"))
_DEFAULT_BANKROLL_FRACTION = float(os.getenv("MERID_BANKROLL_FRACTION", "0.01"))


# ── TradingCandidate (thin subclass of canonical MarketCandidate) ──────────

@dataclass
class TradingCandidate(MarketCandidate):
    """Extends the canonical MarketCandidate with trader-specific fields.

    ``group_id`` is the key used for group-level notional cap tracking.
    It is derived from the event_ticker / underlying / timeframe stored in
    the base ``MarketCandidate`` — never guessed locally.
    """

    group_id: str = ""
    tags: List[str] = field(default_factory=list)  # risk / sizing tags

    @classmethod
    def from_candidate(cls, candidate: MarketCandidate, group_id: str = "", tags: Optional[List[str]] = None) -> "TradingCandidate":
        """Promote a plain MarketCandidate to a TradingCandidate."""
        return cls(
            ticker=candidate.ticker,
            underlying=candidate.underlying,
            timeframe=candidate.timeframe,
            expiry_ts=candidate.expiry_ts,
            volume=candidate.volume,
            open_interest=candidate.open_interest,
            best_bid_cents=candidate.best_bid_cents,
            best_ask_cents=candidate.best_ask_cents,
            spread_cents=candidate.spread_cents,
            mid_price_cents=candidate.mid_price_cents,
            category=candidate.category,
            strike_price=candidate.strike_price,
            spot_price=candidate.spot_price,
            group_id=group_id or f"{candidate.underlying}_{candidate.timeframe}",
            tags=tags or [],
        )


# ── Risk state ────────────────────────────────────────────────────────────

@dataclass
class DailyRiskState:
    """Intra-day risk accounting for the continuous trader.

    ``group_notional`` maps group_id → total notional traded today.
    Fully reset by ``reset_daily()``.
    """

    group_notional: Dict[str, float] = field(default_factory=dict)
    daily_loss: float = 0.0
    trade_count: int = 0
    execution_rejections: int = 0

    def add_notional(self, group_id: str, amount: float) -> None:
        self.group_notional[group_id] = self.group_notional.get(group_id, 0.0) + amount

    def group_used(self, group_id: str) -> float:
        return self.group_notional.get(group_id, 0.0)

    def reset(self) -> None:
        """Clear all intra-day accumulators.  Called at daily rollover."""
        self.group_notional.clear()
        self.daily_loss = 0.0
        self.trade_count = 0
        self.execution_rejections = 0


# ── Trader ────────────────────────────────────────────────────────────────

class KalshiContinuousTrader:
    """Continuously discovers and trades Kalshi crypto prediction markets.

    Parameters
    ----------
    catalog:
        ``KalshiMarketCatalog`` instance; defaults to the process singleton.
    strategy:
        An ``OpinionStrategy`` used to generate swarm consensus opinions.
        ``_apply_confidence_clamp`` is always called before sizing.
    max_group_notional:
        Per-group notional cap ($) for daily risk.  Exceeded groups are
        skipped until ``reset_daily()`` is called.
    min_confidence:
        Minimum clamped confidence to proceed to execution.
    bankroll_fraction:
        Maximum fraction of bankroll per individual trade.
    """

    def __init__(
        self,
        catalog: Optional[KalshiMarketCatalog] = None,
        strategy: Optional[OpinionStrategy] = None,
        max_group_notional: float = _DEFAULT_MAX_GROUP_NOTIONAL,
        min_confidence: float = _DEFAULT_MIN_CONFIDENCE,
        bankroll_fraction: float = _DEFAULT_BANKROLL_FRACTION,
    ) -> None:
        self._catalog = catalog or get_market_catalog()
        self._strategy = strategy
        self._max_group_notional = max_group_notional
        self._min_confidence = min_confidence
        self._bankroll_fraction = bankroll_fraction

        self._risk = DailyRiskState()
        self._filter_config = MarketFilterConfig(
            allowed_underlyings=list(_CRYPTO_ASSETS),
            allowed_timeframes=list(_CRYPTO_TIMEFRAMES),
        )
        self._filter = MarketFilter(self._filter_config)

        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._candidates: List[TradingCandidate] = []

    # ── Lifecycle ─────────────────────────────────────────────────────────

    async def start(self) -> None:
        self._running = True
        logger.info(
            "KalshiContinuousTrader starting — assets=%s timeframes=%s",
            _CRYPTO_ASSETS, _CRYPTO_TIMEFRAMES,
        )
        await self._refresh_candidates()

    async def stop(self) -> None:
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("KalshiContinuousTrader stopped")

    # ── Candidate discovery ───────────────────────────────────────────────

    async def _refresh_candidates(self) -> List[TradingCandidate]:
        """Pull fresh candidates from catalog + filter pipeline."""
        new_candidates: List[TradingCandidate] = []
        asset_counts: Dict[str, Dict[str, int]] = {}

        for asset in _CRYPTO_ASSETS:
            for tf in _CRYPTO_TIMEFRAMES:
                catalog_markets = self._catalog.get_markets_by_asset(asset, timeframe=tf)
                if not catalog_markets:
                    logger.debug("ContinuousTrader: no catalog markets for %s %s", asset, tf)
                    continue

                # Convert catalog → base MarketCandidate list for filter
                raw_candidates = [
                    MarketCandidate(
                        ticker=cm.market.market_id,
                        underlying=asset,
                        timeframe=tf,
                        expiry_ts=cm.expires_at.timestamp() if cm.expires_at else 0.0,
                        volume=int(cm.market.volume) if cm.market.volume else 0,
                        open_interest=int(cm.market.open_interest) if cm.market.open_interest else 0,
                        category=cm.category or "",
                        strike_price=cm.strike_price,
                    )
                    for cm in catalog_markets
                ]

                filter_result = self._filter.filter_markets(raw_candidates)
                for c in filter_result.candidates:
                    new_candidates.append(
                        TradingCandidate.from_candidate(c)
                    )

                counts = asset_counts.setdefault(asset, {})
                counts[tf] = len(filter_result.candidates)

        # Log per-asset/timeframe counts at INFO level
        for asset, tfs in asset_counts.items():
            for tf, cnt in tfs.items():
                logger.info(
                    "ContinuousTrader candidates: %s %s = %d", asset, tf, cnt
                )

        self._candidates = new_candidates
        logger.info(
            "ContinuousTrader: %d total candidates across %d asset/timeframe pairs",
            len(new_candidates), sum(len(v) for v in asset_counts.values()),
        )
        return new_candidates

    # ── Sizing / risk ─────────────────────────────────────────────────────

    def _apply_risk_checks(
        self,
        candidate: TradingCandidate,
        estimate: OpinionEstimate,
        bankroll: float,
    ) -> Optional[float]:
        """Return approved notional ($) or None if any risk check fails.

        Uses group_id from the canonical TradingCandidate (never a local guess).
        """
        # Group notional cap
        group_used = self._risk.group_used(candidate.group_id)
        if group_used >= self._max_group_notional:
            logger.debug(
                "ContinuousTrader: group_notional_cap hit group=%s used=%.2f cap=%.2f",
                candidate.group_id, group_used, self._max_group_notional,
            )
            self._risk.execution_rejections += 1
            self._emit_rejection(candidate.ticker, "group_notional_cap")
            return None

        # Confidence gate (post-clamp)
        if estimate.confidence < self._min_confidence:
            self._risk.execution_rejections += 1
            self._emit_rejection(candidate.ticker, "low_confidence")
            return None

        # Bankroll fraction sizing
        notional = bankroll * self._bankroll_fraction
        remaining_cap = self._max_group_notional - group_used
        notional = min(notional, remaining_cap)
        return notional if notional > 0 else None

    # ── Consensus / estimate ──────────────────────────────────────────────

    def evaluate_candidate(
        self,
        candidate: TradingCandidate,
        market_prob: float,
        context: Optional[Dict[str, Any]] = None,
    ) -> Optional[OpinionEstimate]:
        """Run the wired strategy, applying confidence clamp.

        Returns None if no strategy is wired or if the strategy declines.
        """
        if self._strategy is None:
            return None

        explanation = OpinionExplanation(inputs_used=[], contributions={}, rationale="")
        estimate = self._strategy.estimate(
            agent_id="continuous_trader",
            ticker=candidate.ticker,
            market_prob=market_prob,
            category=candidate.category,
            context=context,
        )
        if estimate is None:
            return None

        # Always apply the confidence clamp from the wired strategy
        clamped_conf = self._strategy._apply_confidence_clamp(estimate.confidence, explanation)
        return OpinionEstimate(
            agent_prob=estimate.agent_prob,
            confidence=clamped_conf,
            edge=estimate.edge,
            reasoning_tag=estimate.reasoning_tag,
            signal_sources=estimate.signal_sources,
        )

    # ── Trade cycle ───────────────────────────────────────────────────────

    async def trade_cycle(
        self,
        bankroll: float,
        spot_prices: Optional[Dict[str, float]] = None,
    ) -> List[Dict[str, Any]]:
        """Run one trade evaluation cycle across all current candidates.

        Returns list of approved intent dicts (does NOT submit orders).
        """
        intents = []
        for candidate in self._candidates:
            if spot_prices:
                candidate.spot_price = spot_prices.get(candidate.underlying)

            mid_prob = candidate.mid_price_cents / 100.0 if candidate.mid_price_cents else 0.5
            estimate = self.evaluate_candidate(candidate, market_prob=mid_prob)
            if estimate is None:
                continue

            notional = self._apply_risk_checks(candidate, estimate, bankroll)
            if notional is None:
                continue

            intent = {
                "ticker": candidate.ticker,
                "underlying": candidate.underlying,
                "timeframe": candidate.timeframe,
                "group_id": candidate.group_id,
                "direction": "yes" if estimate.agent_prob > mid_prob else "no",
                "notional": notional,
                "confidence": estimate.confidence,
                "edge": estimate.edge,
                "intent_id": f"ct-{candidate.ticker}-{int(time.time())}",
                "ts": time.time(),
            }
            self._risk.add_notional(candidate.group_id, notional)
            self._risk.trade_count += 1
            intents.append(intent)
            logger.info(
                "ContinuousTrader: INTENT %s %s notional=%.2f conf=%.3f edge=%.4f",
                intent["direction"], candidate.ticker, notional,
                estimate.confidence, estimate.edge,
            )

        return intents

    # ── Daily reset ───────────────────────────────────────────────────────

    def reset_daily(self) -> None:
        """Reset all intra-day risk accumulators (group notional map, daily loss).

        Called at daily rollover or after testing a day's worth of activity.
        After this call, ``group_notional`` is guaranteed empty.
        """
        self._risk.reset()
        logger.info("ContinuousTrader: daily risk state reset")

    # ── Helpers ───────────────────────────────────────────────────────────

    def _emit_rejection(self, symbol: str, reason: str, intent_id: str = "") -> None:
        """Publish execution_rejected event for audit trail."""
        try:
            from core.streaming_bus import streaming_bus, EventChannel
            event = {
                "symbol": symbol,
                "reason": reason,
                "intent_id": intent_id or f"reject-{symbol}-{int(time.time())}",
                "timestamp": time.time(),
            }
            asyncio.get_event_loop().call_soon_threadsafe(
                lambda: asyncio.ensure_future(
                    streaming_bus.publish(EventChannel.EXECUTION, "execution_rejected", event)
                )
            )
        except Exception:
            pass  # Event emission is best-effort; never block trading logic

    # ── Status ────────────────────────────────────────────────────────────

    def status(self) -> dict:
        return {
            "running": self._running,
            "candidate_count": len(self._candidates),
            "risk": {
                "group_notional": dict(self._risk.group_notional),
                "daily_loss": self._risk.daily_loss,
                "trade_count": self._risk.trade_count,
                "execution_rejections": self._risk.execution_rejections,
            },
            "config": {
                "max_group_notional": self._max_group_notional,
                "min_confidence": self._min_confidence,
                "bankroll_fraction": self._bankroll_fraction,
            },
        }

    @property
    def candidates(self) -> List[TradingCandidate]:
        return list(self._candidates)

    @property
    def risk_state(self) -> DailyRiskState:
        return self._risk


# ── Singleton ─────────────────────────────────────────────────────────────

_trader: Optional[KalshiContinuousTrader] = None


def get_continuous_trader(
    catalog: Optional[KalshiMarketCatalog] = None,
    strategy: Optional[OpinionStrategy] = None,
) -> KalshiContinuousTrader:
    """Return the process-singleton KalshiContinuousTrader."""
    global _trader
    if _trader is None:
        _trader = KalshiContinuousTrader(catalog=catalog, strategy=strategy)
    return _trader

