"""Centralized, immutable per-tick feature snapshot for 15m crypto trading.

The snapshot is built once per loop tick, before agents are evaluated, so that
all five assets share the same time-aligned view of:

- CF Benchmarks RTI values and log returns (1s/3s/10s/30s/60s).
- Top-of-book microstructure (OFI, book imbalance, spread, depth).
- BTC -> alt cross-asset lead-lag from the RTI stream.
- Feature provenance and freshness flags.

The module is intentionally read-only after construction: agents receive the
snapshot and extract their asset's slice.  No per-agent spot fetches or
recomputations are performed inside the evaluation loop.
"""

from __future__ import annotations

import collections
import math
import os
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

from merid.data.cf_rti_adapter import (
    CfbRtiObservation,
    get_live_rti,
    get_rti_return,
)
from merid.prediction.microstructure_features import (
    BookSnapshot,
    SpotHistory,
    compute_microstructure_signals,
    kalshi_state_book_levels,
)


# Default lookbacks for RTI log returns, in seconds.  These are aligned to the
# Kalshi 15m settlement index (CF Benchmarks RTI) so the directional feature is
# priced from the same index that decides the contract.
_RTI_LOOKBACKS_S = (1.0, 3.0, 10.0, 30.0, 60.0)

# Default per-asset order-book history length (used for OFI accumulation).
_BOOK_HISTORY_MAXLEN = int(os.environ.get("MERID_FEATURE_SNAPSHOT_BOOK_HISTORY", "120"))

# BTC spot history window for cross-asset lead-lag.
_BTC_WINDOW_S = float(os.environ.get("MERID_FEATURE_SNAPSHOT_BTC_WINDOW_S", "300.0"))

# Maximum microstructure edge, in percentage points, when computing book pressure.
_MAX_EDGE_PCT = float(os.environ.get("MERID_FEATURE_SNAPSHOT_MAX_EDGE_PCT", "2.0"))

# OFI accumulation window, in seconds.
_OFI_WINDOW_S = float(os.environ.get("MERID_FEATURE_SNAPSHOT_OFI_WINDOW_S", "60.0"))


@dataclass(frozen=True)
class AssetFeatureSlice:
    """Time-aligned features for one asset."""

    asset: str
    rti_value: Optional[float] = None
    rti_source_ts_ms: Optional[int] = None
    rti_observed_ts_ms: Optional[int] = None
    rti_execution_eligible: bool = False
    rti_age_ms: Optional[int] = None
    rti_returns: Dict[str, Optional[float]] = field(default_factory=dict)
    # Microstructure
    book_imbalance_yes: Optional[float] = None
    book_imbalance_no: Optional[float] = None
    ofi_yes: Optional[float] = None
    ofi_no: Optional[float] = None
    spread_yes_cents: Optional[int] = None
    spread_no_cents: Optional[int] = None
    depth_ratio_yes: Optional[float] = None
    depth_ratio_no: Optional[float] = None
    log_depth_imbalance_yes: Optional[float] = None
    log_depth_imbalance_no: Optional[float] = None
    microstructure_yes_features: Optional[Dict[str, Any]] = None
    microstructure_no_features: Optional[Dict[str, Any]] = None
    microstructure_yes_edge_pp: Optional[float] = None
    microstructure_no_edge_pp: Optional[float] = None
    microstructure_book_delta_pp: Optional[float] = None
    microstructure_cross_delta_pp: Optional[float] = None
    microstructure_total_delta_pp: Optional[float] = None
    # Cross-asset BTC lead-lag
    btc_log_return: Optional[float] = None
    # Provenance
    feature_ts: float = 0.0
    feature_age_ms: Optional[float] = None
    feature_valid: bool = False
    missing_reasons: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class FeatureSnapshot:
    """One immutable snapshot shared by all agents in a single loop tick."""

    ts: float
    by_asset: Dict[str, AssetFeatureSlice] = field(default_factory=dict)
    btc_spot_history: Optional[SpotHistory] = None
    source: str = "feature_snapshot"


class FeatureSnapshotBuilder:
    """Builds a centralized ``FeatureSnapshot`` once per loop tick.

    The builder owns the per-asset order-book history and BTC spot history so
    that OFI and cross-asset lead-lag are computed consistently across assets.
    """

    def __init__(
        self,
        assets: Sequence[str],
        market_state_store: Any,
        lookbacks_s: Sequence[float] = _RTI_LOOKBACKS_S,
        book_history_maxlen: int = _BOOK_HISTORY_MAXLEN,
        btc_window_s: float = _BTC_WINDOW_S,
        max_edge_pct: float = _MAX_EDGE_PCT,
        ofi_window_s: float = _OFI_WINDOW_S,
    ) -> None:
        self.assets = list(assets)
        self.market_state_store = market_state_store
        self.lookbacks_s = tuple(lookbacks_s)
        self.book_history_by_asset: Dict[str, collections.deque] = {
            a: collections.deque(maxlen=book_history_maxlen) for a in self.assets
        }
        self.btc_spot_history = SpotHistory(window_s=btc_window_s)
        self.max_edge_pct = max_edge_pct
        self.ofi_window_s = ofi_window_s

    def _find_asset_market_state(self, asset: str) -> Optional[Any]:
        """Return the current market state for ``asset`` if one exists."""
        if self.market_state_store is None:
            return None
        for ms in self.market_state_store.get_all().values():
            underlying = getattr(ms, "underlying", "")
            series = getattr(ms, "series_ticker", "")
            ticker = getattr(ms, "ticker", "")
            if underlying == asset or asset in str(series) or asset in str(ticker):
                return ms
        return None

    def _update_btc_history(self, now: float) -> None:
        """Update the shared BTC spot history from the market state store."""
        if self.market_state_store is None:
            return
        for ms in self.market_state_store.get_all().values():
            underlying = getattr(ms, "underlying", "")
            series = getattr(ms, "series_ticker", "")
            if underlying == "BTC" or "BTC" in str(series):
                btc_spot = getattr(ms, "external_spot", None)
                if btc_spot is None:
                    btc_spot = getattr(ms, "spot_price", None)
                if btc_spot is not None and btc_spot > 0:
                    btc_ts = getattr(ms, "last_book_update_ts", None) or now
                    self.btc_spot_history.update(float(btc_ts), float(btc_spot))
                break

    def _book_snapshots_for_state(self, market_state: Any, now: float) -> List[BookSnapshot]:
        """Append current yes/no snapshots to the asset's ring buffer and return them."""
        snaps = []
        for side in ("yes", "no"):
            snap = kalshi_state_book_levels(market_state, side, ts=now)
            if snap is not None:
                snaps.append(snap)
        return snaps

    def build(self, now: Optional[float] = None) -> FeatureSnapshot:
        """Construct a ``FeatureSnapshot`` for the current tick."""
        now = now or time.time()
        self._update_btc_history(now)

        by_asset: Dict[str, AssetFeatureSlice] = {}
        for asset in self.assets:
            missing: List[str] = []
            rti_obs = get_live_rti(asset)
            if rti_obs is None:
                missing.append("rti_unavailable")

            rti_returns: Dict[str, Optional[float]] = {}
            if rti_obs is not None and rti_obs.execution_eligible:
                for lookback in self.lookbacks_s:
                    key = f"rti_return_{int(lookback)}s"
                    try:
                        rti_returns[key] = get_rti_return(asset, lookback)
                    except Exception:
                        rti_returns[key] = None

            market_state = self._find_asset_market_state(asset)
            if market_state is None:
                missing.append("market_state_unavailable")

            # Update book history and compute microstructure for the current asset.
            yes_features: Optional[Dict[str, Any]] = None
            no_features: Optional[Dict[str, Any]] = None
            yes_edge_pp = 0.0
            no_edge_pp = 0.0
            book_delta_pp = 0.0
            cross_delta_pp = 0.0
            total_delta_pp = 0.0
            if market_state is not None:
                asset_history = self.book_history_by_asset[asset]
                for snap in self._book_snapshots_for_state(market_state, now):
                    asset_history.append(snap)
                target_spot = rti_obs.value if rti_obs is not None and rti_obs.value > 0 else None
                signals = compute_microstructure_signals(
                    state=market_state,
                    history=list(asset_history),
                    ofi_window_s=self.ofi_window_s,
                    max_edge_pct=self.max_edge_pct,
                    base_spot_history=self.btc_spot_history,
                    target_spot=target_spot,
                )
                if signals is not None:
                    yes_features = signals.get("yes_features")
                    no_features = signals.get("no_features")
                    yes_edge_pp = signals.get("yes_edge_pp", 0.0)
                    no_edge_pp = signals.get("no_edge_pp", 0.0)
                    book_delta_pp = signals.get("book_delta_pp", 0.0)
                    cross_delta_pp = signals.get("cross_delta_pp", 0.0)
                    total_delta_pp = signals.get("total_delta_pp", 0.0)

            btc_log_return = (
                self.btc_spot_history.log_return()
                if len(self.btc_spot_history.spots) >= 2
                else None
            )

            feature_valid = bool(rti_obs is not None and market_state is not None)

            slice_ = AssetFeatureSlice(
                asset=asset,
                rti_value=rti_obs.value if rti_obs is not None else None,
                rti_source_ts_ms=rti_obs.source_ts_ms if rti_obs is not None else None,
                rti_observed_ts_ms=rti_obs.observed_ts_ms if rti_obs is not None else None,
                rti_execution_eligible=rti_obs.execution_eligible if rti_obs is not None else False,
                rti_age_ms=rti_obs.age_ms if rti_obs is not None else None,
                rti_returns=rti_returns,
                book_imbalance_yes=yes_features.get("book_imbalance") if yes_features else None,
                book_imbalance_no=no_features.get("book_imbalance") if no_features else None,
                ofi_yes=yes_features.get("ofi") if yes_features else None,
                ofi_no=no_features.get("ofi") if no_features else None,
                spread_yes_cents=yes_features.get("spread_cents") if yes_features else None,
                spread_no_cents=no_features.get("spread_cents") if no_features else None,
                depth_ratio_yes=yes_features.get("depth_ratio") if yes_features else None,
                depth_ratio_no=no_features.get("depth_ratio") if no_features else None,
                log_depth_imbalance_yes=yes_features.get("log_depth_imbalance") if yes_features else None,
                log_depth_imbalance_no=no_features.get("log_depth_imbalance") if no_features else None,
                microstructure_yes_features=yes_features,
                microstructure_no_features=no_features,
                microstructure_yes_edge_pp=yes_edge_pp,
                microstructure_no_edge_pp=no_edge_pp,
                microstructure_book_delta_pp=book_delta_pp,
                microstructure_cross_delta_pp=cross_delta_pp,
                microstructure_total_delta_pp=total_delta_pp,
                btc_log_return=btc_log_return,
                feature_ts=now,
                feature_age_ms=(now - (rti_obs.source_ts_ms / 1000.0)) * 1000.0
                if rti_obs is not None and rti_obs.source_ts_ms is not None
                else None,
                feature_valid=feature_valid,
                missing_reasons=missing,
            )
            by_asset[asset] = slice_

        return FeatureSnapshot(ts=now, by_asset=by_asset, btc_spot_history=self.btc_spot_history)
