"""Background explainer worker for Prime Screen narratives."""
from __future__ import annotations

import asyncio
import json
from utils.logger import get_logger
import os
import time
from typing import List

import requests

from web.api.prime_screen import PrimeScreenStore

logger = get_logger(__name__)

LLM_URL = os.environ.get("MERID_LLM_URL", "http://127.0.0.1:11434/api/generate")
LLM_MODEL = os.environ.get("MERID_LLM_MODEL", "merid-strategist:latest")

# Rate limiting: max 2 requests per second
LAST_LLM_CALL = 0.0
MIN_LLM_INTERVAL = 0.5  # seconds between calls


class DecisionExplainerService:
    """Polls pending decisions and generates narratives via local LLM."""

    def __init__(
        self,
        store: PrimeScreenStore,
        *,
        batch_size: int = 3,
        sleep_seconds: float = 2.0,
    ) -> None:
        self.store = store
        self.batch_size = batch_size
        self.sleep_seconds = sleep_seconds
        self._stopping = asyncio.Event()

    async def run_forever(self) -> None:
        logger.info(
            "Prime Screen explainer worker started (pid=%s, store=%s)",
            os.getpid(),
            self.store.path,
        )
        while not self._stopping.is_set():
            try:
                processed = await self._process_batch()
            except Exception as exc:  # pylint: disable=broad-except
                logger.exception("Explainer batch failed: %s", exc)
                processed = 0
            if processed == 0:
                await asyncio.sleep(self.sleep_seconds)

    def stop(self) -> None:
        self._stopping.set()

    async def _process_batch(self) -> int:
        pending = self.store.list_pending_decisions(
            eligible_states=["approved", "filled", "risk_blocked"],
            limit=self.batch_size,
        )
        if not pending:
            return 0
        logger.debug("Processing %s pending narratives", len(pending))
        count = 0
        for decision_id in pending:
            await self._process_decision(decision_id)
            count += 1
        return count

    async def _process_decision(self, decision_id: str) -> None:
        detail = self.store.get_decision(decision_id)
        prompt = build_prompt(detail)
        # ensure status reflects work-in-progress
        self.store.set_narrative(decision_id, None, status="pending")
        try:
            narrative = await call_local_llm(prompt)
        except Exception as exc:  # pylint: disable=broad-except
            logger.warning("LLM generation failed for %s: %s", decision_id, exc)
            self.store.set_narrative(decision_id, None, status="failed")
            return
        self.store.set_narrative(decision_id, narrative.strip(), status="ready")


def build_prompt(detail) -> str:
    parts: List[str] = [
        "SYSTEM: Generate a concise explanation for the swarm decision.",
        f"Decision: {detail.decision.symbol} {detail.decision.action} size {detail.decision.size}",
        f"State: {detail.decision.state} score {detail.decision.score}",
        f"Expected value: {detail.decision.expected_value} risk score {detail.decision.risk_score}",
    ]
    if detail.features_snapshot:
        parts.append(
            "Features: "
            f"spot {detail.features_snapshot.spot_price}, funding {detail.features_snapshot.funding_rate}, "
            f"ob_imbalance {detail.features_snapshot.orderbook_imbalance}, vol {detail.features_snapshot.realized_vol_1h}"
        )
    if detail.risk_actions:
        parts.append("Risk actions:")
        for action in detail.risk_actions:
            parts.append(
                f" - {action.type} from {action.before} to {action.after} because {action.reason}"
            )
    if detail.orders:
        parts.append("Orders:")
        for order in detail.orders:
            parts.append(
                f" - {order.order_id} @ {order.venue} state={order.state} filled={order.filled_qty or 0}"
            )
    if detail.news_refs:
        parts.append(f"News refs: {', '.join(detail.news_refs)}")
    return "\n".join(parts)


async def call_local_llm(prompt: str) -> str:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _call_llm_sync, prompt)


def _call_llm_sync(prompt: str) -> str:
    global LAST_LLM_CALL
    
    # Rate limiting: enforce minimum interval between LLM calls
    now = time.time()
    if now - LAST_LLM_CALL < MIN_LLM_INTERVAL:
        time.sleep(MIN_LLM_INTERVAL - (now - LAST_LLM_CALL))
    LAST_LLM_CALL = time.time()
    
    payload = {"model": LLM_MODEL, "prompt": prompt, "stream": False}
    response = requests.post(LLM_URL, json=payload, timeout=60)
    
    # Short-circuit 404s to avoid spamming logs
    if response.status_code == 404:
        raise RuntimeError("LLM endpoint not found")
    
    response.raise_for_status()
    data = response.json()
    if isinstance(data, dict):
        text = data.get("response") or data.get("result")
    else:
        text = json.dumps(data)
    if not text:
        raise ValueError("LLM returned empty response")
    return text
