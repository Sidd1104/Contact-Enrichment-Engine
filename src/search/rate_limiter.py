"""
src/search/rate_limiter.py
===========================
Provider Rate Limiter.

Coordinates request-per-minute (RPM) limits and concurrent task allocations
asynchronously using semaphores and sliding windows.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Dict, List

logger = logging.getLogger(__name__)


class ProviderRateLimiter:
    """
    Limits API queries per provider.
    """

    def __init__(self, rpm_limit: int = 60, max_concurrency: int = 5) -> None:
        self.rpm_limit = rpm_limit
        self.max_concurrency = max_concurrency
        self._semaphore = asyncio.Semaphore(max_concurrency)
        self._request_timestamps: List[float] = []
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        """
        Wait until a rate-limit slot and concurrency slot are available.
        """
        # 1. Acquire concurrency semaphore slot
        await self._semaphore.acquire()

        # 2. Acquire RPM window slot
        acquired = False
        while not acquired:
            async with self._lock:
                now = time.monotonic()
                
                # Filter out timestamps older than 60 seconds
                self._request_timestamps = [t for t in self._request_timestamps if now - t < 60.0]
                
                if len(self._request_timestamps) < self.rpm_limit:
                    self._request_timestamps.append(now)
                    acquired = True
                    break
            
            # If rate limited, sleep briefly and try again
            await asyncio.sleep(0.1)

    def release(self) -> None:
        """Release concurrency slot."""
        self._semaphore.release()

    async def __aenter__(self) -> ProviderRateLimiter:
        await self.acquire()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> bool:
        self.release()
        return False
