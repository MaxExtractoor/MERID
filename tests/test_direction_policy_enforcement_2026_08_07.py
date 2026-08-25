"""
Tests for canonical binary price-space handling (2026-08-09 update)

The 2026-08-07 direction policy that rejected SELL entry fills and cross-leg
exits has been removed.  Kalshi binary contracts are economically paired:

  BUY_YES == SELL_NO  -> long YES exposure
  BUY_NO  == SELL_YES -> long NO  exposure

A fill should be accepted when its signed YES-delta is consistent with the
position: same sign opens/adds, opposite sign (without flipping) closes.
"""

import pytest
from merid.event_venues.kalshi.position_cache import CachedPosition


class TestPositionCacheCanonicalBinaryHandling:
    """Test that CachedPosition.apply_fill uses signed YES-delta, not raw side."""

    def _make_position(self, side, contracts=0, price=50):
        return CachedPosition(
            market_id="KXBTC15M-TEST",
            agent_id="test_agent",
            thesis_side=side,
            contracts=contracts,
            side=side,
            avg_price_cents=price,
            realized_pnl_usd=0,
            unrealized_pnl_usd=0,
        )

    # ------------------------------------------------------------------
    # Entry / add using all canonical forms
    # ------------------------------------------------------------------

    def test_buy_yes_opens_long_yes(self):
        """BUY_YES opens a long YES position."""
        position = self._make_position("yes")
        position.apply_fill(contracts=1, price_cents=50, fee_cents=2, side="yes", action="buy")

        assert position.contracts == 1
        assert position.side == "yes"

    def test_sell_no_opens_long_yes(self):
        """SELL_NO is economically BUY_YES (long YES)."""
        position = self._make_position("yes")
        position.apply_fill(contracts=1, price_cents=50, fee_cents=2, side="no", action="sell")

        assert position.contracts == 1
        assert position.side == "yes"

    def test_buy_no_opens_long_no(self):
        """BUY_NO opens a long NO position."""
        position = self._make_position("no")
        position.apply_fill(contracts=1, price_cents=50, fee_cents=2, side="no", action="buy")

        assert position.contracts == 1
        assert position.side == "no"

    def test_sell_yes_opens_long_no(self):
        """SELL_YES is economically BUY_NO (long NO)."""
        position = self._make_position("no")
        position.apply_fill(contracts=1, price_cents=59, fee_cents=2, side="yes", action="sell")

        assert position.contracts == 1
        assert position.side == "no"
        # Price must be converted from YES space (59c) to NO space (41c).
        assert position.avg_price_cents == 41

    # ------------------------------------------------------------------
    # Exits using all canonical forms
    # ------------------------------------------------------------------

    def test_sell_yes_closes_long_yes(self):
        """SELL_YES closes a long YES position."""
        position = self._make_position("yes", contracts=1, price=50)
        position.apply_fill(contracts=1, price_cents=60, fee_cents=2, side="yes", action="sell")

        assert position.contracts == 0

    def test_buy_no_closes_long_yes(self):
        """BUY_NO is economically SELL_YES and closes a long YES position."""
        position = self._make_position("yes", contracts=1, price=50)
        position.apply_fill(contracts=1, price_cents=40, fee_cents=2, side="no", action="buy")

        assert position.contracts == 0

    def test_sell_no_closes_long_no(self):
        """SELL_NO closes a long NO position."""
        position = self._make_position("no", contracts=1, price=50)
        position.apply_fill(contracts=1, price_cents=60, fee_cents=2, side="no", action="sell")

        assert position.contracts == 0

    def test_buy_yes_closes_long_no(self):
        """BUY_YES is economically SELL_NO and closes a long NO position."""
        position = self._make_position("no", contracts=1, price=50)
        position.apply_fill(contracts=1, price_cents=40, fee_cents=2, side="yes", action="buy")

        assert position.contracts == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
