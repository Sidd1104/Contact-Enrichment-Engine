"""
tests/test_search_engine.py
============================
Unit tests for the Website Discovery Search Engine (Phase 2C).

Covers:
  - Cache hits, misses, and file-cache serializations.
  - Domain ranking keyword scoring and directory exclusions.
  - Rate limiter sliding windows and concurrency.
  - Provider router priority resolution.
  - Search manager batched concurrent mappings.
  - Telemetry metrics compilation.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.search.domain_ranker import DomainRanker
from src.search.search_validator import SearchValidator
from src.search.cache_manager import FileSearchCache
from src.search.metrics import SearchMetrics
from src.search.rate_limiter import ProviderRateLimiter
from src.search.retry_handler import TransientSearchError, FatalSearchError, get_retry_decorator
from src.search.search_provider import SearchProvider
from src.search.provider_router import ProviderRouter
from src.search.search_engine import SearchEngine
from src.search.search_manager import SearchManager


# =============================================================================
# Mock Provider for Router / Engine Testing
# =============================================================================

class MockSearchProvider(SearchProvider):
    """Mock search API provider."""

    def __init__(self, name: str = "mock", results: list = None) -> None:
        self._name = name
        self._results = results or []
        self._is_healthy = True
        self._cooldown_until = 0.0
        self._success_calls = 0
        self._failure_calls = 0

    @property
    def name(self) -> str:
        return self._name

    async def search(self, query: str, limit: int = 5) -> List[Tuple[str, str, str]]:
        if not self._is_healthy:
            raise TransientSearchError("Provider unhealthy")
        return self._results[:limit]

    @property
    def is_healthy(self) -> bool:
        return self._is_healthy

    @property
    def cooldown_until(self) -> float:
        return self._cooldown_until

    def trigger_cooldown(self, seconds: float) -> None:
        import time
        self._cooldown_until = time.time() + seconds

    def record_failure(self) -> None:
        self._failure_calls += 1

    def record_success(self) -> None:
        self._success_calls += 1


# =============================================================================
# Test: DomainRanker
# =============================================================================

class TestDomainRanker:
    """Test domain exclusions and scoring algorithms."""

    def test_extract_domain(self):
        ranker = DomainRanker()
        assert ranker.extract_domain("https://www.google.com/search?q=abc") == "google.com"
        assert ranker.extract_domain("http://blog.company.co.uk/about") == "blog.company.co.uk"

    def test_social_blacklist(self):
        ranker = DomainRanker()
        assert ranker.is_blacklisted("https://www.facebook.com/mybusiness") is True
        assert ranker.is_blacklisted("https://linkedin.com/in/doctor") is True
        assert ranker.is_blacklisted("https://www.doctor-clinic.com/about") is False

    def test_ranking_scores(self):
        ranker = DomainRanker()
        biz_name = "ZenQuant Technologies"
        
        # High match score (contains name in domain, root homepage)
        score1 = ranker.calculate_score(
            candidate_url="https://zenquant.com",
            title="ZenQuant Technologies - Quantitative Trading",
            snippet="ZenQuant Technologies LP is a trading firm.",
            business_name=biz_name
        )
        # Lower match score (unrelated domain, deep folder path)
        score2 = ranker.calculate_score(
            candidate_url="https://news-aggregator.com/finance/firm/details/zenquant",
            title="ZenQuant LP news updates",
            snippet="Some details about ZenQuant.",
            business_name=biz_name
        )
        assert score1 > score2
        assert score1 > 0.5


# =============================================================================
# Test: SearchValidator
# =============================================================================

class TestSearchValidator:
    """Test standardizing protocols and domain checks."""

    def test_sanitize_url(self):
        val = SearchValidator()
        assert val.sanitize_url("google.com") == "https://google.com"
        assert val.sanitize_url("http://company.com/home/?ref=abc") == "http://company.com/home"

    def test_is_valid_url(self):
        val = SearchValidator()
        assert val.is_valid_url("https://company.com") is True
        assert val.is_valid_url("http://a.b") is False
        assert val.is_valid_url("not_a_url") is False


# =============================================================================
# Test: FileSearchCache
# =============================================================================

class TestFileSearchCache:
    """Test cache operations and disk writes."""

    @pytest.mark.asyncio
    async def test_cache_hits_and_misses(self):
        with TemporaryDirectory() as temp_dir:
            cache = FileSearchCache(temp_dir)
            
            # Check miss
            assert await cache.get("sample query") is None

            # Set cache
            await cache.set(
                query="sample query",
                resolved_url="https://sample.com",
                confidence=0.9,
                provider="tavily"
            )

            # Check hit
            hit = await cache.get("sample query")
            assert hit is not None
            assert hit["resolved_url"] == "https://sample.com"
            assert hit["confidence_score"] == 0.9
            assert hit["provider_used"] == "tavily"


# =============================================================================
# Test: SearchMetrics
# =============================================================================

class TestSearchMetrics:
    """Test telemetry logger updates and file writes."""

    @pytest.mark.asyncio
    async def test_metrics_serialization(self):
        with TemporaryDirectory() as temp_dir:
            metrics_file = Path(temp_dir) / "metrics.json"
            metrics = SearchMetrics(metrics_file)

            await metrics.record_search(
                provider="tavily",
                success=True,
                latency=1.2,
                cache_hit=False,
                retries=1
            )
            await metrics.record_search(
                provider="cache",
                success=True,
                latency=0.01,
                cache_hit=True
            )

            assert metrics.total_searches == 2
            assert metrics.cache_hits == 1
            assert metrics.cache_misses == 1

            # Check file
            assert metrics_file.exists()
            with open(metrics_file, "r") as f:
                data = json.load(f)
            assert data["summary"]["total_searches"] == 2
            assert data["summary"]["cache_hits"] == 1


# =============================================================================
# Test: ProviderRouter
# =============================================================================

class TestProviderRouter:
    """Test routing prioritizations."""

    def test_select_router_provider(self):
        prov1 = MockSearchProvider("tavily")
        prov2 = MockSearchProvider("bing")
        
        router = ProviderRouter([prov1, prov2], ["tavily", "bing"])
        
        # Primary healthy -> pick tavily
        assert router.select_provider().name == "tavily"

        # Mark primary unhealthy -> pick fallback bing
        prov1._is_healthy = False
        assert router.select_provider().name == "bing"


# =============================================================================
# Test: RateLimiter
# =============================================================================

class TestProviderRateLimiter:
    """Test sliding window concurrency."""

    @pytest.mark.asyncio
    async def test_rate_limiter_concurrency(self):
        # 2 concurrent limit
        limiter = ProviderRateLimiter(rpm_limit=10, max_concurrency=2)
        
        # Should be able to acquire twice
        await limiter.acquire()
        await limiter.acquire()

        # Third attempt should block (simulate timeout check)
        task = asyncio.create_task(limiter.acquire())
        done, pending = await asyncio.wait([task], timeout=0.1)
        assert len(pending) == 1  # Still blocked

        # Release one -> third should acquire
        limiter.release()
        done, pending = await asyncio.wait([task], timeout=0.1)
        assert len(done) == 1
        limiter.release()
        limiter.release()


# =============================================================================
# Test: SearchEngine & SearchManager Orchestration
# =============================================================================

class TestSearchEngineOrchestrator:
    """Test coordination of resolves and batched runs."""

    @pytest.mark.asyncio
    async def test_resolve_skipped_when_website_exists(self):
        prov = MockSearchProvider("tavily")
        router = ProviderRouter([prov], ["tavily"])
        engine = SearchEngine(router)

        # Existing valid url in sheet -> skips query
        res = await engine.resolve_website("Name", existing_website="http://my-site.com")
        assert res.status == "skipped"
        assert res.resolved_url == "http://my-site.com"
        assert res.provider_used == "dataset"

    @pytest.mark.asyncio
    async def test_resolve_runs_search_and_ranks(self):
        results = [
            ("https://facebook.com/doctorsmith", "Dr Smith FB", "FB page"), # blacklisted
            ("https://dr-smith-cardiology.com", "Dr. Smith Cardiology", "NY official clinic homepage"), # target
        ]
        prov = MockSearchProvider("tavily", results)
        router = ProviderRouter([prov], ["tavily"])
        
        with TemporaryDirectory() as temp_dir:
            cache = FileSearchCache(temp_dir)
            engine = SearchEngine(router, cache=cache)

            res = await engine.resolve_website("Dr. Smith Cardiology", city="NY")
            assert res.status == "success"
            # Standardized target url, facebook skipped
            assert res.resolved_url == "https://dr-smith-cardiology.com"
            assert res.confidence_score > 0.3
            assert res.provider_used == "tavily"

            # Re-query should trigger cache hit
            res2 = await engine.resolve_website("Dr. Smith Cardiology", city="NY")
            assert res2.cache_hit is True
            assert res2.provider_used == "cache"

    @pytest.mark.asyncio
    async def test_search_manager_batch(self):
        prov = MockSearchProvider("tavily", [("https://test-site.com", "Title", "Desc")])
        router = ProviderRouter([prov], ["tavily"])
        
        with TemporaryDirectory() as temp_dir:
            cache = FileSearchCache(temp_dir)
            engine = SearchEngine(router, cache=cache)
            manager = SearchManager(engine, max_concurrency=2)

            batch = [
                {"first_name": "Gregory", "last_name": "Waterson", "website": "", "city": "Detroit"},
                {"first_name": "Suyu", "last_name": "Zhang", "website": "https://active-site.com"}, # skipped
                {"company_name": "Three Rivers Marine", "website": ""},
            ]

            updated = await manager.resolve_batch(batch)
            assert len(updated) == 3
            assert updated[1]["website"] == "https://active-site.com" # preserved
            assert updated[0]["website"] == "https://test-site.com"
            assert updated[2]["website"] == "https://test-site.com"
            assert "search_resolution" in updated[0]
