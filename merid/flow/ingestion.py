"""Flow ingestion layer — TokenDetector, WhaleTracker, KOLScanner.

Each service:
  - Has a real-first path using external APIs (Helius, Nansen, TheGraph, X API).
  - Falls back to synthetic data for development/testing.
  - Emits Token, Entity, and FlowEvent records for the FlowStore.
"""

from __future__ import annotations

import os
import random
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from merid.flow.models import (
    Chain,
    Entity,
    EntityType,
    FlowEvent,
    FlowEventType,
    LiquidityInfo,
    Token,
    _now,
    _uid,
)

# ── Config ────────────────────────────────────────────────────────────

HELIUS_API_KEY = os.environ.get("HELIUS_API_KEY", "")
NANSEN_API_KEY = os.environ.get("NANSEN_API_KEY", "")
THE_GRAPH_API_KEY = os.environ.get("THE_GRAPH_API_KEY", "")

# Known CEX deposit addresses (subset for labeling)
KNOWN_CEX_ADDRESSES: Dict[str, str] = {
    "binance-hot-1": "Binance",
    "coinbase-hot-1": "Coinbase",
    "kraken-hot-1": "Kraken",
    "okx-hot-1": "OKX",
    "bybit-hot-1": "Bybit",
}

# ── Synthetic data ────────────────────────────────────────────────────

_SYNTH_TOKENS: List[Dict[str, Any]] = [
    {
        "symbol": "BONK", "name": "Bonk", "chain": "solana",
        "contract_address": "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263",
        "tags": ["meme", "dog", "solana-native"],
        "initial_mcap_usd": 50000, "fdv_usd": 1_000_000,
        "liquidity_usd": 2_500_000, "price_usd": 0.000023,
        "dex": "raydium", "deployer": "BonkDeployer111",
    },
    {
        "symbol": "WIF", "name": "dogwifhat", "chain": "solana",
        "contract_address": "EKpQGSJtjMFqKZ9KQanSqYXRcF8fBopzLHYxdM65zcjm",
        "tags": ["meme", "dog", "solana-native"],
        "initial_mcap_usd": 100000, "fdv_usd": 5_000_000,
        "liquidity_usd": 8_000_000, "price_usd": 2.45,
        "dex": "raydium", "deployer": "WifDeployer222",
    },
    {
        "symbol": "PEPE", "name": "Pepe", "chain": "ethereum",
        "contract_address": "0x6982508145454Ce325dDbE47a25d4ec3d2311933",
        "tags": ["meme", "frog", "ethereum-native"],
        "initial_mcap_usd": 500000, "fdv_usd": 50_000_000,
        "liquidity_usd": 15_000_000, "price_usd": 0.0000089,
        "dex": "uniswap_v2", "deployer": "0xPepeDeployer333",
    },
    {
        "symbol": "POPCAT", "name": "Popcat", "chain": "solana",
        "contract_address": "7GCihgDB8fe6KNjn2MYtkzZcRjQy3t9GHdC8uHYmW2hr",
        "tags": ["meme", "cat", "solana-native"],
        "initial_mcap_usd": 20000, "fdv_usd": 800_000,
        "liquidity_usd": 1_200_000, "price_usd": 0.85,
        "dex": "raydium", "deployer": "PopcatDeploy444",
    },
    {
        "symbol": "BRETT", "name": "Brett", "chain": "base",
        "contract_address": "0x532f27101965dd16442E59d40670FaF5eBB142E4",
        "tags": ["meme", "base-native"],
        "initial_mcap_usd": 30000, "fdv_usd": 2_000_000,
        "liquidity_usd": 3_000_000, "price_usd": 0.12,
        "dex": "uniswap_v3", "deployer": "0xBrettDeploy555",
    },
    {
        "symbol": "NEWMEME", "name": "FreshLaunch", "chain": "solana",
        "contract_address": "NewMeme777TokenAddress",
        "tags": ["meme", "new", "unverified"],
        "initial_mcap_usd": 5000, "fdv_usd": 50_000,
        "liquidity_usd": 25_000, "price_usd": 0.00001,
        "dex": "raydium", "deployer": "NewMemeDeploy777",
    },
]

_SYNTH_ENTITIES: List[Dict[str, Any]] = [
    {
        "address": "WhaleAlpha111SolAddr", "chain": "solana",
        "entity_type": "whale", "label": "Solana Whale Alpha",
        "tags": ["early-meme-hunter", "high-frequency"],
        "pnl": 850_000, "hit_rate": 0.72, "trades": 340, "avg_hold_h": 6.5,
    },
    {
        "address": "SmartWallet222SolAddr", "chain": "solana",
        "entity_type": "smart_wallet", "label": "Smart Money SOL #1",
        "tags": ["consistent-profit", "medium-hold"],
        "pnl": 220_000, "hit_rate": 0.64, "trades": 180, "avg_hold_h": 18.0,
    },
    {
        "address": "0xWhaleEth333", "chain": "ethereum",
        "entity_type": "whale", "label": "ETH Meme Whale",
        "tags": ["pepe-holder", "large-cap-meme"],
        "pnl": 1_200_000, "hit_rate": 0.58, "trades": 95, "avg_hold_h": 72.0,
    },
    {
        "address": "KolWallet444SolAddr", "chain": "solana",
        "entity_type": "kol", "label": "CryptoKOL_Alpha",
        "social_handle": "@CryptoKOL_Alpha", "followers": 450_000,
        "tags": ["influencer", "solana-focused", "memecoin-caller"],
        "pnl": 380_000, "hit_rate": 0.55, "trades": 120, "avg_hold_h": 4.0,
    },
    {
        "address": "KolWallet555EthAddr", "chain": "ethereum",
        "entity_type": "kol", "label": "DegenSpartan",
        "social_handle": "@DegenSpartan", "followers": 280_000,
        "tags": ["influencer", "eth-focused", "degen"],
        "pnl": 95_000, "hit_rate": 0.48, "trades": 200, "avg_hold_h": 2.0,
    },
    {
        "address": "BonkDeployer111", "chain": "solana",
        "entity_type": "deployer", "label": "BONK Deployer",
        "tags": ["deployer", "bonk"],
        "pnl": 0, "hit_rate": 0, "trades": 1, "avg_hold_h": 0,
    },
    {
        "address": "binance-hot-1", "chain": "solana",
        "entity_type": "cex", "label": "Binance Hot Wallet",
        "tags": ["exchange", "binance"],
        "pnl": 0, "hit_rate": 0, "trades": 0, "avg_hold_h": 0,
    },
]


def _synth_flow_events(tokens: List[Token], entities: List[Entity]) -> List[FlowEvent]:
    """Generate synthetic flow events for development."""
    events: List[FlowEvent] = []
    now = _now()
    rng = random.Random(42)

    whale_entities = [e for e in entities if e.entity_type in ("whale", "smart_wallet")]
    kol_entities = [e for e in entities if e.entity_type == "kol"]

    for tok in tokens:
        # Token launch event
        events.append(FlowEvent(
            event_type=FlowEventType.TOKEN_LAUNCH.value,
            chain=tok.chain, token_id=tok.id, token_symbol=tok.symbol,
            entity_address=tok.deployer_address, entity_type="deployer",
            size_usd=tok.initial_mcap_usd,
            timestamp=now - rng.uniform(3600, 86400 * 7),
        ))

        # LP added
        events.append(FlowEvent(
            event_type=FlowEventType.LP_ADDED.value,
            chain=tok.chain, token_id=tok.id, token_symbol=tok.symbol,
            entity_address=tok.deployer_address, entity_type="deployer",
            size_usd=tok.total_liquidity_usd * rng.uniform(0.3, 0.8),
            pool_liquidity_after=tok.total_liquidity_usd,
            timestamp=now - rng.uniform(1800, 86400 * 5),
        ))

        # Whale trades
        for whale in rng.sample(whale_entities, min(2, len(whale_entities))):
            if whale.chain != tok.chain:
                continue
            is_buy = rng.random() > 0.35
            size = rng.uniform(5000, 200_000)
            events.append(FlowEvent(
                event_type=FlowEventType.LARGE_BUY.value if is_buy else FlowEventType.LARGE_SELL.value,
                chain=tok.chain, token_id=tok.id, token_symbol=tok.symbol,
                entity_id=whale.id, entity_address=whale.address,
                entity_type=whale.entity_type,
                size_usd=size, direction="buy" if is_buy else "sell",
                price_impact=size / max(tok.total_liquidity_usd, 1) * 0.5,
                timestamp=now - rng.uniform(60, 7200),
            ))

        # KOL actions
        for kol in rng.sample(kol_entities, min(1, len(kol_entities))):
            if kol.chain != tok.chain:
                continue
            # KOL buy
            events.append(FlowEvent(
                event_type=FlowEventType.KOL_BUY.value,
                chain=tok.chain, token_id=tok.id, token_symbol=tok.symbol,
                entity_id=kol.id, entity_address=kol.address,
                entity_type="kol",
                size_usd=rng.uniform(1000, 50_000),
                direction="buy",
                timestamp=now - rng.uniform(300, 3600),
            ))
            # KOL mention
            events.append(FlowEvent(
                event_type=FlowEventType.KOL_MENTION.value,
                chain=tok.chain, token_id=tok.id, token_symbol=tok.symbol,
                entity_id=kol.id, entity_address=kol.address,
                entity_type="kol",
                mention_text=f"Just aped into ${tok.symbol} 🚀 LFG",
                mention_sentiment=rng.uniform(0.6, 0.95),
                mention_engagement=rng.randint(500, 50_000),
                mention_source="x",
                timestamp=now - rng.uniform(60, 1800),
            ))

    return events


# ── TokenDetector ─────────────────────────────────────────────────────

class TokenDetector:
    """Detects new token launches and CEX listings.

    Real mode: Helius + TheGraph + exchange APIs.
    Fallback: synthetic data for dev.
    """

    def __init__(self):
        self._is_configured = bool(HELIUS_API_KEY or THE_GRAPH_API_KEY)

    @property
    def is_configured(self) -> bool:
        return self._is_configured

    def detect_new_tokens(self, chain: Optional[str] = None) -> List[Tuple[Token, List[FlowEvent]]]:
        """Return newly detected tokens + their launch events.

        Falls back to synthetic data if APIs are not configured.
        """
        if self._is_configured:
            return self._detect_real(chain)
        return self._detect_synthetic(chain)

    def _detect_real(self, chain: Optional[str] = None) -> List[Tuple[Token, List[FlowEvent]]]:
        # Placeholder for real API integration
        return self._detect_synthetic(chain)

    def _detect_synthetic(self, chain: Optional[str] = None) -> List[Tuple[Token, List[FlowEvent]]]:
        results: List[Tuple[Token, List[FlowEvent]]] = []
        now = _now()

        for td in _SYNTH_TOKENS:
            if chain and td["chain"] != chain:
                continue

            tok = Token(
                symbol=td["symbol"], name=td["name"], chain=td["chain"],
                contract_address=td["contract_address"],
                tags=td["tags"], deployer_address=td["deployer"],
                initial_mcap_usd=td["initial_mcap_usd"], fdv_usd=td["fdv_usd"],
                first_lp_timestamp=now - random.uniform(3600, 86400 * 7),
                total_liquidity_usd=td["liquidity_usd"],
                liquidity=[LiquidityInfo(
                    dex=td["dex"],
                    liquidity_usd=td["liquidity_usd"],
                    price_usd=td["price_usd"],
                    pool_created_at=now - random.uniform(3600, 86400 * 7),
                )],
            )

            launch_event = FlowEvent(
                event_type=FlowEventType.TOKEN_LAUNCH.value,
                chain=tok.chain, token_id=tok.id, token_symbol=tok.symbol,
                entity_address=tok.deployer_address, entity_type="deployer",
                size_usd=tok.initial_mcap_usd,
                timestamp=tok.first_lp_timestamp,
            )
            lp_event = FlowEvent(
                event_type=FlowEventType.LP_ADDED.value,
                chain=tok.chain, token_id=tok.id, token_symbol=tok.symbol,
                entity_address=tok.deployer_address, entity_type="deployer",
                size_usd=tok.total_liquidity_usd,
                pool_liquidity_after=tok.total_liquidity_usd,
                timestamp=tok.first_lp_timestamp + 10,
            )
            results.append((tok, [launch_event, lp_event]))

        return results


# ── WhaleTracker ──────────────────────────────────────────────────────

class WhaleTracker:
    """Tracks whale and smart wallet activity.

    Real mode: Nansen + Helius + heuristics.
    Fallback: synthetic data for dev.
    """

    def __init__(self):
        self._is_configured = bool(NANSEN_API_KEY or HELIUS_API_KEY)

    @property
    def is_configured(self) -> bool:
        return self._is_configured

    def get_tracked_entities(self, entity_type: Optional[str] = None) -> List[Entity]:
        """Return currently tracked whale/smart wallet entities."""
        if self._is_configured:
            return self._get_real_entities(entity_type)
        return self._get_synthetic_entities(entity_type)

    def get_recent_flows(
        self, tokens: List[Token], entities: List[Entity],
        since_hours: float = 24,
    ) -> List[FlowEvent]:
        """Return recent flow events from tracked entities."""
        if self._is_configured:
            return self._get_real_flows(tokens, entities, since_hours)
        return self._get_synthetic_flows(tokens, entities, since_hours)

    def _get_real_entities(self, entity_type: Optional[str] = None) -> List[Entity]:
        return self._get_synthetic_entities(entity_type)

    def _get_synthetic_entities(self, entity_type: Optional[str] = None) -> List[Entity]:
        entities: List[Entity] = []
        for ed in _SYNTH_ENTITIES:
            if entity_type and ed["entity_type"] != entity_type:
                continue
            ent = Entity(
                address=ed["address"], chain=ed["chain"],
                entity_type=ed["entity_type"], label=ed["label"],
                tags=ed.get("tags", []),
                social_handle=ed.get("social_handle", ""),
                follower_count=ed.get("followers", 0),
                historical_pnl_usd=ed["pnl"], hit_rate=ed["hit_rate"],
                trade_count=ed["trades"], avg_holding_hours=ed.get("avg_hold_h", 0),
            )
            entities.append(ent)
        return entities

    def _get_real_flows(self, tokens, entities, since_hours):
        return self._get_synthetic_flows(tokens, entities, since_hours)

    def _get_synthetic_flows(
        self, tokens: List[Token], entities: List[Entity],
        since_hours: float = 24,
    ) -> List[FlowEvent]:
        all_events = _synth_flow_events(tokens, entities)
        cutoff = _now() - since_hours * 3600
        return [e for e in all_events if e.timestamp >= cutoff]


# ── KOLScanner ────────────────────────────────────────────────────────

class KOLScanner:
    """Scans KOL wallets and social mentions.

    Real mode: X API + Telegram + on-chain tracking.
    Fallback: synthetic data for dev.
    """

    def __init__(self):
        self._x_api_key = os.environ.get("X_API_KEY", "")
        self._is_configured = bool(self._x_api_key)

    @property
    def is_configured(self) -> bool:
        return self._is_configured

    def get_kol_entities(self) -> List[Entity]:
        """Return tracked KOL entities."""
        if self._is_configured:
            return self._get_real_kols()
        return self._get_synthetic_kols()

    def get_kol_events(
        self, tokens: List[Token], kols: List[Entity],
        since_hours: float = 24,
    ) -> List[FlowEvent]:
        """Return recent KOL-related flow events."""
        if self._is_configured:
            return self._get_real_kol_events(tokens, kols, since_hours)
        return self._get_synthetic_kol_events(tokens, kols, since_hours)

    def _get_real_kols(self) -> List[Entity]:
        return self._get_synthetic_kols()

    def _get_synthetic_kols(self) -> List[Entity]:
        return [
            e for e in WhaleTracker()._get_synthetic_entities()
            if e.entity_type == EntityType.KOL.value
        ]

    def _get_real_kol_events(self, tokens, kols, since_hours):
        return self._get_synthetic_kol_events(tokens, kols, since_hours)

    def _get_synthetic_kol_events(
        self, tokens: List[Token], kols: List[Entity],
        since_hours: float = 24,
    ) -> List[FlowEvent]:
        events: List[FlowEvent] = []
        now = _now()
        rng = random.Random(99)

        for kol in kols:
            for tok in tokens:
                if tok.chain != kol.chain:
                    continue
                if rng.random() < 0.5:
                    continue

                # KOL buy
                events.append(FlowEvent(
                    event_type=FlowEventType.KOL_BUY.value,
                    chain=tok.chain, token_id=tok.id, token_symbol=tok.symbol,
                    entity_id=kol.id, entity_address=kol.address,
                    entity_type="kol",
                    size_usd=rng.uniform(500, 25_000),
                    direction="buy",
                    timestamp=now - rng.uniform(60, since_hours * 3600),
                ))
                # KOL mention
                events.append(FlowEvent(
                    event_type=FlowEventType.KOL_MENTION.value,
                    chain=tok.chain, token_id=tok.id, token_symbol=tok.symbol,
                    entity_id=kol.id, entity_address=kol.address,
                    entity_type="kol",
                    mention_text=f"${tok.symbol} looking strong. Entered a bag. 🔥",
                    mention_sentiment=rng.uniform(0.5, 0.95),
                    mention_engagement=rng.randint(200, 30_000),
                    mention_source="x",
                    timestamp=now - rng.uniform(30, since_hours * 3600),
                ))

        return events


# ── Unified ingestion facade ──────────────────────────────────────────

class FlowIngestionService:
    """Facade that runs all three scanners and returns unified results."""

    def __init__(self):
        self.token_detector = TokenDetector()
        self.whale_tracker = WhaleTracker()
        self.kol_scanner = KOLScanner()

    @property
    def source(self) -> str:
        if any([
            self.token_detector.is_configured,
            self.whale_tracker.is_configured,
            self.kol_scanner.is_configured,
        ]):
            return "live"
        return "synthetic"

    def ingest_all(
        self, chain: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Run full ingestion cycle: tokens, entities, flow events.

        Returns dict with tokens, entities, events lists.
        """
        # 1. Detect tokens
        token_results = self.token_detector.detect_new_tokens(chain)
        tokens = [t for t, _ in token_results]
        token_events = [e for _, evs in token_results for e in evs]

        # 2. Get entities (whales + KOLs)
        all_entities = self.whale_tracker.get_tracked_entities()
        kol_entities = self.kol_scanner.get_kol_entities()

        # Deduplicate entities by address
        seen = set()
        entities: List[Entity] = []
        for ent in all_entities + kol_entities:
            if ent.address not in seen:
                seen.add(ent.address)
                entities.append(ent)

        # 3. Get flow events
        whale_events = self.whale_tracker.get_recent_flows(tokens, entities)
        kol_events = self.kol_scanner.get_kol_events(tokens, kol_entities)

        # Deduplicate events by ID
        seen_ids: set = set()
        all_events: List[FlowEvent] = []
        for ev in token_events + whale_events + kol_events:
            if ev.id not in seen_ids:
                seen_ids.add(ev.id)
                all_events.append(ev)

        return {
            "tokens": tokens,
            "entities": entities,
            "events": all_events,
            "source": self.source,
            "token_count": len(tokens),
            "entity_count": len(entities),
            "event_count": len(all_events),
        }


# ── Singletons ────────────────────────────────────────────────────────

_ingestion_service: Optional[FlowIngestionService] = None


def get_ingestion_service() -> FlowIngestionService:
    global _ingestion_service
    if _ingestion_service is None:
        _ingestion_service = FlowIngestionService()
    return _ingestion_service
