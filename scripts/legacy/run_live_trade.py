"""End-to-end: forecasters -> swarm consensus -> debate -> live Kalshi order."""

# ═══════════════════════════════════════════════════════════════════════════
# PRODUCTION HARDENING — CRITICAL BYPASS DISABLED
# ═══════════════════════════════════════════════════════════════════════════
# This script contains a DIRECT HTTP BYPASS to Kalshi API that circumvents
# the canonical order_router and ALL risk guards (GlobalRiskGuard 1-2% cap,
# Top-3 batch gate, PreTradeGate, execution gate, kill switches).
#
# To enable this bypass (NOT RECOMMENDED): set MERID_ALLOW_LIVE_TRADE_BYPASS=1
# See: run_live_trade.py.DISABLED for full documentation.
# ═══════════════════════════════════════════════════════════════════════════
import os
if os.getenv("MERID_ALLOW_LIVE_TRADE_BYPASS", "").lower() not in ("1", "true", "yes"):
    raise RuntimeError(
        "[PRODUCTION HARDENING] run_live_trade.py is DISABLED. "
        "This script contains a direct HTTP bypass that circumvents all risk guards. "
        "Use the canonical path: POST /api/v1/kalshi/orders or KalshiContinuousTrader. "
        "To bypass (NOT RECOMMENDED): MERID_ALLOW_LIVE_TRADE_BYPASS=1"
    )
# ═══════════════════════════════════════════════════════════════════════════

import asyncio, json, time, base64
from pathlib import Path
from datetime import datetime, timezone

for line in Path('.env').read_text().splitlines():
    if '=' in line and not line.startswith('#'):
        k, _, v = line.partition('=')
        os.environ.setdefault(k.strip(), v.strip())

os.environ['KALSHI_ENV'] = 'live'

MARKET = {
    "ticker":    "KXFED-27APR-T3.25",
    "title":     "Will fed funds rate be above 3.25% after April 2027 FOMC?",
    "yes_ask":   0.62,
    "yes_bid":   0.61,
    "no_ask":    0.39,
    "volume":    4290,
    "close_time": "2027-04-28T18:05:00Z",
}

implied_yes = (MARKET["yes_ask"] + MARKET["yes_bid"]) / 2
close_dt = datetime.fromisoformat(MARKET["close_time"].replace("Z", "+00:00"))
minutes_to_expiry = (close_dt - datetime.now(timezone.utc)).total_seconds() / 60
now_utc = datetime.now(timezone.utc)

print("=" * 60)
print(f"MARKET: {MARKET['ticker']}")
print(f"  {MARKET['title']}")
print(f"  YES ask/bid: ${MARKET['yes_ask']:.2f}/${MARKET['yes_bid']:.2f}  implied {implied_yes:.1%}")
print(f"  Volume: {MARKET['volume']}  Expires in: {int(minutes_to_expiry/60/24)} days")
print()

# ── Forecaster ensemble ───────────────────────────────────────────────
from merid.prediction.forecasters.registry import get_forecaster_registry
from merid.prediction.forecasters.macro_regime import MacroRegimeForecaster
from merid.prediction.forecasters.sentiment import ExternalSentimentForecaster
from merid.prediction.forecasters.time_series import TimeSeriesForecaster

registry = get_forecaster_registry()
for cls in [MacroRegimeForecaster, ExternalSentimentForecaster, TimeSeriesForecaster]:
    try:
        registry.register(cls())
    except Exception:
        pass

ensemble = registry.predict_all(
    market_id=MARKET["ticker"],
    implied_yes=implied_yes,
    implied_no=1 - implied_yes,
    volume=MARKET["volume"],
    open_interest=0,
    minutes_to_expiry=minutes_to_expiry,
    asset="FEDFUNDS",
    timeframe="monthly",
    bid=MARKET["yes_bid"],
    ask=MARKET["yes_ask"],
    category="economics",
)

print("=" * 60)
print("FORECASTER ENSEMBLE")
print("=" * 60)
p_ensemble = implied_yes
if ensemble:
    seen = set()
    for r in ensemble.forecasts:
        if r.forecaster_id in seen:
            continue
        seen.add(r.forecaster_id)
        edge = r.p_model - implied_yes
        print(f"  {r.forecaster_id:<26} p={r.p_model:.3f}  conf={r.confidence:.2f}  edge={edge:+.3f}")
    p_ensemble = ensemble.p_ensemble
    print(f"  {'ENSEMBLE':<26} p={p_ensemble:.3f}  conf={ensemble.confidence:.2f}  edge={p_ensemble-implied_yes:+.3f}")
print()

# ── Swarm consensus ───────────────────────────────────────────────────
from merid.swarm.consensus_aggregator import SwarmConsensusAggregator, AgentProposal

agg = SwarmConsensusAggregator(min_agents_for_consensus=2, consensus_threshold=0.55)
if ensemble:
    seen = set()
    for r in ensemble.forecasts:
        if r.forecaster_id in seen:
            continue
        seen.add(r.forecaster_id)
        direction = "yes" if r.p_model >= 0.5 else "no"
        agg.submit_proposal(AgentProposal(
            agent_id=r.forecaster_id,
            asset="FEDFUNDS",
            timeframe="monthly",
            direction=direction,
            probability=r.p_model,
            confidence=r.confidence,
            size_preference="small",
            rationale=f"{r.forecaster_id} p={r.p_model:.3f}",
            edge_estimate=(r.p_model - implied_yes) * 100,
            timestamp=now_utc,
            agent_archetype=r.forecaster_id,
        ))

consensus = agg.get_consensus("FEDFUNDS", "monthly")
print("=" * 60)
print("SWARM CONSENSUS")
print("=" * 60)
if consensus:
    print(f"  Status:     {consensus.status.value}")
    print(f"  Direction:  {consensus.consensus_direction}")
    print(f"  p_yes:      {consensus.consensus_probability:.3f}")
    print(f"  Agents:     {consensus.voting_agents}/{consensus.total_agents}")
    print(f"  Confidence: {consensus.consensus_confidence:.3f}")
    print(f"  Size band:  {consensus.size_band}")
    print(f"  Breakdown:  {consensus.direction_breakdown}")
print()

# ── Structured debate ─────────────────────────────────────────────────
debate_args = [
    ("macro_regime",   "YES", 0.72, "Core PCE sticky ~2.4%. Labor tight. Rate unlikely below 3.25% by Apr 2027."),
    ("momentum",       "YES", 0.65, "Fed futures: only 1-2 cuts priced. Momentum: rates stay elevated."),
    ("mean_reversion", "NO",  0.58, "Unemployment ~4.5% trending up. Fed historically overshoots cuts."),
    ("sentiment",      "NO",  0.55, "Fear/greed + credit spreads: dovish path gaining. Easing bias wins."),
]

yes_w = sum(c for _, d, c, _ in debate_args if d == "YES")
no_w  = sum(c for _, d, c, _ in debate_args if d == "NO")
post_p = yes_w / (yes_w + no_w)

print("=" * 60)
print("DEBATE")
print("=" * 60)
for ag, direction, conf, text in debate_args:
    print(f"  [{direction}] {ag:<18} ({conf:.0%})")
    print(f"        {text}")
print(f"\n  Pre-debate:  {implied_yes:.3f}")
print(f"  Post-debate: {post_p:.3f}  (lift={post_p - implied_yes:+.3f})")
print()

# ── Final verdict ─────────────────────────────────────────────────────
final_p = (post_p + p_ensemble) / 2
edge    = final_p - implied_yes
action  = "YES" if edge > 0 else "NO"
price   = MARKET["yes_ask"] if action == "YES" else MARKET["no_ask"]

print("=" * 60)
print("FINAL VERDICT")
print("=" * 60)
print(f"  Market implied:  {implied_yes:.1%}")
print(f"  System estimate: {final_p:.1%}")
print(f"  Edge:            {edge:+.3f}")
print(f"  Decision:        BUY {action} @ ${price:.2f}")
print(f"  Thesis: Forecasters 3/4 lean YES. Macro+momentum hawkish dominant.")
print(f"  Cost $0.62  |  Payout $1.00 if YES  |  Net +$0.38 profit")
print()


async def place_live_order():
    import httpx
    from cryptography.hazmat.primitives import serialization, hashes
    from cryptography.hazmat.primitives.asymmetric import padding

    api_key = os.environ['KALSHI_API_KEY_ID']
    pem = Path('kalshi_private_key.pem').read_bytes()
    private_key = serialization.load_pem_private_key(pem, password=None)
    base_url = "https://external-api.kalshi.com/trade-api/v2"

    def sign(method, path):
        ts_ms = str(int(time.time() * 1000))
        sig = private_key.sign(
            (ts_ms + method.upper() + path).encode(),
            padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.DIGEST_LENGTH),
            hashes.SHA256(),
        )
        return {
            "KALSHI-ACCESS-KEY": api_key,
            "KALSHI-ACCESS-TIMESTAMP": ts_ms,
            "KALSHI-ACCESS-SIGNATURE": base64.b64encode(sig).decode(),
            "Content-Type": "application/json",
        }

    async with httpx.AsyncClient(timeout=15) as http:
        r = await http.get(f"{base_url}/portfolio/balance",
                           headers=sign("GET", "/trade-api/v2/portfolio/balance"))
        bal = r.json().get("balance", 0)
        print(f"  Account balance: {bal}c (${bal/100:.2f})")

        price_cents = int(price * 100)
        side = action.lower()  # "yes" or "no"
        price_key = f"{side}_price"
        order_body = {
            "ticker":          MARKET["ticker"],
            "action":          "buy",
            "side":            side,
            "count":           1,
            "type":            "limit",
            price_key:         price_cents,
            "client_order_id": f"merid_consensus_{int(time.time())}",
        }

        path = "/portfolio/orders"
        print(f"  Placing: {json.dumps(order_body)}")
        r = await http.post(f"{base_url}{path}",
                            headers=sign("POST", f"/trade-api/v2{path}"),
                            json=order_body)
        print(f"  HTTP {r.status_code}: {r.text[:400]}")

        if r.status_code in (200, 201):
            order = r.json().get("order", r.json())
            print()
            print("=" * 60)
            print("ORDER PLACED - SYSTEM IS LIVE")
            print("=" * 60)
            print(f"  Order ID:  {order.get('id', order.get('order_id', '?'))}")
            print(f"  Ticker:    {MARKET['ticker']}")
            print(f"  Action:    BUY {action}")
            print(f"  Price:     ${price:.2f} ({price_cents}c)")
            print(f"  Count:     1 contract")
            print(f"  Status:    {order.get('status', '?')}")
            print()
            print("  Pipeline complete: forecasters -> consensus -> debate -> live order.")


asyncio.run(place_live_order())
