"""X (Twitter) bot API — social media posting and sentiment monitoring."""
from __future__ import annotations

from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException, Request, status
from utils.logger import get_logger

logger = get_logger(__name__)

from core.agent_orchestrator import get_agent_orchestrator
from core.cross_domain_portfolio import get_portfolio_engine
from core.automated_risk_controls import get_risk_coordinator
from core.env import capabilities
from security.breach_detection import get_breach_detection_system
from social.social_aware_quant import (
    get_social_aware_quant_engine,
    get_social_bot_health_monitor,
)
from social.social_data_quality import get_social_data_quality_monitor
from social.x_bot_commands import get_default_commands


def _lazy_anti_silent():
    from swarm.anti_silent_failure import get_anti_silent_failure_system  # noqa: PLC0415
    return get_anti_silent_failure_system()


def _lazy_security_defense():
    from swarm.security_defense_system import get_security_defense_system  # noqa: PLC0415
    return get_security_defense_system()


router = APIRouter(prefix="/api/v1", tags=["x-bot"])


def _require_service_token(request: Request) -> None:
    """Simple auth gate for internal bot calls."""
    expected = capabilities.x_bot_service_token
    if not expected:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="X bot service token not configured",
        )

    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing token")

    token = auth_header.split(" ", 1)[1]
    if token != expected:
        system = get_breach_detection_system()
        system.detect_auth_failure("x_bot_service", request.client.host if request.client else "unknown", "invalid_token")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")


@router.get("/x/status")
async def get_x_status(_: None = Depends(_require_service_token)) -> Dict[str, Any]:
    orchestrator = get_agent_orchestrator()
    anti_silent = _lazy_anti_silent()
    health_monitor = get_social_bot_health_monitor()
    data_quality = get_social_data_quality_monitor()

    system_stats = orchestrator.get_system_stats()
    health = anti_silent.get_health_report()

    return {
        "system_running": system_stats.get("running", False),
        "agents": system_stats,
        "health": {
            "components": health["components"],
            "data_feeds": health["data_feeds"],
            "incidents": health["incidents"],
            "generated_at": health["generated_at"],
        },
        "social_bot_health": health_monitor.get_health_status(),
        "social_data_quality": data_quality.get_status(),
    }


async def _get_kalshi_portfolio() -> Dict[str, Any]:
    """Fetch live Kalshi positions and balance for portfolio summary."""
    try:
        from merid.prediction.agent_grid import get_agent_grid
        from merid.prediction.agent_performance_tracker import get_agent_performance_tracker
        grid = get_agent_grid()
        tracker = get_agent_performance_tracker()
        summary = grid.summary()
        perf = tracker.get_system_summary()

        # Pull portfolio risk snapshot from grid
        pr = summary.get("portfolio_risk", {})
        snapshot = pr.get("latest_snapshot") or pr

        positions = []
        for agent in summary.get("agents", []):
            for ticker in agent.get("active_tickers", []):
                positions.append({
                    "position_id": f"{agent['name']}-{ticker}",
                    "asset_class": "prediction",
                    "symbol": ticker,
                    "quantity": 1,
                    "entry_price": None,
                    "current_price": None,
                    "unrealized_pnl": None,
                    "agent": agent["name"],
                })

        return {
            "portfolio_value": float(snapshot.get("total_notional_usd", 0)),
            "total_pnl": float(perf.get("system_pnl_usd", 0)),
            "daily_pnl": float(snapshot.get("daily_pnl_usd", 0)),
            "allocation": {"prediction_markets": 1.0},
            "positions": positions[:25],
            "venue": "kalshi",
        }
    except Exception as exc:
        logger.debug("_get_kalshi_positions skipped: %s", exc)
        return {"error": str(exc), "venue": "kalshi", "positions": []}


async def _get_kalshi_risk() -> Dict[str, Any]:
    """Fetch live Kalshi risk state from operator endpoint."""
    try:
        from merid.risk.kill_switches import risk_controller
        from merid.prediction.agent_grid import get_agent_grid
        grid = get_agent_grid()
        summary = grid.summary()
        pr = summary.get("portfolio_risk", {})
        snapshot = pr.get("latest_snapshot") or pr

        return {
            "kill_switch_active": bool(pr.get("kill_switch_active", False)),
            "can_trade": risk_controller.can_trade(),
            "kill_reason": risk_controller.get_kill_reason() if not risk_controller.can_trade() else None,
            "daily_pnl_usd": float(snapshot.get("daily_pnl_usd", 0)),
            "total_notional_usd": float(snapshot.get("total_notional_usd", 0)),
            "margin_utilization": float(snapshot.get("margin_utilization_pct", 0)),
            "venue": "kalshi",
        }
    except Exception as exc:
        logger.debug("_get_kalshi_risk skipped: %s", exc)
        return {"error": str(exc), "venue": "kalshi"}


@router.get("/x/portfolio")
async def get_x_portfolio(_: None = Depends(_require_service_token)) -> Dict[str, Any]:
    # Primary: Kalshi live portfolio
    kalshi = await _get_kalshi_portfolio()
    if "error" not in kalshi:
        return kalshi

    # Fallback: cross-domain portfolio engine
    engine = get_portfolio_engine()
    total_value = engine.get_total_value()
    pnl = engine.get_total_pnl()
    allocation = engine.get_allocation_by_class()
    positions = [
        {
            "position_id": pos.position_id,
            "asset_class": pos.asset_class.value,
            "symbol": pos.symbol,
            "quantity": pos.quantity,
            "entry_price": pos.entry_price,
            "current_price": pos.current_price,
            "unrealized_pnl": pos.unrealized_pnl,
        }
        for pos in getattr(engine, 'positions', getattr(engine, '_positions', {})).values()
    ]
    return {
        "portfolio_value": total_value,
        "total_pnl": pnl,
        "allocation": {k.value: v for k, v in allocation.items()},
        "positions": positions[:25],
        "venue": "fallback",
    }


@router.get("/x/risk")
async def get_x_risk(_: None = Depends(_require_service_token)) -> Dict[str, Any]:
    # Primary: Kalshi risk state
    kalshi_risk = await _get_kalshi_risk()
    if "error" not in kalshi_risk:
        social_engine = get_social_aware_quant_engine()
        social_status = social_engine.get_social_risk_status()
        return {**kalshi_risk, "social_kill_switch": social_status}

    # Fallback: automated risk coordinator
    coordinator = get_risk_coordinator()
    status_payload = coordinator.get_comprehensive_risk_status()
    social_engine = get_social_aware_quant_engine()
    social_status = social_engine.get_social_risk_status()
    return {
        "portfolio_risk": status_payload["portfolio_risk"],
        "active_stops": status_payload["active_stops"],
        "monitoring_active": status_payload["monitoring_active"],
        "social_kill_switch": social_status,
        "venue": "fallback",
    }


def _collect_incidents() -> List[Dict[str, Any]]:
    anti_silent = _lazy_anti_silent()
    security_system = _lazy_security_defense()

    incidents = []
    for incident in anti_silent.get_active_incidents():
        incidents.append(
            {
                "source": "anti_silent_failure",
                "incident_id": incident.incident_id,
                "failure_class": incident.failure_class.value,
                "severity": incident.severity,
                "component_id": incident.component_id,
                "description": incident.description,
                "evidence": incident.evidence,
            }
        )

    for sec_incident in getattr(security_system, 'incidents', getattr(security_system, '_incidents', [])):
        if sec_incident.resolved:
            continue
        incidents.append(
            {
                "source": "security_defense",
                "incident_id": sec_incident.incident_id,
                "attack_vector": sec_incident.attack_vector.value,
                "threat_level": sec_incident.threat_level.value,
                "description": sec_incident.description,
                "affected_components": sec_incident.affected_components,
                "evidence": sec_incident.evidence,
            }
        )

    return incidents


@router.get("/x/incidents")
async def get_x_incidents(_: None = Depends(_require_service_token)) -> Dict[str, Any]:
    incidents = _collect_incidents()
    return {"incidents": incidents, "total": len(incidents)}


@router.get("/x/social-intel")
async def get_x_social_intel(_: None = Depends(_require_service_token)) -> Dict[str, Any]:
    engine = get_social_aware_quant_engine()
    risk_status = engine.get_social_risk_status()
    top_assets = engine.get_top_asset_exposure(limit=5)

    return {
        "risk_status": risk_status,
        "top_assets": top_assets,
    }


@router.post("/x/test-post")
async def x_test_post(request: Request) -> Dict[str, Any]:
    """Operator test endpoint — posts a canary tweet via the TwitterAgent singleton.

    No service token required (operator use only, not exposed to public).

    Body (all optional):
        text:     str  — custom tweet text (default: auto-generated canary)
        dry_run:  bool — if true, validates credentials & formatting but does NOT post (default: true)
        force:    bool — bypass the 85-min rate-limit cooldown (default: true for test)
    """
    import time as _time

    body = {}
    try:
        body = await request.json()
    except Exception as exc:
        logger.debug("Failed to parse request body as JSON: %s", exc)

    dry_run = body.get("dry_run", True)
    force   = body.get("force", True)
    text    = body.get("text", "").strip()

    if not text:
        ts = _time.strftime("%Y-%m-%d %H:%M UTC", _time.gmtime())
        text = f"🤖 MERID canary ping — swarm online [{ts}] #Kalshi #PredictionMarkets"

    if len(text) > 280:
        raise HTTPException(400, f"Tweet too long ({len(text)}/280 chars)")

    from agents.twitter_agent import get_twitter_agent
    agent = get_twitter_agent()

    status = {
        "enabled":           agent.enabled,
        "has_client":        agent.client is not None,
        "daily_count":       agent._daily_tweet_count,
        "daily_limit":       agent._daily_tweet_limit,
        "disabled_reason":   agent._disabled_reason,
        "last_post_ago_s":   round(_time.time() - agent.last_post_time, 1),
        "text":              text,
        "dry_run":           dry_run,
    }

    if dry_run:
        logger.info("X test-post DRY RUN: %s", text[:60])
        return {"success": True, "dry_run": True, "status": status}

    if not agent.enabled:
        reason = agent._disabled_reason or "credentials missing or tweepy not installed"
        raise HTTPException(503, f"Twitter agent disabled: {reason}")

    import asyncio
    result = await asyncio.to_thread(agent.post_tweet, text, force)

    if result:
        logger.info("X test-post LIVE OK: tweet_id=%s", result.tweet_id)
        return {
            "success":  True,
            "dry_run":  False,
            "tweet_id": result.tweet_id,
            "text":     result.text,
            "status":   status,
        }
    else:
        raise HTTPException(
            429 if agent.enabled else 503,
            "Tweet not posted — rate-limited, daily cap reached, or agent disabled. "
            "Pass force=true to override rate limit.",
        )


@router.get("/x/help")
async def get_x_help(_: None = Depends(_require_service_token)) -> Dict[str, Any]:
    commands = get_default_commands()
    return {
        "commands": [
            {
                "name": cmd.name,
                "description": cmd.description,
                "required_role": cmd.required_role.value,
                "type": cmd.command_type.value,
                "risk_level": cmd.risk_level,
            }
            for cmd in commands.values()
        ]
    }


@router.post("/x/post")
async def post_to_x(
    request: Request,
    _: None = Depends(_require_service_token),
) -> Dict[str, Any]:
    """Post a tweet via the X API (v2 manage tweets endpoint).

    Body:
        text: str — tweet content (max 280 chars)
        reply_to: Optional[str] — tweet ID to reply to

    Requires X_API_KEY, X_API_SECRET, X_ACCESS_TOKEN, X_ACCESS_SECRET
    env vars for OAuth 1.0a user-context posting.

    Rate limit: X Free tier allows 1,500 tweets/month (~50/day).
    The endpoint enforces a 2-minute cooldown between posts to stay
    well under the limit and avoid suspension.
    """
    import os, time as _time, hmac, hashlib, base64, urllib.parse, uuid

    body = await request.json()
    text = body.get("text", "").strip()
    if not text:
        raise HTTPException(400, "text is required")
    if len(text) > 280:
        raise HTTPException(400, f"Tweet too long ({len(text)}/280)")

    # Cooldown: 2 min between posts
    last_post_ts = getattr(post_to_x, "_last_post_ts", 0.0)
    now = _time.time()
    if now - last_post_ts < 120:
        remaining = int(120 - (now - last_post_ts))
        raise HTTPException(429, f"Post cooldown: {remaining}s remaining")

    # Load credentials from centralized settings (env -> settings -> here)
    from merid.settings import settings as _settings
    
    api_key = _settings.X_API_KEY or os.getenv("X_API_KEY")
    api_secret = _settings.X_API_SECRET or os.getenv("X_API_SECRET")
    access_token = _settings.X_ACCESS_TOKEN or os.getenv("X_ACCESS_TOKEN")
    access_secret = _settings.X_ACCESS_TOKEN_SECRET or os.getenv("X_ACCESS_SECRET")

    if not all([api_key, api_secret, access_token, access_secret]):
        raise HTTPException(503, "X posting credentials not configured (need X_API_KEY, X_API_SECRET, X_ACCESS_TOKEN, X_ACCESS_TOKEN_SECRET)")

    # OAuth 1.0a signature for POST /2/tweets
    import httpx as _httpx

    url = "https://api.twitter.com/2/tweets"
    oauth_params = {
        "oauth_consumer_key": api_key,
        "oauth_nonce": uuid.uuid4().hex,
        "oauth_signature_method": "HMAC-SHA1",
        "oauth_timestamp": str(int(now)),
        "oauth_token": access_token,
        "oauth_version": "1.0",
    }

    # Build signature base string
    params_str = "&".join(f"{urllib.parse.quote(k, safe='')}={urllib.parse.quote(v, safe='')}"
                          for k, v in sorted(oauth_params.items()))
    base_string = f"POST&{urllib.parse.quote(url, safe='')}&{urllib.parse.quote(params_str, safe='')}"
    signing_key = f"{urllib.parse.quote(api_secret, safe='')}&{urllib.parse.quote(access_secret, safe='')}"
    signature = base64.b64encode(hmac.new(signing_key.encode(), base_string.encode(), hashlib.sha1).digest()).decode()
    oauth_params["oauth_signature"] = signature

    auth_header = "OAuth " + ", ".join(
        f'{urllib.parse.quote(k, safe="")}="{urllib.parse.quote(v, safe="")}"'
        for k, v in sorted(oauth_params.items())
    )

    payload: Dict[str, Any] = {"text": text}
    reply_to = body.get("reply_to")
    if reply_to:
        payload["reply"] = {"in_reply_to_tweet_id": reply_to}

    try:
        async with _httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(url, json=payload, headers={
                "Authorization": auth_header,
                "Content-Type": "application/json",
            })
            if resp.status_code == 429:
                logger.warning("X API post rate limited (429)")
                raise HTTPException(429, "X API rate limited — try again later")
            resp.raise_for_status()
            result = resp.json()
            post_to_x._last_post_ts = _time.time()  # type: ignore[attr-defined]
            tweet_id = result.get("data", {}).get("id")
            logger.info("Posted tweet %s: %s", tweet_id, text[:50])
            return {"success": True, "tweet_id": tweet_id, "text": text}
    except _httpx.HTTPStatusError as exc:
        logger.error("X post failed (%s): %s", exc.response.status_code, exc.response.text[:200])
        raise HTTPException(exc.response.status_code, f"X API error: {exc.response.text[:200]}")
    except Exception as exc:
        logger.error("X post exception: %s", exc)
        raise HTTPException(500, str(exc))
