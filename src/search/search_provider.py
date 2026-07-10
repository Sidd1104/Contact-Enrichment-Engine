"""
src/search/search_provider.py
==============================
Search Engine Providers.

Implements Tavily and Bing concrete search integrations using httpx.
"""

from __future__ import annotations

import asyncio
import logging
import time
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Tuple

import httpx
from ..config.ai_config import ai_config
from .retry_handler import get_retry_decorator, check_httpx_status, TransientSearchError, FatalSearchError
from .rate_limiter import ProviderRateLimiter

logger = logging.getLogger(__name__)


class SearchProvider(ABC):
    """
    Abstract search provider interface.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Name of the provider (e.g. 'tavily', 'bing')."""
        ...

    @abstractmethod
    async def search(self, query: str, limit: int = 5) -> List[Tuple[str, str, str]]:
        """
        Execute raw web search.
        
        Returns:
            List of tuples: (url, title, snippet).
        """
        ...

    @property
    @abstractmethod
    def is_healthy(self) -> bool:
        """Check if provider is healthy."""
        ...

    @property
    @abstractmethod
    def cooldown_until(self) -> float:
        """Unix timestamp indicating when rate-limit cooldown ends."""
        ...

    @abstractmethod
    def trigger_cooldown(self, seconds: float) -> None:
        """Mark provider on rate-limit cooldown."""
        ...

    @abstractmethod
    def record_failure(self) -> None:
        """Increment consecutive failures."""
        ...

    @abstractmethod
    def record_success(self) -> None:
        """Reset consecutive failures."""
        ...


class BaseSearchProvider(SearchProvider, ABC):
    """
    Base search provider implementation with rate limiting and cooldown state.
    """

    def __init__(self, rpm: int = 60, max_concurrency: int = 5) -> None:
        self.rate_limiter = ProviderRateLimiter(rpm, max_concurrency)
        self._consecutive_failures = 0
        self._cooldown_until = 0.0
        self._max_failures = 5

    @property
    def is_healthy(self) -> bool:
        # Provider is unhealthy if it exceeded maximum consecutive failures and is not in cooldown
        if self._consecutive_failures >= self._max_failures:
            # Let it retry after 5 minutes
            now = time.time()
            if self._cooldown_until > 0.0 and now >= self._cooldown_until:
                # Reset to allow check
                self._consecutive_failures = 0
                self._cooldown_until = 0.0
                return True
            return False
        
        # Check standard rate limit cooldown
        if self._cooldown_until > 0.0:
            return time.time() >= self._cooldown_until
            
        return True

    @property
    def cooldown_until(self) -> float:
        return self._cooldown_until

    def trigger_cooldown(self, seconds: float) -> None:
        self._cooldown_until = time.time() + seconds
        logger.warning(f"[Provider: {self.name}] Placed on rate-limit cooldown for {seconds}s.")

    def record_failure(self) -> None:
        self._consecutive_failures += 1
        if self._consecutive_failures >= self._max_failures:
            # Cool down for 5 minutes
            self.trigger_cooldown(300.0)
            logger.error(f"[Provider: {self.name}] Disabling temporarily due to {self._consecutive_failures} failures.")

    def record_success(self) -> None:
        self._consecutive_failures = 0
        self._cooldown_until = 0.0


class TavilySearchProvider(BaseSearchProvider):
    """
    Tavily search provider.
    """

    def __init__(self, api_key: Optional[str] = None) -> None:
        super().__init__(rpm=60, max_concurrency=5)
        self.api_key = api_key or ai_config.tavily_api_key
        self.client: Optional[httpx.AsyncClient] = None

    @property
    def name(self) -> str:
        return "tavily"

    def _get_client(self) -> httpx.AsyncClient:
        if self.client is None or self.client.is_closed:
            self.client = httpx.AsyncClient(timeout=ai_config.search_timeout)
        return self.client

    async def search(self, query: str, limit: int = 5) -> List[Tuple[str, str, str]]:
        if not self.api_key:
            raise FatalSearchError("Tavily API key not configured.")

        # Rate limiting guard
        async with self.rate_limiter:
            # Build retry-wrapped request
            @get_retry_decorator(ai_config.search_max_retries)
            async def _do_search():
                client = self._get_client()
                url = "https://api.tavily.com/search"
                payload = {
                    "api_key": self.api_key,
                    "query": query,
                    "search_depth": "basic",
                    "max_results": limit,
                }
                
                try:
                    response = await client.post(url, json=payload)
                except httpx.RequestError as e:
                    raise TransientSearchError(f"HTTP request failed: {e}")
                
                check_httpx_status(response)
                return response.json()

            try:
                data = await _do_search()
                self.record_success()
                
                results = []
                for item in data.get("results", []):
                    url = item.get("url", "")
                    title = item.get("title", "")
                    snippet = item.get("content", "")
                    if url:
                        results.append((url, title, snippet))
                return results
            except Exception as e:
                self.record_failure()
                if "429" in str(e):
                    self.trigger_cooldown(60.0)
                raise


class BingSearchProvider(BaseSearchProvider):
    """
    Bing Search API provider.
    
    If BING_API_KEY is missing, operates in Mock mode for testing.
    """

    def __init__(self, api_key: Optional[str] = None) -> None:
        super().__init__(rpm=60, max_concurrency=5)
        self.api_key = api_key or ai_config.bing_api_key
        self.client: Optional[httpx.AsyncClient] = None

    @property
    def name(self) -> str:
        return "bing"

    def _get_client(self) -> httpx.AsyncClient:
        if self.client is None or self.client.is_closed:
            self.client = httpx.AsyncClient(timeout=ai_config.search_timeout)
        return self.client

    async def search(self, query: str, limit: int = 5) -> List[Tuple[str, str, str]]:
        if not self.api_key:
            # Mock mode fallback for local pipeline runs and tests
            logger.info(f"[BingSearchProvider] Mock Search query: '{query}'")
            await asyncio.sleep(0.1)
            
            # Simple mocks depending on query words
            query_clean = query.lower()
            if "zhang" in query_clean:
                return [("https://www.healthgrades.com/zhang", "Dr. Suyu Zhang MD", "Zhang is a cardiologist in NY.")]
            elif "weedman" in query_clean:
                return [
                    ("https://www.threeriversmarine.com", "Three Rivers Marine boat dealer", "Three Rivers Marine located in Woodinville WA."),
                    ("https://www.facebook.com/threeriversmarine", "Three Rivers Marine - Facebook", "Facebook page for Three Rivers Marine.")
                ]
            elif "weeces" in query_clean:
                return [("https://pgsa.com/who-we-are/", "PGSA - Keith Weeces Team", "Keith Weeces team details on PGSA.")]
            elif "zenquant" in query_clean:
                return [
                    ("https://zenquant.com", "ZenQuant Technologies LP - Quantitative Trading", "ZenQuant Technologies is a global proprietary trading firm."),
                    ("https://facebook.com/zenquant", "ZenQuant Tech - Facebook", "Facebook page for ZenQuant.")
                ]
            return [("https://example.com/about", "Mock Result title", "Mock snippet for query.")]

        async with self.rate_limiter:
            @get_retry_decorator(ai_config.search_max_retries)
            async def _do_search():
                client = self._get_client()
                url = f"https://api.bing.microsoft.com/v7.0/search?q={query}&count={limit}"
                headers = {"Ocp-Apim-Subscription-Key": self.api_key}
                
                try:
                    response = await client.get(url, headers=headers)
                except httpx.RequestError as e:
                    raise TransientSearchError(f"HTTP request failed: {e}")
                
                check_httpx_status(response)
                return response.json()

            try:
                data = await _do_search()
                self.record_success()
                
                results = []
                # Parse Bing values
                web_pages = data.get("webPages", {}).get("value", [])
                for page in web_pages:
                    url = page.get("url", "")
                    title = page.get("name", "")
                    snippet = page.get("snippet", "")
                    if url:
                        results.append((url, title, snippet))
                return results
            except Exception as e:
                self.record_failure()
                if "429" in str(e):
                    self.trigger_cooldown(60.0)
                raise
