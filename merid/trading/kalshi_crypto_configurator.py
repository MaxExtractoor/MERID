"""Kalshi crypto scan config — volatility‑scaled widths, lookbacks, and timeframes.

Implements the same rules as ``KALSHI_CRYPTO_CONFIGURATOR_SYSTEM_PROMPT`` for
deterministic use in the stack (tests, services). LLM orchestration can inject
the prompt constant and parse JSON, or call :func:`build_kalshi_crypto_scan_config`.
"""

from __future__ import annotations

import json
import math
from typing import Dict, List, Mapping, Sequence

# All keys required in output JSON
CRYPTO_ASSETS: tuple[str, ...] = ("BTC", "ETH", "SOL", "XRP", "DOGE")

WIDTH_MIN = 0.10
WIDTH_MAX = 0.35
LOOKBACK_MIN = 60
LOOKBACK_MAX = 3600

KALSHI_CRYPTO_CONFIGURATOR_SYSTEM_PROMPT = r"""You are the **KalshiCryptoConfigurator**, responsible for returning clean JSON config for how our trading system scans Kalshi crypto markets.

Your only job is to derive per‑asset parameters **relative to Bitcoin**, based on their typical price volatility, so that each asset's scan window and preferred timeframes are tailored to how it actually moves.

You MUST follow these rules:

1. **Inputs you receive**
   - A baseline config for BTC, including:
     - `base_width_btc` (example: `0.125` for ±12.5% around spot)
     - `base_lookback_btc_seconds` (example: `900` for 15 minutes)
     - `btc_timeframes` (example: `["15M","1H","1D","1W","1M","1Y"]`)
   - A table of annualized volatility multipliers per asset, computed **off‑chain** by another process from historical prices, where:
     - Each multiplier is `asset_vol / btc_vol` over 90–365 days of prices.
     - Keys are: `BTC`, `ETH`, `SOL`, `XRP`, `DOGE`.
   - Example multipliers (THESE ARE EXAMPLES; always use the numbers passed in at runtime):
     - `BTC: 1.0`
     - `ETH: 1.3`
     - `SOL: 2.0`
     - `XRP: 1.8`
     - `DOGE: 2.4`

2. **What you must output**
   - A single **JSON object**, no prose, no comments, no code.
   - Top‑level keys: `BTC`, `ETH`, `SOL`, `XRP`, `DOGE`.
   - For each asset key, output:
     - `width`: the symmetric percent window around spot used to select Kalshi strikes (as a decimal, e.g. `0.125` for ±12.5%).
     - `lookback_seconds`: integer; the effective lookback horizon for signals for that asset.
     - `timeframes`: an ordered list of Kalshi series labels you want the trader to prioritize for that asset, e.g. `["15M","1H","1D"]`. These will be mapped downstream to series like `KXBTC15M`, `KXETH`, `KXSOL`, etc.

3. **How to scale the width (±% around spot)**
   - Use the formula:
     - `width_raw(asset) = base_width_btc * vol_multiplier(asset)`
   - Then **clamp** this to a safe range:
     - If `width_raw < 0.10`, set `width = 0.10`
     - If `width_raw > 0.35`, set `width = 0.35`
     - Otherwise, `width = width_raw`
   - This means higher‑vol assets like SOL or DOGE normally get a wider discovery band than BTC, but never more than ±35%.

4. **How to scale the lookback (signal horizon)**
   - Use the inverse relation so more volatile assets look at shorter history:
     - `lookback_raw(asset) = base_lookback_btc_seconds / vol_multiplier(asset)`
   - Then **clamp**:
     - Minimum: `60` seconds
     - Maximum: `3600` seconds
   - Round to the nearest integer second.
   - Example: if BTC uses 900 seconds and DOGE multiplier is 2.4, DOGE lookback should be around `900 / 2.4 ≈ 375` seconds, then clamped if needed.

5. **How to choose the timeframes per asset**
   - You must map volatility level to a preferred set of Kalshi series timeframes:
     - If `vol_multiplier <= 1.2` (BTC‑like or calmer):
       - `timeframes = ["15M","1H","1D","1W"]`
     - If `1.2 < vol_multiplier <= 1.8` (moderately higher vol, e.g. many ETH/XRP regimes):
       - `timeframes = ["5M","15M","1H","1D"]`
     - If `vol_multiplier > 1.8` (high vol, e.g. typical SOL/DOGE):
       - `timeframes = ["1M","5M","15M","1H"]`
   - Do not invent other timeframe labels. Only use the labels given in input or in these rules.
   - For **BTC**, use the provided `btc_timeframes` list as‑is (order preserved). For **ETH, SOL, XRP, DOGE**, use the bucket above.
   - The system downstream will convert these into actual series codes such as `KXBTC15M`, `KXETH15M`, `KXSOL15M`, `KXXRP15M`, `KXDOGE15M`, etc.

6. **Stability and constraints**
   - You MUST:
     - Respect the `width` clamp `[0.10, 0.35]`.
     - Respect the `lookback_seconds` clamp `[60, 3600]`.
     - Never return negative or zero values.
     - Never include anything other than the required keys.
   - You MUST NOT:
     - Change or re‑derive the volatility multipliers; they are authoritative.
     - Output any explanation, commentary, or code. Only JSON.

7. **Output format**
   - Always output **only** a minified JSON object suitable for direct parsing.
"""


def _clamp_width(raw: float) -> float:
    return max(WIDTH_MIN, min(WIDTH_MAX, raw))


def _clamp_lookback_seconds(raw: float) -> int:
    v = int(round(raw))
    return max(LOOKBACK_MIN, min(LOOKBACK_MAX, v))


def _timeframes_for_multiplier(mult: float) -> List[str]:
    if mult <= 1.2:
        return ["15M", "1H", "1D", "1W"]
    if mult <= 1.8:
        return ["5M", "15M", "1H", "1D"]
    return ["1M", "5M", "15M", "1H"]


def build_kalshi_crypto_scan_config(
    *,
    base_width_btc: float,
    base_lookback_btc_seconds: float,
    btc_timeframes: Sequence[str],
    vol_multipliers: Mapping[str, float],
) -> Dict[str, Dict[str, object]]:
    """Return per‑asset scan config (pure dict, JSON‑serializable).

    Args:
        base_width_btc: BTC baseline half‑window as decimal (e.g. 0.125).
        base_lookback_btc_seconds: BTC baseline lookback in seconds before scaling.
        btc_timeframes: Ordered timeframe labels for **BTC** only (authoritative).
        vol_multipliers: ``asset -> multiplier``; must include all ``CRYPTO_ASSETS``.

    Raises:
        ValueError: if inputs are invalid or multipliers missing keys.
    """
    if base_width_btc <= 0 or base_lookback_btc_seconds <= 0:
        raise ValueError("base_width_btc and base_lookback_btc_seconds must be positive")
    if not btc_timeframes:
        raise ValueError("btc_timeframes must be non-empty")
    if any(not isinstance(x, str) or not x.strip() for x in btc_timeframes):
        raise ValueError("btc_timeframes must be non-empty strings")

    missing = [a for a in CRYPTO_ASSETS if a not in vol_multipliers]
    if missing:
        raise ValueError(f"vol_multipliers missing keys: {missing}")

    out: Dict[str, Dict[str, object]] = {}
    btc_tfs = [str(x).strip().upper() for x in btc_timeframes]

    for asset in CRYPTO_ASSETS:
        mult = float(vol_multipliers[asset])
        if mult <= 0 or not math.isfinite(mult):
            raise ValueError(f"vol_multipliers[{asset!r}] must be positive and finite")

        width = _clamp_width(base_width_btc * mult)
        lookback = _clamp_lookback_seconds(base_lookback_btc_seconds / mult)

        if asset == "BTC":
            tfs: List[str] = list(btc_tfs)
        else:
            tfs = list(_timeframes_for_multiplier(mult))

        out[asset] = {
            "width": width,
            "lookback_seconds": lookback,
            "timeframes": tfs,
        }

    return out


def build_kalshi_crypto_scan_config_json(
    *,
    base_width_btc: float,
    base_lookback_btc_seconds: float,
    btc_timeframes: Sequence[str],
    vol_multipliers: Mapping[str, float],
    indent: int | None = None,
) -> str:
    """Minified JSON string (default) or pretty-printed if ``indent`` is set."""
    cfg = build_kalshi_crypto_scan_config(
        base_width_btc=base_width_btc,
        base_lookback_btc_seconds=base_lookback_btc_seconds,
        btc_timeframes=btc_timeframes,
        vol_multipliers=vol_multipliers,
    )
    if indent is not None:
        return json.dumps(cfg, indent=indent)
    return json.dumps(cfg, separators=(",", ":"))
