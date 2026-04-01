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
import math
import os
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Deque, Dict, List, Optional

from merid.event_venues.kalshi.market_catalog import KalshiMarketCatalog, get_market_catalog
from merid.event_venues.kalshi.market_filter import MarketCandidate, MarketFilter, MarketFilterConfig
from merid.formulas import generate_correlation_id
from merid.prediction.opinion_strategy import OpinionStrategy, OpinionEstimate, OpinionExplanation
from utils.logger import get_logger

logger = get_logger("merid.trading.kalshi_continuous_trader")

# ── Configurable defaults (env overrides) ─────────────────────────────────

_CRYPTO_ASSETS = ("BTC", "ETH", "SOL", "XRP", "DOGE")
_CRYPTO_TIMEFRAMES = ("15m", "1h", "daily", "weekly", "monthly")

_DEFAULT_MAX_GROUP_NOTIONAL = float(os.getenv("MERID_GROUP_NOTIONAL_CAP", "50.0"))
_DEFAULT_MIN_CONFIDENCE = float(os.getenv("MERID_MIN_CONFIDENCE", "0.55"))
_DEFAULT_BANKROLL_FRACTION = float(os.getenv("MERID_BANKROLL_FRACTION", "0.01"))
_DEFAULT_MAX_YES_PRICE = float(os.getenv("MERID_MAX_YES_PRICE", "0.50"))
_DEFAULT_KELLY_FRACTION = float(os.getenv("MERID_KELLY_FRACTION", "0.25"))
_DEFAULT_MIN_EDGE = float(os.getenv("MERID_MIN_EDGE", "0.02"))

# Fallback YES price (cents) when a candidate has no best_ask or mid price data.
# Used only in the max-price guard inside trade_cycle().
_FALLBACK_YES_PRICE_CENTS = 50

# Number of past scan cycles to retain for the rolling volume-band block-rate average.
# At the default ~60s candidate refresh interval this covers roughly 20 minutes.
_VOLUME_BAND_RATE_HISTORY_MAXLEN = 20


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
            best_yes_bid=candidate.best_yes_bid,
            best_yes_ask=candidate.best_yes_ask,
            best_no_bid=candidate.best_no_bid,
            best_no_ask=candidate.best_no_ask,
            edge_pct=candidate.edge_pct,
            model_prob=candidate.model_prob,
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


# ── Sizing result ─────────────────────────────────────────────────────────

@dataclass
class SizingResult:
    """Output of ``signal_to_sizing`` — captures Kelly and sizing arithmetic."""
    edge: float = 0.0
    win_prob: float = 0.5
    payout_cents: float = 0.0
    kelly_raw: float = 0.0
    kelly_frac: float = 0.0
    size_contracts: int = 0
    notional_usd: float = 0.0
    source: str = "none"      # "signal" | "strategy" | "none"


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
    max_yes_price:
        Hard cap (in dollars, e.g. 0.50 = 50¢) on the YES price the trader
        will pay per contract.  Any YES intent whose implied price exceeds
        this cap is dropped with a ``max_yes_price_cap`` rejection log.
        Configurable via ``MERID_MAX_YES_PRICE`` env var; default 0.50.
    """

    def __init__(
        self,
        catalog: Optional[KalshiMarketCatalog] = None,
        strategy: Optional[OpinionStrategy] = None,
        max_group_notional: float = _DEFAULT_MAX_GROUP_NOTIONAL,
        min_confidence: float = _DEFAULT_MIN_CONFIDENCE,
        bankroll_fraction: float = _DEFAULT_BANKROLL_FRACTION,
        max_yes_price: float = _DEFAULT_MAX_YES_PRICE,
        kelly_fraction: float = _DEFAULT_KELLY_FRACTION,
        min_edge: float = _DEFAULT_MIN_EDGE,
    ) -> None:
        self._catalog = catalog or get_market_catalog()
        self._strategy = strategy
        self._max_group_notional = max_group_notional
        self._min_confidence = min_confidence
        self._bankroll_fraction = bankroll_fraction
        self._max_yes_price = max_yes_price
        self._kelly_fraction = kelly_fraction
        self._min_edge = min_edge

        self._risk = DailyRiskState()
        self._filter_config = MarketFilterConfig(
            allowed_underlyings=list(_CRYPTO_ASSETS),
            allowed_timeframes=list(_CRYPTO_TIMEFRAMES),
        )
        self._filter = MarketFilter(self._filter_config)

        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._candidates: List[TradingCandidate] = []

        # ── Filter telemetry ────────────────────────────────────────────────
        # Aggregated filter stats from the most recent _refresh_candidates() call.
        # Empty dict until the first scan completes.
        self._last_scan_filter_stats: Dict[str, Any] = {}
        # Rolling history of per-scan volume_band_block_rate values (oldest first).
        # Capped at _VOLUME_BAND_RATE_HISTORY_MAXLEN entries.
        self._volume_band_rate_history: Deque[float] = deque(
            maxlen=_VOLUME_BAND_RATE_HISTORY_MAXLEN
        )

    # ── Lifecycle ─────────────────────────────────────────────────────────

    async def start(self) -> None:
        self._running = True
        logger.info(
            "KalshiContinuousTrader starting — assets=%s timeframes=%s "
            "max_yes_price=%.2f min_confidence=%.2f bankroll_fraction=%.4f",
            _CRYPTO_ASSETS, _CRYPTO_TIMEFRAMES,
            self._max_yes_price, self._min_confidence, self._bankroll_fraction,
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

        # Accumulators for cross-asset/timeframe filter telemetry for this scan run.
        scan_total_input: int = 0
        scan_rejected_volume_band: int = 0

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

                # Accumulate filter telemetry across all (asset, timeframe) loops.
                scan_total_input += filter_result.total_input
                scan_rejected_volume_band += filter_result.rejected_volume_band

        # Compute per-scan volume-band block rate and update rolling history.
        scan_block_rate = (
            scan_rejected_volume_band / scan_total_input
            if scan_total_input > 0
            else 0.0
        )
        self._volume_band_rate_history.append(scan_block_rate)

        # Store aggregated stats for the most recent scan so status() can expose them.
        rolling_avg = (
            sum(self._volume_band_rate_history) / len(self._volume_band_rate_history)
            if self._volume_band_rate_history
            else 0.0
        )
        self._last_scan_filter_stats = {
            "scan_total_input": scan_total_input,
            "scan_rejected_volume_band": scan_rejected_volume_band,
            "volume_band_block_rate": round(scan_block_rate, 4),
            "volume_band_block_rate_rolling_avg": round(rolling_avg, 4),
            "rolling_window_scans": len(self._volume_band_rate_history),
        }
        logger.info(
            "ContinuousTrader filter: total_input=%d volume_band_rejected=%d "
            "block_rate=%.3f rolling_avg=%.3f (window=%d scans)",
            scan_total_input, scan_rejected_volume_band,
            scan_block_rate, rolling_avg, len(self._volume_band_rate_history),
        )

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

    def signal_to_sizing(
        self,
        candidate: TradingCandidate,
        bankroll: float,
        *,
        edge_override: Optional[float] = None,
        win_prob_override: Optional[float] = None,
    ) -> SizingResult:
        """Compute Kelly-based sizing from candidate edge and market data.

        Sources edge from (in priority order):
          1. ``edge_override`` parameter (for testing / manual injection).
          2. ``candidate.edge_pct`` (enriched from Kalshi signals).
          3. ``estimate.edge`` from the wired ``OpinionStrategy``.
          4. Fallback to 0 (no edge → no trade).

        Uses the binary Kelly formula::

            implied_prob  = mid_price / 100
            win_prob      = implied_prob + edge
            payout        = 100 - price_cents
            b             = payout / price_cents
            kelly_raw     = (p * b - q) / b
            kelly_frac    = kelly_raw * kelly_fraction

        Returns a ``SizingResult`` with all intermediate values for audit.
        """
        price_cents = candidate.mid_price_cents or _FALLBACK_YES_PRICE_CENTS
        implied_prob = price_cents / 100.0

        # 1. Resolve edge (priority: override > candidate signal > strategy > 0)
        edge = 0.0
        source = "none"

        if edge_override is not None:
            edge = edge_override
            source = "override"
        elif candidate.edge_pct is not None and candidate.edge_pct != 0.0:
            edge = candidate.edge_pct / 100.0  # edge_pct is in percentage
            source = "signal"
        else:
            # Try strategy-based edge
            mid_prob = implied_prob if implied_prob > 0 else 0.5
            estimate = self.evaluate_candidate(candidate, market_prob=mid_prob)
            if estimate is not None and estimate.edge != 0.0:
                edge = estimate.edge
                source = "strategy"

        # 2. Compute win probability
        if win_prob_override is not None:
            win_prob = win_prob_override
        else:
            win_prob = max(0.01, min(0.99, implied_prob + edge))

        # 3. Kelly formula for binary contract
        payout_cents = 100 - price_cents
        if price_cents <= 0 or price_cents >= 100 or payout_cents <= 0:
            result = SizingResult(edge=edge, win_prob=win_prob, source=source)
            logger.info(
                "signal_to_sizing: %s edge=%.4f win_prob=%.4f payout=%.2f | "
                "kelly_raw=%.4f kelly_frac=%.4f (k=%.2f%%) source=%s",
                candidate.ticker, edge, win_prob, 0.0, 0.0, 0.0,
                self._kelly_fraction * 100, source,
            )
            return result

        b = payout_cents / price_cents  # net odds ratio
        p = win_prob
        q = 1.0 - p
        kelly_raw = (p * b - q) / b if b > 0 else 0.0

        # Clamp negative Kelly → no trade; negative edge always skips regardless of magnitude
        if kelly_raw <= 0 or edge < self._min_edge:
            result = SizingResult(
                edge=edge, win_prob=win_prob, payout_cents=float(payout_cents),
                kelly_raw=kelly_raw, source=source,
            )
            logger.info(
                "signal_to_sizing: %s edge=%.4f win_prob=%.4f payout=%.2f | "
                "kelly_raw=%.4f kelly_frac=%.4f (k=%.2f%%) source=%s",
                candidate.ticker, edge, win_prob, float(payout_cents),
                kelly_raw, 0.0, self._kelly_fraction * 100, source,
            )
            return result

        kelly_frac = kelly_raw * self._kelly_fraction
        notional = bankroll * kelly_frac
        price_dollars = price_cents / 100.0
        size_contracts = int(math.floor(notional / price_dollars))

        result = SizingResult(
            edge=edge,
            win_prob=win_prob,
            payout_cents=float(payout_cents),
            kelly_raw=kelly_raw,
            kelly_frac=kelly_frac,
            size_contracts=size_contracts,
            notional_usd=notional,
            source=source,
        )
        logger.info(
            "signal_to_sizing: %s edge=%.4f win_prob=%.4f payout=%.2f | "
            "kelly_raw=%.4f kelly_frac=%.4f (k=%.2f%%) size=%d source=%s",
            candidate.ticker, edge, win_prob, float(payout_cents),
            kelly_raw, kelly_frac, self._kelly_fraction * 100,
            size_contracts, source,
        )
        return result

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

        For each candidate:
          1. Enrich with spot price (if available).
          2. Compute edge and Kelly sizing via ``signal_to_sizing``.
          3. Fall back to strategy-based edge if no signal edge.
          4. Apply risk checks (group cap, confidence gate).
          5. Apply max-YES-price guard.

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

            # Use signal_to_sizing for Kelly-based notional
            sizing = self.signal_to_sizing(candidate, bankroll)

            notional = self._apply_risk_checks(candidate, estimate, bankroll)
            if notional is None:
                continue

            # When Kelly sizing produces a positive notional, prefer it
            if sizing.notional_usd > 0:
                notional = min(notional, sizing.notional_usd)

            intent = {
                "ticker": candidate.ticker,
                "underlying": candidate.underlying,
                "timeframe": candidate.timeframe,
                "group_id": candidate.group_id,
                "direction": "yes" if estimate.agent_prob > mid_prob else "no",
                "notional": notional,
                "confidence": estimate.confidence,
                "edge": sizing.edge,
                "kelly_raw": sizing.kelly_raw,
                "kelly_frac": sizing.kelly_frac,
                "size_contracts": sizing.size_contracts,
                "sizing_source": sizing.source,
                "intent_id": generate_correlation_id(datetime.now(timezone.utc), prefix="kalshi-trader"),
                "ts": time.time(),
            }

            # Max YES price guard — drop YES intents whose implied price exceeds cap
            if intent["direction"] == "yes":
                yes_price_cents = candidate.best_ask_cents or candidate.mid_price_cents or _FALLBACK_YES_PRICE_CENTS
                max_cents = int(self._max_yes_price * 100)
                if yes_price_cents > max_cents:
                    logger.info(
                        "ContinuousTrader: MAX_YES_PRICE_CAP dropped YES intent "
                        "ticker=%s price=%d¢ cap=%d¢",
                        candidate.ticker, yes_price_cents, max_cents,
                    )
                    self._risk.execution_rejections += 1
                    self._emit_rejection(candidate.ticker, "max_yes_price_cap", intent["intent_id"])
                    continue

            self._risk.add_notional(candidate.group_id, notional)
            self._risk.trade_count += 1
            intents.append(intent)
            logger.info(
                "ContinuousTrader: INTENT %s %s notional=%.2f conf=%.3f edge=%.4f "
                "kelly_raw=%.4f kelly_frac=%.4f size=%d source=%s",
                intent["direction"], candidate.ticker, notional,
                estimate.confidence, intent["edge"],
                sizing.kelly_raw, sizing.kelly_frac,
                sizing.size_contracts, sizing.source,
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
                "max_yes_price": self._max_yes_price,
                "kelly_fraction": self._kelly_fraction,
                "min_edge": self._min_edge,
            },
            # ── Filter telemetry (populated after first _refresh_candidates call) ──
            # Use these to audit the relative-volume band: a healthy block_rate is
            # 15–40% of input candidates.  Below 10% the band may be too loose;
            # above 60% it may be too restrictive.  rolling_avg smooths scan noise.
            "filter": dict(self._last_scan_filter_stats),
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

