"""
Strategic Debate Protocol Orchestrator
Coordinates debate sessions with quantitative gates and performance tracking.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Set, Tuple

from merid.prediction.debate import DebateStore, DebateSession, DebateArgument, AgentTeam
from merid.prediction.quantitative_gates import get_quantitative_gates, GateSummary
from utils.logger import get_logger

logger = get_logger("merid.prediction.debate_orchestrator")


@dataclass
class DebateConfig:
    """Configuration for debate orchestration."""
    
    # Session settings
    max_rounds: int = 3
    round_duration_minutes: int = 10
    min_participants: int = 2
    max_participants: int = 5
    
    # Quality thresholds
    min_debate_lift: float = 0.02
    min_argument_quality: float = 0.4
    required_evidence_count: int = 1
    
    # Timing settings
    session_timeout_minutes: int = 60
    evaluation_delay_minutes: int = 5
    
    # Gate settings
    enable_quantitative_gates: bool = True
    gate_recheck_interval_minutes: int = 30


@dataclass
class DebateInvitation:
    """Invitation for an agent to participate in a debate."""
    debate_id: str
    agent_id: str
    invited_at: datetime
    expires_at: datetime
    role: str = "participant"
    gate_summary: Optional[GateSummary] = None


@dataclass
class DebateMetrics:
    """Metrics for debate session performance."""
    debate_id: str
    created_at: datetime
    participants: List[str]
    rounds_completed: int
    arguments_count: int
    avg_argument_quality: float
    debate_lift: float
    consensus_improvement: float
    time_to_complete_minutes: float


class DebateOrchestrator:
    """
    Orchestrates strategic debate protocol with quantitative gates.
    
    Manages the full debate lifecycle:
    1. Agent selection and gate validation
    2. Debate session creation and management
    3. Real-time coordination and timing
    4. Performance evaluation and rewards
    5. Leaderboard updates and badge computation
    """
    
    _ORCHESTRATION_STEP_TIMEOUT_S: float = 30.0

    def __init__(self, debate_store: DebateStore, config: Optional[DebateConfig] = None):
        self.store = debate_store
        self.config = config or DebateConfig()
        self.gates = get_quantitative_gates()
        
        # Active session tracking
        self.active_sessions: Dict[str, DebateSession] = {}
        self.pending_invitations: Dict[str, List[DebateInvitation]] = {}
        
        # Background tasks
        self._orchestration_task: Optional[asyncio.Task] = None
        self._running = False
        
    async def start(self) -> None:
        """Start the debate orchestrator background tasks."""
        if self._running:
            logger.warning("Debate orchestrator already running")
            return
            
        self._running = True
        self._orchestration_task = asyncio.create_task(self._orchestration_loop(), name="debate-orchestrator")
        def _task_done_cb(task: asyncio.Task) -> None:
            if not task.cancelled() and task.exception():
                logger.error("Debate orchestrator task crashed: %s", task.exception())
        self._orchestration_task.add_done_callback(_task_done_cb)
        logger.info("Debate orchestrator started")
    
    async def stop(self) -> None:
        """Stop the debate orchestrator background tasks."""
        if not self._running:
            return
            
        self._running = False
        if self._orchestration_task:
            self._orchestration_task.cancel()
            try:
                await self._orchestration_task
            except asyncio.CancelledError:
                pass
                
        logger.info("Debate orchestrator stopped")
    
    async def _orchestration_loop(self) -> None:
        """Main orchestration loop for managing debate sessions."""
        while self._running:
            try:
                steps = [
                    ("scan_debate_opportunities", self._scan_debate_opportunities),
                    ("process_invitations", self._process_invitations),
                    ("manage_active_sessions", self._manage_active_sessions),
                    ("evaluate_completed_sessions", self._evaluate_completed_sessions),
                    ("cleanup_expired_sessions", self._cleanup_expired_sessions),
                ]
                for step_name, step_fn in steps:
                    try:
                        await asyncio.wait_for(
                            step_fn(),
                            timeout=self._ORCHESTRATION_STEP_TIMEOUT_S,
                        )
                    except asyncio.TimeoutError:
                        logger.error(
                            f"Debate orchestration step '{step_name}' timed out "
                            f"after {self._ORCHESTRATION_STEP_TIMEOUT_S}s — skipping"
                        )
                    except Exception as step_exc:
                        logger.error(
                            f"Debate orchestration step '{step_name}' error: {step_exc}"
                        )

                # Sleep before next cycle
                await asyncio.sleep(60)  # Run every minute
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Debate orchestration error: {e}")
                await asyncio.sleep(60)
    
    async def _scan_debate_opportunities(self) -> None:
        """Scan for instruments that would benefit from debate (Kalshi prediction domain only)."""
        try:
            # Get instruments with high disagreement or uncertainty
            from consensus.taco_consensus import get_consensus_coordinator
            from merid.settings import settings
            
            coordinator = get_consensus_coordinator()
            
            # Find symbols with sufficient opinions but low consensus (Kalshi prediction domain only)
            high_disagreement_symbols = []
            for symbol, opinions in getattr(coordinator, '_opinions', {}).items():
                # Filter to Kalshi prediction domain only
                if not self._is_kalshi_prediction_symbol(symbol):
                    continue
                    
                if len(opinions) >= 3:  # Minimum opinions for meaningful debate
                    # Calculate opinion variance
                    scores = [op.score for op in opinions]
                    if len(scores) > 1:
                        variance = sum((s - sum(scores)/len(scores))**2 for s in scores) / len(scores)
                        if variance > 0.1:  # High disagreement threshold
                            high_disagreement_symbols.append(symbol)
            
            # Create debate sessions for high-disagreement instruments (Kalshi only)
            for symbol in high_disagreement_symbols[:5]:  # Limit to 5 new debates per cycle
                await self._create_debate_session(symbol)
                
        except Exception as e:
            logger.warning(f"Error scanning debate opportunities: {e}")

    async def get_opportunity_symbols(self, limit: int = 20) -> List[str]:
        """
        Get read-only list of Kalshi symbols that would benefit from debate.
        
        Args:
            limit: Maximum number of symbols to return
            
        Returns:
            List of Kalshi symbols with high disagreement (read-only, no side effects)
        """
        try:
            # Get instruments with high disagreement or uncertainty
            from consensus.taco_consensus import get_consensus_coordinator
            
            coordinator = get_consensus_coordinator()
            
            # Find symbols with sufficient opinions but low consensus (Kalshi prediction domain only)
            opportunity_symbols = []
            for symbol, opinions in getattr(coordinator, '_opinions', {}).items():
                # Filter to Kalshi prediction domain only
                if not self._is_kalshi_prediction_symbol(symbol):
                    continue
                    
                if len(opinions) >= 3:  # Minimum opinions for meaningful debate
                    # Calculate opinion variance
                    scores = [op.score for op in opinions]
                    if len(scores) > 1:
                        variance = sum((s - sum(scores)/len(scores))**2 for s in scores) / len(scores)
                        if variance > 0.1:  # High disagreement threshold
                            opportunity_symbols.append((symbol, variance))
            
            # Sort by variance (highest disagreement first) and return just symbols
            opportunity_symbols.sort(key=lambda x: x[1], reverse=True)
            return [symbol for symbol, _ in opportunity_symbols[:limit]]
                
        except Exception as e:
            logger.warning(f"Error getting opportunity symbols: {e}")
            return []
    
    def _is_kalshi_prediction_symbol(self, symbol: str) -> bool:
        """Check if symbol belongs to Kalshi prediction domain."""
        try:
            from merid.settings import settings
            
            # Method 1: Check against known Kalshi prediction patterns
            kalshi_patterns = [
                "KXBTCD", "KETH", "KSPX", "KINFL", "KRATE", "KCOMMOD",
                "KPOL", "KWEATHER", "KECON", "KTECH", "KHEALTH"
            ]
            
            # Check if symbol starts with any Kalshi prefix
            for pattern in kalshi_patterns:
                if symbol.startswith(pattern):
                    return True
            
            # Method 2: Check venue registry if available
            try:
                from merid.venue_registry import VenueRegistry
                registry = VenueRegistry()
                venue = registry.get_venue_for_symbol(symbol)
                if venue and "kalshi" in venue.name.lower():
                    return True
            except ImportError:
                pass  # Venue registry not available
            
            # Method 3: Check if symbol is in known Kalshi prediction markets
            try:
                from merid.event_venues.kalshi.client import get_kalshi_client
                client = get_kalshi_client()
                # This would validate against actual Kalshi markets
                # For now, we'll be more permissive with pattern matching
                return any(symbol.startswith(pattern) for pattern in kalshi_patterns)
            except ImportError:
                pass  # Kalshi client not available
            
            return False
            
        except Exception as e:
            logger.debug(f"Error checking Kalshi symbol {symbol}: {e}")
            return False
    
    async def _create_debate_session(self, symbol: str) -> Optional[str]:
        """Create a new debate session for the given Kalshi prediction symbol."""
        try:
            # Validate symbol is in Kalshi prediction domain
            if not self._is_kalshi_prediction_symbol(symbol):
                logger.warning(f"Rejecting debate creation for non-Kalshi symbol: {symbol}")
                return None
            
            # Check if debate already exists for this symbol
            existing_debates = self.store.list_debates(symbol=symbol, status="open")
            if existing_debates:
                return None  # Debate already in progress
            
            # Create new debate session
            debate_id = f"debate-{int(time.time())}-{symbol[:8]}"
            debate = DebateSession(
                id=debate_id,
                symbol=symbol,
                status="open",
                created_at=time.time()
            )
            
            self.store.create_debate(debate)
            self.active_sessions[debate_id] = debate
            
            logger.info(f"Created Kalshi debate session {debate_id} for {symbol}")
            
            # Invite qualified participants
            await self._invite_participants(debate_id, symbol)
            
            return debate_id
            
        except Exception as e:
            logger.error(f"Error creating debate session for {symbol}: {e}")
            return None
    
    async def _invite_participants(self, debate_id: str, symbol: str) -> None:
        """Invite qualified agents to participate in debate with gate enforcement."""
        from core.slo_monitor import SLOMonitor
        
        slo_monitor = SLOMonitor.get_instance()
        invitation_start_time = time.time()
        
        try:
            # Validate symbol is in Kalshi domain before proceeding
            if not self._is_kalshi_prediction_symbol(symbol):
                logger.warning(f"Skipping debate invitations for non-Kalshi symbol: {symbol}")
                slo_monitor.track_slo(
                    metric_name="debate.invitation.domain_violation",
                    success=False,
                    total=1,
                    metadata={"symbol": symbol}
                )
                return
            
            # Get agents with opinions on this symbol
            from consensus.taco_consensus import get_consensus_coordinator
            coordinator = get_consensus_coordinator()
            opinions = getattr(coordinator, '_opinions', {}).get(symbol, [])
            
            if not opinions:
                logger.info(f"No opinions found for Kalshi symbol {symbol}, skipping debate invitations")
                slo_monitor.track_slo(
                    metric_name="debate.invitation.no_opinions",
                    success=False,
                    total=1,
                    metadata={"symbol": symbol}
                )
                return
            
            # Get agent data for gate evaluation
            candidate_agents = []
            for opinion in opinions:
                agent_id = opinion.agent_id
                
                # Collect agent performance data
                agent_data = await self._collect_agent_data(agent_id)
                if agent_data:
                    candidate_agents.append((agent_id, agent_data))
            
            # Evaluate candidates against quantitative gates
            qualified_candidates = []
            for agent_id, agent_data in candidate_agents:
                if self.config.enable_quantitative_gates:
                    gate_summary = self.gates.evaluate_agent(agent_id, agent_data)
                    if gate_summary.overall_passed:
                        qualified_candidates.append((agent_id, gate_summary))
                else:
                    # No gates - all candidates qualified
                    qualified_candidates.append((agent_id, None))
            
            # Select diverse participants
            selected_participants = self._select_diverse_participants(
                qualified_candidates, 
                self.config.max_participants
            )
            
            # Send invitations
            invitations = []
            now = datetime.now(timezone.utc)
            expires_at = now + timedelta(minutes=30)  # 30 minute invitation expiry
            
            for agent_id, gate_summary in selected_participants:
                invitation = DebateInvitation(
                    debate_id=debate_id,
                    agent_id=agent_id,
                    invited_at=now,
                    expires_at=expires_at,
                    gate_summary=gate_summary
                )
                invitations.append(invitation)
            
            self.pending_invitations[debate_id] = invitations
            
            # Track SLO metrics for invitation process
            invitation_latency = time.time() - invitation_start_time
            slo_monitor.track_slo(
                metric_name="debate.invitation.processing_time",
                success=invitation_latency < 5.0,  # 5 second threshold
                total=1,
                metadata={
                    "symbol": symbol,
                    "debate_id": debate_id,
                    "invitation_latency": invitation_latency,
                    "invited_count": len(invitations),
                    "candidate_count": len(candidate_agents)
                }
            )
            
            # Track invitation success rate
            slo_monitor.track_slo(
                metric_name="debate.invitation.success_rate",
                success=len(invitations) >= self.config.min_participants,
                total=1,
                metadata={
                    "symbol": symbol,
                    "invited_count": len(invitations),
                    "required_min": self.config.min_participants,
                    "candidate_count": len(candidate_agents)
                }
            )
            
            logger.info(f"Invited {len(invitations)} agents to Kalshi debate {debate_id} for symbol {symbol}")
            
        except Exception as e:
            logger.error(f"Error inviting participants for debate {debate_id}: {e}")
            slo_monitor.track_slo(
                metric_name="debate.invitation.error",
                success=False,
                total=1,
                metadata={
                    "symbol": symbol,
                    "debate_id": debate_id,
                    "error": str(e)
                }
            )
    
    async def _collect_agent_data(self, agent_id: str) -> Optional[Dict[str, Any]]:
        """Collect comprehensive agent performance data for gate evaluation (Kalshi prediction domain only)."""
        try:
            agent_data = {
                "agent_id": agent_id,
                "domain": "kalshi_prediction",  # Explicit domain tagging
                "recent_predictions": [],
                "recent_arguments": [],
                "debate_history": [],
                "current_team": {}
            }
            
            # Get recent predictions from consensus store (Kalshi prediction domain only)
            from consensus.taco_consensus import get_consensus_coordinator
            coordinator = get_consensus_coordinator()
            
            # Collect agent opinions (as proxy for predictions) - Kalshi symbols only
            for symbol, opinions in getattr(coordinator, '_opinions', {}).items():
                # Filter to Kalshi prediction domain only
                if not self._is_kalshi_prediction_symbol(symbol):
                    continue
                    
                for opinion in opinions:
                    if opinion.agent_id == agent_id:
                        agent_data["recent_predictions"].append({
                            "predicted_prob": (opinion.score + 1.0) / 2.0,  # Convert -1,1 to 0,1
                            "confidence": opinion.confidence,
                            "timestamp": opinion.timestamp,
                            "actual_outcome": None,  # Would be populated from market resolution
                            "symbol": symbol  # Track which Kalshi market
                        })
            
            # Get debate history from debate store (Kalshi prediction domain only)
            agent_debates = self.store.list_agent_debates(agent_id, limit=10)
            for debate in agent_debates:
                # Validate debate symbol is in Kalshi domain
                if self._is_kalshi_prediction_symbol(debate.symbol):
                    agent_data["debate_history"].append({
                        "debate_id": debate.id,
                        "debate_lift": debate.debate_lift or 0.0,
                        "role": "participant",
                        "timestamp": debate.created_at,
                        "symbol": debate.symbol  # Track which Kalshi market
                    })
            
            # Get recent arguments (Kalshi prediction domain only)
            agent_args = self.store.list_agent_arguments(agent_id, limit=10)
            for arg in agent_args:
                # Get the debate to check symbol domain
                debate = self.store.get_debate(arg.debate_id)
                if debate and self._is_kalshi_prediction_symbol(debate.symbol):
                    agent_data["recent_arguments"].append({
                        "content": arg.content,
                        "quality_score": 0.7,  # Would be computed from actual quality metrics
                        "evidence_citations": arg.evidence or [],
                        "timestamp": arg.created_at,
                        "symbol": debate.symbol  # Track which Kalshi market
                    })
            
            return agent_data
            
        except Exception as e:
            logger.warning(f"Error collecting Kalshi agent data for {agent_id}: {e}")
            return None
    
    def _select_diverse_participants(
        self, 
        qualified_candidates: List[Tuple[str, Optional[GateSummary]]], 
        max_participants: int
    ) -> List[Tuple[str, Optional[GateSummary]]]:
        """Select diverse participants from qualified candidates with gate enforcement."""
        from core.slo_monitor import SLOMonitor
        
        slo_monitor = SLOMonitor.get_instance()
        
        if len(qualified_candidates) <= max_participants:
            return qualified_candidates
        
        # Filter to only agents that passed gates and are in Kalshi domain
        gate_passed_candidates = []
        gate_failures = []
        
        for agent_id, gate_summary in qualified_candidates:
            if gate_summary and gate_summary.overall_passed:
                # Double-check domain enforcement
                if gate_summary.gate_results and any("domain" in reason.lower() for reason in gate_summary.blocked_reasons):
                    gate_failures.append((agent_id, "domain_violation"))
                else:
                    gate_passed_candidates.append((agent_id, gate_summary))
            else:
                failure_reason = "gate_failure"
                if gate_summary:
                    failure_reason = "; ".join(gate_summary.blocked_reasons[:2])  # Top 2 reasons
                gate_failures.append((agent_id, failure_reason))
        
        # Track SLO metrics for gate failures
        if gate_failures:
            slo_monitor.track_slo(
                metric_name="debate.gate_failure.rate",
                success=len(gate_passed_candidates),
                total=len(qualified_candidates),
                metadata={
                    "failure_reasons": dict(gate_failures),
                    "total_candidates": len(qualified_candidates),
                    "passed_candidates": len(gate_passed_candidates)
                }
            )
        
        # If not enough qualified candidates, log warning
        if len(gate_passed_candidates) < max_participants:
            logger.warning(
                f"Insufficient qualified candidates: {len(gate_passed_candidates)} "
                f"vs required {max_participants}. Gate failures: {len(gate_failures)}"
            )
            
            # Track SLO for insufficient qualified candidates
            slo_monitor.track_slo(
                metric_name="debate.qualified_candidates.shortage",
                success=len(gate_passed_candidates) >= max_participants,
                total=1,
                metadata={
                    "qualified_count": len(gate_passed_candidates),
                    "required_count": max_participants,
                    "total_candidates": len(qualified_candidates)
                }
            )
        
        # Sort by total gate score (highest first)
        scored_candidates = []
        for agent_id, gate_summary in gate_passed_candidates:
            score = gate_summary.total_score if gate_summary else 0.5
            scored_candidates.append((score, agent_id, gate_summary))
        
        scored_candidates.sort(reverse=True)  # Highest score first
        
        # Select top candidates with diversity consideration
        selected = []
        selected_agent_ids = set()
        
        # First, take the highest-scoring candidates
        for score, agent_id, gate_summary in scored_candidates:
            if len(selected) >= max_participants:
                break
            selected.append((agent_id, gate_summary))
            selected_agent_ids.add(agent_id)
        
        # Track SLO for participant selection quality
        if selected:
            avg_score = sum(gate_summary.total_score for _, gate_summary in selected) / len(selected)
            slo_monitor.track_slo(
                metric_name="debate.participant_selection.avg_score",
                success=avg_score > 0.7,  # Good quality threshold
                total=1,
                metadata={
                    "avg_score": avg_score,
                    "selected_count": len(selected),
                    "max_participants": max_participants
                }
            )
        
        return selected
    
    async def _process_invitations(self) -> None:
        """Process pending debate invitations."""
        now = datetime.now(timezone.utc)
        
        for debate_id, invitations in list(self.pending_invitations.items()):
            # Check for expired invitations
            active_invitations = []
            accepted_count = 0
            
            for invitation in invitations:
                if invitation.expires_at <= now:
                    # Invitation expired
                    logger.debug(f"Invitation expired for {invitation.agent_id} to debate {debate_id}")
                    continue
                
                # Check if agent accepted (would be implemented via agent communication)
                # For now, auto-accept qualified agents
                if invitation.gate_summary and invitation.gate_summary.overall_passed:
                    accepted_count += 1
                    # Add agent to debate session
                    await self._add_participant_to_debate(debate_id, invitation.agent_id)
                else:
                    active_invitations.append(invitation)
            
            # Update pending invitations
            if active_invitations:
                self.pending_invitations[debate_id] = active_invitations
            else:
                del self.pending_invitations[debate_id]
            
            # Start debate if minimum participants reached
            if accepted_count >= self.config.min_participants:
                await self._start_debate_session(debate_id)
    
    async def _add_participant_to_debate(self, debate_id: str, agent_id: str) -> None:
        """Add an agent as a participant to a debate session."""
        try:
            debate = self.active_sessions.get(debate_id)
            if not debate:
                return
            
            if agent_id not in debate.participant_ids:
                debate.participant_ids.append(agent_id)
                self.store.update_debate(debate)
                
                logger.info(f"Added agent {agent_id} to debate {debate_id}")
                
        except Exception as e:
            logger.error(f"Error adding participant {agent_id} to debate {debate_id}: {e}")
    
    async def _start_debate_session(self, debate_id: str) -> None:
        """Start an active debate session."""
        try:
            debate = self.active_sessions.get(debate_id)
            if not debate:
                return
            
            debate.status = "active"
            debate.started_at = time.time()
            self.store.update_debate(debate)
            
            logger.info(f"Started debate session {debate_id} with {len(debate.participant_ids)} participants")

            # Schedule round management
            _round_task = asyncio.create_task(self._manage_debate_rounds(debate_id), name=f"debate-rounds-{debate_id}")
            _round_task.add_done_callback(
                lambda t: logger.error("Debate round management failed: %s", t.exception()) if not t.cancelled() and t.exception() else None
            )
            
        except Exception as e:
            logger.error(f"Error starting debate session {debate_id}: {e}")
    
    async def _manage_debate_rounds(self, debate_id: str) -> None:
        """Manage debate rounds and timing."""
        try:
            debate = self.active_sessions.get(debate_id)
            if not debate:
                return
            
            for round_num in range(1, self.config.max_rounds + 1):
                # Start round
                logger.info(f"Starting round {round_num} for debate {debate_id}")
                
                # Allow arguments for this round
                round_end = time.time() + (self.config.round_duration_minutes * 60)
                
                # Wait for round to complete
                await asyncio.sleep(self.config.round_duration_minutes * 60)
                
                # Check if debate should continue
                if not await self._should_continue_debate(debate_id):
                    break
            
            # End debate session
            await self._end_debate_session(debate_id)
            
        except Exception as e:
            logger.error(f"Error managing debate rounds for {debate_id}: {e}")
    
    async def _should_continue_debate(self, debate_id: str) -> bool:
        """Evaluate if debate should continue to next round."""
        try:
            debate = self.active_sessions.get(debate_id)
            if not debate:
                return False
            
            # Check if minimum lift achieved
            if debate.debate_lift and debate.debate_lift >= self.config.min_debate_lift:
                return True
            
            # Check if participants are still engaged
            recent_args = self.store.list_debate_arguments(debate_id, limit=10)
            if not recent_args:
                return False
            
            return True
            
        except Exception as e:
            logger.error(f"Error evaluating debate continuation for {debate_id}: {e}")
            return False
    
    async def _end_debate_session(self, debate_id: str) -> None:
        """End a debate session and calculate results with SLO tracking."""
        from core.slo_monitor import SLOMonitor
        
        slo_monitor = SLOMonitor.get_instance()
        
        try:
            debate = self.active_sessions.get(debate_id)
            if not debate:
                return
            
            debate.status = "closed"
            debate.closed_at = time.time()
            self.store.update_debate(debate)
            
            # Calculate debate metrics
            metrics = await self._calculate_debate_metrics(debate_id)
            
            # Track SLO metrics for debate completion
            debate_duration = debate.closed_at - debate.created_at
            slo_monitor.track_slo(
                metric_name="debate.completion.duration",
                success=debate_duration < 3600,  # 1 hour threshold
                total=1,
                metadata={
                    "debate_id": debate_id,
                    "symbol": debate.symbol,
                    "duration": debate_duration,
                    "rounds_completed": debate.rounds,
                    "participant_count": len(getattr(debate, 'participant_ids', [])),
                    "debate_lift": metrics.debate_lift
                }
            )
            
            # Track debate lift performance
            slo_monitor.track_slo(
                metric_name="debate.lift.performance",
                success=metrics.debate_lift > 0.01,  # 1% lift threshold
                total=1,
                metadata={
                    "debate_id": debate_id,
                    "symbol": debate.symbol,
                    "debate_lift": metrics.debate_lift,
                    "pre_debate_prob": debate.pre_debate_prob,
                    "post_debate_prob": debate.post_debate_prob,
                    "rounds_completed": debate.rounds
                }
            )
            
            # Track debate quality score
            quality_score = metrics.debate_lift * (1.0 + debate.rounds * 0.1)  # Weight by rounds
            slo_monitor.track_slo(
                metric_name="debate.quality.score",
                success=quality_score > 0.02,  # Quality threshold
                total=1,
                metadata={
                    "debate_id": debate_id,
                    "symbol": debate.symbol,
                    "quality_score": quality_score,
                    "debate_lift": metrics.debate_lift,
                    "rounds_completed": debate.rounds
                }
            )
            
            logger.info(f"Ended Kalshi debate session {debate_id} for symbol {debate.symbol} with lift {metrics.debate_lift:.3f}")
            
            # Remove from active sessions
            self.active_sessions.pop(debate_id, None)
            
        except Exception as e:
            logger.error(f"Error ending debate session {debate_id}: {e}")
            slo_monitor.track_slo(
                metric_name="debate.completion.error",
                success=False,
                total=1,
                metadata={
                    "debate_id": debate_id,
                    "error": str(e)
                }
            )
    
    async def _calculate_debate_metrics(self, debate_id: str) -> DebateMetrics:
        """Calculate comprehensive metrics for a debate session."""
        try:
            debate = self.store.get_debate(debate_id)
            if not debate:
                raise ValueError(f"Debate {debate_id} not found")
            
            # Get arguments
            arguments = self.store.list_debate_arguments(debate_id)
            
            # Calculate metrics
            metrics = DebateMetrics(
                debate_id=debate_id,
                created_at=datetime.fromtimestamp(debate.created_at, tz=timezone.utc),
                participants=debate.participant_ids,
                rounds_completed=debate.rounds or 0,
                arguments_count=len(arguments),
                avg_argument_quality=0.7,  # Would be calculated from actual quality scores
                debate_lift=debate.debate_lift or 0.0,
                consensus_improvement=0.0,  # Would be calculated from pre/post consensus
                time_to_complete_minutes=0.0  # Would be calculated from timing data
            )
            
            return metrics
            
        except Exception as e:
            logger.error(f"Error calculating metrics for debate {debate_id}: {e}")
            raise
    
    async def _manage_active_sessions(self) -> None:
        """Manage and monitor active debate sessions."""
        # Check for sessions that need attention
        for debate_id, debate in list(self.active_sessions.items()):
            if debate.status == "active":
                # Check for timeout
                if debate.started_at:
                    elapsed_minutes = (time.time() - debate.started_at) / 60
                    if elapsed_minutes > self.config.session_timeout_minutes:
                        logger.warning(f"Debate {debate_id} timed out, ending session")
                        await self._end_debate_session(debate_id)
    
    async def _evaluate_completed_sessions(self) -> None:
        """Evaluate recently completed debate sessions."""
        # Get recently closed debates
        recent_debates = self.store.list_debates(
            status="closed", 
            limit=10,
            since=time.time() - 3600  # Last hour
        )
        
        for debate in recent_debates:
            try:
                # Calculate rewards for participants
                await self._calculate_debate_rewards(debate.id)
                
                # Update leaderboards
                await self._update_leaderboards(debate.id)
                
            except Exception as e:
                logger.error(f"Error evaluating completed debate {debate.id}: {e}")
    
    async def _calculate_debate_rewards(self, debate_id: str) -> None:
        """Calculate and distribute rewards for debate participants."""
        try:
            debate = self.store.get_debate(debate_id)
            if not debate or not debate.participant_ids:
                return
            
            # Base rewards for participation
            base_reward = 10.0
            
            # Performance bonuses based on lift and quality
            lift_bonus = (debate.debate_lift or 0.0) * 100.0
            
            for agent_id in debate.participant_ids:
                total_reward = base_reward + lift_bonus
                
                # Record reward
                self.store.add_reward(
                    agent_id=agent_id,
                    team_id="",  # Would be set if team-based
                    reward_type="debate_participation",
                    points=total_reward,
                    detail=f"Participated in debate {debate_id} with lift {debate.debate_lift:.3f}",
                    symbol=debate.symbol
                )
            
            logger.info(f"Distributed debate rewards for {debate_id}")
            
        except Exception as e:
            logger.error(f"Error calculating rewards for debate {debate_id}: {e}")
    
    async def _update_leaderboards(self, debate_id: str) -> None:
        """Update leaderboards after debate completion."""
        try:
            # Leaderboard computation is handled by DebateStore.compute_leaderboard()
            # This could trigger immediate updates or cache invalidation
            logger.debug(f"Leaderboard update triggered by debate {debate_id}")
            
        except Exception as e:
            logger.error(f"Error updating leaderboards for debate {debate_id}: {e}")
    
    async def _cleanup_expired_sessions(self) -> None:
        """Clean up expired debate sessions and invitations."""
        now = datetime.now(timezone.utc)
        
        # Clean up expired invitations
        for debate_id, invitations in list(self.pending_invitations.items()):
            active_invitations = [
                inv for inv in invitations 
                if inv.expires_at > now
            ]
            
            if active_invitations:
                self.pending_invitations[debate_id] = active_invitations
            else:
                del self.pending_invitations[debate_id]
        
        # Clean up very old active sessions
        for debate_id, debate in list(self.active_sessions.items()):
            age_hours = (time.time() - debate.created_at) / 3600
            if age_hours > 24:  # Sessions older than 24 hours
                logger.warning(f"Force-cleaning old debate session {debate_id}")
                await self._end_debate_session(debate_id)


# Global orchestrator instance
_debate_orchestrator: Optional[DebateOrchestrator] = None


def get_debate_orchestrator() -> Optional[DebateOrchestrator]:
    """Get the global debate orchestrator instance."""
    return _debate_orchestrator


def initialize_debate_orchestrator(debate_store: DebateStore, config: Optional[DebateConfig] = None) -> DebateOrchestrator:
    """Initialize the global debate orchestrator."""
    global _debate_orchestrator
    _debate_orchestrator = DebateOrchestrator(debate_store, config)
    return _debate_orchestrator
