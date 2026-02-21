"""MERID Generalized Reward Engine — platform-wide antifragile incentives.

Provides:
- RewardEvent base schema + typed event variants (Forecast, Debate, Cognitive, CodeQuality, Dev*)
- RewardEngine: central event→mechanism→reward pipeline
- RewardMechanism: pluggable scoring rules with config-driven decay, bonuses, caps
- Levels / Reputation: long-term accumulation with influence weights
- Quests / Challenges: time-bound objectives with reward multipliers
- Observability: distribution metrics, gaming detection, reward-contribution correlation

All data persisted in SQLite (same DB spine as DebateStore / ConsensusStore).
"""

from merid.rewards.events import (
    RewardEvent,
    ForecastEvent,
    DebateEvent,
    CognitiveEvent,
    CodeQualityEvent,
    DevForecastEvent,
    DevDebateEvent,
    SportsForecastEvent,
    SportsBetEvent,
    SportsDebateEvent,
    EventCategory,
)
from merid.rewards.sports_rewards import (
    SportsBadgeEngine,
    SportsQuestTracker,
    SportsRewardComputer,
    get_sports_badge_engine,
    get_sports_quest_tracker,
    get_sports_reward_computer,
)
from merid.rewards.engine import (
    RewardEngine,
    RewardOutcome,
    get_reward_engine,
)
from merid.rewards.mechanisms import (
    RewardMechanism,
    AccuracyMechanism,
    ImprovementMechanism,
    ExplanationMechanism,
    StabilityMechanism,
    InsightMechanism,
    MechanismRegistry,
    get_mechanism_registry,
)
from merid.rewards.levels import (
    ReputationLevel,
    ReputationTracker,
)
from merid.rewards.quests import (
    Quest,
    QuestStatus,
    QuestStore,
)

__all__ = [
    "RewardEvent",
    "ForecastEvent",
    "DebateEvent",
    "CognitiveEvent",
    "CodeQualityEvent",
    "DevForecastEvent",
    "DevDebateEvent",
    "EventCategory",
    "RewardEngine",
    "RewardOutcome",
    "get_reward_engine",
    "RewardMechanism",
    "AccuracyMechanism",
    "ImprovementMechanism",
    "ExplanationMechanism",
    "StabilityMechanism",
    "InsightMechanism",
    "MechanismRegistry",
    "get_mechanism_registry",
    "ReputationLevel",
    "ReputationTracker",
    "Quest",
    "QuestStatus",
    "QuestStore",
    "SportsForecastEvent",
    "SportsBetEvent",
    "SportsDebateEvent",
    "SportsBadgeEngine",
    "SportsQuestTracker",
    "SportsRewardComputer",
    "get_sports_badge_engine",
    "get_sports_quest_tracker",
    "get_sports_reward_computer",
]
