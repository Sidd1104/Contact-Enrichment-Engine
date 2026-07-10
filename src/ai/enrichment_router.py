"""
src/ai/enrichment_router.py
============================
Integrates and manages the AI Router layer for structured contact enrichment queries.
"""

from __future__ import annotations

import logging
from typing import Type
from pydantic import BaseModel

from .router import AIRouter
from .providers.gemini import GeminiProvider
from .enrichment_result import AIEnrichmentResponseModel, AIEnrichmentResult

logger = logging.getLogger(__name__)


class AIEnrichmentRouter:
    """
    Manages client-reused AI Router queries, ensuring Gemini providers are not recreated.
    """

    def __init__(self) -> None:
        self.router = AIRouter()
        self.provider = GeminiProvider()
        self.router.register_provider(self.provider)
        
        # Start health loops if background checking is desired
        self.router.start_health_checks()

    async def close(self) -> None:
        """Closes router provider connections."""
        await self.router.stop()

    async def query_enrichment(self, prompt: str) -> AIEnrichmentResult:
        """
        Executes a structured query against Gemini to return verified contact details.
        """
        try:
            # Reuses the underlying router structured routing queries
            response: AIEnrichmentResponseModel = await self.router.query_structured(
                prompt=prompt,
                response_model=AIEnrichmentResponseModel
            )
            return response.enrichment
        except Exception as e:
            logger.error(f"[EnrichmentRouter] Structured query failed: {e}")
            raise
