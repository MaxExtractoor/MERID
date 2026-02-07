from __future__ import annotations

"""Stage 8 Automation: central publisher orchestrating Telegram and X outputs."""

from typing import Any, Dict, List, Tuple

from core.state import state
from utils.logger import get_logger

from interfaces.telegram import is_configured as telegram_ready, send_alert as telegram_send
from interfaces.x_publisher import is_configured as x_ready, send_update as x_send

logger = get_logger("interfaces.automation")


def _format_message(energy: Dict[str, Any], vote_result: Dict[str, Any], validation: Dict[str, Any]) -> str:
    payload = energy.get("payload", "")[:500]
    source = energy.get("source", "unknown")
    consensus = vote_result.get("consensus", 0.0)
    return (
        "🧠 *MERID Reality Confirmed*\n"
        f"Source: `{source}`\n"
        f"Consensus: {consensus:.1%}\n"
        f"Validation Score: {validation.get('score', 0):.2f}\n\n"
        f"{payload}"
    )


def _sanitize_markdown(text: str) -> str:
    return text.replace("*", "").replace("`", "'")


async def _send_with_retry(callable_fn, attempts: int = 2) -> bool:
    for attempt in range(attempts):
        success = await callable_fn()
        if success:
            return True
    return False


async def broadcast_reality(energy: Dict[str, Any], vote_result: Dict[str, Any], validation: Dict[str, Any]) -> None:
    """Publish a confirmed reality to configured outbound channels."""
    status = validation.get("status")
    energy_id = energy["energy_id"]

    if status != "confirmed":
        await state.record_automation_event(
            channel="automation",
            status="skipped",
            message=f"Validation status {status} — automation skipped.",
            energy_id=energy_id,
        )
        return

    message = _format_message(energy, vote_result, validation)
    tasks: List[Tuple[str, bool]] = []

    if telegram_ready():
        success = await _send_with_retry(lambda: telegram_send(_sanitize_markdown(message)))
        tasks.append(("telegram", success))
    else:
        tasks.append(("telegram", False))

    if x_ready():
        success = await _send_with_retry(lambda: x_send(message))
        tasks.append(("x", success))
    else:
        tasks.append(("x", False))

    for channel, success in tasks:
        await state.record_automation_event(
            channel=channel,
            status="sent" if success else "failed",
            message=f"{channel} automation {'succeeded' if success else 'failed'} for energy {energy_id}",
            energy_id=energy_id,
        )
        if success:
            logger.info("Automation delivered via %s", channel)
        else:
            logger.warning("Automation failed via %s", channel)
