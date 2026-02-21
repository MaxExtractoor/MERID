"""Sports odds API client — fetches lines from aggregators (TheOddsAPI etc.).

Supports:
  - Pre-game and in-play odds
  - Multiple sportsbooks per event
  - Normalized implied probabilities with vig removal
  - Consensus and sharp-book views
  - Rate limiting and caching

Configure via env:
  MERID_ODDS_API_KEY  — TheOddsAPI key (or similar)
  MERID_ODDS_API_URL  — base URL (default: https://api.the-odds-api.com/v4)
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from utils.logger import get_logger

from merid.betting.models import (
    BettingEvent,
    BettingOutcome,
    BookOdds,
    OddsSnapshot,
    american_to_decimal,
    decimal_to_implied_prob,
    remove_vig,
)

logger = get_logger("merid.betting.odds_client")

# Books considered "sharp" — better at pricing, used for sharp_prob
SHARP_BOOKS = {"pinnacle", "circa", "betcris", "bookmaker"}

# Default sports to track
DEFAULT_SPORTS = [
    "americanfootball_nfl",
    "basketball_nba",
    "baseball_mlb",
    "icehockey_nhl",
    "soccer_epl",
    "soccer_usa_mls",
    "mma_mixed_martial_arts",
    "basketball_ncaab",
    "americanfootball_ncaaf",
]

SPORT_DISPLAY = {
    "americanfootball_nfl": ("nfl", "NFL"),
    "basketball_nba": ("nba", "NBA"),
    "baseball_mlb": ("mlb", "MLB"),
    "icehockey_nhl": ("nhl", "NHL"),
    "soccer_epl": ("soccer", "Premier League"),
    "soccer_usa_mls": ("soccer", "MLS"),
    "mma_mixed_martial_arts": ("mma", "MMA"),
    "basketball_ncaab": ("ncaab", "NCAAB"),
    "americanfootball_ncaaf": ("ncaaf", "NCAAF"),
}


@dataclass
class OddsAPIClient:
    """Fetches and normalizes sports odds from aggregator APIs.

    In production, calls TheOddsAPI (or similar).
    Falls back to synthetic data for development/testing.
    """

    api_key: str = ""
    base_url: str = "https://api.the-odds-api.com/v4"
    sports: List[str] = field(default_factory=lambda: list(DEFAULT_SPORTS))
    regions: str = "us"
    markets: str = "h2h,spreads,totals"
    odds_format: str = "american"

    # Rate limiting
    _last_request_ts: float = 0.0
    _min_interval: float = 1.0  # min seconds between requests

    # Cache
    _cache: Dict[str, Tuple[float, Any]] = field(default_factory=dict)
    _cache_ttl: float = 30.0  # seconds

    def __post_init__(self):
        if not self.api_key:
            self.api_key = os.environ.get("MERID_ODDS_API_KEY", "")
        if not self.base_url:
            self.base_url = os.environ.get(
                "MERID_ODDS_API_URL", "https://api.the-odds-api.com/v4"
            )

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key)

    def fetch_events(self, sport: Optional[str] = None) -> List[BettingEvent]:
        """Fetch upcoming events, either from API or synthetic fallback."""
        if self.is_configured:
            return self._fetch_events_live(sport)
        return self._synthetic_events(sport)

    def fetch_odds(self, event_id: str, market_type: str = "moneyline") -> Optional[OddsSnapshot]:
        """Fetch odds snapshot for a specific event."""
        if self.is_configured:
            return self._fetch_odds_live(event_id, market_type)
        return self._synthetic_odds(event_id, market_type)

    def fetch_all_odds(self, sport: Optional[str] = None) -> List[Tuple[BettingEvent, OddsSnapshot]]:
        """Fetch events + odds in one pass (for pre-game polling)."""
        events = self.fetch_events(sport)
        results = []
        for ev in events:
            snap = self.fetch_odds(ev.id)
            if snap:
                results.append((ev, snap))
        return results

    # ── Live API calls ────────────────────────────────────────────────

    def _fetch_events_live(self, sport: Optional[str] = None) -> List[BettingEvent]:
        """Call the real odds API for events."""
        try:
            import requests
        except ImportError:
            logger.warning("requests library not available, using synthetic data")
            return self._synthetic_events(sport)

        sports_to_fetch = [sport] if sport else self.sports
        events = []

        for sp in sports_to_fetch:
            cache_key = f"events:{sp}"
            cached = self._get_cache(cache_key)
            if cached is not None:
                events.extend(cached)
                continue

            self._rate_limit()
            try:
                url = f"{self.base_url}/sports/{sp}/odds"
                resp = requests.get(url, params={
                    "apiKey": self.api_key,
                    "regions": self.regions,
                    "markets": "h2h",
                    "oddsFormat": self.odds_format,
                }, timeout=10)

                if resp.status_code == 200:
                    data = resp.json()
                    sport_code, league = SPORT_DISPLAY.get(sp, (sp, sp.upper()))
                    batch = []
                    for game in data:
                        ev = BettingEvent(
                            id=game.get("id", ""),
                            sport=sport_code,
                            league=league,
                            title=f"{game.get('away_team', '')} @ {game.get('home_team', '')}",
                            home_team=game.get("home_team", ""),
                            away_team=game.get("away_team", ""),
                            start_time=_parse_iso(game.get("commence_time", "")),
                            state="live" if game.get("is_live") else "pre",
                            outcomes=[
                                BettingOutcome(id=f"{game['id']}-h", name=game.get("home_team", ""), market_type="moneyline"),
                                BettingOutcome(id=f"{game['id']}-a", name=game.get("away_team", ""), market_type="moneyline"),
                            ],
                        )
                        batch.append(ev)
                    self._set_cache(cache_key, batch)
                    events.extend(batch)
                else:
                    logger.warning(f"Odds API returned {resp.status_code} for {sp}")
            except Exception as exc:
                logger.warning(f"Odds API error for {sp}: {exc}")

        return events

    def _fetch_odds_live(self, event_id: str, market_type: str) -> Optional[OddsSnapshot]:
        """Fetch live odds for one event from the API."""
        # For now, odds are bundled with events in TheOddsAPI format.
        # This would be extended for per-event odds fetching.
        return self._synthetic_odds(event_id, market_type)

    # ── Synthetic / development data ──────────────────────────────────

    def _synthetic_events(self, sport: Optional[str] = None) -> List[BettingEvent]:
        """Generate realistic synthetic events for development."""
        now = time.time()
        events = [
            BettingEvent(
                id="nfl-sb-2026", sport="nfl", league="NFL",
                title="Kansas City Chiefs @ San Francisco 49ers",
                home_team="San Francisco 49ers", away_team="Kansas City Chiefs",
                start_time=now + 86400 * 7, state="pre",
                outcomes=[
                    BettingOutcome(id="nfl-sb-h", name="San Francisco 49ers", market_type="moneyline"),
                    BettingOutcome(id="nfl-sb-a", name="Kansas City Chiefs", market_type="moneyline"),
                ],
                market_types=["moneyline", "spread", "total"],
            ),
            BettingEvent(
                id="nba-lal-bos", sport="nba", league="NBA",
                title="Boston Celtics @ Los Angeles Lakers",
                home_team="Los Angeles Lakers", away_team="Boston Celtics",
                start_time=now + 3600 * 4, state="pre",
                outcomes=[
                    BettingOutcome(id="nba-lb-h", name="Los Angeles Lakers", market_type="moneyline"),
                    BettingOutcome(id="nba-lb-a", name="Boston Celtics", market_type="moneyline"),
                ],
                market_types=["moneyline", "spread", "total"],
            ),
            BettingEvent(
                id="nba-gsw-den", sport="nba", league="NBA",
                title="Denver Nuggets @ Golden State Warriors",
                home_team="Golden State Warriors", away_team="Denver Nuggets",
                start_time=now - 3600, state="live",
                score_home=67, score_away=72, period="Q3", clock="4:23",
                outcomes=[
                    BettingOutcome(id="nba-gd-h", name="Golden State Warriors", market_type="moneyline"),
                    BettingOutcome(id="nba-gd-a", name="Denver Nuggets", market_type="moneyline"),
                ],
                market_types=["moneyline", "spread", "total"],
            ),
            BettingEvent(
                id="mlb-nyy-bos", sport="mlb", league="MLB",
                title="New York Yankees @ Boston Red Sox",
                home_team="Boston Red Sox", away_team="New York Yankees",
                start_time=now + 86400 * 2, state="pre",
                outcomes=[
                    BettingOutcome(id="mlb-yb-h", name="Boston Red Sox", market_type="moneyline"),
                    BettingOutcome(id="mlb-yb-a", name="New York Yankees", market_type="moneyline"),
                ],
            ),
            BettingEvent(
                id="pol-2028-pres", sport="politics", league="US Politics",
                title="2028 Presidential Election Winner",
                start_time=now + 86400 * 365, state="pre",
                outcomes=[
                    BettingOutcome(id="pol-dem", name="Democrat Nominee", market_type="futures"),
                    BettingOutcome(id="pol-rep", name="Republican Nominee", market_type="futures"),
                    BettingOutcome(id="pol-oth", name="Other", market_type="futures"),
                ],
                kalshi_event_id="PRES-2028",
                market_types=["futures"],
            ),
            BettingEvent(
                id="crypto-btc-150k", sport="crypto", league="Crypto",
                title="Bitcoin above $150K by end of 2026",
                start_time=now + 86400 * 300, state="pre",
                outcomes=[
                    BettingOutcome(id="btc-yes", name="Yes", market_type="yes_no"),
                    BettingOutcome(id="btc-no", name="No", market_type="yes_no"),
                ],
                kalshi_event_id="BTCUSD-26DEC-150K",
                market_types=["yes_no"],
            ),
        ]

        if sport:
            events = [e for e in events if e.sport == sport]
        return events

    def _synthetic_odds(self, event_id: str, market_type: str) -> Optional[OddsSnapshot]:
        """Generate synthetic odds for an event."""
        # Realistic odds for each synthetic event
        odds_map: Dict[str, List[Tuple[str, str, int, int]]] = {
            # event_id → [(book, outcome_id, american_home, american_away), ...]
            "nfl-sb-2026": [
                ("draftkings", "nfl-sb-h", -110, -110),
                ("fanduel", "nfl-sb-h", -105, -115),
                ("betmgm", "nfl-sb-h", -108, -112),
                ("caesars", "nfl-sb-h", -110, -110),
                ("pinnacle", "nfl-sb-h", -104, -106),
            ],
            "nba-lal-bos": [
                ("draftkings", "nba-lb-h", +150, -180),
                ("fanduel", "nba-lb-h", +155, -185),
                ("betmgm", "nba-lb-h", +145, -175),
                ("pinnacle", "nba-lb-h", +152, -168),
            ],
            "nba-gsw-den": [
                ("draftkings", "nba-gd-h", +120, -145),
                ("fanduel", "nba-gd-h", +125, -150),
                ("pinnacle", "nba-gd-h", +128, -142),
            ],
            "mlb-nyy-bos": [
                ("draftkings", "mlb-yb-h", -120, +100),
                ("fanduel", "mlb-yb-h", -115, -105),
                ("pinnacle", "mlb-yb-h", -112, -102),
            ],
            "pol-2028-pres": [
                ("kalshi", "pol-dem", -110, -110),
            ],
            "crypto-btc-150k": [
                ("kalshi", "btc-yes", +120, -140),
            ],
        }

        entries = odds_map.get(event_id)
        if not entries:
            return None

        book_odds_list: List[BookOdds] = []
        # Build odds per outcome
        outcome_ids = set()
        for book, base_oid, am_h, am_a in entries:
            # Home outcome
            h_oid = base_oid
            a_suffix = base_oid.rsplit("-", 1)[0] + "-" + ("a" if base_oid.endswith("-h") else "h")
            a_oid = a_suffix

            outcome_ids.add(h_oid)
            outcome_ids.add(a_oid)

            bo_h = BookOdds(book=book, outcome_id=h_oid, american_odds=am_h)
            bo_a = BookOdds(book=book, outcome_id=a_oid, american_odds=am_a)
            book_odds_list.extend([bo_h, bo_a])

        # Compute consensus and sharp probs with vig removal
        snap = OddsSnapshot(
            event_id=event_id, market_type=market_type, book_odds=book_odds_list,
        )
        snap.consensus_prob, snap.sharp_prob, snap.best_odds = _compute_consensus(book_odds_list, list(outcome_ids))
        return snap

    # ── Internal helpers ──────────────────────────────────────────────

    def _rate_limit(self) -> None:
        now = time.time()
        elapsed = now - self._last_request_ts
        if elapsed < self._min_interval:
            import time as _time
            _time.sleep(self._min_interval - elapsed)
        self._last_request_ts = time.time()

    def _get_cache(self, key: str) -> Any:
        if key in self._cache:
            ts, val = self._cache[key]
            if time.time() - ts < self._cache_ttl:
                return val
            del self._cache[key]
        return None

    def _set_cache(self, key: str, val: Any) -> None:
        self._cache[key] = (time.time(), val)


def _compute_consensus(
    book_odds: List[BookOdds],
    outcome_ids: List[str],
) -> Tuple[Dict[str, float], Dict[str, float], Dict[str, BookOdds]]:
    """Compute consensus prob, sharp prob, and best odds from a list of BookOdds."""
    from collections import defaultdict

    # Group by outcome
    by_outcome: Dict[str, List[BookOdds]] = defaultdict(list)
    for bo in book_odds:
        by_outcome[bo.outcome_id].append(bo)

    consensus: Dict[str, float] = {}
    sharp: Dict[str, float] = {}
    best: Dict[str, BookOdds] = {}

    # For each outcome, compute average implied prob across books
    for oid in outcome_ids:
        odds_list = by_outcome.get(oid, [])
        if not odds_list:
            consensus[oid] = 0.5
            continue

        raw_probs = [decimal_to_implied_prob(o.decimal_odds) for o in odds_list]
        avg_raw = sum(raw_probs) / len(raw_probs) if raw_probs else 0.5
        consensus[oid] = avg_raw

        # Sharp books
        sharp_odds = [o for o in odds_list if o.book in SHARP_BOOKS]
        if sharp_odds:
            sharp_raw = [decimal_to_implied_prob(o.decimal_odds) for o in sharp_odds]
            sharp[oid] = sum(sharp_raw) / len(sharp_raw)

        # Best odds (highest decimal = best for bettor)
        best_bo = max(odds_list, key=lambda o: o.decimal_odds)
        best[oid] = best_bo

    # Remove vig from consensus
    if consensus:
        total = sum(consensus.values())
        if total > 0:
            for oid in consensus:
                consensus[oid] = round(consensus[oid] / total, 4)

    # Remove vig from sharp
    if sharp:
        total = sum(sharp.values())
        if total > 0:
            for oid in sharp:
                sharp[oid] = round(sharp[oid] / total, 4)

    # Set implied_prob on best odds (vig-removed)
    for oid, bo in best.items():
        bo.implied_prob = consensus.get(oid, bo.raw_implied_prob)

    return consensus, sharp, best


def _parse_iso(iso_str: str) -> float:
    """Parse ISO 8601 to unix epoch. Returns 0 on failure."""
    if not iso_str:
        return 0.0
    try:
        from datetime import datetime, timezone
        if iso_str.endswith("Z"):
            iso_str = iso_str[:-1] + "+00:00"
        dt = datetime.fromisoformat(iso_str)
        return dt.timestamp()
    except Exception as _e:
        logger.debug("_parse_iso_to_ts failed for %r: %s", iso_str, _e)
        return 0.0


# ── Singleton ─────────────────────────────────────────────────────────

_client: Optional[OddsAPIClient] = None


def get_odds_client() -> OddsAPIClient:
    global _client
    if _client is None:
        _client = OddsAPIClient()
    return _client
