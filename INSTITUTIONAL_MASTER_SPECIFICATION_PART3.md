# MERID INSTITUTIONAL MASTER SPECIFICATION - PART 3
## Sections 11-15: AI Swarm, DeFi Trading, and Integration Systems

---

# SECTION 11: AI TRADING SWARM ARCHITECTURE

## 11.1 Agent Charter System

```python
@dataclass
class AgentCharter:
    """
    Constitutional charter defining agent behavior and constraints.
    
    IMMUTABLE: Cannot be modified by agent
    ENFORCED: Violations trigger immediate suspension
    AUDITED: All charter compliance logged
    """
    charter_id: str
    agent_role: str  # analyst, risk, skeptic, synthesizer
    
    # Behavioral constraints
    max_confidence: float  # Never exceed this confidence
    required_evidence_count: int  # Minimum evidence sources
    forbidden_actions: List[str]  # Actions agent cannot take
    required_checks: List[str]  # Checks agent must perform
    
    # Operational limits
    max_assertions_per_minute: int
    max_vote_weight: float
    cooldown_after_error: float  # Seconds
    
    # Explainability requirements
    must_provide_reasoning: bool = True
    must_cite_sources: bool = True
    must_show_contrary_evidence: bool = True
    
    # Safety constraints
    requires_human_approval: List[str]  # Action types requiring approval
    cannot_execute_alone: bool = False
    must_achieve_consensus: bool = False


# Agent role charters
AGENT_CHARTERS = {
    "analyst": AgentCharter(
        charter_id="analyst-v1",
        agent_role="analyst",
        max_confidence=0.85,
        required_evidence_count=3,
        forbidden_actions=["execute_trade", "modify_positions"],
        required_checks=["verify_data_freshness", "check_market_conditions"],
        max_assertions_per_minute=10,
        max_vote_weight=1.0,
        cooldown_after_error=60.0,
        requires_human_approval=[]
    ),
    
    "risk": AgentCharter(
        charter_id="risk-v1",
        agent_role="risk",
        max_confidence=0.95,  # Risk must be highly confident
        required_evidence_count=5,
        forbidden_actions=["execute_trade"],
        required_checks=[
            "verify_position_limits",
            "check_leverage",
            "validate_stop_losses",
            "assess_correlation"
        ],
        max_assertions_per_minute=20,
        max_vote_weight=1.5,  # Risk has higher weight
        cooldown_after_error=30.0,
        requires_human_approval=["override_risk_limit"]
    ),
    
    "skeptic": AgentCharter(
        charter_id="skeptic-v1",
        agent_role="skeptic",
        max_confidence=0.90,
        required_evidence_count=4,
        forbidden_actions=["execute_trade", "approve_consensus"],
        required_checks=[
            "find_contrary_evidence",
            "challenge_assumptions",
            "verify_data_quality",
            "check_for_bias"
        ],
        max_assertions_per_minute=15,
        max_vote_weight=1.2,  # Skeptic has elevated weight
        cooldown_after_error=45.0,
        requires_human_approval=[],
        must_show_contrary_evidence=True
    ),
    
    "execution": AgentCharter(
        charter_id="execution-v1",
        agent_role="execution",
        max_confidence=0.99,  # Execution must be near-certain
        required_evidence_count=10,
        forbidden_actions=[],  # Can execute but heavily constrained
        required_checks=[
            "verify_consensus",
            "check_risk_limits",
            "validate_market_conditions",
            "confirm_slippage_acceptable",
            "verify_mev_protection"
        ],
        max_assertions_per_minute=5,
        max_vote_weight=0.5,  # Execution has lower vote weight
        cooldown_after_error=300.0,  # 5 minute cooldown
        requires_human_approval=["large_order", "high_risk_trade"],
        cannot_execute_alone=True,
        must_achieve_consensus=True
    )
}
```

## 11.2 Agent Coordination Protocol

```python
class SwarmCoordinator:
    """
    Coordinates multi-agent decision-making with constitutional enforcement.
    
    PROTOCOL:
    1. Proposal broadcast
    2. Agent analysis (parallel)
    3. Vote collection
    4. Consensus calculation
    5. Risk validation
    6. Execution gating
    """
    
    def __init__(self):
        self.agents: Dict[str, BaseAgent] = {}
        self.consensus_engine = ConsensusEngine()
        self.risk_validator = RiskValidator()
        self.execution_gate = ExecutionGate()
        self.audit_logger = AuditLogger()
    
    async def propose_action(
        self,
        action_type: str,
        action_data: Dict[str, Any],
        proposer: str
    ) -> ProposalResult:
        """
        Propose action to swarm for consensus.
        
        STEPS:
        1. Validate proposal format
        2. Broadcast to all agents
        3. Collect votes with timeout
        4. Calculate consensus
        5. Validate against risk limits
        6. Gate execution if approved
        """
        # Create proposal
        proposal = Proposal(
            proposal_id=str(uuid.uuid4()),
            action_type=action_type,
            action_data=action_data,
            proposer=proposer,
            timestamp=time.time(),
            status=ProposalStatus.PENDING
        )
        
        # Broadcast to agents
        votes = await self._collect_votes(proposal)
        
        # Calculate consensus
        consensus = self.consensus_engine.calculate_consensus(votes)
        
        # Log consensus
        await self.audit_logger.log_consensus(proposal, votes, consensus)
        
        # Validate risk
        if consensus.approved:
            risk_check = await self.risk_validator.validate_action(
                action_type,
                action_data,
                consensus.confidence
            )
            
            if not risk_check.passed:
                proposal.status = ProposalStatus.REJECTED_RISK
                return ProposalResult(
                    proposal=proposal,
                    consensus=consensus,
                    risk_check=risk_check,
                    approved=False,
                    reason="Risk validation failed"
                )
        
        # Gate execution
        if consensus.approved and risk_check.passed:
            execution_allowed = await self.execution_gate.check_allowed(
                action_type,
                action_data
            )
            
            if not execution_allowed.allowed:
                proposal.status = ProposalStatus.REJECTED_GATE
                return ProposalResult(
                    proposal=proposal,
                    consensus=consensus,
                    risk_check=risk_check,
                    approved=False,
                    reason=execution_allowed.reason
                )
            
            proposal.status = ProposalStatus.APPROVED
            return ProposalResult(
                proposal=proposal,
                consensus=consensus,
                risk_check=risk_check,
                approved=True,
                reason="Consensus achieved, risk validated, execution gated"
            )
        
        proposal.status = ProposalStatus.REJECTED_CONSENSUS
        return ProposalResult(
            proposal=proposal,
            consensus=consensus,
            approved=False,
            reason="Consensus not achieved"
        )
    
    async def _collect_votes(
        self,
        proposal: Proposal,
        timeout: float = 10.0
    ) -> List[AgentVote]:
        """
        Collect votes from all agents with timeout.
        """
        vote_tasks = []
        
        for agent_id, agent in self.agents.items():
            # Check agent charter allows voting on this proposal
            charter = AGENT_CHARTERS.get(agent.role)
            if not charter:
                continue
            
            # Create vote task
            task = asyncio.create_task(
                self._get_agent_vote(agent, proposal, charter)
            )
            vote_tasks.append(task)
        
        # Wait for votes with timeout
        try:
            votes = await asyncio.wait_for(
                asyncio.gather(*vote_tasks, return_exceptions=True),
                timeout=timeout
            )
        except asyncio.TimeoutError:
            # Collect partial votes
            votes = [
                task.result() for task in vote_tasks
                if task.done() and not task.exception()
            ]
        
        # Filter out exceptions
        valid_votes = [v for v in votes if isinstance(v, AgentVote)]
        
        return valid_votes
    
    async def _get_agent_vote(
        self,
        agent: BaseAgent,
        proposal: Proposal,
        charter: AgentCharter
    ) -> AgentVote:
        """
        Get vote from single agent with charter enforcement.
        """
        # Check if agent can vote on this action type
        if proposal.action_type in charter.forbidden_actions:
            return AgentVote(
                agent_id=agent.agent_id,
                proposal_id=proposal.proposal_id,
                vote=VoteType.ABSTAIN,
                confidence=0.0,
                reasoning="Charter forbids voting on this action type"
            )
        
        # Get agent's analysis
        analysis = await agent.analyze_proposal(proposal)
        
        # Enforce charter constraints
        confidence = min(analysis.confidence, charter.max_confidence)
        
        # Validate reasoning requirements
        if charter.must_provide_reasoning and not analysis.reasoning:
            return AgentVote(
                agent_id=agent.agent_id,
                proposal_id=proposal.proposal_id,
                vote=VoteType.ABSTAIN,
                confidence=0.0,
                reasoning="Charter requires reasoning but none provided"
            )
        
        # Validate evidence requirements
        if len(analysis.evidence) < charter.required_evidence_count:
            return AgentVote(
                agent_id=agent.agent_id,
                proposal_id=proposal.proposal_id,
                vote=VoteType.ABSTAIN,
                confidence=0.0,
                reasoning=f"Insufficient evidence: {len(analysis.evidence)}/{charter.required_evidence_count}"
            )
        
        # Create vote
        return AgentVote(
            agent_id=agent.agent_id,
            proposal_id=proposal.proposal_id,
            vote=analysis.vote,
            confidence=confidence,
            reasoning=analysis.reasoning,
            evidence=analysis.evidence,
            trust_weight=agent.trust_score * charter.max_vote_weight
        )
```

## 11.3 Agent Health Monitoring

```python
class AgentHealthMonitor:
    """
    Monitors agent health and enforces operational limits.
    
    MONITORS:
    - Assertion rate
    - Error rate
    - Response latency
    - Confidence calibration
    - Charter compliance
    """
    
    def __init__(self):
        self.health_metrics: Dict[str, AgentHealthMetrics] = {}
        self.alert_thresholds = {
            "error_rate": 0.1,  # 10% error rate
            "response_latency_p95": 5.0,  # 5 seconds
            "hallucination_score": 0.3,
            "overconfidence": 0.2
        }
    
    async def check_agent_health(
        self,
        agent_id: str
    ) -> AgentHealthStatus:
        """
        Comprehensive agent health check.
        """
        metrics = self.health_metrics.get(agent_id)
        if not metrics:
            return AgentHealthStatus(
                agent_id=agent_id,
                status="UNKNOWN",
                reason="No metrics available"
            )
        
        violations = []
        
        # Check error rate
        if metrics.error_rate > self.alert_thresholds["error_rate"]:
            violations.append(
                f"High error rate: {metrics.error_rate:.1%}"
            )
        
        # Check response latency
        if metrics.response_latency_p95 > self.alert_thresholds["response_latency_p95"]:
            violations.append(
                f"High latency: {metrics.response_latency_p95:.2f}s"
            )
        
        # Check hallucination score
        if metrics.hallucination_score > self.alert_thresholds["hallucination_score"]:
            violations.append(
                f"High hallucination: {metrics.hallucination_score:.1%}"
            )
        
        # Check overconfidence
        if metrics.overconfidence > self.alert_thresholds["overconfidence"]:
            violations.append(
                f"Overconfident: {metrics.overconfidence:.2f}"
            )
        
        # Determine status
        if len(violations) == 0:
            status = "HEALTHY"
        elif len(violations) <= 2:
            status = "DEGRADED"
        else:
            status = "UNHEALTHY"
        
        return AgentHealthStatus(
            agent_id=agent_id,
            status=status,
            violations=violations,
            metrics=metrics
        )
    
    async def enforce_cooldown(
        self,
        agent_id: str,
        error: Exception
    ) -> None:
        """
        Enforce cooldown period after agent error.
        """
        agent = self.agents.get(agent_id)
        if not agent:
            return
        
        charter = AGENT_CHARTERS.get(agent.role)
        if not charter:
            return
        
        # Suspend agent
        agent.suspended = True
        agent.suspended_until = time.time() + charter.cooldown_after_error
        
        # Log suspension
        await self.audit_logger.log_agent_suspension(
            agent_id=agent_id,
            reason=str(error),
            duration=charter.cooldown_after_error
        )
```

---

# SECTION 12: ADVANCED DEFI TRADING INFRASTRUCTURE

## 12.1 Multi-Venue Execution

```python
class MultiVenueExecutor:
    """
    Execute across multiple DeFi venues with optimal routing.
    
    VENUES:
    - Spot exchanges (Binance, Coinbase, Kraken)
    - Perp exchanges (dYdX, GMX, Hyperliquid)
    - Prediction markets (Polymarket, Augur)
    - DEXs (Uniswap, Curve, Balancer)
    """
    
    def __init__(self):
        self.venues: Dict[str, VenueConnector] = {}
        self.router = SmartOrderRouter()
        self.mev_defender = MEVDefenseEngine()
        self.slippage_estimator = SlippageEstimator()
    
    async def execute_order(
        self,
        order: Order,
        routing_strategy: str = "best_execution"
    ) -> ExecutionResult:
        """
        Execute order with optimal venue routing.
        
        ROUTING STRATEGIES:
        - best_execution: Minimize total cost
        - fastest: Minimize latency
        - mev_resistant: Maximize MEV protection
        - split: Split across multiple venues
        """
        # Estimate slippage across venues
        venue_estimates = await self._estimate_venue_slippage(order)
        
        # Apply MEV defense
        protected_order = await self.mev_defender.protect_order(order)
        
        # Route order
        routing_plan = await self.router.route_order(
            protected_order,
            venue_estimates,
            routing_strategy
        )
        
        # Execute across venues
        results = []
        for venue_order in routing_plan.venue_orders:
            venue = self.venues[venue_order.venue_id]
            
            try:
                result = await venue.execute_order(venue_order)
                results.append(result)
            except Exception as e:
                # Log failure and continue with other venues
                logger.error(f"Venue {venue_order.venue_id} execution failed: {e}")
                results.append(ExecutionResult(
                    success=False,
                    error=str(e),
                    venue_id=venue_order.venue_id
                ))
        
        # Aggregate results
        return self._aggregate_results(order, results)
    
    async def _estimate_venue_slippage(
        self,
        order: Order
    ) -> Dict[str, SlippageEstimate]:
        """
        Estimate slippage for order across all venues.
        """
        estimates = {}
        
        for venue_id, venue in self.venues.items():
            try:
                # Get order book depth
                order_book = await venue.get_order_book(order.symbol)
                
                # Estimate slippage
                estimate = self.slippage_estimator.estimate(
                    order,
                    order_book
                )
                
                estimates[venue_id] = estimate
            except Exception as e:
                logger.warning(f"Failed to estimate slippage for {venue_id}: {e}")
                estimates[venue_id] = SlippageEstimate(
                    venue_id=venue_id,
                    estimated_slippage=float('inf'),  # Worst case
                    confidence=0.0
                )
        
        return estimates
```

## 12.2 Perpetual Futures Trading

```python
class PerpetualFuturesEngine:
    """
    Specialized engine for perpetual futures trading.
    
    FEATURES:
    - Funding rate optimization
    - Leverage management
    - Liquidation protection
    - Basis trading
    """
    
    def __init__(self):
        self.funding_tracker = FundingRateTracker()
        self.liquidation_monitor = LiquidationMonitor()
        self.basis_calculator = BasisCalculator()
    
    async def open_perp_position(
        self,
        symbol: str,
        side: PositionSide,
        size: float,
        leverage: float,
        max_funding_rate: float = 0.01  # 1% daily
    ) -> PerpPosition:
        """
        Open perpetual futures position with safety checks.
        
        SAFETY CHECKS:
        - Funding rate acceptable
        - Leverage within limits
        - Liquidation price safe
        - Collateral sufficient
        """
        # Check funding rate
        current_funding = await self.funding_tracker.get_current_rate(symbol)
        
        if abs(current_funding) > max_funding_rate:
            raise FundingRateTooHighError(
                f"Funding rate {current_funding:.4%} exceeds max {max_funding_rate:.4%}"
            )
        
        # Calculate liquidation price
        liquidation_price = self._calculate_liquidation_price(
            symbol=symbol,
            side=side,
            entry_price=await self._get_current_price(symbol),
            leverage=leverage
        )
        
        # Check liquidation safety
        if not self._is_liquidation_safe(symbol, liquidation_price, side):
            raise LiquidationRiskTooHighError(
                f"Liquidation price {liquidation_price} too close to current price"
            )
        
        # Execute position open
        position = await self._execute_perp_open(
            symbol=symbol,
            side=side,
            size=size,
            leverage=leverage
        )
        
        # Start liquidation monitoring
        await self.liquidation_monitor.start_monitoring(position)
        
        return position
    
    async def manage_funding_payments(
        self,
        position: PerpPosition
    ) -> FundingManagementResult:
        """
        Manage funding rate payments for open position.
        
        STRATEGIES:
        - Close position if funding too negative
        - Reduce size if funding unfavorable
        - Hedge with spot if basis attractive
        """
        current_funding = await self.funding_tracker.get_current_rate(
            position.symbol
        )
        
        # Calculate funding cost
        funding_cost = self._calculate_funding_cost(
            position,
            current_funding
        )
        
        # Determine action
        if funding_cost > position.unrealized_pnl * 0.5:
            # Funding eating into profits - consider closing
            return FundingManagementResult(
                action="CLOSE",
                reason=f"High funding cost: {funding_cost:.2f}"
            )
        
        elif funding_cost > position.unrealized_pnl * 0.2:
            # Funding significant - consider reducing
            return FundingManagementResult(
                action="REDUCE",
                reduction_pct=0.5,
                reason=f"Moderate funding cost: {funding_cost:.2f}"
            )
        
        else:
            # Funding acceptable - hold
            return FundingManagementResult(
                action="HOLD",
                reason=f"Funding acceptable: {funding_cost:.2f}"
            )
```

## 12.3 Prediction Market Integration

```python
class PredictionMarketTrader:
    """
    Trade on prediction markets (Polymarket, Augur).
    
    FEATURES:
    - Event outcome prediction
    - Probability calibration
    - Arbitrage detection
    - Resolution monitoring
    """
    
    def __init__(self):
        self.polymarket = PolymarketConnector()
        self.probability_calibrator = ProbabilityCalibrator()
        self.arbitrage_detector = ArbitrageDetector()
    
    async def evaluate_market(
        self,
        market_id: str
    ) -> MarketEvaluation:
        """
        Evaluate prediction market for trading opportunity.
        
        ANALYSIS:
        - Current market probability
        - Our estimated probability
        - Edge calculation
        - Liquidity assessment
        - Resolution timeline
        """
        # Get market data
        market = await self.polymarket.get_market(market_id)
        
        # Calculate market-implied probability
        market_prob = self._calculate_market_probability(market)
        
        # Get our probability estimate
        our_prob = await self._estimate_outcome_probability(market)
        
        # Calculate edge
        edge = abs(our_prob - market_prob)
        
        # Check liquidity
        liquidity = await self._assess_liquidity(market)
        
        # Evaluate resolution timeline
        resolution_time = self._estimate_resolution_time(market)
        
        return MarketEvaluation(
            market_id=market_id,
            market_probability=market_prob,
            estimated_probability=our_prob,
            edge=edge,
            liquidity=liquidity,
            resolution_time=resolution_time,
            tradeable=edge > 0.05 and liquidity.sufficient
        )
    
    async def place_prediction_bet(
        self,
        market_id: str,
        outcome: str,
        amount: float,
        max_slippage: float = 0.02
    ) -> PredictionBet:
        """
        Place bet on prediction market outcome.
        
        EXECUTION:
        - Verify market still open
        - Check slippage
        - Execute trade
        - Monitor resolution
        """
        # Verify market open
        market = await self.polymarket.get_market(market_id)
        if market.status != "OPEN":
            raise MarketClosedError(f"Market {market_id} is not open")
        
        # Get current price
        current_price = await self.polymarket.get_outcome_price(
            market_id,
            outcome
        )
        
        # Calculate expected shares
        expected_shares = amount / current_price
        
        # Execute trade
        trade_result = await self.polymarket.buy_outcome(
            market_id=market_id,
            outcome=outcome,
            amount=amount,
            max_slippage=max_slippage
        )
        
        # Calculate actual slippage
        actual_slippage = abs(
            trade_result.avg_price - current_price
        ) / current_price
        
        if actual_slippage > max_slippage:
            # Attempt to cancel if possible
            await self.polymarket.cancel_trade(trade_result.trade_id)
            raise SlippageTooHighError(
                f"Slippage {actual_slippage:.2%} exceeds max {max_slippage:.2%}"
            )
        
        # Create bet record
        bet = PredictionBet(
            bet_id=str(uuid.uuid4()),
            market_id=market_id,
            outcome=outcome,
            amount=amount,
            shares=trade_result.shares,
            avg_price=trade_result.avg_price,
            timestamp=time.time(),
            status="OPEN"
        )
        
        # Start resolution monitoring
        await self._monitor_resolution(bet)
        
        return bet
```

---

# SECTION 13: WALLET, IDENTITY, SOCIAL, EMAIL SYSTEMS

## 13.1 Wallet Integration Architecture

```python
class WalletManager:
    """
    Secure wallet integration with multiple providers.
    
    SECURITY REQUIREMENTS:
    - No private keys in memory
    - Hardware wallet support
    - Multi-sig for large transactions
    - Transaction signing isolated
    """
    
    def __init__(self):
        self.connectors: Dict[str, WalletConnector] = {
            "metamask": MetaMaskConnector(),
            "phantom": PhantomConnector(),
            "ledger": LedgerConnector(),
            "trezor": TrezorConnector()
        }
        self.signer = TransactionSigner()
        self.validator = TransactionValidator()
    
    async def connect_wallet(
        self,
        wallet_type: str,
        user_id: str
    ) -> WalletConnection:
        """
        Establish secure wallet connection.
        
        PROCESS:
        1. Request connection from wallet
        2. Verify signature
        3. Store public address only
        4. Never store private keys
        """
        connector = self.connectors.get(wallet_type)
        if not connector:
            raise UnsupportedWalletError(f"Wallet type {wallet_type} not supported")
        
        # Request connection
        connection = await connector.connect()
        
        # Verify ownership via signature
        challenge = self._generate_challenge()
        signature = await connector.sign_message(challenge)
        
        if not self._verify_signature(challenge, signature, connection.address):
            raise WalletVerificationError("Signature verification failed")
        
        # Store connection (address only, never private key)
        wallet_connection = WalletConnection(
            user_id=user_id,
            wallet_type=wallet_type,
            address=connection.address,
            connected_at=time.time(),
            verified=True
        )
        
        await self._store_connection(wallet_connection)
        
        return wallet_connection
    
    async def sign_transaction(
        self,
        user_id: str,
        transaction: Transaction
    ) -> SignedTransaction:
        """
        Sign transaction with user's wallet.
        
        SECURITY:
        - Transaction validated before signing
        - User must approve in wallet
        - Signature verified
        - Transaction logged
        """
        # Get user's wallet connection
        connection = await self._get_connection(user_id)
        
        # Validate transaction
        validation = await self.validator.validate(transaction)
        if not validation.valid:
            raise InvalidTransactionError(validation.reason)
        
        # Get connector
        connector = self.connectors[connection.wallet_type]
        
        # Request signature from wallet (user must approve)
        signed_tx = await connector.sign_transaction(transaction)
        
        # Verify signature
        if not self._verify_transaction_signature(signed_tx):
            raise SignatureVerificationError("Transaction signature invalid")
        
        # Log transaction
        await self._log_transaction(user_id, signed_tx)
        
        return signed_tx
```

## 13.2 Identity & Authentication

```python
class IdentityManager:
    """
    Decentralized identity management.
    
    FEATURES:
    - Web3 authentication
    - DID (Decentralized Identifier) support
    - Zero-knowledge proofs
    - Privacy-preserving verification
    """
    
    def __init__(self):
        self.did_resolver = DIDResolver()
        self.zkp_verifier = ZKProofVerifier()
        self.session_manager = SessionManager()
    
    async def authenticate_user(
        self,
        did: str,
        proof: Dict[str, Any]
    ) -> AuthenticationResult:
        """
        Authenticate user via DID and proof.
        
        PROCESS:
        1. Resolve DID document
        2. Verify proof
        3. Check revocation status
        4. Create session
        """
        # Resolve DID
        did_document = await self.did_resolver.resolve(did)
        if not did_document:
            raise DIDResolutionError(f"Failed to resolve DID: {did}")
        
        # Verify proof
        verification = await self.zkp_verifier.verify(
            proof,
            did_document.verification_methods
        )
        
        if not verification.valid:
            raise AuthenticationError("Proof verification failed")
        
        # Check revocation
        if await self._is_revoked(did):
            raise AuthenticationError("DID has been revoked")
        
        # Create session
        session = await self.session_manager.create_session(
            did=did,
            proof=proof,
            expires_in=3600  # 1 hour
        )
        
        return AuthenticationResult(
            authenticated=True,
            session_id=session.session_id,
            did=did,
            expires_at=session.expires_at
        )
```

## 13.3 Social Integration

```python
class SocialIntegrationManager:
    """
    Integrate with social platforms for sentiment and signals.
    
    PLATFORMS:
    - Twitter/X (market sentiment)
    - Discord (community signals)
    - Telegram (alert channels)
    - Reddit (discussion analysis)
    """
    
    def __init__(self):
        self.twitter = TwitterConnector()
        self.discord = DiscordConnector()
        self.telegram = TelegramConnector()
        self.sentiment_analyzer = SentimentAnalyzer()
    
    async def monitor_social_sentiment(
        self,
        symbols: List[str]
    ) -> Dict[str, SentimentScore]:
        """
        Monitor social sentiment for symbols.
        
        ANALYSIS:
        - Tweet volume and sentiment
        - Discord mention frequency
        - Reddit post sentiment
        - Influencer opinions
        """
        sentiment_scores = {}
        
        for symbol in symbols:
            # Collect social data
            tweets = await self.twitter.search_tweets(symbol, limit=100)
            discord_messages = await self.discord.search_messages(symbol, limit=50)
            reddit_posts = await self.reddit.search_posts(symbol, limit=50)
            
            # Analyze sentiment
            tweet_sentiment = await self.sentiment_analyzer.analyze_tweets(tweets)
            discord_sentiment = await self.sentiment_analyzer.analyze_messages(discord_messages)
            reddit_sentiment = await self.sentiment_analyzer.analyze_posts(reddit_posts)
            
            # Aggregate sentiment
            overall_sentiment = self._aggregate_sentiment([
                tweet_sentiment,
                discord_sentiment,
                reddit_sentiment
            ])
            
            sentiment_scores[symbol] = overall_sentiment
        
        return sentiment_scores
```

## 13.4 Email Notification System

```python
class EmailNotificationManager:
    """
    Reliable email notification system.
    
    REQUIREMENTS:
    - 100% delivery reliability
    - Template-based emails
    - Priority routing
    - Delivery confirmation
    """
    
    def __init__(self):
        self.smtp_client = SMTPClient()
        self.template_engine = EmailTemplateEngine()
        self.delivery_tracker = DeliveryTracker()
    
    async def send_alert(
        self,
        user_id: str,
        alert_type: str,
        alert_data: Dict[str, Any],
        priority: str = "NORMAL"
    ) -> EmailDeliveryResult:
        """
        Send alert email with guaranteed delivery.
        
        PRIORITY LEVELS:
        - CRITICAL: Immediate delivery, SMS backup
        - HIGH: Priority queue, retry aggressive
        - NORMAL: Standard delivery
        - LOW: Batch delivery
        """
        # Get user email
        user = await self._get_user(user_id)
        
        # Render email from template
        email = await self.template_engine.render(
            template_name=f"alert_{alert_type}",
            data=alert_data
        )
        
        # Send with retry logic
        delivery_result = await self._send_with_retry(
            to=user.email,
            subject=email.subject,
            body=email.body,
            priority=priority,
            max_retries=5 if priority == "CRITICAL" else 3
        )
        
        # Track delivery
        await self.delivery_tracker.record_delivery(
            user_id=user_id,
            alert_type=alert_type,
            result=delivery_result
        )
        
        # Send SMS backup for critical alerts if email failed
        if priority == "CRITICAL" and not delivery_result.delivered:
            await self._send_sms_backup(user, alert_data)
        
        return delivery_result
```

---

*[SPECIFICATION CONTINUES WITH SECTIONS 14-20]*

**Document continues in next file...**
