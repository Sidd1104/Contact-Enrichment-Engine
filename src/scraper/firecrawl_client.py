"""
src/scraper/firecrawl_client.py
===============================
Asynchronous client for crawling and scraping web pages using the Firecrawl API.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Dict, Optional

import httpx
from .scraper_result import ScrapedPage
from ..config.ai_config import ai_config

logger = logging.getLogger(__name__)


class FirecrawlClient:
    """
    Client for crawling and scraping web pages using the Firecrawl API.
    """

    def __init__(self, api_key: Optional[str] = None) -> None:
        self.api_key = api_key or ai_config.firecrawl_api_key
        self.base_url = "https://api.firecrawl.dev/v1"
        self.client = httpx.AsyncClient(timeout=30.0)

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self.client.aclose()

    async def scrape_page(self, url: str) -> ScrapedPage:
        """
        Scrapes a URL using Firecrawl API.
        """
        if not self.api_key:
            return ScrapedPage(
                url=url,
                status_code=0,
                html="",
                error_message="Firecrawl API key not configured.",
                latency=0.0,
                method="Firecrawl"
            )

        start_time = time.perf_counter()
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "url": url,
            "formats": ["markdown", "html"]
        }

        try:
            logger.info(f"[Firecrawl] Scraping {url}")
            response = await self.client.post(
                f"{self.base_url}/scrape",
                json=payload,
                headers=headers
            )
            latency = time.perf_counter() - start_time

            if response.status_code != 200:
                logger.warning(f"[Firecrawl] Failed with status code {response.status_code}: {response.text}")
                return ScrapedPage(
                    url=url,
                    status_code=response.status_code,
                    html="",
                    error_message=f"Firecrawl error: {response.text[:300]}",
                    latency=latency,
                    method="Firecrawl"
                )

            data = response.json()
            if not data.get("success", False):
                err_msg = data.get("error", "Unknown Firecrawl error")
                logger.warning(f"[Firecrawl] API reported failure: {err_msg}")
                return ScrapedPage(
                    url=url,
                    status_code=400,
                    html="",
                    error_message=err_msg,
                    latency=latency,
                    method="Firecrawl"
                )

            page_data = data.get("data", {})
            # Return the cleaned HTML from Firecrawl
            html_content = page_data.get("html", "")
            # If html is missing, fallback to wrapping markdown in html
            if not html_content:
                markdown = page_data.get("markdown", "")
                html_content = f"<html><body>{markdown}</body></html>"

            return ScrapedPage(
                url=url,
                status_code=200,
                html=html_content,
                headers=response.headers,
                latency=latency,
                method="Firecrawl"
            )

        except Exception as e:
            latency = time.perf_counter() - start_time
            logger.error(f"[Firecrawl] Exception scraping {url}: {e}")
            return ScrapedPage(
                url=url,
                status_code=0,
                html="",
                error_message=str(e),
                latency=latency,
                method="Firecrawl"
            )
