"""Kalshi YES/NO Duality Validator - Hard Data Integrity Guarantees.

This module enforces the fundamental invariant that YES and NO prices
must sum to approximately 100c (accounting for small rounding errors).

If duality is violated, the market data is considered corrupted and
will be rejected to prevent trading on invalid data.

PROFITABILITY ENHANCEMENT: YES/NO Sum Arbitrage
When YES+NO < 100c, this is a risk-free arbitrage opportunity. The system
can buy both YES and NO to lock in a guaranteed profit. This feature is
disabled by default and must be explicitly enabled via configuration.

HARDENING-FIX: Now uses central severity enum for alarm classification.
"""

import logging
from typing import Tuple, Optional, Dict, Any, Callable, List
from datetime import datetime, timezone
from dataclasses import dataclass
import os
import time

# Import central severity classification
from merid.event_venues.kalshi.severity import Severity, Alarm, create_p1_alarm

logger = logging.getLogger(__name__)

# Duality invariant constants
MAX_DUALITY_ERROR_CENTS = 2  # Allow 2c rounding error
DUALITY_VIOLATION_THRESHOLD = 5  # Track violations per ticker
CRITICAL_VIOLATION_THRESHOLD = 10  # Pause trading if violations exceed this

# HARDENING-FIX: Quarantine mode constants
QUARANTINE_DURATION_SECONDS = 300  # 5 minutes quarantine per violation
QUARANTINE_COOLDOWN_SECONDS = 600  # 10 minutes cooldown before re-quarantine
SEQUENCE_ALIGNMENT_WINDOW = 3  # Number of messages to check for sequence alignment

# Arbitrage constants
ARBITRAGE_ENABLED = os.getenv("MERID_YES_NO_ARBITRAGE_ENABLED", "false").lower() == "true"
ARBITRAGE_THRESHOLD_CENTS = 3  # Minimum arbitrage edge to execute (3c = 3%)
ARBITRAGE_MAX_SIZE_CONTRACTS = 10  # Max contracts per arbitrage trade

@dataclass
class ArbitrageOpportunity:
    """YES/NO sum arbitrage opportunity."""
    edge_cents: int  # Profit in cents (100 - (yes_ask + no_bid))
    yes_ask: int
    no_bid: int
    market_id: Optional[str] = None
    recommended_size: int = 1  # Recommended contract size

@dataclass
class DualityCheckResult:
    """Result of duality validation."""
    is_valid: bool
    error_cents: int
    violation_type: Optional[str]  # 'bid_sum', 'ask_sum', 'crossed_market'
    raw_yes_bid: Optional[int] = None
    raw_no_bid: Optional[int] = None
    raw_yes_ask: Optional[int] = None
    raw_no_ask: Optional[int] = None
    ticker: Optional[str] = None
    arbitrage_opportunity: Optional[ArbitrageOpportunity] = None  # Arbitrage opportunity if detected

class DualityValidator:
    """Enforces YES/NO duality invariants for Kalshi market data.
    
    HARDENING-FIX: Includes quarantine mode for persistent violations with
    sequence alignment to ensure data integrity before re-enabling trading.
    """
    
    def __init__(self):
        self._violation_counts: Dict[str, int] = {}
        self._critical_violations: Dict[str, int] = {}
        self._debug_log_enabled = os.getenv("MERID_DUALITY_DEBUG", "false").lower() == "true"
        
        # HARDENING-FIX: Quarantine state tracking
        self._quarantine_until: Dict[str, float] = {}  # ticker -> expiration timestamp
        self._last_quarantine_time: Dict[str, float] = {}  # ticker -> last quarantine start time
        self._sequence_history: Dict[str, List[int]] = {}  # ticker -> recent sequence numbers
        
        # HARDENING-FIX: Alarm tracking with severity
        self._alarms: List[Alarm] = []
        
        # Arbitrage callback for execution
        self._arbitrage_callback: Optional[Callable[[ArbitrageOpportunity], None]] = None
        
    def check_yes_no_duality(self, 
                           yes_bid: Optional[int], 
                           no_bid: Optional[int],
                           yes_ask: Optional[int] = None, 
                           no_ask: Optional[int] = None,
                           ticker: Optional[str] = None) -> DualityCheckResult:
        """
        Check YES/NO duality invariant.
        
        Args:
            yes_bid: YES bid price in cents
            no_bid: NO bid price in cents  
            yes_ask: YES ask price in cents (optional)
            no_ask: NO ask price in cents (optional)
            ticker: Market ticker for tracking
            
        Returns:
            DualityCheckResult with validation details
        """
        # Check correct duality invariants for binary markets:
        # YES_bid + NO_ask = 100c (YES bid + NO ask = 100 cents)
        # NO_bid + YES_ask = 100c (NO bid + YES ask = 100 cents)
        
        # Check YES_bid + NO_ask = 100c
        if yes_bid is not None and no_ask is not None:
            bid_ask_sum = yes_bid + no_ask
            bid_ask_error = abs(bid_ask_sum - 100)
            
            if bid_ask_error > MAX_DUALITY_ERROR_CENTS:
                result = DualityCheckResult(
                    is_valid=False,
                    error_cents=bid_ask_error,
                    violation_type='bid_ask_sum',
                    raw_yes_bid=yes_bid,
                    raw_no_ask=no_ask,
                    ticker=ticker
                )
                self._record_violation(ticker, result)
                return result
        
        # Check NO_bid + YES_ask = 100c
        if no_bid is not None and yes_ask is not None:
            ask_bid_sum = no_bid + yes_ask
            ask_bid_error = abs(ask_bid_sum - 100)
            
            if ask_bid_error > MAX_DUALITY_ERROR_CENTS:
                result = DualityCheckResult(
                    is_valid=False,
                    error_cents=ask_bid_error,
                    violation_type='ask_bid_sum',
                    raw_no_bid=no_bid,
                    raw_yes_ask=yes_ask,
                    ticker=ticker
                )
                self._record_violation(ticker, result)
                return result
        
        # PROFITABILITY ENHANCEMENT: Check for arbitrage opportunity
        # If YES ask + NO bid < 100c, we can buy both for a guaranteed profit
        # This check must happen BEFORE crossed market check because arbitrage
        # opportunities often appear as crossed markets (which is exactly why
        # they're profitable)
        if ARBITRAGE_ENABLED and yes_ask is not None and no_bid is not None:
            ask_bid_sum = yes_ask + no_bid
            if ask_bid_sum < 100 - ARBITRAGE_THRESHOLD_CENTS:
                edge_cents = 100 - ask_bid_sum
                arbitrage_opp = ArbitrageOpportunity(
                    edge_cents=edge_cents,
                    yes_ask=yes_ask,
                    no_bid=no_bid,
                    recommended_size=min(ARBITRAGE_MAX_SIZE_CONTRACTS, max(1, edge_cents // 2))
                )
                logger.info(
                    "[ARBITRAGE-OPPORTUNITY] ticker=%s edge=%dc yes_ask=%dc no_bid=%dc recommended_size=%d",
                    ticker, edge_cents, yes_ask, no_bid, arbitrage_opp.recommended_size
                )
                # Trigger arbitrage execution callback if registered
                if self._arbitrage_callback:
                    try:
                        self._arbitrage_callback(arbitrage_opp)
                    except Exception as e:
                        logger.error(f"[ARBITRAGE-EXECUTION] Failed to execute arbitrage: {e}")
                # Return valid result with arbitrage opportunity attached
                # Arbitrage takes precedence over crossed market violation
                return DualityCheckResult(
                    is_valid=True,
                    error_cents=0,
                    violation_type=None,
                    raw_yes_bid=yes_bid,
                    raw_no_bid=no_bid,
                    raw_yes_ask=yes_ask,
                    raw_no_ask=no_ask,
                    ticker=ticker,
                    arbitrage_opportunity=arbitrage_opp
                )
        
        # Check for crossed markets (YES bid >= NO ask or vice versa)
        if yes_bid is not None and no_ask is not None:
            if yes_bid >= no_ask:
                result = DualityCheckResult(
                    is_valid=False,
                    error_cents=yes_bid - no_ask,
                    violation_type='crossed_market',
                    raw_yes_bid=yes_bid,
                    raw_no_ask=no_ask,
                    ticker=ticker
                )
                self._record_violation(ticker, result)
                return result
        
        # All checks passed
        return DualityCheckResult(is_valid=True, error_cents=0, violation_type=None, ticker=ticker)
    
    def _record_violation(self, ticker: str, result: DualityCheckResult) -> None:
        """Record a duality violation and check thresholds."""
        if not ticker:
            ticker = "unknown"
            
        # Increment violation count
        self._violation_counts[ticker] = self._violation_counts.get(ticker, 0) + 1
        
        # Log structured violation
        logger.error(
            "[DUALITY-VIOLATION] ticker=%s violation_type=%s error_cents=%d count=%d | "
            "YES_bid=%s NO_bid=%s YES_ask=%s NO_ask=%s | "
            "This may indicate Kalshi API drift or parsing error. Rejecting book update.",
            ticker, result.violation_type, result.error_cents, self._violation_counts[ticker],
            result.raw_yes_bid, result.raw_no_bid, result.raw_yes_ask, result.raw_no_ask
        )
        
        # Debug logging with full payload
        if self._debug_log_enabled:
            self._debug_log_violation(ticker, result)
        
        # Check critical threshold
        if self._violation_counts[ticker] >= CRITICAL_VIOLATION_THRESHOLD:
            self._critical_violations[ticker] = self._critical_violations.get(ticker, 0) + 1
            logger.critical(
                "[DUALITY-CRITICAL] ticker=%s violations=%d exceeded threshold=%d | "
                "Trading should be paused for this ticker due to persistent data corruption.",
                ticker, self._violation_counts[ticker], CRITICAL_VIOLATION_THRESHOLD
            )
            
            # HARDENING-FIX: Create P1 alarm for invariant violation
            alarm = create_p1_alarm(
                component="duality_validator",
                message=f"Persistent duality violations: {self._violation_counts[ticker]} violations",
                ticker=ticker,
                violation_count=self._violation_counts[ticker],
                threshold=CRITICAL_VIOLATION_THRESHOLD
            )
            self._alarms.append(alarm)
            
            # HARDENING-FIX: Enter quarantine mode
            self._enter_quarantine(ticker)
    
    def _debug_log_violation(self, ticker: str, result: DualityCheckResult) -> None:
        """Log detailed violation information to debug file."""
        try:
            # Use timestamped log file to prevent stale data accumulation
            timestamp_str = datetime.now(timezone.utc).strftime("%Y%m%d")
            debug_file = f"c:\\Dev\\MERID\\duality_violations_debug_{timestamp_str}.log"
            with open(debug_file, "a") as f:
                timestamp = datetime.now(timezone.utc).isoformat()
                f.write(
                    f"{timestamp} | TICKER={ticker} | TYPE={result.violation_type} | "
                    f"ERROR={result.error_cents} | COUNT={self._violation_counts[ticker]} | "
                    f"YES_BID={result.raw_yes_bid} | NO_BID={result.raw_no_bid} | "
                    f"YES_ASK={result.raw_yes_ask} | NO_ASK={result.raw_no_ask}\n"
                )
                f.flush()
        except Exception as e:
            logger.warning(f"[DUALITY-DEBUG] Failed to write debug log: {e}")
    
    def should_pause_trading(self, ticker: str) -> bool:
        """Check if trading should be paused for a ticker due to violations.
        
        HARDENING-FIX: Also checks quarantine status.
        """
        if not ticker:
            return False
        
        # Check if currently in quarantine
        if self._is_quarantined(ticker):
            return True
        
        return self._critical_violations.get(ticker, 0) > 0
    
    def _enter_quarantine(self, ticker: str) -> None:
        """Enter quarantine mode for a ticker.
        
        HARDENING-FIX: Implements quarantine with cooldown period to prevent
        re-quarantine loops on transient issues.
        """
        now = time.monotonic()
        
        # Check cooldown period before re-quarantining
        if ticker in self._last_quarantine_time:
            time_since_last = now - self._last_quarantine_time[ticker]
            if time_since_last < QUARANTINE_COOLDOWN_SECONDS:
                logger.warning(
                    "[DUALITY-QUARANTINE] ticker=%s skipping quarantine - cooldown active (%.0fs remaining)",
                    ticker, QUARANTINE_COOLDOWN_SECONDS - time_since_last
                )
                return
        
        # Set quarantine expiration
        self._quarantine_until[ticker] = now + QUARANTINE_DURATION_SECONDS
        self._last_quarantine_time[ticker] = now
        
        logger.warning(
            "[DUALITY-QUARANTINE] ticker=%s entered quarantine for %d seconds (cooldown=%ds)",
            ticker, QUARANTINE_DURATION_SECONDS, QUARANTINE_COOLDOWN_SECONDS
        )
    
    def _is_quarantined(self, ticker: str) -> bool:
        """Check if a ticker is currently quarantined.
        
        HARDENING-FIX: Auto-expires quarantine after duration.
        """
        if not ticker:
            return False
        
        now = time.monotonic()
        if ticker in self._quarantine_until:
            if now < self._quarantine_until[ticker]:
                return True
            else:
                # Quarantine expired, clean up
                del self._quarantine_until[ticker]
                logger.info("[DUALITY-QUARANTINE] ticker=%s quarantine expired", ticker)
                return False
        return False
    
    def record_sequence(self, ticker: str, sequence: int) -> None:
        """Record a sequence number for a ticker.
        
        HARDENING-FIX: Tracks sequence alignment to ensure data integrity
        before re-enabling trading after quarantine.
        """
        if not ticker:
            return
        
        if ticker not in self._sequence_history:
            self._sequence_history[ticker] = []
        
        self._sequence_history[ticker].append(sequence)
        
        # Keep only recent sequences
        if len(self._sequence_history[ticker]) > SEQUENCE_ALIGNMENT_WINDOW:
            self._sequence_history[ticker] = self._sequence_history[ticker][-SEQUENCE_ALIGNMENT_WINDOW:]
    
    def check_sequence_alignment(self, ticker: str) -> bool:
        """Check if sequences are aligned (monotonically increasing).
        
        HARDENING-FIX: Used to verify data integrity before lifting quarantine.
        """
        if not ticker or ticker not in self._sequence_history:
            return True  # No history, assume aligned
        
        sequences = self._sequence_history[ticker]
        if len(sequences) < 2:
            return True  # Not enough data
        
        # Check if sequences are monotonically increasing
        for i in range(1, len(sequences)):
            if sequences[i] <= sequences[i-1]:
                logger.warning(
                    "[DUALITY-SEQUENCE] ticker=%s sequence misalignment detected: %d -> %d",
                    ticker, sequences[i-1], sequences[i]
                )
                return False
        
        return True
    
    def get_violation_stats(self) -> Dict[str, Dict[str, int]]:
        """Get violation statistics for monitoring."""
        stats = {}
        for ticker in self._violation_counts:
            stats[ticker] = {
                'violations': self._violation_counts[ticker],
                'critical_violations': self._critical_violations.get(ticker, 0),
                'should_pause': self.should_pause_trading(ticker)
            }
        return stats
    
    def get_alarms(self) -> List[Alarm]:
        """Get all alarms raised by the validator.
        
        HARDENING-FIX: Returns list of Alarm objects with severity classification.
        """
        return self._alarms.copy()
    
    def clear_alarms(self) -> None:
        """Clear all alarms (useful after fixes or maintenance)."""
        self._alarms.clear()
        logger.info("[DUALITY-ALARMS] Cleared all alarms")
    
    def reset_violation_counts(self, ticker: Optional[str] = None) -> None:
        """Reset violation counts (useful after fixes or maintenance)."""
        if ticker:
            self._violation_counts.pop(ticker, None)
            self._critical_violations.pop(ticker, None)
            logger.info(f"[DUALITY-RESET] Reset violations for ticker={ticker}")
        else:
            self._violation_counts.clear()
            self._critical_violations.clear()
            logger.info("[DUALITY-RESET] Reset all violation counts")
    
    def set_arbitrage_callback(self, callback: Callable[[ArbitrageOpportunity], None]) -> None:
        """Register a callback to execute arbitrage opportunities.
        
        Args:
            callback: Function that takes an ArbitrageOpportunity and executes the trade
        """
        self._arbitrage_callback = callback
        logger.info("[ARBITRAGE-SET] Arbitrage execution callback registered")

# Global validator instance
_duality_validator = DualityValidator()

def get_duality_validator() -> DualityValidator:
    """Get the global duality validator instance."""
    return _duality_validator

def check_yes_no_duality(yes_bid: Optional[int], 
                         no_bid: Optional[int],
                         yes_ask: Optional[int] = None, 
                         no_ask: Optional[int] = None,
                         ticker: Optional[str] = None) -> DualityCheckResult:
    """Convenience function for duality checking."""
    return _duality_validator.check_yes_no_duality(yes_bid, no_bid, yes_ask, no_ask, ticker)
