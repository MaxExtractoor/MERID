"""MERID Strategy Registry — factory, validation, and startup wiring helpers.

This module provides:

1. **Registry** — a ``STRATEGY_REGISTRY`` dict plus ``@register_strategy``
   decorator so that each named profile can be instantiated on demand.

2. **Validation** — ``validate_all_strategy_configs()`` loads every
   strategy YAML and checks it against the corresponding Python config
   type.  Unknown keys, type mismatches, and missing required fields all
   raise ``StrategyConfigError`` listing every problem in one shot.  Wire
   this into startup so the server fails fast on misconfiguration.

3. **Catalog loader** — ``load_strategy_catalog()`` reads
   ``config/strategy_catalog.yaml`` and returns the ``enabled_profiles``
   list together with the full parsed catalog.

YAML → Python mapping table
────────────────────────────
  config/strategies/kalshi_crypto_15m_conservative.yaml
      loader : _load_conservative_yaml()
      type   : Conservative15mConfig (merid.strategies.kalshi_crypto_15m_conservative)
      strategy: Conservative15mStrategy → get_conservative_15m_strategy()
      registry: "kalshi_crypto_15m_conservative"

  config/strategy_catalog.yaml  (30-cell grid)
      loader : load_strategy_catalog()
      type   : plain dict (per-cell params used by CT / AgentGrid)
      profiles: trading.strategies.enabled_profiles list

  config/kalshi_agent_grid.yaml  (30 agent configs)
      loader : load_agent_grid_config()  (merid.prediction.agent_grid_config)
      type   : AgentGridConfig
      — not validated here; handled by agent_grid_config.py —

Usage::

    from merid.trading.strategy_registry import (
        validate_all_strategy_configs,
        build_strategy_from_profile,
        load_strategy_catalog,
        STRATEGY_REGISTRY,
    )

    # On startup:
    validate_all_strategy_configs()     # raises StrategyConfigError if bad

    catalog = load_strategy_catalog()
    for profile_name in catalog["enabled_profiles"]:
        strategy = build_strategy_from_profile(profile_name)
        print(f"Loaded strategy={profile_name}")
"""

from __future__ import annotations

import dataclasses
import os
from typing import Any, Callable, Dict, List, Optional

import yaml

from utils.logger import get_logger

logger = get_logger("merid.trading.strategy_registry")

# ── Paths ──────────────────────────────────────────────────────────────────

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
_STRATEGIES_DIR = os.path.join(_REPO_ROOT, "config", "strategies")
_CATALOG_PATH = os.path.join(_REPO_ROOT, "config", "strategy_catalog.yaml")

# ── Exceptions ─────────────────────────────────────────────────────────────


class StrategyConfigError(ValueError):
    """Raised by ``validate_all_strategy_configs()`` when YAML is misconfigured."""


# ── Registry ───────────────────────────────────────────────────────────────

# Maps profile_name → zero-arg factory that returns a live strategy instance.
STRATEGY_REGISTRY: Dict[str, Callable[[], Any]] = {}


def register_strategy(name: str) -> Callable:
    """Decorator that registers a factory under a strategy profile name.

    The decorated callable must be a zero-argument factory that returns a
    live strategy instance when called.

    Example::

        @register_strategy("kalshi_crypto_15m_conservative")
        def _make_conservative_15m():
            from merid.strategies.kalshi_crypto_15m_conservative import (
                get_conservative_15m_strategy,
            )
            return get_conservative_15m_strategy()
    """
    def wrapper(factory: Callable[[], Any]) -> Callable[[], Any]:
        if name in STRATEGY_REGISTRY:
            logger.warning(
                "register_strategy: overwriting existing registration for '%s'", name
            )
        STRATEGY_REGISTRY[name] = factory
        logger.debug("register_strategy: registered '%s'", name)
        return factory
    return wrapper


def build_strategy_from_profile(profile_name: str) -> Any:
    """Instantiate and return a live strategy by its registered profile name.

    Raises ``KeyError`` if *profile_name* is not in ``STRATEGY_REGISTRY``.
    """
    if profile_name not in STRATEGY_REGISTRY:
        raise KeyError(
            f"Strategy profile '{profile_name}' is not registered. "
            f"Known profiles: {sorted(STRATEGY_REGISTRY)}"
        )
    return STRATEGY_REGISTRY[profile_name]()


# ── Built-in registrations ─────────────────────────────────────────────────

@register_strategy("kalshi_crypto_15m_conservative")
def _kalshi_crypto_15m_conservative_factory() -> Any:
    """Return the Conservative15mStrategy singleton."""
    from merid.strategies.kalshi_crypto_15m_conservative import get_conservative_15m_strategy
    return get_conservative_15m_strategy()


# ── Catalog loader ─────────────────────────────────────────────────────────


def load_strategy_catalog(path: Optional[str] = None) -> Dict[str, Any]:
    """Load ``config/strategy_catalog.yaml`` and return a parsed dict.

    Returns a dict with at least:
        ``enabled_profiles``  — list of profile name strings
        ``assets``            — per-asset per-timeframe cell configs
        ``global_risk``       — global risk parameters
        ``promotion_rules``   — promotion / pruning thresholds

    Falls back to ``{"enabled_profiles": [], "assets": {}}`` on load failure.
    """
    catalog_path = path or _CATALOG_PATH
    try:
        with open(catalog_path) as fh:
            raw = yaml.safe_load(fh) or {}
    except (OSError, yaml.YAMLError) as exc:
        logger.warning("Failed to load strategy catalog %s: %s", catalog_path, exc)
        return {"enabled_profiles": [], "assets": {}}

    # Normalise enabled_profiles from trading.strategies.enabled_profiles
    enabled_profiles: List[str] = []
    trading = raw.get("trading", {})
    if isinstance(trading, dict):
        strategies = trading.get("strategies", {})
        if isinstance(strategies, dict):
            enabled_profiles = list(strategies.get("enabled_profiles", []))

    return {
        "enabled_profiles": enabled_profiles,
        "assets": raw.get("assets", {}),
        "global_risk": raw.get("global_risk", {}),
        "promotion_rules": raw.get("promotion_rules", {}),
        "demotion_rules": raw.get("demotion_rules", {}),
        "_raw": raw,
    }


# ── YAML key / type validators ─────────────────────────────────────────────

# These YAML keys appear in kalshi_crypto_15m_conservative.yaml but are
# intentional metadata; they are NOT fields of Conservative15mConfig.
_CONSERVATIVE_YAML_METADATA_KEYS = frozenset(
    {"profile", "version", "assets", "primary_timeframe", "context_timeframes"}
)


def _validate_conservative_yaml(path: str) -> List[str]:
    """Validate ``kalshi_crypto_15m_conservative.yaml`` against ``Conservative15mConfig``.

    Returns a list of error strings (empty = no problems).
    """
    from merid.strategies.kalshi_crypto_15m_conservative import Conservative15mConfig

    errors: List[str] = []

    # Load raw YAML
    try:
        with open(path) as fh:
            raw: Dict[str, Any] = yaml.safe_load(fh) or {}
    except (OSError, yaml.YAMLError) as exc:
        return [f"{path}: load error: {exc}"]

    # ── Required metadata keys ────────────────────────────────────────────
    if raw.get("profile") != "kalshi_crypto_15m_conservative":
        errors.append(
            f"{path}: expected profile='kalshi_crypto_15m_conservative', "
            f"got {raw.get('profile')!r}"
        )

    if "enabled" not in raw:
        errors.append(f"{path}: missing required key 'enabled'")

    # ── Unknown config keys ────────────────────────────────────────────────
    known_fields = {f.name for f in dataclasses.fields(Conservative15mConfig)}
    config_keys = {k for k in raw if k not in _CONSERVATIVE_YAML_METADATA_KEYS}
    unknown = config_keys - known_fields
    if unknown:
        errors.append(
            f"{path}: unknown config keys {sorted(unknown)} "
            f"(not fields of Conservative15mConfig)"
        )

    # ── Type checks for critical numeric fields ───────────────────────────
    type_checks: List[tuple] = [
        ("enabled", bool),
        ("min_p", (int, float)),
        ("min_p_satellite", (int, float)),
        ("min_edge_bps", (int, float)),
        ("soft_target_trades_per_hour", (int, float)),
        ("global_max_trades_per_hour", (int, float)),
        ("per_asset_max_per_15m", (int, float)),
        ("kelly_fraction", (int, float)),
        ("max_risk_per_trade_pct", (int, float)),
        ("htf_alignment_min", (int, float)),
        ("htf_contradiction_threshold", (int, float)),
        ("rate_tighten_delta", (int, float)),
        ("drawdown_warning_pct", (int, float)),
        ("drawdown_pause_pct", (int, float)),
        ("drawdown_min_p_delta", (int, float)),
        ("drawdown_kelly_scale", (int, float)),
        ("min_contract_volume", (int, float)),
        ("min_contract_oi", (int, float)),
        ("max_spread_cents", (int, float)),
    ]
    for key, expected_types in type_checks:
        if key in raw:
            val = raw[key]
            if not isinstance(val, expected_types):
                exp_name = (
                    expected_types.__name__
                    if isinstance(expected_types, type)
                    else "/".join(t.__name__ for t in expected_types)
                )
                errors.append(
                    f"{path}: '{key}' expected {exp_name}, "
                    f"got {type(val).__name__} ({val!r})"
                )

    # ── Sanity-range checks ───────────────────────────────────────────────
    for prob_key in ("min_p", "min_p_satellite"):
        if prob_key in raw:
            v = raw[prob_key]
            if isinstance(v, (int, float)) and not (0.5 <= v < 1.0):
                errors.append(
                    f"{path}: '{prob_key}' = {v} out of expected range [0.5, 1.0)"
                )

    if "kelly_fraction" in raw:
        kf = raw["kelly_fraction"]
        if isinstance(kf, (int, float)) and not (0 < kf <= 0.5):
            errors.append(
                f"{path}: 'kelly_fraction' = {kf} out of expected range (0, 0.5]"
            )

    if "max_risk_per_trade_pct" in raw:
        mr = raw["max_risk_per_trade_pct"]
        if isinstance(mr, (int, float)) and not (0 < mr <= 100):
            errors.append(
                f"{path}: 'max_risk_per_trade_pct' = {mr} out of expected range (0, 100]"
            )

    return errors


def _validate_catalog_profiles(catalog: Dict[str, Any]) -> List[str]:
    """Validate that every enabled profile in the catalog is registered.

    Returns a list of error strings (empty = no problems).
    """
    errors: List[str] = []
    for profile_name in catalog.get("enabled_profiles", []):
        if not isinstance(profile_name, str) or not profile_name.strip():
            errors.append(
                f"strategy_catalog.yaml: enabled profile {profile_name!r} "
                f"is not a valid non-empty string"
            )
            continue
        if profile_name not in STRATEGY_REGISTRY:
            errors.append(
                f"strategy_catalog.yaml: enabled profile '{profile_name}' "
                f"is not registered in STRATEGY_REGISTRY "
                f"(known: {sorted(STRATEGY_REGISTRY)})"
            )
    return errors


# ── Public validation entrypoint ───────────────────────────────────────────


def validate_all_strategy_configs(
    conservative_yaml_path: Optional[str] = None,
    catalog_path: Optional[str] = None,
) -> None:
    """Validate all strategy YAML files against their Python config types.

    Checks performed
    ─────────────────
    1. ``config/strategies/kalshi_crypto_15m_conservative.yaml``
       - All non-metadata keys are fields of ``Conservative15mConfig``.
       - No unknown keys (``extra="forbid"`` equivalent).
       - Critical numeric fields have the expected Python type.
       - Probability and Kelly values are within sane ranges.
       - The ``profile`` key matches the expected value.

    2. ``config/strategy_catalog.yaml``
       - Every profile name in ``trading.strategies.enabled_profiles``
         has a corresponding entry in ``STRATEGY_REGISTRY``.

    Raises
    ──────
    StrategyConfigError
        If any check fails.  The exception message lists every problem
        found (not just the first one) so all issues can be fixed at once.
    """
    errors: List[str] = []

    # 1. Conservative 15m YAML
    cons_path = conservative_yaml_path or os.path.join(
        _STRATEGIES_DIR, "kalshi_crypto_15m_conservative.yaml"
    )
    errors.extend(_validate_conservative_yaml(cons_path))

    # 2. Strategy catalog enabled profiles
    catalog = load_strategy_catalog(catalog_path)
    errors.extend(_validate_catalog_profiles(catalog))

    if errors:
        msg = "Strategy config validation failed:\n" + "\n".join(
            f"  • {e}" for e in errors
        )
        raise StrategyConfigError(msg)

    logger.info(
        "validate_all_strategy_configs: OK — %d profile(s) registered, "
        "%d profile(s) enabled in catalog",
        len(STRATEGY_REGISTRY),
        len(catalog["enabled_profiles"]),
    )
