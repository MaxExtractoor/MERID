from __future__ import annotations

from typing import Dict, List, Optional, Literal
from pydantic import BaseModel


CryptoProduct = Literal[
    "btc_15m",
    "eth_15m",
    "sol_15m",
    "xrp_15m",
    "btc_1h",
]


class KalshiEdgeSignal(BaseModel):
    implied_prob: float
    model_prob: float
    ev_cents: float
    edge_pct: float
    confidence: float
    confidence_bucket: str
    sizing_tier: str
    bid: Optional[float] = None
    ask: Optional[float] = None
    # crypto lane context
    product: Optional[CryptoProduct] = None
    agent_id: Optional[str] = None  # e.g. "btc_15m_regime"
    market_id: Optional[str] = None  # Kalshi ticker


class KalshiEdgeResponse(BaseModel):
    signals: Dict[str, KalshiEdgeSignal]  # key: ticker or agent_id
    count: int
    kelly_fraction: float
    effective_fraction: float
    drawdown_pct: float


class KalshiCryptoEdgeResponse(KalshiEdgeResponse):
    lane: str = "crypto_15m_1h"


class KalshiNewsSignal(BaseModel):
    title: str
    source: str
    url: Optional[str] = None
    importance: float
    published_at: Optional[str] = None
    posted_twitter: Optional[bool] = None
    posted_telegram: Optional[bool] = None
    assets: List[str]
    categories: List[str]


class KalshiNewsSignalsResponse(BaseModel):
    signals: List[KalshiNewsSignal]
    count: int
    monitor_running: bool
    error: Optional[str] = None


class KalshiConsensusSignal(BaseModel):
    ticker: str
    direction: str
    confidence: float
    vote_count: int
    bull_weight: float
    bear_weight: float
    agents: List[str]
    product: Optional[CryptoProduct] = None
    agent_id: Optional[str] = None


class KalshiConsensusSignalsResponse(BaseModel):
    signals: List[KalshiConsensusSignal]
    count: int
    pending_votes: int
    consensus_rate: float
    engine_running: bool
    error: Optional[str] = None
