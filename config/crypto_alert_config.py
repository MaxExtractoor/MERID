from dataclasses import dataclass, field
from typing import Dict, Tuple

from config.kalshi_crypto_config import ACTIVE_CRYPTO_ASSETS


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

    SUPPORTED_SYMBOLS: list = field(default_factory=lambda: list(ACTIVE_CRYPTO_ASSETS))

    # --- Global kill-switch (set False to disable router entirely in tests) ---
    ENABLED: bool = True

    # --- Lookup helpers (never raise KeyError) ---

    def volatility_threshold(self, symbol: str, frequency: str) -> float:
        sym_map = self.VOLATILITY_THRESHOLDS.get(symbol)
        if sym_map is None:
            sym_map = self.VOLATILITY_THRESHOLDS.get("_default", {})
        return sym_map.get(frequency, sym_map.get("_default", 0.25))

    def volume_threshold(self, symbol: str, frequency: str) -> int:
        sym_map = self.HIGH_VOLUME_THRESHOLDS.get(symbol)
        if sym_map is None:
            sym_map = self.HIGH_VOLUME_THRESHOLDS.get("_default", {})
        return sym_map.get(frequency, sym_map.get("_default", 1000))

    def min_volume_for_fifty_fifty(self, symbol: str, frequency: str) -> int:
        sym_map = self.MIN_VOLUME_FOR_FIFTY_FIFTY.get(symbol)
        if sym_map is None:
            sym_map = self.MIN_VOLUME_FOR_FIFTY_FIFTY.get("_default", {})
        return sym_map.get(frequency, sym_map.get("_default", 100))

    def fifty_low(self, symbol: str) -> float:
        return self.FIFTY_FIFTY_BAND.get(symbol, (0.45, 0.55))[0]

    def fifty_high(self, symbol: str) -> float:
        return self.FIFTY_FIFTY_BAND.get(symbol, (0.45, 0.55))[1]
