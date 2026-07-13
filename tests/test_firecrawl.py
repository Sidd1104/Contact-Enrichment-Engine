import sys
from pathlib import Path
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.scraper.firecrawl_client import FirecrawlClient
from src.scraper.scraper_result import ScrapedPage
from src.scraper.scraper_manager import ScraperManager


@pytest.mark.asyncio
async def test_firecrawl_client_success():
    """Verify FirecrawlClient parses scrape response data correctly."""
    client = FirecrawlClient(api_key="test_fc_key")
    
    mock_res_data = {
        "success": True,
        "data": {
            "markdown": "# Welcome\nScrape content.",
            "html": "<html><body><h1>Welcome</h1><p>Scrape content.</p></body></html>"
        }
    }
    
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = mock_res_data
    mock_response.headers = httpx.Headers({})
    
    with patch.object(client.client, "post", return_value=mock_response):
        scraped = await client.scrape_page("https://example.com")
        assert scraped.status_code == 200
        assert "Scrape content" in scraped.html
        assert scraped.method == "Firecrawl"
        
    await client.close()


@pytest.mark.asyncio
async def test_firecrawl_client_fallback_to_markdown():
    """Verify FirecrawlClient wraps markdown in html if raw html is missing from response."""
    client = FirecrawlClient(api_key="test_fc_key")
    
    mock_res_data = {
        "success": True,
        "data": {
            "markdown": "Just raw markdown"
        }
    }
    
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = mock_res_data
    mock_response.headers = httpx.Headers({})
    
    with patch.object(client.client, "post", return_value=mock_response):
        scraped = await client.scrape_page("https://example.com")
        assert scraped.status_code == 200
        assert "<html><body>Just raw markdown</body></html>" in scraped.html
        
    await client.close()
