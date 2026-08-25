"""Unit tests for canonical YES/NO price space model.

Tests the binary_price_space module to ensure:
- Price transformations work correctly
- Side mapping is consistent
- Price range checks are accurate
- Duality invariant is maintained
"""

import pytest
from merid.event_venues.kalshi.binary_price_space import (
    yes_to_no_price,
    no_to_yes_price,
    derive_yes_ask_from_no_bid,
    derive_no_ask_from_yes_bid,
    validate_duality,
    to_kalshi_side,
    parse_kalshi_side,
    extract_outcome_side,
    extract_action,
    legacy_to_v2,
    close_book_side,
    is_price_in_canonical_range,
    is_price_in_crisis_range,
    is_price_in_flb_trading_range,
    is_price_in_flb_edge_band,
    clamp_to_canonical_range,
    clamp_to_crisis_range,
    detect_extreme_price_condition,
    get_price_range_for_condition,
    CanonicalBinaryMarketState,
)


class TestPriceTransformations:
    """Test YES/NO price transformation functions."""
    
    def test_yes_to_no_price(self):
        """Test YES to NO price conversion."""
        assert yes_to_no_price(25) == 75
        assert yes_to_no_price(1) == 99
        assert yes_to_no_price(50) == 50
        assert yes_to_no_price(99) == 1
        assert yes_to_no_price(0) == 100
    
    def test_no_to_yes_price(self):
        """Test NO to YES price conversion."""
        assert no_to_yes_price(75) == 25
        assert no_to_yes_price(99) == 1
        assert no_to_yes_price(50) == 50
        assert no_to_yes_price(1) == 99
        assert no_to_yes_price(100) == 0
    
    def test_derive_yes_ask_from_no_bid(self):
        """Test YES ask derivation from NO bid."""
        assert derive_yes_ask_from_no_bid(75) == 25
        assert derive_yes_ask_from_no_bid(99) == 1
        assert derive_yes_ask_from_no_bid(50) == 50
    
    def test_derive_no_ask_from_yes_bid(self):
        """Test NO ask derivation from YES bid."""
        assert derive_no_ask_from_yes_bid(25) == 75
        assert derive_no_ask_from_yes_bid(1) == 99
        assert derive_no_ask_from_yes_bid(50) == 50
    
    def test_duality_roundtrip(self):
        """Test that transformations are inverses of each other."""
        for price in [1, 10, 25, 50, 75, 90, 99]:
            assert yes_to_no_price(no_to_yes_price(price)) == price
            assert no_to_yes_price(yes_to_no_price(price)) == price


class TestDualityValidation:
    """Test duality invariant validation."""
    
    def test_validate_duality_valid(self):
        """Test validation of valid duality pairs."""
        assert validate_duality(25, 75) == True
        assert validate_duality(50, 50) == True
        assert validate_duality(1, 99) == True
        assert validate_duality(25, 74, tolerance_cents=1) == True  # Within tolerance
    
    def test_validate_duality_invalid(self):
        """Test validation of invalid duality pairs."""
        assert validate_duality(25, 74, tolerance_cents=0) == False  # Strict validation
        assert validate_duality(50, 49, tolerance_cents=0) == False  # Strict validation
        assert validate_duality(25, 73, tolerance_cents=0) == False  # More extreme case


class TestSideMapping:
    """Test side mapping to Kalshi format."""
    
    def test_to_kalshi_side(self):
        """Test conversion to Kalshi format."""
        assert to_kalshi_side("yes", "buy") == "BUY_YES"
        assert to_kalshi_side("yes", "sell") == "SELL_YES"
        assert to_kalshi_side("no", "buy") == "BUY_NO"
        assert to_kalshi_side("no", "sell") == "SELL_NO"
        # Case insensitive
        assert to_kalshi_side("YES", "BUY") == "BUY_YES"
        assert to_kalshi_side("No", "SeLl") == "SELL_NO"
    
    def test_to_kalshi_side_invalid(self):
        """Test invalid side/action combinations."""
        with pytest.raises(ValueError):
            to_kalshi_side("invalid", "buy")
        with pytest.raises(ValueError):
            to_kalshi_side("yes", "invalid")
    
    def test_parse_kalshi_side(self):
        """Test parsing Kalshi format."""
        assert parse_kalshi_side("BUY_YES") == ("yes", "buy")
        assert parse_kalshi_side("SELL_YES") == ("yes", "sell")
        assert parse_kalshi_side("BUY_NO") == ("no", "buy")
        assert parse_kalshi_side("SELL_NO") == ("no", "sell")
        # Case insensitive
        assert parse_kalshi_side("buy_yes") == ("yes", "buy")
    
    def test_parse_kalshi_side_invalid(self):
        """Test invalid Kalshi format."""
        with pytest.raises(ValueError):
            parse_kalshi_side("INVALID")
        with pytest.raises(ValueError):
            parse_kalshi_side("BUY_MAYBE")
    
    def test_extract_outcome_side(self):
        """Test extracting outcome side from Kalshi format."""
        assert extract_outcome_side("BUY_YES") == "yes"
        assert extract_outcome_side("SELL_YES") == "yes"
        assert extract_outcome_side("BUY_NO") == "no"
        assert extract_outcome_side("SELL_NO") == "no"
    
    def test_extract_action(self):
        """Test extracting action from Kalshi format."""
        assert extract_action("BUY_YES") == "buy"
        assert extract_action("SELL_YES") == "sell"
        assert extract_action("BUY_NO") == "buy"
        assert extract_action("SELL_NO") == "sell"


class TestLegacyToV2:
    """Test the single canonical legacy-to-V2 conversion."""

    def test_legacy_to_v2_matrix(self):
        assert legacy_to_v2("buy", "yes", 55) == ("bid", 55)
        assert legacy_to_v2("sell", "yes", 55) == ("ask", 55)
        assert legacy_to_v2("buy", "no", 32) == ("ask", 68)
        assert legacy_to_v2("sell", "no", 32) == ("bid", 68)

    def test_legacy_to_v2_case_insensitive(self):
        assert legacy_to_v2("BUY", "NO", 40) == ("ask", 60)
        assert legacy_to_v2("Sell", "Yes", 70) == ("ask", 70)

    def test_legacy_to_v2_invalid(self):
        with pytest.raises(ValueError):
            legacy_to_v2("hold", "yes", 50)

    def test_close_book_side_exit(self):
        assert close_book_side("yes") == "ask"  # SELL_YES
        assert close_book_side("no") == "bid"   # SELL_NO

    def test_payoff_equivalence_buy_yes(self):
        """BUY_YES @ p should have same payoff as bid @ p in YES-space."""
        # Buy YES at 50c: +50c if YES resolves, -50c if NO resolves
        book_side, yes_price = legacy_to_v2("buy", "yes", 50)
        assert book_side == "bid"
        assert yes_price == 50
        # bid @ 50c: +50c if YES resolves, -50c if NO resolves
        # Economic equivalence confirmed

    def test_payoff_equivalence_sell_yes(self):
        """SELL_YES @ p should have same payoff as ask @ p in YES-space."""
        # Sell YES at 50c: -50c if YES resolves, +50c if NO resolves
        book_side, yes_price = legacy_to_v2("sell", "yes", 50)
        assert book_side == "ask"
        assert yes_price == 50
        # ask @ 50c: -50c if YES resolves, +50c if NO resolves
        # Economic equivalence confirmed

    def test_payoff_equivalence_buy_no(self):
        """BUY_NO @ p should have same payoff as ask @ (100-p) in YES-space."""
        # Buy NO at 25c: +75c if NO resolves, -25c if YES resolves
        book_side, yes_price = legacy_to_v2("buy", "no", 25)
        assert book_side == "ask"
        assert yes_price == 75  # 100 - 25
        # ask @ 75c (sell YES): -75c if YES resolves, +75c if NO resolves
        # Economic equivalence confirmed

    def test_payoff_equivalence_sell_no(self):
        """SELL_NO @ p should have same payoff as bid @ (100-p) in YES-space."""
        # Sell NO at 25c: -75c if NO resolves, +25c if YES resolves
        book_side, yes_price = legacy_to_v2("sell", "no", 25)
        assert book_side == "bid"
        assert yes_price == 75  # 100 - 25
        # bid @ 75c (buy YES): +75c if YES resolves, -75c if NO resolves
        # Economic equivalence confirmed


class TestPriceRangeChecking:
    """Test price range checking functions."""
    
    def test_is_price_in_canonical_range(self):
        """Test canonical entry range (symmetric 10c-75c)."""
        # CRITICAL FIX (2026-08-14): Fail-closed to 10c-75c to prevent
        # extreme longshot / shortshot fills that drained the bankroll.
        assert is_price_in_canonical_range(10, "yes") == True
        assert is_price_in_canonical_range(75, "yes") == True
        assert is_price_in_canonical_range(50, "yes") == True
        assert is_price_in_canonical_range(9, "yes") == False
        assert is_price_in_canonical_range(76, "yes") == False
        assert is_price_in_canonical_range(10, "no") == True
        assert is_price_in_canonical_range(75, "no") == True
        assert is_price_in_canonical_range(50, "no") == True
        assert is_price_in_canonical_range(9, "no") == False
        assert is_price_in_canonical_range(76, "no") == False

    def test_is_price_in_crisis_range(self):
        """Test crisis range (side-aware: YES 1c-99c, NO 5c-99c)."""
        # YES side
        assert is_price_in_crisis_range(1, "yes") == True
        assert is_price_in_crisis_range(99, "yes") == True
        assert is_price_in_crisis_range(50, "yes") == True
        assert is_price_in_crisis_range(0, "yes") == False
        assert is_price_in_crisis_range(100, "yes") == False
        # NO side
        assert is_price_in_crisis_range(5, "no") == True
        assert is_price_in_crisis_range(99, "no") == True
        assert is_price_in_crisis_range(50, "no") == True
        assert is_price_in_crisis_range(4, "no") == False
        assert is_price_in_crisis_range(100, "no") == False

    def test_is_price_in_flb_trading_range(self):
        """Test FLB-aware trading range (prevents capital destruction)."""
        from merid.event_venues.kalshi.binary_price_space import (
            is_price_in_flb_trading_range
        )

        # CRITICAL FIX (2026-08-01): Updated FLB thresholds for 15m crypto volatility
        # YES side: avoid FLB capital destruction (<5¢) and fee drag (>85¢)
        assert is_price_in_flb_trading_range(4, "yes") == False  # FLB capital destruction
        assert is_price_in_flb_trading_range(5, "yes") == True  # Minimum safe (lowered from 10c)
        assert is_price_in_flb_trading_range(50, "yes") == True  # Good
        assert is_price_in_flb_trading_range(85, "yes") == True  # Maximum safe
        assert is_price_in_flb_trading_range(90, "yes") == False  # Fee drag zone

        # NO side: minimum 15¢, max 95¢ (edge band included, lowered from 25c)
        assert is_price_in_flb_trading_range(14, "no") == False  # Too low
        assert is_price_in_flb_trading_range(15, "no") == True  # Minimum safe (lowered from 25c)
        assert is_price_in_flb_trading_range(50, "no") == True  # Good
        assert is_price_in_flb_trading_range(95, "no") == True  # Edge band included
        assert is_price_in_flb_trading_range(99, "no") == False  # Too high

    def test_is_price_in_flb_edge_band(self):
        """Test FLB edge band (systematically underpriced NO contracts)."""
        from merid.event_venues.kalshi.binary_price_space import (
            is_price_in_flb_edge_band
        )

        # NO edge band: 88-95¢ (systematically underpriced)
        assert is_price_in_flb_edge_band(88, "no") == True
        assert is_price_in_flb_edge_band(90, "no") == True
        assert is_price_in_flb_edge_band(95, "no") == True
        assert is_price_in_flb_edge_band(87, "no") == False
        assert is_price_in_flb_edge_band(96, "no") == False

        # YES contracts don't have documented edge band
        assert is_price_in_flb_edge_band(90, "yes") == False
        assert is_price_in_flb_edge_band(50, "yes") == False
    
    def test_clamp_to_canonical_range(self):
        """Test clamping to canonical entry range (10c-75c)."""
        # CRITICAL FIX (2026-08-14): Fail-closed to 10c-75c.
        assert clamp_to_canonical_range(5) == 10
        assert clamp_to_canonical_range(90) == 75
        assert clamp_to_canonical_range(50) == 50
        assert clamp_to_canonical_range(0) == 10
        assert clamp_to_canonical_range(100) == 75
    
    def test_clamp_to_crisis_range(self):
        """Test clamping to crisis range."""
        assert clamp_to_crisis_range(1) == 5
        assert clamp_to_crisis_range(99) == 99
        assert clamp_to_crisis_range(50) == 50
        assert clamp_to_crisis_range(0) == 5
        assert clamp_to_crisis_range(100) == 99
    
    def test_detect_extreme_price_condition(self):
        """Test extreme price condition detection."""
        assert detect_extreme_price_condition(5, 95) == True
        assert detect_extreme_price_condition(1, 99) == True
        assert detect_extreme_price_condition(90, 10) == True
        assert detect_extreme_price_condition(40, 60) == False
        assert detect_extreme_price_condition(50, 50) == False
    
    def test_get_price_range_for_condition(self):
        """Test getting price range for condition."""
        # CRITICAL FIX (2026-08-14): Normal regime is canonical 10c-75c.
        assert get_price_range_for_condition(False) == (10, 75)
        assert get_price_range_for_condition(True) == (5, 99)   # Extreme (crisis)


class TestCanonicalBinaryMarketState:
    """Test CanonicalBinaryMarketState dataclass."""
    
    def test_initialization(self):
        """Test state initialization."""
        state = CanonicalBinaryMarketState(
            ticker="KXBTC-TEST",
            yes_bid_cents=25,
            yes_ask_cents=30,
            no_bid_cents=70,
            no_ask_cents=75,
        )
        assert state.ticker == "KXBTC-TEST"
        assert state.yes_bid_cents == 25
        assert state.yes_ask_cents == 30
        assert state.no_bid_cents == 70
        assert state.no_ask_cents == 75
    
    def test_yes_mid_cents(self):
        """Test YES mid-price calculation."""
        state = CanonicalBinaryMarketState(
            ticker="KXBTC-TEST",
            yes_bid_cents=25,
            yes_ask_cents=30,
        )
        assert state.yes_mid_cents == 27.5
    
    def test_no_mid_cents(self):
        """Test NO mid-price calculation."""
        state = CanonicalBinaryMarketState(
            ticker="KXBTC-TEST",
            no_bid_cents=70,
            no_ask_cents=75,
        )
        assert state.no_mid_cents == 72.5
    
    def test_yes_spread_cents(self):
        """Test YES spread calculation."""
        state = CanonicalBinaryMarketState(
            ticker="KXBTC-TEST",
            yes_bid_cents=25,
            yes_ask_cents=30,
        )
        assert state.yes_spread_cents == 5
    
    def test_no_spread_cents(self):
        """Test NO spread calculation."""
        state = CanonicalBinaryMarketState(
            ticker="KXBTC-TEST",
            no_bid_cents=70,
            no_ask_cents=75,
        )
        assert state.no_spread_cents == 5
    
    def test_yes_implied_prob(self):
        """Test YES implied probability."""
        state = CanonicalBinaryMarketState(
            ticker="KXBTC-TEST",
            yes_bid_cents=25,
            yes_ask_cents=30,
        )
        assert state.yes_implied_prob == 0.275
    
    def test_no_implied_prob(self):
        """Test NO implied probability."""
        state = CanonicalBinaryMarketState(
            ticker="KXBTC-TEST",
            no_bid_cents=70,
            no_ask_cents=75,
        )
        assert state.no_implied_prob == 0.725
    
    def test_validate_duality_valid(self):
        """Test duality validation with valid state."""
        state = CanonicalBinaryMarketState(
            ticker="KXBTC-TEST",
            yes_ask_cents=25,
            no_bid_cents=75,
        )
        assert state.validate_duality() == True
    
    def test_validate_duality_invalid(self):
        """Test duality validation with invalid state."""
        state = CanonicalBinaryMarketState(
            ticker="KXBTC-TEST",
            yes_ask_cents=25,
            no_bid_cents=74,  # Should be 75 for duality
        )
        assert state.validate_duality(tolerance_cents=0) == False  # Strict validation
    
    def test_derive_missing_prices(self):
        """Test deriving missing prices using duality."""
        state = CanonicalBinaryMarketState(
            ticker="KXBTC-TEST",
            yes_bid_cents=25,
            no_bid_cents=75,
        )
        # YES_ask and NO_ask are missing
        assert state.yes_ask_cents is None
        assert state.no_ask_cents is None
        
        # Derive missing prices
        state.derive_missing_prices()
        
        # Should be derived from duality
        assert state.yes_ask_cents == 25  # 100 - 75
        assert state.no_ask_cents == 75  # 100 - 25
    
    def test_is_yes_in_range_normal(self):
        """Test YES price in range check (normal regime)."""
        # CRITICAL FIX (2026-08-14): Normal canonical range is 10c-75c.
        state = CanonicalBinaryMarketState(
            ticker="KXBTC-TEST",
            yes_bid_cents=50,
        )
        assert state.is_yes_in_range(is_extreme=False) == True
        
        state.yes_bid_cents = 10
        assert state.is_yes_in_range(is_extreme=False) == True
        
        state.yes_bid_cents = 75
        assert state.is_yes_in_range(is_extreme=False) == True
        
        state.yes_bid_cents = 9
        assert state.is_yes_in_range(is_extreme=False) == False
        
        state.yes_bid_cents = 76
        assert state.is_yes_in_range(is_extreme=False) == False
    
    def test_is_yes_in_range_extreme(self):
        """Test YES price in range check (extreme regime)."""
        # CRITICAL FIX (2026-08-01): YES crisis range is 1c-99c
        state = CanonicalBinaryMarketState(
            ticker="KXBTC-TEST",
            yes_bid_cents=5,
        )
        assert state.is_yes_in_range(is_extreme=True) == True
        
        state.yes_bid_cents = 1
        assert state.is_yes_in_range(is_extreme=True) == True  # Valid in crisis range
        
        state.yes_bid_cents = 0
        assert state.is_yes_in_range(is_extreme=True) == False  # Below crisis min
    
    def test_is_no_in_range_normal(self):
        """Test NO price in range check (normal regime)."""
        # CRITICAL FIX (2026-08-14): Normal canonical range is 10c-75c.
        state = CanonicalBinaryMarketState(
            ticker="KXBTC-TEST",
            no_bid_cents=50,
        )
        assert state.is_no_in_range(is_extreme=False) == True
        
        state.no_bid_cents = 10
        assert state.is_no_in_range(is_extreme=False) == True
        
        state.no_bid_cents = 75
        assert state.is_no_in_range(is_extreme=False) == True
        
        state.no_bid_cents = 9
        assert state.is_no_in_range(is_extreme=False) == False
        
        state.no_bid_cents = 76
        assert state.is_no_in_range(is_extreme=False) == False
    
    def test_is_no_in_range_extreme(self):
        """Test NO price in range check (extreme regime)."""
        state = CanonicalBinaryMarketState(
            ticker="KXBTC-TEST",
            no_bid_cents=99,
        )
        assert state.is_no_in_range(is_extreme=True) == True
        
        state.no_bid_cents = 100
        assert state.is_no_in_range(is_extreme=True) == False
    
    def test_to_dict(self):
        """Test conversion to dictionary."""
        state = CanonicalBinaryMarketState(
            ticker="KXBTC-TEST",
            yes_bid_cents=25,
            yes_ask_cents=30,
            no_bid_cents=70,
            no_ask_cents=75,
        )
        d = state.to_dict()
        assert d["ticker"] == "KXBTC-TEST"
        assert d["yes_bid_cents"] == 25
        assert d["yes_ask_cents"] == 30
        assert d["no_bid_cents"] == 70
        assert d["no_ask_cents"] == 75
        assert d["yes_mid_cents"] == 27.5
        assert d["no_mid_cents"] == 72.5


class TestV2Normalization:
    """Test V2 fill normalization and invariants."""

    def test_normalize_legacy_to_v2(self):
        """Normalize legacy (action, outcome) to V2 (outcome_side, book_side)."""
        # Per Kalshi docs: buy-YES and sell-NO produce YES exposure
        # buy-NO and sell-YES produce NO exposure
        def normalize_legacy(action: str, outcome: str) -> tuple[str, str]:
            book_side, _ = legacy_to_v2(action, outcome, 50)
            # Determine outcome_side from economic exposure
            if action == "buy":
                outcome_side = outcome
            else:  # sell
                # sell YES -> NO exposure, sell NO -> YES exposure
                outcome_side = "no" if outcome == "yes" else "yes"
            return outcome_side, book_side

        assert normalize_legacy("buy", "yes") == ("yes", "bid")
        assert normalize_legacy("sell", "no") == ("yes", "bid")
        assert normalize_legacy("buy", "no") == ("no", "ask")
        assert normalize_legacy("sell", "yes") == ("no", "ask")

    def test_validate_v2_invariant(self):
        """Validate the V2 invariant: (book_side == "bid") == (outcome_side == "yes")."""
        def validate_v2(outcome_side: str, book_side: str) -> bool:
            return (book_side == "bid") == (outcome_side == "yes")

        assert validate_v2("yes", "bid")
        assert validate_v2("no", "ask")
        assert not validate_v2("yes", "ask")
        assert not validate_v2("no", "bid")

    def test_api_to_economic_equivalence(self):
        """API-to-economic equivalence: legacy_to_v2 mapping is correct."""
        assert legacy_to_v2("buy", "no", 25) == ("ask", 75)
        assert legacy_to_v2("sell", "no", 25) == ("bid", 75)
        assert legacy_to_v2("buy", "yes", 50) == ("bid", 50)
        assert legacy_to_v2("sell", "yes", 50) == ("ask", 50)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
