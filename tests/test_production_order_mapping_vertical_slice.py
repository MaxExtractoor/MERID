"""
Production Order Mapping Vertical Slice Tests

These tests verify the complete intent-to-exposure-to-venue mapping path
for the 15-minute Kalshi crypto trading system across all 5 assets.

Each slice simulates:
1. Strategy intent and signal
2. Risk + bankroll context
3. Order construction through the live pipeline
4. Venue echo validation

CRITICAL FIX (2026-07-19): Prevents "buy NO" → "buy YES" mapping bugs by
testing the complete semantic contract at every layer.

Markers:
- @pytest.mark.production_audit: Indicates these are production-critical tests
- @pytest.mark.order_mapping: Specific to order mapping invariants
"""

import pytest
from datetime import datetime, timezone

from merid.prediction.intent_contract import (
    StrategyIntent,
    EntryExit,
    ExposureLeg,
    ExposureChange,
    KalshiSidePayload,
    IntentContract,
    map_intent_to_exposure,
    map_exposure_to_kalshi_side,
    build_entry_order,
    build_exit_order,
    validate_intent_exposure_consistency,
    validate_fill_against_intent,
    compute_net_exposure_from_fill,
)


# =============================================================================
# Test Fixtures
# =============================================================================

@pytest.fixture(params=["BTC", "ETH", "SOL", "XRP", "DOGE"])
def asset(request):
    """All 5 crypto assets must be tested."""
    return request.param


@pytest.fixture
def sample_ticker(asset):
    """Sample Kalshi ticker for each asset."""
    return f"KX{asset}D-25JUL-T100000"


@pytest.fixture
def entry_price_cents():
    """Canonical entry price within 10-75c range."""
    return 35  # 35 cents


@pytest.fixture
def exit_price_cents():
    """Exit price near cash-out (99c)."""
    return 99


@pytest.fixture
def canonical_risk_config():
    """Canonical Kalshi risk config for 15m crypto profile."""
    return {
        "max_open_price_cents": 75,
        "min_entry_price_cents": 10,
        "per_contract_value_usd": 1.0,
        "max_contracts_per_order": 1,
    }


# =============================================================================
# Entry Order Vertical Slices
# =============================================================================

@pytest.mark.production_audit
@pytest.mark.order_mapping
class TestLongYESTryEntry:
    """Test BULLISH_EVENT → entry → YES exposure (buy YES)."""
    
    def test_bullish_entry_buy_yes(self, asset, sample_ticker, entry_price_cents):
        """BULLISH_EVENT intent should result in BUY YES order."""
        # Build entry order
        contract = build_entry_order(
            intent=StrategyIntent.BULLISH_EVENT,
            asset=asset,
            ticker=sample_ticker,
            price_cents=entry_price_cents,
            magnitude=1,
            rationale="Bullish signal: +7% edge",
        )
        
        # Validate contract
        is_valid, error = contract.validate()
        assert is_valid, f"Contract validation failed: {error}"
        
        # Check intent level
        assert contract.strategy_intent == StrategyIntent.BULLISH_EVENT
        assert contract.entry_or_exit == EntryExit.ENTRY
        assert contract.target_leg == ExposureLeg.YES
        
        # Check exposure level
        assert contract.exposure_change.leg == ExposureLeg.YES
        assert contract.exposure_change.direction == "increase"
        assert contract.exposure_change.magnitude == 1
        
        # Check venue level
        assert contract.kalshi_payload.side == "yes"
        assert contract.kalshi_payload.action == "buy"
        assert contract.kalshi_payload.price_cents == entry_price_cents
        assert contract.kalshi_payload.to_kalshi_format() == "BUY_YES"
        
        # Check position state
        assert contract.current_position is None
        assert contract.pre_position_size == 0
        assert contract.expected_post_position_size == 1
    
    def test_bullish_entry_exposure_mapping(self, asset):
        """Test intent → exposure mapping for BULLISH_EVENT entry."""
        exposure = map_intent_to_exposure(
            intent=StrategyIntent.BULLISH_EVENT,
            current_position=None,
            magnitude=1,
        )
        
        assert exposure.leg == ExposureLeg.YES
        assert exposure.direction == "increase"
        assert exposure.magnitude == 1
    
    def test_bullish_entry_venue_mapping(self, entry_price_cents):
        """Test exposure → Kalshi payload mapping for YES entry."""
        exposure = ExposureChange(leg=ExposureLeg.YES, direction="increase", magnitude=1)
        payload = map_exposure_to_kalshi_side(exposure, entry_price_cents)
        
        assert payload.side == "yes"
        assert payload.action == "buy"
        assert payload.price_cents == entry_price_cents


@pytest.mark.production_audit
@pytest.mark.order_mapping
class TestLongNOTryEntry:
    """Test BEARISH_EVENT → entry → NO exposure (buy NO)."""
    
    def test_bearish_entry_buy_no(self, asset, sample_ticker, entry_price_cents):
        """BEARISH_EVENT intent should result in BUY NO order."""
        # Build entry order
        contract = build_entry_order(
            intent=StrategyIntent.BEARISH_EVENT,
            asset=asset,
            ticker=sample_ticker,
            price_cents=entry_price_cents,
            magnitude=1,
            rationale="Bearish signal: +7% edge",
        )
        
        # Validate contract
        is_valid, error = contract.validate()
        assert is_valid, f"Contract validation failed: {error}"
        
        # Check intent level
        assert contract.strategy_intent == StrategyIntent.BEARISH_EVENT
        assert contract.entry_or_exit == EntryExit.ENTRY
        assert contract.target_leg == ExposureLeg.NO
        
        # Check exposure level
        assert contract.exposure_change.leg == ExposureLeg.NO
        assert contract.exposure_change.direction == "increase"
        assert contract.exposure_change.magnitude == 1
        
        # Check venue level
        assert contract.kalshi_payload.side == "no"
        assert contract.kalshi_payload.action == "buy"
        assert contract.kalshi_payload.price_cents == entry_price_cents
        assert contract.kalshi_payload.to_kalshi_format() == "BUY_NO"
        
        # Check position state
        assert contract.current_position is None
        assert contract.pre_position_size == 0
        assert contract.expected_post_position_size == 1
    
    def test_bearish_entry_exposure_mapping(self, asset):
        """Test intent → exposure mapping for BEARISH_EVENT entry."""
        exposure = map_intent_to_exposure(
            intent=StrategyIntent.BEARISH_EVENT,
            current_position=None,
            magnitude=1,
        )
        
        assert exposure.leg == ExposureLeg.NO
        assert exposure.direction == "increase"
        assert exposure.magnitude == 1
    
    def test_bearish_entry_venue_mapping(self, entry_price_cents):
        """Test exposure → Kalshi payload mapping for NO entry."""
        exposure = ExposureChange(leg=ExposureLeg.NO, direction="increase", magnitude=1)
        payload = map_exposure_to_kalshi_side(exposure, entry_price_cents)
        
        assert payload.side == "no"
        assert payload.action == "buy"
        assert payload.price_cents == entry_price_cents


# =============================================================================
# Exit Order Vertical Slices
# =============================================================================

@pytest.mark.production_audit
@pytest.mark.order_mapping
class TestLongYESTryExit:
    """Test exit from YES position (sell YES or buy NO equivalent)."""
    
    def test_yes_position_exit_sell_yes(self, asset, sample_ticker, exit_price_cents):
        """Exit YES position via SELL YES (direct action)."""
        # Build exit order
        contract = build_exit_order(
            current_position=ExposureLeg.YES,
            asset=asset,
            ticker=sample_ticker,
            price_cents=exit_price_cents,
            magnitude=1,
            rationale="Take profit at 99c",
        )
        
        # Validate contract
        is_valid, error = contract.validate()
        assert is_valid, f"Contract validation failed: {error}"
        
        # Check intent level
        assert contract.strategy_intent == StrategyIntent.NEUTRAL  # Pure exit
        assert contract.entry_or_exit == EntryExit.EXIT
        assert contract.target_leg == ExposureLeg.YES
        
        # Check exposure level
        assert contract.exposure_change.leg == ExposureLeg.YES
        assert contract.exposure_change.direction == "decrease"
        assert contract.exposure_change.magnitude == 1
        
        # Check venue level (default: direct action)
        assert contract.kalshi_payload.side == "yes"
        assert contract.kalshi_payload.action == "sell"
        assert contract.kalshi_payload.price_cents == exit_price_cents
        assert contract.kalshi_payload.to_kalshi_format() == "SELL_YES"
        
        # Check position state
        assert contract.current_position == ExposureLeg.YES
        assert contract.pre_position_size == 1
        assert contract.expected_post_position_size == 0
    
    def test_yes_position_exit_buy_no_equivalent(self, asset, sample_ticker, exit_price_cents):
        """Exit YES position via BUY NO (economically equivalent)."""
        # Build exit order with liquidity preference
        contract = build_exit_order(
            current_position=ExposureLeg.YES,
            asset=asset,
            ticker=sample_ticker,
            price_cents=exit_price_cents,
            magnitude=1,
            prefer_liquidity_side="no",
            rationale="Take profit via NO side for better liquidity",
        )
        
        # Validate contract
        is_valid, error = contract.validate()
        assert is_valid, f"Contract validation failed: {error}"
        
        # Check venue level (equivalent action)
        assert contract.kalshi_payload.side == "no"
        assert contract.kalshi_payload.action == "buy"
        # Price should be complementary (100 - exit_price)
        assert contract.kalshi_payload.price_cents == 100 - exit_price_cents
        assert contract.kalshi_payload.to_kalshi_format() == "BUY_NO"
        
        # Exposure should still be YES decrease
        assert contract.exposure_change.leg == ExposureLeg.YES
        assert contract.exposure_change.direction == "decrease"


@pytest.mark.production_audit
@pytest.mark.order_mapping
class TestLongNOTryExit:
    """Test exit from NO position (sell NO or buy YES equivalent)."""
    
    def test_no_position_exit_sell_no(self, asset, sample_ticker, exit_price_cents):
        """Exit NO position via SELL NO (direct action)."""
        # Build exit order
        contract = build_exit_order(
            current_position=ExposureLeg.NO,
            asset=asset,
            ticker=sample_ticker,
            price_cents=exit_price_cents,
            magnitude=1,
            rationale="Take profit at 99c",
        )
        
        # Validate contract
        is_valid, error = contract.validate()
        assert is_valid, f"Contract validation failed: {error}"
        
        # Check intent level
        assert contract.strategy_intent == StrategyIntent.NEUTRAL  # Pure exit
        assert contract.entry_or_exit == EntryExit.EXIT
        assert contract.target_leg == ExposureLeg.NO
        
        # Check exposure level
        assert contract.exposure_change.leg == ExposureLeg.NO
        assert contract.exposure_change.direction == "decrease"
        assert contract.exposure_change.magnitude == 1
        
        # Check venue level (default: direct action)
        assert contract.kalshi_payload.side == "no"
        assert contract.kalshi_payload.action == "sell"
        assert contract.kalshi_payload.price_cents == exit_price_cents
        assert contract.kalshi_payload.to_kalshi_format() == "SELL_NO"
        
        # Check position state
        assert contract.current_position == ExposureLeg.NO
        assert contract.pre_position_size == 1
        assert contract.expected_post_position_size == 0
    
    def test_no_position_exit_buy_yes_equivalent(self, asset, sample_ticker, exit_price_cents):
        """Exit NO position via BUY YES (economically equivalent)."""
        # Build exit order with liquidity preference
        contract = build_exit_order(
            current_position=ExposureLeg.NO,
            asset=asset,
            ticker=sample_ticker,
            price_cents=exit_price_cents,
            magnitude=1,
            prefer_liquidity_side="yes",
            rationale="Take profit via YES side for better liquidity",
        )
        
        # Validate contract
        is_valid, error = contract.validate()
        assert is_valid, f"Contract validation failed: {error}"
        
        # Check venue level (equivalent action)
        assert contract.kalshi_payload.side == "yes"
        assert contract.kalshi_payload.action == "buy"
        # Price should be complementary (100 - exit_price)
        assert contract.kalshi_payload.price_cents == 100 - exit_price_cents
        assert contract.kalshi_payload.to_kalshi_format() == "BUY_YES"
        
        # Exposure should still be NO decrease
        assert contract.exposure_change.leg == ExposureLeg.NO
        assert contract.exposure_change.direction == "decrease"


# =============================================================================
# Cash-Out Invariant (99c Exit)
# =============================================================================

@pytest.mark.production_audit
@pytest.mark.order_mapping
class TestCashOutInvariant:
    """Test profit-taking exit at 99c (cash-out invariant)."""
    
    @pytest.mark.parametrize("position_leg", [ExposureLeg.YES, ExposureLeg.NO])
    def test_cash_out_at_99c(self, asset, sample_ticker, position_leg):
        """Exit at 99c should result in near-maximum profit."""
        contract = build_exit_order(
            current_position=position_leg,
            asset=asset,
            ticker=sample_ticker,
            price_cents=99,
            magnitude=1,
            rationale="Cash out at 99c",
        )
        
        # Validate contract
        is_valid, error = contract.validate()
        assert is_valid, f"Contract validation failed: {error}"
        
        # Check that we're exiting the correct leg
        assert contract.target_leg == position_leg
        assert contract.exposure_change.direction == "decrease"
        
        # Check that price is at cash-out level
        assert contract.kalshi_payload.price_cents == 99
        
        # For YES position: SELL YES at 99c
        if position_leg == ExposureLeg.YES:
            assert contract.kalshi_payload.side == "yes"
            assert contract.kalshi_payload.action == "sell"
        # For NO position: SELL NO at 99c
        else:
            assert contract.kalshi_payload.side == "no"
            assert contract.kalshi_payload.action == "sell"


# =============================================================================
# Invariant Violation Tests (Tripwires)
# =============================================================================

@pytest.mark.production_audit
@pytest.mark.order_mapping
class TestIntentExposureConsistency:
    """Test intent → exposure consistency validation."""
    
    def test_bullish_with_buy_yes_valid(self):
        """BULLISH_EVENT with BUY YES should be valid."""
        is_valid, error = validate_intent_exposure_consistency(
            intent=StrategyIntent.BULLISH_EVENT,
            kalshi_side="yes",
            kalshi_action="buy",
            current_position=None,
        )
        assert is_valid, f"Should be valid: {error}"
    
    def test_bullish_with_buy_no_invalid(self):
        """BULLISH_EVENT with BUY NO should be INVALID (wrong leg)."""
        is_valid, error = validate_intent_exposure_consistency(
            intent=StrategyIntent.BULLISH_EVENT,
            kalshi_side="no",
            kalshi_action="buy",
            current_position=None,
        )
        assert not is_valid
        assert "leg mismatch" in error.lower()
    
    def test_bearish_with_buy_no_valid(self):
        """BEARISH_EVENT with BUY NO should be valid."""
        is_valid, error = validate_intent_exposure_consistency(
            intent=StrategyIntent.BEARISH_EVENT,
            kalshi_side="no",
            kalshi_action="buy",
            current_position=None,
        )
        assert is_valid, f"Should be valid: {error}"
    
    def test_bearish_with_buy_yes_invalid(self):
        """BEARISH_EVENT with BUY YES should be INVALID (wrong leg)."""
        is_valid, error = validate_intent_exposure_consistency(
            intent=StrategyIntent.BEARISH_EVENT,
            kalshi_side="yes",
            kalshi_action="buy",
            current_position=None,
        )
        assert not is_valid
        assert "leg mismatch" in error.lower()
    
    def test_entry_with_sell_invalid(self):
        """Entry (flat position) with SELL should be INVALID."""
        is_valid, error = validate_intent_exposure_consistency(
            intent=StrategyIntent.BULLISH_EVENT,
            kalshi_side="yes",
            kalshi_action="sell",
            current_position=None,
        )
        assert not is_valid
        assert "direction mismatch" in error.lower()


@pytest.mark.production_audit
@pytest.mark.order_mapping
class TestFillValidation:
    """Test fill → intent consistency validation."""
    
    def test_fill_matches_intent(self, asset, sample_ticker, entry_price_cents):
        """Fill matching intent should be valid."""
        contract = build_entry_order(
            intent=StrategyIntent.BULLISH_EVENT,
            asset=asset,
            ticker=sample_ticker,
            price_cents=entry_price_cents,
            magnitude=1,
        )
        
        # Simulate matching fill
        is_valid, error = validate_fill_against_intent(
            intent_contract=contract,
            fill_side="yes",
            fill_action="buy",
            fill_quantity=1,
        )
        
        assert is_valid, f"Fill should match intent: {error}"
    
    def test_fill_wrong_leg_invalid(self, asset, sample_ticker, entry_price_cents):
        """Fill on wrong leg should be INVALID."""
        contract = build_entry_order(
            intent=StrategyIntent.BULLISH_EVENT,
            asset=asset,
            ticker=sample_ticker,
            price_cents=entry_price_cents,
            magnitude=1,
        )
        
        # Simulate wrong leg fill (NO instead of YES)
        is_valid, error = validate_fill_against_intent(
            intent_contract=contract,
            fill_side="no",
            fill_action="buy",
            fill_quantity=1,
        )
        
        assert not is_valid
        assert "exposure mismatch" in error.lower()
    
    def test_fill_wrong_action_invalid(self, asset, sample_ticker, entry_price_cents):
        """Fill with wrong action should be INVALID."""
        contract = build_entry_order(
            intent=StrategyIntent.BULLISH_EVENT,
            asset=asset,
            ticker=sample_ticker,
            price_cents=entry_price_cents,
            magnitude=1,
        )
        
        # Simulate wrong action (SELL instead of BUY)
        is_valid, error = validate_fill_against_intent(
            intent_contract=contract,
            fill_side="yes",
            fill_action="sell",
            fill_quantity=1,
        )
        
        assert not is_valid
        assert "exposure mismatch" in error.lower()


# =============================================================================
# Entry/Exit Guardrail Tests
# =============================================================================

@pytest.mark.production_audit
@pytest.mark.order_mapping
class TestEntryExitGuardrails:
    """Test entry/exit wiring guardrails."""
    
    def test_entry_requires_flat_position(self, asset, sample_ticker, entry_price_cents):
        """Entry order should require flat position."""
        # Try to build entry with existing position (should fail validation)
        contract = IntentContract(
            strategy_intent=StrategyIntent.BULLISH_EVENT,
            entry_or_exit=EntryExit.ENTRY,
            target_leg=ExposureLeg.YES,
            exposure_change=ExposureChange(leg=ExposureLeg.YES, direction="increase", magnitude=1),
            kalshi_payload=KalshiSidePayload(side="yes", action="buy", price_cents=entry_price_cents),
            asset=asset,
            ticker=sample_ticker,
            current_position=ExposureLeg.YES,  # WRONG: not flat
            pre_position_size=1,
            expected_post_position_size=2,
        )
        
        is_valid, error = contract.validate()
        assert not is_valid
        assert "ENTRY requires flat position" in error
    
    def test_exit_requires_existing_position(self, asset, sample_ticker, exit_price_cents):
        """Exit order should require existing position."""
        # Try to build exit with flat position (should fail validation)
        contract = IntentContract(
            strategy_intent=StrategyIntent.NEUTRAL,
            entry_or_exit=EntryExit.EXIT,
            target_leg=ExposureLeg.YES,
            exposure_change=ExposureChange(leg=ExposureLeg.YES, direction="decrease", magnitude=1),
            kalshi_payload=KalshiSidePayload(side="yes", action="sell", price_cents=exit_price_cents),
            asset=asset,
            ticker=sample_ticker,
            current_position=None,  # WRONG: no position
            pre_position_size=0,
            expected_post_position_size=0,
        )
        
        is_valid, error = contract.validate()
        assert not is_valid
        assert "EXIT requires existing position" in error
    
    def test_entry_must_increase_exposure(self, asset, sample_ticker, entry_price_cents):
        """Entry order must increase exposure."""
        # Try to build entry with decrease (should fail validation)
        contract = IntentContract(
            strategy_intent=StrategyIntent.BULLISH_EVENT,
            entry_or_exit=EntryExit.ENTRY,
            target_leg=ExposureLeg.YES,
            exposure_change=ExposureChange(leg=ExposureLeg.YES, direction="decrease", magnitude=1),  # WRONG
            kalshi_payload=KalshiSidePayload(side="yes", action="sell", price_cents=entry_price_cents),
            asset=asset,
            ticker=sample_ticker,
            current_position=None,
            pre_position_size=0,
            expected_post_position_size=0,
        )
        
        is_valid, error = contract.validate()
        assert not is_valid
        assert "ENTRY must increase exposure" in error
    
    def test_exit_must_decrease_exposure(self, asset, sample_ticker, exit_price_cents):
        """Exit order must decrease exposure."""
        # Try to build exit with increase (should fail validation)
        contract = IntentContract(
            strategy_intent=StrategyIntent.NEUTRAL,
            entry_or_exit=EntryExit.EXIT,
            target_leg=ExposureLeg.YES,
            exposure_change=ExposureChange(leg=ExposureLeg.YES, direction="increase", magnitude=1),  # WRONG
            kalshi_payload=KalshiSidePayload(side="yes", action="buy", price_cents=exit_price_cents),
            asset=asset,
            ticker=sample_ticker,
            current_position=ExposureLeg.YES,
            pre_position_size=1,
            expected_post_position_size=2,
        )
        
        is_valid, error = contract.validate()
        assert not is_valid
        assert "EXIT must decrease exposure" in error


# =============================================================================
# Exposure Computation Tests
# =============================================================================

@pytest.mark.production_audit
@pytest.mark.order_mapping
class TestExposureComputation:
    """Test exposure computation from fills."""
    
    def test_buy_yes_exposure(self):
        """BUY YES should increase YES exposure."""
        exposure = compute_net_exposure_from_fill("yes", "buy", 1)
        assert exposure == {"yes": 1, "no": 0}
    
    def test_sell_yes_exposure(self):
        """SELL YES should decrease YES exposure."""
        exposure = compute_net_exposure_from_fill("yes", "sell", 1)
        assert exposure == {"yes": -1, "no": 0}
    
    def test_buy_no_exposure(self):
        """BUY NO should increase NO exposure."""
        exposure = compute_net_exposure_from_fill("no", "buy", 1)
        assert exposure == {"yes": 0, "no": 1}
    
    def test_sell_no_exposure(self):
        """SELL NO should decrease NO exposure."""
        exposure = compute_net_exposure_from_fill("no", "sell", 1)
        assert exposure == {"yes": 0, "no": -1}
    
    def test_multi_contract_fill(self):
        """Multi-contract fill should scale exposure."""
        exposure = compute_net_exposure_from_fill("yes", "buy", 5)
        assert exposure == {"yes": 5, "no": 0}


# =============================================================================
# Canonical Price Range Tests
# =============================================================================

@pytest.mark.production_audit
@pytest.mark.order_mapping
class TestCanonicalPriceRange:
    """Test that orders respect the 10-75c canonical range."""
    
    @pytest.mark.parametrize("price_cents", [10, 35, 50, 75])
    def test_valid_canonical_prices(self, asset, sample_ticker, price_cents):
        """Prices within 10-75c range should be valid."""
        contract = build_entry_order(
            intent=StrategyIntent.BULLISH_EVENT,
            asset=asset,
            ticker=sample_ticker,
            price_cents=price_cents,
            magnitude=1,
        )
        
        assert contract.kalshi_payload.price_cents == price_cents
    
    @pytest.mark.parametrize("price_cents", [5, 9, 76, 80, 99])
    def test_out_of_range_prices_warning(self, asset, sample_ticker, price_cents):
        """Prices outside 10-75c range should be flagged.
        
        Note: The intent_contract module doesn't enforce price range limits
        (that's done by other layers), but we test that the contract
        correctly records whatever price is passed.
        """
        contract = build_entry_order(
            intent=StrategyIntent.BULLISH_EVENT,
            asset=asset,
            ticker=sample_ticker,
            price_cents=price_cents,
            magnitude=1,
        )
        
        # Contract should record the price even if out of range
        assert contract.kalshi_payload.price_cents == price_cents
        
        # In production, other layers should reject out-of-range prices
        # This test documents that the contract itself is price-agnostic


# =============================================================================
# Asset Coverage Tests
# =============================================================================

@pytest.mark.production_audit
@pytest.mark.order_mapping
class TestAssetCoverage:
    """Test that all 5 assets are covered."""
    
    @pytest.mark.parametrize("asset", ["BTC", "ETH", "SOL", "XRP", "DOGE"])
    def test_all_assets_bullish_entry(self, asset):
        """All assets should support BULLISH_EVENT entry."""
        ticker = f"KX{asset}D-25JUL-T100000"
        contract = build_entry_order(
            intent=StrategyIntent.BULLISH_EVENT,
            asset=asset,
            ticker=ticker,
            price_cents=35,
            magnitude=1,
        )
        
        assert contract.asset == asset
        assert contract.ticker == ticker
        assert contract.strategy_intent == StrategyIntent.BULLISH_EVENT
    
    @pytest.mark.parametrize("asset", ["BTC", "ETH", "SOL", "XRP", "DOGE"])
    def test_all_assets_bearish_entry(self, asset):
        """All assets should support BEARISH_EVENT entry."""
        ticker = f"KX{asset}D-25JUL-T100000"
        contract = build_entry_order(
            intent=StrategyIntent.BEARISH_EVENT,
            asset=asset,
            ticker=ticker,
            price_cents=35,
            magnitude=1,
        )
        
        assert contract.asset == asset
        assert contract.ticker == ticker
        assert contract.strategy_intent == StrategyIntent.BEARISH_EVENT


# =============================================================================
# Serialization Tests
# =============================================================================

@pytest.mark.production_audit
@pytest.mark.order_mapping
class TestContractSerialization:
    """Test contract serialization for logging/audit."""
    
    def test_contract_to_dict(self, asset, sample_ticker, entry_price_cents):
        """Contract should serialize to dict correctly."""
        contract = build_entry_order(
            intent=StrategyIntent.BULLISH_EVENT,
            asset=asset,
            ticker=sample_ticker,
            price_cents=entry_price_cents,
            magnitude=1,
            client_order_id="test_order_123",
            rationale="Test serialization",
        )
        
        d = contract.to_dict()
        
        # Check all fields are present
        assert d["strategy_intent"] == "bullish_event"
        assert d["entry_or_exit"] == "entry"
        assert d["target_leg"] == "yes"
        assert d["asset"] == asset
        assert d["ticker"] == sample_ticker
        assert d["client_order_id"] == "test_order_123"
        assert d["rationale"] == "Test serialization"
        assert d["is_valid"] == True
        assert d["validation_error"] is None
    
    def test_exposure_change_to_dict(self):
        """ExposureChange should serialize correctly."""
        exposure = ExposureChange(leg=ExposureLeg.YES, direction="increase", magnitude=5)
        d = exposure.to_dict()
        
        assert d["leg"] == "yes"
        assert d["direction"] == "increase"
        assert d["magnitude"] == 5
    
    def test_kalshi_payload_to_dict(self):
        """KalshiSidePayload should serialize correctly."""
        payload = KalshiSidePayload(side="yes", action="buy", price_cents=42)
        d = payload.to_dict()
        
        assert d["side"] == "yes"
        assert d["action"] == "buy"
        assert d["price_cents"] == 42
        assert d["kalshi_format"] == "BUY_YES"
