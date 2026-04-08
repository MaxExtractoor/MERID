"""Tests for KalshiMarketCatalog strike detection logic."""

from merid.event_venues.kalshi.market_catalog import KalshiMarketCatalog


class TestStrikeDetection:
    """Tests for _detect_strikes static method."""

    def test_ticker_embedded_strike_integer(self):
        """Should parse integer strikes from ticker format."""
        text = "KXBTC-26APR0722-T95000"
        strikes = KalshiMarketCatalog._detect_strikes(text)

        assert "strike" in strikes
        assert strikes["strike"] == 95000.0

    def test_ticker_embedded_strike_with_decimals(self):
        """Should parse decimal strikes from ticker format (e.g., KXETH-T2839.99)."""
        text = "KXETH-26APR0722-T2839.99"
        strikes = KalshiMarketCatalog._detect_strikes(text)

        assert "strike" in strikes
        assert strikes["strike"] == 2839.99

    def test_ticker_embedded_strike_small_decimal(self):
        """Should parse small decimal strikes (e.g., XRP at $2.0399)."""
        text = "KXXRP-15M-T2.0399"
        strikes = KalshiMarketCatalog._detect_strikes(text)

        assert "strike" in strikes
        assert strikes["strike"] == 2.0399

    def test_ticker_embedded_strike_leading_decimal(self):
        """Should parse strikes with leading decimals (e.g., DOGE at $0.35)."""
        text = "KXDOGE-DAILY-T0.35"
        strikes = KalshiMarketCatalog._detect_strikes(text)

        assert "strike" in strikes
        assert strikes["strike"] == 0.35

    def test_ticker_embedded_strike_many_decimals(self):
        """Should parse strikes with multiple decimal places."""
        text = "KXSOL-1H-T123.456789"
        strikes = KalshiMarketCatalog._detect_strikes(text)

        assert "strike" in strikes
        assert strikes["strike"] == 123.456789

    def test_ticker_strike_case_insensitive(self):
        """Should parse strikes case-insensitively."""
        # Lowercase 't'
        text_lower = "KXBTC-26APR0722-t95000"
        strikes_lower = KalshiMarketCatalog._detect_strikes(text_lower)

        # Uppercase 'T'
        text_upper = "KXBTC-26APR0722-T95000"
        strikes_upper = KalshiMarketCatalog._detect_strikes(text_upper)

        assert strikes_lower["strike"] == 95000.0
        assert strikes_upper["strike"] == 95000.0

    def test_ticker_strike_priority_over_text(self):
        """Ticker-embedded strike should take priority over text-based parsing."""
        # Both ticker (T95000) and text ("above 90000") present
        text = "KXBTC-26APR0722-T95000 Will BTC be above 90000?"
        strikes = KalshiMarketCatalog._detect_strikes(text)

        # Should use ticker value (95000) not text value (90000)
        assert strikes["strike"] == 95000.0

    def test_text_based_strike_fallback(self):
        """Should fall back to text-based parsing when no ticker strike."""
        text = "Will BTC be above 50,000 by end of day?"
        strikes = KalshiMarketCatalog._detect_strikes(text)

        assert "strike" in strikes
        assert strikes["strike"] == 50000.0

    def test_text_based_strike_with_dollar_sign(self):
        """Should parse text strikes with dollar signs."""
        text = "Will ETH trade below $2,500?"
        strikes = KalshiMarketCatalog._detect_strikes(text)

        assert "strike" in strikes
        assert strikes["strike"] == 2500.0

    def test_text_based_strike_decimal(self):
        """Should parse text strikes with decimals."""
        text = "Will SOL be above $150.50?"
        strikes = KalshiMarketCatalog._detect_strikes(text)

        assert "strike" in strikes
        assert strikes["strike"] == 150.50

    def test_range_strikes_between(self):
        """Should parse range strikes (floor and cap)."""
        text = "Will BTC trade between 90,000 and 100,000?"
        strikes = KalshiMarketCatalog._detect_strikes(text)

        assert "floor" in strikes
        assert "cap" in strikes
        assert strikes["floor"] == 90000.0
        assert strikes["cap"] == 100000.0

    def test_range_strikes_with_dollar_signs(self):
        """Should parse range strikes with dollar signs."""
        text = "between $1,000 and $2,000"
        strikes = KalshiMarketCatalog._detect_strikes(text)

        assert strikes["floor"] == 1000.0
        assert strikes["cap"] == 2000.0

    def test_range_strikes_with_decimals(self):
        """Should parse range strikes with decimals."""
        text = "between 1.5 and 2.5"
        strikes = KalshiMarketCatalog._detect_strikes(text)

        assert strikes["floor"] == 1.5
        assert strikes["cap"] == 2.5

    def test_ticker_strike_plus_range(self):
        """Should parse both ticker strike and range if both present."""
        text = "KXBTC-T95000 between 90,000 and 100,000"
        strikes = KalshiMarketCatalog._detect_strikes(text)

        # Ticker strike takes priority for "strike" key
        assert strikes["strike"] == 95000.0
        # Range should also be parsed
        assert strikes["floor"] == 90000.0
        assert strikes["cap"] == 100000.0

    def test_no_strike_returns_empty_dict(self):
        """Should return empty dict when no strikes found."""
        text = "Will the market be open tomorrow?"
        strikes = KalshiMarketCatalog._detect_strikes(text)

        assert strikes == {}

    def test_invalid_ticker_strike_format(self):
        """Should handle malformed ticker strikes gracefully."""
        # Missing number after T
        text = "KXBTC-26APR0722-T"
        strikes = KalshiMarketCatalog._detect_strikes(text)

        # Should either skip or handle gracefully (not crash)
        # Implementation may return empty dict or fall back to text parsing
        assert isinstance(strikes, dict)

    def test_multiple_ticker_strikes_uses_first(self):
        """Should use first ticker strike if multiple present."""
        text = "KXBTC-T95000-T96000"
        strikes = KalshiMarketCatalog._detect_strikes(text)

        # Should use first occurrence
        assert strikes["strike"] == 95000.0

    def test_real_world_btc_ticker(self):
        """Test with real Kalshi BTC ticker format."""
        text = "KXBTC-26APR0722-T95000"
        strikes = KalshiMarketCatalog._detect_strikes(text)

        assert strikes["strike"] == 95000.0

    def test_real_world_eth_ticker_decimal(self):
        """Test with real Kalshi ETH ticker with decimals."""
        text = "KXETH-26APR0722-T2839.99"
        strikes = KalshiMarketCatalog._detect_strikes(text)

        assert strikes["strike"] == 2839.99

    def test_real_world_xrp_ticker_small_decimal(self):
        """Test with real Kalshi XRP ticker with small decimals."""
        text = "KXXRP-15M-T2.0399"
        strikes = KalshiMarketCatalog._detect_strikes(text)

        assert strikes["strike"] == 2.0399

    def test_real_world_sol_ticker(self):
        """Test with real Kalshi SOL ticker."""
        text = "KXSOL-DAILY-T150.25"
        strikes = KalshiMarketCatalog._detect_strikes(text)

        assert strikes["strike"] == 150.25

    def test_real_world_doge_ticker(self):
        """Test with real Kalshi DOGE ticker."""
        text = "KXDOGE-1H-T0.35"
        strikes = KalshiMarketCatalog._detect_strikes(text)

        assert strikes["strike"] == 0.35
