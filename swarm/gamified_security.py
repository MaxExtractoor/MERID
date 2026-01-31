"""
Gamified security quest system for MERID.

Implements:
- Bug-hunt and audit quests
- Security challenge seasons
- Risk-aware behavior quests
- Sybil-resistant rewards
"""

import logging
from typing import Dict, List, Optional, Any, Set, Tuple
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from decimal import Decimal

logger = logging.getLogger(__name__)


class QuestType(Enum):
    """Type of security quest."""
    BUG_HUNT = "bug_hunt"
    AUDIT = "audit"
    PHISHING_DETECTION = "phishing_detection"
    SCAM_TOKEN_DETECTION = "scam_token_detection"
    RISK_BEHAVIOR = "risk_behavior"
    SECURITY_CHALLENGE = "security_challenge"


class QuestStatus(Enum):
    """Quest status."""
    ACTIVE = "active"
    COMPLETED = "completed"
    VERIFIED = "verified"
    REWARDED = "rewarded"
    REJECTED = "rejected"


class SeverityLevel(Enum):
    """Bug/issue severity level."""
    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class RewardTier(Enum):
    """Reward tier."""
    BRONZE = "bronze"
    SILVER = "silver"
    GOLD = "gold"
    PLATINUM = "platinum"
    DIAMOND = "diamond"


@dataclass
class SecurityQuest:
    """Security quest."""
    quest_id: str
    quest_type: QuestType
    
    # Details
    title: str
    description: str
    
    # Requirements
    requirements: List[str] = field(default_factory=list)
    
    # Rewards
    reward_points: int = 0
    reward_tier: RewardTier = RewardTier.BRONZE
    reward_tokens: Decimal = Decimal("0")
    reward_nft: Optional[str] = None
    
    # Status
    status: QuestStatus = QuestStatus.ACTIVE
    
    # Participants
    participants: Set[str] = field(default_factory=set)
    completions: int = 0
    
    # Time
    starts_at: datetime = field(default_factory=datetime.utcnow)
    ends_at: Optional[datetime] = None
    
    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class BugReport:
    """Bug or vulnerability report."""
    report_id: str
    quest_id: Optional[str] = None
    
    # Reporter
    reporter_id: str = ""
    
    # Bug details
    title: str = ""
    description: str = ""
    affected_contract: Optional[str] = None
    affected_pool: Optional[str] = None
    
    # Severity
    reported_severity: SeverityLevel = SeverityLevel.LOW
    verified_severity: Optional[SeverityLevel] = None
    
    # Evidence
    evidence: List[str] = field(default_factory=list)
    reproduction_steps: List[str] = field(default_factory=list)
    
    # Verification
    verified: bool = False
    verified_by: Optional[str] = None
    verified_at: Optional[datetime] = None
    
    # Reward
    reward_points: int = 0
    reward_tokens: Decimal = Decimal("0")
    rewarded: bool = False
    
    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class SecuritySeason:
    """Security challenge season."""
    season_id: str
    season_name: str
    
    # Duration
    starts_at: datetime
    ends_at: datetime
    
    # Challenges
    challenges: List[str] = field(default_factory=list)  # Quest IDs
    
    # Leaderboard
    leaderboard: Dict[str, int] = field(default_factory=dict)  # user_id -> points
    
    # Rewards
    top_rewards: Dict[int, Dict[str, Any]] = field(default_factory=dict)  # rank -> reward
    
    # Status
    active: bool = True
    
    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class UserProfile:
    """User security profile."""
    user_id: str
    
    # Stats
    total_points: int = 0
    total_bugs_reported: int = 0
    verified_bugs: int = 0
    quests_completed: int = 0
    
    # Tier
    current_tier: RewardTier = RewardTier.BRONZE
    
    # Badges
    badges: Set[str] = field(default_factory=set)
    nfts: Set[str] = field(default_factory=set)
    
    # Reputation
    reputation_score: float = 0.0
    
    # Sybil resistance
    stake_amount: Decimal = Decimal("0")
    identity_verified: bool = False
    
    created_at: datetime = field(default_factory=datetime.utcnow)


class GamifiedSecuritySystem:
    """
    Gamified security quest system for MERID.
    
    Implements:
    - Bug-hunt and audit quests
    - Security challenge seasons
    - Risk-aware behavior quests
    - Sybil-resistant rewards
    """
    
    def __init__(self):
        self._quests: Dict[str, SecurityQuest] = {}
        self._bug_reports: Dict[str, BugReport] = {}
        self._seasons: Dict[str, SecuritySeason] = {}
        self._user_profiles: Dict[str, UserProfile] = {}
        
        self._initialize_quests()
    
    def _initialize_quests(self) -> None:
        """Initialize default quests."""
        
        # Bug hunt quest
        self.create_quest(
            quest_type=QuestType.BUG_HUNT,
            title="Bug Hunter",
            description="Report valid bugs in smart contracts or protocols",
            requirements=[
                "Submit detailed bug report",
                "Provide reproduction steps",
                "Include evidence",
            ],
            reward_points=100,
            reward_tier=RewardTier.SILVER,
        )
        
        # Phishing detection quest
        self.create_quest(
            quest_type=QuestType.PHISHING_DETECTION,
            title="Phishing Detector",
            description="Identify and report phishing domains and fake frontends",
            requirements=[
                "Report suspicious domain",
                "Provide screenshots",
                "Verify lookalike pattern",
            ],
            reward_points=50,
            reward_tier=RewardTier.BRONZE,
        )
        
        # Scam token detection quest
        self.create_quest(
            quest_type=QuestType.SCAM_TOKEN_DETECTION,
            title="Scam Token Hunter",
            description="Flag risky memecoins and scam patterns",
            requirements=[
                "Analyze token contract",
                "Check ownership concentration",
                "Verify liquidity status",
            ],
            reward_points=75,
            reward_tier=RewardTier.SILVER,
        )
        
        # Risk-aware behavior quest
        self.create_quest(
            quest_type=QuestType.RISK_BEHAVIOR,
            title="Risk-Aware Trader",
            description="Use safer vaults and enable security features",
            requirements=[
                "Use only audited vaults",
                "Diversify collateral",
                "Enable 2FA/hardware wallet",
            ],
            reward_points=25,
            reward_tier=RewardTier.BRONZE,
        )
        
        logger.info("Initialized gamified security quests")
    
    def create_quest(
        self,
        quest_type: QuestType,
        title: str,
        description: str,
        requirements: Optional[List[str]] = None,
        reward_points: int = 0,
        reward_tier: RewardTier = RewardTier.BRONZE,
        reward_tokens: Decimal = Decimal("0"),
        duration_days: Optional[int] = None,
    ) -> SecurityQuest:
        """Create security quest."""
        quest_id = f"quest_{quest_type.value}_{int(datetime.utcnow().timestamp())}"
        
        ends_at = None
        if duration_days:
            ends_at = datetime.utcnow() + timedelta(days=duration_days)
        
        quest = SecurityQuest(
            quest_id=quest_id,
            quest_type=quest_type,
            title=title,
            description=description,
            requirements=requirements or [],
            reward_points=reward_points,
            reward_tier=reward_tier,
            reward_tokens=reward_tokens,
            ends_at=ends_at,
        )
        
        self._quests[quest_id] = quest
        
        logger.info(
            f"Created quest '{quest_id}': {title} "
            f"({reward_points} points, {reward_tier.value} tier)"
        )
        
        return quest
    
    def submit_bug_report(
        self,
        reporter_id: str,
        title: str,
        description: str,
        reported_severity: SeverityLevel,
        affected_contract: Optional[str] = None,
        evidence: Optional[List[str]] = None,
        reproduction_steps: Optional[List[str]] = None,
        quest_id: Optional[str] = None,
    ) -> BugReport:
        """Submit bug report."""
        report_id = f"bug_{int(datetime.utcnow().timestamp())}"
        
        # Check Sybil resistance
        profile = self._get_or_create_profile(reporter_id)
        if not self._is_sybil_resistant(profile):
            logger.warning(
                f"Bug report from {reporter_id} may be Sybil attack "
                f"(low stake, no identity verification)"
            )
        
        report = BugReport(
            report_id=report_id,
            quest_id=quest_id,
            reporter_id=reporter_id,
            title=title,
            description=description,
            affected_contract=affected_contract,
            reported_severity=reported_severity,
            evidence=evidence or [],
            reproduction_steps=reproduction_steps or [],
        )
        
        self._bug_reports[report_id] = report
        
        # Update user stats
        profile.total_bugs_reported += 1
        
        logger.info(
            f"Bug report submitted: {report_id} by {reporter_id} "
            f"(severity: {reported_severity.value})"
        )
        
        return report
    
    def verify_bug_report(
        self,
        report_id: str,
        verified_severity: SeverityLevel,
        verified_by: str,
    ) -> BugReport:
        """Verify bug report and assign rewards."""
        report = self._bug_reports.get(report_id)
        
        if not report:
            raise ValueError(f"Bug report '{report_id}' not found")
        
        report.verified = True
        report.verified_severity = verified_severity
        report.verified_by = verified_by
        report.verified_at = datetime.utcnow()
        
        # Calculate rewards based on severity
        reward_points = {
            SeverityLevel.INFO: 10,
            SeverityLevel.LOW: 50,
            SeverityLevel.MEDIUM: 150,
            SeverityLevel.HIGH: 500,
            SeverityLevel.CRITICAL: 2000,
        }[verified_severity]
        
        reward_tokens = {
            SeverityLevel.INFO: Decimal("0"),
            SeverityLevel.LOW: Decimal("10"),
            SeverityLevel.MEDIUM: Decimal("50"),
            SeverityLevel.HIGH: Decimal("200"),
            SeverityLevel.CRITICAL: Decimal("1000"),
        }[verified_severity]
        
        report.reward_points = reward_points
        report.reward_tokens = reward_tokens
        
        # Update user profile
        profile = self._get_or_create_profile(report.reporter_id)
        profile.verified_bugs += 1
        profile.total_points += reward_points
        
        # Update tier
        self._update_user_tier(profile)
        
        # Award badge for critical bugs
        if verified_severity == SeverityLevel.CRITICAL:
            profile.badges.add("critical_bug_hunter")
        
        logger.info(
            f"Verified bug report {report_id}: {verified_severity.value} "
            f"(reward: {reward_points} points, {reward_tokens} tokens)"
        )
        
        return report
    
    def reward_bug_report(self, report_id: str) -> bool:
        """Reward verified bug report."""
        report = self._bug_reports.get(report_id)
        
        if not report or not report.verified or report.rewarded:
            return False
        
        # In real implementation, would transfer tokens
        report.rewarded = True
        
        logger.info(
            f"Rewarded bug report {report_id}: "
            f"{report.reward_points} points, {report.reward_tokens} tokens"
        )
        
        return True
    
    def create_security_season(
        self,
        season_name: str,
        duration_days: int = 30,
        challenges: Optional[List[str]] = None,
    ) -> SecuritySeason:
        """Create security challenge season."""
        season_id = f"season_{int(datetime.utcnow().timestamp())}"
        
        season = SecuritySeason(
            season_id=season_id,
            season_name=season_name,
            starts_at=datetime.utcnow(),
            ends_at=datetime.utcnow() + timedelta(days=duration_days),
            challenges=challenges or [],
        )
        
        # Set up top rewards
        season.top_rewards = {
            1: {"points": 5000, "tokens": Decimal("1000"), "nft": "season_champion"},
            2: {"points": 3000, "tokens": Decimal("500"), "nft": "season_runner_up"},
            3: {"points": 2000, "tokens": Decimal("250"), "nft": "season_top_3"},
            4: {"points": 1000, "tokens": Decimal("100")},
            5: {"points": 1000, "tokens": Decimal("100")},
        }
        
        self._seasons[season_id] = season
        
        logger.info(
            f"Created security season '{season_id}': {season_name} "
            f"({duration_days} days)"
        )
        
        return season
    
    def update_season_leaderboard(
        self,
        season_id: str,
        user_id: str,
        points: int,
    ) -> None:
        """Update season leaderboard."""
        season = self._seasons.get(season_id)
        
        if not season or not season.active:
            return
        
        if user_id not in season.leaderboard:
            season.leaderboard[user_id] = 0
        
        season.leaderboard[user_id] += points
    
    def get_season_leaderboard(
        self,
        season_id: str,
        top_n: int = 10,
    ) -> List[Tuple[str, int]]:
        """Get season leaderboard."""
        season = self._seasons.get(season_id)
        
        if not season:
            return []
        
        # Sort by points (descending)
        leaderboard = sorted(
            season.leaderboard.items(),
            key=lambda x: x[1],
            reverse=True,
        )
        
        return leaderboard[:top_n]
    
    def end_season(self, season_id: str) -> Dict[str, Any]:
        """End season and distribute rewards."""
        season = self._seasons.get(season_id)
        
        if not season or not season.active:
            return {}
        
        season.active = False
        
        # Get final leaderboard
        leaderboard = self.get_season_leaderboard(season_id, top_n=100)
        
        # Distribute rewards
        rewards_distributed = {}
        
        for rank, (user_id, points) in enumerate(leaderboard, start=1):
            if rank in season.top_rewards:
                reward = season.top_rewards[rank]
                
                # Update user profile
                profile = self._get_or_create_profile(user_id)
                profile.total_points += reward["points"]
                
                if "nft" in reward:
                    profile.nfts.add(reward["nft"])
                
                rewards_distributed[user_id] = reward
                
                logger.info(
                    f"Season {season_id} rank {rank}: {user_id} "
                    f"(reward: {reward})"
                )
        
        return rewards_distributed
    
    def _get_or_create_profile(self, user_id: str) -> UserProfile:
        """Get or create user profile."""
        if user_id not in self._user_profiles:
            self._user_profiles[user_id] = UserProfile(user_id=user_id)
        
        return self._user_profiles[user_id]
    
    def _is_sybil_resistant(self, profile: UserProfile) -> bool:
        """Check if user profile is Sybil-resistant."""
        # Require either stake or identity verification
        has_stake = profile.stake_amount >= Decimal("100")
        has_identity = profile.identity_verified
        has_reputation = profile.reputation_score >= 0.5
        
        return has_stake or has_identity or has_reputation
    
    def _update_user_tier(self, profile: UserProfile) -> None:
        """Update user tier based on points."""
        if profile.total_points >= 10000:
            profile.current_tier = RewardTier.DIAMOND
        elif profile.total_points >= 5000:
            profile.current_tier = RewardTier.PLATINUM
        elif profile.total_points >= 2000:
            profile.current_tier = RewardTier.GOLD
        elif profile.total_points >= 500:
            profile.current_tier = RewardTier.SILVER
        else:
            profile.current_tier = RewardTier.BRONZE
    
    def get_user_profile(self, user_id: str) -> Optional[UserProfile]:
        """Get user profile."""
        return self._user_profiles.get(user_id)
    
    def get_active_quests(self) -> List[SecurityQuest]:
        """Get active quests."""
        now = datetime.utcnow()
        
        return [
            q for q in self._quests.values()
            if q.status == QuestStatus.ACTIVE
            and (q.ends_at is None or q.ends_at > now)
        ]


_gamified_security_system: Optional[GamifiedSecuritySystem] = None


def get_gamified_security_system() -> GamifiedSecuritySystem:
    """Get global GamifiedSecuritySystem instance."""
    global _gamified_security_system
    if _gamified_security_system is None:
        _gamified_security_system = GamifiedSecuritySystem()
    return _gamified_security_system
