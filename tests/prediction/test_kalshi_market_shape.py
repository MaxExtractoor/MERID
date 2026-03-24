from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
import importlib.util
import sys


ROOT = Path(__file__).resolve().parents[2]


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


# Load modules directly to avoid heavy package side effects during test collection
shape_mod = _load_module("merid.prediction.kalshi_market_shape", ROOT / "merid/prediction/kalshi_market_shape.py")
model_mod = _load_module("merid.prediction.model", ROOT / "merid/prediction/model.py")
strategy_mod = _load_module("merid.prediction.strategy", ROOT / "merid/prediction/strategy.py")

MoveBandsConfig = shape_mod.MoveBandsConfig
classify_market_shape = shape_mod.classify_market_shape
evaluate_geometry = shape_mod.evaluate_geometry
PredictionMarketModel = model_mod.PredictionMarketModel
MarketSnapshot = model_mod.MarketSnapshot
ContractState = model_mod.ContractState
KalshiStrategy = strategy_mod.KalshiStrategy
StrategyConfig = strategy_mod.StrategyConfig
SignalAction = strategy_mod.SignalAction


class DummyOutcome:
    def __init__(self, outcome_id: str, price: float) -> None:
        self.outcome_id = outcome_id
        self.price = Decimal(str(price / 100))


class DummyMarket:
    def __init__(self, question: str, end_date: datetime, yes: float, no: float) -> None:
        self.market_id = "TEST-MKT"
        self.venue = "kalshi"
        self.question = question
        self.description = ""
        self.outcomes = [DummyOutcome("yes", yes), DummyOutcome("no", no)]
        self.end_date = end_date
        self.active = True
        self.volume = Decimal("1000")
        self.open_interest = Decimal("500")


def _make_event_market(question: str, end_date: datetime, yes: float = 50.0, no: float = 50.0) -> DummyMarket:
    return DummyMarket(question=question, end_date=end_date, yes=yes, no=no)


def test_catastrophic_strike_yes_rejected():
    now = datetime.now(timezone.utc)
    end = now + timedelta(hours=1)
    market = _make_event_market(
        "BTC will be at 59,099.99 or below by 3pm today",
        end,
        yes=5.0,
        no=95.0,
    )
    catalog_market = SimpleNamespace(
        market=market,
        asset="BTC",
        timeframe="1h",
        market_type="binary",
        category="crypto",
        event_ticker="KXBTC",
        series_ticker="KXBTC-15M",
        strike_price=59099.99,
        floor_strike=None,
        cap_strike=None,
        expires_at=end,
        minutes_to_expiry=60.0,
    )
    shape = classify_market_shape(market, catalog_market, now)
    decision = evaluate_geometry(shape, spot=69480.0, move_bands=MoveBandsConfig(), now=now)

    assert decision.allow_yes is False
    assert decision.reason_yes and "REJECT_GEOMETRY" in decision.reason_yes
    # NO side should still be considered
    assert decision.allow_no is True


def test_up_down_prefers_no_when_bearish():
    model = PredictionMarketModel()
    implied = model.implied_probabilities(
        yes_bid=Decimal("58"),
        yes_ask=Decimal("62"),
    )

    # Build edges manually using bearish true probability
    edge_yes = model.compute_edge(
        "UPDOWN",
        implied,
        model_prob=Decimal("0.30"),
        true_prob=Decimal("0.30"),
        side="yes",
        action="buy",
        price_cents=62,
    )
    edge_no = model.compute_edge(
        "UPDOWN",
        implied,
        model_prob=Decimal("0.70"),
        true_prob=Decimal("0.70"),
        side="no",
        action="buy",
        price_cents=38,
    )

    snapshot = MarketSnapshot(
        market_id="UPDOWN",
        event_id="UPDOWN",
        title="BTC Up or Down in 15 minutes?",
        state=ContractState.TRADING,
        implied=implied,
        volume=Decimal("5000"),
        open_interest=Decimal("2000"),
        time_to_expiry_hours=Decimal("0.25"),
        edges=[edge_yes, edge_no],
    )

    strategy = KalshiStrategy(config=StrategyConfig(min_volume=Decimal("100"), min_open_interest=Decimal("10")))
    signal = strategy.evaluate(snapshot, archetype="directional")

    assert signal.action == SignalAction.BUY_NO
    assert signal.side == "no"


def test_classification_sets_threshold_leq():
    now = datetime.now(timezone.utc)
    market = _make_event_market(
        "Will BTC be at or below $60,000 by close?",
        now + timedelta(hours=6),
    )
    catalog_market = SimpleNamespace(
        market=market,
        asset="BTC",
        timeframe="1h",
        market_type="binary",
        category="crypto",
        event_ticker="KXBTC",
        series_ticker="KXBTC-1H",
        strike_price=60000.0,
        floor_strike=None,
        cap_strike=None,
        expires_at=market.end_date,
        minutes_to_expiry=360.0,
    )

    shape = classify_market_shape(market, catalog_market, now)
    assert shape.market_type == "THRESHOLD_LEQ"
    assert shape.strike == 60000.0
