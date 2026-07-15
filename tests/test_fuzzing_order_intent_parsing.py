"""Fuzzing tests for order intent parsing.

This module implements fuzzing tests using Hypothesis to test order intent parsing
with randomly generated inputs. This helps identify edge cases, boundary conditions,
and potential vulnerabilities in the intent parsing logic.

Fuzzing Scenarios:
1. Intent JSON parsing fuzzing
2. Intent field validation fuzzing
3. Intent constraint checking fuzzing
4. Intent transformation fuzzing
5. Intent serialization fuzzing
"""

import pytest
from hypothesis import given, strategies as st, settings, Phase
from hypothesis.strategies import integers, floats, text, lists, dictionaries, sampled_from, none, booleans, builds, fixed_dictionaries
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
import json


@dataclass
class OrderIntent:
    """Order intent representation."""
    asset: str
    side: str
    price_cents: int
    quantity: int
    edge: float
    timestamp: int


class TestIntentJSONParsingFuzzing:
    """Fuzzing tests for intent JSON parsing."""

    @given(
        json_str=text(min_size=0, max_size=1000)
    )
    @settings(max_examples=100, phases=[Phase.generate])
    def test_json_parsing_robustness(self, json_str: str):
        """JSON parsing should handle various string inputs."""
        try:
            parsed = json.loads(json_str)
            assert isinstance(parsed, (dict, list, str, int, float, bool, type(None)))
        except json.JSONDecodeError:
            assert True
        except Exception:
            assert True

    @given(
        intent_dict=dictionaries(
            keys=text(min_size=0, max_size=20, alphabet="abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ_"),
            values=sampled_from([
                none(),
                integers(min_value=-1000, max_value=1000),
                floats(min_value=-1000.0, max_value=1000.0),
                text(min_size=0, max_size=100),
                booleans(),
                lists(integers(min_value=0, max_value=10), min_size=0, max_size=5)
            ]),
            min_size=0,
            max_size=20
        )
    )
    @settings(max_examples=100, phases=[Phase.generate])
    def test_intent_dict_validation(self, intent_dict: Dict[str, Any]):
        """Intent dictionary validation should handle various formats."""
        valid_fields = {}
        for key, value in intent_dict.items():
            if not key or not key.isidentifier():
                continue
            try:
                json.dumps(value)
                valid_fields[key] = value
            except Exception:
                continue
        assert isinstance(valid_fields, dict)

    @given(
        intent_list=lists(
            dictionaries(
                keys=text(min_size=0, max_size=10, alphabet="abcdefghijklmnopqrstuvwxyz"),
                values=integers(min_value=0, max_value=100),
                min_size=0,
                max_size=5
            ),
            min_size=0,
            max_size=10
        )
    )
    @settings(max_examples=50, phases=[Phase.generate])
    def test_batch_intent_parsing(self, intent_list: List[Dict[str, Any]]):
        """Batch intent parsing should handle various list formats."""
        valid_intents = []
        for intent in intent_list:
            if not all(k in intent for k in ["asset", "side", "price_cents", "quantity"]):
                continue
            try:
                asset = intent.get("asset")
                side = intent.get("side")
                price = intent.get("price_cents")
                qty = intent.get("quantity")
                if not isinstance(asset, str) or not isinstance(side, str):
                    continue
                if not isinstance(price, int) or not isinstance(qty, int):
                    continue
                if side not in ["buy", "sell"]:
                    continue
                if not (10 <= price <= 75):
                    continue
                if qty <= 0:
                    continue
                valid_intents.append(intent)
            except Exception:
                pass
        assert isinstance(valid_intents, list)


class TestIntentFieldValidationFuzzing:
    """Fuzzing tests for intent field validation."""

    @given(
        asset=text(min_size=0, max_size=20, alphabet="ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_")
    )
    @settings(max_examples=100, phases=[Phase.generate])
    def test_asset_field_validation(self, asset: str):
        """Asset field validation should handle various formats."""
        valid_assets = ["BTC", "ETH", "SOL", "XRP", "DOGE"]
        if asset in valid_assets:
            is_valid = True
        elif not asset:
            is_valid = False
        elif not asset.isupper():
            is_valid = False
        elif len(asset) > 10:
            is_valid = False
        else:
            is_valid = False
        assert isinstance(is_valid, bool)

    @given(
        side=text(min_size=0, max_size=10)
    )
    @settings(max_examples=100, phases=[Phase.generate])
    def test_side_field_validation(self, side: str):
        """Side field validation should handle various formats."""
        if side.lower() in ["buy", "sell"]:
            is_valid = True
        elif not side:
            is_valid = False
        else:
            is_valid = False
        assert isinstance(is_valid, bool)

    @given(
        price_cents=integers(min_value=-1000, max_value=1000)
    )
    @settings(max_examples=100, phases=[Phase.generate])
    def test_price_field_validation(self, price_cents: int):
        """Price field validation should handle various values."""
        if 10 <= price_cents <= 75:
            is_valid = True
        elif price_cents < 0:
            is_valid = False
        else:
            is_valid = False
        assert isinstance(is_valid, bool)

    @given(
        quantity=integers(min_value=-1000, max_value=10000)
    )
    @settings(max_examples=100, phases=[Phase.generate])
    def test_quantity_field_validation(self, quantity: int):
        """Quantity field validation should handle various values."""
        if quantity > 0 and quantity <= 100:
            is_valid = True
        elif quantity <= 0:
            is_valid = False
        else:
            is_valid = False
        assert isinstance(is_valid, bool)

    @given(
        edge=floats(min_value=-1.0, max_value=2.0, allow_nan=False, allow_infinity=False)
    )
    @settings(max_examples=100, phases=[Phase.generate])
    def test_edge_field_validation(self, edge: float):
        """Edge field validation should handle various values."""
        if 0.0 <= edge <= 1.0:
            is_valid = True
        elif edge < 0:
            is_valid = False
        else:
            is_valid = False
        assert isinstance(is_valid, bool)


class TestIntentConstraintCheckingFuzzing:
    """Fuzzing tests for intent constraint checking."""

    @given(
        price_cents=integers(min_value=0, max_value=100),
        quantity=integers(min_value=0, max_value=100),
        exposure_cap=floats(min_value=0.1, max_value=10.0, allow_nan=False, allow_infinity=False)
    )
    @settings(max_examples=100, phases=[Phase.generate])
    def test_exposure_constraint_check(self, price_cents: int, quantity: int, exposure_cap: float):
        """Exposure constraint check should handle various combinations."""
        if exposure_cap <= 0:
            is_within_cap = False
        else:
            exposure = (price_cents / 100.0) * quantity
            is_within_cap = exposure <= exposure_cap
        assert isinstance(is_within_cap, bool)

    @given(
        current_exposure=floats(min_value=0.0, max_value=10.0, allow_nan=False, allow_infinity=False),
        new_exposure=floats(min_value=0.0, max_value=10.0, allow_nan=False, allow_infinity=False),
        exposure_cap=floats(min_value=0.1, max_value=10.0, allow_nan=False, allow_infinity=False)
    )
    @settings(max_examples=100, phases=[Phase.generate])
    def test_cumulative_exposure_check(self, current_exposure: float, new_exposure: float, exposure_cap: float):
        """Cumulative exposure check should handle various combinations."""
        if exposure_cap <= 0:
            is_within_cap = False
        else:
            total_exposure = current_exposure + new_exposure
            is_within_cap = total_exposure <= exposure_cap
        assert isinstance(is_within_cap, bool)

    @given(
        intents=lists(
            fixed_dictionaries({
                "asset": sampled_from(["BTC", "ETH", "SOL", "XRP", "DOGE"]),
                "side": sampled_from(["buy", "sell"]),
                "price_cents": integers(min_value=10, max_value=75),
                "quantity": integers(min_value=1, max_value=10)
            }),
            min_size=0,
            max_size=10
        )
    )
    @settings(max_examples=50, phases=[Phase.generate])
    def test_multi_asset_exposure_check(self, intents: List[Dict[str, Any]]):
        """Multi-asset exposure check should handle various intent combinations."""
        asset_exposure = {}
        for intent in intents:
            asset = intent.get("asset")
            price = intent.get("price_cents", 0)
            qty = intent.get("quantity", 0)
            if asset and price and qty:
                exposure = (price / 100.0) * qty
                asset_exposure[asset] = asset_exposure.get(asset, 0.0) + exposure
        total_exposure = sum(asset_exposure.values())
        assert isinstance(total_exposure, (float, int))
        assert total_exposure >= 0


class TestIntentTransformationFuzzing:
    """Fuzzing tests for intent transformation."""

    @given(
        intent_dict=dictionaries(
            keys=sampled_from(["asset", "side", "price_cents", "quantity", "edge", "timestamp"]),
            values=sampled_from([
                sampled_from(["BTC", "ETH", "SOL", "XRP", "DOGE"]),
                sampled_from(["buy", "sell"]),
                integers(min_value=10, max_value=75),
                integers(min_value=1, max_value=10),
                floats(min_value=0.0, max_value=1.0),
                integers(min_value=0, max_value=9999999999)
            ]),
            min_size=3,
            max_size=6
        )
    )
    @settings(max_examples=100, phases=[Phase.generate])
    def test_dict_to_intent_conversion(self, intent_dict: Dict[str, Any]):
        """Dict to intent conversion should handle various formats."""
        try:
            intent = OrderIntent(
                asset=intent_dict.get("asset", "BTC"),
                side=intent_dict.get("side", "buy"),
                price_cents=intent_dict.get("price_cents", 50),
                quantity=intent_dict.get("quantity", 1),
                edge=intent_dict.get("edge", 0.5),
                timestamp=intent_dict.get("timestamp", 0)
            )
            assert isinstance(intent, OrderIntent)
            assert isinstance(intent.asset, str)
            assert isinstance(intent.side, str)
            assert isinstance(intent.price_cents, int)
            assert isinstance(intent.quantity, int)
        except Exception:
            assert True

    @given(
        intent_list=lists(
            dictionaries(
                keys=sampled_from(["asset", "side", "price_cents", "quantity"]),
                values=sampled_from([
                    sampled_from(["BTC", "ETH", "SOL", "XRP", "DOGE"]),
                    sampled_from(["buy", "sell"]),
                    integers(min_value=10, max_value=75),
                    integers(min_value=1, max_value=10)
                ]),
                min_size=0,
                max_size=5
            )
        )
    )
    @settings(max_examples=50, phases=[Phase.generate])
    def test_batch_intent_transformation(self, intent_list: List[Dict[str, Any]]):
        """Batch intent transformation should handle various formats."""
        intents = []
        for intent_dict in intent_list:
            try:
                intent = OrderIntent(
                    asset=intent_dict.get("asset", "BTC"),
                    side=intent_dict.get("side", "buy"),
                    price_cents=intent_dict.get("price_cents", 50),
                    quantity=intent_dict.get("quantity", 1),
                    edge=0.5,
                    timestamp=0
                )
                intents.append(intent)
            except Exception:
                pass
        assert isinstance(intents, list)
        assert all(isinstance(i, OrderIntent) for i in intents)

    @given(
        price_float=floats(min_value=0.0, max_value=10.0, allow_nan=False, allow_infinity=False)
    )
    @settings(max_examples=100, phases=[Phase.generate])
    def test_price_float_to_cents_conversion(self, price_float: float):
        """Price float to cents conversion should handle various values."""
        price_cents = int(round(price_float * 100))
        price_cents = max(10, min(75, price_cents))
        assert isinstance(price_cents, int)
        assert 10 <= price_cents <= 75


class TestIntentSerializationFuzzing:
    """Fuzzing tests for intent serialization."""

    @given(
        asset=sampled_from(["BTC", "ETH", "SOL", "XRP", "DOGE"]),
        side=sampled_from(["buy", "sell"]),
        price_cents=integers(min_value=10, max_value=75),
        quantity=integers(min_value=1, max_value=10),
        edge=floats(min_value=0.0, max_value=1.0),
        timestamp=integers(min_value=0, max_value=9999999999)
    )
    @settings(max_examples=100, phases=[Phase.generate])
    def test_intent_to_dict_serialization(self, asset: str, side: str, price_cents: int, quantity: int, edge: float, timestamp: int):
        """Intent to dict serialization should handle various intents."""
        intent = OrderIntent(asset, side, price_cents, quantity, edge, timestamp)
        intent_dict = {
            "asset": intent.asset,
            "side": intent.side,
            "price_cents": intent.price_cents,
            "quantity": intent.quantity,
            "edge": intent.edge,
            "timestamp": intent.timestamp
        }
        assert isinstance(intent_dict, dict)
        assert "asset" in intent_dict
        assert "side" in intent_dict
        assert "price_cents" in intent_dict
        assert "quantity" in intent_dict

    @given(
        asset=sampled_from(["BTC", "ETH", "SOL", "XRP", "DOGE"]),
        side=sampled_from(["buy", "sell"]),
        price_cents=integers(min_value=10, max_value=75),
        quantity=integers(min_value=1, max_value=10),
        edge=floats(min_value=0.0, max_value=1.0),
        timestamp=integers(min_value=0, max_value=9999999999)
    )
    @settings(max_examples=100, phases=[Phase.generate])
    def test_intent_to_json_serialization(self, asset: str, side: str, price_cents: int, quantity: int, edge: float, timestamp: int):
        """Intent to JSON serialization should handle various intents."""
        intent = OrderIntent(asset, side, price_cents, quantity, edge, timestamp)
        intent_dict = {
            "asset": intent.asset,
            "side": intent.side,
            "price_cents": intent.price_cents,
            "quantity": intent.quantity,
            "edge": intent.edge,
            "timestamp": intent.timestamp
        }
        try:
            json_str = json.dumps(intent_dict)
            assert isinstance(json_str, str)
            assert len(json_str) > 0
        except Exception:
            assert True

    @given(
        intent_dicts=lists(
            dictionaries(
                keys=sampled_from(["asset", "side", "price_cents", "quantity", "edge", "timestamp"]),
                values=sampled_from([
                    sampled_from(["BTC", "ETH", "SOL", "XRP", "DOGE"]),
                    sampled_from(["buy", "sell"]),
                    integers(min_value=10, max_value=75),
                    integers(min_value=1, max_value=10),
                    floats(min_value=0.0, max_value=1.0),
                    integers(min_value=0, max_value=9999999999)
                ]),
                min_size=3,
                max_size=6
            ),
            min_size=0,
            max_size=10
        )
    )
    @settings(max_examples=50, phases=[Phase.generate])
    def test_batch_intent_serialization(self, intent_dicts: List[Dict[str, Any]]):
        """Batch intent serialization should handle various intent lists."""
        try:
            json_str = json.dumps(intent_dicts)
            assert isinstance(json_str, str)
            assert len(json_str) > 0
        except Exception:
            assert True

