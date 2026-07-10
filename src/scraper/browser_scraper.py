"""
src/scraper/browser_scraper.py
===============================
Asynchronous browser scraper using Playwright as a high-fidelity fallback.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Dict, Optional
from playwright.async_api import async_playwright, Browser, BrowserContext, Page
from .scraper_result import ScrapedPage
from .response_parser import parse_playwright_response

logger = logging.getLogger(__name__)


class BrowserScraper:
    """
    Playwright-based browser scraper that handles Javascript rendering and anti-scraping systems.
    Reuses the browser instance to minimize startup latency and resources.
    """

    def __init__(
        self,
        concurrency_limit: int = 5,
        timeout_ms: int = 20000,
        headless: bool = True,
    ) -> None:
        self.concurrency_limit = concurrency_limit
        self.timeout_ms = timeout_ms
        self.headless = headless
        
        self._semaphore = asyncio.Semaphore(concurrency_limit)
        self._playwright = None
        self._browser: Optional[Browser] = None
        self._launches_count = 0

    async def start(self) -> None:
        """Start the Playwright browser instance."""
        if not self._browser:
            logger.info("[Browser] Launching headless browser...")
            self._playwright = await async_playwright().start()
            self._browser = await self._playwright.chromium.launch(
                headless=self.headless,
                args=["--disable-gpu", "--no-sandbox", "--disable-dev-shm-usage"]
            )
            self._launches_count += 1
            logger.info("[Browser] Headless browser launched.")

    async def close(self) -> None:
        """Close the browser and stop Playwright."""
        if self._browser:
            logger.info("[Browser] Closing headless browser...")
            await self._browser.close()
            self._browser = None
        if self._playwright:
            await self._playwright.stop()
            self._playwright = None
        logger.info("[Browser] Browser scraper stopped.")

    async def __aenter__(self) -> BrowserScraper:
        await self.start()
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        await self.close()

    @property
    def launches_count(self) -> int:
        """Return total browser launches."""
        return self._launches_count

    async def scrape_page(self, url: str) -> ScrapedPage:
        """
        Scrapes a single URL asynchronously using Playwright browser.
        Handles dynamic JS rendering and uses page response parsing.
        """
        # Ensure browser is started
        if not self._browser:
            await self.start()

        async with self._semaphore:
            start_time = time.perf_counter()
            context: Optional[BrowserContext] = None
            page: Optional[Page] = None
            
            try:
                logger.info(f"[Browser] Ingesting {url} via Playwright")
                context = await self._browser.new_context(
                    viewport={"width": 1280, "height": 800},
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                               "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                )
                page = await context.new_page()
                
                # Navigate to the URL
                response = await page.goto(url, timeout=self.timeout_ms, wait_until="load")
                
                # Allow a short extra wait for async dynamic JS requests to resolve
                try:
                    await page.wait_for_load_state("networkidle", timeout=3000)
                except asyncio.TimeoutError:
                    # networkidle timeout is acceptable, parse whatever loaded
                    pass

                # Get response properties
                status_code = response.status if response else 200
                headers = await response.all_headers() if response else {}
                html = await page.content()
                latency = time.perf_counter() - start_time
                
                logger.info(f"[Browser] Succeeded ingesting {url} (Status: {status_code})")
                return parse_playwright_response(url, status_code, html, headers, latency)

            except Exception as e:
                latency = time.perf_counter() - start_time
                error_msg = str(e)
                logger.warning(f"[Browser] Failed to scrape {url}: {error_msg}")
                return ScrapedPage(
                    url=url,
                    status_code=0,
                    html="",
                    headers={},
                    error_message=f"Browser error: {error_msg}",
                    latency=latency,
                    method="Browser"
                )
            finally:
                # Cleanup contexts and pages
                if page:
                    try:
                        await page.close()
                    except Exception:
                        pass
                if context:
                    try:
                        await context.close()
                    except Exception:
                        pass
