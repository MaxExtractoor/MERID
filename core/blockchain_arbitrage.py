"""MERID Blockchain Arbitrage Agent for Swarm.

Cross-chain arbitrage detection and execution across DEXs.
Integrates with swarm intelligence for coordinated opportunities.
"""

from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass
from decimal import Decimal
import asyncio
import structlog
from datetime import datetime

from core.blockchain_dex import DEXManager, MultiChainDEXManager, TokenPair
from core.blockchain_solana import SolanaManager, JupiterQuote
from core.blockchain_wallet import MultiChainWalletManager

logger = structlog.get_logger(__name__)


@dataclass
class ArbitrageOpportunity:
    """Detected arbitrage opportunity."""
    opportunity_id: str
    token_symbol: str
    buy_chain: str
    sell_chain: str
    buy_price: Decimal
    sell_price: Decimal
    profit_percent: Decimal
    max_trade_size: Decimal
    estimated_gas_cost: Decimal
    net_profit: Decimal
    confidence: float
    ttl_seconds: int
    timestamp: datetime
    
    def is_profitable(self, min_profit: Decimal = Decimal("0.001")) -> bool:
        """Check if opportunity meets profit threshold."""
        return self.net_profit > min_profit and self.confidence > 0.7


@dataclass
class ArbitrageExecution:
    """Arbitrage trade execution result."""
    execution_id: str
    opportunity_id: str
    status: str  # pending, executing, completed, failed
    buy_tx_hash: Optional[str]
    sell_tx_hash: Optional[str]
    actual_profit: Optional[Decimal]
    gas_spent: Decimal
    execution_time_ms: int
    error: Optional[str]


class ArbitrageDetector:
    """Detects arbitrage opportunities across chains and DEXs."""
    
    def __init__(
        self,
        dex_manager: MultiChainDEXManager,
        solana_manager: Optional[SolanaManager] = None
    ):
        self.dex = dex_manager
        self.solana = solana_manager
        self.logger = logger.bind(component="ArbitrageDetector")
        
        # Minimum profit thresholds (after gas costs)
        self.min_profit_percent = Decimal("0.005")  # 0.5%
        self.min_net_profit_usd = Decimal("10.00")
    
    async def scan_evm_arbitrage(
        self,
        token_address: str,
        base_token: str = "USDC",
        chains: List[str] = None
    ) -> List[ArbitrageOpportunity]:
        """Scan for EVM chain arbitrage opportunities."""
        chains = chains or ["ethereum", "cronos", "polygon"]
        opportunities = []
        
        # Get prices across chains
        prices: Dict[str, Decimal] = {}
        for chain in chains:
            try:
                manager = self.dex.get_manager(chain)
                # Simplified - would need proper token addresses per chain
                price = await manager.get_token_price_usd(token_address)
                if price:
                    prices[chain] = price
            except Exception as e:
                self.logger.error("price_fetch_error", chain=chain, error=str(e))
        
        if len(prices) < 2:
            return opportunities
        
        # Find arbitrage opportunities
        for buy_chain, buy_price in prices.items():
            for sell_chain, sell_price in prices.items():
                if buy_chain == sell_chain:
                    continue
                
                # Calculate profit
                if sell_price > buy_price:
                    profit_pct = (sell_price - buy_price) / buy_price
                    
                    # Estimate gas costs
                    gas_cost = self._estimate_cross_chain_gas(buy_chain, sell_chain)
                    
                    # Calculate net profit
                    # Assume $1000 trade size for estimation
                    trade_size = Decimal("1000")
                    gross_profit = trade_size * profit_pct
                    net_profit = gross_profit - gas_cost
                    
                    if net_profit > self.min_net_profit_usd:
                        opp = ArbitrageOpportunity(
                            opportunity_id=f"evm_{token_address[:8]}_{buy_chain}_{sell_chain}_{int(datetime.now().timestamp())}",
                            token_symbol=token_address[:8],
                            buy_chain=buy_chain,
                            sell_chain=sell_chain,
                            buy_price=buy_price,
                            sell_price=sell_price,
                            profit_percent=profit_pct,
                            max_trade_size=trade_size,
                            estimated_gas_cost=gas_cost,
                            net_profit=net_profit,
                            confidence=0.8,  # Based on data quality
                            ttl_seconds=60,  # Opportunities expire quickly
                            timestamp=datetime.now()
                        )
                        opportunities.append(opp)
                        
                        self.logger.info(
                            "arbitrage_opportunity_detected",
                            token=token_address[:8],
                            buy=buy_chain,
                            sell=sell_chain,
                            profit=str(profit_pct)
                        )
        
        return opportunities
    
    async def scan_cross_chain_arbitrage(
        self,
        token_symbol: str,
        evm_token: str,
        solana_mint: str
    ) -> List[ArbitrageOpportunity]:
        """Scan for EVM <-> Solana arbitrage."""
        opportunities = []
        
        if not self.solana:
            return opportunities
        
        try:
            # Get EVM price
            evm_manager = self.dex.get_manager("ethereum")
            evm_price = await evm_manager.get_token_price_usd(evm_token)
            
            # Get Solana price via Jupiter
            sol_quote = await self.solana.get_jupiter_quote(
                input_mint=solana_mint,
                output_mint=self.solana.KNOWN_TOKENS["USDC"].mint,
                amount=Decimal("1.0")
            )
            sol_price = sol_quote.out_amount
            
            # Check for arbitrage
            price_diff = abs(evm_price - sol_price) / min(evm_price, sol_price)
            
            if price_diff > self.min_profit_percent:
                # Determine direction
                if evm_price < sol_price:
                    buy_chain, sell_chain = "ethereum", "solana"
                    buy_price, sell_price = evm_price, sol_price
                else:
                    buy_chain, sell_chain = "solana", "ethereum"
                    buy_price, sell_price = sol_price, evm_price
                
                gas_cost = self._estimate_cross_chain_gas(buy_chain, sell_chain)
                
                opp = ArbitrageOpportunity(
                    opportunity_id=f"cross_{token_symbol}_{int(datetime.now().timestamp())}",
                    token_symbol=token_symbol,
                    buy_chain=buy_chain,
                    sell_chain=sell_chain,
                    buy_price=buy_price,
                    sell_price=sell_price,
                    profit_percent=price_diff,
                    max_trade_size=Decimal("1000"),
                    estimated_gas_cost=gas_cost,
                    net_profit=Decimal("1000") * price_diff - gas_cost,
                    confidence=0.7,
                    ttl_seconds=45,
                    timestamp=datetime.now()
                )
                
                if opp.is_profitable():
                    opportunities.append(opp)
                    self.logger.info(
                        "cross_chain_opportunity",
                        token=token_symbol,
                        diff=str(price_diff)
                    )
        
        except Exception as e:
            self.logger.error("cross_chain_scan_error", error=str(e))
        
        return opportunities
    
    def _estimate_cross_chain_gas(
        self,
        buy_chain: str,
        sell_chain: str
    ) -> Decimal:
        """Estimate gas costs for cross-chain arbitrage."""
        # Simplified gas estimates in USD
        chain_costs = {
            "ethereum": Decimal("25.00"),
            "cronos": Decimal("1.00"),
            "polygon": Decimal("0.50"),
            "solana": Decimal("0.10")
        }
        
        buy_cost = chain_costs.get(buy_chain, Decimal("10.00"))
        sell_cost = chain_costs.get(sell_chain, Decimal("10.00"))
        
        return buy_cost + sell_cost


class ArbitrageExecutor:
    """Executes arbitrage trades across chains."""
    
    def __init__(
        self,
        dex_manager: MultiChainDEXManager,
        wallet_manager: MultiChainWalletManager,
        solana_manager: Optional[SolanaManager] = None
    ):
        self.dex = dex_manager
        self.wallets = wallet_manager
        self.solana = solana_manager
        self.logger = logger.bind(component="ArbitrageExecutor")
        
        self.active_executions: Dict[str, ArbitrageExecution] = {}
    
    async def execute_arbitrage(
        self,
        opportunity: ArbitrageOpportunity,
        wallet_id: str,
        trade_size: Optional[Decimal] = None
    ) -> ArbitrageExecution:
        """Execute arbitrage opportunity."""
        
        execution_id = f"exec_{opportunity.opportunity_id}_{int(datetime.now().timestamp())}"
        
        self.logger.info(
            "starting_arbitrage_execution",
            execution_id=execution_id[:20],
            opp=opportunity.opportunity_id[:20]
        )
        
        execution = ArbitrageExecution(
            execution_id=execution_id,
            opportunity_id=opportunity.opportunity_id,
            status="executing",
            buy_tx_hash=None,
            sell_tx_hash=None,
            actual_profit=None,
            gas_spent=Decimal("0"),
            execution_time_ms=0,
            error=None
        )
        
        self.active_executions[execution_id] = execution
        start_time = asyncio.get_event_loop().time()
        
        try:
            # Phase 1: Buy on source chain
            buy_result = await self._execute_buy(
                opportunity,
                wallet_id,
                trade_size or opportunity.max_trade_size
            )
            
            if buy_result.get("error"):
                execution.status = "failed"
                execution.error = f"Buy failed: {buy_result['error']}"
                return execution
            
            execution.buy_tx_hash = buy_result.get("tx_hash")
            execution.gas_spent += buy_result.get("gas_cost", Decimal("0"))
            
            # Phase 2: Bridge assets (if cross-chain)
            if opportunity.buy_chain != opportunity.sell_chain:
                bridge_result = await self._bridge_assets(
                    opportunity,
                    wallet_id,
                    trade_size or opportunity.max_trade_size
                )
                
                if bridge_result.get("error"):
                    execution.status = "failed"
                    execution.error = f"Bridge failed: {bridge_result['error']}"
                    return execution
            
            # Phase 3: Sell on destination chain
            sell_result = await self._execute_sell(
                opportunity,
                wallet_id,
                trade_size or opportunity.max_trade_size
            )
            
            if sell_result.get("error"):
                execution.status = "failed"
                execution.error = f"Sell failed: {sell_result['error']}"
                return execution
            
            execution.sell_tx_hash = sell_result.get("tx_hash")
            execution.gas_spent += sell_result.get("gas_cost", Decimal("0"))
            
            # Calculate actual profit
            execution.actual_profit = (
                (trade_size or opportunity.max_trade_size) * opportunity.profit_percent
            ) - execution.gas_spent
            
            execution.status = "completed"
            
            self.logger.info(
                "arbitrage_completed",
                execution_id=execution_id[:20],
                profit=str(execution.actual_profit),
                gas=str(execution.gas_spent)
            )
            
        except Exception as e:
            execution.status = "failed"
            execution.error = str(e)
            self.logger.error("arbitrage_execution_error", error=str(e))
        
        finally:
            execution.execution_time_ms = int(
                (asyncio.get_event_loop().time() - start_time) * 1000
            )
        
        return execution
    
    async def _execute_buy(
        self,
        opp: ArbitrageOpportunity,
        wallet_id: str,
        amount: Decimal
    ) -> Dict[str, Any]:
        """Execute buy leg of arbitrage."""
        # Implementation depends on chain
        if opp.buy_chain in ["ethereum", "cronos", "polygon"]:
            # EVM swap via DEX
            manager = self.dex.get_manager(opp.buy_chain)
            # Simplified - would construct actual swap
            return {"tx_hash": "0x...", "gas_cost": Decimal("0.01")}
        
        elif opp.buy_chain == "solana" and self.solana:
            # Solana swap via Jupiter
            return {"tx_hash": "...", "gas_cost": Decimal("0.0001")}
        
        return {"error": "Unsupported chain"}
    
    async def _execute_sell(
        self,
        opp: ArbitrageOpportunity,
        wallet_id: str,
        amount: Decimal
    ) -> Dict[str, Any]:
        """Execute sell leg of arbitrage."""
        # Similar to _execute_buy
        if opp.sell_chain in ["ethereum", "cronos", "polygon"]:
            return {"tx_hash": "0x...", "gas_cost": Decimal("0.01")}
        
        elif opp.sell_chain == "solana" and self.solana:
            return {"tx_hash": "...", "gas_cost": Decimal("0.0001")}
        
        return {"error": "Unsupported chain"}
    
    async def _bridge_assets(
        self,
        opp: ArbitrageOpportunity,
        wallet_id: str,
        amount: Decimal
    ) -> Dict[str, Any]:
        """Bridge assets between chains."""
        # Placeholder for bridge integration (LayerZero, Wormhole, etc.)
        self.logger.info(
            "bridging_assets",
            from_chain=opp.buy_chain,
            to_chain=opp.sell_chain,
            amount=str(amount)
        )
        
        # Simulate bridge delay
        await asyncio.sleep(2)
        
        return {"success": True, "bridge_fee": Decimal("5.00")}
    
    async def get_execution_status(self, execution_id: str) -> Optional[ArbitrageExecution]:
        """Get status of arbitrage execution."""
        return self.active_executions.get(execution_id)


class BlockchainArbitrageAgent:
    """Swarm agent for blockchain arbitrage operations."""
    
    def __init__(
        self,
        dex_manager: MultiChainDEXManager,
        wallet_manager: MultiChainWalletManager,
        solana_manager: Optional[SolanaManager] = None
    ):
        self.detector = ArbitrageDetector(dex_manager, solana_manager)
        self.executor = ArbitrageExecutor(
            dex_manager, wallet_manager, solana_manager
        )
        self.logger = logger.bind(component="BlockchainArbitrageAgent")
        
        self.is_scanning = False
        self.opportunities: List[ArbitrageOpportunity] = []
    
    async def start_scanning(
        self,
        tokens: List[Tuple[str, str, str]],  # (symbol, evm_addr, sol_mint)
        scan_interval: float = 5.0
    ):
        """Start continuous arbitrage scanning."""
        self.is_scanning = True
        self.logger.info("arbitrage_scanning_started")
        
        while self.is_scanning:
            try:
                for symbol, evm_addr, sol_mint in tokens:
                    # Scan EVM opportunities
                    evm_opps = await self.detector.scan_evm_arbitrage(evm_addr)
                    self.opportunities.extend(evm_opps)
                    
                    # Scan cross-chain opportunities
                    if sol_mint:
                        cross_opps = await self.detector.scan_cross_chain_arbitrage(
                            symbol, evm_addr, sol_mint
                        )
                        self.opportunities.extend(cross_opps)
                
                # Sort by profit
                self.opportunities.sort(
                    key=lambda x: x.net_profit,
                    reverse=True
                )
                
                # Log top opportunities
                if self.opportunities:
                    top = self.opportunities[0]
                    self.logger.info(
                        "top_opportunity",
                        token=top.token_symbol,
                        profit=str(top.net_profit),
                        confidence=top.confidence
                    )
                
                await asyncio.sleep(scan_interval)
                
            except Exception as e:
                self.logger.error("scanning_error", error=str(e))
                await asyncio.sleep(scan_interval)
    
    def stop_scanning(self):
        """Stop arbitrage scanning."""
        self.is_scanning = False
        self.logger.info("arbitrage_scanning_stopped")
    
    def get_opportunities(
        self,
        min_profit: Decimal = Decimal("0")
    ) -> List[ArbitrageOpportunity]:
        """Get current arbitrage opportunities."""
        return [
            opp for opp in self.opportunities
            if opp.net_profit >= min_profit and opp.is_profitable()
        ]
    
    async def execute_best_opportunity(
        self,
        wallet_id: str,
        max_slippage: Decimal = Decimal("0.01")
    ) -> Optional[ArbitrageExecution]:
        """Execute the best available opportunity."""
        opportunities = self.get_opportunities()
        
        if not opportunities:
            self.logger.info("no_opportunities_available")
            return None
        
        best = opportunities[0]
        
        if best.profit_percent < max_slippage:
            self.logger.info("insufficient_profit_margin")
            return None
        
        return await self.executor.execute_arbitrage(best, wallet_id)
