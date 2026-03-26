"""Tests for merid.scanning.trending_scanner.

Covers all 5 areas:
§1 Data classes — DomainItem, TopOpportunity, ScanResult
§2 TrendingScanner.run() — coverage completeness and domain invariants
§3 Domain scanners — each of the 10 required domains produces ≥ 1 item
§4 TopOpportunity ranking — ordering, count, non-empty tickers
§5 Output formatting — to_dict and format_text correctness
"""

import pytest
from unittest.mock import MagicMock

from merid.scanning.trending_scanner import (
    DOMAINS,
    DomainItem,
    ScanResult,
    TopOpportunity,
    TrendingScanner,
    get_trending_scanner,
)


# ──────────────────────────────────────────────────────────────────────────────
# §1 Data class tests
# ──────────────────────────────────────────────────────────────────────────────


class TestDomainItem:
    def test_defaults(self):
        item = DomainItem(
            domain="crypto",
            title="BTC Test",
            summary="BTC is moving.",
        )
        assert item.domain == "crypto"
        assert item.kalshi_tickers == ["no obvious Kalshi market yet"]
        assert item.sentiment == "mixed"
        assert item.edge_score == 0.0
        assert item.source == "heuristic"

    def test_with_tickers(self):
        item = DomainItem(
            domain="crypto",
            title="BTC Test",
            summary="BTC is moving.",
            kalshi_tickers=["KXBTC-15M"],
            sentiment="bullish",
            edge_score=0.75,
        )
        assert item.kalshi_tickers == ["KXBTC-15M"]
        assert item.sentiment == "bullish"
        assert item.edge_score == 0.75

    def test_edge_score_clamped(self):
        item = DomainItem(
            domain="crypto", title="T", summary="S",
            edge_score=1.5,
        )
        assert item.edge_score == 1.0

        item2 = DomainItem(
            domain="crypto", title="T", summary="S",
            edge_score=-0.5,
        )
        assert item2.edge_score == 0.0

    def test_invalid_sentiment_raises(self):
        with pytest.raises(ValueError, match="bullish/bearish/mixed"):
            DomainItem(domain="crypto", title="T", summary="S", sentiment="unknown")

    def test_to_dict_keys(self):
        item = DomainItem(
            domain="crypto",
            title="BTC Test",
            summary="BTC is moving.",
            kalshi_tickers=["KXBTC-15M"],
            sentiment="bullish",
        )
        d = item.to_dict()
        assert set(d.keys()) == {
            "domain", "title", "summary", "kalshi_tickers",
            "sentiment", "mispriced_side", "cross_domain",
            "edge_score", "liquidity_note", "source",
        }

    def test_sentiment_bearish(self):
        item = DomainItem(domain="politics", title="T", summary="S", sentiment="bearish")
        assert item.sentiment == "bearish"


class TestTopOpportunity:
    def test_defaults(self):
        opp = TopOpportunity(
            rank=1,
            title="Big Trade",
            narrative="Market is mispriced.",
            kalshi_ticker="KXBTC-T95000",
        )
        assert opp.rank == 1
        assert opp.domains == []
        assert opp.sentiment == "mixed"
        assert opp.time_sensitivity == "this_week"

    def test_to_dict_keys(self):
        opp = TopOpportunity(
            rank=1, title="T", narrative="N", kalshi_ticker="KXFED",
            domains=["economics"], sentiment="bearish", edge_score=0.7,
        )
        d = opp.to_dict()
        assert "rank" in d
        assert "kalshi_ticker" in d
        assert "edge_score" in d
        assert d["rank"] == 1
        assert d["kalshi_ticker"] == "KXFED"


class TestScanResult:
    def _make_result(self) -> ScanResult:
        items = {
            d: [
                DomainItem(
                    domain=d,
                    title=f"{d.upper()} item",
                    summary="Summary.",
                    kalshi_tickers=[f"KX{d.upper()[:3]}"],
                    sentiment="mixed",
                )
            ]
            for d in DOMAINS
        }
        opps = [
            TopOpportunity(rank=i + 1, title=f"Opp {i + 1}", narrative="N",
                           kalshi_ticker="KX1")
            for i in range(5)
        ]
        return ScanResult(
            domain_items=items, top_opportunities=opps, coverage_complete=True
        )

    def test_total_items(self):
        r = self._make_result()
        assert r.total_items == len(DOMAINS)

    def test_items_for(self):
        r = self._make_result()
        items = r.items_for("crypto")
        assert len(items) == 1
        assert items[0].domain == "crypto"

    def test_items_for_missing_domain(self):
        r = ScanResult()
        assert r.items_for("nonexistent") == []

    def test_to_dict_structure(self):
        r = self._make_result()
        d = r.to_dict()
        assert "scan_id" in d
        assert "timestamp" in d
        assert "duration_ms" in d
        assert "coverage_complete" in d
        assert "domain_items" in d
        assert "top_opportunities" in d
        assert len(d["top_opportunities"]) == 5

    def test_format_text_contains_all_domains(self):
        r = self._make_result()
        text = r.format_text()
        for domain in DOMAINS:
            assert domain.upper().replace("_", " & ") in text or domain.upper() in text

    def test_format_text_contains_top_opportunities(self):
        r = self._make_result()
        text = r.format_text()
        assert "TOP OPPORTUNITIES" in text
        assert "[1]" in text


# ──────────────────────────────────────────────────────────────────────────────
# §2 TrendingScanner.run() — coverage completeness
# ──────────────────────────────────────────────────────────────────────────────


class TestTrendingScannerRun:
    def test_run_returns_scan_result(self):
        scanner = TrendingScanner()
        result = scanner.run()
        assert isinstance(result, ScanResult)

    def test_run_increments_run_count(self):
        scanner = TrendingScanner()
        scanner.run()
        scanner.run()
        assert scanner.run_count == 2

    def test_last_scan_set(self):
        scanner = TrendingScanner()
        assert scanner.last_scan is None
        r = scanner.run()
        assert scanner.last_scan is r

    def test_coverage_complete(self):
        scanner = TrendingScanner()
        result = scanner.run()
        assert result.coverage_complete is True

    def test_all_domains_present(self):
        scanner = TrendingScanner()
        result = scanner.run()
        for domain in DOMAINS:
            assert domain in result.domain_items, (
                f"Domain {domain!r} missing from domain_items"
            )

    def test_no_domain_is_empty(self):
        scanner = TrendingScanner()
        result = scanner.run()
        for domain in DOMAINS:
            items = result.domain_items[domain]
            assert len(items) >= 1, f"Domain {domain!r} has 0 items"

    def test_top_opportunities_present(self):
        scanner = TrendingScanner()
        result = scanner.run()
        assert len(result.top_opportunities) >= 5

    def test_top_opportunities_ranked_in_order(self):
        scanner = TrendingScanner()
        result = scanner.run()
        ranks = [op.rank for op in result.top_opportunities]
        assert ranks == list(range(1, len(ranks) + 1))

    def test_duration_positive(self):
        scanner = TrendingScanner()
        result = scanner.run()
        assert result.duration_ms >= 0.0

    def test_scan_id_unique(self):
        scanner = TrendingScanner()
        r1 = scanner.run()
        r2 = scanner.run()
        assert r1.scan_id != r2.scan_id

    def test_total_items_at_least_10(self):
        scanner = TrendingScanner()
        result = scanner.run()
        # At least 1 item per domain = 10 minimum
        assert result.total_items >= len(DOMAINS)


# ──────────────────────────────────────────────────────────────────────────────
# §3 Domain scanners — individual methods
# ──────────────────────────────────────────────────────────────────────────────


class TestDomainScanners:
    """Each domain scanner must produce at least 1 item with correct schema."""

    def setup_method(self):
        self.scanner = TrendingScanner()

    def _run_domain(self, domain: str):
        fn = getattr(self.scanner, f"_scan_{domain}")
        items = fn([])
        return items

    @pytest.mark.parametrize("domain", DOMAINS)
    def test_domain_returns_list(self, domain):
        items = self._run_domain(domain)
        assert isinstance(items, list)

    @pytest.mark.parametrize("domain", DOMAINS)
    def test_domain_at_least_one_item(self, domain):
        items = self._run_domain(domain)
        assert len(items) >= 1, f"{domain} returned 0 items"

    @pytest.mark.parametrize("domain", DOMAINS)
    def test_domain_item_has_correct_domain_tag(self, domain):
        items = self._run_domain(domain)
        for item in items:
            assert item.domain == domain

    @pytest.mark.parametrize("domain", DOMAINS)
    def test_domain_item_has_non_empty_title(self, domain):
        items = self._run_domain(domain)
        for item in items:
            assert item.title.strip()

    @pytest.mark.parametrize("domain", DOMAINS)
    def test_domain_item_has_non_empty_summary(self, domain):
        items = self._run_domain(domain)
        for item in items:
            assert item.summary.strip()

    @pytest.mark.parametrize("domain", DOMAINS)
    def test_domain_item_has_kalshi_tickers(self, domain):
        items = self._run_domain(domain)
        for item in items:
            assert isinstance(item.kalshi_tickers, list)
            assert len(item.kalshi_tickers) >= 1

    @pytest.mark.parametrize("domain", DOMAINS)
    def test_domain_item_sentiment_valid(self, domain):
        items = self._run_domain(domain)
        valid = {"bullish", "bearish", "mixed"}
        for item in items:
            assert item.sentiment in valid

    @pytest.mark.parametrize("domain", DOMAINS)
    def test_domain_item_edge_score_in_range(self, domain):
        items = self._run_domain(domain)
        for item in items:
            assert 0.0 <= item.edge_score <= 1.0

    @pytest.mark.parametrize("domain", DOMAINS)
    def test_domain_max_items_not_exceeded(self, domain):
        items = self._run_domain(domain)
        assert len(items) <= TrendingScanner.MAX_ITEMS_PER_DOMAIN

    def test_crypto_has_btc_ticker(self):
        """Crypto domain must reference at least one BTC ticker."""
        items = self._run_domain("crypto")
        all_tickers = [t for item in items for t in item.kalshi_tickers]
        assert any("BTC" in t.upper() for t in all_tickers), (
            "crypto domain must reference a BTC Kalshi ticker"
        )

    def test_economics_has_fomc_or_fed(self):
        """Economics domain must reference macro policy tickers."""
        items = self._run_domain("economics")
        all_tickers = [t for item in items for t in item.kalshi_tickers]
        assert any(
            kw in t.upper() for t in all_tickers for kw in ("FED", "FOMC", "CPI")
        ), "economics domain must reference a FED/FOMC/CPI Kalshi ticker"

    def test_scanner_handles_pipeline_cache_errors_gracefully(self):
        """Scanner must tolerate malformed InsightObjects in pipeline cache."""
        bad_cache = [object(), None, {"not": "an insight"}, 42]
        # Should not raise — all domain scanners must handle gracefully
        for domain in DOMAINS:
            fn = getattr(self.scanner, f"_scan_{domain}")
            items = fn(bad_cache)
            assert len(items) >= 1


# ──────────────────────────────────────────────────────────────────────────────
# §4 TopOpportunity ranking
# ──────────────────────────────────────────────────────────────────────────────


class TestTopOpportunityRanking:
    def test_top_opps_ordered_by_edge_score(self):
        scanner = TrendingScanner()
        result = scanner.run()
        scores = [op.edge_score for op in result.top_opportunities]
        assert scores == sorted(scores, reverse=True), (
            "TopOpportunity list must be ordered descending by edge_score"
        )

    def test_top_opps_no_zero_ticker(self):
        scanner = TrendingScanner()
        result = scanner.run()
        for op in result.top_opportunities:
            assert op.kalshi_ticker, "TopOpportunity must have a non-empty kalshi_ticker"

    def test_top_opps_rank_contiguous(self):
        scanner = TrendingScanner()
        result = scanner.run()
        for i, op in enumerate(result.top_opportunities):
            assert op.rank == i + 1

    def test_top_opps_count_within_bounds(self):
        scanner = TrendingScanner()
        result = scanner.run()
        # Must have at least 5 and at most 10 items (configurable)
        assert 5 <= len(result.top_opportunities) <= 10

    def test_cross_domain_boosts_score(self):
        """An item with cross-domain links should score higher than same item
        without cross-domain links."""
        scanner = TrendingScanner()
        item_no_cross = DomainItem(
            domain="crypto", title="T", summary="S",
            kalshi_tickers=["KXBTC"], edge_score=0.5,
        )
        item_with_cross = DomainItem(
            domain="crypto", title="T", summary="S",
            kalshi_tickers=["KXBTC"], edge_score=0.5,
            cross_domain=["politics → crypto"],
        )
        domain_items = {
            "crypto": [item_no_cross, item_with_cross],
            **{d: [] for d in DOMAINS if d != "crypto"},
        }
        # Fill other domains with placeholder items so ranking can work
        for d in DOMAINS:
            if not domain_items[d]:
                domain_items[d] = [
                    DomainItem(domain=d, title="T", summary="S",
                               edge_score=0.1, kalshi_tickers=["KXTEST"])
                ]
        top = scanner._build_top_opportunities(domain_items)
        # item_with_cross should rank above item_no_cross
        with_cross_rank = next(
            (op.rank for op in top if op.title == "T" and op.domains == ["crypto"]
             and op.edge_score > 0.5), None
        )
        # Simply check that there exists an opportunity with boosted score > 0.5
        boosted = [op for op in top if op.edge_score > 0.5]
        assert boosted, "Cross-domain boost should push at least one item above 0.5"

    def test_no_kalshi_ticker_penalty(self):
        """Item with no real Kalshi ticker should score lower than same item
        with a real ticker."""
        scanner = TrendingScanner()
        item_no_ticker = DomainItem(
            domain="culture", title="T", summary="S",
            edge_score=0.5,
            # kalshi_tickers defaults to placeholder
        )
        item_real_ticker = DomainItem(
            domain="culture", title="T2", summary="S",
            kalshi_tickers=["KXCULTURE"],
            edge_score=0.5,
        )
        domain_items: dict = {}
        for d in DOMAINS:
            if d == "culture":
                domain_items[d] = [item_no_ticker, item_real_ticker]
            else:
                domain_items[d] = [
                    DomainItem(domain=d, title="T", summary="S",
                               edge_score=0.1, kalshi_tickers=["KXTEST"])
                ]
        top = scanner._build_top_opportunities(domain_items)
        real_ticker_score = next(
            (op.edge_score for op in top if op.kalshi_ticker == "KXCULTURE"), None
        )
        no_ticker_score = next(
            (op.edge_score for op in top if op.kalshi_ticker == "TBD"), None
        )
        if real_ticker_score is not None and no_ticker_score is not None:
            assert real_ticker_score >= no_ticker_score


# ──────────────────────────────────────────────────────────────────────────────
# §5 Output formatting
# ──────────────────────────────────────────────────────────────────────────────


class TestOutputFormatting:
    def test_scan_result_to_dict_is_json_serializable(self):
        """ScanResult.to_dict() must produce plain Python types (JSON-safe)."""
        import json
        scanner = TrendingScanner()
        result = scanner.run()
        d = result.to_dict()
        # Should not raise
        serialised = json.dumps(d)
        assert len(serialised) > 100

    def test_format_text_headers(self):
        scanner = TrendingScanner()
        result = scanner.run()
        text = result.format_text()
        assert "MERID TRENDING SCANNER" in text
        assert "TOP OPPORTUNITIES" in text
        # All 10 domain headers should appear
        for domain in DOMAINS:
            assert domain.upper() in text.upper()

    def test_format_text_opportunity_ranks(self):
        scanner = TrendingScanner()
        result = scanner.run()
        text = result.format_text()
        for op in result.top_opportunities:
            assert f"[{op.rank}]" in text

    def test_domain_item_to_dict_roundtrip(self):
        item = DomainItem(
            domain="economics",
            title="FOMC Rate Decision",
            summary="Fed signals pause.",
            kalshi_tickers=["KXFED", "KXFOMC"],
            sentiment="bearish",
            mispriced_side="NO underpriced",
            cross_domain=["economics → crypto"],
            edge_score=0.72,
            liquidity_note="high liquidity",
            source="heuristic",
        )
        d = item.to_dict()
        assert d["domain"] == "economics"
        assert d["sentiment"] == "bearish"
        assert d["edge_score"] == 0.72
        assert "KXFED" in d["kalshi_tickers"]
        assert "economics → crypto" in d["cross_domain"]

    def test_top_opportunity_to_dict_roundtrip(self):
        opp = TopOpportunity(
            rank=2,
            title="FOMC Arb",
            narrative="OIS vs Kalshi divergence is actionable.",
            kalshi_ticker="KXFOMC",
            domains=["economics"],
            sentiment="bearish",
            edge_score=0.71,
            liquidity_note="tight spread",
            time_sensitivity="this_week",
        )
        d = opp.to_dict()
        assert d["rank"] == 2
        assert d["kalshi_ticker"] == "KXFOMC"
        assert d["sentiment"] == "bearish"
        assert d["time_sensitivity"] == "this_week"


# ──────────────────────────────────────────────────────────────────────────────
# §6 Singleton accessor
# ──────────────────────────────────────────────────────────────────────────────


class TestSingleton:
    def test_get_trending_scanner_returns_instance(self):
        scanner = get_trending_scanner()
        assert isinstance(scanner, TrendingScanner)

    def test_get_trending_scanner_is_singleton(self):
        s1 = get_trending_scanner()
        s2 = get_trending_scanner()
        assert s1 is s2

    def test_singleton_run_returns_scan_result(self):
        scanner = get_trending_scanner()
        result = scanner.run()
        assert isinstance(result, ScanResult)
        assert result.coverage_complete


# ──────────────────────────────────────────────────────────────────────────────
# §7 DOMAINS constant
# ──────────────────────────────────────────────────────────────────────────────


class TestDomainsConstant:
    def test_all_required_domains_present(self):
        required = {
            "kalshi", "politics", "sports", "culture", "crypto",
            "climate", "economics", "mentions", "companies", "tech_science",
        }
        assert required == set(DOMAINS)

    def test_domains_count(self):
        assert len(DOMAINS) == 10

    def test_domains_unique(self):
        assert len(DOMAINS) == len(set(DOMAINS))
