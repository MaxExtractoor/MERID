"""Settlement-pending quarantine for the canonical portfolio reconciler.

2026-09-25: Kalshi drops positions from /portfolio/positions at market close
while the local ledger/cache still carries the exposure until the settlement
credit posts.  ``_is_expired_ticker`` waits for a long (900s default) grace
before calling such positions expired, so every window boundary produced a
transient exchange=0 vs cache>0 MISMATCH_PERSISTENT that halted all entries
for ~2-4 minutes.  ``_is_settlement_pending_market`` quarantines past-close
tickers from the active-position authority diff immediately; the position is
still tracked for settlement accounting — it just can't gate live authority.
"""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from merid.event_venues.kalshi.canonical_portfolio_reconciler import (
    CanonicalPortfolioReconciler,
    _is_settlement_pending_market,
)

_MONTHS = {
    1: "JAN", 2: "FEB", 3: "MAR", 4: "APR", 5: "MAY", 6: "JUN",
    7: "JUL", 8: "AUG", 9: "SEP", 10: "OCT", 11: "NOV", 12: "DEC",
}


def _ticker_for_expiry_utc(expiry_utc: datetime) -> str:
    """Ticker whose encoded ET window-end equals ``expiry_utc``."""
    try:
        from zoneinfo import ZoneInfo

        et = expiry_utc.astimezone(ZoneInfo("America/New_York"))
    except Exception:
        et = expiry_utc - timedelta(hours=4)  # EDT
    et = et.replace(second=0, microsecond=0)
    return (
        f"KXBTC15M-{str(et.year)[2:]}{_MONTHS[et.month]}"
        f"{et.day:02d}{et.hour:02d}{et.minute:02d}-45"
    )


def test_past_close_ticker_is_settlement_pending():
    # Window that ended ~5 minutes ago (inside the 900s expiry grace).
    tk = _ticker_for_expiry_utc(datetime.now(timezone.utc) - timedelta(minutes=5))
    assert _is_settlement_pending_market(tk) is True


def test_live_ticker_is_not_settlement_pending():
    # Window ending ~10 minutes in the future.
    tk = _ticker_for_expiry_utc(datetime.now(timezone.utc) + timedelta(minutes=10))
    assert _is_settlement_pending_market(tk) is False


def test_unknown_ticker_is_not_settlement_pending():
    assert _is_settlement_pending_market("") is False
    assert _is_settlement_pending_market("NOT-A-MARKET") is False


def test_filter_quarantines_past_close_from_all_sources():
    rec = CanonicalPortfolioReconciler()
    closed_tk = _ticker_for_expiry_utc(datetime.now(timezone.utc) - timedelta(minutes=3))
    live_tk = _ticker_for_expiry_utc(datetime.now(timezone.utc) + timedelta(minutes=10))
    positions = {
        closed_tk: SimpleNamespace(signed_yes_cc=-100),
        live_tk: SimpleNamespace(signed_yes_cc=50),
    }
    for source in ("exchange", "ledger", "cache"):
        out = rec._filter_expired_positions(dict(positions), source)
        assert closed_tk not in out, f"{source} must quarantine {closed_tk}"
        assert live_tk in out, f"{source} must keep live {live_tk}"


def test_expired_ticker_still_quarantined():
    rec = CanonicalPortfolioReconciler()
    # Window that ended ~20 minutes ago — beyond the close window entirely.
    old_tk = _ticker_for_expiry_utc(datetime.now(timezone.utc) - timedelta(minutes=20))
    live_tk = _ticker_for_expiry_utc(datetime.now(timezone.utc) + timedelta(minutes=10))
    out = rec._filter_expired_positions(
        {old_tk: SimpleNamespace(signed_yes_cc=-100),
         live_tk: SimpleNamespace(signed_yes_cc=50)},
        "cache",
    )
    assert old_tk not in out
    assert live_tk in out
