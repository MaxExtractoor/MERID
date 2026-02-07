"""
MERID Memecoin Sniping Engine - Phase 20

High-risk, high-alpha detection with safety rails.
ALERT-ONLY by default - execution requires consensus + manual approval.
"""

from __future__ import annotations

import asyncio
import hashlib
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple

from utils.logger import get_logger

logger = get_logger("sniping.memecoin_engine")


class TokenRisk(Enum):
    """Token risk classification."""
    SAFE = "safe"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    EXTREME = "extreme"
    HONEYPOT = "honeypot"
    RUGPULL = "rugpull"


class LaunchType(Enum):
    """Token launch type."""
    FAIR_LAUNCH = "fair_launch"
    PRESALE = "presale"
    STEALTH = "stealth"
    MIGRATION = "migration"
    AIRDROP = "airdrop"
    UNKNOWN = "unknown"


class AlertType(Enum):
    """Snipe alert type."""
    NEW_TOKEN = "new_token"
    LIQUIDITY_ADDED = "liquidity_added"
    WHALE_BUY = "whale_buy"
    SOCIAL_SPIKE = "social_spike"
    DEV_ACTIVITY = "dev_activity"
    HONEYPOT_WARNING = "honeypot_warning"
    RUGPULL_WARNING = "rugpull_warning"


@dataclass
class TokenLaunch:
    """Detected token launch."""
    token_address: str
    token_name: str
    token_symbol: str
    chain: str
    launch_type: LaunchType
    detected_at: float
    pair_address: Optional[str] = None
    initial_liquidity_usd: float = 0.0
    initial_price: float = 0.0
    deployer_address: Optional[str] = None
    total_supply: float = 0.0
    circulating_supply: float = 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "token_address": self.token_address,
            "token_name": self.token_name,
            "token_symbol": self.token_symbol,
            "chain": self.chain,
            "launch_type": self.launch_type.value,
            "detected_at": self.detected_at,
            "pair_address": self.pair_address,
            "initial_liquidity_usd": self.initial_liquidity_usd,
            "initial_price": self.initial_price,
            "deployer_address": self.deployer_address,
            "total_supply": self.total_supply,
            "circulating_supply": self.circulating_supply,
        }


@dataclass
class LiquidityLock:
    """Liquidity lock verification."""
    token_address: str
    is_locked: bool
    lock_platform: Optional[str] = None
    lock_duration_days: float = 0.0
    lock_percentage: float = 0.0
    unlock_date: Optional[float] = None
    verified: bool = False
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "token_address": self.token_address,
            "is_locked": self.is_locked,
            "lock_platform": self.lock_platform,
            "lock_duration_days": self.lock_duration_days,
            "lock_percentage": self.lock_percentage,
            "unlock_date": self.unlock_date,
            "verified": self.verified,
        }


@dataclass
class HoneypotAnalysis:
    """Honeypot detection analysis."""
    token_address: str
    is_honeypot: bool
    can_buy: bool
    can_sell: bool
    buy_tax_pct: float = 0.0
    sell_tax_pct: float = 0.0
    transfer_tax_pct: float = 0.0
    max_tx_pct: float = 100.0
    max_wallet_pct: float = 100.0
    is_blacklisted: bool = False
    has_proxy: bool = False
    has_mint_function: bool = False
    has_pause_function: bool = False
    owner_can_change_tax: bool = False
    confidence: float = 0.5
    warnings: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "token_address": self.token_address,
            "is_honeypot": self.is_honeypot,
            "can_buy": self.can_buy,
            "can_sell": self.can_sell,
            "buy_tax_pct": self.buy_tax_pct,
            "sell_tax_pct": self.sell_tax_pct,
            "transfer_tax_pct": self.transfer_tax_pct,
            "max_tx_pct": self.max_tx_pct,
            "max_wallet_pct": self.max_wallet_pct,
            "is_blacklisted": self.is_blacklisted,
            "has_proxy": self.has_proxy,
            "has_mint_function": self.has_mint_function,
            "has_pause_function": self.has_pause_function,
            "owner_can_change_tax": self.owner_can_change_tax,
            "confidence": self.confidence,
            "warnings": self.warnings,
        }


@dataclass
class WalletGraph:
    """Bundle/insider wallet graph analysis."""
    token_address: str
    deployer_address: str
    connected_wallets: int
    insider_wallets: List[str] = field(default_factory=list)
    bundle_detected: bool = False
    dev_holding_pct: float = 0.0
    top_10_holding_pct: float = 0.0
    fresh_wallets_pct: float = 0.0
    suspicious_patterns: List[str] = field(default_factory=list)
    risk_score: float = 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "token_address": self.token_address,
            "deployer_address": self.deployer_address,
            "connected_wallets": self.connected_wallets,
            "insider_wallets": self.insider_wallets[:10],  # Limit for response
            "bundle_detected": self.bundle_detected,
            "dev_holding_pct": self.dev_holding_pct,
            "top_10_holding_pct": self.top_10_holding_pct,
            "fresh_wallets_pct": self.fresh_wallets_pct,
            "suspicious_patterns": self.suspicious_patterns,
            "risk_score": self.risk_score,
        }


@dataclass
class MEVRoute:
    """MEV-aware routing recommendation."""
    token_address: str
    recommended_route: str
    use_private_mempool: bool
    use_flashbots: bool
    max_priority_fee_gwei: float
    sandwich_risk: float
    frontrun_risk: float
    recommended_slippage_pct: float
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "token_address": self.token_address,
            "recommended_route": self.recommended_route,
            "use_private_mempool": self.use_private_mempool,
            "use_flashbots": self.use_flashbots,
            "max_priority_fee_gwei": self.max_priority_fee_gwei,
            "sandwich_risk": self.sandwich_risk,
            "frontrun_risk": self.frontrun_risk,
            "recommended_slippage_pct": self.recommended_slippage_pct,
        }


@dataclass
class SnipeAlert:
    """Memecoin snipe alert."""
    alert_id: str
    alert_type: AlertType
    token_address: str
    token_symbol: str
    chain: str
    risk_level: TokenRisk
    description: str
    opportunity_score: float  # 0-100
    time_sensitivity_seconds: float
    recommended_action: str
    requires_approval: bool = True
    created_at: float = field(default_factory=time.time)
    expires_at: Optional[float] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "alert_id": self.alert_id,
            "alert_type": self.alert_type.value,
            "token_address": self.token_address,
            "token_symbol": self.token_symbol,
            "chain": self.chain,
            "risk_level": self.risk_level.value,
            "description": self.description,
            "opportunity_score": self.opportunity_score,
            "time_sensitivity_seconds": self.time_sensitivity_seconds,
            "recommended_action": self.recommended_action,
            "requires_approval": self.requires_approval,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "metadata": self.metadata,
        }


class TokenLaunchDetector:
    """
    Detects new token launches across chains.
    
    Monitors:
    - New pair creations on DEXes
    - Token deployments
    - Liquidity additions
    """
    
    # Known DEX factory addresses
    DEX_FACTORIES = {
        "ethereum": {
            "uniswap_v2": "0x5C69bEe701ef814a2B6a3EDD4B1652CB9cc5aA6f",
            "uniswap_v3": "0x1F98431c8aD98523631AE4a59f267346ea31F984",
            "sushiswap": "0xC0AEe478e3658e2610c5F7A4A2E1777cE9e4f2Ac",
        },
        "bsc": {
            "pancakeswap_v2": "0xcA143Ce32Fe78f1f7019d7d551a6402fC5350c73",
            "pancakeswap_v3": "0x0BFbCF9fa4f9C56B0F40a671Ad40E0805A091865",
        },
        "base": {
            "uniswap_v3": "0x33128a8fC17869897dcE68Ed026d694621f6FDfD",
            "aerodrome": "0x420DD381b31aEf6683db6B902084cB0FFECe40Da",
        },
        "solana": {
            "raydium": "raydium_amm_program",
            "orca": "orca_whirlpool_program",
            "pump_fun": "pump_fun_program",
        },
    }
    
    def __init__(self):
        self._detected_tokens: Dict[str, TokenLaunch] = {}
        self._monitored_chains: Set[str] = {"ethereum", "bsc", "base", "solana"}
    
    def add_chain(self, chain: str) -> None:
        """Add chain to monitoring."""
        self._monitored_chains.add(chain)
    
    def detect_launch(
        self,
        token_address: str,
        token_name: str,
        token_symbol: str,
        chain: str,
        pair_address: Optional[str] = None,
        initial_liquidity_usd: float = 0.0,
        deployer_address: Optional[str] = None,
    ) -> TokenLaunch:
        """Record a detected token launch."""
        # Determine launch type based on characteristics
        launch_type = LaunchType.UNKNOWN
        if initial_liquidity_usd > 0:
            launch_type = LaunchType.FAIR_LAUNCH
        elif deployer_address:
            launch_type = LaunchType.STEALTH
        
        launch = TokenLaunch(
            token_address=token_address,
            token_name=token_name,
            token_symbol=token_symbol,
            chain=chain,
            launch_type=launch_type,
            detected_at=time.time(),
            pair_address=pair_address,
            initial_liquidity_usd=initial_liquidity_usd,
            deployer_address=deployer_address,
        )
        
        self._detected_tokens[token_address] = launch
        logger.info("Detected token launch: %s (%s) on %s", token_symbol, token_address[:10], chain)
        
        return launch
    
    def get_recent_launches(self, hours: float = 24.0, chain: Optional[str] = None) -> List[TokenLaunch]:
        """Get recent token launches."""
        cutoff = time.time() - (hours * 3600)
        launches = [
            l for l in self._detected_tokens.values()
            if l.detected_at >= cutoff
        ]
        
        if chain:
            launches = [l for l in launches if l.chain == chain]
        
        return sorted(launches, key=lambda x: x.detected_at, reverse=True)


class LiquidityLockVerifier:
    """
    Verifies liquidity locks.
    
    Checks:
    - Lock platform (Unicrypt, Team.Finance, PinkSale, etc.)
    - Lock duration
    - Lock percentage
    """
    
    # Known lock platforms
    LOCK_PLATFORMS = {
        "unicrypt": "0x663A5C229c09b049E36dCc11a9B0d4a8Eb9db214",
        "team_finance": "0xE2fE530C047f2d85298b07D9333C05737f1435fB",
        "pinksale": "0x71B5759d73262FBb223956913ecF4ecC51057641",
        "mudra": "0xae2b892e6d3b5c4e2b3e3f3f3f3f3f3f3f3f3f3f",
    }
    
    def __init__(self):
        self._verified_locks: Dict[str, LiquidityLock] = {}
    
    def verify_lock(
        self,
        token_address: str,
        lock_platform: Optional[str] = None,
        lock_duration_days: float = 0.0,
        lock_percentage: float = 0.0,
    ) -> LiquidityLock:
        """Verify liquidity lock for a token."""
        is_locked = lock_duration_days > 0 and lock_percentage > 0
        
        # Calculate unlock date
        unlock_date = None
        if is_locked:
            unlock_date = time.time() + (lock_duration_days * 86400)
        
        # Verification confidence
        verified = lock_platform in self.LOCK_PLATFORMS if lock_platform else False
        
        lock = LiquidityLock(
            token_address=token_address,
            is_locked=is_locked,
            lock_platform=lock_platform,
            lock_duration_days=lock_duration_days,
            lock_percentage=lock_percentage,
            unlock_date=unlock_date,
            verified=verified,
        )
        
        self._verified_locks[token_address] = lock
        return lock
    
    def get_lock(self, token_address: str) -> Optional[LiquidityLock]:
        """Get verified lock for a token."""
        return self._verified_locks.get(token_address)


class HoneypotDetector:
    """
    Detects honeypot tokens.
    
    Analyzes:
    - Buy/sell tax
    - Transfer restrictions
    - Contract functions
    - Blacklist mechanisms
    """
    
    # Suspicious function signatures
    SUSPICIOUS_FUNCTIONS = {
        "setFee": "owner can change fees",
        "setTax": "owner can change tax",
        "blacklist": "blacklist function exists",
        "pause": "contract can be paused",
        "mint": "tokens can be minted",
        "setMaxTx": "max transaction can be changed",
        "setMaxWallet": "max wallet can be changed",
    }
    
    def __init__(self):
        self._analyses: Dict[str, HoneypotAnalysis] = {}
    
    def analyze(
        self,
        token_address: str,
        buy_tax_pct: float = 0.0,
        sell_tax_pct: float = 0.0,
        max_tx_pct: float = 100.0,
        max_wallet_pct: float = 100.0,
        has_blacklist: bool = False,
        has_proxy: bool = False,
        has_mint: bool = False,
        has_pause: bool = False,
        owner_can_change_tax: bool = False,
    ) -> HoneypotAnalysis:
        """Analyze token for honeypot characteristics."""
        warnings = []
        
        # Check for honeypot indicators
        is_honeypot = False
        can_buy = True
        can_sell = True
        
        # High tax = likely honeypot
        if sell_tax_pct > 50:
            is_honeypot = True
            can_sell = False
            warnings.append(f"Extremely high sell tax: {sell_tax_pct}%")
        elif sell_tax_pct > 20:
            warnings.append(f"High sell tax: {sell_tax_pct}%")
        
        if buy_tax_pct > 50:
            can_buy = False
            warnings.append(f"Extremely high buy tax: {buy_tax_pct}%")
        elif buy_tax_pct > 20:
            warnings.append(f"High buy tax: {buy_tax_pct}%")
        
        # Restrictive limits
        if max_tx_pct < 1:
            warnings.append(f"Very low max transaction: {max_tx_pct}%")
        if max_wallet_pct < 2:
            warnings.append(f"Very low max wallet: {max_wallet_pct}%")
        
        # Dangerous functions
        if has_blacklist:
            warnings.append("Contract has blacklist function")
        if has_proxy:
            warnings.append("Contract uses proxy pattern (upgradeable)")
        if has_mint:
            warnings.append("Owner can mint new tokens")
        if has_pause:
            warnings.append("Contract can be paused")
        if owner_can_change_tax:
            warnings.append("Owner can change tax rates")
        
        # Calculate confidence
        confidence = 0.9 - (len(warnings) * 0.1)
        confidence = max(0.1, min(0.9, confidence))
        
        analysis = HoneypotAnalysis(
            token_address=token_address,
            is_honeypot=is_honeypot,
            can_buy=can_buy,
            can_sell=can_sell,
            buy_tax_pct=buy_tax_pct,
            sell_tax_pct=sell_tax_pct,
            max_tx_pct=max_tx_pct,
            max_wallet_pct=max_wallet_pct,
            is_blacklisted=has_blacklist,
            has_proxy=has_proxy,
            has_mint_function=has_mint,
            has_pause_function=has_pause,
            owner_can_change_tax=owner_can_change_tax,
            confidence=confidence,
            warnings=warnings,
        )
        
        self._analyses[token_address] = analysis
        return analysis
    
    def get_analysis(self, token_address: str) -> Optional[HoneypotAnalysis]:
        """Get honeypot analysis for a token."""
        return self._analyses.get(token_address)


class WalletGraphAnalyzer:
    """
    Analyzes wallet connections and insider patterns.
    
    Detects:
    - Bundle wallets
    - Insider accumulation
    - Fresh wallet patterns
    - Dev wallet holdings
    """
    
    def __init__(self):
        self._graphs: Dict[str, WalletGraph] = {}
    
    def analyze(
        self,
        token_address: str,
        deployer_address: str,
        holder_data: List[Dict[str, Any]],
    ) -> WalletGraph:
        """Analyze wallet graph for a token."""
        suspicious_patterns = []
        insider_wallets = []
        
        # Calculate metrics
        total_holders = len(holder_data)
        dev_holding_pct = 0.0
        top_10_holding_pct = 0.0
        fresh_wallets = 0
        
        # Sort by balance
        sorted_holders = sorted(holder_data, key=lambda x: x.get("balance", 0), reverse=True)
        
        for i, holder in enumerate(sorted_holders[:10]):
            pct = holder.get("percentage", 0)
            top_10_holding_pct += pct
            
            address = holder.get("address", "")
            
            # Check if deployer
            if address.lower() == deployer_address.lower():
                dev_holding_pct = pct
                if pct > 10:
                    suspicious_patterns.append(f"Dev holds {pct:.1f}%")
            
            # Check for fresh wallets (would need on-chain data)
            if holder.get("is_fresh", False):
                fresh_wallets += 1
                insider_wallets.append(address)
            
            # Check for connected wallets
            if holder.get("connected_to_deployer", False):
                insider_wallets.append(address)
                suspicious_patterns.append(f"Wallet {address[:8]} connected to deployer")
        
        fresh_wallets_pct = (fresh_wallets / total_holders * 100) if total_holders > 0 else 0
        
        # Detect bundle
        bundle_detected = len(insider_wallets) >= 3 or fresh_wallets_pct > 30
        if bundle_detected:
            suspicious_patterns.append("Possible bundle/insider accumulation detected")
        
        # Calculate risk score
        risk_score = 0.0
        risk_score += min(dev_holding_pct / 10, 3.0)  # Dev holding
        risk_score += min(top_10_holding_pct / 20, 3.0)  # Concentration
        risk_score += min(fresh_wallets_pct / 10, 2.0)  # Fresh wallets
        risk_score += 2.0 if bundle_detected else 0.0  # Bundle
        risk_score = min(risk_score, 10.0)
        
        graph = WalletGraph(
            token_address=token_address,
            deployer_address=deployer_address,
            connected_wallets=len(insider_wallets),
            insider_wallets=insider_wallets,
            bundle_detected=bundle_detected,
            dev_holding_pct=dev_holding_pct,
            top_10_holding_pct=top_10_holding_pct,
            fresh_wallets_pct=fresh_wallets_pct,
            suspicious_patterns=suspicious_patterns,
            risk_score=risk_score,
        )
        
        self._graphs[token_address] = graph
        return graph


class MEVRouter:
    """
    MEV-aware routing for snipe transactions.
    
    Recommends:
    - Private mempool usage
    - Flashbots protection
    - Optimal gas settings
    """
    
    def __init__(self):
        self._routes: Dict[str, MEVRoute] = {}
    
    def get_route(
        self,
        token_address: str,
        chain: str,
        size_usd: float,
        urgency: str = "normal",
    ) -> MEVRoute:
        """Get MEV-aware routing recommendation."""
        # Calculate risks based on size and chain
        base_sandwich_risk = 0.3
        base_frontrun_risk = 0.2
        
        # Larger sizes attract more MEV
        size_multiplier = min(size_usd / 10000, 3.0)
        sandwich_risk = min(base_sandwich_risk * size_multiplier, 0.9)
        frontrun_risk = min(base_frontrun_risk * size_multiplier, 0.8)
        
        # Determine protection level
        use_private = sandwich_risk > 0.5 or frontrun_risk > 0.4
        use_flashbots = chain == "ethereum" and (sandwich_risk > 0.3 or urgency == "high")
        
        # Gas recommendations
        if urgency == "high":
            max_priority_fee = 50.0
            slippage = 15.0
        elif urgency == "normal":
            max_priority_fee = 20.0
            slippage = 10.0
        else:
            max_priority_fee = 10.0
            slippage = 5.0
        
        # Route selection
        if use_flashbots:
            route = "flashbots_protect"
        elif use_private:
            route = "private_mempool"
        else:
            route = "public_mempool"
        
        mev_route = MEVRoute(
            token_address=token_address,
            recommended_route=route,
            use_private_mempool=use_private,
            use_flashbots=use_flashbots,
            max_priority_fee_gwei=max_priority_fee,
            sandwich_risk=sandwich_risk,
            frontrun_risk=frontrun_risk,
            recommended_slippage_pct=slippage,
        )
        
        self._routes[token_address] = mev_route
        return mev_route


class AutoRejectEngine:
    """
    Auto-reject rule engine.
    
    Automatically rejects tokens that fail safety checks.
    """
    
    def __init__(self):
        self._rules: Dict[str, Dict[str, Any]] = {
            "max_buy_tax": {"value": 15.0, "enabled": True},
            "max_sell_tax": {"value": 20.0, "enabled": True},
            "min_liquidity_usd": {"value": 1000.0, "enabled": True},
            "require_lock": {"value": True, "enabled": True},
            "min_lock_days": {"value": 30.0, "enabled": True},
            "max_dev_holding_pct": {"value": 20.0, "enabled": True},
            "max_top10_holding_pct": {"value": 80.0, "enabled": True},
            "reject_honeypot": {"value": True, "enabled": True},
            "reject_proxy": {"value": True, "enabled": True},
            "reject_mint": {"value": True, "enabled": True},
        }
        self._rejected: Set[str] = set()
    
    def set_rule(self, rule_name: str, value: Any, enabled: bool = True) -> None:
        """Set a rejection rule."""
        self._rules[rule_name] = {"value": value, "enabled": enabled}
    
    def get_rules(self) -> Dict[str, Dict[str, Any]]:
        """Get all rules."""
        return self._rules.copy()
    
    def evaluate(
        self,
        token_address: str,
        honeypot: Optional[HoneypotAnalysis] = None,
        lock: Optional[LiquidityLock] = None,
        graph: Optional[WalletGraph] = None,
        liquidity_usd: float = 0.0,
    ) -> Tuple[bool, List[str]]:
        """
        Evaluate token against rejection rules.
        
        Returns:
            Tuple of (should_reject, list_of_reasons)
        """
        reasons = []
        
        # Tax checks
        if honeypot:
            if self._rules["max_buy_tax"]["enabled"]:
                if honeypot.buy_tax_pct > self._rules["max_buy_tax"]["value"]:
                    reasons.append(f"Buy tax {honeypot.buy_tax_pct}% exceeds max {self._rules['max_buy_tax']['value']}%")
            
            if self._rules["max_sell_tax"]["enabled"]:
                if honeypot.sell_tax_pct > self._rules["max_sell_tax"]["value"]:
                    reasons.append(f"Sell tax {honeypot.sell_tax_pct}% exceeds max {self._rules['max_sell_tax']['value']}%")
            
            if self._rules["reject_honeypot"]["enabled"] and honeypot.is_honeypot:
                reasons.append("Token identified as honeypot")
            
            if self._rules["reject_proxy"]["enabled"] and honeypot.has_proxy:
                reasons.append("Token uses proxy contract")
            
            if self._rules["reject_mint"]["enabled"] and honeypot.has_mint_function:
                reasons.append("Token has mint function")
        
        # Liquidity checks
        if self._rules["min_liquidity_usd"]["enabled"]:
            if liquidity_usd < self._rules["min_liquidity_usd"]["value"]:
                reasons.append(f"Liquidity ${liquidity_usd:.0f} below minimum ${self._rules['min_liquidity_usd']['value']:.0f}")
        
        # Lock checks
        if lock:
            if self._rules["require_lock"]["enabled"] and not lock.is_locked:
                reasons.append("Liquidity not locked")
            
            if self._rules["min_lock_days"]["enabled"] and lock.is_locked:
                if lock.lock_duration_days < self._rules["min_lock_days"]["value"]:
                    reasons.append(f"Lock duration {lock.lock_duration_days:.0f} days below minimum {self._rules['min_lock_days']['value']:.0f}")
        
        # Wallet graph checks
        if graph:
            if self._rules["max_dev_holding_pct"]["enabled"]:
                if graph.dev_holding_pct > self._rules["max_dev_holding_pct"]["value"]:
                    reasons.append(f"Dev holding {graph.dev_holding_pct:.1f}% exceeds max {self._rules['max_dev_holding_pct']['value']}%")
            
            if self._rules["max_top10_holding_pct"]["enabled"]:
                if graph.top_10_holding_pct > self._rules["max_top10_holding_pct"]["value"]:
                    reasons.append(f"Top 10 holding {graph.top_10_holding_pct:.1f}% exceeds max {self._rules['max_top10_holding_pct']['value']}%")
        
        should_reject = len(reasons) > 0
        
        if should_reject:
            self._rejected.add(token_address)
        
        return should_reject, reasons


class MemecoinSnipingEngine:
    """
    Main memecoin sniping engine.
    
    Coordinates all detection and analysis components.
    ALERT-ONLY by default.
    """
    
    def __init__(self):
        self.launch_detector = TokenLaunchDetector()
        self.lock_verifier = LiquidityLockVerifier()
        self.honeypot_detector = HoneypotDetector()
        self.wallet_analyzer = WalletGraphAnalyzer()
        self.mev_router = MEVRouter()
        self.auto_reject = AutoRejectEngine()
        
        self._alerts: List[SnipeAlert] = []
        self._execution_enabled = False  # DISABLED by default
        self._requires_consensus = True
        self._requires_manual_approval = True
        
        logger.info("MemecoinSnipingEngine initialized (ALERT-ONLY mode)")
    
    def enable_execution(self, consensus_approval: str, manual_approval: str) -> bool:
        """
        Enable execution mode.
        
        Requires BOTH consensus and manual approval.
        """
        if not consensus_approval or not manual_approval:
            logger.warning("Execution enable rejected: missing approvals")
            return False
        
        logger.warning(
            "EXECUTION ENABLED - consensus: %s, manual: %s",
            consensus_approval[:20],
            manual_approval[:20],
        )
        self._execution_enabled = True
        return True
    
    def disable_execution(self) -> None:
        """Disable execution mode."""
        self._execution_enabled = False
        logger.info("Execution disabled")
    
    def add_alert(self, alert: SnipeAlert) -> None:
        """Add alert to queue."""
        self._alerts.append(alert)
        
        # Keep last 500 alerts
        if len(self._alerts) > 500:
            self._alerts = self._alerts[-500:]
        
        logger.info(
            "Snipe alert: %s [%s] %s - Score: %.0f",
            alert.alert_type.value,
            alert.risk_level.value,
            alert.token_symbol,
            alert.opportunity_score,
        )
    
    def get_alerts(
        self,
        risk_level: Optional[TokenRisk] = None,
        limit: int = 100,
    ) -> List[SnipeAlert]:
        """Get alerts, optionally filtered by risk level."""
        alerts = self._alerts
        
        if risk_level:
            alerts = [a for a in alerts if a.risk_level == risk_level]
        
        # Filter expired
        now = time.time()
        alerts = [a for a in alerts if not a.expires_at or a.expires_at > now]
        
        return alerts[-limit:]
    
    def analyze_token(
        self,
        token_address: str,
        token_symbol: str,
        chain: str,
        liquidity_usd: float = 0.0,
        buy_tax: float = 0.0,
        sell_tax: float = 0.0,
        deployer_address: Optional[str] = None,
        holder_data: Optional[List[Dict[str, Any]]] = None,
        lock_info: Optional[Dict[str, Any]] = None,
    ) -> Tuple[TokenRisk, SnipeAlert]:
        """
        Analyze a token and generate alert.
        
        Returns risk level and alert.
        """
        # Honeypot analysis
        honeypot = self.honeypot_detector.analyze(
            token_address=token_address,
            buy_tax_pct=buy_tax,
            sell_tax_pct=sell_tax,
        )
        
        # Lock verification
        lock = None
        if lock_info:
            lock = self.lock_verifier.verify_lock(
                token_address=token_address,
                lock_platform=lock_info.get("platform"),
                lock_duration_days=lock_info.get("duration_days", 0),
                lock_percentage=lock_info.get("percentage", 0),
            )
        
        # Wallet graph analysis
        graph = None
        if deployer_address and holder_data:
            graph = self.wallet_analyzer.analyze(
                token_address=token_address,
                deployer_address=deployer_address,
                holder_data=holder_data,
            )
        
        # Auto-reject evaluation
        should_reject, reject_reasons = self.auto_reject.evaluate(
            token_address=token_address,
            honeypot=honeypot,
            lock=lock,
            graph=graph,
            liquidity_usd=liquidity_usd,
        )
        
        # Determine risk level
        if honeypot.is_honeypot:
            risk_level = TokenRisk.HONEYPOT
        elif should_reject:
            risk_level = TokenRisk.EXTREME
        elif len(honeypot.warnings) > 5:
            risk_level = TokenRisk.HIGH
        elif len(honeypot.warnings) > 2:
            risk_level = TokenRisk.MEDIUM
        elif len(honeypot.warnings) > 0:
            risk_level = TokenRisk.LOW
        else:
            risk_level = TokenRisk.SAFE
        
        # Calculate opportunity score
        opportunity_score = 50.0
        if liquidity_usd > 10000:
            opportunity_score += 20
        if lock and lock.is_locked and lock.lock_duration_days > 90:
            opportunity_score += 15
        if honeypot.sell_tax_pct < 5:
            opportunity_score += 10
        if graph and graph.dev_holding_pct < 5:
            opportunity_score += 5
        
        # Reduce score for risks
        opportunity_score -= len(honeypot.warnings) * 5
        opportunity_score -= len(reject_reasons) * 10
        opportunity_score = max(0, min(100, opportunity_score))
        
        # Determine alert type
        if honeypot.is_honeypot:
            alert_type = AlertType.HONEYPOT_WARNING
            description = f"HONEYPOT DETECTED: {', '.join(honeypot.warnings[:3])}"
            action = "DO NOT BUY"
        elif should_reject:
            alert_type = AlertType.RUGPULL_WARNING
            description = f"AUTO-REJECTED: {', '.join(reject_reasons[:3])}"
            action = "AVOID"
        else:
            alert_type = AlertType.NEW_TOKEN
            description = f"New token detected with {len(honeypot.warnings)} warnings"
            action = "REVIEW" if risk_level in [TokenRisk.MEDIUM, TokenRisk.HIGH] else "CONSIDER"
        
        # Create alert
        alert = SnipeAlert(
            alert_id=f"snipe_{token_address[:10]}_{int(time.time())}",
            alert_type=alert_type,
            token_address=token_address,
            token_symbol=token_symbol,
            chain=chain,
            risk_level=risk_level,
            description=description,
            opportunity_score=opportunity_score,
            time_sensitivity_seconds=300,  # 5 minutes
            recommended_action=action,
            requires_approval=True,
            expires_at=time.time() + 3600,  # 1 hour
            metadata={
                "honeypot": honeypot.to_dict(),
                "lock": lock.to_dict() if lock else None,
                "wallet_graph": graph.to_dict() if graph else None,
                "reject_reasons": reject_reasons,
                "liquidity_usd": liquidity_usd,
            },
        )
        
        self.add_alert(alert)
        return risk_level, alert
    
    def get_status(self) -> Dict[str, Any]:
        """Get engine status."""
        return {
            "execution_enabled": self._execution_enabled,
            "requires_consensus": self._requires_consensus,
            "requires_manual_approval": self._requires_manual_approval,
            "mode": "EXECUTION" if self._execution_enabled else "ALERT_ONLY",
            "total_alerts": len(self._alerts),
            "active_alerts": len(self.get_alerts()),
            "detected_tokens": len(self.launch_detector._detected_tokens),
            "rejected_tokens": len(self.auto_reject._rejected),
            "rejection_rules": len(self.auto_reject._rules),
        }


# Singleton instance
_memecoin_engine: Optional[MemecoinSnipingEngine] = None


def get_memecoin_engine() -> MemecoinSnipingEngine:
    """Get the global memecoin sniping engine instance."""
    global _memecoin_engine
    if _memecoin_engine is None:
        _memecoin_engine = MemecoinSnipingEngine()
    return _memecoin_engine
