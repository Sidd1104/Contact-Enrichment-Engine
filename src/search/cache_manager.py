"""
src/search/cache_manager.py
============================
Persistent Search Cache Layer.

Stores and retrieves discovered websites locally in a JSON index file.
Thread-safe using asyncio.Lock.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
import json
import logging
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Dict, Optional
from ..config.ai_config import ai_config

logger = logging.getLogger(__name__)


class SearchCache(ABC):
    """
    Abstract search cache interface.
    """

    @abstractmethod
    async def get(self, query: str) -> Optional[Dict[str, Any]]:
        """Get cache entry if it exists."""
        ...

    @abstractmethod
    async def set(
        self,
        query: str,
        resolved_url: str,
        confidence: float,
        provider: str,
    ) -> None:
        """Store key resolution details in cache."""
        ...

    @abstractmethod
    async def clear(self) -> None:
        """Clear cache entries."""
        ...


class FileSearchCache(SearchCache):
    """
    Local JSON-file based persistent search cache.
    """

    def __init__(self, cache_dir: Optional[str] = None) -> None:
        self.cache_dir = Path(cache_dir or ai_config.search_cache_directory)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.cache_file = self.cache_dir / "search_cache.json"
        self._lock = asyncio.Lock()
        self._cache_data: Dict[str, Dict[str, Any]] = {}
        self._loaded = False

    async def _load_cache(self) -> None:
        """Load cache file contents in memory (internal method)."""
        if self._loaded:
            return
        if not self.cache_file.exists():
            self._cache_data = {}
            self._loaded = True
            return

        try:
            # We do it synchronously inside lock since it is a fast file load
            with open(self.cache_file, "r", encoding="utf-8") as f:
                self._cache_data = json.load(f)
            self._loaded = True
            logger.info(f"[FileSearchCache] Loaded {len(self._cache_data)} cache entries from {self.cache_file.name}")
        except Exception as e:
            logger.error(f"[FileSearchCache] Failed to load cache file {self.cache_file}: {e}")
            self._cache_data = {}
            self._loaded = True

    async def _save_cache(self) -> None:
        """Save memory cache back to disk (internal method)."""
        try:
            with open(self.cache_file, "w", encoding="utf-8") as f:
                json.dump(self._cache_data, f, indent=4)
        except Exception as e:
            logger.error(f"[FileSearchCache] Failed to write cache file: {e}")

    async def get(self, query: str) -> Optional[Dict[str, Any]]:
        """Retrieve resolution details for query from the cache."""
        if not ai_config.search_cache_enabled:
            return None

        async with self._lock:
            await self._load_cache()
            clean_query = query.strip().lower()
            entry = self._cache_data.get(clean_query)
            if entry:
                logger.debug(f"[FileSearchCache] Cache HIT for: '{query}' -> '{entry.get('resolved_url')}'")
                return entry
            return None

    async def set(
        self,
        query: str,
        resolved_url: str,
        confidence: float,
        provider: str,
    ) -> None:
        """Cache query resolution details to file."""
        if not ai_config.search_cache_enabled:
            return

        async with self._lock:
            await self._load_cache()
            clean_query = query.strip().lower()
            self._cache_data[clean_query] = {
                "query": query,
                "resolved_url": resolved_url,
                "confidence_score": confidence,
                "provider_used": provider,
                "timestamp": datetime.now().isoformat(),
            }
            await self._save_cache()
            logger.debug(f"[FileSearchCache] Cache SET for: '{query}' -> '{resolved_url}'")

    async def clear(self) -> None:
        """Wipe cache database."""
        async with self._lock:
            self._cache_data = {}
            await self._save_cache()
            logger.info("[FileSearchCache] Cache wiped successfully.")


class FileCrawlCache:
    """
    Local JSON-file based persistent crawl cache mapping Website URL -> ScrapedPage data.
    """

    def __init__(self, cache_dir: Optional[str] = None) -> None:
        self.cache_dir = Path(cache_dir or ai_config.search_cache_directory)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.cache_file = self.cache_dir / "crawl_cache.json"
        self._lock = asyncio.Lock()
        self._cache_data: Dict[str, Dict[str, Any]] = {}
        self._loaded = False

    async def _load_cache(self) -> None:
        if self._loaded:
            return
        if not self.cache_file.exists():
            self._cache_data = {}
            self._loaded = True
            return
        try:
            with open(self.cache_file, "r", encoding="utf-8") as f:
                self._cache_data = json.load(f)
            self._loaded = True
            logger.info(f"[FileCrawlCache] Loaded {len(self._cache_data)} crawl cache entries.")
        except Exception as e:
            logger.error(f"[FileCrawlCache] Failed to load crawl cache: {e}")
            self._cache_data = {}
            self._loaded = True

    async def _save_cache(self) -> None:
        try:
            with open(self.cache_file, "w", encoding="utf-8") as f:
                json.dump(self._cache_data, f, indent=4)
        except Exception as e:
            logger.error(f"[FileCrawlCache] Failed to write crawl cache file: {e}")

    async def get(self, url: str) -> Optional[Dict[str, Any]]:
        if not ai_config.search_cache_enabled:
            return None
        async with self._lock:
            await self._load_cache()
            clean_url = url.strip().lower()
            return self._cache_data.get(clean_url)

    async def set(self, url: str, scraped_page_dict: Dict[str, Any]) -> None:
        if not ai_config.search_cache_enabled:
            return
        async with self._lock:
            await self._load_cache()
            clean_url = url.strip().lower()
            self._cache_data[clean_url] = {
                "url": url,
                "scraped_data": scraped_page_dict,
                "timestamp": datetime.now().isoformat(),
            }
            await self._save_cache()


class FileContactCache:
    """
    Local JSON-file based persistent cache mapping Company Name/NPI -> Enriched Contact Details.
    """

    def __init__(self, cache_dir: Optional[str] = None) -> None:
        self.cache_dir = Path(cache_dir or ai_config.search_cache_directory)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.cache_file = self.cache_dir / "contact_cache.json"
        self._lock = asyncio.Lock()
        self._cache_data: Dict[str, Dict[str, Any]] = {}
        self._loaded = False

    async def _load_cache(self) -> None:
        if self._loaded:
            return
        if not self.cache_file.exists():
            self._cache_data = {}
            self._loaded = True
            return
        try:
            with open(self.cache_file, "r", encoding="utf-8") as f:
                self._cache_data = json.load(f)
            self._loaded = True
            logger.info(f"[FileContactCache] Loaded {len(self._cache_data)} contact cache entries.")
        except Exception as e:
            logger.error(f"[FileContactCache] Failed to load contact cache: {e}")
            self._cache_data = {}
            self._loaded = True

    async def _save_cache(self) -> None:
        try:
            with open(self.cache_file, "w", encoding="utf-8") as f:
                json.dump(self._cache_data, f, indent=4)
        except Exception as e:
            logger.error(f"[FileContactCache] Failed to write contact cache file: {e}")

    async def get(self, key: str) -> Optional[Dict[str, Any]]:
        if not ai_config.search_cache_enabled:
            return None
        async with self._lock:
            await self._load_cache()
            clean_key = key.strip().lower()
            return self._cache_data.get(clean_key)

    async def set(self, key: str, contact_dict: Dict[str, Any]) -> None:
        if not ai_config.search_cache_enabled:
            return
        async with self._lock:
            await self._load_cache()
            clean_key = key.strip().lower()
            self._cache_data[clean_key] = {
                "key": key,
                "contact": contact_dict,
                "timestamp": datetime.now().isoformat(),
            }
            await self._save_cache()
