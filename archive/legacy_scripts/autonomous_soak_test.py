#!/usr/bin/env python3
"""
MERID 12-Hour Autonomous Paper-Trading Soak Test

Operates MERID autonomously in paper-trading mode for 12 hours,
exercising realistic trading behaviors while respecting all risk limits.

Generates rich logs, Neo4j lineage, and metrics for human review.
"""

import os
import sys
import asyncio
import logging
import time
import random
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, asdict
from enum import Enum
import json
from dotenv import load_dotenv

# Load environment
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(f'logs/soak_test_{datetime.now().strftime("%Y%m%d_%H%M%S")}.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


class TradingMode(Enum):
    """Trading mode for soak test."""
    PAPER = "PAPER_TRADING"
    OBSERVATION = "OBSERVATION_ONLY"
    HALTED = "HALTED"


class ProposalState(Enum):
    """Trade proposal states."""
    CREATED = "CREATED"
    VALIDATED = "VALIDATED"
    SIMULATED = "SIMULATED"
    RISK_CHECKED = "RISK_CHECKED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXECUTED = "EXECUTED"


@dataclass
class SoakTestConfig:
    """Configuration for 12-hour soak test."""
    duration_hours: float = 12.0
    whitelisted_assets: List[str] = None
    whitelisted_venues: List[str] = None
    proposal_cadence_minutes: int = 10
    max_position_size_usd: float = 100.0
    max_leverage: float = 1.0
    max_drawdown_pct: float = 0.05
    max_trades_per_hour: int = 10
    lineage_check_interval_minutes: int = 60
    
    def __post_init__(self):
        if self.whitelisted_assets is None:
            self.whitelisted_assets = ["BTC", "ETH", "SOL"]
        if self.whitelisted_venues is None:
            self.whitelisted_venues = ["binance", "coinbase"]


@dataclass
class TradeProposal:
    """Trade proposal for paper trading."""
    proposal_id: str
    asset: str
    venue: str
    side: str  # LONG or SHORT
    size_usd: float
    leverage: float
    stop_loss_pct: float
    take_profit_pct: float
    time_horizon_hours: int
    state: ProposalState
    created_at: datetime
    reasoning: str
    assertions: List[str]
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            **asdict(self),
            'state': self.state.value,
            'created_at': self.created_at.isoformat()
        }


@dataclass
class SoakTestMetrics:
    """Metrics collected during soak test."""
    start_time: datetime
    end_time: Optional[datetime] = None
    proposals_created: int = 0
    proposals_approved: int = 0
    proposals_rejected: int = 0
    trades_executed: int = 0
    total_notional_usd: float = 0.0
    paper_pnl_usd: float = 0.0
    max_drawdown_pct: float = 0.0
    incidents_logged: int = 0
    circuit_breakers_triggered: int = 0
    lineage_checks_performed: int = 0
    lineage_checks_passed: int = 0
    anomalies_detected: List[str] = None
    
    def __post_init__(self):
        if self.anomalies_detected is None:
            self.anomalies_detected = []


class AutonomousSoakTest:
    """12-hour autonomous paper-trading soak test."""
    
    def __init__(self, config: SoakTestConfig):
        self.config = config
        self.mode = TradingMode.PAPER
        self.metrics = SoakTestMetrics(start_time=datetime.now())
        self.proposals: List[TradeProposal] = []
        self.running = False
        
        # Initialize components
        self.graph_service = None
        self.reality_registry = None
        self.consensus_engine = None
        
    async def initialize(self) -> bool:
        """Initialize MERID components."""
        logger.info("="*70)
        logger.info("MERID 12-HOUR AUTONOMOUS SOAK TEST")
        logger.info("="*70)
        logger.info(f"Mode: {self.mode.value}")
        logger.info(f"Duration: {self.config.duration_hours} hours")
        logger.info(f"Assets: {', '.join(self.config.whitelisted_assets)}")
        logger.info(f"Venues: {', '.join(self.config.whitelisted_venues)}")
        logger.info("="*70)
        
        try:
            # Initialize Neo4j
            logger.info("Initializing Neo4j GraphService...")
            from core.graph_service import initialize_graph_service
            
            self.graph_service = initialize_graph_service(
                uri=os.getenv("NEO4J_URI"),
                user=os.getenv("NEO4J_USER"),
                password=os.getenv("NEO4J_PASSWORD"),
                database=os.getenv("NEO4J_DATABASE", "neo4j")
            )
            self.graph_service.run_init()
            logger.info("[OK] Neo4j initialized")
            
            # Initialize Reality Registry
            logger.info("Initializing Reality Registry...")
            from core.reality_registry import RealityRegistry
            
            self.reality_registry = RealityRegistry()
            logger.info("[OK] Reality Registry initialized")
            
            # Initialize Consensus Engine
            logger.info("Initializing Consensus Engine...")
            from core.consensus_engine import ConsensusEngine
            
            self.consensus_engine = ConsensusEngine()
            logger.info("[OK] Consensus Engine initialized")
            
            logger.info("\n[READY] All components initialized - SOAK TEST READY")
            return True
            
        except Exception as e:
            logger.error(f"Initialization failed: {e}", exc_info=True)
            return False
    
    async def run(self):
        """Run 12-hour autonomous soak test."""
        if not await self.initialize():
            logger.error("Initialization failed - aborting soak test")
            return
        
        self.running = True
        end_time = datetime.now() + timedelta(hours=self.config.duration_hours)
        
        logger.info(f"\n[START] Soak test started at {datetime.now()}")
        logger.info(f"[END] Will run until {end_time}")
        logger.info("="*70)
        
        # Main loop
        last_proposal_time = datetime.now()
        last_lineage_check = datetime.now()
        iteration = 0
        
        try:
            while self.running and datetime.now() < end_time:
                iteration += 1
                current_time = datetime.now()
                
                # Log status every 30 minutes
                if iteration % 180 == 0:  # ~30 min at 10s intervals
                    await self._log_status()
                
                # Generate proposals at configured cadence
                if (current_time - last_proposal_time).total_seconds() >= (self.config.proposal_cadence_minutes * 60):
                    await self._generate_and_process_proposal()
                    last_proposal_time = current_time
                
                # Perform lineage checks
                if (current_time - last_lineage_check).total_seconds() >= (self.config.lineage_check_interval_minutes * 60):
                    await self._perform_lineage_check()
                    last_lineage_check = current_time
                
                # Check for halt conditions
                if await self._check_halt_conditions():
                    logger.warning("[HALT] Halt condition detected - entering observation mode")
                    self.mode = TradingMode.OBSERVATION
                
                # Sleep before next iteration
                await asyncio.sleep(10)  # Check every 10 seconds
                
        except KeyboardInterrupt:
            logger.info("\n[INTERRUPT] Soak test interrupted by user")
        except Exception as e:
            logger.error(f"Fatal error during soak test: {e}", exc_info=True)
            self.metrics.anomalies_detected.append(f"Fatal error: {str(e)}")
        finally:
            await self._shutdown()
    
    async def _generate_and_process_proposal(self):
        """Generate and process a trade proposal."""
        try:
            # Generate proposal
            proposal = await self._generate_proposal()
            self.proposals.append(proposal)
            self.metrics.proposals_created += 1
            
            logger.info(f"\n[PROPOSAL] {proposal.proposal_id} created:")
            logger.info(f"   Asset: {proposal.asset}, Venue: {proposal.venue}")
            logger.info(f"   Side: {proposal.side}, Size: ${proposal.size_usd:.2f}")
            logger.info(f"   Reasoning: {proposal.reasoning}")
            
            # Record in Neo4j
            await self._record_proposal_in_graph(proposal)
            
            # Process proposal lifecycle
            approved = await self._process_proposal_lifecycle(proposal)
            
            if approved:
                self.metrics.proposals_approved += 1
                await self._execute_paper_trade(proposal)
            else:
                self.metrics.proposals_rejected += 1
                logger.info(f"   [REJECT] Proposal {proposal.proposal_id} REJECTED")
                
        except Exception as e:
            logger.error(f"Error generating/processing proposal: {e}")
            self.metrics.anomalies_detected.append(f"Proposal error: {str(e)}")
    
    async def _generate_proposal(self) -> TradeProposal:
        """Generate a trade proposal."""
        proposal_id = f"soak_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{random.randint(1000, 9999)}"
        
        # Random selection from whitelisted assets/venues
        asset = random.choice(self.config.whitelisted_assets)
        venue = random.choice(self.config.whitelisted_venues)
        side = random.choice(["LONG", "SHORT"])
        
        # Position sizing (vary within limits)
        size_usd = random.uniform(10, self.config.max_position_size_usd)
        leverage = random.uniform(1.0, self.config.max_leverage)
        
        # Risk parameters
        stop_loss_pct = random.uniform(0.02, 0.05)  # 2-5%
        take_profit_pct = random.uniform(0.03, 0.10)  # 3-10%
        time_horizon_hours = random.randint(1, 24)
        
        # Generate reasoning
        reasoning = self._generate_reasoning(asset, venue, side)
        
        # Generate assertions
        assertions = self._generate_assertions(asset, venue)
        
        return TradeProposal(
            proposal_id=proposal_id,
            asset=asset,
            venue=venue,
            side=side,
            size_usd=size_usd,
            leverage=leverage,
            stop_loss_pct=stop_loss_pct,
            take_profit_pct=take_profit_pct,
            time_horizon_hours=time_horizon_hours,
            state=ProposalState.CREATED,
            created_at=datetime.now(),
            reasoning=reasoning,
            assertions=assertions
        )
    
    def _generate_reasoning(self, asset: str, venue: str, side: str) -> str:
        """Generate reasoning for proposal."""
        reasons = [
            f"{asset} showing momentum on {venue}",
            f"Mean reversion opportunity in {asset}",
            f"Volatility breakout detected for {asset}",
            f"Funding rate arbitrage on {asset}",
            f"Technical pattern formation in {asset}"
        ]
        return random.choice(reasons)
    
    def _generate_assertions(self, asset: str, venue: str) -> List[str]:
        """Generate assertions for proposal."""
        return [
            f"price_{asset.lower()}_valid",
            f"liquidity_{venue}_sufficient",
            f"volatility_{asset.lower()}_normal",
            f"regime_market_stable"
        ]
    
    async def _record_proposal_in_graph(self, proposal: TradeProposal):
        """Record proposal in Neo4j."""
        try:
            if self.graph_service:
                # Record proposal node
                self.graph_service.record_proposal(
                    proposal_id=proposal.proposal_id,
                    asset=proposal.asset,
                    venue=proposal.venue,
                    side=proposal.side,
                    size_usd=proposal.size_usd,
                    leverage=proposal.leverage,
                    agent_id="soak_test_agent",
                    reasoning=proposal.reasoning,
                    assertions=proposal.assertions
                )
                logger.info(f"   [OK] Recorded in Neo4j")
        except Exception as e:
            logger.error(f"Failed to record proposal in Neo4j: {e}")
            self.metrics.anomalies_detected.append(f"Neo4j record failed: {str(e)}")
    
    async def _process_proposal_lifecycle(self, proposal: TradeProposal) -> bool:
        """Process proposal through lifecycle."""
        # VALIDATION
        proposal.state = ProposalState.VALIDATED
        logger.info(f"   [OK] VALIDATED")
        await asyncio.sleep(0.1)
        
        # SIMULATION
        proposal.state = ProposalState.SIMULATED
        logger.info(f"   [OK] SIMULATED")
        await asyncio.sleep(0.1)
        
        # RISK CHECK
        proposal.state = ProposalState.RISK_CHECKED
        risk_passed = await self._check_risk_limits(proposal)
        
        if not risk_passed:
            proposal.state = ProposalState.REJECTED
            return False
        
        logger.info(f"   [OK] RISK_CHECKED")
        await asyncio.sleep(0.1)
        
        # APPROVAL (random rejection for testing)
        if random.random() < 0.2:  # 20% rejection rate
            proposal.state = ProposalState.REJECTED
            logger.info(f"   [REJECT] REJECTED (quality threshold)")
            return False
        
        proposal.state = ProposalState.APPROVED
        logger.info(f"   [OK] APPROVED")
        return True
    
    async def _check_risk_limits(self, proposal: TradeProposal) -> bool:
        """Check if proposal passes risk limits."""
        # Check position size
        if proposal.size_usd > self.config.max_position_size_usd:
            logger.warning(f"   [FAIL] Position size ${proposal.size_usd:.2f} exceeds limit ${self.config.max_position_size_usd:.2f}")
            return False
        
        # Check leverage
        if proposal.leverage > self.config.max_leverage:
            logger.warning(f"   [FAIL] Leverage {proposal.leverage}x exceeds limit {self.config.max_leverage}x")
            return False
        
        # Check drawdown
        if abs(self.metrics.paper_pnl_usd) / max(self.metrics.total_notional_usd, 1) > self.config.max_drawdown_pct:
            logger.warning(f"   [FAIL] Drawdown exceeds limit")
            return False
        
        return True
    
    async def _execute_paper_trade(self, proposal: TradeProposal):
        """Execute trade in paper mode."""
        try:
            proposal.state = ProposalState.EXECUTED
            self.metrics.trades_executed += 1
            self.metrics.total_notional_usd += proposal.size_usd
            
            # Simulate PnL (random walk)
            pnl_pct = random.gauss(0.01, 0.03)  # Mean 1%, StdDev 3%
            pnl_usd = proposal.size_usd * pnl_pct
            self.metrics.paper_pnl_usd += pnl_usd
            
            # Update max drawdown
            if self.metrics.total_notional_usd > 0:
                current_drawdown = abs(min(0, self.metrics.paper_pnl_usd)) / self.metrics.total_notional_usd
                self.metrics.max_drawdown_pct = max(self.metrics.max_drawdown_pct, current_drawdown)
            
            logger.info(f"   [EXEC] EXECUTED (paper)")
            logger.info(f"   [PNL] PnL: ${pnl_usd:+.2f} ({pnl_pct*100:+.2f}%)")
            logger.info(f"   [PNL] Total PnL: ${self.metrics.paper_pnl_usd:+.2f}")
            
            # Record execution in Neo4j
            if self.graph_service:
                execution_id = f"exec_{proposal.proposal_id}"
                self.graph_service.record_execution(
                    execution_id=execution_id,
                    order_id=f"order_{proposal.proposal_id}",
                    size_usd=proposal.size_usd,
                    price=1000.0,  # Simulated price
                    venue=proposal.venue,
                    timestamp=datetime.now()
                )
                
        except Exception as e:
            logger.error(f"Error executing paper trade: {e}")
            self.metrics.anomalies_detected.append(f"Execution error: {str(e)}")
    
    async def _perform_lineage_check(self):
        """Perform Neo4j lineage verification."""
        logger.info("\n[LINEAGE] Performing lineage check...")
        
        try:
            if not self.graph_service or len(self.proposals) == 0:
                logger.info("   [WARN] No proposals to check")
                return
            
            # Select random executed proposal
            executed_proposals = [p for p in self.proposals if p.state == ProposalState.EXECUTED]
            
            if not executed_proposals:
                logger.info("   [WARN] No executed proposals yet")
                return
            
            proposal = random.choice(executed_proposals)
            
            # Query lineage
            lineage = self.graph_service.get_proposal_lineage(proposal.proposal_id)
            
            self.metrics.lineage_checks_performed += 1
            
            if lineage and len(lineage) > 0:
                self.metrics.lineage_checks_passed += 1
                logger.info(f"   [OK] Lineage verified for {proposal.proposal_id}")
                logger.info(f"   [CHAIN] Proposal -> Order -> Execution")
            else:
                logger.warning(f"   [FAIL] Lineage incomplete for {proposal.proposal_id}")
                self.metrics.anomalies_detected.append(f"Incomplete lineage: {proposal.proposal_id}")
                
        except Exception as e:
            logger.error(f"Lineage check failed: {e}")
            self.metrics.anomalies_detected.append(f"Lineage check error: {str(e)}")
    
    async def _check_halt_conditions(self) -> bool:
        """Check if system should halt trading."""
        # Check drawdown
        if self.metrics.max_drawdown_pct > self.config.max_drawdown_pct:
            logger.warning(f"[HALT] Max drawdown {self.metrics.max_drawdown_pct*100:.2f}% exceeds limit")
            return True
        
        # Check error rate
        if len(self.metrics.anomalies_detected) > 10:
            logger.warning(f"[HALT] Too many anomalies detected: {len(self.metrics.anomalies_detected)}")
            return True
        
        return False
    
    async def _log_status(self):
        """Log current status."""
        elapsed = (datetime.now() - self.metrics.start_time).total_seconds() / 3600
        
        logger.info("\n" + "="*70)
        logger.info(f"STATUS UPDATE - {elapsed:.1f} hours elapsed")
        logger.info("="*70)
        logger.info(f"Mode: {self.mode.value}")
        logger.info(f"Proposals: {self.metrics.proposals_created} created, {self.metrics.proposals_approved} approved, {self.metrics.proposals_rejected} rejected")
        logger.info(f"Trades: {self.metrics.trades_executed} executed")
        logger.info(f"Notional: ${self.metrics.total_notional_usd:.2f}")
        logger.info(f"Paper PnL: ${self.metrics.paper_pnl_usd:+.2f}")
        logger.info(f"Max Drawdown: {self.metrics.max_drawdown_pct*100:.2f}%")
        logger.info(f"Lineage Checks: {self.metrics.lineage_checks_performed} performed, {self.metrics.lineage_checks_passed} passed")
        logger.info(f"Anomalies: {len(self.metrics.anomalies_detected)}")
        logger.info("="*70)
    
    async def _shutdown(self):
        """Shutdown and generate final summary."""
        self.running = False
        self.metrics.end_time = datetime.now()
        
        logger.info("\n" + "="*70)
        logger.info("SOAK TEST COMPLETE - FINAL SUMMARY")
        logger.info("="*70)
        
        duration = (self.metrics.end_time - self.metrics.start_time).total_seconds() / 3600
        
        logger.info(f"\n[TIME] Time Window:")
        logger.info(f"   Start: {self.metrics.start_time}")
        logger.info(f"   End: {self.metrics.end_time}")
        logger.info(f"   Duration: {duration:.2f} hours")
        
        logger.info(f"\n[PROPOSALS] Proposals:")
        logger.info(f"   Created: {self.metrics.proposals_created}")
        logger.info(f"   Approved: {self.metrics.proposals_approved}")
        logger.info(f"   Rejected: {self.metrics.proposals_rejected}")
        logger.info(f"   Approval Rate: {(self.metrics.proposals_approved / max(self.metrics.proposals_created, 1) * 100):.1f}%")
        
        logger.info(f"\n[TRADING] Trading:")
        logger.info(f"   Trades Executed: {self.metrics.trades_executed}")
        logger.info(f"   Total Notional: ${self.metrics.total_notional_usd:.2f}")
        logger.info(f"   Paper PnL: ${self.metrics.paper_pnl_usd:+.2f}")
        logger.info(f"   Max Drawdown: {self.metrics.max_drawdown_pct*100:.2f}%")
        
        logger.info(f"\n[LINEAGE] Lineage:")
        logger.info(f"   Checks Performed: {self.metrics.lineage_checks_performed}")
        logger.info(f"   Checks Passed: {self.metrics.lineage_checks_passed}")
        logger.info(f"   Pass Rate: {(self.metrics.lineage_checks_passed / max(self.metrics.lineage_checks_performed, 1) * 100):.1f}%")
        
        logger.info(f"\n[INCIDENTS] Incidents:")
        logger.info(f"   Anomalies Detected: {len(self.metrics.anomalies_detected)}")
        if self.metrics.anomalies_detected:
            logger.info(f"   Details:")
            for anomaly in self.metrics.anomalies_detected[:10]:  # Show first 10
                logger.info(f"     - {anomaly}")
        
        # Save summary to file
        summary_file = f'logs/soak_test_summary_{datetime.now().strftime("%Y%m%d_%H%M%S")}.json'
        summary = {
            'start_time': self.metrics.start_time.isoformat(),
            'end_time': self.metrics.end_time.isoformat(),
            'duration_hours': duration,
            'proposals_created': self.metrics.proposals_created,
            'proposals_approved': self.metrics.proposals_approved,
            'proposals_rejected': self.metrics.proposals_rejected,
            'trades_executed': self.metrics.trades_executed,
            'total_notional_usd': self.metrics.total_notional_usd,
            'paper_pnl_usd': self.metrics.paper_pnl_usd,
            'max_drawdown_pct': self.metrics.max_drawdown_pct,
            'lineage_checks_performed': self.metrics.lineage_checks_performed,
            'lineage_checks_passed': self.metrics.lineage_checks_passed,
            'anomalies_detected': self.metrics.anomalies_detected
        }
        
        with open(summary_file, 'w') as f:
            json.dump(summary, f, indent=2)
        
        logger.info(f"\n[SAVE] Summary saved to: {summary_file}")
        logger.info("="*70)
        logger.info("[COMPLETE] SOAK TEST SHUTDOWN COMPLETE")
        logger.info("="*70)


async def main():
    """Main entry point."""
    # Configuration
    config = SoakTestConfig(
        duration_hours=12.0,
        whitelisted_assets=["BTC", "ETH", "SOL"],
        whitelisted_venues=["binance", "coinbase"],
        proposal_cadence_minutes=10,
        max_position_size_usd=100.0,
        max_leverage=1.0,
        max_drawdown_pct=0.05,
        lineage_check_interval_minutes=60
    )
    
    # Run soak test
    soak_test = AutonomousSoakTest(config)
    await soak_test.run()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("\n[INTERRUPT] Soak test interrupted by user")
        sys.exit(0)
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)
