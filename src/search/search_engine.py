"""
src/search/search_engine.py
============================
Website Discovery Search Engine.

Main API for resolving business homepages.
Coordinates caches, provider routers, ranking heuristics, validation, and metrics.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

from .search_result import SearchResolution
from .provider_router import ProviderRouter
from .domain_ranker import DomainRanker
from .search_validator import SearchValidator
from .cache_manager import SearchCache, FileSearchCache
from .metrics import SearchMetrics
from .search_provider import SearchProvider
from .retry_handler import FatalSearchError, TransientSearchError

logger = logging.getLogger(__name__)


class SearchEngine:
    """
    Search Engine orchestrating website discovery.
    """

    def __init__(
        self,
        router: ProviderRouter,
        cache: Optional[SearchCache] = None,
        metrics: Optional[SearchMetrics] = None,
        ranker: Optional[DomainRanker] = None,
    ) -> None:
        self.router = router
        self.cache = cache or FileSearchCache()
        self.metrics = metrics or SearchMetrics()
        self.ranker = ranker or DomainRanker()
        self.validator = SearchValidator()

    def construct_query(
        self,
        business_name: str,
        city: Optional[str] = None,
        state: Optional[str] = None,
        country: Optional[str] = None,
    ) -> str:
        """
        Formulate search query without using LLMs.
        
        Examples:
          - "Gregory Waterson Detroit MI website"
          - "Three Rivers Marine Woodinville Washington website"
        """
        # Clean business name
        query_parts = [business_name.strip()]

        # Inject location hints if available
        location = []
        if city:
            location.append(city.strip())
        if state:
            location.append(state.strip())
        if country and country.lower() != "us" and country.lower() != "united states":
            location.append(country.strip())
            
        if location:
            query_parts.append(" ".join(location))
            
        query_parts.append("website")
        return " ".join(query_parts)

    async def resolve_website(
        self,
        business_name: str,
        existing_website: Optional[str] = None,
        city: Optional[str] = None,
        state: Optional[str] = None,
        country: Optional[str] = None,
    ) -> SearchResolution:
        """
        Main entrypoint resolving a business name to an official website URL.
        """
        start_time = time.monotonic()
        
        # 1. Skip search if website is already populated in spreadsheet
        if existing_website and existing_website.strip() and existing_website.lower() not in ("nan", "none", "n/a", "-"):
            clean_url = self.validator.sanitize_url(existing_website)
            if self.validator.is_valid_url(clean_url):
                logger.info(f"[SearchEngine] Skipping search: website already exists for '{business_name}' -> '{clean_url}'")
                res = SearchResolution(
                    query="",
                    resolved_url=clean_url,
                    confidence_score=1.0,
                    provider_used="dataset",
                    latency=0.0,
                    cache_hit=False,
                    status="skipped"
                )
                await self.metrics.record_search(provider="dataset", success=True, latency=0.0, cache_hit=True)
                return res

        # 2. Formulate query
        query = self.construct_query(business_name, city, state, country)
        
        # 3. Check cache
        if self.cache:
            cached = await self.cache.get(query)
            if cached:
                latency = time.monotonic() - start_time
                res = SearchResolution(
                    query=query,
                    resolved_url=cached["resolved_url"],
                    confidence_score=cached["confidence_score"],
                    provider_used="cache",
                    latency=latency,
                    cache_hit=True,
                    status="success"
                )
                await self.metrics.record_search(provider="cache", success=True, latency=latency, cache_hit=True)
                return res

        # 4. Route query to available search providers in priority fallback loop
        last_error = None
        providers_tried = 0
        max_providers_to_try = len(self.router.get_providers())
        
        while providers_tried < max_providers_to_try:
            provider = self.router.select_provider()
            if not provider:
                break
                
            providers_tried += 1
            logger.info(f"[SearchEngine] Discovering website for '{business_name}' via provider '{provider.name}'")
            
            try:
                candidates = await provider.search(query, limit=5)
                
                # Rank candidates
                ranked = self.ranker.rank_candidates(candidates, business_name, city, state)
                
                resolved_url = ""
                confidence = 0.0
                
                if ranked:
                    top_url, confidence = ranked[0]
                    resolved_url = self.validator.sanitize_url(top_url)
                    if not self.validator.is_valid_url(resolved_url):
                        resolved_url = ""
                        confidence = 0.0

                latency = time.monotonic() - start_time

                # 5. Save result to cache
                if self.cache and resolved_url:
                    await self.cache.set(query, resolved_url, confidence, provider.name)

                # Record success metrics
                await self.metrics.record_search(
                    provider=provider.name,
                    success=True,
                    latency=latency,
                    cache_hit=False
                )

                return SearchResolution(
                    query=query,
                    resolved_url=resolved_url,
                    confidence_score=confidence,
                    provider_used=provider.name,
                    latency=latency,
                    cache_hit=False,
                    status="success"
                )

            except (FatalSearchError, TransientSearchError, Exception) as e:
                latency = time.monotonic() - start_time
                err_name = type(e).__name__
                logger.error(
                    f"[SearchEngine] Provider '{provider.name}' failed with {err_name}: {e}. "
                    f"Trying fallback..."
                )
                
                # Penalize/cool down provider so it won't be immediately reselected in this process run
                provider.record_failure()
                if "429" in str(e) or "432" in str(e):
                    provider.trigger_cooldown(300.0)
                
                # Record failure metrics for this provider
                rate_limit = "RateLimit" in err_name or "429" in str(e) or "432" in str(e)
                await self.metrics.record_search(
                    provider=provider.name,
                    success=False,
                    latency=latency,
                    cache_hit=False,
                    rate_limit_event=rate_limit
                )
                last_error = e
                continue

        # If all providers in fallback chain failed
        latency = time.monotonic() - start_time
        err_msg = f"All providers failed. Last error: {last_error}" if last_error else "No search providers available."
        
        return SearchResolution(
            query=query,
            resolved_url="",
            confidence_score=0.0,
            provider_used="",
            latency=latency,
            cache_hit=False,
            status="failed",
            error_message=err_msg
        )
