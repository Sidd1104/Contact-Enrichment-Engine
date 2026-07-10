"""
src/search/metrics.py
======================
Search Metrics Logger.

Accumulates pipeline search latencies, cache ratios, and provider statuses,
persisting updates to logs/search_metrics.json.
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Dict, Optional

logger = logging.getLogger(__name__)

DEFAULT_METRICS_FILE = Path("logs/search_metrics.json")


class SearchMetrics:
    """
    Manages telemetry data for search operations.
    """

    def __init__(self, metrics_file: Optional[Path] = None) -> None:
        self.metrics_file = metrics_file or DEFAULT_METRICS_FILE
        self.metrics_file.parent.mkdir(parents=True, exist_ok=True)
        self._lock = asyncio.Lock()
        
        # In-memory counters
        self.total_searches = 0
        self.successful_searches = 0
        self.cache_hits = 0
        self.cache_misses = 0
        self.failures = 0
        self.rate_limit_events = 0
        self.total_retries = 0
        self.total_latency = 0.0
        self.provider_usage: Dict[str, int] = {}

    async def record_search(
        self,
        provider: str,
        success: bool,
        latency: float,
        cache_hit: bool,
        retries: int = 0,
        rate_limit_event: bool = False,
    ) -> None:
        """
        Thread-safe logger recording result variables and saving them to file.
        """
        async with self._lock:
            self.total_searches += 1
            if success:
                self.successful_searches += 1
            else:
                self.failures += 1

            if cache_hit:
                self.cache_hits += 1
            else:
                self.cache_misses += 1
                self.total_latency += latency
                
                # Record provider usage for non-cache hits
                self.provider_usage[provider] = self.provider_usage.get(provider, 0) + 1

            if rate_limit_event:
                self.rate_limit_events += 1

            self.total_retries += retries

            await self._save_metrics()

    async def _save_metrics(self) -> None:
        """Write current stats to disk."""
        avg_latency = 0.0
        if self.cache_misses > 0:
            avg_latency = self.total_latency / self.cache_misses

        cache_ratio = 0.0
        if self.total_searches > 0:
            cache_ratio = self.cache_hits / self.total_searches

        report = {
            "summary": {
                "total_searches": self.total_searches,
                "successful_searches": self.successful_searches,
                "failures": self.failures,
                "cache_hits": self.cache_hits,
                "cache_misses": self.cache_misses,
                "cache_hit_ratio": round(cache_ratio, 4),
                "avg_non_cached_latency_seconds": round(avg_latency, 3),
                "total_retries_triggered": self.total_retries,
                "rate_limit_429_events": self.rate_limit_events,
            },
            "providers": self.provider_usage
        }

        try:
            with open(self.metrics_file, "w", encoding="utf-8") as f:
                json.dump(report, f, indent=4)
        except Exception as e:
            logger.error(f"[SearchMetrics] Failed to save search metrics: {e}")

    async def clear(self) -> None:
        """Reset all counters and rewrite file."""
        async with self._lock:
            self.total_searches = 0
            self.successful_searches = 0
            self.cache_hits = 0
            self.cache_misses = 0
            self.failures = 0
            self.rate_limit_events = 0
            self.total_retries = 0
            self.total_latency = 0.0
            self.provider_usage.clear()
            await self._save_metrics()
            logger.info("[SearchMetrics] Metrics cleared.")
