"""§4 Signal Agents — SentimentAgent, NewsThesisAgent, TelegramOpsAgent.

Canonical agents that consume processed InfoEvents and produce
structured outputs for the swarm pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional

from merid.agents.base import AgentCategory, AgentOutput, CanonicalAgent
from merid.agents.research import ResearchThesis, ThesisDirection
from merid.signals.events import (
    InfoEvent,
    InfoSource,
    OperatorCommand,
    SentimentFeature,
    SentimentSpike,
)
from merid.signals.processing import SentimentProcessor

from utils.logger import get_logger

logger = get_logger("merid.signals.agents")


# ======================================================================
# SentimentAgent
# ======================================================================

class SentimentAgent(CanonicalAgent):
    """Consumes InfoEvents from X + news, maintains per-ticker sentiment.

    Emits SentimentSpike events when thresholds are crossed.
    Feeds sentiment features to strategy and risk agents.
    """

    def __init__(
        self,
        agent_id: str = "sentiment-agent-01",
        processor: Optional[SentimentProcessor] = None,
        spike_threshold: float = 0.5,
    ):
        super().__init__(agent_id, AgentCategory.RESEARCH)
        self._processor = processor or SentimentProcessor(spike_threshold=spike_threshold)
        self._pending_events: List[InfoEvent] = []

    @property
    def processor(self) -> SentimentProcessor:
        return self._processor

    def ingest(self, events: List[InfoEvent]) -> None:
        """Queue events for next run."""
        self._pending_events.extend(events)

    async def _execute(self, context: Dict[str, Any]) -> AgentOutput:
        """Process pending events, detect spikes, emit features."""
        # Accept events from context or pending queue
        events = context.get("info_events", []) + self._pending_events
        self._pending_events.clear()

        features = self._processor.process_batch(events)
        spikes = self._processor.detect_all_spikes()

        # Build per-ticker summaries
        ticker_summaries = {}
        for ticker in self._processor.get_tracked_tickers():
            window = self._processor.get_window(ticker, window_minutes=15)
            ticker_summaries[ticker] = window.to_dict()

        return AgentOutput(
            agent_id=self.agent_id,
            category=self.category.value,
            output_type="sentiment_features",
            payload={
                "features_count": len(features),
                "spikes": [s.to_dict() for s in spikes],
                "spikes_count": len(spikes),
                "ticker_summaries": ticker_summaries,
                "events_processed": len(events),
            },
            confidence=0.6 if spikes else 0.4,
        )


# ======================================================================
# NewsThesisAgent
# ======================================================================

class NewsThesisAgent(CanonicalAgent):
    """Builds structured theses from high-signal news events.

    Consumes InfoEvents with source=NEWS, evaluates event type and
    sentiment, and produces ResearchThesis objects.
    """

    # Event types that warrant thesis generation
    THESIS_EVENT_TYPES = {
        "earnings", "macro", "regulatory", "hack", "exploit",
        "partnership", "launch", "delisting", "sec", "fed",
    }

    def __init__(self, agent_id: str = "news-thesis-01"):
        super().__init__(agent_id, AgentCategory.RESEARCH)
        self._theses: List[ResearchThesis] = []

    async def _execute(self, context: Dict[str, Any]) -> AgentOutput:
        """Generate theses from news events in context."""
        events: List[InfoEvent] = context.get("info_events", [])
        news_events = [e for e in events if e.source == InfoSource.NEWS]

        # Also accept sentiment features for enrichment
        spikes: List[Dict] = context.get("spikes", [])

        theses = []
        for event in news_events:
            thesis = self._build_thesis(event)
            if thesis:
                theses.append(thesis)
                self._theses.append(thesis)

        # Generate spike-driven theses
        for spike_dict in spikes:
            thesis = self._build_spike_thesis(spike_dict)
            if thesis:
                theses.append(thesis)
                self._theses.append(thesis)

        return AgentOutput(
            agent_id=self.agent_id,
            category=self.category.value,
            output_type="theses",
            payload={
                "theses": [t.to_dict() for t in theses],
                "count": len(theses),
                "data_sources": ["news", "sentiment_spikes"],
            },
            confidence=max((t.confidence for t in theses), default=0.3),
        )

    def _build_thesis(self, event: InfoEvent) -> Optional[ResearchThesis]:
        """Build a thesis from a single news event."""
        event_type = event.metadata.get("event_type", "").lower()
        sentiment = event.metadata.get("sentiment_score")
        relevance = event.metadata.get("relevance_score", 0)

        # Only generate thesis for high-relevance or known event types
        if event_type not in self.THESIS_EVENT_TYPES and (relevance or 0) < 0.5:
            return None

        if not event.tickers:
            return None

        # Determine direction from sentiment
        if sentiment is not None:
            if sentiment > 0.3:
                direction = ThesisDirection.LONG
            elif sentiment < -0.3:
                direction = ThesisDirection.SHORT
            else:
                direction = ThesisDirection.NEUTRAL
        else:
            direction = ThesisDirection.NEUTRAL

        confidence = min(0.9, abs(sentiment or 0) * 0.5 + (relevance or 0) * 0.5)

        return ResearchThesis(
            thesis_id=f"news-{event.event_id}",
            domain="crypto" if any(t in {"BTC", "ETH", "SOL"} for t in event.tickers) else "equity",
            instrument=event.tickers[0],
            direction=direction,
            confidence=confidence,
            drivers=[event_type or "news", f"sentiment={sentiment}"],
            data_sources=["news", event.author],
            summary=event.raw_text[:200],
        )

    def _build_spike_thesis(self, spike: Dict[str, Any]) -> Optional[ResearchThesis]:
        """Build a thesis from a sentiment spike."""
        ticker = spike.get("ticker", "")
        direction_str = spike.get("direction", "neutral")
        delta = spike.get("delta", 0)

        if not ticker or abs(delta) < 0.3:
            return None

        direction = ThesisDirection.LONG if direction_str == "bullish" else ThesisDirection.SHORT

        return ResearchThesis(
            thesis_id=f"spike-{spike.get('spike_id', '')}",
            domain="crypto" if ticker in {"BTC", "ETH", "SOL"} else "equity",
            instrument=ticker,
            direction=direction,
            confidence=min(0.85, abs(delta)),
            drivers=[f"sentiment_spike_{direction_str}", f"delta={delta:.4f}"],
            data_sources=["sentiment_spike"],
            summary=f"Sentiment spike on {ticker}: {direction_str} delta={delta:.4f}",
        )

    def get_theses(self, limit: int = 20) -> List[ResearchThesis]:
        return self._theses[-limit:]


# ======================================================================
# TelegramOpsAgent
# ======================================================================

class TelegramOpsAgent(CanonicalAgent):
    """Translates operator Telegram commands into swarm tasks.

    Commands go through governance/risk agents, not directly to code paths.
    """

    def __init__(self, agent_id: str = "telegram-ops-01"):
        super().__init__(agent_id, AgentCategory.OPS)
        self._processed_commands: List[OperatorCommand] = []
        self._tasks: List[Dict[str, Any]] = []

    async def _execute(self, context: Dict[str, Any]) -> AgentOutput:
        """Process pending operator commands from Telegram."""
        commands: List[OperatorCommand] = context.get("operator_commands", [])

        tasks = []
        for cmd in commands:
            task = self._translate_command(cmd)
            if task:
                tasks.append(task)
                self._tasks.append(task)
            self._processed_commands.append(cmd)

        return AgentOutput(
            agent_id=self.agent_id,
            category=self.category.value,
            output_type="operator_tasks",
            payload={
                "tasks": tasks,
                "count": len(tasks),
                "commands_processed": len(commands),
            },
            confidence=0.9 if tasks else 0.5,
        )

    def _translate_command(self, cmd: OperatorCommand) -> Optional[Dict[str, Any]]:
        """Translate an operator command into a swarm task."""
        task_map = {
            "pause": "consider_pause",
            "resume": "consider_resume",
            "status": "report_status",
            "kill_switch": "activate_kill_switch",
            "positions": "report_positions",
            "risk": "report_risk",
        }

        task_type = task_map.get(cmd.command)
        if not task_type:
            return None

        return {
            "task_type": task_type,
            "domain": cmd.domain or "all",
            "reason": cmd.reason or f"Operator command: /{cmd.command}",
            "operator_id": cmd.operator_id,
            "command_id": cmd.command_id,
            "timestamp": cmd.timestamp.isoformat(),
            "requires_governance": cmd.command in ("pause", "resume", "kill_switch"),
        }

    def get_tasks(self, limit: int = 50) -> List[Dict[str, Any]]:
        return self._tasks[-limit:]
