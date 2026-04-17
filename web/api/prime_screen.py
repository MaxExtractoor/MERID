"""Prime Screen API surface for local-first UI contract."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from threading import Lock
from typing import Dict, List, Optional
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from web.api.auth import get_current_session
from utils.logger import get_logger

logger = get_logger(__name__)


router = APIRouter(prefix="/api/v1/swarm/prime-screen", tags=["prime-screen"], dependencies=[Depends(get_current_session)]  # ZT6-01
)


class Position(BaseModel):
    symbol: str
    net_qty: float
    avg_entry: float
    unrealized_pnl: float


class Intent(BaseModel):
    symbol: str
    side: str
    size: float = Field(..., gt=0)
    confidence: float = Field(..., ge=0, le=1)
    time_horizon_sec: int = Field(..., ge=0)
    predicted_move_bps: float


class AgentHealth(BaseModel):
    latency_ms: float
    error_rate_1m: float


class AgentState(BaseModel):
    id: str
    name: str
    role: str
    instruments: List[str]
    status: str
    pnl_24h: float
    position: Optional[Position]
    current_intent: Optional[Intent]
    health: AgentHealth


class AgentVote(BaseModel):
    agent_id: str
    vote: str
    weight: float
    confidence: float
    reason_code: Optional[str]


class ConsensusDecision(BaseModel):
    decision_id: str
    symbol: str
    action: str
    size: float
    score: float
    expected_value: float
    risk_score: float
    state: str
    agent_votes: List[AgentVote]


class NewsItem(BaseModel):
    id: str
    source: str
    headline: str
    published_at: str
    symbols: List[str]
    sentiment: float
    url: Optional[str]
    summary: Optional[str]


class PredictionBook(BaseModel):
    agent_id: str
    bid_prob: float
    ask_prob: float
    position: float


class PredictionMarket(BaseModel):
    id: str
    label: str
    expiry: str
    house_prob: float
    agent_books: List[PredictionBook]


class PrimeScreenState(BaseModel):
    timestamp: str
    env: str
    symbols: List[str]
    agents: List[AgentState]
    consensus: List[ConsensusDecision]
    news: List[NewsItem]
    prediction_markets: List[PredictionMarket]


class FeatureSnapshot(BaseModel):
    spot_price: float
    funding_rate: float
    orderbook_imbalance: float
    realized_vol_1h: float


class RiskAction(BaseModel):
    type: str
    before: float
    after: float
    reason: str


class OrderRecord(BaseModel):
    order_id: str
    venue: str
    state: str
    avg_fill_price: Optional[float]
    filled_qty: Optional[float]


class DecisionDetailResponse(BaseModel):
    decision: ConsensusDecision
    features_snapshot: FeatureSnapshot
    news_refs: List[str]
    risk_actions: List[RiskAction]
    orders: List[OrderRecord]
    realized_pnl: Optional[float]
    narrative: Optional[str] = None
    narrative_status: Literal["pending", "ready", "failed"] = "pending"


class IntentOverrideRequest(BaseModel):
    decision_id: str
    action: str
    new_size: Optional[float]
    reason: str


class BacktestRequest(BaseModel):
    name: str
    mode: str
    symbols: List[str]
    start: str
    end: str
    risk_profile: str
    venues: List[str]
    data_source: str
    slippage_model: str
    seed: int


class BacktestResponse(BaseModel):
    backtest_id: str


class BacktestSummary(BaseModel):
    backtest_id: str
    name: str
    mode: str
    symbols: List[str]
    start: str
    end: str
    status: str
    total_trades: int
    realized_pnl: Optional[float]


class TradeRecord(BaseModel):
    trade_id: str
    decision_id: str
    symbol: str
    action: str
    size: float
    avg_price: float
    filled_at: str
    pnl: Optional[float]


class PrimeScreenStore:
    """Lightweight persistence layer using a JSON file."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.lock = Lock()
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            self._save(self._default_payload())

    def _default_payload(self) -> Dict[str, object]:
        return {
            "state": PrimeScreenState(
                timestamp="2026-01-29T19:45:00Z",
                env="live",
                symbols=["BTC-USD", "ETH-USD"],
                agents=[
                    AgentState(
                        id="agent:trend_1",
                        name="Trend Follower L1",
                        role="trend",
                        instruments=["BTC-USD"],
                        status="active",
                        pnl_24h=123.45,
                        position=Position(
                            symbol="BTC-USD",
                            net_qty=0.42,
                            avg_entry=42000.0,
                            unrealized_pnl=15.1,
                        ),
                        current_intent=Intent(
                            symbol="BTC-USD",
                            side="buy",
                            size=0.1,
                            confidence=0.82,
                            time_horizon_sec=3600,
                            predicted_move_bps=80,
                        ),
                        health=AgentHealth(latency_ms=35, error_rate_1m=0.0),
                    )
                ],
                consensus=[
                    ConsensusDecision(
                        decision_id="dec:btc_20260129_1945",
                        symbol="BTC-USD",
                        action="buy",
                        size=0.25,
                        score=0.77,
                        expected_value=14.2,
                        risk_score=0.31,
                        state="approved",
                        agent_votes=[
                            AgentVote(
                                agent_id="agent:trend_1",
                                vote="buy",
                                weight=0.6,
                                confidence=0.9,
                                reason_code="trend_breakout",
                            ),
                            AgentVote(
                                agent_id="agent:meanrev_1",
                                vote="sell",
                                weight=0.4,
                                confidence=0.7,
                                reason_code="overextension",
                            ),
                        ],
                    )
                ],
                news=[
                    NewsItem(
                        id="news:123",
                        source="coindesk",
                        headline="BTC spikes on ETF inflows",
                        published_at="2026-01-29T19:30:00Z",
                        symbols=["BTC-USD"],
                        sentiment=0.68,
                        url=None,
                        summary="Short local summary for offline use.",
                    )
                ],
                prediction_markets=[
                    PredictionMarket(
                        id="pred:BTC_UP_5PCT_24H",
                        label="BTC up 5% in 24h",
                        expiry="2026-01-30T19:45:00Z",
                        house_prob=0.41,
                        agent_books=[
                            PredictionBook(
                                agent_id="agent:trend_1",
                                bid_prob=0.45,
                                ask_prob=0.55,
                                position=-0.2,
                            )
                        ],
                    )
                ],
            ).model_dump(),
            "decisions": {
                "dec:btc_20260129_1945": DecisionDetailResponse(
                    decision=ConsensusDecision(
                        decision_id="dec:btc_20260129_1945",
                        symbol="BTC-USD",
                        action="buy",
                        size=0.25,
                        score=0.77,
                        expected_value=14.2,
                        risk_score=0.31,
                        state="approved",
                        agent_votes=[],
                    ),
                    features_snapshot=FeatureSnapshot(
                        spot_price=42500.1,
                        funding_rate=0.0003,
                        orderbook_imbalance=0.22,
                        realized_vol_1h=0.18,
                    ),
                    news_refs=["news:123"],
                    risk_actions=[
                        RiskAction(
                            type="size_down",
                            before=0.4,
                            after=0.25,
                            reason="max_notional_per_symbol_exceeded",
                        )
                    ],
                    orders=[
                        OrderRecord(
                            order_id="ord:abc",
                            venue="binance_futures",
                            state="filled",
                            avg_fill_price=42480.0,
                            filled_qty=0.25,
                        )
                    ],
                    realized_pnl=3.2,
                    narrative="The swarm went long BTC because...",
                    narrative_status="ready",
                ).model_dump(),
            },
            "overrides": [],
            "backtests": {},
            "trades": {},
        }

    def _load(self) -> Dict[str, object]:
        with self.lock:
            data = json.loads(self.path.read_text())
        return data

    def _save(self, data: Dict[str, object]) -> None:
        with self.lock:
            tmp_path = self.path.with_suffix(self.path.suffix + ".tmp")
            with tmp_path.open("w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            
            # Retry loop for Windows file-lock issues
            for attempt in range(5):
                try:
                    os.replace(tmp_path, self.path)
                    return
                except PermissionError:
                    if attempt == 4:  # Last attempt
                        raise
                    time.sleep(0.05)

    def get_state(self) -> PrimeScreenState:
        payload = self._load()["state"]
        return PrimeScreenState.model_validate(payload)

    def get_decision(self, decision_id: str) -> DecisionDetailResponse:
        data = self._load()["decisions"]
        try:
            decision = data[decision_id]
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Decision not found") from exc
        return DecisionDetailResponse.model_validate(decision)

    def list_pending_decisions(
        self, eligible_states: Optional[List[str]] = None, limit: Optional[int] = None
    ) -> List[str]:
        data = self._load()["decisions"]
        states = set(eligible_states or [])
        pending: List[str] = []
        for decision_id, payload in data.items():
            status = payload.get("narrative_status", "pending")
            if status == "ready":
                continue
            if states and payload.get("decision", {}).get("state") not in states:
                continue
            pending.append(decision_id)
            if limit is not None and len(pending) >= limit:
                break
        return pending

    def set_narrative(
        self, decision_id: str, narrative: Optional[str], status: str
    ) -> DecisionDetailResponse:
        data = self._load()
        decisions = data["decisions"]

        if decision_id not in decisions:
            raise HTTPException(status_code=404, detail="Decision not found")

        record = decisions[decision_id]
        # Normalize fields before saving/validation
        record["narrative"] = narrative
        record["narrative_status"] = status

        self._save(data)

        # Ensure key exists and is explicitly None if unset
        record.setdefault("narrative", None)

        return DecisionDetailResponse.model_validate(record)

    def reset_narrative(self, decision_id: str) -> DecisionDetailResponse:
        return self.set_narrative(decision_id, narrative=None, status="pending")

    def record_override(self, override: IntentOverrideRequest) -> Dict[str, object]:
        data = self._load()
        data.setdefault("overrides", []).append(override.model_dump())
        self._save(data)
        return {"status": "recorded", "decision_id": override.decision_id}

    def create_backtest(self, req: BacktestRequest) -> str:
        data = self._load()
        backtest_id = f"bt:{req.name}:{req.start}_{req.end}"
        data.setdefault("backtests", {})[backtest_id] = {
            "summary": BacktestSummary(
                backtest_id=backtest_id,
                name=req.name,
                mode=req.mode,
                symbols=req.symbols,
                start=req.start,
                end=req.end,
                status="queued",
                total_trades=0,
                realized_pnl=None,
            ).model_dump(),
            "request": req.model_dump(),
        }
        data.setdefault("trades", {})[backtest_id] = []
        self._save(data)
        return backtest_id

    def get_backtest(self, backtest_id: str) -> BacktestSummary:
        backtests = self._load()["backtests"]
        try:
            summary = backtests[backtest_id]["summary"]
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Backtest not found") from exc
        return BacktestSummary.model_validate(summary)

    def get_backtest_trades(self, backtest_id: str) -> List[TradeRecord]:
        trades = self._load()["trades"]
        try:
            trade_list = trades[backtest_id]
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Backtest not found") from exc
        return [TradeRecord.model_validate(item) for item in trade_list]


store = PrimeScreenStore(Path("data/prime_screen_store.json"))


@router.get("/state", response_model=PrimeScreenState)
async def get_prime_screen_state() -> PrimeScreenState:
    return store.get_state()


@router.get("/decisions/{decision_id}", response_model=DecisionDetailResponse)
async def get_decision(decision_id: str) -> DecisionDetailResponse:
    return store.get_decision(decision_id)


@router.post("/decisions/{decision_id}/narrative/retry", response_model=DecisionDetailResponse)
async def retry_decision_narrative(decision_id: str) -> DecisionDetailResponse:
    """Reset the narrative so the explainer worker can regenerate it."""
    return store.reset_narrative(decision_id)


@router.post("/intents/override")
async def override_intent(request: IntentOverrideRequest):
    return store.record_override(request)


@router.post("/backtests", response_model=BacktestResponse)
async def create_backtest(req: BacktestRequest) -> BacktestResponse:
    backtest_id = store.create_backtest(req)
    return BacktestResponse(backtest_id=backtest_id)


@router.get("/backtests/{backtest_id}", response_model=BacktestSummary)
async def get_backtest(backtest_id: str) -> BacktestSummary:
    return store.get_backtest(backtest_id)


@router.get("/backtests/{backtest_id}/trades", response_model=List[TradeRecord])
async def list_backtest_trades(backtest_id: str) -> List[TradeRecord]:
    return store.get_backtest_trades(backtest_id)
