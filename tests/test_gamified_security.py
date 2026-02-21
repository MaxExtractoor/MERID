"""
Tests for swarm/gamified_security.py — GamifiedSecuritySystem.

Covers:
- Quest creation and initialization
- Bug report submission and verification
- Reward distribution
- Security seasons and leaderboards
- User profiles, tiers, and badges
- Sybil resistance checks
"""

import unittest
from datetime import datetime, timedelta
from decimal import Decimal

from swarm.gamified_security import (
    BugReport,
    GamifiedSecuritySystem,
    QuestStatus,
    QuestType,
    RewardTier,
    SecurityQuest,
    SecuritySeason,
    SeverityLevel,
    UserProfile,
)


class TestQuestCreation(unittest.TestCase):
    """Quest creation and initialization."""

    def setUp(self):
        self.system = GamifiedSecuritySystem()

    def test_default_quests_initialized(self):
        """System initializes with default security quests."""
        self.assertGreater(len(self.system._quests), 0)

    def test_default_quest_types(self):
        """Default quests cover key security types."""
        types = {q.quest_type for q in self.system._quests.values()}
        self.assertIn(QuestType.BUG_HUNT, types)
        self.assertIn(QuestType.PHISHING_DETECTION, types)
        self.assertIn(QuestType.SCAM_TOKEN_DETECTION, types)
        self.assertIn(QuestType.RISK_BEHAVIOR, types)

    def test_create_custom_quest(self):
        """Can create a custom quest."""
        quest = self.system.create_quest(
            quest_type=QuestType.SECURITY_CHALLENGE,
            title="Custom Challenge",
            description="Test challenge",
            requirements=["Step 1", "Step 2"],
            reward_points=200,
            reward_tier=RewardTier.GOLD,
            reward_tokens=Decimal("50"),
            duration_days=7,
        )
        self.assertIn(quest.quest_id, self.system._quests)
        self.assertEqual(quest.reward_points, 200)
        self.assertEqual(quest.reward_tier, RewardTier.GOLD)
        self.assertEqual(quest.reward_tokens, Decimal("50"))
        self.assertIsNotNone(quest.ends_at)

    def test_quest_without_duration_has_no_end(self):
        """Quest without duration_days has no end date."""
        quest = self.system.create_quest(
            quest_type=QuestType.AUDIT,
            title="Open-ended Audit",
            description="No deadline",
        )
        self.assertIsNone(quest.ends_at)

    def test_quest_status_defaults_to_active(self):
        """New quests default to ACTIVE status."""
        quest = self.system.create_quest(
            quest_type=QuestType.BUG_HUNT,
            title="Active Quest",
            description="Should be active",
        )
        self.assertEqual(quest.status, QuestStatus.ACTIVE)

    def test_get_active_quests(self):
        """get_active_quests returns only active, non-expired quests."""
        active = self.system.get_active_quests()
        self.assertGreater(len(active), 0)
        for q in active:
            self.assertEqual(q.status, QuestStatus.ACTIVE)


class TestBugReportSubmission(unittest.TestCase):
    """Bug report submission."""

    def setUp(self):
        self.system = GamifiedSecuritySystem()

    def test_submit_bug_report(self):
        """Can submit a bug report."""
        report = self.system.submit_bug_report(
            reporter_id="user-1",
            title="XSS in dashboard",
            description="Reflected XSS via symbol parameter",
            reported_severity=SeverityLevel.HIGH,
            affected_contract="web/api/dashboard.py",
            evidence=["screenshot.png"],
            reproduction_steps=["Step 1: navigate to...", "Step 2: inject..."],
        )
        self.assertIn(report.report_id, self.system._bug_reports)
        self.assertEqual(report.reporter_id, "user-1")
        self.assertEqual(report.reported_severity, SeverityLevel.HIGH)
        self.assertFalse(report.verified)

    def test_submit_updates_user_stats(self):
        """Submitting a bug report increments user's total_bugs_reported."""
        self.system.submit_bug_report(
            reporter_id="user-2",
            title="Bug 1",
            description="desc",
            reported_severity=SeverityLevel.LOW,
        )
        profile = self.system.get_user_profile("user-2")
        self.assertIsNotNone(profile)
        self.assertEqual(profile.total_bugs_reported, 1)

    def test_multiple_reports_increment_count(self):
        """Multiple reports from same user increment count."""
        for i in range(3):
            self.system.submit_bug_report(
                reporter_id="user-3",
                title=f"Bug {i}",
                description="desc",
                reported_severity=SeverityLevel.MEDIUM,
            )
        profile = self.system.get_user_profile("user-3")
        self.assertEqual(profile.total_bugs_reported, 3)


class TestBugReportVerification(unittest.TestCase):
    """Bug report verification and reward assignment."""

    def setUp(self):
        self.system = GamifiedSecuritySystem()
        self.report = self.system.submit_bug_report(
            reporter_id="hunter-1",
            title="Critical vuln",
            description="Remote code execution",
            reported_severity=SeverityLevel.CRITICAL,
        )

    def test_verify_bug_report(self):
        """Can verify a bug report."""
        verified = self.system.verify_bug_report(
            report_id=self.report.report_id,
            verified_severity=SeverityLevel.CRITICAL,
            verified_by="auditor-1",
        )
        self.assertTrue(verified.verified)
        self.assertEqual(verified.verified_severity, SeverityLevel.CRITICAL)
        self.assertEqual(verified.verified_by, "auditor-1")

    def test_critical_bug_awards_2000_points(self):
        """Critical bug awards 2000 points."""
        self.system.verify_bug_report(
            self.report.report_id, SeverityLevel.CRITICAL, "auditor-1"
        )
        self.assertEqual(self.report.reward_points, 2000)

    def test_critical_bug_awards_1000_tokens(self):
        """Critical bug awards 1000 tokens."""
        self.system.verify_bug_report(
            self.report.report_id, SeverityLevel.CRITICAL, "auditor-1"
        )
        self.assertEqual(self.report.reward_tokens, Decimal("1000"))

    def test_low_severity_awards_50_points(self):
        """Low severity bug awards 50 points."""
        report = self.system.submit_bug_report(
            reporter_id="hunter-2", title="Minor", description="d",
            reported_severity=SeverityLevel.LOW,
        )
        self.system.verify_bug_report(report.report_id, SeverityLevel.LOW, "auditor-1")
        self.assertEqual(report.reward_points, 50)

    def test_verify_updates_user_profile(self):
        """Verification updates user's verified_bugs and total_points."""
        self.system.verify_bug_report(
            self.report.report_id, SeverityLevel.CRITICAL, "auditor-1"
        )
        profile = self.system.get_user_profile("hunter-1")
        self.assertEqual(profile.verified_bugs, 1)
        self.assertEqual(profile.total_points, 2000)

    def test_critical_bug_awards_badge(self):
        """Critical bug awards 'critical_bug_hunter' badge."""
        self.system.verify_bug_report(
            self.report.report_id, SeverityLevel.CRITICAL, "auditor-1"
        )
        profile = self.system.get_user_profile("hunter-1")
        self.assertIn("critical_bug_hunter", profile.badges)

    def test_non_critical_no_badge(self):
        """Non-critical bug does not award critical badge."""
        report = self.system.submit_bug_report(
            reporter_id="hunter-3", title="Low", description="d",
            reported_severity=SeverityLevel.LOW,
        )
        self.system.verify_bug_report(report.report_id, SeverityLevel.LOW, "auditor-1")
        profile = self.system.get_user_profile("hunter-3")
        self.assertNotIn("critical_bug_hunter", profile.badges)

    def test_verify_nonexistent_report_raises(self):
        """Verifying nonexistent report raises ValueError."""
        with self.assertRaises(ValueError):
            self.system.verify_bug_report("nonexistent", SeverityLevel.LOW, "auditor-1")


class TestRewardDistribution(unittest.TestCase):
    """Bug report reward distribution."""

    def setUp(self):
        self.system = GamifiedSecuritySystem()

    def test_reward_verified_report(self):
        """Can reward a verified bug report."""
        report = self.system.submit_bug_report(
            reporter_id="user-1", title="Bug", description="d",
            reported_severity=SeverityLevel.MEDIUM,
        )
        self.system.verify_bug_report(report.report_id, SeverityLevel.MEDIUM, "auditor")
        result = self.system.reward_bug_report(report.report_id)
        self.assertTrue(result)
        self.assertTrue(report.rewarded)

    def test_cannot_reward_unverified(self):
        """Cannot reward an unverified report."""
        report = self.system.submit_bug_report(
            reporter_id="user-1", title="Bug", description="d",
            reported_severity=SeverityLevel.LOW,
        )
        result = self.system.reward_bug_report(report.report_id)
        self.assertFalse(result)

    def test_cannot_double_reward(self):
        """Cannot reward the same report twice."""
        report = self.system.submit_bug_report(
            reporter_id="user-1", title="Bug", description="d",
            reported_severity=SeverityLevel.HIGH,
        )
        self.system.verify_bug_report(report.report_id, SeverityLevel.HIGH, "auditor")
        self.system.reward_bug_report(report.report_id)
        result = self.system.reward_bug_report(report.report_id)
        self.assertFalse(result)

    def test_reward_nonexistent_returns_false(self):
        """Rewarding nonexistent report returns False."""
        result = self.system.reward_bug_report("nonexistent")
        self.assertFalse(result)


class TestSecuritySeasons(unittest.TestCase):
    """Security challenge seasons."""

    def setUp(self):
        self.system = GamifiedSecuritySystem()

    def test_create_season(self):
        """Can create a security season."""
        season = self.system.create_security_season(
            season_name="Season 1: Bug Bounty",
            duration_days=30,
            challenges=["quest_1", "quest_2"],
        )
        self.assertIn(season.season_id, self.system._seasons)
        self.assertEqual(season.season_name, "Season 1: Bug Bounty")
        self.assertTrue(season.active)
        self.assertEqual(len(season.challenges), 2)

    def test_season_has_top_rewards(self):
        """Season has top-5 reward tiers."""
        season = self.system.create_security_season("Test Season")
        self.assertEqual(len(season.top_rewards), 5)
        self.assertEqual(season.top_rewards[1]["points"], 5000)
        self.assertEqual(season.top_rewards[1]["tokens"], Decimal("1000"))

    def test_update_leaderboard(self):
        """Can update season leaderboard."""
        season = self.system.create_security_season("Test")
        self.system.update_season_leaderboard(season.season_id, "user-1", 100)
        self.system.update_season_leaderboard(season.season_id, "user-1", 50)
        self.system.update_season_leaderboard(season.season_id, "user-2", 200)
        self.assertEqual(season.leaderboard["user-1"], 150)
        self.assertEqual(season.leaderboard["user-2"], 200)

    def test_get_leaderboard_sorted(self):
        """Leaderboard is sorted by points descending."""
        season = self.system.create_security_season("Test")
        self.system.update_season_leaderboard(season.season_id, "user-a", 100)
        self.system.update_season_leaderboard(season.season_id, "user-b", 300)
        self.system.update_season_leaderboard(season.season_id, "user-c", 200)
        lb = self.system.get_season_leaderboard(season.season_id, top_n=3)
        self.assertEqual(lb[0], ("user-b", 300))
        self.assertEqual(lb[1], ("user-c", 200))
        self.assertEqual(lb[2], ("user-a", 100))

    def test_leaderboard_nonexistent_season(self):
        """Leaderboard for nonexistent season returns empty."""
        lb = self.system.get_season_leaderboard("nonexistent")
        self.assertEqual(lb, [])

    def test_inactive_season_blocks_updates(self):
        """Cannot update leaderboard for inactive season."""
        season = self.system.create_security_season("Test")
        season.active = False
        self.system.update_season_leaderboard(season.season_id, "user-1", 100)
        self.assertEqual(len(season.leaderboard), 0)

    def test_end_season(self):
        """Ending a season distributes rewards and deactivates."""
        season = self.system.create_security_season("Finale")
        self.system.update_season_leaderboard(season.season_id, "winner", 1000)
        self.system.update_season_leaderboard(season.season_id, "runner", 500)
        rewards = self.system.end_season(season.season_id)
        self.assertFalse(season.active)
        self.assertIn("winner", rewards)
        self.assertEqual(rewards["winner"]["points"], 5000)

    def test_end_season_awards_nft(self):
        """Top-3 finishers get NFT badges."""
        season = self.system.create_security_season("NFT Season")
        self.system.update_season_leaderboard(season.season_id, "champ", 1000)
        self.system.end_season(season.season_id)
        profile = self.system.get_user_profile("champ")
        self.assertIn("season_champion", profile.nfts)

    def test_end_inactive_season_returns_empty(self):
        """Ending an already-inactive season returns empty dict."""
        season = self.system.create_security_season("Done")
        self.system.end_season(season.season_id)
        result = self.system.end_season(season.season_id)
        self.assertEqual(result, {})


class TestUserProfiles(unittest.TestCase):
    """User profiles, tiers, and Sybil resistance."""

    def setUp(self):
        self.system = GamifiedSecuritySystem()

    def test_profile_created_on_first_interaction(self):
        """Profile auto-created on first bug report."""
        self.system.submit_bug_report(
            reporter_id="new-user", title="Bug", description="d",
            reported_severity=SeverityLevel.LOW,
        )
        profile = self.system.get_user_profile("new-user")
        self.assertIsNotNone(profile)
        self.assertEqual(profile.current_tier, RewardTier.BRONZE)

    def test_tier_progression(self):
        """Tier upgrades based on total points."""
        profile = self.system._get_or_create_profile("tier-user")

        profile.total_points = 499
        self.system._update_user_tier(profile)
        self.assertEqual(profile.current_tier, RewardTier.BRONZE)

        profile.total_points = 500
        self.system._update_user_tier(profile)
        self.assertEqual(profile.current_tier, RewardTier.SILVER)

        profile.total_points = 2000
        self.system._update_user_tier(profile)
        self.assertEqual(profile.current_tier, RewardTier.GOLD)

        profile.total_points = 5000
        self.system._update_user_tier(profile)
        self.assertEqual(profile.current_tier, RewardTier.PLATINUM)

        profile.total_points = 10000
        self.system._update_user_tier(profile)
        self.assertEqual(profile.current_tier, RewardTier.DIAMOND)

    def test_sybil_resistant_with_stake(self):
        """User with sufficient stake passes Sybil check."""
        profile = self.system._get_or_create_profile("staker")
        profile.stake_amount = Decimal("100")
        self.assertTrue(self.system._is_sybil_resistant(profile))

    def test_sybil_resistant_with_identity(self):
        """User with identity verification passes Sybil check."""
        profile = self.system._get_or_create_profile("verified")
        profile.identity_verified = True
        self.assertTrue(self.system._is_sybil_resistant(profile))

    def test_sybil_resistant_with_reputation(self):
        """User with high reputation passes Sybil check."""
        profile = self.system._get_or_create_profile("reputable")
        profile.reputation_score = 0.5
        self.assertTrue(self.system._is_sybil_resistant(profile))

    def test_sybil_not_resistant_default(self):
        """Default profile fails Sybil check."""
        profile = self.system._get_or_create_profile("new-user")
        self.assertFalse(self.system._is_sybil_resistant(profile))

    def test_nonexistent_profile_returns_none(self):
        """get_user_profile for unknown user returns None."""
        self.assertIsNone(self.system.get_user_profile("ghost"))


class TestSeverityRewards(unittest.TestCase):
    """Reward amounts by severity level."""

    def setUp(self):
        self.system = GamifiedSecuritySystem()

    def _submit_and_verify(self, severity):
        report = self.system.submit_bug_report(
            reporter_id="tester", title="Bug", description="d",
            reported_severity=severity,
        )
        self.system.verify_bug_report(report.report_id, severity, "auditor")
        return report

    def test_info_severity(self):
        r = self._submit_and_verify(SeverityLevel.INFO)
        self.assertEqual(r.reward_points, 10)
        self.assertEqual(r.reward_tokens, Decimal("0"))

    def test_low_severity(self):
        r = self._submit_and_verify(SeverityLevel.LOW)
        self.assertEqual(r.reward_points, 50)
        self.assertEqual(r.reward_tokens, Decimal("10"))

    def test_medium_severity(self):
        r = self._submit_and_verify(SeverityLevel.MEDIUM)
        self.assertEqual(r.reward_points, 150)
        self.assertEqual(r.reward_tokens, Decimal("50"))

    def test_high_severity(self):
        r = self._submit_and_verify(SeverityLevel.HIGH)
        self.assertEqual(r.reward_points, 500)
        self.assertEqual(r.reward_tokens, Decimal("200"))

    def test_critical_severity(self):
        r = self._submit_and_verify(SeverityLevel.CRITICAL)
        self.assertEqual(r.reward_points, 2000)
        self.assertEqual(r.reward_tokens, Decimal("1000"))


if __name__ == "__main__":
    unittest.main()
