"""Tests for swarm.gamified_security."""

from __future__ import annotations

from decimal import Decimal

import pytest

from swarm.gamified_security import (
    GamifiedSecuritySystem,
    QuestType,
    RewardTier,
    SeverityLevel,
)


@pytest.fixture()
def security_system():
    # Fresh instance per test to avoid default quest carryover issues.
    return GamifiedSecuritySystem()


def test_create_quest_adds_active_entry(security_system):
    quest = security_system.create_quest(
        quest_type=QuestType.BUG_HUNT,
        title="New Quest",
        description="Find bugs",
        reward_points=200,
        reward_tier=RewardTier.GOLD,
        duration_days=7,
    )

    active = security_system.get_active_quests()
    assert quest in active
    assert quest.reward_tier == RewardTier.GOLD


def test_submit_and_verify_bug_report_updates_profile(security_system):
    report = security_system.submit_bug_report(
        reporter_id="user-1",
        title="Bug",
        description="Critical bug",
        reported_severity=SeverityLevel.CRITICAL,
        affected_contract="0xabc",
        evidence=["tx"],
    )
    assert report.report_id in security_system._bug_reports

    verified = security_system.verify_bug_report(report.report_id, SeverityLevel.HIGH, verified_by="auditor")
    assert verified.verified is True
    profile = security_system.get_user_profile("user-1")
    assert profile.total_points >= 500
    assert profile.current_tier in {RewardTier.SILVER, RewardTier.GOLD, RewardTier.PLATINUM, RewardTier.DIAMOND}


def test_reward_bug_report_marks_rewarded(security_system):
    report = security_system.submit_bug_report(
        reporter_id="user-2",
        title="Medium bug",
        description="Details",
        reported_severity=SeverityLevel.MEDIUM,
    )
    security_system.verify_bug_report(report.report_id, SeverityLevel.MEDIUM, verified_by="auditor")

    rewarded = security_system.reward_bug_report(report.report_id)
    assert rewarded is True
    assert security_system._bug_reports[report.report_id].rewarded is True


def test_security_season_leaderboard_and_rewards(security_system):
    season = security_system.create_security_season("Season One", duration_days=1)
    security_system.update_season_leaderboard(season.season_id, "alice", 1200)
    security_system.update_season_leaderboard(season.season_id, "bob", 800)

    leaderboard = security_system.get_season_leaderboard(season.season_id, top_n=2)
    assert leaderboard[0][0] == "alice"

    rewards = security_system.end_season(season.season_id)
    assert "alice" in rewards
    assert rewards["alice"]["points"] >= 1000


def test_sybil_resistance_checks(security_system):
    profile = security_system._get_or_create_profile("sybil")
    profile.stake_amount = Decimal("50")
    assert security_system._is_sybil_resistant(profile) is False

    profile.identity_verified = True
    assert security_system._is_sybil_resistant(profile) is True


def test_get_gamified_security_system_singleton(monkeypatch):
    monkeypatch.setattr("swarm.gamified_security._gamified_security_system", None)
    from swarm.gamified_security import get_gamified_security_system

    first = get_gamified_security_system()
    second = get_gamified_security_system()
    assert first is second
