"""
Tests for DataContract system (S8-01: formal data contracts per feed).

Tests:
- Contract registration and retrieval
- Schema type validation
- Required field validation
- FieldSpec range/allowed value checks
- Freshness (timestamp age) warnings
- Custom validators
- Fallback/default value application
- Registry summary and failure history
- Default contracts (binance, coinbase, kalshi, alpaca, polygon)
"""

import time
import json
import unittest

from core.data_contracts import (
    DataContract,
    DataContractRegistry,
    FieldSpec,
    FallbackStrategy,
    ValidationResult,
    build_default_contracts,
)


class TestDataContractValidation(unittest.TestCase):
    """Core contract validation logic."""

    def setUp(self):
        self.contract = DataContract(
            feed_id="test_feed",
            schema={"price": float, "volume": float, "symbol": str},
            max_age_seconds=30.0,
            required_fields={"price", "symbol"},
        )

    def test_valid_data_passes(self):
        data = {"price": 50000.0, "volume": 1.5, "symbol": "BTC/USDT"}
        result = self.contract.validate(data)
        self.assertTrue(result.valid)
        self.assertEqual(len(result.errors), 0)

    def test_missing_required_field_fails(self):
        data = {"volume": 1.5}
        result = self.contract.validate(data)
        self.assertFalse(result.valid)
        self.assertTrue(any("price" in e for e in result.errors))
        self.assertTrue(any("symbol" in e for e in result.errors))

    def test_wrong_type_fails(self):
        data = {"price": "not_a_float", "symbol": "BTC"}
        result = self.contract.validate(data)
        self.assertFalse(result.valid)
        self.assertTrue(any("Type mismatch" in e for e in result.errors))

    def test_optional_field_missing_ok(self):
        data = {"price": 50000.0, "symbol": "BTC"}
        result = self.contract.validate(data)
        self.assertTrue(result.valid)

    def test_stale_timestamp_warning(self):
        data = {
            "price": 50000.0,
            "symbol": "BTC",
            "timestamp": time.time() - 60,
        }
        result = self.contract.validate(data)
        self.assertTrue(result.valid)  # warnings don't fail
        self.assertTrue(any("stale" in w.lower() for w in result.warnings))

    def test_fresh_timestamp_no_warning(self):
        data = {
            "price": 50000.0,
            "symbol": "BTC",
            "timestamp": time.time(),
        }
        result = self.contract.validate(data)
        self.assertTrue(result.valid)
        self.assertEqual(len(result.warnings), 0)


class TestFieldSpec(unittest.TestCase):
    """FieldSpec range and allowed value validation."""

    def test_min_value_violation(self):
        spec = FieldSpec("price", float, min_value=0.0)
        errors = spec.validate(-1.0)
        self.assertTrue(any("below min" in e for e in errors))

    def test_max_value_violation(self):
        spec = FieldSpec("pct", float, max_value=100.0)
        errors = spec.validate(101.0)
        self.assertTrue(any("above max" in e for e in errors))

    def test_allowed_values_violation(self):
        spec = FieldSpec("side", str, allowed_values={"buy", "sell"})
        errors = spec.validate("hold")
        self.assertTrue(any("not in allowed" in e for e in errors))

    def test_valid_value_passes(self):
        spec = FieldSpec("price", float, min_value=0.0, max_value=1000000.0)
        errors = spec.validate(50000.0)
        self.assertEqual(len(errors), 0)

    def test_required_field_none_fails(self):
        spec = FieldSpec("price", float, required=True)
        errors = spec.validate(None)
        self.assertTrue(any("Missing required" in e for e in errors))

    def test_optional_field_none_ok(self):
        spec = FieldSpec("volume", float, required=False)
        errors = spec.validate(None)
        self.assertEqual(len(errors), 0)

    def test_wrong_type_in_spec(self):
        spec = FieldSpec("price", float)
        errors = spec.validate("not_a_float")
        self.assertTrue(any("Type mismatch" in e for e in errors))


class TestFieldSpecInContract(unittest.TestCase):
    """FieldSpec integrated into DataContract validation."""

    def test_field_spec_range_check(self):
        contract = DataContract(
            feed_id="kalshi",
            schema={"yes_ask": float},
            field_specs=[
                FieldSpec("yes_ask", float, min_value=0.0, max_value=100.0),
            ],
        )
        result = contract.validate({"yes_ask": 150.0})
        self.assertFalse(result.valid)
        self.assertTrue(any("above max" in e for e in result.errors))


class TestCustomValidators(unittest.TestCase):
    """Custom validator callables on DataContract."""

    def test_custom_validator_error(self):
        def check_spread(data):
            bid = data.get("bid", 0)
            ask = data.get("ask", 0)
            if ask > 0 and bid > 0 and (ask - bid) / ask > 0.05:
                return [f"Spread too wide: {(ask - bid) / ask:.2%}"]
            return []

        contract = DataContract(
            feed_id="test",
            schema={"bid": float, "ask": float},
            custom_validators=[check_spread],
        )
        result = contract.validate({"bid": 90.0, "ask": 100.0})
        self.assertFalse(result.valid)
        self.assertTrue(any("Spread too wide" in e for e in result.errors))

    def test_custom_validator_pass(self):
        def check_spread(data):
            bid = data.get("bid", 0)
            ask = data.get("ask", 0)
            if ask > 0 and bid > 0 and (ask - bid) / ask > 0.05:
                return [f"Spread too wide"]
            return []

        contract = DataContract(
            feed_id="test",
            schema={"bid": float, "ask": float},
            custom_validators=[check_spread],
        )
        result = contract.validate({"bid": 99.0, "ask": 100.0})
        self.assertTrue(result.valid)

    def test_custom_validator_exception_captured(self):
        def bad_validator(data):
            raise RuntimeError("boom")

        contract = DataContract(
            feed_id="test",
            schema={"price": float},
            custom_validators=[bad_validator],
        )
        result = contract.validate({"price": 100.0})
        self.assertFalse(result.valid)
        self.assertTrue(any("Custom validator error" in e for e in result.errors))


class TestFallbackApplication(unittest.TestCase):
    """Fallback/default value application."""

    def test_apply_defaults_for_missing(self):
        contract = DataContract(
            feed_id="test",
            schema={"price": float, "volume": float},
            default_values={"volume": 0.0},
        )
        patched = contract.apply_fallback({"price": 100.0})
        self.assertEqual(patched["volume"], 0.0)
        self.assertEqual(patched["price"], 100.0)

    def test_existing_values_not_overwritten(self):
        contract = DataContract(
            feed_id="test",
            schema={"price": float, "volume": float},
            default_values={"volume": 0.0},
        )
        patched = contract.apply_fallback({"price": 100.0, "volume": 5.0})
        self.assertEqual(patched["volume"], 5.0)


class TestDataContractRegistry(unittest.TestCase):
    """Registry operations."""

    def test_register_and_get(self):
        reg = DataContractRegistry()
        contract = DataContract(feed_id="test", schema={"price": float})
        reg.register(contract)
        self.assertIs(reg.get("test"), contract)

    def test_get_missing_returns_none(self):
        reg = DataContractRegistry()
        self.assertIsNone(reg.get("nonexistent"))

    def test_validate_unregistered_feed_fails(self):
        reg = DataContractRegistry()
        result = reg.validate("unknown", {"price": 100.0})
        self.assertFalse(result.valid)
        self.assertTrue(any("No contract" in e for e in result.errors))

    def test_validate_registered_feed(self):
        reg = DataContractRegistry()
        reg.register(DataContract(
            feed_id="test",
            schema={"price": float},
            required_fields={"price"},
        ))
        result = reg.validate("test", {"price": 100.0})
        self.assertTrue(result.valid)

    def test_validate_with_fallback(self):
        reg = DataContractRegistry()
        reg.register(DataContract(
            feed_id="test",
            schema={"price": float, "volume": float},
            required_fields={"price"},
            default_values={"volume": 0.0},
        ))
        result, patched = reg.validate_with_fallback("test", {"price": 100.0})
        self.assertTrue(result.valid)
        self.assertEqual(patched["volume"], 0.0)

    def test_list_contracts(self):
        reg = DataContractRegistry()
        reg.register(DataContract(feed_id="a", schema={"x": float}))
        reg.register(DataContract(feed_id="b", schema={"y": str}))
        contracts = reg.list_contracts()
        self.assertEqual(len(contracts), 2)

    def test_recent_failures(self):
        reg = DataContractRegistry()
        reg.register(DataContract(
            feed_id="test",
            schema={"price": float},
            required_fields={"price"},
        ))
        reg.validate("test", {})  # missing price → fail
        reg.validate("test", {"price": 100.0})  # pass
        failures = reg.get_recent_failures()
        self.assertEqual(len(failures), 1)
        self.assertEqual(failures[0]["feed_id"], "test")

    def test_summary_json_serializable(self):
        reg = DataContractRegistry()
        reg.register(DataContract(feed_id="test", schema={"price": float}))
        reg.validate("test", {"price": 100.0})
        summary = reg.get_summary()
        serialized = json.dumps(summary)
        self.assertIn("total_contracts", serialized)
        self.assertIn("success_rate", serialized)


class TestDefaultContracts(unittest.TestCase):
    """Default contracts for known feeds."""

    def test_build_default_has_5_feeds(self):
        reg = build_default_contracts()
        contracts = reg.list_contracts()
        self.assertEqual(len(contracts), 5)

    def test_binance_contract_validates(self):
        reg = build_default_contracts()
        result = reg.validate("binance", {
            "price": 50000.0,
            "volume": 1.5,
            "symbol": "BTC/USDT",
            "timestamp": time.time(),
        })
        self.assertTrue(result.valid)

    def test_binance_negative_price_fails(self):
        reg = build_default_contracts()
        result = reg.validate("binance", {
            "price": -1.0,
            "symbol": "BTC/USDT",
        })
        self.assertFalse(result.valid)

    def test_kalshi_contract_validates(self):
        reg = build_default_contracts()
        result = reg.validate("kalshi", {
            "yes_ask": 55.0,
            "yes_bid": 53.0,
            "no_ask": 47.0,
            "no_bid": 45.0,
            "ticker": "FED-25DEC",
            "volume": 100.0,
            "timestamp": time.time(),
        })
        self.assertTrue(result.valid)

    def test_kalshi_out_of_range_fails(self):
        reg = build_default_contracts()
        result = reg.validate("kalshi", {
            "yes_ask": 150.0,
            "yes_bid": 53.0,
            "ticker": "FED-25DEC",
        })
        self.assertFalse(result.valid)

    def test_alpaca_contract_validates(self):
        reg = build_default_contracts()
        result = reg.validate("alpaca", {
            "price": 175.50,
            "symbol": "AAPL",
            "timestamp": time.time(),
        })
        self.assertTrue(result.valid)

    def test_contract_to_dict_serializable(self):
        reg = build_default_contracts()
        for contract_dict in reg.list_contracts():
            serialized = json.dumps(contract_dict)
            self.assertIn("feed_id", serialized)
            self.assertIn("schema", serialized)


class TestValidationResultSerialization(unittest.TestCase):
    """ValidationResult is JSON-serializable."""

    def test_result_to_dict(self):
        result = ValidationResult(
            valid=False,
            feed_id="test",
            errors=["missing price"],
            warnings=["stale data"],
        )
        d = result.to_dict()
        serialized = json.dumps(d)
        self.assertIn("missing price", serialized)
        self.assertIn("stale data", serialized)


if __name__ == "__main__":
    unittest.main()
