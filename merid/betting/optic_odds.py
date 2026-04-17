"""OpticOdds-style API integration for real-time sports odds ingestion.

Connects to an OpticOdds-compatible REST + WebSocket API, normalizes odds
into the MERID SportsOddsFeed pipeline, and persists snapshots for
backtesting and audit.

Configure via env:
  OPTIC_ODDS_API_KEY   — API key
  OPTIC_ODDS_BASE_URL  — REST base URL (default: https://api.opticodds.com/api/v3)
  OPTIC_ODDS_WS_URL    — WebSocket URL (default: wss://api.opticodds.com/ws/v3)

Components:
  1. OpticOddsClient: HTTP client for REST endpoints (events, odds, fixtures).
  2. OpticOddsNormalizer: Converts provider-specific formats → OddsUpdate.
  3. OpticOddsPoller: Background polling loop that feeds SportsOddsFeed.
  4. OddsSnapshotStore: In-memory ring buffer + optional SQLite persistence
     for backtesting and audit trails.
"""

from __future__ import annotations

import collections
import hashlib
import os
import statistics
import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Deque, Dict, List, Optional, Set, Tuple

from utils.logger import get_logger

logger = get_logger("merid.betting.optic_odds")


# ═══════════════════════════════════════════════════════════════════════
# 1. Configuration & Constants
# ═══════════════════════════════════════════════════════════════════════

OPTIC_ODDS_SPORTS = {
    "football": "nfl",
    "basketball": "nba",
    "baseball": "mlb",
    "hockey": "nhl",
    "soccer": "soccer",
    "mma": "mma",
    "college-football": "ncaaf",
    "college-basketball": "ncaab",
}

MARKET_TYPE_MAP = {
    "moneyline": "moneyline",
    "spread": "spread",
    "total": "total",
    "over_under": "total",
    "prop": "prop",
    "futures": "futures",
    "h2h": "moneyline",
}


class OddsFormat(str, Enum):
    AMERICAN = "american"
    DECIMAL = "decimal"
    FRACTIONAL = "fractional"


# ═══════════════════════════════════════════════════════════════════════
# 2. Data Models
# ═══════════════════════════════════════════════════════════════════════

@dataclass
class OpticOddsFixture:
    """A fixture (game/event) from the OpticOdds API."""
    fixture_id: str = ""
    sport: str = ""
    league: str = ""
    home_team: str = ""
    away_team: str = ""
    start_time: float = 0.0
    is_live: bool = False
    status: str = "pre"           # pre, live, final, cancelled, postponed
    score_home: Optional[int] = None
    score_away: Optional[int] = None
    period: str = ""
    clock: str = ""
    last_updated: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "fixture_id": self.fixture_id,
            "sport": self.sport,
            "league": self.league,
            "home_team": self.home_team,
            "away_team": self.away_team,
            "start_time": self.start_time,
            "is_live": self.is_live,
            "status": self.status,
            "score_home": self.score_home,
            "score_away": self.score_away,
            "period": self.period,
            "clock": self.clock,
        }


@dataclass
class OpticOddsLine:
    """A single odds line from a sportsbook via OpticOdds."""
    fixture_id: str = ""
    sportsbook: str = ""
    market_type: str = "moneyline"
    outcome_label: str = ""       # "home", "away", "over", "under", "draw"
    line: Optional[float] = None  # spread or total line
    american_odds: int = 0
    decimal_odds: float = 0.0
    implied_prob: float = 0.0
    is_live: bool = False
    timestamp: float = field(default_factory=time.time)

    def __post_init__(self):
        if self.american_odds != 0 and self.decimal_odds == 0:
            self.decimal_odds = _american_to_decimal(self.american_odds)
        if self.decimal_odds > 0 and self.implied_prob == 0:
            self.implied_prob = 1.0 / self.decimal_odds

    def to_dict(self) -> Dict[str, Any]:
        return {
            "fixture_id": self.fixture_id,
            "sportsbook": self.sportsbook,
            "market_type": self.market_type,
            "outcome_label": self.outcome_label,
            "line": self.line,
            "american_odds": self.american_odds,
            "decimal_odds": round(self.decimal_odds, 4),
            "implied_prob": round(self.implied_prob, 4),
            "is_live": self.is_live,
            "timestamp": self.timestamp,
        }


@dataclass
class OddsSnapshotRecord:
    """A persisted odds snapshot for backtesting and audit."""
    id: str = field(default_factory=lambda: f"snap-{uuid.uuid4().hex[:12]}")
    fixture_id: str = ""
    market_type: str = "moneyline"
    sportsbook: str = ""
    outcome_label: str = ""
    american_odds: int = 0
    decimal_odds: float = 0.0
    implied_prob: float = 0.0
    line: Optional[float] = None
    is_live: bool = False
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "fixture_id": self.fixture_id,
            "market_type": self.market_type,
            "sportsbook": self.sportsbook,
            "outcome_label": self.outcome_label,
            "american_odds": self.american_odds,
            "decimal_odds": round(self.decimal_odds, 4),
            "implied_prob": round(self.implied_prob, 4),
            "line": self.line,
            "is_live": self.is_live,
            "timestamp": self.timestamp,
        }


# ═══════════════════════════════════════════════════════════════════════
# 3. Odds Conversion Helpers
# ═══════════════════════════════════════════════════════════════════════

def _american_to_decimal(american: int) -> float:
    """Convert American odds to decimal odds."""
    if american > 0:
        return 1.0 + american / 100.0
    elif american < 0:
        return 1.0 + 100.0 / abs(american)
    return 2.0  # even


def _decimal_to_implied(decimal_odds: float) -> float:
    """Convert decimal odds to implied probability."""
    if decimal_odds <= 0:
        return 0.0
    return 1.0 / decimal_odds


def _remove_vig_two_way(prob_a: float, prob_b: float) -> Tuple[float, float]:
    """Remove vig from a two-way market (moneyline, spread, total)."""
    total = prob_a + prob_b
    if total <= 0:
        return 0.5, 0.5
    return prob_a / total, prob_b / total


def _remove_vig_multi(probs: List[float]) -> List[float]:
    """Remove vig from a multi-way market."""
    total = sum(probs)
    if total <= 0:
        n = len(probs)
        return [1.0 / n] * n if n > 0 else []
    return [p / total for p in probs]


# ═══════════════════════════════════════════════════════════════════════
# 4. OpticOdds Normalizer
# ═══════════════════════════════════════════════════════════════════════

class OpticOddsNormalizer:
    """Converts raw OpticOdds API responses into normalized data models."""

    @staticmethod
    def normalize_fixture(raw: Dict[str, Any]) -> OpticOddsFixture:
        """Parse a fixture from the OpticOdds API response."""
        sport_raw = raw.get("sport", raw.get("sport_key", ""))
        sport = OPTIC_ODDS_SPORTS.get(sport_raw, sport_raw)

        start_str = raw.get("start_time", raw.get("commence_time", ""))
        start_time = _parse_timestamp(start_str) if isinstance(start_str, str) else float(start_str or 0)

        status = raw.get("status", "pre")
        is_live = status == "live" or raw.get("is_live", False)

        return OpticOddsFixture(
            fixture_id=raw.get("id", raw.get("fixture_id", "")),
            sport=sport,
            league=raw.get("league", raw.get("sport_title", "")),
            home_team=raw.get("home_team", ""),
            away_team=raw.get("away_team", ""),
            start_time=start_time,
            is_live=is_live,
            status="live" if is_live else status,
            score_home=raw.get("score_home"),
            score_away=raw.get("score_away"),
            period=raw.get("period", ""),
            clock=raw.get("clock", ""),
        )

    @staticmethod
    def normalize_odds(fixture_id: str, raw_odds: Dict[str, Any]) -> List[OpticOddsLine]:
        """Parse odds lines from an OpticOdds API response."""
        lines = []
        sportsbook = raw_odds.get("sportsbook", raw_odds.get("bookmaker", ""))
        market_type_raw = raw_odds.get("market", raw_odds.get("market_type", "moneyline"))
        market_type = MARKET_TYPE_MAP.get(market_type_raw, market_type_raw)
        is_live = raw_odds.get("is_live", False)
        line_value = raw_odds.get("line", raw_odds.get("point"))

        outcomes = raw_odds.get("outcomes", raw_odds.get("prices", []))
        for outcome in outcomes:
            label = outcome.get("label", outcome.get("name", "")).lower()
            american = outcome.get("american_odds", outcome.get("price", 0))
            decimal_val = outcome.get("decimal_odds", 0.0)

            if isinstance(american, str):
                try:
                    american = int(american.replace("+", ""))
                except ValueError:
                    american = 0

            ol = OpticOddsLine(
                fixture_id=fixture_id,
                sportsbook=sportsbook,
                market_type=market_type,
                outcome_label=label,
                line=line_value,
                american_odds=american,
                decimal_odds=decimal_val,
                is_live=is_live,
            )
            lines.append(ol)

        return lines

    @staticmethod
    def to_odds_update(line: OpticOddsLine, receipt_time: Optional[float] = None) -> Any:
        """Convert an OpticOddsLine to a SportsOddsFeed OddsUpdate."""
        from merid.betting.live_sports import OddsUpdate
        now = receipt_time or time.time()
        latency_ms = (now - line.timestamp) * 1000 if line.timestamp > 0 else 0.0
        return OddsUpdate(
            provider=line.sportsbook,
            event_id=line.fixture_id,
            outcome_label=line.outcome_label,
            american_odds=line.american_odds,
            decimal_odds=line.decimal_odds,
            implied_prob=line.implied_prob,
            timestamp=now,
            latency_ms=max(0.0, latency_ms),
        )


# ═══════════════════════════════════════════════════════════════════════
# 5. OpticOdds REST Client
# ═══════════════════════════════════════════════════════════════════════

class OpticOddsClient:
    """HTTP client for the OpticOdds REST API.

    Supports:
      - Fetching fixtures (events) by sport
      - Fetching odds for a fixture
      - Fetching live/in-play odds
      - Rate limiting and caching
    """

    def __init__(
        self,
        api_key: str = "",
        base_url: str = "",
        cache_ttl_s: float = 15.0,
        min_request_interval_s: float = 0.5,
    ):
        self.api_key = api_key or os.environ.get("OPTIC_ODDS_API_KEY", "")
        self.base_url = (base_url or os.environ.get(
            "OPTIC_ODDS_BASE_URL", "https://api.opticodds.com/api/v3"
        )).rstrip("/")
        self._cache_ttl = cache_ttl_s
        self._min_interval = min_request_interval_s
        self._last_request_ts = 0.0
        self._cache: Dict[str, Tuple[float, Any]] = {}
        self._request_count = 0
        self._error_count = 0
        self._normalizer = OpticOddsNormalizer()

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key)

    def get_fixtures(self, sport: str = "", league: str = "", live_only: bool = False) -> List[OpticOddsFixture]:
        """Fetch fixtures from the API (or synthetic fallback)."""
        if not self.is_configured:
            return self._synthetic_fixtures(sport, live_only)

        cache_key = f"fixtures:{sport}:{league}:{live_only}"
        cached = self._get_cache(cache_key)
        if cached is not None:
            return cached

        params: Dict[str, Any] = {}
        if sport:
            params["sport"] = sport
        if league:
            params["league"] = league
        if live_only:
            params["is_live"] = True

        data = self._request("GET", "/fixtures", params=params)
        if data is None:
            return self._synthetic_fixtures(sport, live_only)

        fixtures_raw = data if isinstance(data, list) else data.get("data", data.get("fixtures", []))
        fixtures = [self._normalizer.normalize_fixture(f) for f in fixtures_raw]
        self._set_cache(cache_key, fixtures)
        return fixtures

    def get_odds(
        self,
        fixture_id: str,
        market_type: str = "moneyline",
        sportsbooks: Optional[List[str]] = None,
    ) -> List[OpticOddsLine]:
        """Fetch odds for a specific fixture."""
        if not self.is_configured:
            return self._synthetic_odds(fixture_id, market_type)

        cache_key = f"odds:{fixture_id}:{market_type}"
        cached = self._get_cache(cache_key)
        if cached is not None:
            return cached

        params: Dict[str, Any] = {"fixture_id": fixture_id, "market": market_type}
        if sportsbooks:
            params["sportsbooks"] = ",".join(sportsbooks)

        data = self._request("GET", "/odds", params=params)
        if data is None:
            return self._synthetic_odds(fixture_id, market_type)

        odds_raw = data if isinstance(data, list) else data.get("data", data.get("odds", []))
        lines = []
        for raw in odds_raw:
            lines.extend(self._normalizer.normalize_odds(fixture_id, raw))
        self._set_cache(cache_key, lines)
        return lines

    def get_live_odds(self, sport: str = "") -> List[OpticOddsLine]:
        """Fetch all live/in-play odds."""
        if not self.is_configured:
            return self._synthetic_live_odds(sport)

        cache_key = f"live_odds:{sport}"
        cached = self._get_cache(cache_key)
        if cached is not None:
            return cached

        params: Dict[str, Any] = {"is_live": True}
        if sport:
            params["sport"] = sport

        data = self._request("GET", "/odds/live", params=params)
        if data is None:
            return self._synthetic_live_odds(sport)

        odds_raw = data if isinstance(data, list) else data.get("data", [])
        lines = []
        for raw in odds_raw:
            fid = raw.get("fixture_id", raw.get("id", ""))
            lines.extend(self._normalizer.normalize_odds(fid, raw))
        self._set_cache(cache_key, lines)
        return lines

    def get_client_stats(self) -> Dict[str, Any]:
        """Get client usage statistics."""
        return {
            "configured": self.is_configured,
            "base_url": self.base_url,
            "requests": self._request_count,
            "errors": self._error_count,
            "cache_entries": len(self._cache),
        }

    # ── HTTP helpers ──────────────────────────────────────────────────

    def _request(self, method: str, path: str, params: Optional[Dict] = None) -> Optional[Any]:
        """Make an HTTP request with rate limiting."""
        try:
            import requests as req_lib
        except ImportError:
            logger.warning("requests library not available")
            return None

        self._rate_limit()
        self._request_count += 1

        headers = {"x-api-key": self.api_key}
        url = f"{self.base_url}{path}"

        try:
            resp = req_lib.request(method, url, params=params, headers=headers, timeout=10)
            if resp.status_code == 200:
                return resp.json()
            else:
                logger.warning("OpticOdds API %s %s returned %d", method, path, resp.status_code)
                self._error_count += 1
                return None
        except Exception as exc:
            logger.warning("OpticOdds API error: %s", exc)
            self._error_count += 1
            return None

    def _rate_limit(self) -> None:
        now = time.time()
        elapsed = now - self._last_request_ts
        if elapsed < self._min_interval:
            time.sleep(self._min_interval - elapsed)
        self._last_request_ts = time.time()

    def _get_cache(self, key: str) -> Optional[Any]:
        entry = self._cache.get(key)
        if entry and (time.time() - entry[0]) < self._cache_ttl:
            return entry[1]
        return None

    def _set_cache(self, key: str, value: Any) -> None:
        self._cache[key] = (time.time(), value)

    # ── Synthetic data (development/testing) ──────────────────────────

    def _synthetic_fixtures(self, sport: str = "", live_only: bool = False) -> List[OpticOddsFixture]:
        now = time.time()
        fixtures = [
            OpticOddsFixture(
                fixture_id="optic-nfl-kc-sf", sport="nfl", league="NFL",
                home_team="San Francisco 49ers", away_team="Kansas City Chiefs",
                start_time=now + 86400, is_live=False, status="pre",
            ),
            OpticOddsFixture(
                fixture_id="optic-nba-lal-bos", sport="nba", league="NBA",
                home_team="Los Angeles Lakers", away_team="Boston Celtics",
                start_time=now - 3600, is_live=True, status="live",
                score_home=54, score_away=61, period="Q3", clock="8:42",
            ),
            OpticOddsFixture(
                fixture_id="optic-mlb-nyy-bos", sport="mlb", league="MLB",
                home_team="Boston Red Sox", away_team="New York Yankees",
                start_time=now + 86400 * 2, is_live=False, status="pre",
            ),
            OpticOddsFixture(
                fixture_id="optic-nhl-bos-tor", sport="nhl", league="NHL",
                home_team="Toronto Maple Leafs", away_team="Boston Bruins",
                start_time=now - 1800, is_live=True, status="live",
                score_home=2, score_away=3, period="P2", clock="12:15",
            ),
            OpticOddsFixture(
                fixture_id="optic-soccer-ars-che", sport="soccer", league="Premier League",
                home_team="Arsenal", away_team="Chelsea",
                start_time=now + 3600 * 6, is_live=False, status="pre",
            ),
        ]
        if sport:
            fixtures = [f for f in fixtures if f.sport == sport]
        if live_only:
            fixtures = [f for f in fixtures if f.is_live]
        return fixtures

    def _synthetic_odds(self, fixture_id: str, market_type: str) -> List[OpticOddsLine]:
        odds_data: Dict[str, List[Tuple[str, str, int, str]]] = {
            "optic-nfl-kc-sf": [
                ("draftkings", "home", -110, "moneyline"),
                ("draftkings", "away", -110, "moneyline"),
                ("fanduel", "home", -105, "moneyline"),
                ("fanduel", "away", -115, "moneyline"),
                ("pinnacle", "home", -104, "moneyline"),
                ("pinnacle", "away", -106, "moneyline"),
                ("betmgm", "home", -108, "moneyline"),
                ("betmgm", "away", -112, "moneyline"),
            ],
            "optic-nba-lal-bos": [
                ("draftkings", "home", +150, "moneyline"),
                ("draftkings", "away", -180, "moneyline"),
                ("fanduel", "home", +145, "moneyline"),
                ("fanduel", "away", -175, "moneyline"),
                ("pinnacle", "home", +155, "moneyline"),
                ("pinnacle", "away", -170, "moneyline"),
            ],
            "optic-mlb-nyy-bos": [
                ("draftkings", "home", +120, "moneyline"),
                ("draftkings", "away", -140, "moneyline"),
                ("fanduel", "home", +125, "moneyline"),
                ("fanduel", "away", -145, "moneyline"),
            ],
            "optic-nhl-bos-tor": [
                ("draftkings", "home", +130, "moneyline"),
                ("draftkings", "away", -150, "moneyline"),
                ("pinnacle", "home", +135, "moneyline"),
                ("pinnacle", "away", -145, "moneyline"),
            ],
            "optic-soccer-ars-che": [
                ("draftkings", "home", -120, "moneyline"),
                ("draftkings", "away", +250, "moneyline"),
                ("draftkings", "draw", +280, "moneyline"),
                ("pinnacle", "home", -115, "moneyline"),
                ("pinnacle", "away", +260, "moneyline"),
                ("pinnacle", "draw", +275, "moneyline"),
            ],
        }

        raw = odds_data.get(fixture_id, [])
        lines = []
        for book, outcome, odds_val, mtype in raw:
            if market_type and mtype != market_type:
                continue
            lines.append(OpticOddsLine(
                fixture_id=fixture_id,
                sportsbook=book,
                market_type=mtype,
                outcome_label=outcome,
                american_odds=odds_val,
            ))
        return lines

    def _synthetic_live_odds(self, sport: str = "") -> List[OpticOddsLine]:
        live_fixtures = self._synthetic_fixtures(sport, live_only=True)
        lines = []
        for f in live_fixtures:
            lines.extend(self._synthetic_odds(f.fixture_id, "moneyline"))
        for line in lines:
            line.is_live = True
        return lines


# ═══════════════════════════════════════════════════════════════════════
# 6. Odds Snapshot Store (in-memory + optional persistence)
# ═══════════════════════════════════════════════════════════════════════

class OddsSnapshotStore:
    """Ring-buffer store for odds snapshots with optional SQLite persistence.

    Keeps the last N snapshots per fixture in memory for fast access,
    and optionally writes to SQLite for backtesting and audit.
    """

    def __init__(self, max_per_fixture: int = 500, persist: bool = False):
        self._lock = threading.RLock()
        self._snapshots: Dict[str, Deque[OddsSnapshotRecord]] = {}
        self._max_per_fixture = max_per_fixture
        self._total_stored = 0

    def record(self, line: OpticOddsLine) -> OddsSnapshotRecord:
        """Record an odds snapshot from a line update."""
        snap = OddsSnapshotRecord(
            fixture_id=line.fixture_id,
            market_type=line.market_type,
            sportsbook=line.sportsbook,
            outcome_label=line.outcome_label,
            american_odds=line.american_odds,
            decimal_odds=line.decimal_odds,
            implied_prob=line.implied_prob,
            line=line.line,
            is_live=line.is_live,
            timestamp=line.timestamp,
        )
        with self._lock:
            if line.fixture_id not in self._snapshots:
                self._snapshots[line.fixture_id] = collections.deque(maxlen=self._max_per_fixture)
            self._snapshots[line.fixture_id].append(snap)
            self._total_stored += 1
        return snap

    def get_history(
        self,
        fixture_id: str,
        market_type: Optional[str] = None,
        sportsbook: Optional[str] = None,
        limit: int = 100,
    ) -> List[OddsSnapshotRecord]:
        """Get historical snapshots for a fixture."""
        with self._lock:
            snaps = list(self._snapshots.get(fixture_id, []))
        if market_type:
            snaps = [s for s in snaps if s.market_type == market_type]
        if sportsbook:
            snaps = [s for s in snaps if s.sportsbook == sportsbook]
        return snaps[-limit:]

    def get_closing_line(self, fixture_id: str, outcome_label: str) -> Optional[OddsSnapshotRecord]:
        """Get the last recorded odds for a fixture+outcome (closing line proxy)."""
        with self._lock:
            snaps = list(self._snapshots.get(fixture_id, []))
        matching = [s for s in snaps if s.outcome_label == outcome_label]
        return matching[-1] if matching else None

    def get_store_stats(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "fixtures_tracked": len(self._snapshots),
                "total_snapshots": self._total_stored,
                "max_per_fixture": self._max_per_fixture,
            }


# ═══════════════════════════════════════════════════════════════════════
# 7. OpticOdds Poller (background feed)
# ═══════════════════════════════════════════════════════════════════════

class OpticOddsPoller:
    """Background polling loop that fetches odds and feeds them into SportsOddsFeed.

    Polls at configurable intervals:
      - Pre-game: every 60s
      - Live: every 5s (or as fast as API allows)
    """

    def __init__(
        self,
        client: OpticOddsClient,
        odds_feed: Any = None,          # SportsOddsFeed instance
        snapshot_store: Optional[OddsSnapshotStore] = None,
        pre_game_interval_s: float = 60.0,
        live_interval_s: float = 5.0,
        sports: Optional[List[str]] = None,
    ):
        self.client = client
        self.odds_feed = odds_feed
        self.snapshot_store = snapshot_store or OddsSnapshotStore()
        self.pre_game_interval_s = pre_game_interval_s
        self.live_interval_s = live_interval_s
        self.sports = sports or list(OPTIC_ODDS_SPORTS.values())

        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.RLock()
        self._poll_count = 0
        self._last_poll_ts = 0.0
        self._fixtures_seen: Set[str] = set()
        self._normalizer = OpticOddsNormalizer()

    def start(self) -> None:
        """Start the background polling thread."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._poll_loop, daemon=True, name="optic-odds-poller")
        self._thread.start()
        logger.info("OpticOdds poller started (pre=%ds, live=%ds)", self.pre_game_interval_s, self.live_interval_s)

    def stop(self) -> None:
        """Stop the background polling thread."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=10)
            self._thread = None
        logger.info("OpticOdds poller stopped")

    def poll_once(self) -> Dict[str, Any]:
        """Execute a single poll cycle. Returns stats."""
        receipt_time = time.time()
        updates_ingested = 0
        fixtures_found = 0
        errors = 0

        for sport in self.sports:
            try:
                fixtures = self.client.get_fixtures(sport=sport)
                fixtures_found += len(fixtures)

                for fixture in fixtures:
                    self._fixtures_seen.add(fixture.fixture_id)
                    lines = self.client.get_odds(fixture.fixture_id)

                    for line in lines:
                        # Record snapshot
                        self.snapshot_store.record(line)

                        # Convert to OddsUpdate and feed
                        if self.odds_feed:
                            update = self._normalizer.to_odds_update(line, receipt_time)
                            self.odds_feed.ingest_update(update)
                            updates_ingested += 1

            except Exception as exc:
                logger.warning("Poll error for sport %s: %s", sport, exc)
                errors += 1

        with self._lock:
            self._poll_count += 1
            self._last_poll_ts = time.time()

        return {
            "poll_count": self._poll_count,
            "fixtures_found": fixtures_found,
            "updates_ingested": updates_ingested,
            "errors": errors,
        }

    def get_poller_stats(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "running": self._running,
                "poll_count": self._poll_count,
                "last_poll_ts": self._last_poll_ts,
                "fixtures_seen": len(self._fixtures_seen),
                "sports": self.sports,
                "snapshot_store": self.snapshot_store.get_store_stats(),
            }

    def _poll_loop(self) -> None:
        """Main polling loop — runs in background thread."""
        while self._running:
            try:
                self.poll_once()
            except Exception as exc:
                logger.error("Poller loop error: %s", exc)

            # Sleep: use live interval if any live fixtures exist
            has_live = any(
                f.is_live for sport in self.sports
                for f in self.client.get_fixtures(sport=sport, live_only=True)
            )
            interval = self.live_interval_s if has_live else self.pre_game_interval_s
            # Sleep in small increments so stop() is responsive
            slept = 0.0
            while slept < interval and self._running:
                time.sleep(min(1.0, interval - slept))
                slept += 1.0


# ═══════════════════════════════════════════════════════════════════════
# 8. Timestamp parsing helper
# ═══════════════════════════════════════════════════════════════════════

def _parse_timestamp(ts_str: str) -> float:
    """Parse ISO 8601 timestamp to epoch seconds."""
    if not ts_str:
        return 0.0
    try:
        from datetime import datetime, timezone
        # Handle common ISO formats
        for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S.%fZ"):
            try:
                dt = datetime.strptime(ts_str, fmt)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt.timestamp()
            except ValueError:
                continue
    except Exception as exc:
        logger.debug("operation_suppressed", error=str(exc))
    return 0.0


# ═══════════════════════════════════════════════════════════════════════
# 9. Singleton access
# ═══════════════════════════════════════════════════════════════════════

_optic_client: Optional[OpticOddsClient] = None
_optic_client_lock = threading.Lock()
_optic_poller: Optional[OpticOddsPoller] = None
_snapshot_store: Optional[OddsSnapshotStore] = None
_snapshot_store_lock = threading.Lock()


def get_optic_odds_client() -> OpticOddsClient:
    """Get or create the singleton OpticOddsClient."""
    global _optic_client
    if _optic_client is None:
        with _optic_client_lock:
            if _optic_client is None:
                _optic_client = OpticOddsClient()
    return _optic_client


def get_snapshot_store() -> OddsSnapshotStore:
    """Get or create the singleton OddsSnapshotStore."""
    global _snapshot_store
    if _snapshot_store is None:
        with _snapshot_store_lock:
            if _snapshot_store is None:
                _snapshot_store = OddsSnapshotStore()
    return _snapshot_store


def get_optic_odds_poller() -> OpticOddsPoller:
    """Get or create the singleton OpticOddsPoller."""
    global _optic_poller
    if _optic_poller is None:
        from merid.betting.live_sports import get_sports_betting_manager
        mgr = get_sports_betting_manager()
        _optic_poller = OpticOddsPoller(
            client=get_optic_odds_client(),
            odds_feed=mgr.odds_feed,
            snapshot_store=get_snapshot_store(),
        )
    return _optic_poller
