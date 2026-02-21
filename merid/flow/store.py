"""FlowStore — SQLite persistence for the flow domain.

Tables:
  - flow_tokens: tracked tokens/memecoins
  - flow_entities: whales, smart wallets, KOLs, deployers, CEX endpoints
  - flow_events: normalized flow events
  - flow_opinions: swarm opinions on tokens
  - flow_meme_plans: memecoin trade plans
  - flow_whale_plans: whale-follow/front-run/fade plans
  - flow_kol_plans: KOL-driven plans
  - flow_sniper_orders: MEV-aware sniper orders
  - flow_sniper_fills: execution fill records
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
from typing import Any, Dict, List, Optional

from merid.flow.models import (
    Chain,
    Entity,
    EntityType,
    FlowEvent,
    FlowEventType,
    FlowOpinion,
    FlowStance,
    KOLPlan,
    MemePlan,
    MevRiskTolerance,
    PlanStatus,
    SniperFill,
    SniperOrder,
    Token,
    WhalePlan,
    compute_flow_score,
)


def _now() -> float:
    return time.time()


class FlowStore:
    """SQLite store for the flow domain."""

    def __init__(self, db_path: str = ""):
        self._db_path = db_path or os.environ.get("MERID_FLOW_DB", "data/flow.db")
        self._persistent_conn: Optional[sqlite3.Connection] = None

        if self._db_path == ":memory:":
            self._persistent_conn = sqlite3.connect(
                ":memory:", check_same_thread=False
            )

        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        if self._persistent_conn is not None:
            return self._persistent_conn
        conn = sqlite3.connect(self._db_path)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _init_db(self):
        conn = self._get_conn()
        try:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS flow_tokens (
                    id TEXT PRIMARY KEY,
                    symbol TEXT NOT NULL,
                    name TEXT NOT NULL DEFAULT '',
                    contract_address TEXT NOT NULL DEFAULT '',
                    chain TEXT NOT NULL DEFAULT 'solana',
                    decimals INTEGER DEFAULT 9,
                    logo_url TEXT DEFAULT '',
                    tags TEXT DEFAULT '[]',
                    deployer_address TEXT DEFAULT '',
                    first_lp_timestamp REAL DEFAULT 0,
                    initial_mcap_usd REAL DEFAULT 0,
                    fdv_usd REAL DEFAULT 0,
                    total_liquidity_usd REAL DEFAULT 0,
                    liquidity_json TEXT DEFAULT '[]',
                    cex_listings TEXT DEFAULT '[]',
                    is_active INTEGER DEFAULT 1,
                    created_at REAL,
                    updated_at REAL
                );

                CREATE TABLE IF NOT EXISTS flow_entities (
                    id TEXT PRIMARY KEY,
                    address TEXT NOT NULL,
                    chain TEXT NOT NULL DEFAULT 'solana',
                    entity_type TEXT NOT NULL DEFAULT 'whale',
                    label TEXT DEFAULT '',
                    tags TEXT DEFAULT '[]',
                    social_handle TEXT DEFAULT '',
                    telegram_handle TEXT DEFAULT '',
                    follower_count INTEGER DEFAULT 0,
                    historical_pnl_usd REAL DEFAULT 0,
                    hit_rate REAL DEFAULT 0,
                    trade_count INTEGER DEFAULT 0,
                    avg_holding_hours REAL DEFAULT 0,
                    is_active INTEGER DEFAULT 1,
                    quality TEXT DEFAULT 'unknown',
                    created_at REAL,
                    updated_at REAL
                );

                CREATE TABLE IF NOT EXISTS flow_events (
                    id TEXT PRIMARY KEY,
                    event_type TEXT NOT NULL,
                    chain TEXT NOT NULL DEFAULT 'solana',
                    token_id TEXT DEFAULT '',
                    token_symbol TEXT DEFAULT '',
                    entity_id TEXT DEFAULT '',
                    entity_address TEXT DEFAULT '',
                    entity_type TEXT DEFAULT '',
                    size_usd REAL DEFAULT 0,
                    size_tokens REAL DEFAULT 0,
                    direction TEXT DEFAULT 'buy',
                    tx_hash TEXT DEFAULT '',
                    price_usd REAL DEFAULT 0,
                    price_impact REAL DEFAULT 0,
                    slippage REAL DEFAULT 0,
                    pool_liquidity_before REAL DEFAULT 0,
                    pool_liquidity_after REAL DEFAULT 0,
                    mention_text TEXT DEFAULT '',
                    mention_sentiment REAL DEFAULT 0,
                    mention_engagement INTEGER DEFAULT 0,
                    mention_source TEXT DEFAULT '',
                    timestamp REAL,
                    metadata_json TEXT DEFAULT '{}'
                );

                CREATE TABLE IF NOT EXISTS flow_opinions (
                    id TEXT PRIMARY KEY,
                    agent_id TEXT NOT NULL,
                    token_id TEXT NOT NULL,
                    token_symbol TEXT DEFAULT '',
                    chain TEXT DEFAULT 'solana',
                    contract_address TEXT DEFAULT '',
                    stance TEXT DEFAULT 'watch',
                    probability REAL DEFAULT 0.5,
                    expected_return_1h REAL DEFAULT 0,
                    expected_return_24h REAL DEFAULT 0,
                    confidence REAL DEFAULT 0.5,
                    reasoning TEXT DEFAULT '',
                    driver_event_ids TEXT DEFAULT '[]',
                    driver_entity_ids TEXT DEFAULT '[]',
                    timestamp REAL
                );

                CREATE TABLE IF NOT EXISTS flow_meme_plans (
                    id TEXT PRIMARY KEY,
                    token_id TEXT NOT NULL,
                    token_symbol TEXT DEFAULT '',
                    chain TEXT DEFAULT 'solana',
                    contract_address TEXT DEFAULT '',
                    entry_size_usd REAL DEFAULT 50,
                    max_slippage_bps INTEGER DEFAULT 300,
                    max_price_impact REAL DEFAULT 0.05,
                    min_liquidity_usd REAL DEFAULT 10000,
                    take_profit_pct REAL DEFAULT 50,
                    stop_loss_pct REAL DEFAULT 30,
                    max_holding_hours REAL DEFAULT 24,
                    trailing_stop_pct REAL DEFAULT 0,
                    mev_risk_tolerance TEXT DEFAULT 'low',
                    max_gas_usd REAL DEFAULT 5,
                    status TEXT DEFAULT 'proposed',
                    triggered_by TEXT DEFAULT '[]',
                    supporting_agents TEXT DEFAULT '[]',
                    opposing_agents TEXT DEFAULT '[]',
                    confidence REAL DEFAULT 0.5,
                    created_at REAL,
                    updated_at REAL
                );

                CREATE TABLE IF NOT EXISTS flow_whale_plans (
                    id TEXT PRIMARY KEY,
                    token_id TEXT NOT NULL,
                    token_symbol TEXT DEFAULT '',
                    chain TEXT DEFAULT 'solana',
                    contract_address TEXT DEFAULT '',
                    entity_id TEXT DEFAULT '',
                    entity_label TEXT DEFAULT '',
                    entity_quality TEXT DEFAULT 'unknown',
                    whale_action TEXT DEFAULT 'buy',
                    whale_size_usd REAL DEFAULT 0,
                    strategy TEXT DEFAULT 'follow',
                    entry_size_usd REAL DEFAULT 100,
                    max_slippage_bps INTEGER DEFAULT 200,
                    max_price_impact REAL DEFAULT 0.03,
                    take_profit_pct REAL DEFAULT 30,
                    stop_loss_pct REAL DEFAULT 15,
                    max_holding_hours REAL DEFAULT 48,
                    mev_risk_tolerance TEXT DEFAULT 'medium',
                    max_gas_usd REAL DEFAULT 10,
                    status TEXT DEFAULT 'proposed',
                    triggered_by TEXT DEFAULT '[]',
                    supporting_agents TEXT DEFAULT '[]',
                    opposing_agents TEXT DEFAULT '[]',
                    confidence REAL DEFAULT 0.5,
                    created_at REAL,
                    updated_at REAL
                );

                CREATE TABLE IF NOT EXISTS flow_kol_plans (
                    id TEXT PRIMARY KEY,
                    token_id TEXT NOT NULL,
                    token_symbol TEXT DEFAULT '',
                    chain TEXT DEFAULT 'solana',
                    contract_address TEXT DEFAULT '',
                    entity_id TEXT DEFAULT '',
                    kol_handle TEXT DEFAULT '',
                    kol_follower_count INTEGER DEFAULT 0,
                    mention_text TEXT DEFAULT '',
                    mention_sentiment REAL DEFAULT 0,
                    has_onchain_buy INTEGER DEFAULT 0,
                    entry_size_usd REAL DEFAULT 25,
                    max_slippage_bps INTEGER DEFAULT 500,
                    max_price_impact REAL DEFAULT 0.08,
                    take_profit_pct REAL DEFAULT 100,
                    stop_loss_pct REAL DEFAULT 40,
                    max_holding_hours REAL DEFAULT 12,
                    mev_risk_tolerance TEXT DEFAULT 'high',
                    max_gas_usd REAL DEFAULT 3,
                    status TEXT DEFAULT 'proposed',
                    triggered_by TEXT DEFAULT '[]',
                    supporting_agents TEXT DEFAULT '[]',
                    opposing_agents TEXT DEFAULT '[]',
                    confidence REAL DEFAULT 0.5,
                    created_at REAL,
                    updated_at REAL
                );

                CREATE TABLE IF NOT EXISTS flow_sniper_orders (
                    id TEXT PRIMARY KEY,
                    plan_id TEXT NOT NULL,
                    plan_type TEXT DEFAULT 'meme',
                    token_id TEXT DEFAULT '',
                    token_symbol TEXT DEFAULT '',
                    chain TEXT DEFAULT 'solana',
                    contract_address TEXT DEFAULT '',
                    direction TEXT DEFAULT 'buy',
                    size_usd REAL DEFAULT 0,
                    size_tokens REAL DEFAULT 0,
                    max_slippage_bps INTEGER DEFAULT 300,
                    max_gas_usd REAL DEFAULT 5,
                    min_liquidity_usd REAL DEFAULT 10000,
                    max_price_impact REAL DEFAULT 0.05,
                    mev_risk_tolerance TEXT DEFAULT 'low',
                    route_type TEXT DEFAULT 'standard',
                    dex_router TEXT DEFAULT '',
                    mev_relay TEXT DEFAULT '',
                    sim_price_impact REAL DEFAULT 0,
                    sim_output_tokens REAL DEFAULT 0,
                    sim_passed INTEGER DEFAULT 0,
                    sim_reason TEXT DEFAULT '',
                    status TEXT DEFAULT 'proposed',
                    created_at REAL
                );

                CREATE TABLE IF NOT EXISTS flow_sniper_fills (
                    id TEXT PRIMARY KEY,
                    order_id TEXT NOT NULL,
                    plan_id TEXT DEFAULT '',
                    token_id TEXT DEFAULT '',
                    token_symbol TEXT DEFAULT '',
                    chain TEXT DEFAULT 'solana',
                    direction TEXT DEFAULT 'buy',
                    filled_size_usd REAL DEFAULT 0,
                    filled_tokens REAL DEFAULT 0,
                    fill_price_usd REAL DEFAULT 0,
                    expected_price_usd REAL DEFAULT 0,
                    actual_slippage_bps INTEGER DEFAULT 0,
                    actual_price_impact REAL DEFAULT 0,
                    gas_used_usd REAL DEFAULT 0,
                    latency_ms REAL DEFAULT 0,
                    route_type_used TEXT DEFAULT 'standard',
                    mev_detected INTEGER DEFAULT 0,
                    mev_loss_usd REAL DEFAULT 0,
                    mev_details TEXT DEFAULT '',
                    tx_hash TEXT DEFAULT '',
                    block_number INTEGER DEFAULT 0,
                    timestamp REAL,
                    success INTEGER DEFAULT 1,
                    error TEXT DEFAULT ''
                );

                CREATE INDEX IF NOT EXISTS idx_flow_events_token ON flow_events(token_id);
                CREATE INDEX IF NOT EXISTS idx_flow_events_entity ON flow_events(entity_id);
                CREATE INDEX IF NOT EXISTS idx_flow_events_type ON flow_events(event_type);
                CREATE INDEX IF NOT EXISTS idx_flow_events_ts ON flow_events(timestamp);
                CREATE INDEX IF NOT EXISTS idx_flow_opinions_token ON flow_opinions(token_id);
                CREATE INDEX IF NOT EXISTS idx_flow_entities_type ON flow_entities(entity_type);
            """)
            conn.commit()
        finally:
            if self._persistent_conn is None:
                conn.close()

    # ── Tokens ────────────────────────────────────────────────────────

    def upsert_token(self, token: Token):
        conn = self._get_conn()
        try:
            conn.execute("""
                INSERT INTO flow_tokens
                    (id, symbol, name, contract_address, chain, decimals,
                     logo_url, tags, deployer_address, first_lp_timestamp,
                     initial_mcap_usd, fdv_usd, total_liquidity_usd,
                     liquidity_json, cex_listings, is_active, created_at, updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET
                    symbol=excluded.symbol, name=excluded.name,
                    total_liquidity_usd=excluded.total_liquidity_usd,
                    liquidity_json=excluded.liquidity_json,
                    cex_listings=excluded.cex_listings,
                    is_active=excluded.is_active,
                    updated_at=excluded.updated_at
            """, (
                token.id, token.symbol, token.name, token.contract_address,
                token.chain, token.decimals, token.logo_url,
                json.dumps(token.tags), token.deployer_address,
                token.first_lp_timestamp, token.initial_mcap_usd,
                token.fdv_usd, token.total_liquidity_usd,
                json.dumps([li.to_dict() if hasattr(li, 'to_dict') else li for li in token.liquidity]),
                json.dumps(token.cex_listings), int(token.is_active),
                token.created_at, _now(),
            ))
            conn.commit()
        finally:
            if self._persistent_conn is None:
                conn.close()

    def get_token(self, token_id: str) -> Optional[Token]:
        conn = self._get_conn()
        try:
            row = conn.execute(
                "SELECT * FROM flow_tokens WHERE id = ?", (token_id,)
            ).fetchone()
            if not row:
                return None
            return self._row_to_token(row, conn)
        finally:
            if self._persistent_conn is None:
                conn.close()

    def list_tokens(self, chain: Optional[str] = None, active_only: bool = True) -> List[Token]:
        conn = self._get_conn()
        try:
            query = "SELECT * FROM flow_tokens WHERE 1=1"
            params: list = []
            if active_only:
                query += " AND is_active = 1"
            if chain:
                query += " AND chain = ?"
                params.append(chain)
            query += " ORDER BY updated_at DESC"
            rows = conn.execute(query, params).fetchall()
            return [self._row_to_token(r, conn) for r in rows]
        finally:
            if self._persistent_conn is None:
                conn.close()

    def _row_to_token(self, row, conn) -> Token:
        cols = [d[0] for d in conn.execute("SELECT * FROM flow_tokens LIMIT 0").description]
        d = dict(zip(cols, row))
        return Token(
            id=d["id"], symbol=d["symbol"], name=d["name"],
            contract_address=d["contract_address"], chain=d["chain"],
            decimals=d["decimals"], logo_url=d.get("logo_url", ""),
            tags=json.loads(d.get("tags", "[]")),
            deployer_address=d.get("deployer_address", ""),
            first_lp_timestamp=d.get("first_lp_timestamp", 0),
            initial_mcap_usd=d.get("initial_mcap_usd", 0),
            fdv_usd=d.get("fdv_usd", 0),
            total_liquidity_usd=d.get("total_liquidity_usd", 0),
            cex_listings=json.loads(d.get("cex_listings", "[]")),
            is_active=bool(d.get("is_active", 1)),
            created_at=d.get("created_at", 0),
            updated_at=d.get("updated_at", 0),
        )

    # ── Entities ──────────────────────────────────────────────────────

    def upsert_entity(self, entity: Entity):
        conn = self._get_conn()
        try:
            conn.execute("""
                INSERT INTO flow_entities
                    (id, address, chain, entity_type, label, tags,
                     social_handle, telegram_handle, follower_count,
                     historical_pnl_usd, hit_rate, trade_count,
                     avg_holding_hours, is_active, quality, created_at, updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET
                    label=excluded.label, tags=excluded.tags,
                    historical_pnl_usd=excluded.historical_pnl_usd,
                    hit_rate=excluded.hit_rate, trade_count=excluded.trade_count,
                    is_active=excluded.is_active, quality=excluded.quality,
                    updated_at=excluded.updated_at
            """, (
                entity.id, entity.address, entity.chain, entity.entity_type,
                entity.label, json.dumps(entity.tags), entity.social_handle,
                entity.telegram_handle, entity.follower_count,
                entity.historical_pnl_usd, entity.hit_rate, entity.trade_count,
                entity.avg_holding_hours, int(entity.is_active), entity.quality,
                entity.created_at, _now(),
            ))
            conn.commit()
        finally:
            if self._persistent_conn is None:
                conn.close()

    def get_entity(self, entity_id: str) -> Optional[Entity]:
        conn = self._get_conn()
        try:
            row = conn.execute(
                "SELECT * FROM flow_entities WHERE id = ?", (entity_id,)
            ).fetchone()
            if not row:
                return None
            return self._row_to_entity(row, conn)
        finally:
            if self._persistent_conn is None:
                conn.close()

    def list_entities(self, entity_type: Optional[str] = None) -> List[Entity]:
        conn = self._get_conn()
        try:
            query = "SELECT * FROM flow_entities WHERE is_active = 1"
            params: list = []
            if entity_type:
                query += " AND entity_type = ?"
                params.append(entity_type)
            query += " ORDER BY historical_pnl_usd DESC"
            rows = conn.execute(query, params).fetchall()
            return [self._row_to_entity(r, conn) for r in rows]
        finally:
            if self._persistent_conn is None:
                conn.close()

    def _row_to_entity(self, row, conn) -> Entity:
        cols = [d[0] for d in conn.execute("SELECT * FROM flow_entities LIMIT 0").description]
        d = dict(zip(cols, row))
        return Entity(
            id=d["id"], address=d["address"], chain=d["chain"],
            entity_type=d["entity_type"], label=d["label"],
            tags=json.loads(d.get("tags", "[]")),
            social_handle=d.get("social_handle", ""),
            telegram_handle=d.get("telegram_handle", ""),
            follower_count=d.get("follower_count", 0),
            historical_pnl_usd=d.get("historical_pnl_usd", 0),
            hit_rate=d.get("hit_rate", 0),
            trade_count=d.get("trade_count", 0),
            avg_holding_hours=d.get("avg_holding_hours", 0),
            is_active=bool(d.get("is_active", 1)),
            quality=d.get("quality", "unknown"),
            created_at=d.get("created_at", 0),
            updated_at=d.get("updated_at", 0),
        )

    # ── Flow events ───────────────────────────────────────────────────

    def add_event(self, event: FlowEvent):
        conn = self._get_conn()
        try:
            conn.execute("""
                INSERT OR REPLACE INTO flow_events
                    (id, event_type, chain, token_id, token_symbol,
                     entity_id, entity_address, entity_type,
                     size_usd, size_tokens, direction, tx_hash, price_usd,
                     price_impact, slippage, pool_liquidity_before,
                     pool_liquidity_after, mention_text, mention_sentiment,
                     mention_engagement, mention_source, timestamp, metadata_json)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                event.id, event.event_type, event.chain,
                event.token_id, event.token_symbol,
                event.entity_id, event.entity_address, event.entity_type,
                event.size_usd, event.size_tokens, event.direction,
                event.tx_hash, event.price_usd,
                event.price_impact, event.slippage,
                event.pool_liquidity_before, event.pool_liquidity_after,
                event.mention_text, event.mention_sentiment,
                event.mention_engagement, event.mention_source,
                event.timestamp, json.dumps(event.metadata),
            ))
            conn.commit()
        finally:
            if self._persistent_conn is None:
                conn.close()

    def list_events(
        self, token_id: Optional[str] = None,
        entity_id: Optional[str] = None,
        event_type: Optional[str] = None,
        since_hours: float = 24,
        limit: int = 200,
    ) -> List[FlowEvent]:
        conn = self._get_conn()
        try:
            query = "SELECT * FROM flow_events WHERE timestamp >= ?"
            params: list = [_now() - since_hours * 3600]
            if token_id:
                query += " AND token_id = ?"
                params.append(token_id)
            if entity_id:
                query += " AND entity_id = ?"
                params.append(entity_id)
            if event_type:
                query += " AND event_type = ?"
                params.append(event_type)
            query += " ORDER BY timestamp DESC LIMIT ?"
            params.append(limit)
            rows = conn.execute(query, params).fetchall()
            return [self._row_to_event(r, conn) for r in rows]
        finally:
            if self._persistent_conn is None:
                conn.close()

    def _row_to_event(self, row, conn) -> FlowEvent:
        cols = [d[0] for d in conn.execute("SELECT * FROM flow_events LIMIT 0").description]
        d = dict(zip(cols, row))
        return FlowEvent(
            id=d["id"], event_type=d["event_type"], chain=d["chain"],
            token_id=d.get("token_id", ""), token_symbol=d.get("token_symbol", ""),
            entity_id=d.get("entity_id", ""), entity_address=d.get("entity_address", ""),
            entity_type=d.get("entity_type", ""),
            size_usd=d.get("size_usd", 0), size_tokens=d.get("size_tokens", 0),
            direction=d.get("direction", "buy"), tx_hash=d.get("tx_hash", ""),
            price_usd=d.get("price_usd", 0),
            price_impact=d.get("price_impact", 0), slippage=d.get("slippage", 0),
            pool_liquidity_before=d.get("pool_liquidity_before", 0),
            pool_liquidity_after=d.get("pool_liquidity_after", 0),
            mention_text=d.get("mention_text", ""),
            mention_sentiment=d.get("mention_sentiment", 0),
            mention_engagement=d.get("mention_engagement", 0),
            mention_source=d.get("mention_source", ""),
            timestamp=d.get("timestamp", 0),
            metadata=json.loads(d.get("metadata_json", "{}")),
        )

    # ── Opinions ──────────────────────────────────────────────────────

    def add_opinion(self, opinion: FlowOpinion):
        conn = self._get_conn()
        try:
            conn.execute("""
                INSERT OR REPLACE INTO flow_opinions
                    (id, agent_id, token_id, token_symbol, chain,
                     contract_address, stance, probability,
                     expected_return_1h, expected_return_24h, confidence,
                     reasoning, driver_event_ids, driver_entity_ids, timestamp)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                opinion.id, opinion.agent_id, opinion.token_id,
                opinion.token_symbol, opinion.chain, opinion.contract_address,
                opinion.stance, opinion.probability,
                opinion.expected_return_1h, opinion.expected_return_24h,
                opinion.confidence, opinion.reasoning,
                json.dumps(opinion.driver_event_ids),
                json.dumps(opinion.driver_entity_ids),
                opinion.timestamp,
            ))
            conn.commit()
        finally:
            if self._persistent_conn is None:
                conn.close()

    def list_opinions(self, token_id: str) -> List[FlowOpinion]:
        conn = self._get_conn()
        try:
            rows = conn.execute(
                "SELECT * FROM flow_opinions WHERE token_id = ? ORDER BY timestamp DESC",
                (token_id,),
            ).fetchall()
            return [self._row_to_opinion(r, conn) for r in rows]
        finally:
            if self._persistent_conn is None:
                conn.close()

    def _row_to_opinion(self, row, conn) -> FlowOpinion:
        cols = [d[0] for d in conn.execute("SELECT * FROM flow_opinions LIMIT 0").description]
        d = dict(zip(cols, row))
        return FlowOpinion(
            id=d["id"], agent_id=d["agent_id"], token_id=d["token_id"],
            token_symbol=d.get("token_symbol", ""), chain=d.get("chain", "solana"),
            contract_address=d.get("contract_address", ""),
            stance=d.get("stance", "watch"), probability=d.get("probability", 0.5),
            expected_return_1h=d.get("expected_return_1h", 0),
            expected_return_24h=d.get("expected_return_24h", 0),
            confidence=d.get("confidence", 0.5), reasoning=d.get("reasoning", ""),
            driver_event_ids=json.loads(d.get("driver_event_ids", "[]")),
            driver_entity_ids=json.loads(d.get("driver_entity_ids", "[]")),
            timestamp=d.get("timestamp", 0),
        )

    # ── Meme plans ────────────────────────────────────────────────────

    def add_meme_plan(self, plan: MemePlan):
        conn = self._get_conn()
        try:
            conn.execute("""
                INSERT OR REPLACE INTO flow_meme_plans
                    (id, token_id, token_symbol, chain, contract_address,
                     entry_size_usd, max_slippage_bps, max_price_impact,
                     min_liquidity_usd, take_profit_pct, stop_loss_pct,
                     max_holding_hours, trailing_stop_pct, mev_risk_tolerance,
                     max_gas_usd, status, triggered_by, supporting_agents,
                     opposing_agents, confidence, created_at, updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                plan.id, plan.token_id, plan.token_symbol, plan.chain,
                plan.contract_address, plan.entry_size_usd,
                plan.max_slippage_bps, plan.max_price_impact,
                plan.min_liquidity_usd, plan.take_profit_pct,
                plan.stop_loss_pct, plan.max_holding_hours,
                plan.trailing_stop_pct, plan.mev_risk_tolerance,
                plan.max_gas_usd, plan.status,
                json.dumps(plan.triggered_by),
                json.dumps(plan.supporting_agents),
                json.dumps(plan.opposing_agents),
                plan.confidence, plan.created_at, _now(),
            ))
            conn.commit()
        finally:
            if self._persistent_conn is None:
                conn.close()

    def list_meme_plans(self, status: Optional[str] = None) -> List[MemePlan]:
        conn = self._get_conn()
        try:
            query = "SELECT * FROM flow_meme_plans WHERE 1=1"
            params: list = []
            if status:
                query += " AND status = ?"
                params.append(status)
            query += " ORDER BY created_at DESC"
            rows = conn.execute(query, params).fetchall()
            return [self._row_to_meme_plan(r, conn) for r in rows]
        finally:
            if self._persistent_conn is None:
                conn.close()

    def _row_to_meme_plan(self, row, conn) -> MemePlan:
        cols = [d[0] for d in conn.execute("SELECT * FROM flow_meme_plans LIMIT 0").description]
        d = dict(zip(cols, row))
        return MemePlan(
            id=d["id"], token_id=d["token_id"], token_symbol=d.get("token_symbol", ""),
            chain=d.get("chain", "solana"), contract_address=d.get("contract_address", ""),
            entry_size_usd=d.get("entry_size_usd", 50),
            max_slippage_bps=d.get("max_slippage_bps", 300),
            max_price_impact=d.get("max_price_impact", 0.05),
            min_liquidity_usd=d.get("min_liquidity_usd", 10000),
            take_profit_pct=d.get("take_profit_pct", 50),
            stop_loss_pct=d.get("stop_loss_pct", 30),
            max_holding_hours=d.get("max_holding_hours", 24),
            trailing_stop_pct=d.get("trailing_stop_pct", 0),
            mev_risk_tolerance=d.get("mev_risk_tolerance", "low"),
            max_gas_usd=d.get("max_gas_usd", 5),
            status=d.get("status", "proposed"),
            triggered_by=json.loads(d.get("triggered_by", "[]")),
            supporting_agents=json.loads(d.get("supporting_agents", "[]")),
            opposing_agents=json.loads(d.get("opposing_agents", "[]")),
            confidence=d.get("confidence", 0.5),
            created_at=d.get("created_at", 0), updated_at=d.get("updated_at", 0),
        )

    # ── Whale plans ───────────────────────────────────────────────────

    def add_whale_plan(self, plan: WhalePlan):
        conn = self._get_conn()
        try:
            conn.execute("""
                INSERT OR REPLACE INTO flow_whale_plans
                    (id, token_id, token_symbol, chain, contract_address,
                     entity_id, entity_label, entity_quality,
                     whale_action, whale_size_usd, strategy,
                     entry_size_usd, max_slippage_bps, max_price_impact,
                     take_profit_pct, stop_loss_pct, max_holding_hours,
                     mev_risk_tolerance, max_gas_usd, status,
                     triggered_by, supporting_agents, opposing_agents,
                     confidence, created_at, updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                plan.id, plan.token_id, plan.token_symbol, plan.chain,
                plan.contract_address, plan.entity_id, plan.entity_label,
                plan.entity_quality, plan.whale_action, plan.whale_size_usd,
                plan.strategy, plan.entry_size_usd, plan.max_slippage_bps,
                plan.max_price_impact, plan.take_profit_pct, plan.stop_loss_pct,
                plan.max_holding_hours, plan.mev_risk_tolerance, plan.max_gas_usd,
                plan.status, json.dumps(plan.triggered_by),
                json.dumps(plan.supporting_agents),
                json.dumps(plan.opposing_agents),
                plan.confidence, plan.created_at, _now(),
            ))
            conn.commit()
        finally:
            if self._persistent_conn is None:
                conn.close()

    def list_whale_plans(self, status: Optional[str] = None) -> List[WhalePlan]:
        conn = self._get_conn()
        try:
            query = "SELECT * FROM flow_whale_plans WHERE 1=1"
            params: list = []
            if status:
                query += " AND status = ?"
                params.append(status)
            query += " ORDER BY created_at DESC"
            rows = conn.execute(query, params).fetchall()
            return [self._row_to_whale_plan(r, conn) for r in rows]
        finally:
            if self._persistent_conn is None:
                conn.close()

    def _row_to_whale_plan(self, row, conn) -> WhalePlan:
        cols = [d[0] for d in conn.execute("SELECT * FROM flow_whale_plans LIMIT 0").description]
        d = dict(zip(cols, row))
        return WhalePlan(
            id=d["id"], token_id=d["token_id"], token_symbol=d.get("token_symbol", ""),
            chain=d.get("chain", "solana"), contract_address=d.get("contract_address", ""),
            entity_id=d.get("entity_id", ""), entity_label=d.get("entity_label", ""),
            entity_quality=d.get("entity_quality", "unknown"),
            whale_action=d.get("whale_action", "buy"),
            whale_size_usd=d.get("whale_size_usd", 0),
            strategy=d.get("strategy", "follow"),
            entry_size_usd=d.get("entry_size_usd", 100),
            max_slippage_bps=d.get("max_slippage_bps", 200),
            max_price_impact=d.get("max_price_impact", 0.03),
            take_profit_pct=d.get("take_profit_pct", 30),
            stop_loss_pct=d.get("stop_loss_pct", 15),
            max_holding_hours=d.get("max_holding_hours", 48),
            mev_risk_tolerance=d.get("mev_risk_tolerance", "medium"),
            max_gas_usd=d.get("max_gas_usd", 10),
            status=d.get("status", "proposed"),
            triggered_by=json.loads(d.get("triggered_by", "[]")),
            supporting_agents=json.loads(d.get("supporting_agents", "[]")),
            opposing_agents=json.loads(d.get("opposing_agents", "[]")),
            confidence=d.get("confidence", 0.5),
            created_at=d.get("created_at", 0), updated_at=d.get("updated_at", 0),
        )

    # ── KOL plans ─────────────────────────────────────────────────────

    def add_kol_plan(self, plan: KOLPlan):
        conn = self._get_conn()
        try:
            conn.execute("""
                INSERT OR REPLACE INTO flow_kol_plans
                    (id, token_id, token_symbol, chain, contract_address,
                     entity_id, kol_handle, kol_follower_count,
                     mention_text, mention_sentiment, has_onchain_buy,
                     entry_size_usd, max_slippage_bps, max_price_impact,
                     take_profit_pct, stop_loss_pct, max_holding_hours,
                     mev_risk_tolerance, max_gas_usd, status,
                     triggered_by, supporting_agents, opposing_agents,
                     confidence, created_at, updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                plan.id, plan.token_id, plan.token_symbol, plan.chain,
                plan.contract_address, plan.entity_id, plan.kol_handle,
                plan.kol_follower_count, plan.mention_text,
                plan.mention_sentiment, int(plan.has_onchain_buy),
                plan.entry_size_usd, plan.max_slippage_bps,
                plan.max_price_impact, plan.take_profit_pct,
                plan.stop_loss_pct, plan.max_holding_hours,
                plan.mev_risk_tolerance, plan.max_gas_usd, plan.status,
                json.dumps(plan.triggered_by),
                json.dumps(plan.supporting_agents),
                json.dumps(plan.opposing_agents),
                plan.confidence, plan.created_at, _now(),
            ))
            conn.commit()
        finally:
            if self._persistent_conn is None:
                conn.close()

    def list_kol_plans(self, status: Optional[str] = None) -> List[KOLPlan]:
        conn = self._get_conn()
        try:
            query = "SELECT * FROM flow_kol_plans WHERE 1=1"
            params: list = []
            if status:
                query += " AND status = ?"
                params.append(status)
            query += " ORDER BY created_at DESC"
            rows = conn.execute(query, params).fetchall()
            return [self._row_to_kol_plan(r, conn) for r in rows]
        finally:
            if self._persistent_conn is None:
                conn.close()

    def _row_to_kol_plan(self, row, conn) -> KOLPlan:
        cols = [d[0] for d in conn.execute("SELECT * FROM flow_kol_plans LIMIT 0").description]
        d = dict(zip(cols, row))
        return KOLPlan(
            id=d["id"], token_id=d["token_id"], token_symbol=d.get("token_symbol", ""),
            chain=d.get("chain", "solana"), contract_address=d.get("contract_address", ""),
            entity_id=d.get("entity_id", ""), kol_handle=d.get("kol_handle", ""),
            kol_follower_count=d.get("kol_follower_count", 0),
            mention_text=d.get("mention_text", ""),
            mention_sentiment=d.get("mention_sentiment", 0),
            has_onchain_buy=bool(d.get("has_onchain_buy", 0)),
            entry_size_usd=d.get("entry_size_usd", 25),
            max_slippage_bps=d.get("max_slippage_bps", 500),
            max_price_impact=d.get("max_price_impact", 0.08),
            take_profit_pct=d.get("take_profit_pct", 100),
            stop_loss_pct=d.get("stop_loss_pct", 40),
            max_holding_hours=d.get("max_holding_hours", 12),
            mev_risk_tolerance=d.get("mev_risk_tolerance", "high"),
            max_gas_usd=d.get("max_gas_usd", 3),
            status=d.get("status", "proposed"),
            triggered_by=json.loads(d.get("triggered_by", "[]")),
            supporting_agents=json.loads(d.get("supporting_agents", "[]")),
            opposing_agents=json.loads(d.get("opposing_agents", "[]")),
            confidence=d.get("confidence", 0.5),
            created_at=d.get("created_at", 0), updated_at=d.get("updated_at", 0),
        )

    # ── Sniper orders & fills ─────────────────────────────────────────

    def add_sniper_order(self, order: SniperOrder):
        conn = self._get_conn()
        try:
            conn.execute("""
                INSERT OR REPLACE INTO flow_sniper_orders
                    (id, plan_id, plan_type, token_id, token_symbol,
                     chain, contract_address, direction, size_usd,
                     size_tokens, max_slippage_bps, max_gas_usd,
                     min_liquidity_usd, max_price_impact,
                     mev_risk_tolerance, route_type, dex_router,
                     mev_relay, sim_price_impact, sim_output_tokens,
                     sim_passed, sim_reason, status, created_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                order.id, order.plan_id, order.plan_type, order.token_id,
                order.token_symbol, order.chain, order.contract_address,
                order.direction, order.size_usd, order.size_tokens,
                order.max_slippage_bps, order.max_gas_usd,
                order.min_liquidity_usd, order.max_price_impact,
                order.mev_risk_tolerance, order.route_type,
                order.dex_router, order.mev_relay,
                order.sim_price_impact, order.sim_output_tokens,
                int(order.sim_passed), order.sim_reason,
                order.status, order.created_at,
            ))
            conn.commit()
        finally:
            if self._persistent_conn is None:
                conn.close()

    def add_sniper_fill(self, fill: SniperFill):
        conn = self._get_conn()
        try:
            conn.execute("""
                INSERT OR REPLACE INTO flow_sniper_fills
                    (id, order_id, plan_id, token_id, token_symbol,
                     chain, direction, filled_size_usd, filled_tokens,
                     fill_price_usd, expected_price_usd,
                     actual_slippage_bps, actual_price_impact,
                     gas_used_usd, latency_ms, route_type_used,
                     mev_detected, mev_loss_usd, mev_details,
                     tx_hash, block_number, timestamp, success, error)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                fill.id, fill.order_id, fill.plan_id, fill.token_id,
                fill.token_symbol, fill.chain, fill.direction,
                fill.filled_size_usd, fill.filled_tokens,
                fill.fill_price_usd, fill.expected_price_usd,
                fill.actual_slippage_bps, fill.actual_price_impact,
                fill.gas_used_usd, fill.latency_ms, fill.route_type_used,
                int(fill.mev_detected), fill.mev_loss_usd,
                fill.mev_details, fill.tx_hash, fill.block_number,
                fill.timestamp, int(fill.success), fill.error,
            ))
            conn.commit()
        finally:
            if self._persistent_conn is None:
                conn.close()

    def list_sniper_orders(self, limit: int = 50) -> List[SniperOrder]:
        conn = self._get_conn()
        try:
            rows = conn.execute(
                "SELECT * FROM flow_sniper_orders ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [self._row_to_sniper_order(r, conn) for r in rows]
        finally:
            if self._persistent_conn is None:
                conn.close()

    def list_sniper_fills(self, limit: int = 50) -> List[SniperFill]:
        conn = self._get_conn()
        try:
            rows = conn.execute(
                "SELECT * FROM flow_sniper_fills ORDER BY timestamp DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [self._row_to_sniper_fill(r, conn) for r in rows]
        finally:
            if self._persistent_conn is None:
                conn.close()

    def _row_to_sniper_order(self, row, conn) -> SniperOrder:
        cols = [d[0] for d in conn.execute("SELECT * FROM flow_sniper_orders LIMIT 0").description]
        d = dict(zip(cols, row))
        return SniperOrder(
            id=d["id"], plan_id=d["plan_id"], plan_type=d.get("plan_type", "meme"),
            token_id=d.get("token_id", ""), token_symbol=d.get("token_symbol", ""),
            chain=d.get("chain", "solana"), contract_address=d.get("contract_address", ""),
            direction=d.get("direction", "buy"),
            size_usd=d.get("size_usd", 0), size_tokens=d.get("size_tokens", 0),
            max_slippage_bps=d.get("max_slippage_bps", 300),
            max_gas_usd=d.get("max_gas_usd", 5),
            min_liquidity_usd=d.get("min_liquidity_usd", 10000),
            max_price_impact=d.get("max_price_impact", 0.05),
            mev_risk_tolerance=d.get("mev_risk_tolerance", "low"),
            route_type=d.get("route_type", "standard"),
            dex_router=d.get("dex_router", ""),
            mev_relay=d.get("mev_relay", ""),
            sim_price_impact=d.get("sim_price_impact", 0),
            sim_output_tokens=d.get("sim_output_tokens", 0),
            sim_passed=bool(d.get("sim_passed", 0)),
            sim_reason=d.get("sim_reason", ""),
            status=d.get("status", "proposed"),
            created_at=d.get("created_at", 0),
        )

    def _row_to_sniper_fill(self, row, conn) -> SniperFill:
        cols = [d[0] for d in conn.execute("SELECT * FROM flow_sniper_fills LIMIT 0").description]
        d = dict(zip(cols, row))
        return SniperFill(
            id=d["id"], order_id=d["order_id"],
            plan_id=d.get("plan_id", ""), token_id=d.get("token_id", ""),
            token_symbol=d.get("token_symbol", ""),
            chain=d.get("chain", "solana"), direction=d.get("direction", "buy"),
            filled_size_usd=d.get("filled_size_usd", 0),
            filled_tokens=d.get("filled_tokens", 0),
            fill_price_usd=d.get("fill_price_usd", 0),
            expected_price_usd=d.get("expected_price_usd", 0),
            actual_slippage_bps=d.get("actual_slippage_bps", 0),
            actual_price_impact=d.get("actual_price_impact", 0),
            gas_used_usd=d.get("gas_used_usd", 0),
            latency_ms=d.get("latency_ms", 0),
            route_type_used=d.get("route_type_used", "standard"),
            mev_detected=bool(d.get("mev_detected", 0)),
            mev_loss_usd=d.get("mev_loss_usd", 0),
            mev_details=d.get("mev_details", ""),
            tx_hash=d.get("tx_hash", ""),
            block_number=d.get("block_number", 0),
            timestamp=d.get("timestamp", 0),
            success=bool(d.get("success", 1)),
            error=d.get("error", ""),
        )

    # ── Update plan status ────────────────────────────────────────────

    def update_plan_status(self, plan_id: str, plan_type: str, new_status: str):
        """Update status for any plan type (meme/whale/kol)."""
        table = {
            "meme": "flow_meme_plans",
            "whale": "flow_whale_plans",
            "kol": "flow_kol_plans",
        }.get(plan_type)
        if not table:
            return
        conn = self._get_conn()
        try:
            conn.execute(
                f"UPDATE {table} SET status = ?, updated_at = ? WHERE id = ?",
                (new_status, _now(), plan_id),
            )
            conn.commit()
        finally:
            if self._persistent_conn is None:
                conn.close()

    # ── Consensus ─────────────────────────────────────────────────────

    def build_token_consensus(self, token_id: str) -> Dict[str, Any]:
        """Build consensus view for a single token.

        Aggregates:
          - Recent flow events (buys/sells, whale, KOL, LP)
          - Swarm opinions (stance distribution, avg confidence)
          - Active plans (meme, whale, kol) and their statuses
          - Flow score
        """
        conn = self._get_conn()
        try:
            # Get token
            token = self.get_token(token_id)
            if not token:
                return {}

            # Recent events (last 24h)
            events = self.list_events(token_id=token_id, since_hours=24)

            # Count events by type
            whale_buys = sum(1 for e in events if e.event_type in (
                FlowEventType.LARGE_BUY.value,) and e.entity_type in ("whale", "smart_wallet"))
            whale_sells = sum(1 for e in events if e.event_type in (
                FlowEventType.LARGE_SELL.value,) and e.entity_type in ("whale", "smart_wallet"))
            kol_buys = sum(1 for e in events if e.event_type == FlowEventType.KOL_BUY.value)
            kol_mentions = sum(1 for e in events if e.event_type == FlowEventType.KOL_MENTION.value)
            lp_adds = sum(1 for e in events if e.event_type == FlowEventType.LP_ADDED.value)
            lp_removes = sum(1 for e in events if e.event_type == FlowEventType.LP_REMOVED.value)

            flow_score = compute_flow_score(
                whale_buys, whale_sells, kol_buys, kol_mentions,
                lp_adds, lp_removes, token.age_hours,
            )

            # Opinions
            opinions = self.list_opinions(token_id)
            stance_counts = {s.value: 0 for s in FlowStance}
            total_confidence = 0.0
            for op in opinions:
                stance_counts[op.stance] = stance_counts.get(op.stance, 0) + 1
                total_confidence += op.confidence
            avg_confidence = total_confidence / max(len(opinions), 1)

            # Dominant stance
            dominant_stance = max(stance_counts, key=stance_counts.get) if opinions else "watch"

            # Plans
            meme_plans = [p for p in self.list_meme_plans() if p.token_id == token_id]
            whale_plans = [p for p in self.list_whale_plans() if p.token_id == token_id]
            kol_plans = [p for p in self.list_kol_plans() if p.token_id == token_id]

            active_statuses = {PlanStatus.PROPOSED.value, PlanStatus.APPROVED.value, PlanStatus.EXECUTING.value}
            active_plans = (
                [p for p in meme_plans if p.status in active_statuses]
                + [p for p in whale_plans if p.status in active_statuses]
                + [p for p in kol_plans if p.status in active_statuses]
            )

            return {
                "token_id": token.id,
                "symbol": token.symbol,
                "name": token.name,
                "chain": token.chain,
                "contract_address": token.contract_address,
                "liquidity_usd": token.total_liquidity_usd,
                "price_usd": token.current_price_usd,
                "age_hours": round(token.age_hours, 1),
                "flow_score": round(flow_score, 1),
                "event_summary": {
                    "total": len(events),
                    "whale_buys": whale_buys,
                    "whale_sells": whale_sells,
                    "kol_buys": kol_buys,
                    "kol_mentions": kol_mentions,
                    "lp_adds": lp_adds,
                    "lp_removes": lp_removes,
                },
                "opinion_summary": {
                    "total": len(opinions),
                    "stance_distribution": stance_counts,
                    "dominant_stance": dominant_stance,
                    "avg_confidence": round(avg_confidence, 3),
                },
                "plan_summary": {
                    "meme_plans": len(meme_plans),
                    "whale_plans": len(whale_plans),
                    "kol_plans": len(kol_plans),
                    "active_plans": len(active_plans),
                },
                "recent_events": [e.to_dict() for e in events[:10]],
            }
        finally:
            if self._persistent_conn is None:
                conn.close()

    def build_all_consensus(self, chain: Optional[str] = None) -> List[Dict[str, Any]]:
        """Build consensus for all active tokens."""
        tokens = self.list_tokens(chain=chain)
        results = []
        for tok in tokens:
            c = self.build_token_consensus(tok.id)
            if c:
                results.append(c)
        # Sort by flow score descending
        results.sort(key=lambda x: x.get("flow_score", 0), reverse=True)
        return results

    # ── Metrics ───────────────────────────────────────────────────────

    def get_flow_metrics(self) -> Dict[str, Any]:
        """Aggregate metrics across the flow domain."""
        conn = self._get_conn()
        try:
            token_count = conn.execute(
                "SELECT COUNT(*) FROM flow_tokens WHERE is_active = 1"
            ).fetchone()[0]
            entity_count = conn.execute(
                "SELECT COUNT(*) FROM flow_entities WHERE is_active = 1"
            ).fetchone()[0]
            event_count_24h = conn.execute(
                "SELECT COUNT(*) FROM flow_events WHERE timestamp >= ?",
                (_now() - 86400,),
            ).fetchone()[0]
            opinion_count = conn.execute(
                "SELECT COUNT(*) FROM flow_opinions"
            ).fetchone()[0]

            # Plan counts by type and status
            meme_plans = conn.execute("SELECT status, COUNT(*) FROM flow_meme_plans GROUP BY status").fetchall()
            whale_plans = conn.execute("SELECT status, COUNT(*) FROM flow_whale_plans GROUP BY status").fetchall()
            kol_plans_rows = conn.execute("SELECT status, COUNT(*) FROM flow_kol_plans GROUP BY status").fetchall()

            def _plan_summary(rows):
                d = {r[0]: r[1] for r in rows}
                return {
                    "proposed": d.get("proposed", 0),
                    "approved": d.get("approved", 0),
                    "executing": d.get("executing", 0),
                    "filled": d.get("filled", 0),
                    "failed": d.get("failed", 0),
                    "total": sum(d.values()),
                }

            # Sniper stats
            fills = self.list_sniper_fills(limit=1000)
            total_fills = len(fills)
            successful_fills = sum(1 for f in fills if f.success)
            total_mev_loss = sum(f.mev_loss_usd for f in fills)
            mev_incidents = sum(1 for f in fills if f.mev_detected)
            avg_slippage = (
                sum(f.actual_slippage_bps for f in fills) / max(total_fills, 1)
            )
            avg_latency = (
                sum(f.latency_ms for f in fills) / max(total_fills, 1)
            )
            total_volume = sum(f.filled_size_usd for f in fills)

            # Entity stats
            whale_count = conn.execute(
                "SELECT COUNT(*) FROM flow_entities WHERE entity_type IN ('whale','smart_wallet') AND is_active = 1"
            ).fetchone()[0]
            kol_count = conn.execute(
                "SELECT COUNT(*) FROM flow_entities WHERE entity_type = 'kol' AND is_active = 1"
            ).fetchone()[0]

            return {
                "tokens_tracked": token_count,
                "entities_tracked": entity_count,
                "whale_count": whale_count,
                "kol_count": kol_count,
                "events_24h": event_count_24h,
                "opinions_total": opinion_count,
                "plans": {
                    "meme": _plan_summary(meme_plans),
                    "whale": _plan_summary(whale_plans),
                    "kol": _plan_summary(kol_plans_rows),
                },
                "sniper": {
                    "total_fills": total_fills,
                    "success_rate": successful_fills / max(total_fills, 1),
                    "total_volume_usd": round(total_volume, 2),
                    "avg_slippage_bps": round(avg_slippage, 1),
                    "avg_latency_ms": round(avg_latency, 1),
                    "mev_incidents": mev_incidents,
                    "mev_loss_usd": round(total_mev_loss, 2),
                },
            }
        finally:
            if self._persistent_conn is None:
                conn.close()


# ── Singleton ─────────────────────────────────────────────────────────

_flow_store: Optional[FlowStore] = None


def get_flow_store() -> FlowStore:
    global _flow_store
    if _flow_store is None:
        _flow_store = FlowStore()
    return _flow_store
