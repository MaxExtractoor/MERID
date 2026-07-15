"""Entropy-Based Kill Switch for Kalshi 15m Crypto Trading

Implements a physics-inspired kill switch based on Shannon entropy and signal energy.
When market entropy exceeds threshold due to manipulation or extreme volatility,
trading is halted to protect capital.

Based on VGM Risk Engine principles adapted for prediction markets.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional, Dict
from datetime import datetime, timezone

from utils.logger import get_logger

logger = get_logger("merid.event_venues.kalshi.entropy_kill_switch")


@dataclass
class KillSwitchState:
    """Kill switch state for a market or globally."""
    
    is_active: bool = False  # Kill switch is currently active
    triggered_at: Optional[float] = None  # Timestamp when triggered
    trigger_reason: str = ""  # Reason for trigger
    entropy_at_trigger: float = 0.0  # Entropy value at trigger
    signal_energy_at_trigger: float = 0.0  # Signal energy at trigger
    
    # Cooldown state
    cooldown_until: Optional[float] = None  # Cooldown expiry timestamp
    cooldown_duration_sec: int = 300  # Default 5-minute cooldown
    
    # Statistics
    trigger_count: int = 0  # Total trigger count
    last_reset_at: Optional[float] = None  # Last reset timestamp
    
    def to_dict(self) -> dict:
        """Convert to dict for logging/alerting."""
        return {
            "is_active": self.is_active,
            "triggered_at": self.triggered_at,
            "trigger_reason": self.trigger_reason,
            "entropy_at_trigger": self.entropy_at_trigger,
            "signal_energy_at_trigger": self.signal_energy_at_trigger,
            "cooldown_until": self.cooldown_until,
            "cooldown_duration_sec": self.cooldown_duration_sec,
            "trigger_count": self.trigger_count,
            "last_reset_at": self.last_reset_at,
        }


class EntropyKillSwitch:
    """Entropy-based kill switch for trading protection.
    
    Monitors market entropy and signal energy to detect manipulation
    or extreme volatility, triggering a trading halt when thresholds
    are exceeded.
    """
    
    def __init__(
        self,
        entropy_threshold: float = 2.5,  # Entropy threshold for trigger
        signal_energy_threshold: float = 1000.0,  # Signal energy threshold
        cooldown_duration_sec: int = 300,  # 5-minute cooldown after trigger
        auto_reset: bool = True,  # Auto-reset after cooldown
    ):
        self.entropy_threshold = entropy_threshold
        self.signal_energy_threshold = signal_energy_threshold
        self.cooldown_duration_sec = cooldown_duration_sec
        self.auto_reset = auto_reset
        
        # Per-market kill switch states
        self.market_states: Dict[str, KillSwitchState] = {}
        
        # Global kill switch (affects all markets)
        self.global_state = KillSwitchState()
        
        logger.info(
            f"[ENTROPY-KILL-SWITCH] Initialized with thresholds: "
            f"entropy={entropy_threshold}, signal_energy={signal_energy_threshold}, "
            f"cooldown={cooldown_duration_sec}s, auto_reset={auto_reset}"
        )
    
    def check_kill_switch(
        self,
        ticker: str,
        entropy: float,
        signal_energy: float,
        timestamp: Optional[float] = None,
    ) -> KillSwitchState:
        """Check if kill switch should trigger for a market.
        
        Args:
            ticker: Market ticker
            entropy: Current market entropy
            signal_energy: Current signal energy
            timestamp: Current timestamp (defaults to now)
        
        Returns:
            KillSwitchState after check
        """
        if timestamp is None:
            timestamp = datetime.now(timezone.utc).timestamp()
        
        # Get or create market state
        if ticker not in self.market_states:
            self.market_states[ticker] = KillSwitchState()
        
        state = self.market_states[ticker]
        
        # Check if in cooldown
        if state.cooldown_until and timestamp < state.cooldown_until:
            if self.auto_reset:
                # Still in cooldown, keep kill switch active
                state.is_active = True
            return state
        
        # Auto-reset after cooldown
        if state.cooldown_until and timestamp >= state.cooldown_until:
            if self.auto_reset:
                logger.info(
                    f"[ENTROPY-KILL-SWITCH] Auto-resetting kill switch for {ticker} "
                    f"after cooldown expired"
                )
                state.is_active = False
                state.cooldown_until = None
                state.last_reset_at = timestamp
        
        # Check thresholds
        should_trigger = False
        trigger_reason = ""
        
        if entropy >= self.entropy_threshold:
            should_trigger = True
            trigger_reason = f"Entropy threshold exceeded: {entropy:.3f} >= {self.entropy_threshold}"
        elif signal_energy >= self.signal_energy_threshold:
            should_trigger = True
            trigger_reason = f"Signal energy threshold exceeded: {signal_energy:.1f} >= {self.signal_energy_threshold}"
        
        if should_trigger:
            self._trigger_kill_switch(
                ticker,
                state,
                entropy,
                signal_energy,
                trigger_reason,
                timestamp,
            )
        
        return state
    
    def _trigger_kill_switch(
        self,
        ticker: str,
        state: KillSwitchState,
        entropy: float,
        signal_energy: float,
        reason: str,
        timestamp: float,
    ) -> None:
        """Trigger kill switch for a market.
        
        Args:
            ticker: Market ticker
            state: Market kill switch state
            entropy: Entropy at trigger
            signal_energy: Signal energy at trigger
            reason: Trigger reason
            timestamp: Trigger timestamp
        """
        state.is_active = True
        state.triggered_at = timestamp
        state.trigger_reason = reason
        state.entropy_at_trigger = entropy
        state.signal_energy_at_trigger = signal_energy
        state.cooldown_until = timestamp + self.cooldown_duration_sec
        state.trigger_count += 1
        
        logger.warning(
            f"[ENTROPY-KILL-SWITCH] TRIGGERED for {ticker}: {reason} "
            f"(entropy={entropy:.3f}, signal_energy={signal_energy:.1f}, "
            f"cooldown={self.cooldown_duration_sec}s, trigger_count={state.trigger_count})"
        )
    
    def trigger_global_kill_switch(
        self,
        reason: str,
        entropy: float = 0.0,
        signal_energy: float = 0.0,
        timestamp: Optional[float] = None,
    ) -> None:
        """Manually trigger global kill switch (affects all markets).
        
        Args:
            reason: Reason for manual trigger
            entropy: Entropy at trigger (optional)
            signal_energy: Signal energy at trigger (optional)
            timestamp: Trigger timestamp (defaults to now)
        """
        if timestamp is None:
            timestamp = datetime.now(timezone.utc).timestamp()
        
        self.global_state.is_active = True
        self.global_state.triggered_at = timestamp
        self.global_state.trigger_reason = f"MANUAL: {reason}"
        self.global_state.entropy_at_trigger = entropy
        self.global_state.signal_energy_at_trigger = signal_energy
        self.global_state.cooldown_until = timestamp + self.cooldown_duration_sec
        self.global_state.trigger_count += 1
        
        logger.critical(
            f"[ENTROPY-KILL-SWITCH] GLOBAL KILL SWITCH TRIGGERED: {reason} "
            f"(entropy={entropy:.3f}, signal_energy={signal_energy:.1f})"
        )
    
    def reset_kill_switch(
        self,
        ticker: Optional[str] = None,
        timestamp: Optional[float] = None,
    ) -> None:
        """Manually reset kill switch for a market or globally.
        
        Args:
            ticker: Market ticker (None for global reset)
            timestamp: Reset timestamp (defaults to now)
        """
        if timestamp is None:
            timestamp = datetime.now(timezone.utc).timestamp()
        
        if ticker is None:
            # Reset global kill switch
            self.global_state.is_active = False
            self.global_state.cooldown_until = None
            self.global_state.last_reset_at = timestamp
            logger.info("[ENTROPY-KILL-SWITCH] Global kill switch manually reset")
        else:
            # Reset market kill switch
            if ticker in self.market_states:
                self.market_states[ticker].is_active = False
                self.market_states[ticker].cooldown_until = None
                self.market_states[ticker].last_reset_at = timestamp
                logger.info(f"[ENTROPY-KILL-SWITCH] Kill switch manually reset for {ticker}")
    
    def is_trading_allowed(
        self,
        ticker: str,
        timestamp: Optional[float] = None,
    ) -> Tuple[bool, str]:
        """Check if trading is allowed for a market.
        
        Args:
            ticker: Market ticker
            timestamp: Current timestamp (defaults to now)
        
        Returns:
            (is_allowed, reason)
        """
        if timestamp is None:
            timestamp = datetime.now(timezone.utc).timestamp()
        
        # Check global kill switch first
        if self.global_state.is_active:
            if self.global_state.cooldown_until and timestamp >= self.global_state.cooldown_until:
                if self.auto_reset:
                    self.global_state.is_active = False
                    self.global_state.cooldown_until = None
                else:
                    return False, f"Global kill switch active: {self.global_state.trigger_reason}"
            else:
                return False, f"Global kill switch active: {self.global_state.trigger_reason}"
        
        # Check market-specific kill switch
        if ticker in self.market_states:
            state = self.market_states[ticker]
            if state.is_active:
                if state.cooldown_until and timestamp >= state.cooldown_until:
                    if self.auto_reset:
                        state.is_active = False
                        state.cooldown_until = None
                    else:
                        return False, f"Market kill switch active: {state.trigger_reason}"
                else:
                    return False, f"Market kill switch active: {state.trigger_reason}"
        
        return True, "Trading allowed"
    
    def get_state(self, ticker: Optional[str] = None) -> KillSwitchState:
        """Get kill switch state for a market or globally.
        
        Args:
            ticker: Market ticker (None for global state)
        
        Returns:
            KillSwitchState
        """
        if ticker is None:
            return self.global_state
        return self.market_states.get(ticker, KillSwitchState())
    
    def get_all_states(self) -> Dict[str, KillSwitchState]:
        """Get all kill switch states (global + per-market).
        
        Returns:
            Dict mapping ticker to KillSwitchState (includes "global" key)
        """
        states = {"global": self.global_state}
        states.update(self.market_states)
        return states


# Global kill switch instance
_global_kill_switch: Optional[EntropyKillSwitch] = None


def get_entropy_kill_switch(
    entropy_threshold: float = 2.5,
    signal_energy_threshold: float = 1000.0,
    cooldown_duration_sec: int = 300,
    auto_reset: bool = True,
) -> EntropyKillSwitch:
    """Get or create global entropy kill switch instance.
    
    Args:
        entropy_threshold: Entropy threshold for trigger
        signal_energy_threshold: Signal energy threshold
        cooldown_duration_sec: Cooldown duration in seconds
        auto_reset: Auto-reset after cooldown
    
    Returns:
        EntropyKillSwitch instance
    """
    global _global_kill_switch
    
    if _global_kill_switch is None:
        _global_kill_switch = EntropyKillSwitch(
            entropy_threshold=entropy_threshold,
            signal_energy_threshold=signal_energy_threshold,
            cooldown_duration_sec=cooldown_duration_sec,
            auto_reset=auto_reset,
        )
        logger.info("[ENTROPY-KILL-SWITCH] Created global kill switch instance")
    
    return _global_kill_switch


def reset_entropy_kill_switch() -> None:
    """Reset global entropy kill switch (clear all state)."""
    global _global_kill_switch
    _global_kill_switch = None
    logger.info("[ENTROPY-KILL-SWITCH] Reset global kill switch")
