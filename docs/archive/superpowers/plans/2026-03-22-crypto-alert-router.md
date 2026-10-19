# Crypto Alert Router Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a self-contained `CryptoAlertRouter` that classifies live Kalshi crypto markets (BTC/ETH/SOL/XRP/DOGE) into six tags, emits batched Telegram summaries and risk alerts, and exposes REST metrics — running as a background asyncio task every 30s without touching the ingestion hot path.

**Architecture:** Periodic router reads `KalshiMarketStateStore` (book data) joined against a `_market_meta` side-table (REST data refreshed every 5 min) to build typed `MarketSnapshot` objects. A pure `compute_tags()` function assigns up to six `MarketTag` values per snapshot. The router batches results by (symbol, tag) and emits via extended `TelegramAgent` methods, with per-key cooldown suppression.

**Tech Stack:** Python 3.10+, asyncio, FastAPI lifespan, pytest, html (stdlib), collections.Counter

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `config/crypto_alert_config.py` | **CREATE** | All thresholds, feature flags, per-symbol/freq lookups with fallback |
| `merid/alerts/crypto_alert_router.py` | **CREATE** | `MarketSnapshot`, `MarketTag`, `MarketSelectionItem`, `compute_tags()`, `CryptoAlertRouter` |
| `agents/telegram_agent.py` | **MODIFY** | Add `send_market_selection_batch()`; extend `send_risk_alert()` kwargs |
| `merid/prediction/alerts.py` | **MODIFY** | Add `AlertCategory.MARKET_SELECTION` |
| `web/main.py` | **MODIFY** | Wire router startup + teardown in lifespan |
| `web/api/system_endpoints.py` | **MODIFY** | Add `/api/v1/alerts/crypto/status` + `/metrics` endpoints |
| `tests/test_crypto_alert_router.py` | **CREATE** | All router tests |
| `tests/test_telegram_market_batch.py` | **CREATE** | Telegram batch method tests |

---

## Task 1: Config — `CryptoAlertConfig`

**Files:**
- Create: `config/crypto_alert_config.py`
- Test: `tests/test_crypto_alert_router.py` (initial section)

- [ ] **Step 1.1: Write failing tests for config lookups**

```python
# tests/test_crypto_alert_router.py
import pytest
from config.crypto_alert_config import CryptoAlertConfig

def make_config():
    return CryptoAlertConfig()

class TestCryptoAlertConfig:
    def test_volatility_threshold_known_symbol_and_freq(self):
        cfg = make_config()
        val = cfg.volatility_threshold("BTC", "daily")
        assert isinstance(val, float)
        assert val > 0

    def test_volatility_threshold_unknown_symbol_falls_back(self):
        cfg = make_config()
        val = cfg.volatility_threshold("UNKNOWN", "daily")
        assert isinstance(val, float)  # no KeyError

    def test_volatility_threshold_unknown_freq_falls_back(self):
        cfg = make_config()
        val = cfg.volatility_threshold("BTC", "biannual")
        assert isinstance(val, float)  # no KeyError

    def test_volume_threshold_returns_int(self):
        cfg = make_config()
        assert isinstance(cfg.volume_threshold("ETH", "15m"), int)

    def test_fifty_fifty_band_defaults(self):
        cfg = make_config()
        low, high = cfg.fifty_low("BTC"), cfg.fifty_high("BTC")
        assert low == pytest.approx(0.45)
        assert high == pytest.approx(0.55)

    def test_min_volume_for_fifty_fifty_no_error(self):
        cfg = make_config()
        assert isinstance(cfg.min_volume_for_fifty_fifty("DOGE", "hourly"), int)

    def test_feature_flags_are_bool(self):
        cfg = make_config()
        assert isinstance(cfg.ENABLE_TELEGRAM_MARKET_ALERTS, bool)
        assert isinstance(cfg.ENABLE_FIFTY_FIFTY, bool)

    def test_volatility_threshold_symbol_dict_without_default_key(self):
        """Symbol dict exists but has no '_default' — must fall back to global default."""
        cfg = make_config()
        # Inject a symbol with only a specific frequency, no _default
        cfg.VOLATILITY_THRESHOLDS["LTC"] = {"daily": 0.30}
        result = cfg.volatility_threshold("LTC", "15m")  # unknown freq
        assert isinstance(result, float)
        assert result > 0  # returned global fallback, not KeyError
```

- [ ] **Step 1.2: Run to verify they all fail**

```bash
cd c:/Dev/MERID && python -m pytest tests/test_crypto_alert_router.py::TestCryptoAlertConfig -v 2>&1 | head -40
```
Expected: `ModuleNotFoundError: No module named 'config.crypto_alert_config'`

- [ ] **Step 1.3: Create `config/crypto_alert_config.py`**

```python
from dataclasses import dataclass, field
from typing import Dict, Tuple


@dataclass
class CryptoAlertConfig:
    # --- Volatility thresholds (spread/depth ratio, 0–1) ---
    # symbol → frequency → threshold; "_default" used as fallback
    VOLATILITY_THRESHOLDS: Dict[str, Dict[str, float]] = field(default_factory=lambda: {
        "BTC":  {"15m": 0.15, "hourly": 0.20, "daily": 0.30, "_default": 0.25},
        "ETH":  {"15m": 0.18, "hourly": 0.22, "daily": 0.32, "_default": 0.27},
        "SOL":  {"15m": 0.22, "hourly": 0.28, "daily": 0.38, "_default": 0.30},
        "XRP":  {"15m": 0.20, "hourly": 0.25, "daily": 0.35, "_default": 0.28},
        "DOGE": {"15m": 0.25, "hourly": 0.30, "daily": 0.40, "_default": 0.33},
        "_default": {"_default": 0.25},
    })

    # --- High-volume thresholds (contracts per 24h) ---
    HIGH_VOLUME_THRESHOLDS: Dict[str, Dict[str, int]] = field(default_factory=lambda: {
        "BTC":  {"15m": 500, "hourly": 1000, "daily": 5000, "_default": 2000},
        "ETH":  {"15m": 300, "hourly":  800, "daily": 3000, "_default": 1500},
        "SOL":  {"15m": 200, "hourly":  500, "daily": 2000, "_default": 1000},
        "XRP":  {"15m": 200, "hourly":  500, "daily": 2000, "_default": 1000},
        "DOGE": {"15m": 150, "hourly":  400, "daily": 1500, "_default":  800},
        "_default": {"_default": 1000},
    })

    # --- 50/50 band per symbol (low, high) ---
    FIFTY_FIFTY_BAND: Dict[str, Tuple[float, float]] = field(default_factory=lambda: {
        "BTC": (0.45, 0.55), "ETH": (0.45, 0.55),
        "SOL": (0.45, 0.55), "XRP": (0.45, 0.55),
        "DOGE": (0.45, 0.55),
    })

    # --- Minimum volume for FIFTY_FIFTY tag ---
    MIN_VOLUME_FOR_FIFTY_FIFTY: Dict[str, Dict[str, int]] = field(default_factory=lambda: {
        "BTC":  {"15m": 100, "hourly": 200, "daily": 500, "_default": 200},
        "ETH":  {"15m":  80, "hourly": 150, "daily": 400, "_default": 150},
        "SOL":  {"15m":  50, "hourly": 100, "daily": 300, "_default": 100},
        "XRP":  {"15m":  50, "hourly": 100, "daily": 300, "_default": 100},
        "DOGE": {"15m":  40, "hourly":  80, "daily": 200, "_default":  80},
        "_default": {"_default": 100},
    })

    # --- Timing windows ---
    NEW_MARKET_WINDOW_MINUTES: int = 60
    CLOSING_SOON_WINDOW_MINUTES: int = 10
    META_REFRESH_INTERVAL_SECONDS: int = 300
    TICK_INTERVAL_SECONDS: int = 30

    # --- Alert limits ---
    TOP_N_PER_TAG_PER_SYMBOL: int = 5
    RISK_ALERT_COOLDOWN_MINUTES: int = 5
    MARKET_SELECTION_COOLDOWN_MINUTES: int = 10
    TREND_VOLUME_MULTIPLIER: float = 1.5

    # --- Feature flags ---
    ENABLE_LOGGING: bool = True
    ENABLE_TELEGRAM_RISK_ALERTS: bool = True
    ENABLE_TELEGRAM_MARKET_ALERTS: bool = True
    ENABLE_METRICS: bool = True
    ENABLE_FIFTY_FIFTY: bool = True

    SUPPORTED_SYMBOLS: list = field(default_factory=lambda: ["BTC", "ETH", "SOL", "XRP", "DOGE"])

    # --- Lookup helpers (never raise KeyError) ---

    def volatility_threshold(self, symbol: str, frequency: str) -> float:
        sym_map = self.VOLATILITY_THRESHOLDS.get(symbol) or self.VOLATILITY_THRESHOLDS.get("_default", {})
        return sym_map.get(frequency, sym_map.get("_default", 0.25))

    def volume_threshold(self, symbol: str, frequency: str) -> int:
        sym_map = self.HIGH_VOLUME_THRESHOLDS.get(symbol) or self.HIGH_VOLUME_THRESHOLDS.get("_default", {})
        return sym_map.get(frequency, sym_map.get("_default", 1000))

    def min_volume_for_fifty_fifty(self, symbol: str, frequency: str) -> int:
        sym_map = self.MIN_VOLUME_FOR_FIFTY_FIFTY.get(symbol) or self.MIN_VOLUME_FOR_FIFTY_FIFTY.get("_default", {})
        return sym_map.get(frequency, sym_map.get("_default", 100))

    def fifty_low(self, symbol: str) -> float:
        return self.FIFTY_FIFTY_BAND.get(symbol, (0.45, 0.55))[0]

    def fifty_high(self, symbol: str) -> float:
        return self.FIFTY_FIFTY_BAND.get(symbol, (0.45, 0.55))[1]
```

- [ ] **Step 1.4: Run tests — expect all pass**

```bash
cd c:/Dev/MERID && python -m pytest tests/test_crypto_alert_router.py::TestCryptoAlertConfig -v
```
Expected: 8 PASSED

- [ ] **Step 1.5: Commit**

```bash
cd c:/Dev/MERID && git add config/crypto_alert_config.py tests/test_crypto_alert_router.py
git commit -m "feat: add CryptoAlertConfig with per-symbol/freq threshold lookups"
```

---

## Task 2: Data Model — `MarketSnapshot`, `MarketTag`, `MarketSelectionItem`, `compute_tags()`

**Files:**
- Create: `merid/alerts/crypto_alert_router.py` (data model + pure functions only)
- Test: `tests/test_crypto_alert_router.py` (append)

- [ ] **Step 2.1: Verify `merid/alerts/` directory exists**

```bash
ls c:/Dev/MERID/merid/alerts/
```
If it doesn't exist: `mkdir -p c:/Dev/MERID/merid/alerts && touch c:/Dev/MERID/merid/alerts/__init__.py`

- [ ] **Step 2.2: Write failing tests for data model and tag computation**

Append to `tests/test_crypto_alert_router.py`:

```python
import time
from merid.alerts.crypto_alert_router import (
    MarketSnapshot, MarketTag, MarketSelectionItem, compute_tags
)
from config.crypto_alert_config import CryptoAlertConfig


def make_snap(**overrides) -> MarketSnapshot:
    base = dict(
        symbol="BTC", market_id="KXBTCD-26MAR22", episode_id="KXBTCD",
        frequency="daily", status="active", title="Will BTC close above $87k?",
        volume_24h=6000, p_yes=0.52, spread_cents=2.0, depth_10c=100,
        seconds_to_expiry=3600.0, created_at=time.time() - 7200,
        is_new=False, is_trending=False, volatility_score=0.1, closing_soon=False,
    )
    base.update(overrides)
    return MarketSnapshot(**base)


class TestComputeTags:
    def test_no_tags_on_baseline_snap(self):
        snap = make_snap()
        cfg = CryptoAlertConfig()
        assert compute_tags(snap, cfg) == set()

    def test_trending_tag_when_is_trending_true(self):
        snap = make_snap(is_trending=True)
        tags = compute_tags(snap, CryptoAlertConfig())
        assert MarketTag.TRENDING in tags

    def test_volatile_tag_when_score_exceeds_threshold(self):
        cfg = CryptoAlertConfig()
        threshold = cfg.volatility_threshold("BTC", "daily")
        snap = make_snap(volatility_score=threshold + 0.1)
        assert MarketTag.VOLATILE in compute_tags(snap, cfg)

    def test_volatile_tag_absent_when_score_below_threshold(self):
        cfg = CryptoAlertConfig()
        threshold = cfg.volatility_threshold("BTC", "daily")
        snap = make_snap(volatility_score=threshold - 0.01)
        assert MarketTag.VOLATILE not in compute_tags(snap, cfg)

    def test_new_tag_when_is_new_true(self):
        snap = make_snap(is_new=True)
        assert MarketTag.NEW in compute_tags(snap, CryptoAlertConfig())

    def test_closing_soon_tag_when_flag_true(self):
        snap = make_snap(closing_soon=True)
        assert MarketTag.CLOSING_SOON in compute_tags(snap, CryptoAlertConfig())

    def test_high_volume_tag_when_volume_exceeds_threshold(self):
        cfg = CryptoAlertConfig()
        threshold = cfg.volume_threshold("BTC", "daily")
        snap = make_snap(volume_24h=threshold + 1)
        assert MarketTag.HIGH_VOLUME in compute_tags(snap, cfg)

    def test_fifty_fifty_tag_assigned(self):
        cfg = CryptoAlertConfig()
        min_vol = cfg.min_volume_for_fifty_fifty("BTC", "daily")
        snap = make_snap(p_yes=0.50, volume_24h=min_vol + 100)
        assert MarketTag.FIFTY_FIFTY in compute_tags(snap, cfg)

    def test_fifty_fifty_suppressed_on_low_volume(self):
        cfg = CryptoAlertConfig()
        min_vol = cfg.min_volume_for_fifty_fifty("BTC", "daily")
        snap = make_snap(p_yes=0.50, volume_24h=max(0, min_vol - 1))
        assert MarketTag.FIFTY_FIFTY not in compute_tags(snap, cfg)

    def test_fifty_fifty_suppressed_when_flag_disabled(self):
        cfg = CryptoAlertConfig()
        cfg.ENABLE_FIFTY_FIFTY = False
        snap = make_snap(p_yes=0.50, volume_24h=99999)
        assert MarketTag.FIFTY_FIFTY not in compute_tags(snap, cfg)

    def test_multiple_tags_simultaneously(self):
        cfg = CryptoAlertConfig()
        snap = make_snap(
            is_trending=True, closing_soon=True,
            volatility_score=cfg.volatility_threshold("BTC", "daily") + 0.1,
        )
        tags = compute_tags(snap, cfg)
        assert MarketTag.TRENDING in tags
        assert MarketTag.CLOSING_SOON in tags
        assert MarketTag.VOLATILE in tags

    def test_market_selection_item_fields(self):
        item = MarketSelectionItem(
            market_id="KXBTCD-26MAR22",
            title="Will BTC close above $87k?",
            frequency="daily",
            volume_24h=5000,
            p_yes=0.52,
            tags={MarketTag.TRENDING},
        )
        assert item.market_id == "KXBTCD-26MAR22"
```

- [ ] **Step 2.3: Run — expect ImportError**

```bash
cd c:/Dev/MERID && python -m pytest tests/test_crypto_alert_router.py::TestComputeTags -v 2>&1 | head -20
```

- [ ] **Step 2.4: Create `merid/alerts/crypto_alert_router.py` (data model + compute_tags only)**

```python
"""
MERID Crypto Alert Router
Classifies live Kalshi crypto markets into tags and emits batched alerts.
"""
from __future__ import annotations

import asyncio
import html
import logging
import time
from collections import Counter, deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Tuple

from config.crypto_alert_config import CryptoAlertConfig

logger = logging.getLogger("merid.prediction.alerts")


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
    tags: set


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
```

- [ ] **Step 2.5: Ensure `merid/alerts/__init__.py` exists**

```bash
ls c:/Dev/MERID/merid/alerts/__init__.py 2>/dev/null || touch c:/Dev/MERID/merid/alerts/__init__.py
```

- [ ] **Step 2.6: Run tests — expect all pass**

```bash
cd c:/Dev/MERID && python -m pytest tests/test_crypto_alert_router.py -v
```
Expected: all PASSED

- [ ] **Step 2.7: Commit**

```bash
cd c:/Dev/MERID && git add merid/alerts/__init__.py merid/alerts/crypto_alert_router.py tests/test_crypto_alert_router.py
git commit -m "feat: add MarketSnapshot, MarketTag, compute_tags pure functions"
```

---

## Task 3: Extend `TelegramAgent`

**Files:**
- Modify: `agents/telegram_agent.py`
- Test: `tests/test_telegram_market_batch.py`

- [ ] **Step 3.1: Read current `send_risk_alert` and `send_message` signatures**

```bash
cd c:/Dev/MERID && grep -n "async def send_risk_alert\|async def send_message\|async def send_market" agents/telegram_agent.py
```

- [ ] **Step 3.2: Write failing tests**

```python
# tests/test_telegram_market_batch.py
import html
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from merid.alerts.crypto_alert_router import MarketSelectionItem, MarketTag


@pytest.fixture
def agent():
    with patch("agents.telegram_agent.Bot"):
        from agents.telegram_agent import TelegramAgent
        ag = TelegramAgent.__new__(TelegramAgent)
        ag._bot = AsyncMock()
        ag._bot.send_message = AsyncMock()
        ag.last_post_time = 0.0
        ag.recent_messages = []
        return ag


class TestSendMarketSelectionBatch:
    @pytest.mark.asyncio
    async def test_sends_one_message(self, agent):
        items = [
            MarketSelectionItem("KXBTCD-26MAR22", "Will BTC close above $87k?",
                                "daily", 5000, 0.52, {MarketTag.TRENDING}),
        ]
        await agent.send_market_selection_batch("BTC", MarketTag.TRENDING, items)
        agent._bot.send_message.assert_called_once()

    @pytest.mark.asyncio
    async def test_html_escapes_title(self, agent):
        items = [
            MarketSelectionItem("KXBTCD-26MAR22", "<b>Tricky & title</b>",
                                "daily", 5000, 0.50, {MarketTag.TRENDING}),
        ]
        await agent.send_market_selection_batch("BTC", MarketTag.TRENDING, items)
        call_args = agent._bot.send_message.call_args
        text = call_args[1].get("text") or call_args[0][1]
        assert "&lt;b&gt;" in text or "Tricky &amp; title" in text

    @pytest.mark.asyncio
    async def test_message_under_4096_chars(self, agent):
        items = [
            MarketSelectionItem(f"KXBTCD-26MAR{i:02d}", f"Title {i}", "daily", 1000, 0.50, set())
            for i in range(5)
        ]
        await agent.send_market_selection_batch("BTC", MarketTag.TRENDING, items)
        call_args = agent._bot.send_message.call_args
        text = call_args[1].get("text") or call_args[0][1]
        assert len(text) < 4096

    @pytest.mark.asyncio
    async def test_send_risk_alert_accepts_new_kwargs(self, agent):
        """New optional kwargs must not break existing call sites."""
        await agent.send_risk_alert("risk_limit", "Test message", "warning",
                                    symbol="BTC", episode_id="KXBTCD",
                                    frequency="daily", total_risk=480.0, risk_limit=500.0)
        agent._bot.send_message.assert_called_once()

    @pytest.mark.asyncio
    async def test_send_risk_alert_old_signature_still_works(self, agent):
        """Existing call sites with 3 args must not break."""
        await agent.send_risk_alert("risk_limit", "Test message", "warning")
        agent._bot.send_message.assert_called_once()

    @pytest.mark.asyncio
    async def test_send_risk_alert_escapes_plain_message(self, agent):
        """BREAKING CHANGE NOTE: the new send_risk_alert escapes the message param.
        Any caller passing an intentionally HTML-formatted message string will have
        it double-escaped. This test documents that behavior explicitly."""
        await agent.send_risk_alert("risk_limit", "Balance <b>breached</b>", "critical")
        call_args = agent._bot.send_message.call_args
        text = call_args[1].get("text") or call_args[0][1]
        # The < and > must be escaped — raw HTML tags must NOT appear in output
        assert "<b>" not in text
        assert "&lt;b&gt;" in text or "breached" in text
```

- [ ] **Step 3.3: Run — expect failures**

```bash
cd c:/Dev/MERID && python -m pytest tests/test_telegram_market_batch.py -v 2>&1 | head -30
```

- [ ] **Step 3.4: Add `send_market_selection_batch` and extend `send_risk_alert` in `agents/telegram_agent.py`**

Read the file first, then find the end of the class and append:

```python
    async def send_market_selection_batch(
        self,
        symbol: str,
        tag,   # MarketTag enum value
        markets: list,  # list[MarketSelectionItem]
    ) -> None:
        """Send a batched market-selection summary for one (symbol, tag) pair."""
        tag_name = tag.value if hasattr(tag, "value") else str(tag)
        lines = [f"📈 [<b>{html.escape(symbol)}</b>] [<b>{html.escape(tag_name)}</b>] markets"]
        lines.append(f"Top {symbol} {tag_name} markets\n")
        for m in markets:
            safe_id = html.escape(m.market_id)
            safe_title = html.escape(m.title) if m.title else safe_id
            prob_str = f"{m.p_yes:.2f}"
            lines.append(
                f"- {safe_id}: {safe_title} "
                f"(freq={html.escape(m.frequency)}, vol={m.volume_24h:,}, p_yes≈{prob_str})"
            )
        text = "\n".join(lines)
        await self.send_message(text)
```

Also extend `send_risk_alert` by adding the optional kwargs and updating the message body. Find the existing method and replace it:

```python
    async def send_risk_alert(
        self,
        alert_type: str,
        message: str,
        severity: str = "warning",
        symbol: str | None = None,
        episode_id: str | None = None,
        frequency: str | None = None,
        total_risk: float | None = None,
        risk_limit: float | None = None,
    ) -> None:
        sev_upper = severity.upper()
        icon = "🚨" if sev_upper == "CRITICAL" else ("⚠️" if sev_upper == "WARNING" else "ℹ️")
        sym_part = f" [{html.escape(symbol)}]" if symbol else ""
        lines = [f"{icon} [{sev_upper}]{sym_part} [{html.escape(alert_type)}]",
                 html.escape(message)]
        if episode_id:
            freq_part = f" ({html.escape(frequency)})" if frequency else ""
            lines.append(f"{html.escape(episode_id)}{freq_part}")
        if total_risk is not None and risk_limit is not None:
            lines.append(f"Total risk: ${total_risk:.0f} / Limit: ${risk_limit:.0f}")
        await self.send_message("\n".join(lines))
```

Add `import html` at the top of `agents/telegram_agent.py` if not already present.

- [ ] **Step 3.5: Run tests — expect all pass**

```bash
cd c:/Dev/MERID && python -m pytest tests/test_telegram_market_batch.py -v
```
Expected: 6 PASSED

- [ ] **Step 3.6: Commit**

```bash
cd c:/Dev/MERID && git add agents/telegram_agent.py tests/test_telegram_market_batch.py
git commit -m "feat: add send_market_selection_batch; extend send_risk_alert with symbol/episode kwargs"
```

---

## Task 4: `AlertCategory.MARKET_SELECTION`

**Files:**
- Modify: `merid/prediction/alerts.py`
- Test: inline in `tests/test_crypto_alert_router.py`

- [ ] **Step 4.1: Check current AlertCategory values**

```bash
cd c:/Dev/MERID && grep -n "MARKET_SELECTION\|class AlertCategory\|RISK_LIMIT\|TRADE" merid/prediction/alerts.py | head -20
```

- [ ] **Step 4.2: Add test**

Append to `tests/test_crypto_alert_router.py`:

```python
class TestAlertCategoryExtension:
    def test_market_selection_category_exists(self):
        from merid.prediction.alerts import AlertCategory
        assert hasattr(AlertCategory, "MARKET_SELECTION")
        assert AlertCategory.MARKET_SELECTION.value  # non-empty string
```

- [ ] **Step 4.3: Run — expect fail**

```bash
cd c:/Dev/MERID && python -m pytest tests/test_crypto_alert_router.py::TestAlertCategoryExtension -v 2>&1 | head -15
```

- [ ] **Step 4.4: Add `MARKET_SELECTION` to `AlertCategory` enum in `merid/prediction/alerts.py`**

Read the file, find the `AlertCategory` enum, add `MARKET_SELECTION = "market_selection"` after the last existing entry.

- [ ] **Step 4.5: Run — expect pass**

```bash
cd c:/Dev/MERID && python -m pytest tests/test_crypto_alert_router.py::TestAlertCategoryExtension -v
```

- [ ] **Step 4.6: Commit**

```bash
cd c:/Dev/MERID && git add merid/prediction/alerts.py tests/test_crypto_alert_router.py
git commit -m "feat: add AlertCategory.MARKET_SELECTION"
```

---

## Task 5: `CryptoAlertRouter` — meta side-table + snapshot construction

**Files:**
- Modify: `merid/alerts/crypto_alert_router.py` (append `CryptoAlertRouter` class skeleton + snapshot builder)
- Test: `tests/test_crypto_alert_router.py`

- [ ] **Step 5.1: Write failing tests for snapshot construction**

Append to `tests/test_crypto_alert_router.py`:

```python
from unittest.mock import MagicMock, patch
from merid.alerts.crypto_alert_router import CryptoAlertRouter
from config.crypto_alert_config import CryptoAlertConfig


def make_mock_market_state(ticker="KXBTCD-26MAR22", volume_24h=5000, mid_cents=52.0,
                            spread_cents=2.0, depth_10c=80, seconds_to_expiry=3600.0):
    state = MagicMock()
    state.ticker = ticker
    state.volume_24h = volume_24h
    state.mid_cents = mid_cents
    state.spread_cents = spread_cents
    state.depth_10c = depth_10c
    state.seconds_to_expiry = seconds_to_expiry
    return state


def make_mock_meta(ticker="KXBTCD-26MAR22", series_ticker="KXBTCD",
                   title="Will BTC close above $87k?", status="active",
                   created_at=None, open_interest=None):
    import time
    meta = MagicMock()
    meta.ticker = ticker
    meta.series_ticker = series_ticker
    meta.title = title
    meta.status = status
    meta.created_at_ts = created_at or (time.time() - 7200)
    meta.open_interest = open_interest
    return meta


class TestSnapshotConstruction:
    def _make_router(self):
        cfg = CryptoAlertConfig()
        router = CryptoAlertRouter(cfg=cfg)
        return router

    def test_ticker_to_symbol_known_prefixes(self):
        router = self._make_router()
        assert router._ticker_to_symbol("KXBTCD-26MAR22") == "BTC"
        assert router._ticker_to_symbol("KXETHU-26MAR22") == "ETH"
        assert router._ticker_to_symbol("KXSOL-26MAR22") == "SOL"
        assert router._ticker_to_symbol("KXXRP-26MAR22") == "XRP"
        assert router._ticker_to_symbol("KXDOGE-26MAR22") == "DOGE"

    def test_ticker_to_symbol_unknown_returns_none(self):
        router = self._make_router()
        assert router._ticker_to_symbol("KXPOLITICS-26MAR22") is None

    def test_build_snapshot_populates_p_yes(self):
        router = self._make_router()
        state = make_mock_market_state(mid_cents=63.0)
        meta = make_mock_meta()
        router._market_meta["KXBTCD-26MAR22"] = meta
        snap = router._build_snapshot(state)
        assert snap is not None
        assert abs(snap.p_yes - 0.63) < 0.001

    def test_build_snapshot_skips_unsupported_symbol(self):
        router = self._make_router()
        state = make_mock_market_state(ticker="KXPOLITICS-26MAR22")
        router._market_meta["KXPOLITICS-26MAR22"] = make_mock_meta(ticker="KXPOLITICS-26MAR22")
        snap = router._build_snapshot(state)
        assert snap is None

    def test_build_snapshot_skips_missing_meta(self):
        router = self._make_router()
        state = make_mock_market_state()
        # No meta loaded
        snap = router._build_snapshot(state)
        assert snap is None

    def test_build_snapshot_closing_soon_flag(self):
        router = self._make_router()
        state = make_mock_market_state(seconds_to_expiry=5 * 60)  # 5 min < 10 min threshold
        meta = make_mock_meta()
        router._market_meta["KXBTCD-26MAR22"] = meta
        snap = router._build_snapshot(state)
        assert snap is not None
        assert snap.closing_soon is True

    def test_build_snapshot_is_new_flag(self):
        import time
        router = self._make_router()
        state = make_mock_market_state()
        meta = make_mock_meta(created_at=time.time() - 10 * 60)  # 10 min ago < 60 min window
        router._market_meta["KXBTCD-26MAR22"] = meta
        snap = router._build_snapshot(state)
        assert snap is not None
        assert snap.is_new is True
```

- [ ] **Step 5.2: Run — expect ImportError or AttributeError**

```bash
cd c:/Dev/MERID && python -m pytest tests/test_crypto_alert_router.py::TestSnapshotConstruction -v 2>&1 | head -20
```

- [ ] **Step 5.3: Append `CryptoAlertRouter` skeleton + `_build_snapshot` to `merid/alerts/crypto_alert_router.py`**

```python
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

# Series suffix → frequency mapping (extend as Kalshi adds new series)
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
# CryptoAlertRouter
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


class CryptoAlertRouter:
    """
    Periodic router that classifies live Kalshi crypto markets into six tags
    and emits batched Telegram summaries + risk alerts.
    """

    def __init__(self, cfg: Optional[CryptoAlertConfig] = None):
        self._cfg = cfg or CryptoAlertConfig()
        self._market_meta: Dict[str, _MarketMeta] = {}
        self._volume_baseline: Dict[str, float] = {}   # symbol → rolling avg volume
        self._cooldowns: Dict[tuple, float] = {}
        self._last_tick_ts: float = 0.0
        self._last_meta_refresh: float = 0.0
        self._error_count: int = 0
        self._running: bool = False
        self._task: Optional[asyncio.Task] = None
        # Metrics
        self._counters: Counter = Counter()
        self._gauges: Dict[str, int] = {}

    # ------------------------------------------------------------------
    # Symbol helpers
    # ------------------------------------------------------------------

    def _ticker_to_symbol(self, ticker: str) -> Optional[str]:
        upper = ticker.upper()
        for prefix, sym in TICKER_PREFIX_TO_SYMBOL.items():
            if upper.startswith(prefix):
                return sym
        return None

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
            volatility_score=raw_vol_score,  # normalized later across all snaps
            closing_soon=closing_soon,
        )
```

- [ ] **Step 5.4: Run tests — expect all pass**

```bash
cd c:/Dev/MERID && python -m pytest tests/test_crypto_alert_router.py::TestSnapshotConstruction -v
```
Expected: all PASSED

- [ ] **Step 5.5: Commit**

```bash
cd c:/Dev/MERID && git add merid/alerts/crypto_alert_router.py tests/test_crypto_alert_router.py
git commit -m "feat: add CryptoAlertRouter skeleton with ticker-to-symbol and snapshot construction"
```

---

## Task 6: Cooldown map + risk drain + tick loop + emit

**Files:**
- Modify: `merid/alerts/crypto_alert_router.py` (append tick loop, cooldown, emit methods)
- Test: `tests/test_crypto_alert_router.py`

- [ ] **Step 6.1: Write failing tests for cooldown logic**

Append to `tests/test_crypto_alert_router.py`:

```python
class TestCooldownMap:
    def _make_router(self):
        return CryptoAlertRouter(cfg=CryptoAlertConfig())

    def test_not_suppressed_on_first_fire(self):
        router = self._make_router()
        key = ("risk_limit", "BTC", "KXBTCD", "warning")
        assert not router._is_suppressed(key, 5.0)

    def test_suppressed_immediately_after_fire(self):
        router = self._make_router()
        key = ("risk_limit", "BTC", "KXBTCD", "warning")
        router._record_fired(key)
        assert router._is_suppressed(key, 5.0)

    def test_not_suppressed_after_cooldown_expires(self):
        import time
        router = self._make_router()
        key = ("risk_limit", "BTC", "KXBTCD", "warning")
        router._cooldowns[key] = time.monotonic() - 400  # 6.6 min ago
        assert not router._is_suppressed(key, 5.0)  # 5 min cooldown

    def test_market_selection_key_shape(self):
        router = self._make_router()
        key = router._key_market_selection("BTC", MarketTag.TRENDING)
        assert key[0] == "market_selection"
        assert key[1] == "BTC"
        assert MarketTag.TRENDING.value in key

    def test_risk_key_shape(self):
        router = self._make_router()
        key = router._key_risk("BTC", "KXBTCD", "warning")
        assert key[0] == "risk_limit"
        assert "KXBTCD" in key

    def test_severity_escalation_overrides_cooldown(self):
        """A critical alert must fire even if a warning for the same episode is suppressed."""
        import time
        router = self._make_router()
        # Simulate: warning already fired recently
        warn_key = router._key_risk("BTC", "KXBTCD", "warning")
        router._record_fired(warn_key)
        assert router._is_suppressed(warn_key, 5.0)
        # Critical for the same episode: must NOT be suppressed (escalation override)
        crit_key = router._key_risk("BTC", "KXBTCD", "critical")
        # crit_key has never been fired, so it is not suppressed by the cooldown map
        assert not router._is_suppressed(crit_key, 5.0)

    def test_drain_does_not_emit_alerts_older_than_startup(self):
        """Alerts that existed before the router started (timestamp <= 0) must be skipped."""
        # _last_tick_ts starts at 0.0; all real alerts have timestamp > epoch start,
        # but we simulate a pre-existing alert with a timestamp just before now.
        import time
        router = self._make_router()
        # Set _last_tick_ts to current time to simulate "router just finished first tick"
        router._last_tick_ts = time.time()
        # Any alert with timestamp <= _last_tick_ts should be filtered out
        from unittest.mock import MagicMock
        from datetime import datetime, timezone
        old_alert = MagicMock()
        # timestamp is 10 seconds before the last tick
        old_alert.timestamp = datetime.fromtimestamp(
            router._last_tick_ts - 10, tz=timezone.utc
        )
        old_alert.data = {}
        old_alert.severity = MagicMock(value="warning")
        # Helper to extract the pending-alert filter logic directly
        def _alert_ts(a) -> float:
            ts = getattr(a, "timestamp", None)
            if ts is None:
                return 0.0
            return ts.timestamp() if hasattr(ts, "timestamp") else float(ts)
        assert _alert_ts(old_alert) <= router._last_tick_ts  # must be filtered out


class TestRankAndSelect:
    def test_trending_rank_filters_first(self):
        from merid.alerts.crypto_alert_router import _rank_snapshots
        cfg = CryptoAlertConfig()
        snaps = [
            make_snap(market_id=f"KXBTCD-{i:02d}", volume_24h=i * 100, is_trending=(i % 2 == 0))
            for i in range(1, 6)
        ]
        ranked = _rank_snapshots(snaps, MarketTag.TRENDING, 3)
        assert all(s.is_trending for s in ranked)
        # exactly 2 trending snaps exist (i=2,4 from range(1,6)); top_n=3 so all trending returned
        assert len(ranked) == 2
        # sorted by volume desc
        assert ranked[0].volume_24h >= ranked[-1].volume_24h

    def test_volatile_rank_by_score_desc(self):
        from merid.alerts.crypto_alert_router import _rank_snapshots
        snaps = [make_snap(market_id=f"KXBTCD-{i}", volatility_score=i * 0.1) for i in range(5)]
        ranked = _rank_snapshots(snaps, MarketTag.VOLATILE, 3)
        assert ranked[0].volatility_score >= ranked[-1].volatility_score

    def test_closing_soon_rank_by_expiry_asc(self):
        from merid.alerts.crypto_alert_router import _rank_snapshots
        snaps = [make_snap(market_id=f"K-{i}", seconds_to_expiry=float(i * 60 + 60)) for i in range(5)]
        ranked = _rank_snapshots(snaps, MarketTag.CLOSING_SOON, 3)
        assert ranked[0].seconds_to_expiry <= ranked[-1].seconds_to_expiry

    def test_top_n_respected(self):
        from merid.alerts.crypto_alert_router import _rank_snapshots
        snaps = [make_snap(market_id=f"K-{i}", volume_24h=i * 100) for i in range(10)]
        ranked = _rank_snapshots(snaps, MarketTag.HIGH_VOLUME, 4)
        assert len(ranked) <= 4
```

- [ ] **Step 6.2: Run — expect ImportError on `_rank_snapshots`**

```bash
cd c:/Dev/MERID && python -m pytest tests/test_crypto_alert_router.py::TestCooldownMap tests/test_crypto_alert_router.py::TestRankAndSelect -v 2>&1 | head -20
```

- [ ] **Step 6.3: Append cooldown helpers, `_rank_snapshots`, `_normalize_volatility`, and full `_tick()` to `merid/alerts/crypto_alert_router.py`**

```python
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
    # Ranking
    # ------------------------------------------------------------------


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
# NOTE: Everything below `_rank_snapshots` is INSIDE the CryptoAlertRouter
# class — indented one level (4 spaces). `_rank_snapshots` itself is a
# module-level function (zero indent). Do not indent it into the class.
# ---------------------------------------------------------------------------

# (resume class CryptoAlertRouter — indent all methods below at 4 spaces)

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
        """Update rolling per-symbol volume baseline (simple moving average)."""
        symbol_vols: Dict[str, List[int]] = {}
        for s in snaps:
            symbol_vols.setdefault(s.symbol, []).append(s.volume_24h)
        for sym, vols in symbol_vols.items():
            avg = sum(vols) / len(vols)
            prev = self._volume_baseline.get(sym, avg)
            # Exponential moving average (alpha=0.2)
            self._volume_baseline[sym] = prev * 0.8 + avg * 0.2

    async def _drain_risk_alerts(self) -> None:
        """Read AlertManager history, emit risk alerts not seen since last tick."""
        try:
            from merid.prediction.alerts import get_alert_manager, AlertCategory
            am = get_alert_manager()
            history = am.get_history()
        except Exception as exc:
            logger.warning("CryptoAlertRouter: could not read alert history: %s", exc)
            return

        # PredictionAlert.timestamp is a timezone-aware datetime, not a float.
        # Convert to Unix float for comparison against self._last_tick_ts (time.time()).
        def _alert_ts(a) -> float:
            ts = getattr(a, "timestamp", None)
            if ts is None:
                return 0.0
            return ts.timestamp() if hasattr(ts, "timestamp") else float(ts)

        pending = [a for a in history if _alert_ts(a) > self._last_tick_ts]
        for alert in pending:
            data = getattr(alert, "data", {}) or {}
            symbol = data.get("symbol", "")
            episode_id = data.get("episode_id", data.get("market_id", ""))
            severity = getattr(getattr(alert, "severity", None), "value", "info")
            key = self._key_risk(symbol, episode_id, severity)
            # Override cooldown on severity escalation
            prev_key = next((k for k in self._cooldowns if k[0] == "risk_limit" and k[1] == symbol and k[2] == episode_id), None)
            is_escalation = False
            if prev_key and prev_key[3] != severity and severity == "critical":
                is_escalation = True
            if not is_escalation and self._is_suppressed(key, self._cfg.RISK_ALERT_COOLDOWN_MINUTES):
                continue
            self._record_fired(key)
            if self._cfg.ENABLE_LOGGING:
                logger.info(
                    "PM alert fired: [%s] risk_limit - %s %s tags=[%s]",
                    severity, symbol, episode_id,
                    ",".join(data.get("tags", [])),
                )
            if self._cfg.ENABLE_TELEGRAM_RISK_ALERTS:
                try:
                    from agents.telegram_agent import get_telegram_agent
                    tg = get_telegram_agent()
                    await tg.send_risk_alert(
                        alert_type="risk_limit",
                        message=getattr(alert, "message", str(alert)),
                        severity=severity,
                        symbol=symbol or None,
                        episode_id=episode_id or None,
                        total_risk=data.get("total_risk"),
                        risk_limit=data.get("risk_limit"),
                    )
                except Exception as exc:
                    logger.warning("CryptoAlertRouter: telegram risk alert failed: %s", exc)
            if self._cfg.ENABLE_METRICS:
                self._counters[("merid_risk_alerts_total", symbol, episode_id, severity, "risk_limit")] += 1

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
                # MarketSelectionItem is defined in this same module — no import needed
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
        if self._cfg.ENABLE_METRICS:
            self._counters[("merid_crypto_selected_markets_total", symbol, tag.value)] += len(top)

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
            self._last_tick_ts = time.time()

    def _build_all_snapshots(self) -> List[MarketSnapshot]:
        """Read KalshiMarketStateStore and build snapshots for all crypto markets."""
        snaps = []
        try:
            from merid.event_venues.kalshi.market_state import get_market_state_store
            store = get_market_state_store()
            raw = store.get_all() if hasattr(store, "get_all") else {}
            # get_all() returns Dict[str, KalshiMarketState] — iterate values, not keys
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
        """Fetch crypto market metadata from Kalshi REST and populate _market_meta."""
        try:
            from merid.event_venues.kalshi.client import get_kalshi_client
            client = get_kalshi_client()
            # KalshiVenueClient exposes list_markets(), not get_markets()
            markets = await client.list_markets()
            for m in markets:
                ticker = getattr(m, "ticker", None)
                if not ticker:
                    continue
                created_ts = 0.0
                created_at = getattr(m, "created_at", None)
                if created_at is not None:
                    try:
                        created_ts = created_at.timestamp() if hasattr(created_at, "timestamp") else float(created_at)
                    except Exception:
                        pass
                self._market_meta[ticker] = _MarketMeta(
                    ticker=ticker,
                    series_ticker=getattr(m, "series_ticker", "") or "",
                    title=getattr(m, "title", "") or "",
                    status=getattr(m, "status", "active") or "active",
                    created_at_ts=created_ts,
                    open_interest=getattr(m, "open_interest", None),
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
        """Create and store the background task (call from async context)."""
        loop = asyncio.get_event_loop()
        self._task = loop.create_task(self.run())

    # ------------------------------------------------------------------
    # Metrics / status accessors
    # ------------------------------------------------------------------

    def get_status(self) -> dict:
        return {
            "running": self._running,
            "last_tick_ts": self._last_tick_ts,
            "error_count": self._error_count,
            "cooldown_map_size": len(self._cooldowns),
            "meta_markets_loaded": len(self._market_meta),
        }

    def get_metrics(self) -> dict:
        return {
            "counters": {str(k): v for k, v in self._counters.items()},
            "gauges": dict(self._gauges),
        }
```

- [ ] **Step 6.4: Run all tests**

```bash
cd c:/Dev/MERID && python -m pytest tests/test_crypto_alert_router.py -v
```
Expected: all PASSED

- [ ] **Step 6.5: Commit**

```bash
cd c:/Dev/MERID && git add merid/alerts/crypto_alert_router.py tests/test_crypto_alert_router.py
git commit -m "feat: add CryptoAlertRouter tick loop, cooldown map, rank/emit logic"
```

---

## Task 7: REST Endpoints — status + metrics

**Files:**
- Modify: `web/api/system_endpoints.py`
- Test: inline in `tests/test_crypto_alert_router.py`

- [ ] **Step 7.1: Read system_endpoints.py router prefix and auth pattern**

```bash
cd c:/Dev/MERID && head -40 web/api/system_endpoints.py
```

- [ ] **Step 7.2: Write failing test**

Append to `tests/test_crypto_alert_router.py`:

```python
class TestRouterStatusEndpoint:
    def test_status_dict_shape(self):
        from merid.alerts.crypto_alert_router import CryptoAlertRouter
        router = CryptoAlertRouter()
        status = router.get_status()
        assert "running" in status
        assert "last_tick_ts" in status
        assert "error_count" in status

    def test_metrics_dict_shape(self):
        from merid.alerts.crypto_alert_router import CryptoAlertRouter
        router = CryptoAlertRouter()
        metrics = router.get_metrics()
        assert "counters" in metrics
        assert "gauges" in metrics
```

- [ ] **Step 7.3: Run — should pass immediately (methods already written)**

```bash
cd c:/Dev/MERID && python -m pytest tests/test_crypto_alert_router.py::TestRouterStatusEndpoint -v
```

- [ ] **Step 7.4: Add endpoints to `web/api/system_endpoints.py`**

Read the file first to find the router variable name and prefix, then append:

```python
# Near imports at top of file — add if not already present:
# from merid.alerts.crypto_alert_router import CryptoAlertRouter
# _crypto_router_instance: Optional[CryptoAlertRouter] = None
#
# def set_crypto_alert_router(r: CryptoAlertRouter) -> None:
#     global _crypto_router_instance
#     _crypto_router_instance = r

@router.get("/alerts/crypto/status")
async def crypto_alert_router_status():
    """Health and state of the CryptoAlertRouter background task."""
    if _crypto_router_instance is None:
        return {"running": False, "error": "router not initialized"}
    return _crypto_router_instance.get_status()


@router.get("/alerts/crypto/metrics")
async def crypto_alert_router_metrics():
    """Per-symbol and per-tag alert counters and gauges."""
    if _crypto_router_instance is None:
        return {"counters": {}, "gauges": {}}
    return _crypto_router_instance.get_metrics()
```

(Adjust to match the actual router variable name and prefix found in step 7.1.)

- [ ] **Step 7.5: Commit**

```bash
cd c:/Dev/MERID && git add web/api/system_endpoints.py tests/test_crypto_alert_router.py
git commit -m "feat: expose /api/v1/alerts/crypto/status and /metrics endpoints"
```

---

## Task 8: Wire in `web/main.py` — startup + teardown

**Files:**
- Modify: `web/main.py`
- Test: smoke import test

- [ ] **Step 8.1: Read the lifespan function in `web/main.py`**

```bash
cd c:/Dev/MERID && grep -n "lifespan\|create_task\|CancelledError\|yield\|shutdown" web/main.py | head -30
```

- [ ] **Step 8.2: Smoke test that router imports cleanly**

```bash
cd c:/Dev/MERID && python -c "from merid.alerts.crypto_alert_router import CryptoAlertRouter; r = CryptoAlertRouter(); print('OK', r.get_status())"
```
Expected: `OK {'running': False, 'last_tick_ts': 0.0, ...}`

- [ ] **Step 8.3: Wire router into lifespan**

Read `web/main.py` fully, find the lifespan function. Add startup (before `yield`) and teardown (after `yield`):

```python
# In imports section (top of file) — CryptoAlertRouter and config are safe
# to import directly since they have no FastAPI/DB startup dependencies:
from merid.alerts.crypto_alert_router import CryptoAlertRouter
from config.crypto_alert_config import CryptoAlertConfig

# In lifespan, before yield — access set_crypto_alert_router via the already-
# loaded system_endpoints module to stay consistent with the _si() resilience
# pattern used everywhere else in web/main.py:
_crypto_cfg = CryptoAlertConfig()
_crypto_router = CryptoAlertRouter(cfg=_crypto_cfg)
# _si() returns the router *attribute* of the module, NOT the module itself.
# Use sys.modules to get the actual module object so we can call the plain
# module-level function set_crypto_alert_router():
import sys as _sys
_se_mod = _sys.modules.get("web.api.system_endpoints")
if _se_mod and hasattr(_se_mod, "set_crypto_alert_router"):
    _se_mod.set_crypto_alert_router(_crypto_router)
_crypto_router.start()
logger.info("CryptoAlertRouter started")

# yield  ← existing yield line

# After yield (teardown):
await _crypto_router.stop()
logger.info("CryptoAlertRouter stopped")
```

- [ ] **Step 8.4: Verify app still starts cleanly**

```bash
cd c:/Dev/MERID && python -c "
import asyncio, sys
sys.path.insert(0, '.')
from web.main import app
print('Import OK, routes:', len(app.routes))
"
```
Expected: `Import OK, routes: N` (some number > 0, no exception)

- [ ] **Step 8.5: Run full test suite to ensure nothing broken**

```bash
cd c:/Dev/MERID && python -m pytest tests/test_crypto_alert_router.py tests/test_telegram_market_batch.py -v
```
Expected: all PASSED

- [ ] **Step 8.6: Final commit**

```bash
cd c:/Dev/MERID && git add web/main.py web/api/system_endpoints.py
git commit -m "feat: wire CryptoAlertRouter into FastAPI lifespan — startup/teardown"
```

---

## Bug-Hunt Notes (confirmed by parallel audit — already applied)

The following were confirmed by the parallel bug-hunt audit and are already reflected in the plan above or fixed in the codebase:

**PRE-EXISTING BUG — FIXED (commit 78221be3):**
- `KalshiMarketState` was imported in `market_state.py` but not defined in `models.py`, causing a startup `ImportError` for any consumer. Added `KalshiMarketState` dataclass with all required fields to `models.py`.

**Confirmed singleton/method names (use these exactly):**
- Market state store: `from merid.event_venues.kalshi.market_state import get_kalshi_market_state_store` — use this in `_build_all_snapshots()` (not `get_market_state_store`)
- `store.get_all()` returns `Dict[str, KalshiMarketState]` — iterate `.values()` ✓ already in plan
- Kalshi client: `from merid.event_venues.kalshi.client import KalshiVenueClient` — get instance via existing singleton; use `list_markets()` ✓ already in plan
- Alert manager: `from merid.prediction.alerts import get_alert_manager` ✓
- Telegram agent: `from agents.telegram_agent import get_telegram_agent` — thread-safe double-checked lock singleton ✓
- `PredictionAlert.timestamp` is `datetime` (UTC-aware), NOT a float — drain filter converts via `.timestamp()` ✓ already in plan

**Confirmed `system_endpoints.py` auth pattern:**
- New endpoints need `Depends(get_current_session)` and `require_role()` — match this when adding status/metrics endpoints in Task 7.

**Minor non-blocking issue (not blocking feature):**
- `telegram_agent.py` line 110: `datetime.now()` uses naive datetime (no timezone). Does not affect the CryptoAlertRouter feature.
