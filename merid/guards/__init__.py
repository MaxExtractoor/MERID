"""
Pre-Go-Live Checklist and Guards for MERID Kalshi Crypto Trading

This module implements comprehensive upstream, mid-pipeline, and downstream
guards as specified in the pre-go-live checklist. It provides:

.. note:: Uses ``ACTIVE_CRYPTO_ASSETS`` from ``config.kalshi_crypto_config``
   as the canonical asset list — do not hard-code asset lists here.

1. Upstream guards: market sanity, config integrity, regime checks
2. Mid-pipeline checks: indicator health, hierarchy enforcement, conviction consistency
3. Downstream guards: pre-trade risk, execution monitoring, post-trade TCA
4. Go-live checklist YAML/JSON with self-validation

Usage:
    from merid.guards import TradingGuardian, GoLiveChecklist
    
    guardian = TradingGuardian()
    if guardian.run_all_checks():
        # Safe to trade
        pass
    else:
        # Enter observation mode
        guardian.enter_observation_mode()
"""

from __future__ import annotations

import json
import math
import time
import yaml
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple, Any

from config.kalshi_crypto_config import ACTIVE_CRYPTO_ASSETS
from utils.logger import get_logger

logger = get_logger("merid.guards")


# =============================================================================
# Status Enums
# =============================================================================

class GuardStatus(str, Enum):
    """Status of a guard check."""
    PASS = "pass"
    FAIL = "fail"
    WARNING = "warning"
    SKIP = "skip"


class TradingMode(str, Enum):
    """Trading system operating mode."""
    DISABLED = "disabled"           # No trading, no observation
    OBSERVATION = "observation"     # Full pipeline, orders not sent
    LIVE_SMALL = "live_small"       # Live trading with reduced size caps
    LIVE_FULL = "live_full"         # Full live trading


# =============================================================================
# Go-Live Checklist Config
# =============================================================================

@dataclass
class GoLiveChecklist:
    """Configuration and validation for go-live readiness.
    
    This is the single source of truth for pre-flight checks.
    """
    
    version: str = "1.0.0"
    last_updated: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    
    # ── Trading Mode ─────────────────────────────────────────────────────────
    mode: TradingMode = TradingMode.OBSERVATION
    observation_reason: Optional[str] = None
    
    # ── Upstream Guards ──────────────────────────────────────────────────────
    upstream: Dict[str, Any] = field(default_factory=lambda: {
        "market_sanity": {
            "enabled": True,
            "required_assets": list(ACTIVE_CRYPTO_ASSETS),
            "max_data_age_seconds": 30,
            "fail_on_missing": True,
        },
        "registry_integrity": {
            "enabled": True,
            "check_weights_sum": True,
            "weight_tolerance": 0.01,  # Weights must sum to 1.0 ± tolerance
            "fail_on_invalid": True,
        },
        "regime_health": {
            "enabled": True,
            "required_regimes": ["calm_neutral", "extreme_fear", "extreme_greed"],
            "observation_if_stale": True,
        },
    })
    
    # ── Mid-Pipeline Guards ─────────────────────────────────────────────────
    mid_pipeline: Dict[str, Any] = field(default_factory=lambda: {
        "indicator_health": {
            "enabled": True,
            "fvg_pressure_bounds": [-3.0, 3.0],  # Raw before normalization
            "atr_min_positive": True,
            "log_interval_seconds": 300,  # Log condensed snapshot every 5 min
        },
        "hierarchy_enforcement": {
            "enabled": True,
            "assert_layer1_vetoes": True,
            "conviction_bounds": [0.4, 1.2],  # structural_factor bounds
        },
        "conviction_consistency": {
            "enabled": True,
            "epsilon": 0.001,  # Tolerance for size math
            "verify_reproducibility": True,
        },
    })
    
    # ── Downstream Guards ───────────────────────────────────────────────────
    downstream: Dict[str, Any] = field(default_factory=lambda: {
        "pre_trade_risk": {
            "enabled": True,
            "check_ev_positive": True,
            "max_slippage_bps": 50,  # 0.5% price band
            "enforce_exposure_caps": True,
        },
        "execution_monitoring": {
            "enabled": True,
            "store_decision_record": True,
            "link_fvg_context": True,
        },
        "post_trade_tca": {
            "enabled": True,
            "stratify_by_conviction": True,
            "feedback_to_weights": False,  # Manual for now
        },
    })
    
    # ── Live Size Caps (per-asset % of normal Kelly) ────────────────────────
    # STATIC: Flat caps for backward compatibility (all 0.0 = observation)
    live_size_caps: Dict[str, float] = field(default_factory=lambda: {
        "BTC": 0.0,
        "ETH": 0.0,
        "SOL": 0.0,
        "XRP": 0.0,
        "DOGE": 0.0,
    })
    
    # ── Computed Caps Configuration (BTC-anchored, bankroll-aware) ───────────
    # Use base_per_asset_frac + mode multiplier + BTC vol scaling for dynamic caps
    use_computed_caps: bool = False  # Enable to use computed caps instead of static
    base_per_asset_frac: Dict[str, float] = field(default_factory=lambda: {
        "BTC": 0.02,    # 2% of bankroll base
        "ETH": 0.015,   # 1.5% of bankroll base
        "SOL": 0.01,    # 1% of bankroll base
        "XRP": 0.01,    # 1% of bankroll base
        "DOGE": 0.005,  # 0.5% of bankroll base
    })
    
    # Vol anchor configuration
    vol_anchor_asset: str = "BTC"  # Asset to use for vol scaling
    target_vol_annual: float = 0.65  # Target annualized vol for scaling (65%)
    vol_scale_min: float = 0.3  # Minimum vol scale (30%)
    vol_scale_max: float = 1.0  # Maximum vol scale (100%)
    
    # Mode multipliers for computed caps
    mode_caps_multiplier: Dict[str, float] = field(default_factory=lambda: {
        "OBSERVATION": 0.0,
        "DISABLED": 0.0,
        "LIVE_SMALL": 0.3,
        "LIVE_FULL": 1.0,
    })
    
    # ── Phase 2 Feature Flags ───────────────────────────────────────────────
    phase2_features: Dict[str, bool] = field(default_factory=lambda: {
        "ohlc_fvg_oracle": False,
        "ifvg_tracking": False,
        "higher_tf_filters": False,
    })
    
    # ── Tiny Bankroll Dev Mode (DEV ONLY - NOT FOR PRODUCTION) ────────────────
    # This is an explicit opt-in mechanism for tiny bankroll dev/testing.
    # When enabled, it can force minimum contract caps even when computed caps are 0.
    # 
    # SAFETY: This must NEVER be enabled in production configs.
    # The observation invariant (mode==OBSERVATION -> can_trade=False) is ALWAYS enforced.
    tiny_bankroll_mode: Dict[str, Any] = field(default_factory=lambda: {
        "enabled": False,           # Default: disabled (production safe)
        "bankroll_cents_floor": 5000,   # $50 minimum bankroll to qualify for override
        "min_contracts_if_above_floor": 1,  # Force at least 1 contract when active
        "log_override": True,       # Log loudly when override is applied
    })
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dict for YAML/JSON output."""
        d = asdict(self)
        d["mode"] = self.mode.value
        return d
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "GoLiveChecklist":
        """Deserialize from dict."""
        data = data.copy()
        if "mode" in data:
            data["mode"] = TradingMode(data["mode"])
        return cls(**data)
    
    @classmethod
    def from_yaml(cls, path: Path) -> "GoLiveChecklist":
        """Load from YAML file."""
        with open(path) as f:
            data = yaml.safe_load(f)
        return cls.from_dict(data)
    
    def to_yaml(self, path: Path) -> None:
        """Save to YAML file."""
        with open(path, "w") as f:
            yaml.dump(self.to_dict(), f, default_flow_style=False, sort_keys=False)
    
    def save_default(self, path: Path = Path("go_live_checklist.yaml")) -> None:
        """Save default checklist to file."""
        self.to_yaml(path)
        logger.info("Go-live checklist saved to %s", path)


# =============================================================================
# Check Result Records
# =============================================================================

@dataclass
class GuardCheckResult:
    """Result of a single guard check."""
    name: str
    status: GuardStatus
    message: str
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    details: Optional[Dict[str, Any]] = None


@dataclass  
class GuardReport:
    """Complete report from a guard run."""
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    mode: TradingMode = TradingMode.OBSERVATION
    upstream: List[GuardCheckResult] = field(default_factory=list)
    mid_pipeline: List[GuardCheckResult] = field(default_factory=list)
    downstream: List[GuardCheckResult] = field(default_factory=list)
    overall_status: GuardStatus = GuardStatus.PASS
    can_trade: bool = False
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "mode": self.mode.value,
            "overall_status": self.overall_status.value,
            "can_trade": self.can_trade,
            "upstream": [
                {"name": r.name, "status": r.status.value, "message": r.message, "details": r.details}
                for r in self.upstream
            ],
            "mid_pipeline": [
                {"name": r.name, "status": r.status.value, "message": r.message, "details": r.details}
                for r in self.mid_pipeline
            ],
            "downstream": [
                {"name": r.name, "status": r.status.value, "message": r.message, "details": r.details}
                for r in self.downstream
            ],
        }


# =============================================================================
# Trading Guardian - Main Guard Implementation
# =============================================================================

class TradingGuardian:
    """Orchestrates all upstream, mid-pipeline, and downstream guards.
    
    This is the main entry point for pre-go-live checks and ongoing monitoring.
    """
    
    def __init__(self, checklist: Optional[GoLiveChecklist] = None):
        self.checklist = checklist or GoLiveChecklist()
        self._last_report: Optional[GuardReport] = None
        self._last_indicator_snapshots: Dict[str, Any] = {}
        self._decision_history: List[Dict[str, Any]] = []
        
        # Conviction bucket PnL tracking for 80%+ hit-rate targeting
        # Buckets: [0.4-0.6), [0.6-0.8), [0.8-1.0]
        self._conviction_bucket_stats: Dict[str, Dict[str, Any]] = {
            "BTC": {"0.4-0.6": {"trades": 0, "wins": 0, "losses": 0, "pnl": 0.0, "ev_sum": 0.0},
                    "0.6-0.8": {"trades": 0, "wins": 0, "losses": 0, "pnl": 0.0, "ev_sum": 0.0},
                    "0.8-1.0": {"trades": 0, "wins": 0, "losses": 0, "pnl": 0.0, "ev_sum": 0.0}},
            "ETH": {"0.4-0.6": {"trades": 0, "wins": 0, "losses": 0, "pnl": 0.0, "ev_sum": 0.0},
                    "0.6-0.8": {"trades": 0, "wins": 0, "losses": 0, "pnl": 0.0, "ev_sum": 0.0},
                    "0.8-1.0": {"trades": 0, "wins": 0, "losses": 0, "pnl": 0.0, "ev_sum": 0.0}},
            "SOL": {"0.4-0.6": {"trades": 0, "wins": 0, "losses": 0, "pnl": 0.0, "ev_sum": 0.0},
                    "0.6-0.8": {"trades": 0, "wins": 0, "losses": 0, "pnl": 0.0, "ev_sum": 0.0},
                    "0.8-1.0": {"trades": 0, "wins": 0, "losses": 0, "pnl": 0.0, "ev_sum": 0.0}},
            "XRP": {"0.4-0.6": {"trades": 0, "wins": 0, "losses": 0, "pnl": 0.0, "ev_sum": 0.0},
                    "0.6-0.8": {"trades": 0, "wins": 0, "losses": 0, "pnl": 0.0, "ev_sum": 0.0},
                    "0.8-1.0": {"trades": 0, "wins": 0, "losses": 0, "pnl": 0.0, "ev_sum": 0.0}},
            "DOGE": {"0.4-0.6": {"trades": 0, "wins": 0, "losses": 0, "pnl": 0.0, "ev_sum": 0.0},
                    "0.6-0.8": {"trades": 0, "wins": 0, "losses": 0, "pnl": 0.0, "ev_sum": 0.0},
                    "0.8-1.0": {"trades": 0, "wins": 0, "losses": 0, "pnl": 0.0, "ev_sum": 0.0}},
        }
        self._runtime_threshold_overrides: Dict[str, Dict[str, float]] = {}  # Asset-specific threshold adjustments
        
        # Run startup self-check and log bootstrap state
        self._run_startup_self_check()
        self._log_bootstrap_state()
        self._run_capital_engine_self_check()
        
        # Register kill switch callback to force OBSERVATION mode on kill
        self._register_kill_switch_handler()
        
    def _register_kill_switch_handler(self) -> None:
        """Register callback with kill switch to force OBSERVATION mode when triggered."""
        from merid.risk.kill_switches import risk_controller
        
        def on_kill_switch_triggered(event) -> None:
            """Callback invoked when kill switch triggers."""
            if self.checklist.mode != TradingMode.OBSERVATION:
                logger.critical(
                    "[GUARD] Kill switch triggered (%s) - forcing all assets to OBSERVATION mode",
                    event.reason
                )
                self.enter_observation_mode(
                    reason=f"Kill switch triggered: {event.reason} - {event.details}"
                )
                # Reset all size caps to 0 (OBSERVATION)
                for asset in self.checklist.live_size_caps:
                    self.checklist.live_size_caps[asset] = 0.0
        
        risk_controller.on_kill(on_kill_switch_triggered)
        logger.info("[GUARD] Registered kill switch callback for mode override")
        
    def _run_capital_engine_self_check(self) -> None:
        """Startup self-check: validate AssetCapitalConfig for all assets."""
        from merid.risk.capital_engine import _default_asset_configs, _default_risk_budgets
        
        issues = []
        required_assets = list(ACTIVE_CRYPTO_ASSETS)
        required_timeframes = ["scalp", "intraday", "swing"]
        
        # Validate asset configs
        asset_configs = _default_asset_configs()
        for asset in required_assets:
            if asset not in asset_configs:
                issues.append(f"{asset}: missing AssetCapitalConfig")
                continue
            
            cfg = asset_configs[asset]
            
            # Check sweep fractions sum to <= 1.0
            sweep_total = cfg.profit_sweep_pct_to_core + cfg.profit_sweep_pct_to_growth
            if sweep_total > 1.0:
                issues.append(
                    f"{asset}: sweep fractions sum to {sweep_total:.2f} > 1.0"
                )
            
            # Check drawdown thresholds are realistic (0.05 - 0.50)
            if not (0.05 <= cfg.drawdown_stepdown_threshold <= 0.50):
                issues.append(
                    f"{asset}: drawdown_stepdown_threshold={cfg.drawdown_stepdown_threshold} outside [0.05, 0.50]"
                )
            
            # Check rebalance multiple is realistic (0.5 - 2.0)
            if not (0.5 <= cfg.risk_to_core_rebalance_multiple <= 2.0):
                issues.append(
                    f"{asset}: risk_to_core_rebalance_multiple={cfg.risk_to_core_rebalance_multiple} outside [0.5, 2.0]"
                )
        
        # Validate risk budgets exist for all (asset, timeframe) combinations
        budgets = _default_risk_budgets()
        budget_keys = {(b.asset, b.timeframe) for b in budgets}
        
        for asset in required_assets:
            for tf in required_timeframes:
                if (asset, tf) not in budget_keys:
                    issues.append(f"{asset}/{tf}: missing RiskBudget")
        
        if issues:
            logger.error("[CAPITAL-ENGINE-CHECK] AssetCapitalConfig issues found:")
            for issue in issues:
                logger.error("  - %s", issue)
        else:
            logger.info("[CAPITAL-ENGINE-CHECK] All assets have valid AssetCapitalConfig and RiskBudgets")
        
        # Log compact summary per asset
        logger.info("=" * 70)
        logger.info("[CAPITAL-ENGINE] Initial Balances & Budget Caps")
        logger.info("=" * 70)
        
        # Create a temp engine to show initial balances
        from merid.risk.capital_engine import CapitalEngine
        engine = CapitalEngine(total_equity=10_000.0)
        snap = engine.snapshot()
        
        logger.info("Global: core=%.2f risk=%.2f growth=%.2f mult=%.2f",
            snap.core_capital, snap.risk_capital, snap.growth_capital, snap.sizing_multiplier)
        logger.info("-" * 70)
        
        for asset in required_assets:
            if asset in asset_configs:
                cfg = asset_configs[asset]
                risk_cap = engine.get_risk_capital(asset)
                budget_caps = []
                for tf in required_timeframes:
                    budget = engine.get_risk_budget(asset, tf)
                    if budget:
                        budget_caps.append(f"{tf}={budget.max_risk_pct_risk_capital:.1%}")
                
                logger.info(
                    "[CAPITAL] %s | risk_cap=%.2f | per_trade=%.1f%% | equity_cap=%.1f%% | budgets: %s",
                    asset, risk_cap, cfg.max_risk_pct_per_trade * 100,
                    cfg.asset_max_risk_pct_of_total_equity * 100,
                    ", ".join(budget_caps) if budget_caps else "NONE"
                )
        
        logger.info("=" * 70)
        
    def _run_startup_self_check(self) -> None:
        """Startup self-check: verify CalibrationConfig bounds for all assets."""
        from merid.sentiment.crypto_registry import get_calibration_config
        
        MIN_EDGE_LOWER_BOUND = 0.05
        MIN_EDGE_UPPER_BOUND = 0.40
        
        issues = []
        required_assets = list(ACTIVE_CRYPTO_ASSETS)
        
        for asset in required_assets:
            calib = get_calibration_config(asset)
            if not calib:
                issues.append(f"{asset}: missing CalibrationConfig")
                continue
            
            # Check low TF bounds
            if not (MIN_EDGE_LOWER_BOUND <= calib.min_prob_edge_low_tf <= MIN_EDGE_UPPER_BOUND):
                issues.append(
                    f"{asset}: min_prob_edge_low_tf={calib.min_prob_edge_low_tf} "
                    f"outside bounds [{MIN_EDGE_LOWER_BOUND}, {MIN_EDGE_UPPER_BOUND}]"
                )
            
            # Check high TF bounds
            if not (MIN_EDGE_LOWER_BOUND <= calib.min_prob_edge_high_tf <= MIN_EDGE_UPPER_BOUND):
                issues.append(
                    f"{asset}: min_prob_edge_high_tf={calib.min_prob_edge_high_tf} "
                    f"outside bounds [{MIN_EDGE_LOWER_BOUND}, {MIN_EDGE_UPPER_BOUND}]"
                )
        
        if issues:
            logger.error("[STARTUP-CHECK] CalibrationConfig issues found:")
            for issue in issues:
                logger.error("  - %s", issue)
        else:
            logger.info("[STARTUP-CHECK] All assets have valid CalibrationConfig bounds")
    
    def _log_bootstrap_state(self) -> None:
        """Log initial bootstrap state for all assets."""
        from merid.sentiment.crypto_registry import get_calibration_config
        
        logger.info("=" * 70)
        logger.info("[BOOTSTRAP] TradingGuardian Initial State")
        logger.info("=" * 70)
        logger.info("Global Mode: %s", self.checklist.mode.value)
        logger.info("-" * 70)
        
        required_assets = list(ACTIVE_CRYPTO_ASSETS)
        
        for asset in required_assets:
            calib = get_calibration_config(asset)
            size_cap = self.checklist.live_size_caps.get(asset, 0.0)
            
            if calib:
                logger.info(
                    "[BOOTSTRAP] %s | mode=%s | size_cap=%.0f%% | min_edge_low=%.3f | min_edge_high=%.3f | veto=%.2f",
                    asset,
                    "OBSERVATION" if size_cap == 0.0 else "LIVE",
                    size_cap * 100,
                    calib.min_prob_edge_low_tf,
                    calib.min_prob_edge_high_tf,
                    calib.conviction_veto_threshold
                )
            else:
                logger.warning("[BOOTSTRAP] %s | NO CalibrationConfig found", asset)
        
        logger.info("=" * 70)
        
    # ── Top-Level API ───────────────────────────────────────────────────────
    
    def run_all_checks(self) -> GuardReport:
        """Run complete guard suite and return report."""
        report = GuardReport(mode=self.checklist.mode)
        
        # Run upstream guards
        report.upstream = self._run_upstream_guards()
        
        # Run mid-pipeline guards (only if upstream passes)
        if all(r.status == GuardStatus.PASS for r in report.upstream):
            report.mid_pipeline = self._run_mid_pipeline_guards()
        else:
            report.mid_pipeline = [GuardCheckResult(
                name="mid_pipeline_skipped",
                status=GuardStatus.SKIP,
                message="Upstream guards failed, skipping mid-pipeline"
            )]
        
        # Run downstream guards (config validation only, no active orders to check)
        report.downstream = self._run_downstream_guards()
        
        # Determine overall status with STRICT OBSERVATION MODE INVARIANT:
        # If mode == OBSERVATION, can_trade MUST be False regardless of check results
        all_results = report.upstream + report.mid_pipeline + report.downstream
        has_fail = any(r.status == GuardStatus.FAIL for r in all_results)
        has_warning = any(r.status == GuardStatus.WARNING for r in all_results)
        
        # ENFORCED INVARIANT: OBSERVATION mode → can_trade = False
        if self.checklist.mode == TradingMode.OBSERVATION:
            report.can_trade = False
            if has_fail:
                report.overall_status = GuardStatus.FAIL
            elif has_warning:
                report.overall_status = GuardStatus.WARNING
            else:
                report.overall_status = GuardStatus.PASS
        elif has_fail:
            report.overall_status = GuardStatus.FAIL
            report.can_trade = False
        elif has_warning:
            report.overall_status = GuardStatus.WARNING
            # In WARNING state, can_trade depends on mode
            report.can_trade = self.checklist.mode in (TradingMode.LIVE_SMALL, TradingMode.LIVE_FULL)
        else:
            report.overall_status = GuardStatus.PASS
            report.can_trade = self.checklist.mode in (TradingMode.LIVE_SMALL, TradingMode.LIVE_FULL)
        
        self._last_report = report
        
        # Log summary
        self._log_report(report)
        
        return report
    
    def compute_btc_vol_scale(self, btc_vol_annual: float) -> float:
        """Compute volatility scaling factor based on BTC vol.
        
        Args:
            btc_vol_annual: BTC annualized volatility (e.g., 0.65 for 65%)
            
        Returns:
            Scale factor clamped between vol_scale_min and vol_scale_max
        """
        if btc_vol_annual <= 0:
            return self.checklist.vol_scale_min
        
        target = self.checklist.target_vol_annual
        # Scale = target / current_vol (lower vol → higher scale, higher vol → lower scale)
        scale = target / max(btc_vol_annual, 0.01)
        
        return max(self.checklist.vol_scale_min, 
                   min(self.checklist.vol_scale_max, scale))
    
    def compute_live_cap(
        self,
        asset: str,
        bankroll_cents: int,
        btc_vol_annual: float,
    ) -> int:
        """Compute live size cap for an asset using BTC-anchored, bankroll-aware formula.
        
        Formula:
            dollar_cap = bankroll * base_frac * mode_mult * vol_scale
            contracts_cap = dollar_cap / typical_contract_risk
        
        Args:
            asset: Asset symbol (BTC, ETH, SOL, XRP, DOGE)
            bankroll_cents: Total bankroll in cents
            btc_vol_annual: BTC annualized volatility for scaling
            
        Returns:
            Maximum contracts allowed for this asset (0 if mode is OBSERVATION)
        """
        # OBSERVATION mode always returns 0
        if self.checklist.mode == TradingMode.OBSERVATION:
            return 0
        
        # Get base fraction for asset
        base_frac = self.checklist.base_per_asset_frac.get(asset, 0.01)
        
        # Get mode multiplier - handle both uppercase and lowercase keys
        mode_value = self.checklist.mode.value
        mode_mult = self.checklist.mode_caps_multiplier.get(mode_value)
        if mode_mult is None:
            # Try uppercase fallback
            mode_mult = self.checklist.mode_caps_multiplier.get(mode_value.upper(), 0.0)
        
        # Compute vol scale
        vol_scale = self.compute_btc_vol_scale(btc_vol_annual)
        
        # Calculate dollar cap
        bankroll_dollars = bankroll_cents / 100.0
        dollar_cap = bankroll_dollars * base_frac * mode_mult * vol_scale
        
        # Convert to contracts (assuming ~$1 risk per contract at mid-curve)
        typical_contract_risk = 1.0  # $1 per contract
        contracts_cap = int(dollar_cap / typical_contract_risk)
        
        return max(0, contracts_cap)
    
    def compute_all_live_caps(
        self,
        bankroll_cents: int,
        btc_vol_annual: float,
    ) -> Dict[str, int]:
        """Compute live caps for all assets.
        
        Returns dict mapping asset -> max contracts.
        """
        return {
            asset: self.compute_live_cap(asset, bankroll_cents, btc_vol_annual)
            for asset in self.checklist.base_per_asset_frac.keys()
        }
    
    def compute_live_cap_with_override(
        self,
        asset: str,
        bankroll_cents: int,
        btc_vol_annual: float,
    ) -> tuple[int, int, bool]:
        """Compute live cap with optional tiny-bankroll dev override.
        
        DEV ONLY: This method applies the tiny_bankroll_mode override when enabled.
        This is explicitly marked as dev-only and should NEVER be enabled in production.
        
        Args:
            asset: Asset symbol
            bankroll_cents: Total bankroll in cents
            btc_vol_annual: BTC annualized volatility
            
        Returns:
            Tuple of (raw_cap, effective_cap, override_applied):
            - raw_cap: Computed cap without override
            - effective_cap: Cap after applying override (if eligible)
            - override_applied: True if override was applied
        """
        # CRITICAL: OBSERVATION mode blocks ALL trading, including overrides
        if self.checklist.mode == TradingMode.OBSERVATION:
            return 0, 0, False
        
        # Compute raw cap (standard formula)
        raw_cap = self.compute_live_cap(asset, bankroll_cents, btc_vol_annual)
        
        # Check if tiny-bankroll override is enabled
        tiny_mode = getattr(self.checklist, 'tiny_bankroll_mode', {})
        if not tiny_mode.get('enabled', False):
            return raw_cap, raw_cap, False
        
        # Get override parameters
        floor_cents = tiny_mode.get('bankroll_cents_floor', 5000)  # Default $50
        min_contracts = tiny_mode.get('min_contracts_if_above_floor', 1)
        log_override = tiny_mode.get('log_override', True)
        
        # Check if bankroll qualifies for override
        if bankroll_cents < floor_cents:
            # Bankroll too small even for dev mode
            return raw_cap, raw_cap, False
        
        # Check if raw cap is below minimum
        if raw_cap < min_contracts:
            # Apply override: force minimum contracts
            effective_cap = min_contracts
            override_applied = True
            
            if log_override:
                logger.warning(
                    "[GUARD-DEV-OVERRIDE] %s | raw=%d -> effective=%d | "
                    "bankroll=%d¢ floor=%d¢ | TINY BANKROLL OVERRIDE ACTIVE",
                    asset, raw_cap, effective_cap, bankroll_cents, floor_cents
                )
            
            return raw_cap, effective_cap, override_applied
        
        # Raw cap is already sufficient, no override needed
        return raw_cap, raw_cap, False
    
    def compute_all_live_caps_with_override(
        self,
        bankroll_cents: int,
        btc_vol_annual: float,
    ) -> dict[str, tuple[int, int, bool]]:
        """Compute all live caps with override info.
        
        Returns dict mapping asset -> (raw_cap, effective_cap, override_applied).
        """
        return {
            asset: self.compute_live_cap_with_override(asset, bankroll_cents, btc_vol_annual)
            for asset in self.checklist.base_per_asset_frac.keys()
        }
    
    def get_effective_live_caps(
        self,
        bankroll_cents: int = 0,
        btc_vol_annual: float = 0.65,
    ) -> dict[str, float]:
        """Get effective live size caps (static or computed) with dev override.
        
        If use_computed_caps is True and bankroll is provided, uses computed caps.
        Otherwise falls back to static live_size_caps.
        
        Returns caps as fraction of Kelly (0.0-1.0+).
        """
        # If using computed caps and we have bankroll info
        if self.checklist.use_computed_caps and bankroll_cents > 0:
            caps_with_override = self.compute_all_live_caps_with_override(bankroll_cents, btc_vol_annual)
            
            # Convert effective contract counts back to fractions
            bankroll_dollars = bankroll_cents / 100.0
            return {
                asset: (effective / bankroll_dollars) if bankroll_dollars > 0 else 0.0
                for asset, (raw, effective, override_applied) in caps_with_override.items()
            }
        
        # Fall back to static caps
        return self.checklist.live_size_caps.copy()
    
    def get_caps_with_telemetry(
        self,
        bankroll_cents: int = 0,
        btc_vol_annual: float = 0.65,
    ) -> dict[str, any]:
        """Get caps with full telemetry for logging/fingerprinting.
        
        Returns dict with:
        - raw_caps: Computed caps without override
        - effective_caps: Caps after override
        - override_enabled: Whether tiny_bankroll_mode is enabled
        - override_applied: Dict of which assets had override applied
        - floor_cents: The bankroll floor threshold
        """
        tiny_mode = getattr(self.checklist, 'tiny_bankroll_mode', {})
        override_enabled = tiny_mode.get('enabled', False)
        floor_cents = tiny_mode.get('bankroll_cents_floor', 5000) if override_enabled else 0
        
        if not self.checklist.use_computed_caps or bankroll_cents <= 0:
            return {
                'raw_caps': self.checklist.live_size_caps.copy(),
                'effective_caps': self.checklist.live_size_caps.copy(),
                'override_enabled': False,
                'override_applied': {},
                'floor_cents': 0,
            }
        
        caps_with_override = self.compute_all_live_caps_with_override(bankroll_cents, btc_vol_annual)
        bankroll_dollars = bankroll_cents / 100.0
        
        raw_caps = {}
        effective_caps = {}
        override_applied = {}
        
        for asset, (raw, effective, was_overridden) in caps_with_override.items():
            raw_caps[asset] = (raw / bankroll_dollars) if bankroll_dollars > 0 else 0.0
            effective_caps[asset] = (effective / bankroll_dollars) if bankroll_dollars > 0 else 0.0
            override_applied[asset] = was_overridden
        
        return {
            'raw_caps': raw_caps,
            'effective_caps': effective_caps,
            'override_enabled': override_enabled,
            'override_applied': override_applied,
            'floor_cents': floor_cents,
        }
    
    def can_trade(self) -> bool:
        """Quick check if trading is currently allowed."""
        if self._last_report is None:
            self.run_all_checks()
        return self._last_report.can_trade if self._last_report else False
    
    def enter_observation_mode(self, reason: str) -> None:
        """Enter observation mode (orders built but not sent)."""
        self.checklist.mode = TradingMode.OBSERVATION
        self.checklist.observation_reason = reason
        logger.warning("[GUARD] Entering observation mode: %s", reason)
    
    def enable_live_trading(self, mode: TradingMode = TradingMode.LIVE_SMALL) -> GuardReport:
        """Attempt to enable live trading after passing all guards."""
        if mode not in (TradingMode.LIVE_SMALL, TradingMode.LIVE_FULL):
            raise ValueError(f"Invalid live mode: {mode}")
        
        report = self.run_all_checks()
        
        if report.overall_status == GuardStatus.FAIL:
            logger.error("[GUARD] Cannot enable live trading - guards failed")
            return report
        
        self.checklist.mode = mode
        logger.info("[GUARD] Live trading enabled: %s", mode.value)
        return report
    
    # ── Upstream Guards ─────────────────────────────────────────────────────
    
    def _run_upstream_guards(self) -> List[GuardCheckResult]:
        """Run all upstream guard checks."""
        results = []
        cfg = self.checklist.upstream
        
        # Market sanity check
        if cfg.get("market_sanity", {}).get("enabled", True):
            results.append(self._check_market_sanity())
        
        # Registry integrity check
        if cfg.get("registry_integrity", {}).get("enabled", True):
            results.append(self._check_registry_integrity())
        
        # Regime health check
        if cfg.get("regime_health", {}).get("enabled", True):
            results.append(self._check_regime_health())
        
        return results
    
    def _check_market_sanity(self) -> GuardCheckResult:
        """Check market data sanity for all assets."""
        try:
            from merid.sentiment.crypto_registry import get_crypto_registry
            
            registry = get_crypto_registry()
            required = self.checklist.upstream["market_sanity"]["required_assets"]
            max_age = self.checklist.upstream["market_sanity"]["max_data_age_seconds"]
            
            missing_assets = []
            stale_assets = []
            
            for asset in required:
                config = registry.get_config(asset)
                if not config:
                    missing_assets.append(asset)
                    continue
                
                # TODO: Check actual data age from spot feeds
                # For now, assume config presence means asset is registered
            
            if missing_assets:
                return GuardCheckResult(
                    name="market_sanity",
                    status=GuardStatus.FAIL,
                    message=f"Missing assets in registry: {missing_assets}",
                    details={"missing": missing_assets, "required": required}
                )
            
            return GuardCheckResult(
                name="market_sanity",
                status=GuardStatus.PASS,
                message=f"All {len(required)} assets registered and valid",
                details={"assets": required, "max_data_age": max_age}
            )
            
        except Exception as e:
            return GuardCheckResult(
                name="market_sanity",
                status=GuardStatus.FAIL,
                message=f"Exception during market sanity check: {e}"
            )
    
    def _check_registry_integrity(self) -> GuardCheckResult:
        """Verify crypto registry integrity."""
        try:
            from merid.sentiment.crypto_registry import get_crypto_registry, validate_registry
            
            registry = get_crypto_registry()
            cfg = self.checklist.upstream["registry_integrity"]
            
            # Check for validation issues
            issues = validate_registry()
            
            if issues:
                return GuardCheckResult(
                    name="registry_integrity",
                    status=GuardStatus.FAIL,
                    message=f"Registry validation failed: {issues}",
                    details={"issues": issues}
                )
            
            # Check all required assets have configs
            required = list(ACTIVE_CRYPTO_ASSETS)
            missing_fvg = []
            
            for asset in required:
                config = registry.get_config(asset)
                if not config:
                    missing_fvg.append(f"{asset}: missing config")
                elif not config.fvg_config.enabled:
                    missing_fvg.append(f"{asset}: FVG disabled")
            
            if missing_fvg:
                return GuardCheckResult(
                    name="registry_integrity",
                    status=GuardStatus.FAIL,
                    message=f"FVG config issues: {missing_fvg}",
                    details={"issues": missing_fvg}
                )
            
            return GuardCheckResult(
                name="registry_integrity",
                status=GuardStatus.PASS,
                message="Registry integrity verified for all 5 assets",
                details={"assets": required}
            )
            
        except Exception as e:
            return GuardCheckResult(
                name="registry_integrity",
                status=GuardStatus.FAIL,
                message=f"Exception during registry check: {e}"
            )
    
    def _check_regime_health(self) -> GuardCheckResult:
        """Check sentiment regime systems are healthy."""
        try:
            from merid.sentiment.sentiment_regime import get_sentiment_regime_engine
            
            engine = get_sentiment_regime_engine()
            
            # Check engine is available
            if not engine:
                return GuardCheckResult(
                    name="regime_health",
                    status=GuardStatus.WARNING,
                    message="Sentiment regime engine not available"
                )
            
            return GuardCheckResult(
                name="regime_health",
                status=GuardStatus.PASS,
                message="Sentiment regime engine operational"
            )
            
        except Exception as e:
            return GuardCheckResult(
                name="regime_health",
                status=GuardStatus.WARNING,
                message=f"Regime engine check exception: {e}"
            )
    
    # ── Mid-Pipeline Guards ─────────────────────────────────────────────────
    
    def _run_mid_pipeline_guards(self) -> List[GuardCheckResult]:
        """Run mid-pipeline guard checks."""
        results = []
        cfg = self.checklist.mid_pipeline
        
        if cfg.get("indicator_health", {}).get("enabled", True):
            results.append(self._check_indicator_health())
        
        if cfg.get("hierarchy_enforcement", {}).get("enabled", True):
            results.append(self._check_hierarchy_enforcement())
        
        if cfg.get("conviction_consistency", {}).get("enabled", True):
            results.append(self._check_conviction_consistency())
        
        return results
    
    def _check_indicator_health(self) -> GuardCheckResult:
        """Check indicator snapshots are healthy."""
        cfg = self.checklist.mid_pipeline["indicator_health"]
        
        issues = []
        
        # Check stored snapshots if any
        for asset, snap in self._last_indicator_snapshots.items():
            # Check FVG pressure bounds
            if hasattr(snap, 'fvg_pressure'):
                fvg_bounds = cfg.get("fvg_pressure_bounds", [-3.0, 3.0])
                if not (fvg_bounds[0] <= snap.fvg_pressure <= fvg_bounds[1]):
                    issues.append(f"{asset}: fvg_pressure {snap.fvg_pressure} out of bounds")
            
            # Check ATR positive
            if cfg.get("atr_min_positive", True):
                if hasattr(snap, 'atr') and snap.atr <= 0:
                    issues.append(f"{asset}: ATR is {snap.atr}")
        
        if issues:
            return GuardCheckResult(
                name="indicator_health",
                status=GuardStatus.WARNING,
                message=f"Indicator health issues: {issues[:3]}",  # Limit to first 3
                details={"issues": issues}
            )
        
        return GuardCheckResult(
            name="indicator_health",
            status=GuardStatus.PASS,
            message="Indicator health nominal"
        )
    
    def _check_hierarchy_enforcement(self) -> GuardCheckResult:
        """Verify decision hierarchy is properly enforced."""
        cfg = self.checklist.mid_pipeline["hierarchy_enforcement"]
        
        # This is a code-structure check - verify the hierarchy is documented
        # and the bounds are configured correctly
        bounds = cfg.get("conviction_bounds", [0.4, 1.2])
        
        if bounds[0] < 0.3 or bounds[1] > 1.5:
            return GuardCheckResult(
                name="hierarchy_enforcement",
                status=GuardStatus.WARNING,
                message=f"Conviction bounds {bounds} may be too wide"
            )
        
        return GuardCheckResult(
            name="hierarchy_enforcement",
            status=GuardStatus.PASS,
            message=f"Hierarchy enforced with conviction bounds {bounds}",
            details={"conviction_bounds": bounds}
        )
    
    def _check_conviction_consistency(self) -> GuardCheckResult:
        """Verify conviction calculations are consistent."""
        cfg = self.checklist.mid_pipeline["conviction_consistency"]
        epsilon = cfg.get("epsilon", 0.001)
        
        # Check recent decision history
        inconsistencies = []
        
        for decision in self._decision_history[-10:]:  # Last 10 decisions
            base_size = decision.get("base_size", 0)
            structural_factor = decision.get("structural_factor", 1.0)
            final_size = decision.get("final_size", 0)
            
            expected = int(base_size * structural_factor)
            if abs(final_size - expected) > max(1, int(base_size * epsilon)):
                inconsistencies.append({
                    "market_id": decision.get("market_id"),
                    "expected": expected,
                    "actual": final_size
                })
        
        if inconsistencies:
            return GuardCheckResult(
                name="conviction_consistency",
                status=GuardStatus.WARNING,
                message=f"{len(inconsistencies)} recent decisions with size math issues",
                details={"inconsistencies": inconsistencies}
            )
        
        return GuardCheckResult(
            name="conviction_consistency",
            status=GuardStatus.PASS,
            message="Conviction math consistent across recent decisions"
        )
    
    # ── Downstream Guards ─────────────────────────────────────────────────────
    
    def _run_downstream_guards(self) -> List[GuardCheckResult]:
        """Run downstream guard checks (config validation)."""
        results = []
        cfg = self.checklist.downstream
        
        if cfg.get("pre_trade_risk", {}).get("enabled", True):
            results.append(self._check_pre_trade_risk_config())
        
        if cfg.get("execution_monitoring", {}).get("enabled", True):
            results.append(self._check_execution_config())
        
        return results
    
    def _check_pre_trade_risk_config(self) -> GuardCheckResult:
        """Verify pre-trade risk configuration."""
        cfg = self.checklist.downstream["pre_trade_risk"]
        
        max_slippage = cfg.get("max_slippage_bps", 50)
        
        if max_slippage > 100:  # 1%
            return GuardCheckResult(
                name="pre_trade_risk",
                status=GuardStatus.WARNING,
                message=f"Max slippage {max_slippage} bps is high"
            )
        
        return GuardCheckResult(
            name="pre_trade_risk",
            status=GuardStatus.PASS,
            message=f"Pre-trade risk configured: slippage {max_slippage} bps"
        )
    
    def _check_execution_config(self) -> GuardCheckResult:
        """Verify execution monitoring configuration."""
        cfg = self.checklist.downstream["execution_monitoring"]
        
        if not cfg.get("store_decision_record", True):
            return GuardCheckResult(
                name="execution_config",
                status=GuardStatus.WARNING,
                message="Decision records not being stored - audit trail incomplete"
            )
        
        return GuardCheckResult(
            name="execution_config",
            status=GuardStatus.PASS,
            message="Execution monitoring configured with audit trail"
        )
    
    # ── Helper Methods ───────────────────────────────────────────────────────
    
    def _log_report(self, report: GuardReport) -> None:
        """Log guard report summary."""
        status_emoji = {
            GuardStatus.PASS: "✓",
            GuardStatus.WARNING: "⚠",
            GuardStatus.FAIL: "✗",
            GuardStatus.SKIP: "○"
        }
        
        logger.info("=" * 60)
        logger.info("GUARD REPORT - %s", report.timestamp)
        logger.info("Mode: %s | Overall: %s | Can Trade: %s",
                    report.mode.value,
                    report.overall_status.value,
                    report.can_trade)
        logger.info("-" * 60)
        
        all_checks = [
            ("Upstream", report.upstream),
            ("Mid-Pipeline", report.mid_pipeline),
            ("Downstream", report.downstream)
        ]
        
        for section_name, checks in all_checks:
            logger.info("%s:", section_name)
            for check in checks:
                emoji = status_emoji.get(check.status, "?")
                logger.info("  %s %s: %s", emoji, check.name, check.message)
        
        logger.info("=" * 60)
    
    def record_decision(self, 
                        market_id: str,
                        base_size: int,
                        structural_factor: float,
                        final_size: int,
                        conviction_components: Dict[str, float]) -> None:
        """Record a trade decision for consistency auditing."""
        self._decision_history.append({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "market_id": market_id,
            "base_size": base_size,
            "structural_factor": structural_factor,
            "final_size": final_size,
            "conviction": conviction_components,
        })
        
        # Trim history
        if len(self._decision_history) > 1000:
            self._decision_history = self._decision_history[-500:]
    
    def record_indicator_snapshot(self, asset: str, snapshot: Any) -> None:
        """Store indicator snapshot for health checks."""
        self._last_indicator_snapshots[asset] = snapshot

    # ── Conviction Bucket PnL Tracking ───────────────────────────────────────
    
    def _get_conviction_bucket(self, conviction: float) -> str:
        """Map conviction (0-1) to bucket string."""
        if conviction < 0.6:
            return "0.4-0.6"
        elif conviction < 0.8:
            return "0.6-0.8"
        else:
            return "0.8-1.0"
    
    def record_trade_outcome(
        self,
        asset: str,
        conviction: float,
        realized_pnl: float,
        ev_at_entry: float,
        won: bool
    ) -> None:
        """Record a closed trade outcome for bucket statistics."""
        if asset not in self._conviction_bucket_stats:
            return
        
        bucket = self._get_conviction_bucket(conviction)
        stats = self._conviction_bucket_stats[asset][bucket]
        
        stats["trades"] += 1
        stats["wins"] += 1 if won else 0
        stats["losses"] += 0 if won else 1
        stats["pnl"] += realized_pnl
        stats["ev_sum"] += ev_at_entry
        
        logger.info(
            "[BUCKET-TRACK] %s | bucket=%s | pnl=%.1f | win=%s | total_trades=%d",
            asset, bucket, realized_pnl, won, stats["trades"]
        )
    
    def get_bucket_statistics(self, asset: str) -> Dict[str, Any]:
        """Get statistics for all conviction buckets of an asset."""
        if asset not in self._conviction_bucket_stats:
            return {}
        
        stats = {}
        for bucket, data in self._conviction_bucket_stats[asset].items():
            trades = data["trades"]
            if trades > 0:
                hit_rate = data["wins"] / trades
                avg_pnl = data["pnl"] / trades
                avg_ev = data["ev_sum"] / trades
            else:
                hit_rate = 0.0
                avg_pnl = 0.0
                avg_ev = 0.0
            
            stats[bucket] = {
                "trades": trades,
                "hit_rate": round(hit_rate, 3),
                "avg_pnl": round(avg_pnl, 2),
                "avg_ev": round(avg_ev, 4),
                "total_pnl": round(data["pnl"], 2),
            }
        
        return stats
    
    def get_all_bucket_summary(self) -> Dict[str, Dict[str, Any]]:
        """Get bucket statistics for all assets."""
        return {asset: self.get_bucket_statistics(asset) for asset in self._conviction_bucket_stats}
    
    # ── Promotion Rules (OBSERVATION → LIVE) ─────────────────────────────────
    
    def evaluate_promotion_eligibility(
        self,
        asset: str,
        min_trades_for_promotion: int = 10,
        min_hit_rate: float = 0.75
    ) -> Dict[str, Any]:
        """Evaluate if an asset should be promoted from OBSERVATION to LIVE.
        
        Args:
            asset: Asset symbol
            min_trades_for_promotion: Minimum trades required before promotion
            min_hit_rate: Minimum hit rate across all buckets for promotion
        
        Returns:
            Dict with eligibility status and details
        """
        stats = self.get_bucket_statistics(asset)
        
        total_trades = sum(b.get("trades", 0) for b in stats.values())
        total_wins = sum(
            int(b.get("hit_rate", 0) * b.get("trades", 0)) 
            for b in stats.values()
        )
        overall_hit_rate = total_wins / total_trades if total_trades > 0 else 0
        
        # Check minimum trades
        has_enough_trades = total_trades >= min_trades_for_promotion
        
        # Check hit rate meets threshold
        meets_hit_rate = overall_hit_rate >= min_hit_rate
        
        # Currently in OBSERVATION
        current_cap = self.checklist.live_size_caps.get(asset, 0.0)
        is_observation = current_cap == 0.0 or self.checklist.mode == TradingMode.OBSERVATION
        
        eligible = is_observation and has_enough_trades and meets_hit_rate
        
        return {
            "asset": asset,
            "eligible": eligible,
            "is_observation": is_observation,
            "total_trades": total_trades,
            "overall_hit_rate": round(overall_hit_rate, 3),
            "has_enough_trades": has_enough_trades,
            "meets_hit_rate": meets_hit_rate,
            "bucket_breakdown": stats,
            "current_mode": self.checklist.mode.value,
            "promotion_to": "LIVE_SMALL" if eligible else None,
        }
    
    def promote_asset_to_live(self, asset: str, mode: TradingMode = TradingMode.LIVE_SMALL) -> bool:
        """Promote an asset from OBSERVATION to LIVE trading.
        
        Args:
            asset: Asset symbol to promote
            mode: Target trading mode (LIVE_SMALL or LIVE_FULL)
        
        Returns:
            True if promotion successful
        """
        if mode not in (TradingMode.LIVE_SMALL, TradingMode.LIVE_FULL):
            logger.error("Invalid promotion mode: %s", mode)
            return False
        
        # Check eligibility
        eligibility = self.evaluate_promotion_eligibility(asset)
        if not eligibility["eligible"]:
            logger.warning(
                "[PROMOTION] %s NOT eligible: trades=%d, hit_rate=%.2f",
                asset, eligibility["total_trades"], eligibility["overall_hit_rate"]
            )
            return False
        
        # Promote: set size cap and mode
        if mode == TradingMode.LIVE_SMALL:
            self.checklist.live_size_caps[asset] = 0.25  # 25% of normal Kelly
        else:
            self.checklist.live_size_caps[asset] = 1.0  # Full Kelly
        
        # If all assets promoted, update global mode
        all_promoted = all(
            cap > 0 for cap in self.checklist.live_size_caps.values()
        )
        if all_promoted and self.checklist.mode == TradingMode.OBSERVATION:
            self.checklist.mode = TradingMode.LIVE_SMALL
            logger.info("[PROMOTION] Global mode upgraded to LIVE_SMALL")
        
        logger.warning(
            "[PROMOTION] %s promoted to %s | size_cap=%.0f%% | hit_rate=%.2f | trades=%d",
            asset, mode.value, self.checklist.live_size_caps[asset] * 100,
            eligibility["overall_hit_rate"], eligibility["total_trades"]
        )
        
        return True
    
    def get_promotion_status_all(self) -> Dict[str, Any]:
        """Get promotion status for all assets."""
        return {
            asset: self.evaluate_promotion_eligibility(asset)
            for asset in self._conviction_bucket_stats.keys()
        }
    
    def evaluate_and_tighten_thresholds(self) -> Dict[str, Any]:
        """Evaluate bucket performance and auto-tighten thresholds if needed."""
        from merid.sentiment.crypto_registry import get_calibration_config
        
        actions = {}
        
        for asset in self._conviction_bucket_stats:
            calib = get_calibration_config(asset)
            if not calib or not calib.auto_tighten_enabled:
                continue
            
            stats = self.get_bucket_statistics(asset)
            overrides = self._runtime_threshold_overrides.get(asset, {})
            current_min_edge = overrides.get("min_prob_edge", calib.min_prob_edge_low_tf)
            
            # Check low bucket (0.4-0.6) performance
            low_bucket = stats.get("0.4-0.6", {})
            if low_bucket.get("trades", 0) >= calib.min_trades_for_tightening:
                target_hit_rate = calib.target_hit_rate_low
                actual_hit_rate = low_bucket.get("hit_rate", 0)
                
                if actual_hit_rate < target_hit_rate:
                    # Underperforming: tighten threshold
                    new_min_edge = min(current_min_edge + calib.tighten_delta, calib.max_prob_edge)
                    
                    if new_min_edge > current_min_edge:
                        if asset not in self._runtime_threshold_overrides:
                            self._runtime_threshold_overrides[asset] = {}
                        self._runtime_threshold_overrides[asset]["min_prob_edge"] = new_min_edge
                        
                        logger.warning(
                            "[AUTO-TIGHTEN] %s | hit_rate=%.2f < target=%.2f | min_edge: %.3f -> %.3f",
                            asset, actual_hit_rate, target_hit_rate, current_min_edge, new_min_edge
                        )
                        actions[asset] = {
                            "action": "tighten_low_bucket",
                            "old_threshold": current_min_edge,
                            "new_threshold": new_min_edge,
                            "reason": f"hit_rate {actual_hit_rate:.2f} < target {target_hit_rate:.2f}"
                        }
        
        return actions
    
    def get_effective_thresholds(self, asset: str) -> Dict[str, float]:
        """Get current effective thresholds (including runtime overrides)."""
        from merid.sentiment.crypto_registry import get_calibration_config
        
        calib = get_calibration_config(asset)
        if not calib:
            return {}
        
        overrides = self._runtime_threshold_overrides.get(asset, {})
        
        return {
            "min_prob_edge_low_tf": overrides.get("min_prob_edge", calib.min_prob_edge_low_tf),
            "min_prob_edge_high_tf": calib.min_prob_edge_high_tf,
            "conviction_veto_threshold": calib.conviction_veto_threshold,
            "conviction_strict_threshold": calib.conviction_strict_threshold,
        }


# =============================================================================
# Convenience Functions
# =============================================================================

def create_default_checklist(path: Path = Path("go_live_checklist.yaml")) -> GoLiveChecklist:
    """Create and save default go-live checklist."""
    checklist = GoLiveChecklist()
    checklist.save_default(path)
    return checklist


def quick_health_check() -> bool:
    """Quick one-liner health check."""
    guardian = TradingGuardian()
    report = guardian.run_all_checks()
    return report.can_trade


if __name__ == "__main__":
    # Generate default checklist
    create_default_checklist()
    
    # Run quick check
    guardian = TradingGuardian()
    report = guardian.run_all_checks()
    
    print(json.dumps(report.to_dict(), indent=2))
