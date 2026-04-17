"""Load and resolve `config/crypto_threshold_matrix.yaml` — single tuning surface for crypto PM/MM.

Override path: env ``MERID_CRYPTO_THRESHOLD_MATRIX_PATH`` (absolute or cwd-relative).
Active profile key: ``legacy`` | ``modern`` from :func:`merid.prediction.crypto_edge_production.get_crypto_edge_runtime`.
"""

from __future__ import annotations

import os
import threading
from copy import deepcopy
from dataclasses import asdict, dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

from utils.logger import get_logger

logger = get_logger("merid.prediction.crypto_threshold_matrix")


def normalize_crypto_timeframe(timeframe: str) -> str:
    """Map agent/Catalog labels to grid keys (15m, 1h, daily, weekly, monthly, annual)."""
    t = (timeframe or "").strip().lower()
    if t in ("15m", "15min", "fifteen_min", "kx15m"):
        return "15m"
    if t in ("1h", "1hr", "hourly", "hour", "60m", "60min"):
        return "1h"
    if t in ("daily", "d1", "day", "1d"):
        return "daily"
    if t in ("weekly", "w1", "week"):
        return "weekly"
    if t in ("monthly", "1m", "month", "mo"):
        return "monthly"
    if t in ("annual", "yearly", "y1", "year", "kxannual"):
        return "annual"
    # Grid YAML uses HOURLY, ANNUAL, etc.
    if t == "hourly":
        return "1h"
    return "15m"


def _get_threshold_mode() -> str:
    from merid.prediction.crypto_edge_production import get_crypto_edge_runtime

    return str(get_crypto_edge_runtime().threshold_mode or "legacy")


_matrix_lock = threading.Lock()
_cached_path: Optional[str] = None
_cached_doc: Optional[Dict[str, Any]] = None


def _default_matrix_path() -> Path:
    return Path(__file__).resolve().parents[2] / "config" / "crypto_threshold_matrix.yaml"


def matrix_document_path() -> str:
    raw = (os.environ.get("MERID_CRYPTO_THRESHOLD_MATRIX_PATH") or "").strip()
    if raw:
        return str(Path(raw).expanduser())
    return str(_default_matrix_path())


def _decimal(val: Any, default: Decimal) -> Decimal:
    if val is None:
        return default
    if isinstance(val, Decimal):
        return val
    return Decimal(str(val))


def _float(val: Any, default: Optional[float] = None) -> Optional[float]:
    if val is None:
        return default
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def load_matrix_document(force: bool = False) -> Dict[str, Any]:
    global _cached_path, _cached_doc
    path = matrix_document_path()
    with _matrix_lock:
        if not force and _cached_doc is not None and _cached_path == path:
            return _cached_doc
        if not os.path.isfile(path):
            logger.warning("Crypto threshold matrix missing at %s — using embedded fallbacks", path)
            _cached_path = path
            _cached_doc = _embedded_fallback_document()
            return _cached_doc
        with open(path, "rb") as f:
            raw = yaml.safe_load(f.read())
        if not isinstance(raw, dict) or "profiles" not in raw:
            logger.error("Invalid crypto_threshold_matrix.yaml — expected top-level 'profiles'")
            _cached_path = path
            _cached_doc = _embedded_fallback_document()
            return _cached_doc
        _cached_path = path
        _cached_doc = raw
        logger.info("Loaded crypto threshold matrix from %s", path)
        return _cached_doc


def reload_matrix_document() -> Dict[str, Any]:
    return load_matrix_document(force=True)


def _embedded_fallback_document() -> Dict[str, Any]:
    """Minimal structure if YAML is absent (legacy + modern mirror prior Python constants)."""
    return {
        "schema_version": 1,
        "profiles": {
            "legacy": {"rows": _fallback_rows("legacy")},
            "modern": {"rows": _fallback_rows("modern")},
        },
    }


def _fallback_rows(mode: str) -> List[Dict[str, Any]]:
    if mode == "modern":
        tf_map = {
            "15m": ("0.01", "0.01", "58", "40", "40", "0.005"),
            "1h": ("0.0125", "0.0125", "58", "40", "40", "0.005"),
            "daily": ("0.015", "0.015", "58", "40", "40", "0.005"),
            "weekly": ("0.02", "0.02", "58", "40", "40", "0.005"),
            "monthly": ("0.02", "0.02", "58", "40", "40", "0.005"),
            "annual": ("0.02", "0.02", "58", "40", "40", "0.005"),
        }
    else:
        tf_map = {
            "15m": ("0.04", "0.04", "75", "10", "10", "0.08"),
            "1h": ("0.04", "0.04", "75", "10", "10", "0.08"),
            "daily": ("0.035", "0.035", "75", "10", "10", "0.08"),
            "weekly": ("0.03", "0.03", "75", "10", "10", "0.08"),
            "monthly": ("0.03", "0.03", "75", "10", "10", "0.08"),
            "annual": ("0.03", "0.03", "75", "10", "10", "0.08"),
        }
    rows = []
    for tf, (
        dme,
        sve,
        csm,
        mm,
        pm,
        tier,
    ) in tf_map.items():
        rows.append(
            {
                "asset": "*",
                "timeframe": tf,
                "archetype": "*",
                "directional_min_edge": dme,
                "sentiment_vol_regime_min_edge": sve,
                "contrarian_sentiment_min": float(csm),
                "contrarian_model_gap_min": 0.10,
                "mm_max_spread_cents": mm,
                "pm_risk_max_spread_cents": pm,
                "tier_min_edge_floor": tier,
                "kelly_fraction": "0.25",
                "min_order_notional_usd": 0.35,
                "vol_low_threshold": None,
                "vol_high_threshold": None,
                "vol_size_mult_low": None,
                "vol_size_mult_mid": None,
                "vol_size_mult_high": None,
                "spot_strike_veto_flag": False,
            }
        )
    return rows


def _row_specificity(r: Dict[str, Any]) -> int:
    a = str(r.get("asset") or "*").strip().upper()
    arch = str(r.get("archetype") or "*").strip().lower()
    tf = str(r.get("timeframe") or "*").strip().lower()
    s = 0
    if a != "*":
        s += 4
    if arch != "*":
        s += 2
    if tf != "*":
        s += 1
    return s


def _row_matches(
    r: Dict[str, Any],
    asset_upper: str,
    timeframe_norm: str,
    archetype_l: str,
) -> bool:
    ra = str(r.get("asset") or "*").strip().upper()
    rt = str(r.get("timeframe") or "*").strip().lower()
    rarch = str(r.get("archetype") or "*").strip().lower()
    if ra != "*" and ra != asset_upper:
        return False
    if rt != "*" and normalize_crypto_timeframe(rt) != timeframe_norm:
        return False
    if rarch != "*" and rarch != archetype_l:
        return False
    return True


def _coerce_row_types(merged: Dict[str, Any], path: str) -> Dict[str, Any]:
    out = dict(merged)
    out["directional_min_edge"] = _decimal(out.get("directional_min_edge"), Decimal("0.04"))
    out["sentiment_vol_regime_min_edge"] = _decimal(
        out.get("sentiment_vol_regime_min_edge"),
        out["directional_min_edge"],
    )
    out["contrarian_sentiment_min"] = float(out.get("contrarian_sentiment_min") or 75.0)
    gap = out.get("contrarian_model_gap_min")
    out["contrarian_model_gap_min"] = float(gap) if gap is not None else None
    out["mm_max_spread_cents"] = _decimal(out.get("mm_max_spread_cents"), Decimal("10"))
    out["pm_risk_max_spread_cents"] = _decimal(
        out.get("pm_risk_max_spread_cents"),
        out["mm_max_spread_cents"],
    )
    out["tier_min_edge_floor"] = _decimal(out.get("tier_min_edge_floor"), Decimal("0.08"))
    kf = out.get("kelly_fraction")
    if kf is not None:
        out["kelly_fraction"] = _decimal(kf, Decimal("0.25"))
    else:
        out["kelly_fraction"] = None
    out["min_order_notional_usd"] = _float(out.get("min_order_notional_usd"))
    for vk in ("vol_low_threshold", "vol_high_threshold"):
        out[vk] = _float(out.get(vk))
    for vk in ("vol_size_mult_low", "vol_size_mult_mid", "vol_size_mult_high"):
        v = out.get(vk)
        out[vk] = float(v) if v is not None else None
    out["spot_strike_veto_flag"] = bool(out.get("spot_strike_veto_flag"))
    out["matrix_source_path"] = path
    return out


def resolve_merged_row(
    *,
    asset: str,
    timeframe: str,
    archetype: str,
    profile_key: Optional[str] = None,
) -> Dict[str, Any]:
    """Merge all matching YAML rows for profile; higher-specificity rows overlay lower.
    
    When MERID_USE_DYNAMIC_EDGE_CALIBRATOR=true, uses DynamicEdgeCalibrator to compute
    edge thresholds based on current market conditions instead of static YAML values.
    """
    import os
    
    doc = load_matrix_document()
    path = matrix_document_path()
    prof = (profile_key or _get_threshold_mode() or "legacy").lower()
    prof_block = doc.get("profiles", {}).get(prof) or doc.get("profiles", {}).get("legacy")
    if not prof_block:
        prof_block = {"rows": _fallback_rows("legacy")}
    rows: List[Dict[str, Any]] = list(prof_block.get("rows") or [])
    asset_u = (asset or "").strip().upper() or "*"
    tf_n = normalize_crypto_timeframe(timeframe)
    arch_l = (archetype or "directional").strip().lower().replace("-", "_")

    # Check if dynamic edge calibration is enabled
    use_dynamic = os.getenv("MERID_USE_DYNAMIC_EDGE_CALIBRATOR", "false").lower() in ("true", "1", "yes")
    
    matching = [r for r in rows if _row_matches(r, asset_u, tf_n, arch_l)]
    merged: Dict[str, Any] = {}
    if matching:
        # Low-specificity rows first, then overlays (e.g. *|*|* then *|daily|*).
        for r in sorted(matching, key=_row_specificity):
            for k, v in r.items():
                if v is None:
                    continue
                merged[k] = v
    base = _fallback_rows("modern" if prof == "modern" else "legacy")
    base_row = next(
        (deepcopy(x) for x in base if normalize_crypto_timeframe(str(x.get("timeframe"))) == tf_n),
        deepcopy(base[0]) if base else {},
    )
    # Underlay defaults from fallback row for this timeframe, then YAML merged (specific), then merged (wildcards)
    out = {**base_row, **merged}
    
    # Apply dynamic edge calibration if enabled
    if use_dynamic and asset_u in ("BTC", "ETH", "SOL", "XRP", "DOGE"):
        try:
            from merid.prediction.dynamic_edge_calibrator import get_dynamic_edge_calibrator
            calibrator = get_dynamic_edge_calibrator()
            dynamic_edge = calibrator.compute_edge_threshold(asset_u, tf_n)
            
            # Override the static edge values with dynamic computation
            out["directional_min_edge"] = str(dynamic_edge)
            out["sentiment_vol_regime_min_edge"] = str(dynamic_edge)
            out["dynamic_edge_applied"] = True
            out["dynamic_edge_value"] = str(dynamic_edge)
            
            logger.debug(
                f"Dynamic edge applied for {asset_u}/{tf_n}: {dynamic_edge} "
                f"(was {merged.get('directional_min_edge', base_row.get('directional_min_edge', 'N/A'))})"
            )
        except Exception as e:
            logger.debug(f"Dynamic edge calibration failed for {asset_u}/{tf_n}: {e}")
            out["dynamic_edge_applied"] = False
    else:
        out["dynamic_edge_applied"] = False
    
    out["asset"] = asset_u
    out["timeframe"] = tf_n
    out["archetype"] = arch_l
    out["profile"] = prof
    return _coerce_row_types(out, path)


@dataclass(frozen=True)
class EffectiveCryptoConfig:
    """Resolved crypto tuning row for an agent × market context."""

    agent_name: str
    market_id: str
    profile: str
    archetype: str
    asset: str
    timeframe: str
    directional_min_edge: Decimal
    sentiment_vol_regime_min_edge: Decimal
    contrarian_sentiment_min: float
    contrarian_model_gap_min: Optional[float]
    mm_max_spread_cents: Decimal
    pm_risk_max_spread_cents: Decimal
    tier_min_edge_floor: Decimal
    kelly_fraction: Optional[Decimal]
    min_order_notional_usd: Optional[float]
    vol_low_threshold: Optional[float]
    vol_high_threshold: Optional[float]
    vol_size_mult_low: Optional[float]
    vol_size_mult_mid: Optional[float]
    vol_size_mult_high: Optional[float]
    spot_strike_veto_flag: bool
    matrix_source_path: str

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        for k, v in list(d.items()):
            if isinstance(v, Decimal):
                d[k] = str(v)
        return d


def parse_grid_name_from_agent_id(agent_id: Optional[str]) -> Optional[str]:
    """Best-effort: ``kalshi-btc_15m`` + ``_deadbeef`` instance suffix → ``BTC_15M``."""
    if not agent_id:
        return None
    s = agent_id.strip()
    low = s.lower()
    if low.startswith("kalshi-"):
        s = s[7:]
    if "_" in s:
        tail = s.rsplit("_", 1)[-1]
        if len(tail) == 8 and all(c in "0123456789abcdef" for c in tail.lower()):
            s = s[: -(len(tail) + 1)]
    return s.upper().replace("-", "_")


def get_effective_crypto_config(
    agent_name: str,
    market_id: str,
    *,
    timeframe_override: Optional[str] = None,
    asset_override: Optional[str] = None,
) -> Optional[EffectiveCryptoConfig]:
    """Resolve matrix row for a grid agent display name and Kalshi market ticker.

    For table expansion without a real ticker, pass ``timeframe_override`` / ``asset_override``.
    """
    try:
        from config.kalshi_crypto_config import ACTIVE_CRYPTO_ASSETS, kalshi_ticker_to_asset
        from merid.prediction.agent_grid_config import get_agent_grid_config
        from merid.event_venues.kalshi.market_filter import get_series_timeframe_bucket
    except Exception as exc:
        logger.debug("get_effective_crypto_config imports failed: %s", exc)
        return None

    grid = get_agent_grid_config()
    ag = grid.get_agent(agent_name)
    if ag is None:
        return None

    primary = (ag.assets[0] if ag.assets else "") or ""
    primary_u = primary.strip().upper()
    mid = market_id or ""
    if timeframe_override:
        tf_raw = timeframe_override
        m_asset = ""
    elif mid.startswith("SYNTH-") or not mid.strip():
        m_asset = ""
        tf_raw = ag.timeframes[0] if ag.timeframes else "15m"
    else:
        m_asset = kalshi_ticker_to_asset(mid) or ""
        try:
            tf_raw = get_series_timeframe_bucket(mid)
        except Exception:
            tf_raw = ag.timeframes[0] if ag.timeframes else "15m"

    if asset_override:
        m_asset = asset_override.strip().upper()

    asset_u = (m_asset or primary_u or "*").strip().upper()
    if asset_u not in ACTIVE_CRYPTO_ASSETS and primary_u in ACTIVE_CRYPTO_ASSETS:
        asset_u = primary_u
    if asset_u not in ACTIVE_CRYPTO_ASSETS:
        return None

    tf = normalize_crypto_timeframe(str(tf_raw))
    arch = (ag.archetype or "directional").strip().lower().replace("-", "_")
    row = resolve_merged_row(asset=asset_u, timeframe=tf, archetype=arch)
    return EffectiveCryptoConfig(
        agent_name=ag.name,
        market_id=market_id or "",
        profile=str(row.get("profile", "")),
        archetype=arch,
        asset=asset_u,
        timeframe=tf,
        directional_min_edge=_decimal(row.get("directional_min_edge"), Decimal("0.04")),
        sentiment_vol_regime_min_edge=_decimal(
            row.get("sentiment_vol_regime_min_edge"),
            _decimal(row.get("directional_min_edge"), Decimal("0.04")),
        ),
        contrarian_sentiment_min=float(row.get("contrarian_sentiment_min") or 75.0),
        contrarian_model_gap_min=_float(row.get("contrarian_model_gap_min")),
        mm_max_spread_cents=_decimal(row.get("mm_max_spread_cents"), Decimal("10")),
        pm_risk_max_spread_cents=_decimal(row.get("pm_risk_max_spread_cents"), Decimal("10")),
        tier_min_edge_floor=_decimal(row.get("tier_min_edge_floor"), Decimal("0.08")),
        kelly_fraction=_decimal(row.get("kelly_fraction"), Decimal("0.25"))
        if row.get("kelly_fraction") is not None
        else None,
        min_order_notional_usd=_float(row.get("min_order_notional_usd")),
        vol_low_threshold=_float(row.get("vol_low_threshold")),
        vol_high_threshold=_float(row.get("vol_high_threshold")),
        vol_size_mult_low=_float(row.get("vol_size_mult_low")),
        vol_size_mult_mid=_float(row.get("vol_size_mult_mid")),
        vol_size_mult_high=_float(row.get("vol_size_mult_high")),
        spot_strike_veto_flag=bool(row.get("spot_strike_veto_flag")),
        matrix_source_path=str(row.get("matrix_source_path", "")),
    )


def get_min_order_notional_for_intent(agent_id: Optional[str], ticker: str) -> Optional[float]:
    name = parse_grid_name_from_agent_id(agent_id)
    if not name:
        return None
    eff = get_effective_crypto_config(name, ticker)
    if eff is None:
        return None
    return eff.min_order_notional_usd


def enumerate_effective_rows_for_grid() -> List[Dict[str, Any]]:
    """Expand grid crypto agents × a representative market id per asset/timeframe (for API)."""
    try:
        from config.kalshi_crypto_config import ACTIVE_CRYPTO_ASSETS
        from merid.prediction.agent_grid_config import get_agent_grid_config
    except Exception:
        return []

    grid = get_agent_grid_config()
    out: List[Dict[str, Any]] = []
    for ag in grid.agents:
        if (ag.category or "").lower() != "crypto":
            continue
        if (ag.archetype or "") in ("arbitrage",):
            continue
        assets = ag.assets or ["BTC"]
        tfs = ag.timeframes or ["15m"]
        for asset in assets:
            au = str(asset).upper()
            if au not in ACTIVE_CRYPTO_ASSETS:
                continue
            for tf in tfs:
                tf_n = normalize_crypto_timeframe(str(tf))
                eff = get_effective_crypto_config(
                    ag.name,
                    "",
                    timeframe_override=tf_n,
                    asset_override=au,
                )
                if eff:
                    row = eff.to_dict()
                    row["note"] = "resolved via asset_override/timeframe_override (no market ticker)"
                    out.append(row)
    return out


def effective_matrix_payload() -> Dict[str, Any]:
    """API / scripts: document path, runtime profile, and resolved rows."""
    doc = load_matrix_document()
    return {
        "matrix_path": matrix_document_path(),
        "schema_version": doc.get("schema_version", 1),
        "threshold_mode": _get_threshold_mode(),
        "legacy_grid": enumerate_crypto_threshold_matrix_from_yaml("legacy"),
        "modern_grid": enumerate_crypto_threshold_matrix_from_yaml("modern"),
        "agents": enumerate_effective_rows_for_grid(),
    }


def enumerate_crypto_threshold_matrix_from_yaml(profile: str) -> Dict[str, Any]:
    from config.kalshi_crypto_config import ACTIVE_CRYPTO_ASSETS

    prof = profile.lower()
    nested: Dict[str, Any] = {}
    for tf in ("15m", "1h", "daily", "weekly", "monthly", "annual"):
        for ast in ACTIVE_CRYPTO_ASSETS:
            row = resolve_merged_row(asset=ast, timeframe=tf, archetype="directional", profile_key=prof)
            nested[f"{ast}:{tf}"] = {
                "directional_min_edge": str(row["directional_min_edge"]),
                "sentiment_vol_regime_min_edge": str(row["sentiment_vol_regime_min_edge"]),
                "contrarian_sentiment_min": row["contrarian_sentiment_min"],
                "contrarian_model_gap_min": row.get("contrarian_model_gap_min"),
                "mm_max_spread_cents": str(row["mm_max_spread_cents"]),
                "pm_risk_max_spread_cents": str(row["pm_risk_max_spread_cents"]),
                "tier_min_edge_floor": str(row["tier_min_edge_floor"]),
                "kelly_fraction": str(row["kelly_fraction"]) if row.get("kelly_fraction") is not None else None,
                "min_order_notional_usd": row.get("min_order_notional_usd"),
                "spot_strike_veto_flag": row.get("spot_strike_veto_flag"),
            }
    return {"assets": list(ACTIVE_CRYPTO_ASSETS), prof: nested}
