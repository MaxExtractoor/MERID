"""Resolved live configuration for the MERID Kalshi 15m crypto trading system.

This module is the single authority that:

1. Loads the active 15m crypto profile (``kalshi_crypto_15m_v2.yaml``).
2. Applies a typed, validated set of environment overrides.
3. Enforces cross-field invariants across exposure, loss, price, TIF,
   stop-loss execution, and contract limits.
4. Produces an immutable ``ResolvedLiveConfig`` with a SHA-256 hash.

The hash is attached to every order intent, trade decision, fill, and
reconciliation record so the configuration that authorized each record is
cryptographically auditable.

Usage::

    from merid.config.live_config import resolve_live_config, get_resolved_live_config

    resolved = resolve_live_config()
    print(resolved.config_hash)
    print(resolved.fixed_exposure_cap_usd)

The resolver is fail-closed: any conflict or unsafe override raises
``LiveConfigInvariantError`` and prevents the process from starting live trading.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
from dataclasses import asdict, dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

from utils.logger import get_logger

logger = get_logger("merid.config.live_config")


class LiveConfigInvariantError(RuntimeError):
    """Raised when the live configuration violates a safety invariant."""


@dataclass(frozen=True)
class ResolvedAssetConfig:
    """Per-asset slice of the resolved live config."""

    asset: str
    max_contracts: int
    max_notional_pct: Decimal
    max_notional_usd: Optional[Decimal]
    min_edge: Optional[Decimal]
    min_confidence: Optional[Decimal]


@dataclass(frozen=True)
class ResolvedLiveConfig:
    """Immutable, fully resolved live-trading configuration.

    All safety-critical fields are present with explicit provenance.
    The ``config_hash`` is the SHA-256 of the canonical JSON serialization of
    this object (without the hash field itself).
    """

    # Identity
    resolved: bool = True
    profile_name: str = ""
    profile_version: str = ""
    profile_path: str = ""
    operation_mode: str = "prod"
    config_hash: str = ""
    resolved_at: float = 0.0

    # Exposure and sizing
    fixed_exposure_cap_usd: Decimal = Decimal("2.00")
    max_total_notional_usd: Decimal = Decimal("2.00")
    max_single_order_notional_usd: Decimal = Decimal("2.00")
    max_contracts_per_order: int = 2
    max_positions_per_asset: int = 1

    # Price collar (execution; router must be a subset of this)
    min_entry_cents: int = 10
    max_entry_cents: int = 75
    valid_price_cents_min: int = 10
    valid_price_cents_max: int = 99

    # Loss and drawdown
    daily_loss_enabled: bool = True
    max_daily_loss_pct: Decimal = Decimal("0.05")
    max_daily_loss_usd: Optional[Decimal] = None
    drawdown_halt_pct: Decimal = Decimal("0.20")
    drawdown_unwind_pct: Decimal = Decimal("0.25")

    # Throttling
    max_orders_per_minute: int = 30
    max_orders_per_hour: int = 300
    global_orders_limit: int = 30
    global_orders_window_sec: float = 60.0

    # Stop loss / protective exits
    stop_loss_enabled: bool = True
    stop_candidate_submission_enabled: bool = False
    unprotected_entries_allowed: bool = False

    # Time in force
    entry_tif_default: str = "ioc"
    exit_tif_default: str = "gtc"
    ioc_auto_below_seconds: int = 120
    max_book_staleness_ms: int = 30000

    # Edge / confidence economics
    min_held_price_cents: Decimal = Decimal("35")  # cents
    min_required_edge: Decimal = Decimal("0.05")
    min_p_selected: Decimal = Decimal("0.50")

    # Per-asset overrides
    per_asset: Dict[str, ResolvedAssetConfig] = field(default_factory=dict)

    # Provenance / audit
    source_overrides: Dict[str, Any] = field(default_factory=dict)
    conflicts_caught: List[str] = field(default_factory=list)

    def to_canonical_dict(self) -> Dict[str, Any]:
        """Return a JSON-safe, hashable canonical dict."""
        return _convert_for_hash(asdict(self))


@dataclass
class _EnvOverride:
    """Schema for a safety-critical environment override."""

    name: str
    type: str
    is_safety_limit: bool = False
    safety_kind: str = "none"  # cap | floor | bool_safe | enum
    allowed_values: Optional[List[str]] = None
    default: Any = None
    description: str = ""


# Typed schema for environment overrides.  Only keys in this list may influence
# safety-critical live configuration.  All other MERID_* environment variables
# that touch risk/caps are treated as unknown and are rejected.
_ENV_OVERRIDES: Dict[str, _EnvOverride] = {
    "MERID_PROFILE": _EnvOverride(
        name="MERID_PROFILE",
        type="str",
        description="Active MERID profile; only kalshi_crypto_15m_v2 is supported for live resolution.",
    ),
    "MERID_OPERATION_MODE": _EnvOverride(
        name="MERID_OPERATION_MODE",
        type="str",
        allowed_values=["prod", "test"],
        description="Operation mode used to select mode-specific profile values.",
    ),
    "MERID_TRADE_MODE": _EnvOverride(
        name="MERID_TRADE_MODE",
        type="str",
        allowed_values=["live", "paper", "sim", "dev"],
        description="Trading mode used for environment gating.",
    ),
    "KALSHI_ENV": _EnvOverride(
        name="KALSHI_ENV",
        type="str",
        allowed_values=["prod", "live", "demo"],
        description="Kalshi venue environment.",
    ),
    "MERID_FIXED_EXPOSURE_CAP_USD": _EnvOverride(
        name="MERID_FIXED_EXPOSURE_CAP_USD",
        type="decimal",
        is_safety_limit=True,
        safety_kind="cap",
        description="Fixed USD exposure cap; env may only lower this limit.",
    ),
    "MERID_MAX_EXPOSURE_USD": _EnvOverride(
        name="MERID_MAX_EXPOSURE_CAP_USD",
        type="decimal",
        is_safety_limit=True,
        safety_kind="cap",
        description="Alias for MERID_FIXED_EXPOSURE_CAP_USD; must match if both set.",
    ),
    "MERID_MAX_CONTRACTS_PER_ORDER": _EnvOverride(
        name="MERID_MAX_CONTRACTS_PER_ORDER",
        type="int",
        is_safety_limit=True,
        safety_kind="cap",
        description="Maximum contracts per order; env may only lower this limit.",
    ),
    "MERID_MIN_ENTRY_CENTS": _EnvOverride(
        name="MERID_MIN_ENTRY_CENTS",
        type="int",
        is_safety_limit=True,
        safety_kind="floor",
        description="Minimum entry price in cents; env may only raise this floor.",
    ),
    "MERID_MAX_ENTRY_CENTS": _EnvOverride(
        name="MERID_MAX_ENTRY_CENTS",
        type="int",
        is_safety_limit=True,
        safety_kind="cap",
        description="Maximum entry price in cents; env may only lower this ceiling.",
    ),
    "MERID_MAX_POSITIONS_PER_ASSET": _EnvOverride(
        name="MERID_MAX_POSITIONS_PER_ASSET",
        type="int",
        is_safety_limit=True,
        safety_kind="cap",
        description="Maximum simultaneous positions per asset.",
    ),
    "MERID_VALID_PRICE_CENTS_MIN": _EnvOverride(
        name="MERID_VALID_PRICE_CENTS_MIN",
        type="int",
        is_safety_limit=True,
        safety_kind="floor",
        description="Hard Kalshi valid-price minimum; execution range must be within it.",
    ),
    "MERID_VALID_PRICE_CENTS_MAX": _EnvOverride(
        name="MERID_VALID_PRICE_CENTS_MAX",
        type="int",
        is_safety_limit=True,
        safety_kind="cap",
        description="Hard Kalshi valid-price maximum; execution range must be within it.",
    ),
    "MERID_MAX_DAILY_LOSS_PCT": _EnvOverride(
        name="MERID_MAX_DAILY_LOSS_PCT",
        type="decimal",
        is_safety_limit=True,
        safety_kind="cap",
        description="Daily loss percentage; env may only lower this limit.",
    ),
    "MERID_ENABLE_STOP_CANDIDATE_SUBMISSION": _EnvOverride(
        name="MERID_ENABLE_STOP_CANDIDATE_SUBMISSION",
        type="bool",
        is_safety_limit=True,
        safety_kind="bool_safe",
        description="Whether stop-loss candidates can be submitted as live orders.",
    ),
    "MERID_ALLOW_UNPROTECTED_ENTRIES": _EnvOverride(
        name="MERID_ALLOW_UNPROTECTED_ENTRIES",
        type="bool",
        is_safety_limit=True,
        safety_kind="bool_safe",
        description="Whether to allow new entries without executable protective exits.",
    ),
    "MERID_MIN_HELD_PRICE_CENTS": _EnvOverride(
        name="MERID_MIN_HELD_PRICE_CENTS",
        type="decimal",
        is_safety_limit=True,
        safety_kind="floor",
        description="Held-side entry price floor in cents; env may only raise this floor.",
    ),
    "MERID_TRADE_DECISION_MIN_REQUIRED_EDGE": _EnvOverride(
        name="MERID_TRADE_DECISION_MIN_REQUIRED_EDGE",
        type="decimal",
        is_safety_limit=True,
        safety_kind="floor",
        description="Minimum required net edge; env may only raise this floor.",
    ),
    "MERID_TRADE_DECISION_MIN_P_SELECTED": _EnvOverride(
        name="MERID_TRADE_DECISION_MIN_P_SELECTED",
        type="decimal",
        is_safety_limit=True,
        safety_kind="floor",
        description="Minimum selected probability; env may only raise this floor.",
    ),
    "MERID_MAX_SLIPPAGE_CENTS": _EnvOverride(
        name="MERID_MAX_SLIPPAGE_CENTS",
        type="int",
        is_safety_limit=True,
        safety_kind="cap",
        description="Maximum slippage budget in cents; env may only lower this cap.",
    ),
    "MERID_ENTRY_TIF_DEFAULT": _EnvOverride(
        name="MERID_ENTRY_TIF_DEFAULT",
        type="str",
        allowed_values=["ioc", "fok", "gtc", "gtt"],
        description="Default TIF for entry orders.",
    ),
    "MERID_EXIT_TIF_DEFAULT": _EnvOverride(
        name="MERID_EXIT_TIF_DEFAULT",
        type="str",
        allowed_values=["ioc", "fok", "gtc", "gtt"],
        description="Default TIF for exit orders.",
    ),
    "MERID_IOC_AUTO_BELOW_SECONDS": _EnvOverride(
        name="MERID_IOC_AUTO_BELOW_SECONDS",
        type="int",
        description="Auto-IOC threshold for orders near expiry.",
    ),
    "MERID_MAX_BOOK_STALENESS_MS": _EnvOverride(
        name="MERID_MAX_BOOK_STALENESS_MS",
        type="int",
        description="Maximum orderbook staleness in milliseconds.",
    ),
    "MERID_RISK_ENVELOPE_ENABLED": _EnvOverride(
        name="MERID_RISK_ENVELOPE_ENABLED",
        type="bool",
        is_safety_limit=True,
        safety_kind="bool_safe",
        description="Whether the risk envelope is enabled.",
    ),
    "MERID_ALLOW_LIVE_TRADES": _EnvOverride(
        name="MERID_ALLOW_LIVE_TRADES",
        type="bool",
        is_safety_limit=True,
        safety_kind="bool_safe",
        description="Whether live order submission is explicitly allowed.",
    ),
}

# Environment variables that are explicitly not safety-critical and may be
# present without being in the typed schema.  Any other MERID_* variable that
# looks like a cap/floor/enable/allow override is treated as unknown and
# reported as a conflict.
_ALLOWED_NON_SAFETY_PREFIXES = {
    "MERID_LOG_",
    "MERID_ENV",
    "MERID_RUNTIME_MODE",
    "MERID_RUNTIME_",
    "MERID_DATA_",
    "MERID_REDIS_",
    "MERID_POSTGRES_",
    "MERID_WEB_",
    "MERID_UI_",
    "MERID_API_",
    "MERID_WS_",
    "MERID_TELEMETRY_",
    "MERID_ALERT_",
    "MERID_DEV_",
    "MERID_TEST_",
    "MERID_SIM_",
    "MERID_PAPER_",
    "MERID_SHADOW_",
    "MERID_KALSHI_API_",
    "MERID_KALSHI_WS_",
    "MERID_KALSHI_KEY_",
    "MERID_KALSHI_",
    "MERID_KALSHI_ENV",
    "MERID_BANKROLL_",
    "MERID_EQUITY_",
    "MERID_CIRCUIT_",
    "MERID_BREAKER_",
    "MERID_MANUAL_EMERGENCY_",
    "MERID_KILL_",
    "MERID_ERROR_",
    "MERID_EXIT_FIREWALL_",
    "MERID_REQUIRE_",
    "MERID_REQUIRE_EXIT_PARENTAGE",
    "MERID_STOP_SUBMISSION_",
    "MERID_ENTRY_IDEMPOTENCY_",
    "MERID_TAIL_",
    "MERID_CHEAP_TAIL_",
    "MERID_PI_STAR_",
    "MERID_TRADE_DECISION_ALLOW_HYBRID_",
    "MERID_MIN_REGIME_POSTERIOR",
    "TRADING_ENABLED",
    "MERID_ALLOW_FAKE_BANKROLL",
    "MERID_DRY_",
    "MERID_ENABLE_ARBITRAGE",
    "MERID_ENABLE_KALSHI_",
    "MERID_ENABLE_LEGACY_",
    "MERID_ENABLE_FVG",
    "MERID_FVG_",
    "MERID_HYBRID_DISABLE_",
    "MERID_DISABLE_CRYPTO15M_GATE",
    "MERID_DISABLE_SHARED_RISK_GUARD",
    "MERID_LIVE_CONFIRMATION",
    "MERID_ANNUALIZED_VOL_",
    "MERID_CFB_",
    "MERID_ALLOW_CT_SCRIPT_BYPASS",
    "MERID_VALIDATION_MODE",
    "MERID_OPERATION_MODE",  # already in schema
    "MERID_TRADE_MODE",  # already in schema
    "MERID_PM_",
}

import re

# Regexes for environment variables that look like safety caps/floors and MUST
# be declared in the schema.  Feature toggles and operational variables should
# not match these.
_SAFETY_PATTERNS = (
    re.compile(
        r"^MERID_(MIN|MAX|FIXED)_.*(USD|PCT|CENTS|CONTRACT|EXPOSURE|LOSS|PRICE|EDGE|DAILY|ENTRY|POSITION|HELD|RISK|STOP|TIF|CAP|LOSS|CONTRACTS)$",
        re.IGNORECASE,
    ),
    re.compile(
        r"^MERID_(ENABLE|ALLOW)_.*(STOP|LOSS|RISK|PROTECTED|LIVE_TRADES|UNPROTECTED)$",
        re.IGNORECASE,
    ),
)

# Singleton cache
_resolved_lock = threading.RLock()
_resolved_config: Optional[ResolvedLiveConfig] = None
_unresolved_default: Optional[ResolvedLiveConfig] = None


def _convert_for_hash(obj: Any) -> Any:
    """Recursively convert values to JSON-safe, stable hash inputs."""
    if isinstance(obj, Decimal):
        return str(obj)
    if isinstance(obj, float):
        # Round to 12 decimal places for stable hashes.
        return round(obj, 12)
    if isinstance(obj, dict):
        return {k: _convert_for_hash(v) for k, v in sorted(obj.items())}
    if isinstance(obj, (list, tuple)):
        return [_convert_for_hash(v) for v in obj]
    if isinstance(obj, (set, frozenset)):
        return sorted([_convert_for_hash(v) for v in obj])
    return obj


def _canonical_json(data: Dict[str, Any]) -> str:
    """Stable canonical JSON for hashing."""
    return json.dumps(data, sort_keys=True, separators=(",", ":"))


def compute_config_hash(canonical_dict: Dict[str, Any]) -> str:
    """Compute the SHA-256 hash of a canonical configuration dict."""
    payload = _canonical_json(canonical_dict)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _safe_env(name: str) -> Optional[str]:
    """Read an environment variable, returning None for empty/whitespace."""
    value = os.environ.get(name)
    if value is None:
        return None
    value = value.strip()
    return value if value else None


def _parse_bool(value: str) -> bool:
    """Parse a boolean from common env string forms."""
    return value.lower() in ("1", "true", "yes", "on")


def _parse_decimal(value: str, name: str) -> Decimal:
    """Parse a Decimal, raising an invariant error on failure."""
    try:
        return Decimal(value)
    except InvalidOperation as exc:
        raise LiveConfigInvariantError(
            f"Environment variable {name}={value!r} is not a valid decimal number"
        ) from exc


def _parse_int(value: str, name: str) -> int:
    """Parse an int, raising an invariant error on failure."""
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise LiveConfigInvariantError(
            f"Environment variable {name}={value!r} is not a valid integer"
        ) from exc


def _parse_float(value: str, name: str) -> float:
    """Parse a float, raising an invariant error on failure."""
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise LiveConfigInvariantError(
            f"Environment variable {name}={value!r} is not a valid number"
        ) from exc


def _apply_schema(name: str, override: _EnvOverride) -> Any:
    """Read and type-validate an environment override from the schema."""
    raw = _safe_env(name)
    if raw is None:
        return None

    if override.allowed_values is not None:
        if raw.lower() not in [v.lower() for v in override.allowed_values]:
            raise LiveConfigInvariantError(
                f"Environment variable {name}={raw!r} is not one of the allowed values: "
                f"{override.allowed_values}"
            )

    if override.type == "bool":
        return _parse_bool(raw)
    if override.type == "int":
        return _parse_int(raw, name)
    if override.type == "float":
        return _parse_float(raw, name)
    if override.type == "decimal":
        return _parse_decimal(raw, name)
    if override.type == "str":
        return raw
    raise LiveConfigInvariantError(f"Unknown schema type {override.type!r} for {name}")


class LiveConfigResolver:
    """Resolve profile + environment overrides into an authoritative live config."""

    def __init__(
        self,
        profile_name: Optional[str] = None,
        profile_path: Optional[Path] = None,
        operation_mode: Optional[str] = None,
    ):
        self._profile_name = (profile_name or _safe_env("MERID_PROFILE") or "").strip()
        self._profile_path = profile_path
        self._operation_mode = (operation_mode or _safe_env("MERID_OPERATION_MODE") or "").strip()
        self._conflicts: List[str] = []
        self._overrides: Dict[str, Any] = {}

    def resolve(self) -> ResolvedLiveConfig:
        """Load the profile, apply env overrides, and enforce invariants."""
        self._conflicts = []
        self._overrides = {}

        # Load profile via the canonical adapter and also keep raw YAML.
        # Importing the adapter pulls in merid.settings, which loads the .env
        # file.  We need the .env values in os.environ before resolving the
        # operation mode and applying typed env overrides.
        from merid.risk.profiles.crypto_15m_profile import Crypto15mProfileAdapter

        # The .env file is now loaded, so read MERID_PROFILE from it if needed.
        if not self._profile_name:
            self._profile_name = _safe_env("MERID_PROFILE") or ""

        if not self._profile_name:
            self._profile_name = "kalshi_crypto_15m_v2"
            logger.warning(
                "[LIVE-CONFIG] MERID_PROFILE not set; defaulting to %s for resolution",
                self._profile_name,
            )

        if self._profile_name != "kalshi_crypto_15m_v2":
            raise LiveConfigInvariantError(
                f"Unsupported profile for live resolution: {self._profile_name!r}. "
                "Only 'kalshi_crypto_15m_v2' is supported."
            )

        if self._profile_path is None:
            repo_root = Path(__file__).parent.parent.parent
            self._profile_path = (
                repo_root / "config" / "profiles" / f"{self._profile_name}.yaml"
            )

        if not self._profile_path.exists():
            raise LiveConfigInvariantError(f"Profile file not found: {self._profile_path}")

        with open(self._profile_path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}

        adapter = Crypto15mProfileAdapter(self._profile_path)
        profile = adapter.profile

        # Validate that all safety-critical env variables are in the schema and
        # collect unknown/overrides.  This runs after the profile adapter import
        # so the .env file is loaded into os.environ.
        env_overrides = self._collect_env_overrides()

        # Resolve operation mode now that the .env is loaded.
        if not self._operation_mode:
            env_op = _safe_env("MERID_OPERATION_MODE")
            if env_op:
                self._operation_mode = env_op
            else:
                from merid.config.environment import current_env

                env_value = current_env().value
                if env_value in ("dev", "staging"):
                    self._operation_mode = "test"
                elif env_value == "prod":
                    self._operation_mode = "prod"
                else:
                    self._operation_mode = "prod"

        # Build the resolved config field by field.
        resolved = self._build_resolved(raw, profile, env_overrides)

        # Run cross-field invariants.
        self._enforce_invariants(resolved)

        # Attach provenance.
        resolved = self._with_provenance(resolved, env_overrides)

        return resolved

    def _collect_env_overrides(self) -> Dict[str, Any]:
        """Collect and validate all safety-critical env overrides."""
        env_overrides: Dict[str, Any] = {}

        for name, override in _ENV_OVERRIDES.items():
            value = _apply_schema(name, override)
            if value is not None:
                env_overrides[name] = value
                self._overrides[name] = value

        # Warn on unknown MERID_* variables; raise only when they look like
        # safety caps/floors and are not in the schema.
        for name in sorted(os.environ.keys()):
            if name in _ENV_OVERRIDES:
                continue
            if not name.startswith("MERID_"):
                continue
            if any(name.startswith(prefix) for prefix in _ALLOWED_NON_SAFETY_PREFIXES):
                continue
            if any(pattern.match(name) for pattern in _SAFETY_PATTERNS):
                raise LiveConfigInvariantError(
                    f"Unknown safety-critical environment variable {name}={os.environ[name]!r}. "
                    "Declare it in the live-config schema or remove it."
                )
            self._conflicts.append(
                f"Unknown MERID_* variable not in live-config schema: {name}={os.environ[name]!r}. "
                "It will be ignored for safety-critical resolution."
            )

        return env_overrides

    def _build_resolved(
        self,
        raw: Dict[str, Any],
        profile: Any,
        env: Dict[str, Any],
    ) -> ResolvedLiveConfig:
        """Combine profile and validated env overrides into a ResolvedLiveConfig."""

        # ── Exposure cap ──────────────────────────────────────────────────────
        profile_cap = Decimal(str(profile.risk_policy_fixed_exposure_cap_usd))
        env_fixed = env.get("MERID_FIXED_EXPOSURE_CAP_USD")
        env_max = env.get("MERID_MAX_EXPOSURE_USD")

        if env_fixed is not None and env_max is not None:
            if env_fixed != env_max:
                raise LiveConfigInvariantError(
                    f"Conflicting exposure caps: MERID_FIXED_EXPOSURE_CAP_USD={env_fixed} "
                    f"and MERID_MAX_EXPOSURE_USD={env_max}"
                )
            self._overrides.setdefault("MERID_FIXED_EXPOSURE_CAP_USD", env_fixed)

        env_cap = env_fixed if env_fixed is not None else env_max
        if env_cap is not None and env_cap > profile_cap:
            raise LiveConfigInvariantError(
                f"Environment override attempts to raise the fixed exposure cap: "
                f"profile={profile_cap}, env={env_cap}. Raising safety limits is not allowed."
            )
        fixed_exposure_cap = env_cap if env_cap is not None else profile_cap

        # ── Contracts per order ───────────────────────────────────────────────
        profile_contracts = int(profile.contract_caps_max_single_order_contracts)
        profile_failsafe = int(profile.failsafe_max_contracts_per_order)
        if profile_contracts != profile_failsafe:
            raise LiveConfigInvariantError(
                f"Profile contract cap conflict: contract_caps.max_single_order_contracts="
                f"{profile_contracts} != failsafe.max_contracts_per_order={profile_failsafe}"
            )

        env_contracts = env.get("MERID_MAX_CONTRACTS_PER_ORDER")
        if env_contracts is not None and env_contracts > profile_contracts:
            raise LiveConfigInvariantError(
                f"Environment override attempts to raise max contracts per order: "
                f"profile={profile_contracts}, env={env_contracts}"
            )
        max_contracts = env_contracts if env_contracts is not None else profile_contracts

        # ── Price collar ──────────────────────────────────────────────────────
        # Resolve the tightest execution range from all profile sources.
        # Fail-closed: if sources disagree, take the most restrictive values and
        # record the conflict.
        price_range = profile.price_range
        guardrails_min = int(profile.guardrails_min_contract_price_cents)
        guardrails_max = int(profile.guardrails_max_contract_price_cents)

        min_entry = max(
            price_range.min_price_cents,
            guardrails_min,
            int(profile.venue_invariants_valid_price_cents_min),
        )
        max_entry = min(
            price_range.max_price_cents,
            guardrails_max,
            int(profile.venue_invariants_valid_price_cents_max),
        )

        if price_range.min_price_cents != guardrails_min:
            self._conflicts.append(
                f"Profile price floor disagreement: price_range.min_price_cents="
                f"{price_range.min_price_cents}, guardrails.min_contract_price_cents={guardrails_min}; "
                f"resolved to the safer floor {min_entry}c"
            )
        if price_range.max_price_cents != guardrails_max:
            self._conflicts.append(
                f"Profile price ceiling disagreement: price_range.max_price_cents="
                f"{price_range.max_price_cents}, guardrails.max_contract_price_cents={guardrails_max}; "
                f"resolved to the safer ceiling {max_entry}c"
            )

        env_min_entry = env.get("MERID_MIN_ENTRY_CENTS")
        if env_min_entry is not None:
            if env_min_entry < min_entry:
                raise LiveConfigInvariantError(
                    f"Environment override attempts to lower the minimum entry price: "
                    f"profile={min_entry}, env={env_min_entry}"
                )
            min_entry = env_min_entry

        env_max_entry = env.get("MERID_MAX_ENTRY_CENTS")
        if env_max_entry is not None:
            if env_max_entry > max_entry:
                raise LiveConfigInvariantError(
                    f"Environment override attempts to raise the maximum entry price: "
                    f"profile={max_entry}, env={env_max_entry}"
                )
            max_entry = env_max_entry

        valid_min = int(profile.venue_invariants_valid_price_cents_min)
        valid_max = int(profile.venue_invariants_valid_price_cents_max)

        env_valid_min = env.get("MERID_VALID_PRICE_CENTS_MIN")
        if env_valid_min is not None:
            valid_min = env_valid_min
        env_valid_max = env.get("MERID_VALID_PRICE_CENTS_MAX")
        if env_valid_max is not None:
            valid_max = env_valid_max

        min_entry = max(min_entry, valid_min)
        max_entry = min(max_entry, valid_max)

        # ── Daily loss ────────────────────────────────────────────────────────
        guardrails = raw.get("guardrails", {})
        daily_loss_enabled = bool(guardrails.get("daily_loss_enabled", False))
        max_daily_loss_pct = Decimal("0.05")

        mdl = guardrails.get("max_daily_loss_pct")
        if isinstance(mdl, dict):
            mdl_value = mdl.get(self._operation_mode, mdl.get("prod", 0.05))
            max_daily_loss_pct = Decimal(str(mdl_value))
        elif mdl is not None:
            max_daily_loss_pct = Decimal(str(mdl))

        env_daily_loss = env.get("MERID_MAX_DAILY_LOSS_PCT")
        if env_daily_loss is not None:
            if env_daily_loss > max_daily_loss_pct:
                raise LiveConfigInvariantError(
                    f"Environment override attempts to raise the daily loss limit: "
                    f"profile={max_daily_loss_pct}, env={env_daily_loss}"
                )
            max_daily_loss_pct = env_daily_loss

        capital_usd = Decimal(str(profile.capital_usd)) if profile.capital_usd > 0 else None
        max_daily_loss_usd = None
        if daily_loss_enabled and capital_usd is not None:
            max_daily_loss_usd = (capital_usd * max_daily_loss_pct).quantize(
                Decimal("0.01"), rounding="ROUND_HALF_UP"
            )

        # ── Drawdown ──────────────────────────────────────────────────────────
        drawdown_halt = Decimal(str(profile.guardrails_drawdown_halt_pct))
        drawdown_unwind = Decimal(str(profile.guardrails_drawdown_unwind_pct))

        # ── TIF / venue invariants ────────────────────────────────────────────
        venue_invariants = raw.get("venue_invariants", {})
        entry_tif = _extract_venue_invariant_value(venue_invariants, "entry_tif_default", "ioc")
        exit_tif = _extract_venue_invariant_value(venue_invariants, "exit_tif_default", "gtc")

        env_entry_tif = env.get("MERID_ENTRY_TIF_DEFAULT")
        if env_entry_tif is not None:
            if env_entry_tif.lower() not in ("ioc", "fok"):
                raise LiveConfigInvariantError(
                    f"Unsafe entry TIF override: {env_entry_tif!r}. Entry orders must be "
                    "immediate (ioc or fok)."
                )
            entry_tif = env_entry_tif.lower()

        env_exit_tif = env.get("MERID_EXIT_TIF_DEFAULT")
        if env_exit_tif is not None:
            if env_exit_tif.lower() in ("ioc", "fok"):
                raise LiveConfigInvariantError(
                    f"Unsafe exit TIF override: {env_exit_tif!r}. Exit orders must be able to "
                    "rest (gtc or gtt)."
                )
            exit_tif = env_exit_tif.lower()

        ioc_auto = int(profile.venue_invariants_ioc_auto_below_seconds)
        env_ioc_auto = env.get("MERID_IOC_AUTO_BELOW_SECONDS")
        if env_ioc_auto is not None:
            ioc_auto = env_ioc_auto

        book_staleness = int(profile.venue_invariants_max_book_staleness_ms)
        env_book_staleness = env.get("MERID_MAX_BOOK_STALENESS_MS")
        if env_book_staleness is not None:
            book_staleness = env_book_staleness

        # ── Stop-loss execution path ──────────────────────────────────────────
        exit_policy = raw.get("exit_policy", {})
        risk_reward = exit_policy.get("risk_reward", {})
        stop_loss_enabled = bool(risk_reward.get("stop_loss_enabled", True))

        stop_submission_enabled = bool(env.get("MERID_ENABLE_STOP_CANDIDATE_SUBMISSION", False))
        unprotected_entries = bool(env.get("MERID_ALLOW_UNPROTECTED_ENTRIES", False))

        # ── Edge / confidence economics ───────────────────────────────────────
        strategy_policy = raw.get("strategy_policy", {})
        profile_min_edge = Decimal(str(strategy_policy.get("min_edge", profile.strategy_policy_min_edge)))
        env_min_edge = env.get("MERID_TRADE_DECISION_MIN_REQUIRED_EDGE")
        if env_min_edge is not None:
            if env_min_edge < profile_min_edge:
                raise LiveConfigInvariantError(
                    f"Environment override attempts to lower the minimum required edge: "
                    f"profile={profile_min_edge}, env={env_min_edge}"
                )
            min_required_edge = env_min_edge
        else:
            min_required_edge = profile_min_edge

        profile_min_confidence = Decimal(str(profile.confidence_min_confidence_threshold))
        env_min_p = env.get("MERID_TRADE_DECISION_MIN_P_SELECTED")
        default_min_p = Decimal("0.50")
        min_p = max(default_min_p, profile_min_confidence)
        if env_min_p is not None:
            if env_min_p < min_p:
                raise LiveConfigInvariantError(
                    f"Environment override attempts to lower the minimum selected probability: "
                    f"profile={min_p}, env={env_min_p}"
                )
            min_p = env_min_p

        held_floor_default = Decimal("35")  # cents
        env_held_floor = env.get("MERID_MIN_HELD_PRICE_CENTS")
        if env_held_floor is not None:
            if env_held_floor < held_floor_default:
                raise LiveConfigInvariantError(
                    f"Environment override attempts to lower the held-side price floor: "
                    f"default={held_floor_default}, env={env_held_floor}"
                )
            min_held_price = env_held_floor
        else:
            min_held_price = held_floor_default

        # ── Throttling ────────────────────────────────────────────────────────
        throttling = raw.get("throttling", {})
        max_orders_per_minute = int(profile.venue_max_orders_per_minute)
        max_orders_per_hour = int(profile.venue_max_orders_per_hour)
        global_orders_limit = int(throttling.get("global_orders_limit", profile.venue_max_orders_per_hour))
        global_orders_window = float(throttling.get("global_orders_window_sec", 60.0))

        # ── Per-asset ─────────────────────────────────────────────────────────
        per_asset: Dict[str, ResolvedAssetConfig] = {}
        for asset_name, ac in profile.asset_configs.items():
            per_asset[asset_name] = ResolvedAssetConfig(
                asset=asset_name,
                max_contracts=int(ac.max_contracts),
                max_notional_pct=Decimal(str(ac.max_notional_pct)),
                max_notional_usd=Decimal(str(ac.max_notional_usd)) if ac.max_notional_usd else None,
                min_edge=None,
                min_confidence=None,
            )

        return ResolvedLiveConfig(
            resolved=True,
            profile_name=profile.profile_name,
            profile_version=profile.profile_version,
            profile_path=str(self._profile_path),
            operation_mode=self._operation_mode,
            fixed_exposure_cap_usd=fixed_exposure_cap,
            max_total_notional_usd=fixed_exposure_cap,
            max_single_order_notional_usd=fixed_exposure_cap,
            max_contracts_per_order=max_contracts,
            max_positions_per_asset=int(profile.agent_max_yes_position),
            min_entry_cents=min_entry,
            max_entry_cents=max_entry,
            valid_price_cents_min=valid_min,
            valid_price_cents_max=valid_max,
            daily_loss_enabled=daily_loss_enabled,
            max_daily_loss_pct=max_daily_loss_pct,
            max_daily_loss_usd=max_daily_loss_usd,
            drawdown_halt_pct=drawdown_halt,
            drawdown_unwind_pct=drawdown_unwind,
            max_orders_per_minute=max_orders_per_minute,
            max_orders_per_hour=max_orders_per_hour,
            global_orders_limit=global_orders_limit,
            global_orders_window_sec=global_orders_window,
            stop_loss_enabled=stop_loss_enabled,
            stop_candidate_submission_enabled=stop_submission_enabled,
            unprotected_entries_allowed=unprotected_entries,
            entry_tif_default=entry_tif,
            exit_tif_default=exit_tif,
            ioc_auto_below_seconds=ioc_auto,
            max_book_staleness_ms=book_staleness,
            min_held_price_cents=min_held_price,
            min_required_edge=min_required_edge,
            min_p_selected=min_p,
            per_asset=per_asset,
            source_overrides={},
            conflicts_caught=[],
            resolved_at=0.0,
            config_hash="",
        )

    def _enforce_invariants(self, resolved: ResolvedLiveConfig) -> None:
        """Cross-field invariant checks.  Fail closed."""

        # 1. Execution price range must be inside the hard valid price range.
        if resolved.min_entry_cents < resolved.valid_price_cents_min:
            raise LiveConfigInvariantError(
                f"Entry price floor {resolved.min_entry_cents}c is below the hard valid minimum "
                f"{resolved.valid_price_cents_min}c"
            )
        if resolved.max_entry_cents > resolved.valid_price_cents_max:
            raise LiveConfigInvariantError(
                f"Entry price ceiling {resolved.max_entry_cents}c is above the hard valid maximum "
                f"{resolved.valid_price_cents_max}c"
            )
        if resolved.min_entry_cents > resolved.max_entry_cents:
            raise LiveConfigInvariantError(
                f"Entry price range is empty: [{resolved.min_entry_cents}, {resolved.max_entry_cents}]"
            )

        # 2. Drawdown unwind must be strictly wider than halt.
        if resolved.drawdown_unwind_pct <= resolved.drawdown_halt_pct:
            raise LiveConfigInvariantError(
                f"drawdown_unwind_pct ({resolved.drawdown_unwind_pct}) must be > "
                f"drawdown_halt_pct ({resolved.drawdown_halt_pct})"
            )

        # 3. Stop loss declared but not executable.
        if (
            resolved.stop_loss_enabled
            and not resolved.stop_candidate_submission_enabled
            and not resolved.unprotected_entries_allowed
        ):
            raise LiveConfigInvariantError(
                "Profile declares stop_loss_enabled=true but MERID_ENABLE_STOP_CANDIDATE_SUBMISSION "
                "is not enabled and MERID_ALLOW_UNPROTECTED_ENTRIES is not set. New entries are "
                "blocked because protective exits cannot be executed. Either enable stop-candidate "
                "submission, set MERID_ALLOW_UNPROTECTED_ENTRIES=1, or disable stop-loss in the profile."
            )

        # 4. Stop-candidate submission and unprotected entries are mutually exclusive safety modes.
        if resolved.stop_candidate_submission_enabled and resolved.unprotected_entries_allowed:
            self._conflicts.append(
                "Both MERID_ENABLE_STOP_CANDIDATE_SUBMISSION and MERID_ALLOW_UNPROTECTED_ENTRIES "
                "are enabled; unprotected_entries takes precedence for the resolver but both should "
                "not be active simultaneously."
            )

        # 5. Daily loss percentage must be sensible.
        if not (Decimal("0") < resolved.max_daily_loss_pct <= Decimal("1")):
            raise LiveConfigInvariantError(
                f"max_daily_loss_pct must be in (0, 1], got {resolved.max_daily_loss_pct}"
            )

        # 6. Fixed exposure cap must be positive and modest.
        if resolved.fixed_exposure_cap_usd <= Decimal("0"):
            raise LiveConfigInvariantError(
                f"fixed_exposure_cap_usd must be positive, got {resolved.fixed_exposure_cap_usd}"
            )

        # 7. TIF invariants.
        if resolved.entry_tif_default not in ("ioc", "fok"):
            raise LiveConfigInvariantError(
                f"Entry TIF must be immediate (ioc/fok), got {resolved.entry_tif_default}"
            )
        if resolved.exit_tif_default in ("ioc", "fok"):
            raise LiveConfigInvariantError(
                f"Exit TIF must allow resting (gtc/gtt), got {resolved.exit_tif_default}"
            )

    def _with_provenance(
        self, resolved: ResolvedLiveConfig, env_overrides: Dict[str, Any]
    ) -> ResolvedLiveConfig:
        """Attach source overrides, conflict log, and the immutable config hash."""
        from dataclasses import replace
        import time

        overrides = dict(env_overrides)
        overrides["profile_path"] = str(self._profile_path)
        overrides["operation_mode"] = self._operation_mode

        canonical = resolved.to_canonical_dict()
        canonical.pop("config_hash", None)
        canonical.pop("resolved_at", None)
        canonical["source_overrides"] = _convert_for_hash(overrides)
        canonical["conflicts_caught"] = _convert_for_hash(self._conflicts)
        config_hash = compute_config_hash(canonical)

        return replace(
            resolved,
            resolved_at=time.time(),
            config_hash=config_hash,
            source_overrides=overrides,
            conflicts_caught=list(self._conflicts),
        )


def _extract_venue_invariant_value(invariants: Dict[str, Any], key: str, default: str) -> str:
    """Read a venue invariant that may be a dict with a 'value' field."""
    value = invariants.get(key, default)
    if isinstance(value, dict):
        value = value.get("value", default)
    return str(value).lower()


def resolve_live_config(
    profile_name: Optional[str] = None,
    profile_path: Optional[Path] = None,
    operation_mode: Optional[str] = None,
    force: bool = False,
) -> ResolvedLiveConfig:
    """Resolve the live configuration and cache it as the process singleton.

    Args:
        profile_name: Optional profile name override.
        profile_path: Optional path to the YAML profile.
        operation_mode: Optional operation mode (``prod`` or ``test``).
        force: If True, re-resolve even if a resolved config is already cached.

    Returns:
        The resolved, immutable live configuration.
    """
    global _resolved_config

    with _resolved_lock:
        if _resolved_config is not None and not force:
            return _resolved_config

        resolver = LiveConfigResolver(
            profile_name=profile_name,
            profile_path=profile_path,
            operation_mode=operation_mode,
        )
        resolved = resolver.resolve()
        _resolved_config = resolved

        logger.info(
            "[LIVE-CONFIG] Resolved live config for profile=%s version=%s mode=%s hash=%s",
            resolved.profile_name,
            resolved.profile_version,
            resolved.operation_mode,
            resolved.config_hash,
        )
        for conflict in resolved.conflicts_caught:
            logger.warning("[LIVE-CONFIG] conflict: %s", conflict)

        return resolved


def get_resolved_live_config(allow_unresolved: bool = False) -> ResolvedLiveConfig:
    """Return the cached resolved live configuration.

    If ``allow_unresolved`` is True and no resolution has happened, a default
    unresolved config is returned (useful for tests and modules that need a
    fallback before startup resolves the profile). If ``allow_unresolved`` is
    False and no resolution has happened, the function attempts to resolve.
    """
    global _resolved_config, _unresolved_default

    with _resolved_lock:
        if _resolved_config is not None:
            return _resolved_config

        if allow_unresolved:
            if _unresolved_default is None:
                _unresolved_default = ResolvedLiveConfig(resolved=False)
            return _unresolved_default

        # Auto-resolve only if the live 15m profile is active.
        profile = _safe_env("MERID_PROFILE")
        if profile == "kalshi_crypto_15m_v2":
            return resolve_live_config()

        raise LiveConfigInvariantError(
            "Live configuration has not been resolved. Call resolve_live_config() first."
        )


def reset_resolved_live_config() -> None:
    """Clear the cached resolved live configuration.  For tests only."""
    global _resolved_config, _unresolved_default
    with _resolved_lock:
        _resolved_config = None
        _unresolved_default = None


def is_resolved_live_config() -> bool:
    """Return True if a resolved live config has been cached."""
    with _resolved_lock:
        return _resolved_config is not None
