import sys
from pathlib import Path
import pytest
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.search.search_provider import GeminiSearchProvider
from src.ai.providers.gemini import GeminiProvider
from src.ai.base.provider import AIResponse


@pytest.mark.asyncio
async def test_gemini_search_provider_success():
    """Verify GeminiSearchProvider correctly extracts website from text and grounding metadata."""
    provider = GeminiSearchProvider(api_key="test_key")
    
    mock_response = AIResponse(
        text="https://www.example.com",
        provider_name="gemini",
        model="gemini-flash",
        latency=0.5,
        retry_count=0,
        metadata={"grounding_urls": ["https://www.example.com"]}
    )
    
    with patch.object(provider.provider, "query_with_search", return_value=mock_response) as mock_query:
        results = await provider.search("Example Company")
        assert len(results) == 1
        assert results[0][0] == "https://www.example.com"
        assert "Example Company" in results[0][1]
        mock_query.assert_called_once()


@pytest.mark.asyncio
async def test_gemini_search_provider_fallback_to_metadata():
    """Verify GeminiSearchProvider falls back to metadata URLs if text response does not contain http link."""
    provider = GeminiSearchProvider(api_key="test_key")
    
    mock_response = AIResponse(
        text="I searched for Example Company and found their official link below.",
        provider_name="gemini",
        model="gemini-flash",
        latency=0.5,
        retry_count=0,
        metadata={"grounding_urls": ["https://www.example-fallback.com", "https://other.com"]}
    )
    
    with patch.object(provider.provider, "query_with_search", return_value=mock_response):
        results = await provider.search("Example Company")
        assert len(results) == 1
        assert results[0][0] == "https://www.example-fallback.com"
