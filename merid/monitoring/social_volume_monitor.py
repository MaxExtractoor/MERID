"""
Real-Time Social Volume Monitoring with Alert System

Monitors social media volume spikes across Twitter, Reddit, and Telegram
for energy and crypto markets. Generates alerts for momentum shifts.

Octobot-style Reddit evaluator integrated for community engagement tracking.
"""

from __future__ import annotations

import asyncio
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any, Callable

from utils.logger import get_logger

logger = get_logger("merid.monitoring.social_volume_monitor")


@dataclass
class VolumeAlert:
    """Alert for social volume spike."""
    asset: str
    platform: str  # twitter, reddit, telegram
    current_volume: int
    baseline_volume: float
    spike_ratio: float  # current / baseline
    timestamp: datetime
    alert_id: str
    metadata: Dict[str, Any]


class SocialVolumeMonitor:
    """
    Real-time social volume monitoring with spike detection.

    Tracks volume baselines per asset/platform and generates alerts
    when current volume exceeds threshold (default 3× baseline).

    Integration with Telegram/Discord for manual review alerts.
    """

    def __init__(
        self,
        alert_threshold: float = 3.0,  # 3× baseline triggers alert
        baseline_window_seconds: float = 3600.0,  # 1h rolling baseline
        min_baseline_samples: int = 5,
    ):
        self.alert_threshold = alert_threshold
        self.baseline_window = baseline_window_seconds
        self.min_samples = min_baseline_samples

        # Baselines: {asset: {platform: rolling_avg}}
        self._baseline_volume: Dict[str, Dict[str, float]] = defaultdict(
            lambda: defaultdict(float)
        )

        # Recent volume measurements: {asset: {platform: [(timestamp, volume)]}}
        self._volume_history: Dict[str, Dict[str, List[tuple]]] = defaultdict(
            lambda: defaultdict(list)
        )

        # Alert history
        self._alerts: List[VolumeAlert] = []
        self._last_alert_time: Dict[str, float] = {}  # Debounce alerts

        # Alert callbacks
        self._alert_callbacks: List[Callable[[VolumeAlert], None]] = []

    def update_volume(self, asset: str, platform: str, volume: int) -> Optional[VolumeAlert]:
        """
        Update volume measurement and check for spikes.

        Args:
            asset: Asset symbol (BTC, ETH, ERCOT, etc.)
            platform: Platform name (twitter, reddit, telegram)
            volume: Current volume (post count, tweet count, etc.)

        Returns:
            VolumeAlert if spike detected, None otherwise
        """
        now = time.time()
        timestamp = datetime.now(timezone.utc)

        # Add to history
        history = self._volume_history[asset][platform]
        history.append((now, volume))

        # Clean old history
        cutoff = now - self.baseline_window
        history[:] = [(t, v) for t, v in history if t >= cutoff]

        # Compute baseline (rolling average)
        if len(history) < self.min_samples:
            # Not enough samples yet
            return None

        baseline = sum(v for _, v in history) / len(history)
        self._baseline_volume[asset][platform] = baseline

        # Check for spike
        if volume <= baseline * self.alert_threshold:
            # No spike
            return None

        # Spike detected
        spike_ratio = volume / baseline if baseline > 0 else float("inf")

        # Debounce: don't alert more than once per 10 minutes for same asset/platform
        alert_key = f"{asset}:{platform}"
        last_alert = self._last_alert_time.get(alert_key, 0)
        if now - last_alert < 600:  # 10 min debounce
            logger.debug(f"Volume spike debounced for {alert_key}")
            return None

        # Generate alert
        alert = VolumeAlert(
            asset=asset,
            platform=platform,
            current_volume=volume,
            baseline_volume=baseline,
            spike_ratio=spike_ratio,
            timestamp=timestamp,
            alert_id=f"vol-{asset}-{platform}-{int(now)}",
            metadata={
                "history_samples": len(history),
                "window_seconds": self.baseline_window,
                "threshold": self.alert_threshold,
            },
        )

        self._alerts.append(alert)
        self._last_alert_time[alert_key] = now

        logger.warning(
            f"Social volume spike: {asset} on {platform} | "
            f"current={volume} baseline={baseline:.1f} ratio={spike_ratio:.2f}×"
        )

        # Notify callbacks
        for callback in self._alert_callbacks:
            try:
                callback(alert)
            except Exception as exc:
                logger.debug(f"Alert callback error: {exc}")

        return alert

    async def check_all_platforms(self, asset: str) -> List[VolumeAlert]:
        """
        Check all platforms for volume spikes for an asset.

        Args:
            asset: Asset symbol

        Returns:
            List of generated alerts
        """
        alerts = []

        # Check Twitter
        try:
            from merid.sentiment.twitter_fetcher import get_twitter_sentiment_service
            twitter = get_twitter_sentiment_service()
            result = twitter.get_sentiment(asset, minutes=15, use_cache=True)

            alert = self.update_volume(asset, "twitter", result.volume)
            if alert:
                alerts.append(alert)

        except Exception as exc:
            logger.debug(f"Twitter volume check failed for {asset}: {exc}")

        # Check Reddit
        try:
            from merid.sentiment.reddit_scraper import get_reddit_sentiment_service
            reddit = get_reddit_sentiment_service()
            result = reddit.get_sentiment(asset, time_filter="hour", use_cache=True)

            alert = self.update_volume(asset, "reddit", result.volume)
            if alert:
                alerts.append(alert)

        except Exception as exc:
            logger.debug(f"Reddit volume check failed for {asset}: {exc}")

        # Telegram volume would require scraping implementation
        # Currently Telegram agent only posts, doesn't scrape
        # Future enhancement: integrate Telegram scraper

        return alerts

    def register_alert_callback(self, callback: Callable[[VolumeAlert], None]) -> None:
        """
        Register callback for volume alerts.

        Callback receives VolumeAlert when spike detected.

        Example:
            async def telegram_alerter(alert: VolumeAlert):
                from agents.telegram_agent import TelegramAgent
                agent = TelegramAgent()
                await agent.send_alert(
                    f"Volume spike: {alert.asset} on {alert.platform} "
                    f"({alert.spike_ratio:.1f}× baseline)"
                )

            monitor.register_alert_callback(telegram_alerter)
        """
        self._alert_callbacks.append(callback)

    def get_recent_alerts(self, limit: int = 50) -> List[VolumeAlert]:
        """Get recent volume alerts."""
        return self._alerts[-limit:]

    def get_baseline(self, asset: str, platform: str) -> float:
        """Get current baseline volume for asset/platform."""
        return self._baseline_volume.get(asset, {}).get(platform, 0.0)

    def get_metrics(self) -> Dict[str, Any]:
        """Get monitor metrics."""
        return {
            "total_alerts": len(self._alerts),
            "assets_tracked": len(self._baseline_volume),
            "platforms_tracked": sum(len(p) for p in self._baseline_volume.values()),
            "alert_callbacks": len(self._alert_callbacks),
            "recent_alerts": [
                {
                    "asset": a.asset,
                    "platform": a.platform,
                    "spike_ratio": round(a.spike_ratio, 2),
                    "timestamp": a.timestamp.isoformat(),
                }
                for a in self._alerts[-10:]
            ],
        }


# ── Octobot-style Reddit Evaluator ────────────────────────────────────

@dataclass
class RedditEngagementMetrics:
    """Engagement metrics for Reddit posts."""
    subreddit: str
    post_count: int
    avg_upvotes: float
    avg_comments: float
    upvote_ratio: float
    total_engagement: int
    top_keywords: List[str]
    timestamp: datetime


class RedditEvaluator:
    """
    Octobot-style Reddit community engagement evaluator.

    Analyzes subreddit engagement patterns to identify:
    - Community sentiment shifts
    - High-engagement topics
    - Organic vs brigaded discussions
    """

    def __init__(self):
        self._engagement_history: Dict[str, List[RedditEngagementMetrics]] = defaultdict(list)

    async def evaluate_subreddit(
        self,
        subreddit: str,
        asset: str,
        time_filter: str = "hour",
    ) -> Optional[RedditEngagementMetrics]:
        """
        Evaluate engagement for a subreddit on an asset.

        Args:
            subreddit: Subreddit name (without r/)
            asset: Asset symbol
            time_filter: Time window

        Returns:
            RedditEngagementMetrics or None
        """
        try:
            from merid.sentiment.reddit_scraper import get_reddit_sentiment_service
            reddit = get_reddit_sentiment_service()

            # Fetch posts
            posts = reddit.fetch_posts_for_asset(
                asset=asset,
                subreddits=[subreddit],
                limit_per_sub=50,
                time_filter=time_filter,
            )

            if not posts:
                return None

            # Calculate engagement metrics
            avg_upvotes = sum(p.score for p in posts) / len(posts)
            avg_comments = sum(p.num_comments for p in posts) / len(posts)
            avg_ratio = sum(p.upvote_ratio for p in posts) / len(posts)
            total_engagement = sum(p.score + p.num_comments for p in posts)

            # Extract top keywords (simple frequency analysis)
            from collections import Counter
            all_words = []
            for p in posts:
                words = (p.title + " " + p.selftext).lower().split()
                all_words.extend([w for w in words if len(w) > 4])

            top_keywords = [word for word, _ in Counter(all_words).most_common(10)]

            metrics = RedditEngagementMetrics(
                subreddit=subreddit,
                post_count=len(posts),
                avg_upvotes=avg_upvotes,
                avg_comments=avg_comments,
                upvote_ratio=avg_ratio,
                total_engagement=total_engagement,
                top_keywords=top_keywords,
                timestamp=datetime.now(timezone.utc),
            )

            self._engagement_history[subreddit].append(metrics)

            logger.info(
                f"Reddit engagement: r/{subreddit} {asset} | "
                f"posts={len(posts)} avg_upvotes={avg_upvotes:.1f} "
                f"engagement={total_engagement}"
            )

            return metrics

        except Exception as exc:
            logger.warning(f"Reddit evaluation failed for r/{subreddit}: {exc}")
            return None

    def detect_brigade(self, subreddit: str, lookback_count: int = 5) -> bool:
        """
        Detect potential brigading (coordinated voting).

        Looks for unusual spikes in engagement compared to historical patterns.

        Args:
            subreddit: Subreddit to check
            lookback_count: Number of historical samples to compare

        Returns:
            True if brigading suspected
        """
        history = self._engagement_history.get(subreddit, [])

        if len(history) < lookback_count + 1:
            return False

        # Get recent and historical metrics
        recent = history[-1]
        historical = history[-(lookback_count + 1):-1]

        avg_historical_engagement = sum(h.total_engagement for h in historical) / len(historical)

        # Brigade if engagement 5× higher than baseline
        if recent.total_engagement > avg_historical_engagement * 5:
            logger.warning(
                f"Potential brigade detected in r/{subreddit}: "
                f"engagement={recent.total_engagement} vs baseline={avg_historical_engagement:.1f}"
            )
            return True

        return False


# ── Singletons ─────────────────────────────────────────────────────────

_social_volume_monitor: Optional[SocialVolumeMonitor] = None
_reddit_evaluator: Optional[RedditEvaluator] = None


def get_social_volume_monitor() -> SocialVolumeMonitor:
    """Get or create social volume monitor singleton."""
    global _social_volume_monitor
    if _social_volume_monitor is None:
        _social_volume_monitor = SocialVolumeMonitor()
    return _social_volume_monitor


def get_reddit_evaluator() -> RedditEvaluator:
    """Get or create Reddit evaluator singleton."""
    global _reddit_evaluator
    if _reddit_evaluator is None:
        _reddit_evaluator = RedditEvaluator()
    return _reddit_evaluator


# ── Convenience Functions ──────────────────────────────────────────────

async def check_social_volume_for_assets(assets: List[str]) -> List[VolumeAlert]:
    """
    Check social volume for multiple assets.

    Args:
        assets: List of asset symbols

    Returns:
        List of generated volume alerts
    """
    monitor = get_social_volume_monitor()
    all_alerts = []

    for asset in assets:
        alerts = await monitor.check_all_platforms(asset)
        all_alerts.extend(alerts)

    return all_alerts


async def send_volume_alert_to_telegram(alert: VolumeAlert) -> bool:
    """
    Send volume alert to Telegram.

    Args:
        alert: VolumeAlert to send

    Returns:
        True if successful
    """
    try:
        from agents.telegram_agent import TelegramAgent

        agent = TelegramAgent()

        message = (
            f"🔔 Social Volume Spike Alert\n\n"
            f"Asset: {alert.asset}\n"
            f"Platform: {alert.platform}\n"
            f"Current Volume: {alert.current_volume}\n"
            f"Baseline: {alert.baseline_volume:.1f}\n"
            f"Spike Ratio: {alert.spike_ratio:.2f}×\n"
            f"Time: {alert.timestamp.strftime('%Y-%m-%d %H:%M UTC')}"
        )

        await agent.send_alert(message, severity="warning")
        return True

    except Exception as exc:
        logger.warning(f"Failed to send Telegram alert: {exc}")
        return False
