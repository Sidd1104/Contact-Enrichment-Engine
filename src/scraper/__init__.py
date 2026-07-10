"""
src/scraper/
============
Website Acquisition and HTML scraping module.
"""

from __future__ import annotations

from .scraper_result import ScrapedPage
from .http_scraper import HTTPScraper
from .browser_scraper import BrowserScraper
from .html_parser import HTMLParser, ParsedHTML
from .page_discovery import PageDiscovery
from .robots_handler import RobotsHandler
from .scraper_metrics import ScraperMetrics
from .scraper_manager import ScraperManager
from .response_parser import parse_httpx_response, parse_playwright_response

__all__ = [
    "ScrapedPage",
    "HTTPScraper",
    "BrowserScraper",
    "HTMLParser",
    "ParsedHTML",
    "PageDiscovery",
    "RobotsHandler",
    "ScraperMetrics",
    "ScraperManager",
    "parse_httpx_response",
    "parse_playwright_response"
]
