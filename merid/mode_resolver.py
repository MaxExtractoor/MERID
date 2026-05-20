"""Canonical mode and environment resolution service.

This module provides a single source of truth for:
- Application trading mode (live/paper/mock)
- Kalshi environment selection (demo/live/elections)
- Mode-environment consistency enforcement

All mode-related checks should use this service instead of ad-hoc
combinations of env vars and trade_mode.py functions.
"""

from __future__ import annotations

import os
from enum import Enum
from typing import Optional

from trading.trade_mode import TradeMode, get_trade_mode
from utils.logger import get_logger

logger = get_logger("mode_resolver")


class KalshiEnvironment(str, Enum):
    """Kalshi API environment."""
    DEMO = "demo"
    LIVE = "live"
    ELECTIONS = "elections"


class ModeResolver:
    """Single source of truth for mode + environment resolution."""

    @staticmethod
    def is_live_trading() -> bool:
        """Return True if the system is in live trading mode."""
        return get_trade_mode() == TradeMode.LIVE

    @staticmethod
    def is_paper_trading() -> bool:
        """Return True if the system is in paper or mock trading mode."""
        return get_trade_mode() in (TradeMode.PAPER, TradeMode.MOCK)

    @staticmethod
    def get_kalshi_environment() -> KalshiEnvironment:
        """Resolve Kalshi environment from KALSHI_ENV or KALSHI_USE_DEMO.

        Priority:
        1. KALSHI_ENV (demo, live, elections)
        2. KALSHI_USE_DEMO (true → demo, false → live)
        3. Default to LIVE (fail-closed for safety)
        """
        kalshi_env = os.getenv("KALSHI_ENV", "").lower()
        if kalshi_env == "live":
            return KalshiEnvironment.LIVE
        elif kalshi_env == "demo":
            return KalshiEnvironment.DEMO
        elif kalshi_env == "elections":
            return KalshiEnvironment.ELECTIONS
        elif kalshi_env:
            logger.warning(
                "Unknown KALSHI_ENV=%r; falling back to KALSHI_USE_DEMO",
                kalshi_env
            )

        # Fallback to KALSHI_USE_DEMO
        use_demo = os.getenv("KALSHI_USE_DEMO", "false").lower() in ("true", "1", "yes")
        if use_demo:
            return KalshiEnvironment.DEMO
        else:
            return KalshiEnvironment.LIVE

    @staticmethod
    def assert_mode_consistency() -> None:
        """Hard assertion that TradeMode and Kalshi environment agree.

        Raises:
            RuntimeError: If mode and environment are mismatched.

        Rules:
        - Live mode must use live Kalshi environment
        - Paper mode must use demo Kalshi environment
        """
        trade_mode = get_trade_mode()
        kalshi_env = ModeResolver.get_kalshi_environment()

        if trade_mode == TradeMode.LIVE:
            if kalshi_env != KalshiEnvironment.LIVE:
                raise RuntimeError(
                    f"MODE_MISMATCH: TradeMode=LIVE but Kalshi environment={kalshi_env.value}. "
                    f"Set KALSHI_ENV=live for live trading."
                )
        elif trade_mode == TradeMode.PAPER:
            if kalshi_env == KalshiEnvironment.LIVE:
                raise RuntimeError(
                    f"MODE_MISMATCH: TradeMode=PAPER but Kalshi environment={kalshi_env.value} (live host). "
                    f"Set KALSHI_ENV=demo or KALSHI_USE_DEMO=true for paper trading."
                )
        elif trade_mode == TradeMode.MOCK:
            # Mock mode can use either environment, but warn if using live
            if kalshi_env == KalshiEnvironment.LIVE:
                logger.warning(
                    "TradeMode=MOCK but Kalshi environment=LIVE. "
                    "This is safe (no real orders), but consider using demo environment."
                )

        logger.debug(
            "Mode consistency check passed: trade_mode=%s, kalshi_env=%s",
            trade_mode.value,
            kalshi_env.value,
        )

    @staticmethod
    def assert_not_live(context: str = "") -> None:
        """Hard assertion that current mode is not LIVE.

        Args:
            context: Optional context string for error message.

        Raises:
            RuntimeError: If mode is LIVE.
        """
        if ModeResolver.is_live_trading():
            msg = "SAFETY: live execution attempted"
            if context:
                msg += f" in {context}"
            msg += " — blocked by assert_not_live()"
            logger.error(msg)
            raise RuntimeError(msg)
