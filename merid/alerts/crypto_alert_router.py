"""
MERID Crypto Alert Router
Classifies live Kalshi crypto markets into tags and emits batched alerts.
"""
from __future__ import annotations

import asyncio
import html
import logging
import time
from collections import Counter
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional

from config.crypto_alert_config import CryptoAlertConfig
from config.kalshi_crypto_config import kalshi_ticker_to_asset
from merid.prediction.alerts import risk_alert_router_episode_id

logger = logging.getLogger("merid.alerts.crypto_alert_router")


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class MarketTag(str, Enum):
    TRENDING     = "TRENDING"
    VOLATILE     = "VOLATILE"
    NEW          = "NEW"
    CLOSING_SOON = "CLOSING_SOON"
    HIGH_VOLUME  = "HIGH_VOLUME"
    FIFTY_FIFTY  = "FIFTY_FIFTY"


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class MarketSnapshot:
    # Identity
    symbol: str
    market_id: str
    episode_id: str
    frequency: str
    status: str
    title: str = ""
    # Volume & liquidity
    volume_24h: int = 0
    oi: Optional[int] = None
    # Pricing (0–1, always)
    p_yes: float = 0.5
    # Book state
    spread_cents: float = 0.0
    depth_10c: int = 0
    # Timing
    seconds_to_expiry: float = 0.0
    created_at: float = 0.0
    # Computed flags (set during construction)
    is_new: bool = False
    is_trending: bool = False
    volatility_score: float = 0.0
    closing_soon: bool = False


@dataclass
class MarketSelectionItem:
    market_id: str
    title: str        # pre-HTML-escaped
    frequency: str
    volume_24h: int
    p_yes: float
    tags: set = field(default_factory=set)


# ---------------------------------------------------------------------------
# Pure tag computation
# ---------------------------------------------------------------------------

def compute_tags(snap: MarketSnapshot, cfg: CryptoAlertConfig) -> set:
    """Pure function — no I/O, no side effects."""
    tags = set()
    if snap.is_trending:
        tags.add(MarketTag.TRENDING)
    if snap.volatility_score > cfg.volatility_threshold(snap.symbol, snap.frequency):
        tags.add(MarketTag.VOLATILE)
    if snap.is_new:
        tags.add(MarketTag.NEW)
    if snap.closing_soon:
        tags.add(MarketTag.CLOSING_SOON)
    if snap.volume_24h > cfg.volume_threshold(snap.symbol, snap.frequency):
        tags.add(MarketTag.HIGH_VOLUME)
    if (
        cfg.ENABLE_FIFTY_FIFTY
        and snap.volume_24h >= cfg.min_volume_for_fifty_fifty(snap.symbol, snap.frequency)
        and cfg.fifty_low(snap.symbol) <= snap.p_yes <= cfg.fifty_high(snap.symbol)
    ):
        tags.add(MarketTag.FIFTY_FIFTY)
    return tags


# ---------------------------------------------------------------------------
# Ticker → symbol mapping
# ---------------------------------------------------------------------------

TICKER_PREFIX_TO_SYMBOL: Dict[str, str] = {
    "KXBTC":  "BTC",
    "KXETH":  "ETH",
    "KXSOL":  "SOL",
    "KXXRP":  "XRP",
    "KXDOGE": "DOGE",
}

# Longest prefix first so e.g. KXBTC15M wins over KXBTC.
_TICKER_PREFIX_RANKED: tuple[tuple[str, str], ...] = tuple(
    sorted(TICKER_PREFIX_TO_SYMBOL.items(), key=lambda x: len(x[0]), reverse=True)
)


def _ticker_prefix_to_symbol(ticker: str) -> Optional[str]:
    upper = ticker.upper()
    for prefix, sym in _TICKER_PREFIX_RANKED:
        if upper.startswith(prefix):
            return sym
    return None

# Series suffix → frequency mapping
SERIES_SUFFIX_TO_FREQUENCY: Dict[str, str] = {
    "15T": "15m", "15M": "15m",
    "H":   "hourly",
    "D":   "daily",
    "W":   "weekly",
    "MO":  "monthly",
    "Y":   "annual",
}


def _infer_frequency(series_ticker: str) -> str:
    """Infer frequency from series_ticker suffix (e.g., KXBTCD → daily)."""
    upper = (series_ticker or "").upper()
    for suffix, freq in SERIES_SUFFIX_TO_FREQUENCY.items():
        if upper.endswith(suffix):
            return freq
    return "one_time"


# ---------------------------------------------------------------------------
# Module-level ranking helper (NOT a class method)
# ---------------------------------------------------------------------------

def _rank_snapshots(snaps: List[MarketSnapshot], tag: MarketTag, top_n: int) -> List[MarketSnapshot]:
    """Rank and select top-N snapshots for a given tag."""
    if tag == MarketTag.TRENDING:
        candidates = [s for s in snaps if s.is_trending]
        return sorted(candidates, key=lambda s: s.volume_24h, reverse=True)[:top_n]
    elif tag == MarketTag.VOLATILE:
        return sorted(snaps, key=lambda s: s.volatility_score, reverse=True)[:top_n]
    elif tag == MarketTag.NEW:
        return sorted(snaps, key=lambda s: s.created_at, reverse=True)[:top_n]
    elif tag == MarketTag.CLOSING_SOON:
        candidates = [s for s in snaps if s.closing_soon and s.seconds_to_expiry > 0]
        return sorted(candidates, key=lambda s: s.seconds_to_expiry)[:top_n]
    elif tag == MarketTag.HIGH_VOLUME:
        return sorted(snaps, key=lambda s: s.volume_24h, reverse=True)[:top_n]
    elif tag == MarketTag.FIFTY_FIFTY:
        return sorted(snaps, key=lambda s: (-s.volume_24h, s.seconds_to_expiry))[:top_n]
    return snaps[:top_n]


# ---------------------------------------------------------------------------
# REST metadata container
# ---------------------------------------------------------------------------

class _MarketMeta:
    """Lightweight container for REST-side market fields."""
    __slots__ = ("ticker", "series_ticker", "title", "status", "created_at_ts", "open_interest")

    def __init__(self, ticker, series_ticker, title, status, created_at_ts, open_interest):
        self.ticker = ticker
        self.series_ticker = series_ticker or ""
        self.title = title or ""
        self.status = status or "active"
        self.created_at_ts = created_at_ts or 0.0
        self.open_interest = open_interest


# ---------------------------------------------------------------------------
# CryptoAlertRouter
# ---------------------------------------------------------------------------

class CryptoAlertRouter:
    """
    Periodic router that classifies live Kalshi crypto markets into six tags
    and emits batched Telegram summaries + risk alerts every TICK_INTERVAL_SECONDS.
    """

    def __init__(self, cfg: Optional[CryptoAlertConfig] = None):
        self._cfg = cfg or CryptoAlertConfig()
        self._market_meta: Dict[str, _MarketMeta] = {}
        self._volume_baseline: Dict[str, float] = {}   # symbol → rolling avg volume
        self._cooldowns: Dict[tuple, float] = {}
        self._last_tick_ts: float = 0.0
        self._last_meta_refresh: float = 0.0
        self._error_count: int = 0
        self._tick_count: int = 0
        self._running: bool = False
        self._task: Optional[asyncio.Task] = None
        self._counters: Counter = Counter()
        self._gauges: Dict[str, int] = {}

    # ------------------------------------------------------------------
    # Symbol helpers
    # ------------------------------------------------------------------

    def _ticker_to_symbol(self, ticker: str) -> Optional[str]:
        return _ticker_prefix_to_symbol(ticker)

    # ------------------------------------------------------------------
    # Snapshot construction
    # ------------------------------------------------------------------

    def _build_snapshot(self, state) -> Optional[MarketSnapshot]:
        """Build a MarketSnapshot from a KalshiMarketState + _market_meta entry.
        Returns None if the ticker is unsupported or meta is missing."""
        ticker = state.ticker
        symbol = self._ticker_to_symbol(ticker)
        if symbol is None:
            return None
        meta = self._market_meta.get(ticker)
        if meta is None:
            return None

        now = time.time()
        mid = float(getattr(state, "mid_cents", 0) or 0)
        p_yes = max(0.0, min(1.0, mid / 100.0))

        ste = float(getattr(state, "seconds_to_expiry", 0) or 0)
        closing_soon = 0 < ste < self._cfg.CLOSING_SOON_WINDOW_MINUTES * 60

        created_at = float(meta.created_at_ts or 0)
        is_new = (created_at > 0) and ((now - created_at) < self._cfg.NEW_MARKET_WINDOW_MINUTES * 60)

        baseline = self._volume_baseline.get(symbol, 0.0)
        vol = int(getattr(state, "volume_24h", 0) or 0)
        is_trending = baseline > 0 and vol > baseline * self._cfg.TREND_VOLUME_MULTIPLIER

        spread = float(getattr(state, "spread_cents", 0) or 0)
        depth = int(getattr(state, "depth_10c", 1) or 1)
        raw_vol_score = spread / max(depth, 1)

        return MarketSnapshot(
            symbol=symbol,
            market_id=ticker,
            episode_id=meta.series_ticker,
            frequency=_infer_frequency(meta.series_ticker),
            status=meta.status,
            title=html.escape(meta.title),
            volume_24h=vol,
            oi=meta.open_interest,
            p_yes=p_yes,
            spread_cents=spread,
            depth_10c=depth,
            seconds_to_expiry=ste,
            created_at=created_at,
            is_new=is_new,
            is_trending=is_trending,
            volatility_score=raw_vol_score,
            closing_soon=closing_soon,
        )

    # ------------------------------------------------------------------
    # Cooldown helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _key_risk(symbol: str, episode_id: str, severity: str) -> tuple:
        return ("risk_limit", symbol, episode_id, severity)

    @staticmethod
    def _key_market_selection(symbol: str, tag: MarketTag) -> tuple:
        return ("market_selection", symbol, tag.value, "info")

    def _is_suppressed(self, key: tuple, cooldown_minutes: float) -> bool:
        last = self._cooldowns.get(key, 0.0)
        return (time.monotonic() - last) < cooldown_minutes * 60

    def _record_fired(self, key: tuple) -> None:
        self._cooldowns[key] = time.monotonic()

    # ------------------------------------------------------------------
    # Volatility normalization + volume baseline
    # ------------------------------------------------------------------

    def _normalize_volatility(self, snaps: List[MarketSnapshot], symbol: str) -> None:
        """Min-max normalize volatility_score in-place across snaps for one symbol."""
        sym_snaps = [s for s in snaps if s.symbol == symbol]
        if not sym_snaps:
            return
        scores = [s.volatility_score for s in sym_snaps]
        lo, hi = min(scores), max(scores)
        rng = hi - lo if hi > lo else 1.0
        for s in sym_snaps:
            s.volatility_score = (s.volatility_score - lo) / rng

    def _update_volume_baseline(self, snaps: List[MarketSnapshot]) -> None:
        """Update rolling per-symbol volume baseline (exponential moving average)."""
        symbol_vols: Dict[str, List[int]] = {}
        for s in snaps:
            symbol_vols.setdefault(s.symbol, []).append(s.volume_24h)
        for sym, vols in symbol_vols.items():
            avg = sum(vols) / len(vols)
            prev = self._volume_baseline.get(sym, avg)
            self._volume_baseline[sym] = prev * 0.8 + avg * 0.2

    # ------------------------------------------------------------------
    # Risk alert drain
    # ------------------------------------------------------------------

    async def _drain_risk_alerts(self) -> None:
        """Read AlertManager history, emit risk alerts not seen since last tick."""
        try:
            from merid.prediction.alerts import get_alert_manager
            am = get_alert_manager()
            history = am.get_history()
        except Exception as exc:
            logger.warning("CryptoAlertRouter: could not read alert history: %s", exc)
            return

        # PredictionAlert.timestamp is a timezone-aware datetime, not a float.
        def _alert_ts(a) -> float:
            ts = getattr(a, "timestamp", None)
            if ts is None:
                return 0.0
            return ts.timestamp() if hasattr(ts, "timestamp") else float(ts)

        pending = [a for a in history if _alert_ts(a) > self._last_tick_ts]
        for alert in pending:
            data = getattr(alert, "data", {}) or {}
            market_from_alert = getattr(alert, "market_id", None) or ""
            raw_episode = data.get("episode_id") or data.get("market_id") or market_from_alert
            episode_id = risk_alert_router_episode_id(str(raw_episode) if raw_episode else "")
            symbol = (data.get("symbol") or "").strip()
            if not symbol and market_from_alert:
                symbol = _ticker_prefix_to_symbol(str(market_from_alert)) or ""
            risk_asset = kalshi_ticker_to_asset(str(market_from_alert)) if market_from_alert else None
            severity = getattr(getattr(alert, "severity", None), "value", "info")
            key = self._key_risk(symbol, episode_id, severity)
            # Override cooldown on critical severity escalation
            prev_key = next(
                (k for k in self._cooldowns
                 if k[0] == "risk_limit" and k[1] == symbol and k[2] == episode_id),
                None,
            )
            is_escalation = bool(prev_key and prev_key[3] != severity and severity == "critical")
            if not is_escalation and self._is_suppressed(key, self._cfg.RISK_ALERT_COOLDOWN_MINUTES):
                continue
            self._record_fired(key)
            if self._cfg.ENABLE_LOGGING:
                logger.info(
                    "PM alert fired: [%s] risk_limit - asset=%s symbol=%s market_id=%s episode=%s tags=[%s]",
                    severity,
                    risk_asset or "UNKNOWN",
                    symbol,
                    market_from_alert or "",
                    episode_id,
                    ",".join(data.get("tags", [])),
                )
            # NOTE: Telegram dispatch is already handled by the
            # PredictionAlertManager singleton's _make_telegram_sink.
            # Do NOT re-send here — that caused duplicate TG messages and
            # rate-limit cascades (see alert flood fix 2026-03).
            if self._cfg.ENABLE_METRICS:
                self._counters[("merid_risk_alerts_total", symbol, episode_id, severity, "risk_limit")] += 1

    # ------------------------------------------------------------------
    # Market selection emission
    # ------------------------------------------------------------------

    async def _emit_market_selection(self, symbol: str, tag: MarketTag, top: List[MarketSnapshot]) -> None:
        """Emit one batched market-selection alert for (symbol, tag)."""
        key = self._key_market_selection(symbol, tag)
        if self._is_suppressed(key, self._cfg.MARKET_SELECTION_COOLDOWN_MINUTES):
            return
        self._record_fired(key)
        market_ids = ", ".join(s.market_id for s in top)
        if self._cfg.ENABLE_LOGGING:
            logger.info(
                "PM alert fired: [info] market_selection - %s %s markets: %s",
                symbol, tag.value, market_ids,
            )
        if self._cfg.ENABLE_TELEGRAM_MARKET_ALERTS:
            try:
                from agents.telegram_agent import get_telegram_agent
                items = [
                    MarketSelectionItem(
                        market_id=s.market_id,
                        title=s.title,
                        frequency=s.frequency,
                        volume_24h=s.volume_24h,
                        p_yes=s.p_yes,
                        tags=compute_tags(s, self._cfg),
                    )
                    for s in top
                ]
                tg = get_telegram_agent()
                await tg.send_market_selection_batch(symbol, tag, items)
            except Exception as exc:
                logger.warning("CryptoAlertRouter: telegram market alert failed: %s", exc)
        try:
            from merid.prediction.alerts import get_alert_manager, PredictionAlert, AlertCategory, AlertSeverity
            am = get_alert_manager()
            am.fire(PredictionAlert(
                category=AlertCategory.MARKET_SELECTION,
                severity=AlertSeverity.INFO,
                title=f"market_selection: {symbol} [{tag.value}]",
                message=f"{len(top)} markets selected for {symbol}/{tag.value}: {market_ids}",
                market_id=symbol,
                data={"symbol": symbol, "tag": tag.value, "markets": [s.market_id for s in top]},
            ))
        except Exception as exc:
            logger.debug("CryptoAlertRouter: AlertManager fire failed (ignored): %s", exc)
        if self._cfg.ENABLE_METRICS:
            self._counters[("merid_crypto_selected_markets_total", symbol, tag.value)] += len(top)

    # ------------------------------------------------------------------
    # Main tick loop
    # ------------------------------------------------------------------

    async def _tick(self) -> None:
        """One full evaluation cycle."""
        try:
            # Step 1: risk alerts first
            await self._drain_risk_alerts()

            # Step 2: meta refresh if stale
            now = time.monotonic()
            if now - self._last_meta_refresh > self._cfg.META_REFRESH_INTERVAL_SECONDS:
                await self._refresh_meta()

            # Step 3: build snapshots
            snaps = self._build_all_snapshots()

            # Step 4: update volume baselines
            self._update_volume_baseline(snaps)

            # Step 5: normalize volatility per symbol
            for sym in self._cfg.SUPPORTED_SYMBOLS:
                self._normalize_volatility(snaps, sym)

            # Step 6: tag + rank + emit per (symbol, tag)
            by_symbol: Dict[str, List[MarketSnapshot]] = {}
            for s in snaps:
                by_symbol.setdefault(s.symbol, []).append(s)

            for sym in self._cfg.SUPPORTED_SYMBOLS:
                sym_snaps = by_symbol.get(sym, [])
                for tag in MarketTag:
                    tagged = [s for s in sym_snaps if tag in compute_tags(s, self._cfg)]
                    if self._cfg.ENABLE_METRICS:
                        self._gauges[f"merid_crypto_markets_by_tag.{sym}.{tag.value}"] = len(tagged)
                    if not tagged:
                        continue
                    top = _rank_snapshots(tagged, tag, self._cfg.TOP_N_PER_TAG_PER_SYMBOL)
                    await self._emit_market_selection(sym, tag, top)

            # Step 7: update live-market gauge
            for sym in self._cfg.SUPPORTED_SYMBOLS:
                self._gauges[f"merid_crypto_markets_live.{sym}"] = len(by_symbol.get(sym, []))

        except Exception as exc:
            self._error_count += 1
            logger.error("CryptoAlertRouter tick error: %s", exc, exc_info=True)
        finally:
            self._tick_count += 1
            self._last_tick_ts = time.time()

    def _build_all_snapshots(self) -> List[MarketSnapshot]:
        """Read KalshiMarketStateStore and build snapshots for all crypto markets."""
        snaps = []
        try:
            from merid.event_venues.kalshi.market_state import get_kalshi_market_state_store
            store = get_kalshi_market_state_store()
            raw = store.get_all() if hasattr(store, "get_all") else {}
            states = raw.values() if isinstance(raw, dict) else raw
        except Exception as exc:
            logger.warning("CryptoAlertRouter: could not read market state store: %s", exc)
            return snaps
        for state in states:
            snap = self._build_snapshot(state)
            if snap is not None:
                snaps.append(snap)
        return snaps

    async def _refresh_meta(self) -> None:
        """Fetch crypto market metadata from Kalshi REST and populate _market_meta.

        EventMarket field mapping:
          market_id  → ticker  (EventMarket uses market_id, not ticker)
          question   → title   (EventMarket uses question, not title)
          raw_data   → {"series_ticker": ..., "event_ticker": ...}
          active/resolved → status string
        """
        try:
            from merid.event_venues.kalshi.client import get_kalshi_client
            client = get_kalshi_client()
            markets = await client.list_markets()
            for m in markets:
                # EventMarket stores the Kalshi ticker in .market_id (not .ticker)
                ticker = getattr(m, "market_id", None)
                if not ticker:
                    continue
                # series_ticker lives in EventMarket.raw_data injected by _to_event_market()
                raw = getattr(m, "raw_data", None) or {}
                series_ticker = raw.get("series_ticker", "") or ""
                # EventMarket uses .question for the market title
                title = getattr(m, "question", "") or ""
                # Derive status from bool flags
                resolved = getattr(m, "resolved", False)
                active = getattr(m, "active", True)
                status = "settled" if resolved else ("active" if active else "inactive")
                created_ts = 0.0
                created_at = getattr(m, "created_at", None)
                if created_at is not None:
                    try:
                        created_ts = (
                            created_at.timestamp()
                            if hasattr(created_at, "timestamp")
                            else float(created_at)
                        )
                    except Exception as e:
                        logger.debug(f"Timestamp parsing failed: {e}")
                oi = getattr(m, "open_interest", None)
                self._market_meta[ticker] = _MarketMeta(
                    ticker=ticker,
                    series_ticker=series_ticker,
                    title=title,
                    status=status,
                    created_at_ts=created_ts,
                    open_interest=int(oi) if oi is not None else None,
                )
            self._last_meta_refresh = time.monotonic()
            logger.debug("CryptoAlertRouter: meta refreshed, %d markets", len(self._market_meta))
        except Exception as exc:
            logger.warning("CryptoAlertRouter: meta refresh failed: %s", exc)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def run(self) -> None:
        self._running = True
        try:
            while True:
                await self._tick()
                await asyncio.sleep(self._cfg.TICK_INTERVAL_SECONDS)
        except asyncio.CancelledError:
            return
        finally:
            self._running = False

    async def stop(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)

    def start(self) -> None:
        """Create and store the background task (must be called from an async context).

        Uses asyncio.create_task() rather than the deprecated
        asyncio.get_event_loop().create_task() — the latter is deprecated
        in Python 3.10+ when called from a coroutine/Task and can attach
        the task to the wrong loop.
        """
        self._task = asyncio.create_task(self.run(), name="crypto-alert-router")

    # ------------------------------------------------------------------
    # Metrics / status accessors
    # ------------------------------------------------------------------

    def get_status(self) -> dict:
        return {
            "running": self._running,
            "tick_count": self._tick_count,
            "last_tick_ts": self._last_tick_ts or None,
            "error_count": self._error_count,
            "cooldown_map_size": len(self._cooldowns),
            "meta_markets_loaded": len(self._market_meta),
        }

    def get_metrics(self) -> dict:
        return {
            "counters": {
                ",".join(str(p) for p in k) if isinstance(k, tuple) else str(k): v
                for k, v in self._counters.items()
            },
            "gauges": dict(self._gauges),
        }
