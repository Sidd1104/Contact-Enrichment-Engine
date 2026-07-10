"""
tests/test_ai_enrichment.py
============================
Unit tests for AI enrichment prompting, routing, merging, and metrics (Phase 2F).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.validator.business_profile_validator import BusinessProfile
from src.ai.enrichment_result import AIEnrichmentResult, AIEnrichmentResponseModel
from src.ai.enrichment_prompts import EnrichmentPrompts
from src.ai.merge_engine import MergeEngine
from src.ai.ai_metrics import AIMetrics
from src.ai.enrichment_manager import AIEnrichmentManager


# =============================================================================
# Test: EnrichmentPrompts
# =============================================================================

def test_enrichment_prompts():
    prompt = EnrichmentPrompts.get_enrichment_prompt(
        business_name="Green Clinic",
        website_url="https://greenclinic.com",
        crawled_text="We are located in Seattle. Call 206-555-1234."
    )
    
    assert "Green Clinic" in prompt
    assert "https://greenclinic.com" in prompt
    assert "206-555-1234" in prompt


# =============================================================================
# Test: MergeEngine
# =============================================================================

def test_merge_engine_priority_rules():
    # 1. Scraper profile (missing phone)
    scraper_p = BusinessProfile(
        business_name="Green Clinic",
        official_website="https://greenclinic.com",
        emails=["info@greenclinic.com"],
        phones=[],
        confidence=0.6,
        provenance={"emails": "scraper"}
    )
    
    # AI enrichment results (contains phone and a duplicate email)
    ai_res = AIEnrichmentResult(
        official_email="info@greenclinic.com", # duplicate, should not overwrite
        official_phone="(206) 555-0199",
        reasoning="Found on contacts header.",
        confidence=0.85
    )

    merged = MergeEngine.merge(scraper_p, ai_res)

    # Emails should keep scraper provenance
    assert merged.emails == ["info@greenclinic.com"]
    assert merged.provenance["emails"] == "scraper"

    # Phone should be added with AI provenance
    assert "+12065550199" in merged.phones
    assert merged.provenance["phones"] == "AI"
    assert merged.extraction_method == "Merged"
    assert merged.confidence == 0.85


# =============================================================================
# Test: AIMetrics
# =============================================================================

def test_ai_metrics_saving():
    with TemporaryDirectory() as temp_dir:
        metrics_file = Path(temp_dir) / "ai_metrics.json"
        
        metrics = AIMetrics(str(metrics_file))
        metrics.record_ai_call(latency=1.2, prompt_tok=100, cand_tok=50)
        metrics.record_ai_avoided()
        metrics.record_confidence_improvement()
        metrics.save()

        assert metrics_file.exists()
        with open(metrics_file, "r") as f:
            data = json.load(f)

        assert data["counts"]["ai_calls"] == 1
        assert data["counts"]["ai_avoided"] == 1
        assert data["counts"]["confidence_improvements"] == 1
        assert data["tokens"]["total_tokens"] == 150
        assert data["performance"]["average_enrichment_time_seconds"] == 1.2


# =============================================================================
# Test: AIEnrichmentManager Flow (Mocked Router)
# =============================================================================

@pytest.mark.asyncio
async def test_enrichment_manager_flow():
    with TemporaryDirectory() as temp_dir:
        metrics_file = Path(temp_dir) / "ai_metrics.json"
        
        # Scraper profile
        scraper_p = BusinessProfile(
            business_name="Blue Clinic",
            official_website="https://blueclinic.com",
            emails=["info@blueclinic.com"],
            phones=[],
            confidence=0.6,
            provenance={"emails": "scraper"}
        )

        ai_response_obj = AIEnrichmentResponseModel(
            enrichment=AIEnrichmentResult(
                official_email="",
                official_phone="206-555-0199",
                reasoning="Found on footer.",
                confidence=0.8
            )
        )

        # Setup mock router return value
        mock_router_instance = MagicMock()
        mock_router_instance.query_structured = AsyncMock(return_value=ai_response_obj)
        mock_router_instance.stop = AsyncMock()

        with patch("src.ai.enrichment_router.AIRouter", return_value=mock_router_instance):
            manager = AIEnrichmentManager(metrics_file=str(metrics_file))
            
            # Enrich profile
            enriched = await manager.enrich_profile(scraper_p, "Blue clinic details...")
            
            # Assert E2E flow
            assert "+12065550199" in enriched.phones
            assert enriched.extraction_method == "Merged"
            assert enriched.confidence >= 0.8
            
            # Assert metrics recorded
            assert metrics_file.exists()
            with open(metrics_file, "r") as f:
                data = json.load(f)
            assert data["counts"]["ai_calls"] == 1

            await manager.close()
