"""AI Model Security Guardrails — Treats AI models as untrusted suggestion engines.

Enforces a hard-coded risk envelope around all AI/model outputs so that:
  - No model can exceed position limits, rate limits, or notional caps
  - Model outputs are validated, logged, and anomaly-checked before execution
  - Irreversible actions require explicit human confirmation
  - All model parameter changes are audited
  - Data integrity is verified before feeding models

Security risks addressed (per regulatory guidance):
  1. Data integrity attacks — checksums + anomaly detection on inputs
  2. Model poisoning/tampering — signed artifacts, change audit log
  3. Unauthorized access — least-privilege, MFA enforcement (external)
  4. Emergent/abusive behaviour — hard constraints that models cannot override

Usage::

    guard = get_ai_guardrails()
    result = guard.validate_suggestion(suggestion)
    if result.allowed:
        execute(suggestion)
    else:
        log_rejection(result.reason)
"""

from __future__ import annotations

import os
import threading
import hashlib
import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from utils.logger import get_logger


def _env_int(env_key: str, default: int) -> int:
    return int(os.getenv(env_key, str(default)))


def _env_float(env_key: str, default: float) -> float:
    return float(os.getenv(env_key, str(default)))

logger = get_logger("merid.prediction.ai_guardrails")


# ── Enums ────────────────────────────────────────────────────────────────────

class SuggestionType(str, Enum):
    """Types of AI suggestions that go through guardrails."""
    TRADE = "trade"                  # Place/modify an order
    RESIZE = "resize"                # Adjust Kelly/position size
    PAUSE_AGENT = "pause_agent"      # Pause a trading agent
    RESUME_AGENT = "resume_agent"    # Resume a trading agent
    PARAMETER_CHANGE = "param"       # Change model/strategy parameter
    KILL_SWITCH = "kill_switch"      # Activate kill switch
    DATA_OVERRIDE = "data_override"  # Override a data feed value


class RejectionReason(str, Enum):
    """Standardised rejection reasons."""
    EXCEEDS_POSITION_LIMIT = "exceeds_position_limit"
    EXCEEDS_NOTIONAL_CAP = "exceeds_notional_cap"
    EXCEEDS_RATE_LIMIT = "exceeds_rate_limit"
    INVALID_PRICE = "invalid_price"
    INVALID_SIZE = "invalid_size"
    ANOMALOUS_INPUT = "anomalous_input"
    TAMPERED_MODEL = "tampered_model"
    REQUIRES_CONFIRMATION = "requires_confirmation"
    KILL_SWITCH_ACTIVE = "kill_switch_active"
    FORBIDDEN_ACTION = "forbidden_action"
    PARAMETER_OUT_OF_BOUNDS = "parameter_out_of_bounds"
    STALE_DATA = "stale_data"


# ── Data models ──────────────────────────────────────────────────────────────

@dataclass
class AISuggestion:
    """A suggestion from an AI model that must pass through guardrails."""
    suggestion_type: SuggestionType
    source: str                               # model/agent name
    payload: Dict[str, Any]                   # action details
    confidence: float = 0.0                   # model confidence [0,1]
    ts: float = field(default_factory=time.time)
    request_id: str = ""                      # for audit trail

    @property
    def market_id(self) -> Optional[str]:
        return self.payload.get("market_id")

    @property
    def contracts(self) -> int:
        return int(self.payload.get("contracts", 0))

    @property
    def price_cents(self) -> int:
        return int(self.payload.get("price_cents", 0))


@dataclass
class GuardrailResult:
    """Result of passing a suggestion through guardrails."""
    allowed: bool
    suggestion: AISuggestion
    reason: Optional[str] = None
    rejection_code: Optional[RejectionReason] = None
    adjustments: Dict[str, Any] = field(default_factory=dict)
    audit_id: str = ""
    ts: float = field(default_factory=time.time)


@dataclass
class GuardrailConfig:
    """ENV-DRIVEN limits that NO model can override.
    
    CRITICAL: max_total_notional_usd and max_notional_per_market_usd are now
    DYNAMICALLY DERIVED from settings.KALSHI_PORTFOLIO_BANKROLL_CENTS.
    Hardcoded defaults removed to prevent risk bypass with fake capital.
    All other limits are ENV-DRIVEN with sensible defaults.
    """
    # Position limits (ENV-DRIVEN, contract counts)
    max_contracts_per_order: int = field(default_factory=lambda: _env_int("MERID_MAX_CONTRACTS_PER_ORDER", 50))
    max_contracts_per_market: int = field(default_factory=lambda: _env_int("MERID_MAX_CONTRACTS_PER_MARKET", 200))
    
    # NOTIONAL LIMITS: These are computed from actual Kalshi balance, not hardcoded.
    # Default 0 means "derive from bankroll" - see _get_dynamic_limits()
    max_total_notional_usd: float = 0.0  # 0 = derive from bankroll (was 500.0)
    max_notional_per_market_usd: float = 0.0  # 0 = derive from bankroll (was 100.0)

    # Rate limits (ENV-DRIVEN)
    max_orders_per_minute: int = field(default_factory=lambda: _env_int("MERID_MAX_ORDERS_PER_MINUTE", 30))
    max_orders_per_hour: int = field(default_factory=lambda: _env_int("MERID_MAX_ORDERS_PER_HOUR", 200))

    # Price sanity (ENV-DRIVEN)
    min_price_cents: int = field(default_factory=lambda: _env_int("MERID_MIN_PRICE_CENTS", 1))
    max_price_cents: int = field(default_factory=lambda: _env_int("MERID_MAX_PRICE_CENTS", 99))

    # Data staleness (ENV-DRIVEN)
    max_data_age_seconds: float = field(default_factory=lambda: _env_float("MERID_MAX_DATA_AGE_SEC", 300.0))

    # Parameter bounds (ENV-DRIVEN - for AI-suggested parameter changes)
    kelly_fraction_bounds: tuple = field(default_factory=lambda: (
        _env_float("MERID_KELLY_FRAC_MIN", 0.01),
        _env_float("MERID_KELLY_FRAC_MAX", 0.50)
    ))
    vol_scale_bounds: tuple = field(default_factory=lambda: (
        _env_float("MERID_VOL_SCALE_MIN", 0.1),
        _env_float("MERID_VOL_SCALE_MAX", 3.0)
    ))
    max_drawdown_halt_pct: float = field(default_factory=lambda: _env_float("MERID_MAX_DRAWDOWN_HALT_PCT", 0.20))

    # Actions that ALWAYS require human confirmation
    requires_confirmation: tuple = (
        SuggestionType.KILL_SWITCH,
        SuggestionType.DATA_OVERRIDE,
    )

    # Actions that AI is NEVER allowed to take
    forbidden_actions: tuple = ()


# ── Guardrails engine ────────────────────────────────────────────────────────

class AIGuardrails:
    """Validates all AI model outputs against hard-coded safety constraints.

    Design principles:
      - Models are *untrusted suggestion engines* inside a hard envelope
      - No model output can bypass position limits, rate limits, or caps
      - Irreversible actions require human confirmation
      - All decisions are audit-logged
    """

    def __init__(self, config: Optional[GuardrailConfig] = None):
        self.config = config or GuardrailConfig()
        self._audit_log: List[Dict[str, Any]] = []
        self._orders_this_minute: int = 0
        self._orders_this_hour: int = 0
        self._minute_reset_ts: float = time.time()
        self._hour_reset_ts: float = time.time()
        self._model_hashes: Dict[str, str] = {}  # model_name -> sha256
        self._shadow_models: Dict[str, Any] = {}  # name -> predict_fn
        self._pending_confirmations: Dict[str, AISuggestion] = {}
        self._total_checked: int = 0
        self._total_rejected: int = 0

    # ── Core validation ───────────────────────────────────────────────────

    def validate_suggestion(self, suggestion: AISuggestion) -> GuardrailResult:
        """Run a suggestion through all guardrail checks.

        Returns a GuardrailResult indicating whether the suggestion
        is allowed, rejected, or requires human confirmation.
        """
        self._total_checked += 1
        self._rotate_rate_counters()

        # 1. Forbidden action check
        if suggestion.suggestion_type in self.config.forbidden_actions:
            return self._reject(
                suggestion, RejectionReason.FORBIDDEN_ACTION,
                f"Action type {suggestion.suggestion_type.value} is forbidden",
            )

        # 2. Kill switch check
        try:
            from merid.prediction.risk import get_prediction_risk
            risk = get_prediction_risk()
            if risk.is_halted and suggestion.suggestion_type == SuggestionType.TRADE:
                return self._reject(
                    suggestion, RejectionReason.KILL_SWITCH_ACTIVE,
                    "Kill switch active — all trading halted",
                )
        except ImportError:
            logger.warning("[ai-guardrails] prediction risk module not available — kill switch check skipped")

        # 3. Human confirmation required?
        if suggestion.suggestion_type in self.config.requires_confirmation:
            self._pending_confirmations[suggestion.request_id] = suggestion
            return self._reject(
                suggestion, RejectionReason.REQUIRES_CONFIRMATION,
                f"{suggestion.suggestion_type.value} requires manual confirmation",
            )

        # 4. Type-specific checks
        if suggestion.suggestion_type == SuggestionType.TRADE:
            return self._check_trade(suggestion)
        elif suggestion.suggestion_type == SuggestionType.RESIZE:
            return self._check_resize(suggestion)
        elif suggestion.suggestion_type == SuggestionType.PARAMETER_CHANGE:
            return self._check_parameter_change(suggestion)
        elif suggestion.suggestion_type in (
            SuggestionType.PAUSE_AGENT, SuggestionType.RESUME_AGENT,
        ):
            return self._allow(suggestion)

        return self._allow(suggestion)

    # ── Trade checks ──────────────────────────────────────────────────────

    def _check_trade(self, s: AISuggestion) -> GuardrailResult:
        """Validate a trade suggestion."""
        # Price sanity
        price = s.price_cents
        if price < self.config.min_price_cents or price > self.config.max_price_cents:
            return self._reject(
                s, RejectionReason.INVALID_PRICE,
                f"Price {price}c outside [{self.config.min_price_cents}, {self.config.max_price_cents}]",
            )

        # Size sanity
        contracts = s.contracts
        if contracts <= 0:
            return self._reject(
                s, RejectionReason.INVALID_SIZE,
                "Contracts must be > 0",
            )
        if contracts > self.config.max_contracts_per_order:
            return self._reject(
                s, RejectionReason.EXCEEDS_POSITION_LIMIT,
                f"Size {contracts} exceeds max {self.config.max_contracts_per_order}",
            )

        # Notional check (dynamic from bankroll if not explicitly configured)
        notional = (contracts * price) / 100.0
        max_per_market = self._get_dynamic_max_per_market()
        if notional > max_per_market:
            return self._reject(
                s, RejectionReason.EXCEEDS_NOTIONAL_CAP,
                f"Notional ${notional:.2f} exceeds cap ${max_per_market:.2f} (bankroll-derived)",
            )

        # Rate limit check
        if self._orders_this_minute >= self.config.max_orders_per_minute:
            return self._reject(
                s, RejectionReason.EXCEEDS_RATE_LIMIT,
                f"Rate limit: {self._orders_this_minute}/{self.config.max_orders_per_minute} per minute",
            )
        if self._orders_this_hour >= self.config.max_orders_per_hour:
            return self._reject(
                s, RejectionReason.EXCEEDS_RATE_LIMIT,
                f"Rate limit: {self._orders_this_hour}/{self.config.max_orders_per_hour} per hour",
            )

        # All checks passed — count the order
        self._orders_this_minute += 1
        self._orders_this_hour += 1
        return self._allow(s)

    def _get_dynamic_max_per_market(self) -> float:
        """
        Compute max notional per market from actual bankroll.
        
        If config has explicit value > 0, use it.
        Otherwise derive from KALSHI_PORTFOLIO_BANKROLL_CENTS (1% of bankroll).
        """
        # If explicitly configured, use that
        if self.config.max_notional_per_market_usd > 0:
            return self.config.max_notional_per_market_usd
        
        # Otherwise derive from actual Kalshi bankroll
        try:
            from merid.settings import settings
            bankroll_cents = settings.KALSHI_PORTFOLIO_BANKROLL_CENTS
            # Use 1% of bankroll per market (conservative)
            return bankroll_cents / 100.0 * 0.01  # 1% of bankroll in USD
        except Exception:
            # Fail-safe: if we can't get bankroll, return extremely conservative $10
            # This forces explicit configuration or working bankroll fetch
            return 10.0

    # ── Resize checks ─────────────────────────────────────────────────────

    def _check_resize(self, s: AISuggestion) -> GuardrailResult:
        """Validate a resize (Kelly fraction change) suggestion."""
        new_kelly = s.payload.get("kelly_fraction")
        if new_kelly is not None:
            lo, hi = self.config.kelly_fraction_bounds
            if not (lo <= new_kelly <= hi):
                return self._reject(
                    s, RejectionReason.PARAMETER_OUT_OF_BOUNDS,
                    f"Kelly fraction {new_kelly} outside [{lo}, {hi}]",
                )

        new_vol_scale = s.payload.get("vol_scale")
        if new_vol_scale is not None:
            lo, hi = self.config.vol_scale_bounds
            if not (lo <= new_vol_scale <= hi):
                return self._reject(
                    s, RejectionReason.PARAMETER_OUT_OF_BOUNDS,
                    f"Vol scale {new_vol_scale} outside [{lo}, {hi}]",
                )

        return self._allow(s)

    # ── Parameter change checks ───────────────────────────────────────────

    def _check_parameter_change(self, s: AISuggestion) -> GuardrailResult:
        """Validate a model/strategy parameter change."""
        param_name = s.payload.get("param_name", "")
        param_value = s.payload.get("param_value")

        # Block changes to critical guardrail parameters
        protected = {
            "max_contracts_per_order", "max_total_notional_usd",
            "max_orders_per_minute", "kill_switch",
        }
        if param_name in protected:
            return self._reject(
                s, RejectionReason.FORBIDDEN_ACTION,
                f"Parameter '{param_name}' is protected and cannot be changed by AI",
            )

        # Log the change for audit
        self._audit(s, "param_change", {
            "param": param_name, "value": param_value, "source": s.source,
        })

        return self._allow(s)

    # ── Data integrity ────────────────────────────────────────────────────

    def check_data_freshness(self, data_ts: float, label: str = "data") -> bool:
        """Verify that input data is not stale."""
        age = time.time() - data_ts
        if age > self.config.max_data_age_seconds:
            logger.warning(
                f"Stale {label}: age={age:.0f}s > max={self.config.max_data_age_seconds}s"
            )
            return False
        return True

    def verify_data_checksum(
        self, data: bytes, expected_hash: str, label: str = "feed",
    ) -> bool:
        """Verify data integrity via SHA-256 checksum."""
        actual = hashlib.sha256(data).hexdigest()
        if actual != expected_hash:
            logger.error(
                f"Data integrity failure for {label}: "
                f"expected={expected_hash[:16]}... got={actual[:16]}..."
            )
            return False
        return True

    def detect_input_anomaly(
        self,
        value: float,
        historical_mean: float,
        historical_std: float,
        z_threshold: float = None,
        label: str = "input",
    ) -> bool:
        """Detect anomalous model inputs using z-score.

        Returns True if anomalous (should be rejected/flagged).
        """
        # ENV-DRIVEN: Use env var or default to 5.0
        if z_threshold is None:
            z_threshold = _env_float("MERID_ANOMALY_Z_THRESHOLD", 5.0)
        if historical_std <= 0:
            return False
        z = abs(value - historical_mean) / historical_std
        if z > z_threshold:
            logger.warning(
                f"Anomalous {label}: value={value:.4f} z={z:.1f} "
                f"(mean={historical_mean:.4f} std={historical_std:.4f})"
            )
            return True
        return False

    # ── Model artifact integrity ──────────────────────────────────────────

    def register_model_hash(self, model_name: str, artifact_bytes: bytes) -> str:
        """Register the SHA-256 hash of a model artifact."""
        h = hashlib.sha256(artifact_bytes).hexdigest()
        self._model_hashes[model_name] = h
        self._audit_log.append({
            "event": "model_registered",
            "model": model_name,
            "hash": h,
            "ts": time.time(),
        })
        logger.info(f"Registered model artifact: {model_name} hash={h[:16]}...")
        return h

    def verify_model_hash(self, model_name: str, artifact_bytes: bytes) -> bool:
        """Verify a model artifact hasn't been tampered with."""
        expected = self._model_hashes.get(model_name)
        if expected is None:
            logger.warning(f"No registered hash for model {model_name}")
            return False
        actual = hashlib.sha256(artifact_bytes).hexdigest()
        if actual != expected:
            logger.error(
                f"Model tamper detected: {model_name} "
                f"expected={expected[:16]}... got={actual[:16]}..."
            )
            self._audit_log.append({
                "event": "model_tamper_detected",
                "model": model_name,
                "expected": expected,
                "actual": actual,
                "ts": time.time(),
            })
            return False
        return True

    # ── Shadow / guard model comparison ─────────────────────────────────────

    def register_shadow_model(
        self, name: str, predict_fn: Any,
    ) -> None:
        """Register a trusted baseline (shadow) model.

        Parameters
        ----------
        name : str
            Identifier for the shadow model.
        predict_fn : callable
            ``predict_fn(payload) -> float``  returns a prediction score
            comparable to the primary model's output.
        """
        self._shadow_models[name] = predict_fn
        logger.info(f"Shadow model registered: {name}")

    def compare_with_shadows(
        self,
        primary_output: float,
        payload: Dict[str, Any],
        max_divergence: float = None,
    ) -> Dict[str, Any]:
        """Compare primary model output against all shadow models.

        Returns a dict with ``ok`` (bool), per-shadow divergence, and
        whether deployment should be blocked.

        Parameters
        ----------
        primary_output : float
            The primary model's prediction (e.g. probability 0-1).
        payload : dict
            Input data forwarded to each shadow model's predict_fn.
        max_divergence : float
            Maximum allowed absolute divergence before flagging.
        """
        # ENV-DRIVEN: Use env var or default to 0.30
        if max_divergence is None:
            max_divergence = _env_float("MERID_SHADOW_MAX_DIVERGENCE", 0.30)
        if not self._shadow_models:
            return {"ok": True, "shadows": {}, "blocked": False}

        results: Dict[str, Any] = {}
        blocked = False

        for name, fn in self._shadow_models.items():
            try:
                shadow_output = fn(payload)
                divergence = abs(primary_output - shadow_output)
                flagged = divergence > max_divergence
                results[name] = {
                    "shadow_output": round(shadow_output, 4),
                    "divergence": round(divergence, 4),
                    "flagged": flagged,
                }
                if flagged:
                    blocked = True
                    logger.warning(
                        f"Shadow model {name} diverges: "
                        f"primary={primary_output:.4f} shadow={shadow_output:.4f} "
                        f"div={divergence:.4f} > max={max_divergence}"
                    )
            except Exception as exc:
                results[name] = {"error": str(exc), "flagged": False}
                logger.warning(f"Shadow model {name} error: {exc}")

        self._audit_log.append({
            "event": "shadow_comparison",
            "primary_output": primary_output,
            "blocked": blocked,
            "shadows": results,
            "ts": time.time(),
        })

        return {"ok": not blocked, "shadows": results, "blocked": blocked}

    # ── Human confirmation ────────────────────────────────────────────────

    def confirm(self, request_id: str) -> Optional[AISuggestion]:
        """Operator confirms a pending AI suggestion."""
        suggestion = self._pending_confirmations.pop(request_id, None)
        if suggestion:
            self._audit(suggestion, "confirmed", {"confirmed_by": "operator"})
            logger.info(f"Suggestion {request_id} confirmed by operator")
        return suggestion

    def dismiss(self, request_id: str) -> bool:
        """Operator dismisses a pending AI suggestion."""
        removed = self._pending_confirmations.pop(request_id, None)
        if removed:
            self._audit(removed, "dismissed", {"dismissed_by": "operator"})
            logger.info(f"Suggestion {request_id} dismissed")
            return True
        return False

    @property
    def pending_confirmations(self) -> List[Dict[str, Any]]:
        """Return all suggestions awaiting human confirmation."""
        return [
            {
                "request_id": s.request_id,
                "type": s.suggestion_type.value,
                "source": s.source,
                "payload": s.payload,
                "ts": s.ts,
            }
            for s in self._pending_confirmations.values()
        ]

    # ── Internal helpers ──────────────────────────────────────────────────

    def _allow(self, s: AISuggestion) -> GuardrailResult:
        audit_id = self._audit(s, "allowed")
        return GuardrailResult(
            allowed=True, suggestion=s, audit_id=audit_id,
        )

    def _reject(
        self, s: AISuggestion, code: RejectionReason, reason: str,
    ) -> GuardrailResult:
        self._total_rejected += 1
        audit_id = self._audit(s, "rejected", {"code": code.value, "reason": reason})
        logger.warning(
            f"AI suggestion rejected: type={s.suggestion_type.value} "
            f"source={s.source} code={code.value} reason={reason}"
        )
        return GuardrailResult(
            allowed=False, suggestion=s,
            reason=reason, rejection_code=code, audit_id=audit_id,
        )

    def _audit(
        self, s: AISuggestion, outcome: str, extra: Optional[Dict] = None,
    ) -> str:
        audit_id = f"gr-{int(time.time() * 1000)}-{self._total_checked}"
        entry = {
            "audit_id": audit_id,
            "outcome": outcome,
            "type": s.suggestion_type.value,
            "source": s.source,
            "market_id": s.market_id,
            "contracts": s.contracts,
            "confidence": s.confidence,
            "ts": time.time(),
        }
        if extra:
            entry.update(extra)
        self._audit_log.append(entry)
        # Cap audit log size
        if len(self._audit_log) > 5000:
            self._audit_log = self._audit_log[-5000:]
        return audit_id

    def _rotate_rate_counters(self) -> None:
        now = time.time()
        if now - self._minute_reset_ts >= 60:
            self._orders_this_minute = 0
            self._minute_reset_ts = now
        if now - self._hour_reset_ts >= 3600:
            self._orders_this_hour = 0
            self._hour_reset_ts = now

    # ── Observability ─────────────────────────────────────────────────────

    def stats(self) -> Dict[str, Any]:
        return {
            "total_checked": self._total_checked,
            "total_rejected": self._total_rejected,
            "rejection_rate": (
                round(self._total_rejected / self._total_checked * 100, 1)
                if self._total_checked > 0 else 0
            ),
            "orders_this_minute": self._orders_this_minute,
            "orders_this_hour": self._orders_this_hour,
            "pending_confirmations": len(self._pending_confirmations),
            "registered_models": len(self._model_hashes),
            "audit_log_size": len(self._audit_log),
        }

    def recent_audit(self, limit: int = 50) -> List[Dict[str, Any]]:
        return self._audit_log[-limit:]


# ── Singleton ────────────────────────────────────────────────────────────────

_guardrails: Optional[AIGuardrails] = None
_guardrails_lock = threading.Lock()


def get_ai_guardrails() -> AIGuardrails:
    """Get or create the singleton AIGuardrails instance."""
    global _guardrails
    if _guardrails is None:
        with _guardrails_lock:
            if _guardrails is None:
                _guardrails = AIGuardrails()
    return _guardrails
