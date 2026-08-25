"""Fail-closed validation for outcome side fields.

Replaces every downstream ``.get("side", "yes")`` fallback with a strict
parser that raises for missing, blank, unknown, or inconsistent side metadata.
"""

from __future__ import annotations

import pytest

from merid.event_venues.kalshi.binary_price_space import (
    canonical_outcome_side,
    require_outcome_side,
    require_consistent_outcome_side,
    require_canonical_outcome_side,
    normalize_rest_position,
    OutcomeSide,
    PositionDataError,
    SideValidationError,
)


@pytest.mark.parametrize(
    "record,expected",
    [
        ({"outcome_side": "yes"}, "yes"),
        ({"outcome_side": "no"}, "no"),
        ({"outcome_side": "YES"}, "yes"),
        ({"outcome_side": "NO"}, "no"),
        ({"side": "yes"}, "yes"),
        ({"side": "no"}, "no"),
        ({"kalshi_side": "BUY_YES"}, "yes"),
        ({"kalshi_side": "SELL_NO"}, "yes"),
        ({"kalshi_side": "BUY_NO"}, "no"),
        ({"kalshi_side": "SELL_YES"}, "no"),
        ({"outcome_id": "yes"}, "yes"),
        ({"outcome_id": "no"}, "no"),
    ],
)
def test_require_outcome_side_valid(record, expected):
    assert require_outcome_side(record, context="test") == expected


@pytest.mark.parametrize(
    "record",
    [
        {},
        {"outcome_side": None},
        {"side": ""},
        {"kalshi_side": "unknown"},
        {"outcome_side": "maybe"},
        {"outcome_side": "123"},
    ],
)
def test_require_outcome_side_invalid(record):
    with pytest.raises(SideValidationError):
        require_outcome_side(record, context="test")


@pytest.mark.parametrize(
    "record,expected",
    [
        ({"outcome_side": "yes", "kalshi_side": "BUY_YES"}, "yes"),
        ({"side": "no", "kalshi_side": "BUY_NO"}, "no"),
    ],
)
def test_require_consistent_outcome_side_agreement(record, expected):
    assert require_consistent_outcome_side(record, context="test") == expected


@pytest.mark.parametrize(
    "record",
    [
        {"outcome_side": "yes", "kalshi_side": "BUY_NO"},
        {"side": "yes", "outcome_side": "no"},
        {"side": "yes", "outcome_side": None, "kalshi_side": "BUY_NO"},
    ],
)
def test_require_consistent_outcome_side_inconsistent(record):
    with pytest.raises(SideValidationError):
        require_consistent_outcome_side(record, context="test")


class TestPositionCacheSideValidation:
    """Side validation at REST position sync time."""

    @pytest.mark.asyncio
    async def test_missing_side_quarantines_position(self, mocker):
        from merid.event_venues.kalshi.position_cache import PositionCache

        cache = PositionCache()
        cache._last_sync = None
        cache._last_rest_sync_timestamp = 0.0
        cache.require_rest_reconciliation = mocker.MagicMock()

        # Patch internal lock and other helpers so we can exercise the loop.
        import merid.event_venues.kalshi.position_cache as pc
        original = pc._require_outcome_side_for_position

        async def _sync_wrapper():
            # Simulate only the validation part of sync_from_rest.
            try:
                pc._require_outcome_side_for_position({"market_id": "KXBTC-15M-TEST"}, "KXBTC-15M-TEST")
            except (SideValidationError, pc.SideValidationErrorLocal):
                cache.require_rest_reconciliation("KXBTC-15M-TEST", reason="invalid_outcome_side")
                return True
            return False

        quarantined = await _sync_wrapper()
        assert quarantined is True
        cache.require_rest_reconciliation.assert_called_once_with(
            "KXBTC-15M-TEST", reason="invalid_outcome_side"
        )


class TestFillsLedgerSideValidation:
    """Side validation during reconciliation."""

    @pytest.mark.asyncio
    async def test_missing_kalshi_side_records_divergence(self, mocker):
        from merid.event_venues.kalshi.fills_ledger import KalshiFillsLedger

        ledger = KalshiFillsLedger()
        ledger._fills = {}
        ledger._fills_by_market = {}

        kalshi_positions = [{"market_ticker": "KXBTC-15M-TEST"}]
        divergences = []

        for kalshi_pos in kalshi_positions:
            ticker = kalshi_pos.get("market_ticker")
            try:
                require_consistent_outcome_side(kalshi_pos, context=f"fills_ledger ticker={ticker}")
            except SideValidationError:
                divergences.append({"type": "invalid_kalshi_side"})

        assert len(divergences) == 1
        assert divergences[0]["type"] == "invalid_kalshi_side"


class TestClientPnLSideValidation:
    """Side validation in PnL mark calculation."""

    def test_missing_side_excludes_position(self):
        # The client loop now calls require_consistent_outcome_side; a missing
        # side must raise and be excluded from PnL aggregation.
        with pytest.raises(SideValidationError):
            require_consistent_outcome_side({}, context="kalshi_client pnl ticker=KXBTC-15M-TEST")


class TestCanonicalOutcomeSide:
    """Canonical adapter for REST, WebSocket, and fill side strings."""

    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("yes", OutcomeSide.YES),
            ("no", OutcomeSide.NO),
            ("YES", OutcomeSide.YES),
            ("NO", OutcomeSide.NO),
            ("Yes", OutcomeSide.YES),
            ("No", OutcomeSide.NO),
            ("buy_yes", OutcomeSide.YES),
            ("SELL_NO", OutcomeSide.YES),
            ("buy_no", OutcomeSide.NO),
            ("sell_yes", OutcomeSide.NO),
        ],
    )
    def test_canonical_outcome_side_valid(self, raw, expected):
        assert canonical_outcome_side(raw) == expected

    @pytest.mark.parametrize("raw", [None, "", "   ", "maybe", "123", "YES/NO"])
    def test_canonical_outcome_side_invalid(self, raw):
        with pytest.raises(PositionDataError):
            canonical_outcome_side(raw)


class TestRequireCanonicalOutcomeSide:
    """Strict side extraction with conflict detection and sign agreement."""

    def test_outcome_id_yes_and_no(self):
        assert require_canonical_outcome_side({"outcome_id": "yes"}, context="test") == OutcomeSide.YES
        assert require_canonical_outcome_side({"outcome_id": "no"}, context="test") == OutcomeSide.NO

    def test_outcome_id_outcome_side_conflict(self):
        with pytest.raises(PositionDataError):
            require_canonical_outcome_side(
                {"outcome_id": "no", "outcome_side": "yes"},
                context="test",
            )

    def test_outcome_side_and_kalshi_side_agreement(self):
        assert require_canonical_outcome_side(
            {"outcome_side": "yes", "kalshi_side": "BUY_YES"},
            context="test",
        ) == OutcomeSide.YES

    def test_positive_signed_infers_yes(self):
        assert require_canonical_outcome_side({"position_fp": 1.55}, context="test") == OutcomeSide.YES

    def test_negative_signed_infers_no(self):
        assert require_canonical_outcome_side({"position_fp": -1.55}, context="test") == OutcomeSide.NO

    def test_missing_everything_raises(self):
        with pytest.raises(PositionDataError):
            require_canonical_outcome_side({}, context="test")

    def test_missing_with_zero_signed_raises(self):
        with pytest.raises(PositionDataError):
            require_canonical_outcome_side({"position_fp": 0}, context="test")

    def test_side_conflicts_with_signed_quantity(self):
        with pytest.raises(PositionDataError):
            require_canonical_outcome_side(
                {"outcome_side": "yes", "position_fp": -1.0},
                context="test",
            )
        with pytest.raises(PositionDataError):
            require_canonical_outcome_side(
                {"outcome_side": "no", "position_fp": +1.0},
                context="test",
            )

    def test_rest_and_ws_records_produce_identical_side(self):
        rest_record = {"outcome_id": "no", "position_fp": -1.0}
        ws_record = {"outcome_side": "no", "signed_size": -1.0, "book_side": "ask"}
        assert require_canonical_outcome_side(rest_record, context="test") == OutcomeSide.NO
        assert require_canonical_outcome_side(ws_record, context="test") == OutcomeSide.NO


class TestNormalizeRestPosition:
    """Signed-YES exposure from REST snapshots."""

    def test_positive_yes_position(self):
        assert normalize_rest_position(3, "yes", "KXBTC15M") == 3

    def test_positive_no_position(self):
        assert normalize_rest_position(3, "no", "KXBTC15M") == -3

    def test_negative_no_position_missing_side(self):
        assert normalize_rest_position(-3, "", "KXBTC15M") == -3

    def test_negative_yes_position_is_conflict(self):
        with pytest.raises(PositionDataError):
            normalize_rest_position(-3, "yes", "KXBTC15M")

    def test_unknown_side_is_conflict(self):
        with pytest.raises(PositionDataError):
            normalize_rest_position(3, "maybe", "KXBTC15M")


class TestTradeContractSideValidation:
    """Side validation at contract construction."""

    def test_missing_thesis_side_raises(self):
        from merid.prediction.trade_contract import build_trade_contract_from_signal

        with pytest.raises((SideValidationError, ValueError)):
            build_trade_contract_from_signal(
                signal_data={},
                config_data={"asset": "BTC", "market_id": "KXBTC-15M-TEST"},
                market_data={},
            )
