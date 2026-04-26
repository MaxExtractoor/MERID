import os
from dataclasses import dataclass, field
from typing import Dict, Tuple

from config.kalshi_crypto_config import ACTIVE_CRYPTO_ASSETS


def _env_float(env_key: str, default: float) -> float:
    return float(os.getenv(env_key, str(default)))


def _env_int(env_key: str, default: int) -> int:
    return int(os.getenv(env_key, str(default)))


@dataclass
class CryptoAlertConfig:
    # --- Volatility thresholds (ENV-DRIVEN: spread/depth ratio, 0–1) ---
    # symbol → frequency → threshold; "_default" used as fallback
    VOLATILITY_THRESHOLDS: Dict[str, Dict[str, float]] = field(default_factory=lambda: {
        "BTC":  {"15m": _env_float("MERID_VOL_THRESH_BTC_15M", 0.15), "hourly": _env_float("MERID_VOL_THRESH_BTC_H", 0.20), "daily": _env_float("MERID_VOL_THRESH_BTC_D", 0.30), "_default": _env_float("MERID_VOL_THRESH_BTC", 0.25)},
        "ETH":  {"15m": _env_float("MERID_VOL_THRESH_ETH_15M", 0.18), "hourly": _env_float("MERID_VOL_THRESH_ETH_H", 0.22), "daily": _env_float("MERID_VOL_THRESH_ETH_D", 0.32), "_default": _env_float("MERID_VOL_THRESH_ETH", 0.27)},
        "SOL":  {"15m": _env_float("MERID_VOL_THRESH_SOL_15M", 0.22), "hourly": _env_float("MERID_VOL_THRESH_SOL_H", 0.28), "daily": _env_float("MERID_VOL_THRESH_SOL_D", 0.38), "_default": _env_float("MERID_VOL_THRESH_SOL", 0.30)},
        "XRP":  {"15m": _env_float("MERID_VOL_THRESH_XRP_15M", 0.20), "hourly": _env_float("MERID_VOL_THRESH_XRP_H", 0.25), "daily": _env_float("MERID_VOL_THRESH_XRP_D", 0.35), "_default": _env_float("MERID_VOL_THRESH_XRP", 0.28)},
        "DOGE": {"15m": _env_float("MERID_VOL_THRESH_DOGE_15M", 0.25), "hourly": _env_float("MERID_VOL_THRESH_DOGE_H", 0.30), "daily": _env_float("MERID_VOL_THRESH_DOGE_D", 0.40), "_default": _env_float("MERID_VOL_THRESH_DOGE", 0.33)},
        "_default": {"_default": _env_float("MERID_VOL_THRESH_DEFAULT", 0.25)},
    })

    # --- High-volume thresholds (ENV-DRIVEN: contracts per 24h) ---
    HIGH_VOLUME_THRESHOLDS: Dict[str, Dict[str, int]] = field(default_factory=lambda: {
        "BTC":  {"15m": _env_int("MERID_VOL_BTC_15M", 500), "hourly": _env_int("MERID_VOL_BTC_H", 1000), "daily": _env_int("MERID_VOL_BTC_D", 5000), "_default": _env_int("MERID_VOL_BTC", 2000)},
        "ETH":  {"15m": _env_int("MERID_VOL_ETH_15M", 300), "hourly": _env_int("MERID_VOL_ETH_H", 800), "daily": _env_int("MERID_VOL_ETH_D", 3000), "_default": _env_int("MERID_VOL_ETH", 1500)},
        "SOL":  {"15m": _env_int("MERID_VOL_SOL_15M", 200), "hourly": _env_int("MERID_VOL_SOL_H", 500), "daily": _env_int("MERID_VOL_SOL_D", 2000), "_default": _env_int("MERID_VOL_SOL", 1000)},
        "XRP":  {"15m": _env_int("MERID_VOL_XRP_15M", 200), "hourly": _env_int("MERID_VOL_XRP_H", 500), "daily": _env_int("MERID_VOL_XRP_D", 2000), "_default": _env_int("MERID_VOL_XRP", 1000)},
        "DOGE": {"15m": _env_int("MERID_VOL_DOGE_15M", 150), "hourly": _env_int("MERID_VOL_DOGE_H", 400), "daily": _env_int("MERID_VOL_DOGE_D", 1500), "_default": _env_int("MERID_VOL_DOGE", 800)},
        "_default": {"_default": _env_int("MERID_VOL_DEFAULT", 1000)},
    })

    # --- 50/50 band per symbol (ENV-DRIVEN: low, high) ---
    FIFTY_FIFTY_BAND: Dict[str, Tuple[float, float]] = field(default_factory=lambda: {
        "BTC": (_env_float("MERID_50_50_BTC_LOW", 0.45), _env_float("MERID_50_50_BTC_HIGH", 0.55)),
        "ETH": (_env_float("MERID_50_50_ETH_LOW", 0.45), _env_float("MERID_50_50_ETH_HIGH", 0.55)),
        "SOL": (_env_float("MERID_50_50_SOL_LOW", 0.45), _env_float("MERID_50_50_SOL_HIGH", 0.55)),
        "XRP": (_env_float("MERID_50_50_XRP_LOW", 0.45), _env_float("MERID_50_50_XRP_HIGH", 0.55)),
        "DOGE": (_env_float("MERID_50_50_DOGE_LOW", 0.45), _env_float("MERID_50_50_DOGE_HIGH", 0.55)),
    })

    # --- Minimum volume for FIFTY_FIFTY tag (ENV-DRIVEN) ---
    MIN_VOLUME_FOR_FIFTY_FIFTY: Dict[str, Dict[str, int]] = field(default_factory=lambda: {
        "BTC":  {"15m": _env_int("MERID_MINVOL_BTC_15M", 100), "hourly": _env_int("MERID_MINVOL_BTC_H", 200), "daily": _env_int("MERID_MINVOL_BTC_D", 500), "_default": _env_int("MERID_MINVOL_BTC", 200)},
        "ETH":  {"15m": _env_int("MERID_MINVOL_ETH_15M", 80), "hourly": _env_int("MERID_MINVOL_ETH_H", 150), "daily": _env_int("MERID_MINVOL_ETH_D", 400), "_default": _env_int("MERID_MINVOL_ETH", 150)},
        "SOL":  {"15m": _env_int("MERID_MINVOL_SOL_15M", 50), "hourly": _env_int("MERID_MINVOL_SOL_H", 100), "daily": _env_int("MERID_MINVOL_SOL_D", 300), "_default": _env_int("MERID_MINVOL_SOL", 100)},
        "XRP":  {"15m": _env_int("MERID_MINVOL_XRP_15M", 50), "hourly": _env_int("MERID_MINVOL_XRP_H", 100), "daily": _env_int("MERID_MINVOL_XRP_D", 300), "_default": _env_int("MERID_MINVOL_XRP", 100)},
        "DOGE": {"15m": _env_int("MERID_MINVOL_DOGE_15M", 40), "hourly": _env_int("MERID_MINVOL_DOGE_H", 80), "daily": _env_int("MERID_MINVOL_DOGE_D", 200), "_default": _env_int("MERID_MINVOL_DOGE", 80)},
        "_default": {"_default": _env_int("MERID_MINVOL_DEFAULT", 100)},
    })

    # --- Timing windows (ENV-DRIVEN) ---
    NEW_MARKET_WINDOW_MINUTES: int = field(default_factory=lambda: _env_int("MERID_NEW_MARKET_WINDOW_MIN", 60))
    CLOSING_SOON_WINDOW_MINUTES: int = field(default_factory=lambda: _env_int("MERID_CLOSING_SOON_WINDOW_MIN", 10))
    META_REFRESH_INTERVAL_SECONDS: int = field(default_factory=lambda: _env_int("MERID_META_REFRESH_SEC", 300))
    TICK_INTERVAL_SECONDS: int = field(default_factory=lambda: _env_int("MERID_TICK_INTERVAL_SEC", 30))

    # --- Alert limits (ENV-DRIVEN) ---
    TOP_N_PER_TAG_PER_SYMBOL: int = field(default_factory=lambda: _env_int("MERID_TOP_N_PER_TAG", 5))
    RISK_ALERT_COOLDOWN_MINUTES: int = field(default_factory=lambda: _env_int("MERID_RISK_COOLDOWN_MIN", 5))
    MARKET_SELECTION_COOLDOWN_MINUTES: int = field(default_factory=lambda: _env_int("MERID_MARKET_COOLDOWN_MIN", 10))
    TREND_VOLUME_MULTIPLIER: float = field(default_factory=lambda: _env_float("MERID_TREND_VOL_MULT", 1.5))

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
