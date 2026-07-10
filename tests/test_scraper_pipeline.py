"""
tests/test_scraper_pipeline.py
===============================
Unit tests for the Website Acquisition, Scraping & Contact Extraction Pipeline.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import httpx

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.scraper.scraper_result import ScrapedPage
from src.scraper.robots_handler import RobotsHandler
from src.scraper.response_parser import parse_httpx_response, parse_playwright_response
from src.scraper.http_scraper import HTTPScraper
from src.scraper.browser_scraper import BrowserScraper
from src.scraper.html_parser import HTMLParser, ParsedHTML
from src.scraper.page_discovery import PageDiscovery
from src.scraper.scraper_metrics import ScraperMetrics
from src.scraper.scraper_manager import ScraperManager

from src.extractor.structured_contact import StructuredContact
from src.extractor.contact_page_detector import ContactPageDetector
from src.extractor.email_extractor import EmailExtractor
from src.extractor.phone_extractor import PhoneExtractor
from src.extractor.social_extractor import SocialExtractor
from src.extractor.confidence_engine import ConfidenceEngine


# =============================================================================
# Test: HTMLParser
# =============================================================================

def test_html_parser_extraction():
    html_content = """
    <html>
        <head>
            <title>My Cool Business - Home</title>
            <meta name="description" content="This is the description of my awesome business.">
            <script type="application/ld+json">
            {
                "@context": "https://schema.org",
                "@type": "MedicalBusiness",
                "name": "Super Clinic",
                "telephone": "555-444-3333",
                "email": "office@superclinic.com"
            }
            </script>
        </head>
        <body>
            <header>Welcome to Super Clinic</header>
            <main>
                <p>For support, email us at <a href="mailto:support@superclinic.com">support@superclinic.com</a> or call <a href="tel:+15554443333">+1 (555) 444-3333</a>.</p>
                <p>Or find us on <a href="https://www.linkedin.com/company/super-clinic">LinkedIn</a> or <a href="https://facebook.com/super-clinic">Facebook</a>.</p>
                <p>This is some general visible page body text.</p>
            </main>
            <footer>
                <p>&copy; 2026 Super Clinic. Contact: info@superclinic.com.</p>
            </footer>
        </body>
    </html>
    """
    
    parsed = HTMLParser.parse(html_content, "https://superclinic.com")
    
    assert parsed.title == "My Cool Business - Home"
    assert parsed.meta_description == "This is the description of my awesome business."
    assert "support@superclinic.com" in parsed.mailto_links
    assert "+15554443333" in parsed.tel_links or "5554443333" in parsed.tel_links or "+1 (555) 444-3333" in parsed.tel_links or "tel:+15554443333" in parsed.tel_links or "+15554443333" in [t.replace("tel:", "") for t in parsed.tel_links]
    
    # Check footers and structured data
    assert "info@superclinic.com" in parsed.footer_text
    assert len(parsed.json_ld) == 1
    assert parsed.json_ld[0]["name"] == "Super Clinic"
    assert "visible_text" in ParsedHTML.model_fields
    assert "general visible page body text" in parsed.visible_text



# =============================================================================
# Test: ContactPageDetector
# =============================================================================

def test_contact_page_detector_scoring():
    base = "https://superclinic.com"
    
    # Excellent contact indicators
    assert ContactPageDetector.evaluate_link("https://superclinic.com/contact-us", "Contact Us Today", base) == 1.0
    assert ContactPageDetector.evaluate_link("https://superclinic.com/about", "Meet the Team", base) == 0.9
    
    # Normal internal link
    score_blog = ContactPageDetector.evaluate_link("https://superclinic.com/blog/article-1", "Our latest blog post", base)
    assert score_blog < 0.2
    
    # Ignore patterns (external socials or downloads)
    assert ContactPageDetector.evaluate_link("https://facebook.com/super-clinic", "Facebook", base) == 0.0
    assert ContactPageDetector.evaluate_link("https://superclinic.com/docs/manual.pdf", "PDF Manual", base) == 0.0


# =============================================================================
# Test: PageDiscovery
# =============================================================================

def test_page_discovery_ranking():
    parsed = ParsedHTML(
        all_links=[
            {"url": "https://superclinic.com/contact-us", "text": "Contact"},
            {"url": "https://superclinic.com/services", "text": "Our Services"},
            {"url": "https://superclinic.com/about-us", "text": "About Us"},
            {"url": "https://facebook.com/superclinic", "text": "Facebook"},
        ]
    )
    
    discovery = PageDiscovery(max_candidates=3)
    candidates = discovery.discover_pages(parsed, "https://superclinic.com")
    
    # Must rank contact / about first
    urls = [url for url, score in candidates]
    assert "https://superclinic.com/contact-us" in urls
    assert "https://superclinic.com/about-us" in urls
    assert "https://facebook.com/superclinic" not in urls


# =============================================================================
# Test: Extractors (Email, Phone, Social)
# =============================================================================

def test_email_extractor_obfuscation():
    text = "Please reach out to support [at] company [dot] org or test(at)company.com or normal@company.com"
    mailto = ["info@company.com"]
    
    results = EmailExtractor.extract(text, mailto)
    
    assert "info@company.com" in results
    assert results["info@company.com"] == 1.0  # mailto score
    
    assert "normal@company.com" in results
    assert results["normal@company.com"] == 0.9
    
    assert "support@company.org" in results
    assert results["support@company.org"] == 0.7  # deobfuscated
    
    assert "test@company.com" in results
    assert results["test@company.com"] == 0.7


def test_phone_extractor_normalization():
    text = "Call us at (212) 456-7890 or +1-800-275-8777"
    tel = ["tel:+12124567891"]
    
    results = PhoneExtractor.extract(text, tel)
    
    # Normalizes to E.164
    assert "+12124567891" in results
    assert results["+12124567891"] == 1.0
    
    assert "+12124567890" in results
    assert results["+12124567890"] == 0.85


def test_social_extractor():
    links = [
        {"url": "https://linkedin.com/company/my-business", "text": "LinkedIn"},
        {"url": "https://facebook.com/my-business", "text": "Facebook"},
        {"url": "https://twitter.com/share?url=abc", "text": "Share X"},  # share link, ignore
        {"url": "https://x.com/my_business", "text": "X Profile"},
    ]
    
    socials = SocialExtractor.extract(links)
    
    assert socials["linkedin"] == "https://linkedin.com/company/my-business"
    assert socials["facebook"] == "https://facebook.com/my-business"
    assert socials["twitter"] == "https://x.com/my_business"


# =============================================================================
# Test: ConfidenceEngine
# =============================================================================

def test_confidence_engine():
    website = "https://mybiz.com"
    
    # High confidence cases
    conf_email_high = ConfidenceEngine.compute_email_confidence(
        email="info@mybiz.com",
        page_url="https://mybiz.com/contact-us",
        is_mailto=True,
        is_in_footer=True,
        website_url=website
    )
    assert conf_email_high >= 0.95

    # Low confidence cases (domain mismatch, no mailto)
    conf_email_low = ConfidenceEngine.compute_email_confidence(
        email="info@otherbiz.com",
        page_url="https://mybiz.com/blog/article",
        is_mailto=False,
        is_in_footer=False,
        website_url=website
    )
    assert conf_email_low < 0.70


# =============================================================================
# Test: RobotsHandler (Asynchronous)
# =============================================================================

@pytest.mark.asyncio
async def test_robots_handler():
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.text = """
    User-agent: *
    Disallow: /admin/
    Disallow: /private/
    """
    
    mock_client = AsyncMock()
    mock_client.get.return_value = mock_response

    handler = RobotsHandler(client=mock_client)
    
    # Check allowed paths
    allowed = await handler.is_allowed("https://testclinic.com/contact")
    assert allowed is True
    
    # Check blocked path
    blocked = await handler.is_allowed("https://testclinic.com/admin/settings")
    assert blocked is False
    
    # Verify cache works (only 1 get request made)
    await handler.is_allowed("https://testclinic.com/private/data")
    assert mock_client.get.call_count == 1


# =============================================================================
# Test: HTTPScraper (Asynchronous & Retry Logics)
# =============================================================================

@pytest.mark.asyncio
async def test_http_scraper_retry_success():
    scraper = HTTPScraper(retries=2, backoff_factor=0.01)
    
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.text = "<html>Success!</html>"
    mock_response.url = httpx.URL("https://retrybiz.com")
    mock_response.headers = httpx.Headers({"content-type": "text/html"})

    # First attempt fails with status 503, second attempt succeeds with 200
    side_effects = [
        httpx.HTTPStatusError("Service Unavailable", request=MagicMock(), response=MagicMock(status_code=503)),
        mock_response
    ]
    
    with patch.object(scraper.client, "get", side_effect=side_effects) as mock_get:
        res = await scraper.scrape_page("https://retrybiz.com")
        assert res.status_code == 200
        assert res.html == "<html>Success!</html>"
        assert mock_get.call_count == 2
        
    await scraper.close()


# =============================================================================
# Test: ScraperMetrics
# =============================================================================

def test_scraper_metrics_logging():
    with TemporaryDirectory() as temp_dir:
        metrics_file = Path(temp_dir) / "metrics.json"
        
        metrics = ScraperMetrics(str(metrics_file))
        metrics.increment_http_success()
        metrics.increment_http_success()
        metrics.increment_http_fail()
        metrics.increment_browser_launches()
        metrics.increment_pages_crawled(4)
        metrics.add_extracted_counts(10, 5)
        metrics.record_session(5.5)
        
        metrics.save()
        assert metrics_file.exists()
        
        with open(metrics_file, "r") as f:
            data = json.load(f)
            
        assert data["counts"]["http_success"] == 2
        assert data["counts"]["http_fail"] == 1
        assert data["counts"]["browser_launches"] == 1
        assert data["counts"]["pages_crawled"] == 4
        assert data["counts"]["emails_extracted"] == 10
        assert data["counts"]["phones_extracted"] == 5
        assert data["performance"]["sessions_count"] == 1
        assert abs(data["rates"]["http_success_rate"] - (2.0 / 3.0)) < 0.001


# =============================================================================
# Test: ScraperManager Orchestration
# =============================================================================

@pytest.mark.asyncio
async def test_scraper_manager_http_only_flow():
    # Setup mock homepage response with contact links and email/phone on homepage
    mock_res = ScrapedPage(
        url="https://mockclinic.com",
        status_code=200,
        html="""
        <html>
            <title>Mock Clinic</title>
            <body>
                <p>Welcome! Email us at info@mockclinic.com or call 212-456-7890.</p>
                <a href="/contact">Contact Info</a>
            </body>
        </html>
        """,
        headers={},
        latency=0.1,
        method="HTTP"
    )

    manager = ScraperManager(strict_robots=False)
    
    # Mock out HTTP scraper to return the mock homepage response
    with patch.object(manager.http_scraper, "scrape_page", return_value=mock_res):
        contact = await manager.scrape_website("https://mockclinic.com")
        
        assert contact.official_website == "https://mockclinic.com"
        assert "info@mockclinic.com" in contact.emails
        assert "+12124567890" in contact.phones
        assert contact.extraction_method == "HTTP"
        assert contact.confidence > 0.6
        
    await manager.close()


@pytest.mark.asyncio
async def test_scraper_manager_browser_fallback_flow():
    # HTTP scraper fails (returns status 0 / network error)
    mock_http_fail = ScrapedPage(
        url="https://failbiz.com",
        status_code=0,
        html="",
        headers={},
        error_message="Connection timed out",
        latency=1.0,
        method="HTTP"
    )

    # Browser scraper succeeds
    mock_browser_success = ScrapedPage(
        url="https://failbiz.com",
        status_code=200,
        html="""
        <html>
            <title>JS Rendered Biz</title>
            <body>
                <p>Find us at contact@failbiz.com or +1 212-999-8888</p>
            </body>
        </html>
        """,
        headers={},
        latency=0.5,
        method="Browser"
    )

    manager = ScraperManager(strict_robots=False, headless_browser=True)
    
    # Patch manager's helper components
    with patch.object(manager.http_scraper, "scrape_page", return_value=mock_http_fail), \
         patch.object(manager.browser_scraper, "start", return_value=None), \
         patch.object(manager.browser_scraper, "scrape_page", return_value=mock_browser_success):
        
        contact = await manager.scrape_website("https://failbiz.com")
        
        assert contact.official_website == "https://failbiz.com"
        assert "contact@failbiz.com" in contact.emails
        assert "+12129998888" in contact.phones
        assert contact.extraction_method == "Browser"
        assert len(contact.errors) == 1
        assert "HTTP homepage failed" in contact.errors[0]

    await manager.close()
