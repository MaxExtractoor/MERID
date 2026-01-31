"""Manual social trade evaluation helper.

This script mirrors the social strategy integration test so engineers can run
an end-to-end evaluation from the command line. It ensures the strategy is
registered, seeds the social quant engine with a signal + market confirmation,
and prints the resulting evaluation payload.
"""

from __future__ import annotations

import argparse
import json
import time
from typing import Any, Dict

from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core.social_strategy_router import evaluate_social_trade
from core.strategy_versioning import (
    StrategyVersion,
    VersionStatus,
    get_version_registry,
)
from social.social_aware_quant import get_social_aware_quant_engine, SocialSource


def _ensure_strategy(strategy_id: str, asset: str) -> StrategyVersion:
    registry = get_version_registry()
    existing = registry.get_active_version(strategy_id)
    if existing:
        return existing

    strategy = StrategyVersion(
        strategy_id=strategy_id,
        version="1.0.0",
        status=VersionStatus.PRODUCTION,
        created_at=time.time(),
        promoted_at=time.time(),
        deprecated_at=None,
        performance_metrics={},
        config={},
        dependencies=[],
        changelog="Manual social trade check auto-registration",
        is_social_strategy=True,
        social_assets=[asset.upper()],
    )
    registry.register_version(strategy)
    registry.set_active_version(strategy.strategy_id, strategy.version)
    return strategy


def _seed_social_context(asset: str, sentiment_score: float, market_metrics: Dict[str, float]) -> None:
    engine = get_social_aware_quant_engine()
    engine.register_social_asset(asset)

    if not engine.is_social_asset(asset) or not engine.is_data_fresh(asset):
        engine.ingest_social_signal(
            source=SocialSource.TWITTER,
            asset=asset,
            sentiment_score=sentiment_score,
            volume=500,
            velocity=1.0,
            influencer_mentions=2,
            whale_mentions=1,
        )

    engine.check_market_confirmation(
        asset=asset,
        price_change_1h=market_metrics["price_change_1h"],
        price_change_24h=market_metrics["price_change_24h"],
        volume_24h=market_metrics["volume_24h"],
        liquidity_depth=market_metrics["liquidity_depth"],
        spread_bps=market_metrics["spread_bps"],
        volatility_24h=market_metrics["volatility_24h"],
        sentiment_direction=sentiment_score,
    )


def _default_market_metrics() -> Dict[str, float]:
    return {
        "price_change_1h": 0.02,
        "price_change_24h": 0.05,
        "volume_24h": 8_000_000.0,
        "liquidity_depth": 12_000_000.0,
        "spread_bps": 4.0,
        "volatility_24h": 0.15,
    }


def run_manual_check(args: argparse.Namespace) -> Dict[str, Any]:
    asset = args.asset.upper()
    sentiment_score = args.sentiment
    market_metrics = _default_market_metrics()
    market_metrics.update({k: v for k, v in vars(args).items() if k in market_metrics and v is not None})

    _ensure_strategy(args.strategy_id, asset)
    _seed_social_context(asset, sentiment_score, market_metrics)

    result = evaluate_social_trade(
        strategy_id=args.strategy_id,
        asset=asset,
        portfolio_value=args.portfolio,
        sentiment_score=sentiment_score,
        market_metrics=market_metrics,
    )
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Manual social strategy trade evaluation")
    parser.add_argument("asset", help="Asset ticker, e.g. BTC")
    parser.add_argument(
        "--strategy-id",
        default="social_btc_v1",
        help="Strategy identifier registered with the version registry",
    )
    parser.add_argument(
        "--portfolio",
        type=float,
        default=100_000.0,
        help="Portfolio value in USD",
    )
    parser.add_argument(
        "--sentiment",
        type=float,
        default=0.7,
        help="Sentiment score between -1 and 1",
    )
    parser.add_argument("--price-change-1h", dest="price_change_1h", type=float)
    parser.add_argument("--price-change-24h", dest="price_change_24h", type=float)
    parser.add_argument("--volume-24h", dest="volume_24h", type=float)
    parser.add_argument("--liquidity-depth", dest="liquidity_depth", type=float)
    parser.add_argument("--spread-bps", dest="spread_bps", type=float)
    parser.add_argument("--volatility-24h", dest="volatility_24h", type=float)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    result = run_manual_check(args)
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
