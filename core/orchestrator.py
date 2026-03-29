from __future__ import annotations

# Stage 2 Core: resilient orchestrator, singleton lifecycle, and blind consensus routing.

import asyncio
from typing import Any, Dict, List

from agents.registry import load_agents
from agents.reflection_layer import reflection_layer
from core.event_bus import event_stream
from core.settings import CONSENSUS_THRESHOLD
from core.state import state as global_state
from db.neo4j import memory
from core.validation.engine import validation_engine
from interfaces.automation import broadcast_reality
from memory.store import reality_memory
from swarm.performance import performance_ledger
from swarm.spawner import SwarmSpawner
from utils.logger import get_logger
from hardening.watchdog import watchdog
from core.consensus_math import Vote, compute_consensus

try:
    from voting.engine import blind_vote  # type: ignore
except Exception:  # pragma: no cover - compatibility fallback
    def blind_vote(votes_with_agents, threshold=CONSENSUS_THRESHOLD):
        weighted_votes = []
        summaries = []
        for response, agent in votes_with_agents:
            vote_raw = str(response.get("vote", "reject")).strip().lower()
            vote_int = 1 if vote_raw in {"accept", "approve", "yes", "buy", "long", "1", "true"} else -1
            confidence = float(response.get("confidence", 0.0) or 0.0)
            agent_id = getattr(agent, "agent_id", response.get("agent_id", "unknown"))
            trust = float(getattr(agent, "trust", response.get("trust", 1.0) or 1.0))
            weighted_votes.append(
                Vote(
                    agent_id=agent_id,
                    vote=vote_int,
                    trust=trust,
                    confidence=confidence,
                    source=str(response.get("source", "unknown")),
                    source_srw=float(response.get("source_srw", 1.0) or 1.0),
                )
            )
            summaries.append(
                {
                    "agent": agent_id,
                    "vote": vote_int,
                    "confidence": confidence,
                    "reasoning": str(response.get("reasoning", "")),
                }
            )
        result = compute_consensus(weighted_votes, threshold=threshold)
        return {"consensus": result.consensus_score, "approved": result.approved, "summaries": summaries}


class MeridCore:
    """Central orchestrator driving MERID agent debates and consensus."""

    def __init__(self) -> None:
        self.logger = get_logger("core.orchestrator")
        self.state = global_state
        self.spawner = SwarmSpawner(performance_ledger)
        base_agents = load_agents()
        self.agents = self.spawner.bootstrap(base_agents)
        watchdog.ensure_running()
        self.logger.info("MERID CORE INITIALIZED — %d agents active", len(self.agents))
        for agent in self.agents:
            self.logger.info("  • %s → %s", agent.agent_id, agent.model_name)

    async def run_cycle(self, energy: Dict[str, Any]) -> Dict[str, Any]:
        """Run a full reasoning cycle across all agents for a given energy packet."""
        energy_id = energy["energy_id"]
        payload_preview = energy.get("payload", "")[:160]

        self.logger.info("Processing energy %s | %s", energy_id, payload_preview)
        await event_stream.publish(
            "core:energy_received",
            {"energy_id": energy_id, "source": energy.get("source"), "payload": payload_preview},
        )

        memory.log_energy(energy)

        agent_tasks = [self._execute_agent(agent, energy) for agent in self.agents]
        responses = await asyncio.gather(*agent_tasks)

        vote_result = blind_vote(list(zip(responses, self.agents)), threshold=CONSENSUS_THRESHOLD)

        vote_records = [
            {
                "agent_id": agent.agent_id,
                "vote": response.get("vote"),
                "confidence": response.get("confidence"),
                "reasoning": response.get("reasoning", ""),
            }
            for agent, response in zip(self.agents, responses)
        ]

        memory.log_votes(energy_id, vote_records)
        performance_ledger.record_cycle(vote_records, vote_result["approved"])

        await event_stream.publish(
            "core:consensus_complete",
            {"energy_id": energy_id, "consensus": vote_result["consensus"], "approved": vote_result["approved"]},
        )

        if vote_result["approved"]:
            await self._handle_approved_energy(energy, vote_result, responses)
            validation_result = await self._validate_reality(energy, vote_result)
            
            # Record outcome for reflection layer
            reality_gap = validation_result.get("reality_gap")
            validated = validation_result.get("validated", True)
            reflection_layer.record_outcome(energy_id, validated, reality_gap)
        else:
            self.logger.info(
                "Energy %s dissipated (consensus %.3f < %.2f)",
                energy_id,
                vote_result["consensus"],
                CONSENSUS_THRESHOLD,
            )
            # Record rejection outcome
            reflection_layer.record_outcome(energy_id, validated=False)

        self.agents = self.spawner.refresh_population()
        return vote_result

    async def _execute_agent(self, agent, energy: Dict[str, Any]) -> Dict[str, Any]:
        try:
            result = await agent.process(energy, phase="reasoning")
            return result
        except Exception as exc:  # pragma: no cover - best-effort resilience
            error_type = "unknown"
            error_details = str(exc)
            self.logger.error("[%s] agent failure: %s", agent.agent_id, exc)
            
            # Publish structured error event
            await event_stream.publish(
                "agent:error",
                {
                    "agent_id": agent.agent_id, 
                    "energy_id": energy["energy_id"], 
                    "error": error_details,
                    "error_type": error_type
                },
            )
            
            # Return structured fallback response
            fallback_reasoning = f"Agent {error_type} error: {error_details[:200]}"
            return {
                "agent_id": agent.agent_id,
                "vote": "abstain",
                "confidence": 0.0,
                "reasoning": fallback_reasoning,
                "simulation": f"Agent encountered {error_type} error",
                "raw": "",
                "trust": getattr(agent, "trust", 1.0),
                "error_type": error_type,
                "error_details": error_details,
            }

    async def _handle_approved_energy(
        self,
        energy: Dict[str, Any],
        vote_result: Dict[str, Any],
        responses: List[Dict[str, Any]],
    ) -> None:
        energy_id = energy["energy_id"]
        consensus = vote_result["consensus"]
        await self.state.record_top_pick(
            energy_id=energy_id,
            payload=energy.get("payload", ""),
            consensus=consensus,
            source=energy.get("source", "user"),
            curator=[summary["agent"] for summary in vote_result["summaries"] if summary["vote"] > 0],
        )

        memory.log_reality(
            energy_id,
            vote_result,
            [{"agent_id": agent.agent_id, "vote": response.get("vote")} for agent, response in zip(self.agents, responses)],
        )

        alert_lines = [
            "MERID REALITY CONFIRMED",
            f"Payload: {energy.get('payload')}",
            f"Consensus: {consensus:.1%}",
            "",
            "Agent Agreement:",
        ]
        alert_lines.extend(
            [
                f"• {summary['agent']}: {summary['reasoning'][:200]}..."
                for summary in vote_result["summaries"]
                if summary["vote"] > 0
            ]
        )

        await self._dispatch_alert("\n".join(alert_lines))
        await event_stream.publish(
            "core:reality_created",
            {"energy_id": energy_id, "consensus": consensus, "summary": alert_lines},
        )
        self.logger.info("Reality formed for energy %s at %.2f%% consensus", energy_id, consensus * 100)

    async def _validate_reality(self, energy: Dict[str, Any], vote_result: Dict[str, Any]) -> None:
        verdict = await validation_engine.validate(energy, vote_result)
        await self.state.record_validation(energy, verdict, vote_result)
        await event_stream.publish(
            "core:validation_update",
            {"energy_id": energy["energy_id"], "validation": verdict},
        )
        if verdict["status"] == "confirmed":
            contributions = [
                {
                    "agent_id": agent.agent_id,
                    "vote": response.get("vote"),
                    "confidence": response.get("confidence"),
                }
                for agent, response in zip(self.agents, vote_result.get("summaries", []))
            ]
            reality_memory.record(energy, vote_result, verdict, contributions)
            await broadcast_reality(energy, vote_result, verdict)
        self.logger.info(
            "Validation recorded for energy %s: status=%s score=%.2f",
            energy["energy_id"],
            verdict["status"],
            verdict["score"],
        )

    async def _dispatch_alert(self, message: str) -> None:
        try:
            from interfaces.telegram import send_alert

            await send_alert(message)
        except Exception as exc:
            self.logger.error("Failed to dispatch Telegram alert: %s", exc)


_CORE_INSTANCE: MeridCore | None = None


def get_core() -> MeridCore:
    global _CORE_INSTANCE
    if _CORE_INSTANCE is None:
        _CORE_INSTANCE = MeridCore()
    return _CORE_INSTANCE
