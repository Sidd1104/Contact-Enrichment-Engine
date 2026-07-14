"""
src/ai/enrichment_manager.py
==============================
Manager coordinating prompt builds, router queries, merge operations, and metrics logging.
"""

from __future__ import annotations

import logging
import time
from typing import Dict, Any

from .enrichment_router import AIEnrichmentRouter
from .enrichment_prompts import EnrichmentPrompts
from .merge_engine import MergeEngine
from .ai_metrics import AIMetrics
from ..validator.business_profile_validator import BusinessProfile
from ..validator.confidence_validator import ConfidenceValidator

logger = logging.getLogger(__name__)


class AIEnrichmentManager:
    """
    Main manager for AI enrichment logic. Builds prompts, queries Gemini structured models,
    merges data back into profiles, and updates metrics logs.
    """

    def __init__(self, metrics_file: str = "logs/ai_metrics.json") -> None:
        self.router = AIEnrichmentRouter()
        self.metrics = AIMetrics(metrics_file)

    async def close(self) -> None:
        """Gracefully release router resources."""
        await self.router.close()

    async def __aenter__(self) -> AIEnrichmentManager:
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        await self.close()

    def record_ai_avoided(self) -> None:
        """Call this to record a skipped AI query."""
        self.metrics.record_ai_avoided()
        self.metrics.save()

    async def enrich_profile(self, profile: BusinessProfile, website_text: str = "") -> BusinessProfile:
        """
        Queries Google Gemini structured output to extract missing details,
        merges AI fields with scraper data, and recomputes the final confidence.
        """
        logger.info(f"[Enrichment] Requesting AI fallback details for: {profile.business_name}")
        start_time = time.perf_counter()

        # 1. Build prompt
        prompt = EnrichmentPrompts.get_enrichment_prompt(
            business_name=profile.business_name,
            website_url=profile.official_website,
            crawled_text=website_text
        )

        use_search = False
        cleaned_text = website_text.strip().lower()
        if not cleaned_text or cleaned_text in ("clinic web text...", "[no text successfully crawled from website]"):
            use_search = True
            logger.info(f"[Enrichment] Empty or placeholder website text detected. Enabling Google Search Grounding fallback for '{profile.business_name}'.")

        try:
            # 2. Query Gemini structured output
            ai_result = await self.router.query_enrichment(prompt, use_search_grounding=use_search)
            latency = time.perf_counter() - start_time
            
            # Simple mock token tracker (Gemini doesn't always expose token usage in response metadata)
            # We estimate 1 token per 4 characters in the prompt/response if metadata is missing
            prompt_tok = len(prompt) // 4
            cand_tok = 150 # estimated response length tokens
            
            # Record AI call metrics
            self.metrics.record_ai_call(latency, prompt_tok, cand_tok)
            logger.info(f"[Enrichment] AI responded in {latency:.2f}s (Self-assessed confidence={ai_result.confidence})")

            # 3. Merge outputs
            orig_confidence = profile.confidence
            merged_profile = MergeEngine.merge(profile, ai_result)

            # 4. Recompute final confidence score
            has_contact_page = any("contact" in p.lower() or "about" in p.lower() for p in merged_profile.pages_visited)
            has_footer = "footer" in "".join(merged_profile.errors).lower()
            
            final_conf = ConfidenceValidator.calculate(
                profile=merged_profile,
                has_contact_page=has_contact_page,
                has_footer=has_footer
            )
            merged_profile.confidence = final_conf

            # Record confidence improvements
            if final_conf > orig_confidence:
                self.metrics.record_confidence_improvement()
                logger.info(f"[Enrichment] Profile confidence improved from {orig_confidence} to {final_conf}")

            self.metrics.save()
            return merged_profile

        except Exception as e:
            latency = time.perf_counter() - start_time
            logger.error(f"[Enrichment] Failed to enrich profile: {e}")
            profile.errors.append(f"AI Enrichment Error: {e}")
            self.metrics.save()
            return profile
