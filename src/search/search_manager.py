"""
src/search/search_manager.py
=============================
Asynchronous Search Manager.

Orchestrates concurrent resolution of record website batches using semaphores
to enforce limits without overloading providers.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List
from .search_engine import SearchEngine
from .search_result import SearchResolution
from ..config.ai_config import ai_config

logger = logging.getLogger(__name__)


class SearchManager:
    """
    Manages concurrent website discovery operations.
    """

    def __init__(self, search_engine: SearchEngine, max_concurrency: Optional[int] = None) -> None:
        self.engine = search_engine
        self.concurrency = max_concurrency or ai_config.search_concurrency
        self._semaphore = asyncio.Semaphore(self.concurrency)

    async def resolve_record(self, record: Dict[str, Any]) -> Dict[str, Any]:
        """
        Resolve website for a single record dict using concurrency locks.
        
        Args:
            record: Mapped record dictionary from Import Engine.
            
        Returns:
            Dict containing the updated record with discovered website fields.
        """
        # Exporter target field: 'website' -> maps to raw column 'Source Website'
        first = record.get("first_name", "")
        last = record.get("last_name", "")
        company = record.get("company_name", "")

        # Compute query name (doctor name or company name)
        name = ""
        if first or last:
            name = f"{first} {last}".strip()
        else:
            name = company.strip()

        # If no entity name exists, skip
        if not name:
            record["search_resolution"] = {
                "resolved_url": "",
                "confidence_score": 0.0,
                "provider_used": "none",
                "status": "skipped",
                "error_message": "Empty entity name"
            }
            return record

        existing_url = record.get("website", "")
        city = record.get("city", "")
        state = record.get("state", "")
        country = record.get("country", "")

        async with self._semaphore:
            resolution = await self.engine.resolve_website(
                business_name=name,
                existing_website=existing_url,
                city=city,
                state=state,
                country=country
            )

        if resolution.status == "failed":
            raise RuntimeError(
                f"Search API Exhausted: {resolution.error_message}. "
                f"Please verify your Tavily/Bing API keys or plan limits."
            )

        # Update record dictionary fields
        record["website"] = resolution.resolved_url
        record["search_resolution"] = resolution.model_dump()
        return record

    async def resolve_batch(self, batch_records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Concurrently resolve website fields for a batch of records.
        """
        logger.info(f"[SearchManager] Resolving batch of {len(batch_records)} records with concurrency={self.concurrency}")
        
        # Build task list
        tasks = [self.resolve_record(record) for record in batch_records]
        
        # Execute concurrently
        updated_records = await asyncio.gather(*tasks)
        
        logger.info(f"[SearchManager] Batch resolution completed.")
        return updated_records
